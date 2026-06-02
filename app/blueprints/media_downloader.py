import logging
import os
import threading
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user

from app import db, limiter
from app.models.media_downloader import MediaDownloadJob
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.media_downloader import (
    is_media_downloader_compatible,
    validate_media_url,
    parse_time_segment,
    run_download,
    get_retention_timedelta,
    get_upload_dir,
)

logger = logging.getLogger(__name__)

media_downloader_bp = Blueprint('media_downloader', __name__, url_prefix='/media-downloader')


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


def _process_download(app, job_id):
    with app.app_context():
        job = MediaDownloadJob.query.get(job_id)
        if not job:
            return

        job.status = 'processing'
        db.session.commit()

        success, error_message = run_download(job)

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

        db.session.commit()


def _start_download_thread(app, job_id):
    thread = threading.Thread(
        target=_process_download,
        args=(app, job_id),
        daemon=True,
        name=f'media-download-{job_id}',
    )
    thread.start()


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

    max_concurrent = current_app.config.get('MEDIA_DOWNLOADER_MAX_CONCURRENT', 2)
    if _active_job_count(current_user.id) >= max_concurrent:
        flash(translate('media_downloader.flash.too_many_jobs', max=max_concurrent), 'warning')
        return redirect(url_for('media_downloader.index'))

    job = MediaDownloadJob(
        user_id=current_user.id,
        source_url=source_url,
        format=output_format,
        start_time=start_parsed,
        end_time=end_parsed,
        status='pending',
        expires_at=datetime.utcnow() + get_retention_timedelta(),
    )
    db.session.add(job)
    db.session.commit()

    get_upload_dir()
    _start_download_thread(current_app._get_current_object(), job.id)

    flash(translate('media_downloader.flash.started'), 'success')
    return redirect(url_for('media_downloader.index'))


@media_downloader_bp.route('/status/<int:job_id>')
@login_required
@check_module_access('module_media_downloader')
def job_status(job_id):
    job = MediaDownloadJob.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()

    return jsonify({
        'id': job.id,
        'status': job.status,
        'title': job.title,
        'error_message': job.error_message,
        'downloadable': job.is_downloadable(),
        'expires_at': job.expires_at.isoformat() + 'Z' if job.expires_at else None,
        'file_size': job.file_size,
    })


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
