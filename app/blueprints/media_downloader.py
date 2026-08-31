import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime
from werkzeug.utils import secure_filename

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, Response, stream_with_context
from flask_login import login_required, current_user

from app import db, limiter
from app.models.media_downloader import MediaDownloadJob
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.media_downloader import (
    is_media_downloader_compatible,
    validate_media_url,
    is_playlist_url,
    normalize_media_url,
    canonicalize_playlist_url,
    parse_time_segment,
    run_convert,
    get_retention_timedelta,
    get_upload_dir,
    get_raw_dir,
    delete_job_file,
    delete_job_raw_dir,
    is_allowed_youtube_proxy_url,
    build_youtube_proxy_request,
    iter_youtube_proxy_response,
    ensure_youtubei_vendor,
    YOUTUBE_PROXY_SKIP_RESPONSE_HEADERS,
)

logger = logging.getLogger(__name__)

media_downloader_bp = Blueprint('media_downloader', __name__, url_prefix='/media-downloader')

_queue_lock = threading.Lock()
_user_active_converts = defaultdict(int)
_cancelled_job_ids = set()
_job_client_progress = {}

ACTIVE_CLIENT_STATUSES = ('downloading', 'uploading')
ACTIVE_SERVER_STATUSES = ('converting',)
ACTIVE_STATUSES = ACTIVE_CLIENT_STATUSES + ACTIVE_SERVER_STATUSES + ('cancelling',)


def _require_downloader():
    if not is_media_downloader_compatible():
        flash(translate('media_downloader.flash.incompatible'), 'warning')
        return False
    return True


def _youtube_search_enabled():
    try:
        from app.utils.music_oauth import get_music_setting

        api_key = get_music_setting('youtube_api_key')
        return bool(api_key and str(api_key).strip())
    except Exception:
        logger.debug('YouTube search availability check failed', exc_info=True)
        return False


def _active_job_count(user_id):
    return MediaDownloadJob.query.filter(
        MediaDownloadJob.user_id == user_id,
        MediaDownloadJob.status.in_(ACTIVE_STATUSES),
    ).count()


def _get_max_concurrent_for_user(app):
    max_concurrent = app.config.get('MEDIA_DOWNLOADER_MAX_CONCURRENT', 2)
    return max(1, int(max_concurrent))


def _mark_job_cancelled(job_id):
    with _queue_lock:
        _cancelled_job_ids.add(job_id)


def _clear_job_cancelled(job_id):
    with _queue_lock:
        _cancelled_job_ids.discard(job_id)
        _job_client_progress.pop(job_id, None)


def _is_job_cancelled(job_id):
    with _queue_lock:
        return job_id in _cancelled_job_ids


def _set_job_progress(job_id, progress):
    with _queue_lock:
        _job_client_progress[job_id] = max(0, min(100, int(progress)))


def _get_job_progress(job_id):
    with _queue_lock:
        return _job_client_progress.get(job_id)


def _purge_job(job):
    if not job:
        return
    try:
        delete_job_file(job)
    except Exception:
        logger.debug('Could not delete media file for job %s', getattr(job, 'id', None), exc_info=True)
    _clear_job_cancelled(job.id)
    db.session.delete(job)


def _force_purge_cancelled_job(app, job_id, delay_seconds=8):
    def _run():
        try:
            time.sleep(max(1, int(delay_seconds)))
            with app.app_context():
                job = MediaDownloadJob.query.get(job_id)
                if not job:
                    return
                if job.status in ('cancelling', 'cancelled') or _is_job_cancelled(job_id):
                    _purge_job(job)
                    db.session.commit()
                    logger.info('Purged cancelled media job %s after timeout', job_id)
        except Exception:
            logger.exception('Failed to purge cancelled media job %s', job_id)
        finally:
            _clear_job_cancelled(job_id)

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name=f'media-cancel-purge-{job_id}',
    )
    thread.start()


def _request_job_cancel(app, job):
    if job.status in ACTIVE_CLIENT_STATUSES:
        _mark_job_cancelled(job.id)
        _purge_job(job)
        return True

    if job.status in ACTIVE_SERVER_STATUSES + ('cancelling',):
        _mark_job_cancelled(job.id)
        job.status = 'cancelling'
        job.error_message = translate(
            'media_downloader.flash.cancelling',
            language=_job_language(job),
        )
        _force_purge_cancelled_job(app, job.id, delay_seconds=8)
        return False

    _purge_job(job)
    return True


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
        key = key.strip()
        rest = rest.lstrip(' ')
        if key.startswith('err_') or key in ('cancelled', 'output_not_found', 'client_download_failed', 'upload_failed'):
            return key, rest or text
    return None, text


def _apply_convert_result(job, success, error_message):
    lang = _job_language(job)

    if success:
        job.status = 'completed'
        job.error_message = None
        _set_job_progress(job.id, 100)
        return 'updated'

    if error_message == 'cancelled':
        _purge_job(job)
        return 'deleted'

    job.status = 'failed'
    key_map = {
        'err_age_restricted': 'media_downloader.flash.err_age_restricted',
        'err_video_unavailable': 'media_downloader.flash.err_video_unavailable',
        'err_convert_failed': 'media_downloader.flash.err_convert_failed',
        'output_not_found': 'media_downloader.flash.file_missing',
        'upload_failed': 'media_downloader.flash.upload_failed',
        'client_download_failed': 'media_downloader.flash.client_download_failed',
    }
    if error_message in key_map:
        job.error_message = _pack_error(
            error_message,
            translate(key_map[error_message], language=lang),
        )
    else:
        job.error_message = error_message

    job.expires_at = datetime.utcnow() + get_retention_timedelta()
    return 'updated'


def _process_convert(app, user_id, job_id):
    try:
        with app.app_context():
            job = MediaDownloadJob.query.get(job_id)
            if not job:
                return

            if job.status != 'converting':
                return

            if _is_job_cancelled(job.id):
                _purge_job(job)
                db.session.commit()
                return

            success, error_message = run_convert(
                job,
                should_cancel=lambda: _is_job_cancelled(job.id),
            )

            job = MediaDownloadJob.query.get(job_id)
            if not job:
                return

            if job.status == 'cancelling' or _is_job_cancelled(job.id):
                error_message = 'cancelled'
                success = False

            _apply_convert_result(job, success, error_message)
            db.session.commit()
    except Exception:
        logger.exception('Media convert thread crashed for job %s', job_id)
        try:
            with app.app_context():
                job = MediaDownloadJob.query.get(job_id)
                if job and job.status in ('converting', 'cancelling'):
                    if _is_job_cancelled(job.id) or job.status == 'cancelling':
                        _purge_job(job)
                    else:
                        job.status = 'failed'
                        job.error_message = _pack_error(
                            'err_convert_failed',
                            translate(
                                'media_downloader.flash.err_convert_failed',
                                language=_job_language(job),
                            ),
                        )
                        job.expires_at = datetime.utcnow() + get_retention_timedelta()
                    db.session.commit()
        except Exception:
            logger.exception('Could not mark media job %s as failed after crash', job_id)
    finally:
        with _queue_lock:
            _user_active_converts[user_id] = max(0, _user_active_converts[user_id] - 1)


def _start_convert_thread(app, job_id):
    with app.app_context():
        job = MediaDownloadJob.query.get(job_id)
        if not job:
            return
        user_id = job.user_id
        with _queue_lock:
            _user_active_converts[user_id] += 1
        thread = threading.Thread(
            target=_process_convert,
            args=(app, user_id, job_id),
            daemon=True,
            name=f'media-convert-{job_id}',
        )
        thread.start()


def _create_job(user_id, source_url, output_format, start_parsed, end_parsed, title=None):
    job = MediaDownloadJob(
        user_id=user_id,
        source_url=source_url,
        format=output_format,
        start_time=start_parsed,
        end_time=end_parsed,
        status='downloading',
        title=(title or '').strip() or None,
        expires_at=datetime.utcnow() + get_retention_timedelta(),
    )
    db.session.add(job)
    db.session.flush()
    _set_job_progress(job.id, 0)
    return job


def _serialize_job_status(job):
    error_key, error_message = _unpack_error(job.error_message)
    progress = _get_job_progress(job.id)
    if progress is None and job.status == 'completed':
        progress = 100
    return {
        'id': job.id,
        'status': job.status,
        'title': job.title,
        'source_url': job.source_url,
        'format': job.format,
        'start_time': job.start_time,
        'end_time': job.end_time,
        'error_message': error_message,
        'error_key': error_key,
        'downloadable': job.is_downloadable(),
        'expires_at': job.expires_at.isoformat() + 'Z' if job.expires_at else None,
        'file_size': job.file_size,
        'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
        'progress': progress,
    }


def _validate_job_payload(data):
    source_url = normalize_media_url(data.get('source_url') or '')
    output_format = (data.get('format') or 'audio').strip().lower()
    start_time = (data.get('start_time') or '').strip()
    end_time = (data.get('end_time') or '').strip()
    title = (data.get('title') or '').strip() or None

    if output_format not in ('audio', 'video'):
        return None, translate('media_downloader.flash.invalid_format'), 'invalid_format'

    is_valid, error_key = validate_media_url(source_url)
    if not is_valid:
        return None, translate(f'media_downloader.flash.{error_key}'), error_key

    if is_playlist_url(source_url):
        return None, translate('media_downloader.flash.not_a_playlist'), 'not_a_playlist'

    start_parsed, end_parsed, segment_error = parse_time_segment(start_time, end_time)
    if segment_error:
        return None, translate(f'media_downloader.flash.{segment_error}'), segment_error

    return {
        'source_url': source_url,
        'format': output_format,
        'start_time': start_parsed,
        'end_time': end_parsed,
        'title': title,
    }, None, None


@media_downloader_bp.route('/')
@login_required
@check_module_access('module_media_downloader')
def index():
    if not _require_downloader():
        return redirect(url_for('dashboard.index'))

    stuck = MediaDownloadJob.query.filter(
        MediaDownloadJob.user_id == current_user.id,
        MediaDownloadJob.status.in_(('cancelling', 'cancelled')),
    ).all()
    if stuck:
        for job in stuck:
            _purge_job(job)
        db.session.commit()

    jobs = MediaDownloadJob.query.filter_by(user_id=current_user.id).order_by(
        MediaDownloadJob.created_at.desc()
    ).limit(50).all()

    active_jobs_count = sum(1 for job in jobs if job.status in ACTIVE_STATUSES)

    return render_template(
        'media_downloader/index.html',
        jobs=jobs,
        active_jobs_count=active_jobs_count,
        youtube_search_enabled=_youtube_search_enabled(),
        pending_playlist_url=canonicalize_playlist_url(
            normalize_media_url(request.args.get('playlist_url', ''))
        ) or normalize_media_url(request.args.get('playlist_url', '')),
    )


@media_downloader_bp.route('/youtube-search', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def youtube_search():
    if not _youtube_search_enabled():
        return jsonify({
            'error': translate('media_downloader.search.unavailable'),
            'results': [],
        }), 403

    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()
    try:
        limit = int(data.get('limit') or 8)
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 15))

    if len(query) < 2:
        return jsonify({'results': []})

    try:
        from app.utils.music_api import get_api_client

        client = get_api_client(user_id=None, provider='youtube', use_client_credentials=True)
        results = client.search(query, limit=limit) or []
        sanitized = []
        for track in results:
            if not isinstance(track, dict) or not track.get('url'):
                continue
            sanitized.append({
                'id': track.get('id'),
                'title': track.get('title') or '',
                'artist': track.get('artist') or '',
                'image_url': track.get('image_url'),
                'url': track.get('url'),
                'provider': 'youtube',
            })
        return jsonify({'results': sanitized})
    except Exception as exc:
        logger.warning('YouTube search failed: %s', exc)
        return jsonify({
            'error': translate('media_downloader.search.error'),
            'results': [],
        }), 502


@media_downloader_bp.route('/vendor/youtubei.js')
@login_required
@check_module_access('module_media_downloader')
def youtubei_vendor():
    """Serve youtubei.js via Flask (nginx /static bypasses Python mimetypes)."""
    try:
        path = ensure_youtubei_vendor(current_app)
        return send_file(path, mimetype='text/javascript', conditional=True)
    except Exception as exc:
        logger.error('youtubei.js vendor unavailable: %s', exc, exc_info=True)
        return Response('// youtubei.js unavailable\n', status=503, mimetype='text/javascript')


@media_downloader_bp.route('/youtube-proxy', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('240 per hour')
def youtube_proxy():
    """
    Same-origin CORS proxy for youtubei.js and googlevideo stream fetches.

    Browser code cannot call YouTube APIs directly; this forwards allowed hosts only.
    """
    import requests

    data = request.get_json(silent=True) or {}
    req_kwargs, error_key = build_youtube_proxy_request(data)
    if error_key:
        if error_key == 'forbidden_host':
            logger.warning('YouTube proxy rejected host: %s', data.get('url'))
        return jsonify({'error': error_key}), 400

    try:
        upstream = requests.request(**req_kwargs)
    except requests.RequestException as exc:
        logger.warning('YouTube proxy request failed: %s', exc)
        return jsonify({'error': 'proxy_failed'}), 502

    if upstream.status_code >= 400:
        logger.warning(
            'YouTube proxy upstream %s %s -> %s',
            req_kwargs.get('method'),
            req_kwargs.get('url'),
            upstream.status_code,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in YOUTUBE_PROXY_SKIP_RESPONSE_HEADERS
    }

    return Response(
        stream_with_context(iter_youtube_proxy_response(upstream)),
        status=upstream.status_code,
        headers=response_headers,
    )


@media_downloader_bp.route('/jobs', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def create_job():
    if not is_media_downloader_compatible():
        return jsonify({'error': translate('media_downloader.flash.incompatible')}), 503

    data = request.get_json(silent=True) or {}
    payload, error, error_key = _validate_job_payload(data)
    if error:
        return jsonify({'error': error, 'error_key': error_key}), 400

    max_concurrent = _get_max_concurrent_for_user(current_app)
    if _active_job_count(current_user.id) >= max_concurrent:
        return jsonify({
            'error': translate('media_downloader.flash.too_many_jobs', max=max_concurrent),
            'error_key': 'too_many_jobs',
        }), 429

    job = _create_job(
        current_user.id,
        payload['source_url'],
        payload['format'],
        payload['start_time'],
        payload['end_time'],
        title=payload['title'],
    )
    db.session.commit()
    get_upload_dir()

    return jsonify(_serialize_job_status(job)), 201


@media_downloader_bp.route('/jobs/<int:job_id>/progress', methods=['PATCH'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('120 per hour')
def update_job_progress(job_id):
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    if job.status not in ACTIVE_CLIENT_STATUSES:
        return jsonify({'error': 'invalid_status'}), 400

    data = request.get_json(silent=True) or {}
    try:
        progress = int(data.get('progress', 0))
    except (TypeError, ValueError):
        progress = 0

    status = (data.get('status') or '').strip().lower()
    if status in ACTIVE_CLIENT_STATUSES:
        job.status = status

    title = (data.get('title') or '').strip()
    if title:
        job.title = title

    _set_job_progress(job_id, progress)
    db.session.commit()
    return jsonify(_serialize_job_status(job))


@media_downloader_bp.route('/jobs/<int:job_id>/upload', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def upload_job_files(job_id):
    if not is_media_downloader_compatible():
        return jsonify({'error': translate('media_downloader.flash.incompatible')}), 503

    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()

    if _is_job_cancelled(job_id):
        _purge_job(job)
        db.session.commit()
        return jsonify({'error': translate('media_downloader.flash.cancelled')}), 410

    if job.status not in ACTIVE_CLIENT_STATUSES + ('downloading',):
        return jsonify({'error': 'invalid_status'}), 400

    title = (request.form.get('title') or '').strip()
    if title:
        job.title = title

    raw_dir = get_raw_dir(job.id)
    delete_job_raw_dir(job.id)
    os.makedirs(raw_dir, exist_ok=True)

    saved = 0
    role_files = [
        ('file', 'muxed'),
        ('muxed', 'muxed'),
        ('video', 'video'),
        ('audio', 'audio'),
    ]

    for field_name, role in role_files:
        upload = request.files.get(field_name)
        if not upload or not upload.filename:
            continue
        ext = secure_filename(upload.filename).rsplit('.', 1)[-1].lower() if '.' in upload.filename else 'bin'
        if ext not in ('mp4', 'webm', 'm4a', 'mp3', 'opus', 'bin'):
            ext = 'bin'
        dest = os.path.join(raw_dir, f'{role}.{ext}')
        upload.save(dest)
        saved += 1

    if saved == 0:
        return jsonify({
            'error': translate('media_downloader.flash.upload_failed'),
            'error_key': 'upload_failed',
        }), 400

    job.status = 'converting'
    _set_job_progress(job.id, 0)
    db.session.commit()

    app = current_app._get_current_object()
    _start_convert_thread(app, job.id)

    return jsonify(_serialize_job_status(job))


@media_downloader_bp.route('/jobs/<int:job_id>/fail', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('60 per hour')
def fail_job(job_id):
    """Mark a client-side download job as failed (browser could not fetch)."""
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    if job.status not in ACTIVE_CLIENT_STATUSES + ('downloading',):
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    error_key = (data.get('error_key') or 'client_download_failed').strip()
    lang = _job_language(job)

    if error_key == 'cancelled':
        _purge_job(job)
        db.session.commit()
        return jsonify({'success': True, 'removed': True})

    key_map = {
        'err_bot_check': 'media_downloader.flash.err_bot_check',
        'err_age_restricted': 'media_downloader.flash.err_age_restricted',
        'err_video_unavailable': 'media_downloader.flash.err_video_unavailable',
        'client_download_failed': 'media_downloader.flash.client_download_failed',
        'err_download_failed': 'media_downloader.flash.err_download_failed',
    }
    job.status = 'failed'
    job.error_message = _pack_error(
        error_key,
        translate(key_map.get(error_key, 'media_downloader.flash.client_download_failed'), language=lang),
    )
    job.expires_at = datetime.utcnow() + get_retention_timedelta()
    delete_job_raw_dir(job.id)
    db.session.commit()
    return jsonify(_serialize_job_status(job))


@media_downloader_bp.route('/download', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('5 per hour')
def start_download():
    """Legacy form endpoint — redirects to index; downloads are started via JS."""
    if not _require_downloader():
        return redirect(url_for('media_downloader.index'))
    flash(translate('media_downloader.flash.use_browser'), 'info')
    return redirect(url_for('media_downloader.index') + '#jobs')


@media_downloader_bp.route('/playlist-preview', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def playlist_preview():
    """Deprecated server-side preview — client loads playlists in the browser."""
    return jsonify({
        'error': translate('media_downloader.playlist.client_only'),
        'error_key': 'client_only',
    }), 410


@media_downloader_bp.route('/download-batch', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('20 per hour')
def download_batch():
    if not is_media_downloader_compatible():
        return jsonify({'error': translate('media_downloader.flash.incompatible')}), 503

    data = request.get_json(silent=True) or {}
    output_format = (data.get('format') or 'audio').strip().lower()
    items = data.get('items') or []

    if output_format not in ('audio', 'video'):
        return jsonify({'error': translate('media_downloader.flash.invalid_format')}), 400

    if not items or not isinstance(items, list):
        return jsonify({'error': translate('media_downloader.flash.empty_playlist')}), 400

    max_concurrent = _get_max_concurrent_for_user(current_app)
    slots = max(0, max_concurrent - _active_job_count(current_user.id))
    if len(items) > slots and slots == 0:
        return jsonify({
            'error': translate('media_downloader.flash.too_many_jobs', max=max_concurrent),
        }), 429

    jobs = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return jsonify({'error': translate('media_downloader.flash.invalid_batch_item')}), 400

        payload, error, error_key = _validate_job_payload({
            'source_url': item.get('source_url'),
            'format': output_format,
            'start_time': item.get('start_time'),
            'end_time': item.get('end_time'),
            'title': item.get('title'),
        })
        if error:
            return jsonify({'error': error, 'index': index, 'error_key': error_key}), 400

        if _active_job_count(current_user.id) + len(jobs) >= max_concurrent:
            break

        job = _create_job(
            current_user.id,
            payload['source_url'],
            payload['format'],
            payload['start_time'],
            payload['end_time'],
            title=payload['title'],
        )
        jobs.append(job)

    db.session.commit()
    get_upload_dir()

    return jsonify({
        'started': len(jobs),
        'job_ids': [job.id for job in jobs],
        'jobs': [_serialize_job_status(job) for job in jobs],
    })


@media_downloader_bp.route('/clear-all', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('10 per hour')
def clear_all():
    jobs = MediaDownloadJob.query.filter_by(user_id=current_user.id).all()
    removed_count = 0
    cancelling_count = 0
    app = current_app._get_current_object()

    for job in jobs:
        if job.status in ACTIVE_STATUSES:
            removed = _request_job_cancel(app, job)
            if removed:
                removed_count += 1
            else:
                cancelling_count += 1
        else:
            _purge_job(job)
            removed_count += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'removed': removed_count,
        'cancelling': cancelling_count,
    })


@media_downloader_bp.route('/job/<int:job_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def delete_job(job_id):
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    app = current_app._get_current_object()
    force = str(
        request.args.get('force')
        or (request.get_json(silent=True) or {}).get('force')
        or ''
    ).lower() in ('1', 'true', 'yes')

    if force or job.status in ('cancelled', 'cancelling', 'failed', 'completed'):
        _mark_job_cancelled(job.id)
        _purge_job(job)
        db.session.commit()
        _clear_job_cancelled(job_id)
        return jsonify({'success': True, 'removed': True, 'cancelling': False})

    removed = _request_job_cancel(app, job)
    db.session.commit()
    return jsonify({'success': True, 'removed': removed, 'cancelling': not removed})


@media_downloader_bp.route('/status/<int:job_id>')
@login_required
@check_module_access('module_media_downloader')
def job_status(job_id):
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    return jsonify(_serialize_job_status(job))


@media_downloader_bp.route('/file/<int:job_id>')
@login_required
@check_module_access('module_media_downloader')
def download_file(job_id):
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()

    if not job.is_downloadable():
        flash(translate('media_downloader.flash.expired'), 'warning')
        return redirect(url_for('media_downloader.index'))

    filepath = os.path.abspath(os.path.join(get_upload_dir(), job.filename))
    upload_root = os.path.abspath(get_upload_dir())
    if not filepath.startswith(upload_root + os.sep) and filepath != upload_root:
        flash(translate('media_downloader.flash.file_missing'), 'danger')
        return redirect(url_for('media_downloader.index'))

    if not os.path.isfile(filepath):
        flash(translate('media_downloader.flash.file_missing'), 'danger')
        return redirect(url_for('media_downloader.index'))

    mimetype = 'audio/mpeg' if job.format == 'audio' else 'video/mp4'
    try:
        return send_file(filepath, as_attachment=True, download_name=job.filename, mimetype=mimetype)
    except FileNotFoundError:
        flash(translate('media_downloader.flash.file_missing'), 'danger')
        return redirect(url_for('media_downloader.index'))
