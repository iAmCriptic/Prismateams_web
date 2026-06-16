import logging
import os
import threading
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user

from app import db, limiter
from app.models.media_downloader import MediaDownloadJob
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.media_downloader import (
    is_media_downloader_compatible,
    validate_media_url,
    is_playlist_url,
    parse_time_segment,
    extract_playlist_entries,
    run_download,
    get_retention_timedelta,
    get_upload_dir,
)

logger = logging.getLogger(__name__)

media_downloader_bp = Blueprint('media_downloader', __name__, url_prefix='/media-downloader')

_download_semaphore = None
_semaphore_lock = threading.Lock()


def _require_downloader():
    if not is_media_downloader_compatible():
        flash(translate('media_downloader.flash.incompatible'), 'warning')
        return False
    return True


def _active_job_count(user_id):
    return MediaDownloadJob.query.filter(
        MediaDownloadJob.user_id == user_id,
        MediaDownloadJob.status.in_(('pending', 'processing')),
    ).count()


def _get_download_semaphore(app):
    global _download_semaphore
    with _semaphore_lock:
        if _download_semaphore is None:
            max_concurrent = app.config.get('MEDIA_DOWNLOADER_MAX_CONCURRENT', 2)
            _download_semaphore = threading.Semaphore(max(1, int(max_concurrent)))
        return _download_semaphore


def _apply_job_result(job, success, error_message):
    if success:
        job.status = 'completed'
        job.error_message = None
    else:
        job.status = 'failed'
        if error_message == 'err_http_403':
            job.error_message = translate('media_downloader.flash.err_http_403')
        elif error_message == 'err_age_restricted':
            job.error_message = translate('media_downloader.flash.err_age_restricted')
        elif error_message == 'err_video_unavailable':
            job.error_message = translate('media_downloader.flash.err_video_unavailable')
        elif error_message == 'err_download_failed':
            job.error_message = translate('media_downloader.flash.err_download_failed')
        elif error_message == 'output_not_found':
            job.error_message = translate('media_downloader.flash.file_missing')
        else:
            job.error_message = error_message
        job.expires_at = datetime.utcnow() + get_retention_timedelta()


def _process_download(app, job_id):
    semaphore = _get_download_semaphore(app)
    semaphore.acquire()
    try:
        with app.app_context():
            job = MediaDownloadJob.query.get(job_id)
            if not job:
                return

            job.status = 'processing'
            db.session.commit()

            success, error_message = run_download(job)
            _apply_job_result(job, success, error_message)
            db.session.commit()
    finally:
        semaphore.release()


def _start_download_thread(app, job_id):
    thread = threading.Thread(
        target=_process_download,
        args=(app, job_id),
        daemon=True,
        name=f'media-download-{job_id}',
    )
    thread.start()


def _create_and_start_job(user_id, source_url, output_format, start_parsed, end_parsed, app):
    job = MediaDownloadJob(
        user_id=user_id,
        source_url=source_url,
        format=output_format,
        start_time=start_parsed,
        end_time=end_parsed,
        status='pending',
        expires_at=datetime.utcnow() + get_retention_timedelta(),
    )
    db.session.add(job)
    db.session.flush()
    _start_download_thread(app, job.id)
    return job


def _serialize_job_status(job):
    return {
        'id': job.id,
        'status': job.status,
        'title': job.title,
        'source_url': job.source_url,
        'format': job.format,
        'start_time': job.start_time,
        'end_time': job.end_time,
        'error_message': job.error_message,
        'downloadable': job.is_downloadable(),
        'expires_at': job.expires_at.isoformat() + 'Z' if job.expires_at else None,
        'file_size': job.file_size,
        'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
    }


@media_downloader_bp.route('/')
@login_required
@check_module_access('module_media_downloader')
def index():
    if not _require_downloader():
        return redirect(url_for('dashboard.index'))

    jobs = MediaDownloadJob.query.filter_by(user_id=current_user.id).order_by(
        MediaDownloadJob.created_at.desc()
    ).limit(50).all()

    return render_template('media_downloader/index.html', jobs=jobs)


@media_downloader_bp.route('/download', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('5 per hour')
def start_download():
    if not _require_downloader():
        return redirect(url_for('media_downloader.index'))

    source_url = request.form.get('source_url', '').strip()
    output_format = request.form.get('format', 'audio').strip().lower()
    start_time = request.form.get('start_time', '').strip()
    end_time = request.form.get('end_time', '').strip()

    if output_format not in ('audio', 'video'):
        flash(translate('media_downloader.flash.invalid_format'), 'danger')
        return redirect(url_for('media_downloader.index'))

    is_valid, error_key = validate_media_url(source_url)
    if not is_valid:
        flash(translate(f'media_downloader.flash.{error_key}'), 'danger')
        return redirect(url_for('media_downloader.index'))

    start_parsed, end_parsed, segment_error = parse_time_segment(start_time, end_time)
    if segment_error:
        flash(translate(f'media_downloader.flash.{segment_error}'), 'danger')
        return redirect(url_for('media_downloader.index'))

    if is_playlist_url(source_url):
        flash(translate('media_downloader.flash.use_playlist_modal'), 'info')
        return redirect(url_for('media_downloader.index'))

    max_concurrent = current_app.config.get('MEDIA_DOWNLOADER_MAX_CONCURRENT', 2)
    if _active_job_count(current_user.id) >= max_concurrent:
        flash(translate('media_downloader.flash.too_many_jobs', max=max_concurrent), 'warning')
        return redirect(url_for('media_downloader.index'))

    job = _create_and_start_job(
        current_user.id,
        source_url,
        output_format,
        start_parsed,
        end_parsed,
        current_app._get_current_object(),
    )
    db.session.commit()

    get_upload_dir()

    flash(translate('media_downloader.flash.started'), 'success')
    return redirect(url_for('media_downloader.index'))


@media_downloader_bp.route('/playlist-preview', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('10 per hour')
def playlist_preview():
    if not is_media_downloader_compatible():
        return jsonify({'error': translate('media_downloader.flash.incompatible')}), 503

    data = request.get_json(silent=True) or {}
    source_url = (data.get('source_url') or '').strip()

    is_valid, error_key = validate_media_url(source_url)
    if not is_valid:
        return jsonify({'error': translate(f'media_downloader.flash.{error_key}')}), 400

    if not is_playlist_url(source_url):
        return jsonify({'error': translate('media_downloader.flash.not_a_playlist')}), 400

    result, error_key = extract_playlist_entries(source_url)
    if error_key:
        return jsonify({'error': translate(f'media_downloader.flash.{error_key}')}), 400

    return jsonify(result)


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

    validated_items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return jsonify({'error': translate('media_downloader.flash.invalid_batch_item')}), 400

        source_url = (item.get('source_url') or '').strip()
        start_time = (item.get('start_time') or '').strip() if item.get('start_time') else ''
        end_time = (item.get('end_time') or '').strip() if item.get('end_time') else ''

        is_valid, error_key = validate_media_url(source_url)
        if not is_valid:
            return jsonify({
                'error': translate(f'media_downloader.flash.{error_key}'),
                'index': index,
            }), 400

        start_parsed, end_parsed, segment_error = parse_time_segment(start_time, end_time)
        if segment_error:
            return jsonify({
                'error': translate(f'media_downloader.flash.{segment_error}'),
                'index': index,
            }), 400

        validated_items.append({
            'source_url': source_url,
            'start_time': start_parsed,
            'end_time': end_parsed,
            'title': (item.get('title') or '').strip() or None,
        })

    app = current_app._get_current_object()
    get_upload_dir()

    jobs = []
    for item in validated_items:
        job = _create_and_start_job(
            current_user.id,
            item['source_url'],
            output_format,
            item['start_time'],
            item['end_time'],
            app,
        )
        if item['title']:
            job.title = item['title']
        jobs.append(job)

    db.session.commit()

    return jsonify({
        'started': len(jobs),
        'job_ids': [job.id for job in jobs],
        'jobs': [_serialize_job_status(job) for job in jobs],
    })


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

    filepath = os.path.join(get_upload_dir(), job.filename)
    if not os.path.isfile(filepath):
        flash(translate('media_downloader.flash.file_missing'), 'danger')
        return redirect(url_for('media_downloader.index'))

    mimetype = 'audio/mpeg' if job.format == 'audio' else 'video/mp4'
    return send_file(filepath, as_attachment=True, download_name=job.filename, mimetype=mimetype)
