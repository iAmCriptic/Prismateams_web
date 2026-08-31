"""File Converter module: upload → choose format/size → async convert → download."""

import json
import logging
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app import db, limiter
from app.models.file_converter import ConversionJob
from app.utils.access_control import check_module_access
from app.utils.file_converter import (
    delete_job_files,
    get_job_dir,
    get_retention_timedelta,
    get_upload_dir,
    parse_options_json,
    run_conversion,
)
from app.utils.file_converter_catalog import (
    PAGE_SIZES,
    analyze_upload,
    find_option,
    get_available_engines,
    options_to_dict,
)
from app.utils.file_storage_limits import get_global_max_file_size
from app.utils.i18n import translate

logger = logging.getLogger(__name__)

file_converter_bp = Blueprint('file_converter', __name__, url_prefix='/file-converter')

_queue_lock = threading.Lock()
_user_active_jobs = defaultdict(int)

ACTIVE_STATUSES = ('pending', 'processing')
ALLOWED_UPLOAD_EXTS = frozenset({
    'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'opus', 'wma',
    'jpg', 'jpeg', 'png', 'webp', 'bmp', 'tiff', 'tif', 'gif',
    'pdf',
    'docx', 'doc', 'odt', 'rtf',
    'xlsx', 'xls', 'ods', 'csv',
    'pptx', 'ppt', 'odp',
})


def _job_language(job):
    try:
        user = getattr(job, 'user', None)
        lang = getattr(user, 'language', None) if user else None
        if lang:
            return lang
    except Exception:
        pass
    return None


def _pack_error(error_key, text):
    if error_key:
        return f'[{error_key}] {text}'
    return text


def _unpack_error(message):
    if not message:
        return None, None
    text = str(message)
    if text.startswith('[') and ']' in text[:64]:
        key, _, rest = text[1:].partition(']')
        return key.strip(), rest.lstrip(' ') or text
    return None, text


def _error_message_for_key(error_key, lang=None):
    key_map = {
        'unsupported_type': 'file_converter.flash.unsupported_type',
        'ffmpeg_missing': 'file_converter.flash.ffmpeg_missing',
        'libreoffice_missing': 'file_converter.flash.libreoffice_missing',
        'pillow_missing': 'file_converter.flash.pillow_missing',
        'pypdf_missing': 'file_converter.flash.pypdf_missing',
        'no_options': 'file_converter.flash.no_options',
        'file_missing': 'file_converter.flash.file_missing',
        'file_too_large': 'file_converter.flash.file_too_large',
        'invalid_option': 'file_converter.flash.invalid_option',
        'invalid_format': 'file_converter.flash.invalid_format',
        'invalid_resize': 'file_converter.flash.invalid_resize',
        'invalid_page_size': 'file_converter.flash.invalid_page_size',
        'too_many_jobs': 'file_converter.flash.too_many_jobs',
        'err_convert_failed': 'file_converter.flash.err_convert_failed',
        'output_not_found': 'file_converter.flash.output_not_found',
        'timeout': 'file_converter.flash.timeout',
        'upload_failed': 'file_converter.flash.upload_failed',
    }
    i18n_key = key_map.get(error_key, 'file_converter.flash.err_convert_failed')
    return translate(i18n_key, language=lang)


def _active_job_count(user_id):
    return ConversionJob.query.filter(
        ConversionJob.user_id == user_id,
        ConversionJob.status.in_(ACTIVE_STATUSES),
    ).count()


def _get_max_concurrent(app):
    max_concurrent = app.config.get('FILE_CONVERTER_MAX_CONCURRENT', 2)
    return max(1, int(max_concurrent))


def _purge_job(job):
    if not job:
        return
    try:
        delete_job_files(job)
    except Exception:
        logger.debug('Could not delete files for conversion job %s', getattr(job, 'id', None), exc_info=True)
    db.session.delete(job)


def _serialize_job(job):
    error_key, error_message = _unpack_error(job.error_message)
    options = parse_options_json(job.options_json)
    return {
        'id': job.id,
        'status': job.status,
        'source_filename': job.source_filename,
        'source_category': job.source_category,
        'source_format': job.source_format,
        'target_format': job.target_format,
        'options': options,
        'output_filename': job.output_filename,
        'file_size': job.file_size,
        'error_message': error_message,
        'error_key': error_key,
        'downloadable': job.is_downloadable(),
        'expires_at': job.expires_at.isoformat() + 'Z' if job.expires_at else None,
        'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
        'completed_at': job.completed_at.isoformat() + 'Z' if job.completed_at else None,
    }


def _process_conversion(app, user_id, job_id):
    try:
        with app.app_context():
            job = ConversionJob.query.get(job_id)
            if not job or job.status != 'processing':
                return

            success, error_key = run_conversion(job)

            job = ConversionJob.query.get(job_id)
            if not job:
                return

            if success:
                job.status = 'completed'
                job.error_message = None
                job.completed_at = datetime.utcnow()
                job.expires_at = datetime.utcnow() + get_retention_timedelta()
            else:
                job.status = 'failed'
                job.completed_at = datetime.utcnow()
                job.expires_at = datetime.utcnow() + get_retention_timedelta()
                msg = _error_message_for_key(error_key or 'err_convert_failed', _job_language(job))
                job.error_message = _pack_error(error_key or 'err_convert_failed', msg)

            db.session.commit()
    except Exception:
        logger.exception('Conversion thread crashed for job %s', job_id)
        try:
            with app.app_context():
                job = ConversionJob.query.get(job_id)
                if job and job.status == 'processing':
                    job.status = 'failed'
                    job.completed_at = datetime.utcnow()
                    job.expires_at = datetime.utcnow() + get_retention_timedelta()
                    msg = _error_message_for_key('err_convert_failed', _job_language(job))
                    job.error_message = _pack_error('err_convert_failed', msg)
                    db.session.commit()
        except Exception:
            logger.exception('Could not mark conversion job %s as failed', job_id)
    finally:
        with _queue_lock:
            _user_active_jobs[user_id] = max(0, _user_active_jobs[user_id] - 1)


def _start_conversion_thread(app, job_id):
    with app.app_context():
        job = ConversionJob.query.get(job_id)
        if not job:
            return
        user_id = job.user_id
        with _queue_lock:
            _user_active_jobs[user_id] += 1
        thread = threading.Thread(
            target=_process_conversion,
            args=(app, user_id, job_id),
            daemon=True,
            name=f'file-convert-{job_id}',
        )
        thread.start()


def _save_upload(file_storage):
    """Save upload to a staging area under upload dir. Returns (path, safe_name, size)."""
    original = secure_filename(file_storage.filename or '') or 'upload.bin'
    if '.' not in original:
        raise ValueError('unsupported_type')

    ext = original.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise ValueError('unsupported_type')

    max_size = get_global_max_file_size()
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError('upload_failed')
    if size > max_size:
        raise ValueError('file_too_large')

    staging = os.path.join(get_upload_dir(), '_staging')
    os.makedirs(staging, exist_ok=True)
    token = uuid.uuid4().hex
    safe_name = f'{token}_{original}'
    path = os.path.join(staging, safe_name)
    file_storage.save(path)
    return path, original, size


@file_converter_bp.route('/')
@login_required
@check_module_access('module_file_converter')
def index():
    jobs = ConversionJob.query.filter_by(user_id=current_user.id).order_by(
        ConversionJob.created_at.desc()
    ).limit(50).all()
    active_jobs_count = sum(1 for job in jobs if job.status in ACTIVE_STATUSES)
    engines = get_available_engines()

    return render_template(
        'file_converter/index.html',
        jobs=jobs,
        active_jobs_count=active_jobs_count,
        engines=engines,
        page_sizes=list(PAGE_SIZES),
        max_file_size=get_global_max_file_size(),
    )


@file_converter_bp.route('/upload', methods=['POST'])
@login_required
@check_module_access('module_file_converter')
@limiter.limit('40 per hour')
def upload():
    file_storage = request.files.get('file')
    if not file_storage or not file_storage.filename:
        return jsonify({
            'error': translate('file_converter.flash.upload_failed'),
            'error_key': 'upload_failed',
        }), 400

    try:
        path, original_name, size = _save_upload(file_storage)
    except ValueError as exc:
        key = str(exc) or 'upload_failed'
        return jsonify({
            'error': _error_message_for_key(key),
            'error_key': key,
        }), 400
    except Exception:
        logger.exception('Upload failed')
        return jsonify({
            'error': translate('file_converter.flash.upload_failed'),
            'error_key': 'upload_failed',
        }), 500

    mime = file_storage.mimetype
    analysis = analyze_upload(path, original_name, mime)
    if analysis.error:
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({
            'error': _error_message_for_key(analysis.error),
            'error_key': analysis.error,
            'engines': analysis.engines,
        }), 400

    # Encode label text for each option for the client
    labeled_options = []
    for opt in options_to_dict(analysis.options):
        labeled = dict(opt)
        labeled['label'] = translate(opt['label_key'])
        labeled_options.append(labeled)

    return jsonify({
        'upload_token': os.path.basename(path),
        'source_filename': original_name,
        'source_format': analysis.source_format,
        'source_category': analysis.category,
        'file_size': size,
        'options': labeled_options,
        'engines': analysis.engines,
    })


@file_converter_bp.route('/convert', methods=['POST'])
@login_required
@check_module_access('module_file_converter')
@limiter.limit('30 per hour')
def convert():
    data = request.get_json(silent=True) or {}
    upload_token = (data.get('upload_token') or '').strip()
    option_id = (data.get('option_id') or '').strip()
    source_category = (data.get('source_category') or '').strip()
    source_format = (data.get('source_format') or '').strip().lower()
    source_filename = (data.get('source_filename') or '').strip()
    extra_params = data.get('params') if isinstance(data.get('params'), dict) else {}

    if not upload_token or '..' in upload_token or '/' in upload_token or '\\' in upload_token:
        return jsonify({
            'error': translate('file_converter.flash.upload_failed'),
            'error_key': 'upload_failed',
        }), 400

    staging_path = os.path.join(get_upload_dir(), '_staging', upload_token)
    if not os.path.isfile(staging_path):
        return jsonify({
            'error': translate('file_converter.flash.file_missing'),
            'error_key': 'file_missing',
        }), 400

    engines = get_available_engines()
    option = find_option(option_id, source_category, source_format, engines)
    if not option:
        return jsonify({
            'error': translate('file_converter.flash.invalid_option'),
            'error_key': 'invalid_option',
        }), 400

    options = dict(option.params or {})
    options['kind'] = option.kind
    options.update({k: v for k, v in extra_params.items() if k in (
        'width', 'height', 'percent', 'keep_aspect', 'page_size', 'dpi', 'mode',
    )})

    # Validate custom resize params
    if option.kind == 'resize' and options.get('mode') == 'custom':
        try:
            w = int(options.get('width') or 0)
            h = int(options.get('height') or 0)
        except (TypeError, ValueError):
            w, h = 0, 0
        if w <= 0 and h <= 0:
            return jsonify({
                'error': translate('file_converter.flash.invalid_resize'),
                'error_key': 'invalid_resize',
            }), 400
        options['width'] = w
        options['height'] = h
    if option.kind == 'resize' and options.get('mode') == 'percent':
        try:
            percent = float(options.get('percent') or 0)
        except (TypeError, ValueError):
            percent = 0
        if percent < 25 or percent > 400:
            return jsonify({
                'error': translate('file_converter.flash.invalid_resize'),
                'error_key': 'invalid_resize',
            }), 400
        options['percent'] = percent

    max_concurrent = _get_max_concurrent(current_app)
    if _active_job_count(current_user.id) >= max_concurrent:
        return jsonify({
            'error': translate('file_converter.flash.too_many_jobs', max=max_concurrent),
            'error_key': 'too_many_jobs',
        }), 429

    job = ConversionJob(
        user_id=current_user.id,
        source_filename=secure_filename(source_filename) or 'upload.bin',
        source_category=source_category,
        source_format=source_format,
        target_format=option.target_format,
        options_json=json.dumps(options),
        status='pending',
        expires_at=datetime.utcnow() + get_retention_timedelta(),
    )
    db.session.add(job)
    db.session.flush()

    job_dir = get_job_dir(job.id)
    dest_src = os.path.join(job_dir, f'source_{job.source_filename}')
    try:
        os.replace(staging_path, dest_src)
    except OSError:
        import shutil
        shutil.copy2(staging_path, dest_src)
        try:
            os.remove(staging_path)
        except OSError:
            pass

    job.source_path = dest_src
    job.status = 'processing'
    db.session.commit()

    app = current_app._get_current_object()
    _start_conversion_thread(app, job.id)

    return jsonify(_serialize_job(job)), 201


@file_converter_bp.route('/status/<int:job_id>')
@login_required
@check_module_access('module_file_converter')
def job_status(job_id):
    job = ConversionJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    return jsonify(_serialize_job(job))


@file_converter_bp.route('/download/<int:job_id>')
@login_required
@check_module_access('module_file_converter')
def download_file(job_id):
    job = ConversionJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    if not job.is_downloadable():
        flash(translate('file_converter.flash.file_missing'), 'warning')
        return redirect(url_for('file_converter.index'))

    path = job.output_path
    if not path or not os.path.isfile(path):
        flash(translate('file_converter.flash.file_missing'), 'warning')
        return redirect(url_for('file_converter.index'))

    return send_file(
        path,
        as_attachment=True,
        download_name=job.output_filename or os.path.basename(path),
    )


@file_converter_bp.route('/jobs/<int:job_id>', methods=['DELETE'])
@login_required
@check_module_access('module_file_converter')
@limiter.limit('60 per hour')
def delete_job(job_id):
    job = ConversionJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    _purge_job(job)
    db.session.commit()
    return jsonify({'success': True})


@file_converter_bp.route('/clear-all', methods=['POST'])
@login_required
@check_module_access('module_file_converter')
@limiter.limit('10 per hour')
def clear_all():
    jobs = ConversionJob.query.filter_by(user_id=current_user.id).all()
    for job in jobs:
        if job.status in ACTIVE_STATUSES:
            continue
        _purge_job(job)
    db.session.commit()
    return jsonify({'success': True})
