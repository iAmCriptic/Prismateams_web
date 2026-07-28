import logging
import os
import threading
import time
from collections import defaultdict
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
    normalize_media_url,
    canonicalize_playlist_url,
    parse_time_segment,
    extract_playlist_entries,
    run_download,
    get_retention_timedelta,
    get_upload_dir,
    delete_job_file,
)

logger = logging.getLogger(__name__)

media_downloader_bp = Blueprint('media_downloader', __name__, url_prefix='/media-downloader')

_queue_lock = threading.Lock()
_user_active_downloads = defaultdict(int)
_cancelled_job_ids = set()


def _require_downloader():
    if not is_media_downloader_compatible():
        flash(translate('media_downloader.flash.incompatible'), 'warning')
        return False
    return True


def _youtube_search_enabled():
    """True when a YouTube Data API key is configured (Media Downloader search).

    Does not require YouTube as an active Music-module provider — the API key
    alone is enough for public video search suggestions.
    """
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
        MediaDownloadJob.status.in_(('pending', 'processing')),
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


def _is_job_cancelled(job_id):
    with _queue_lock:
        return job_id in _cancelled_job_ids


def _purge_job(job):
    """Delete job file + DB row. Caller must commit."""
    if not job:
        return
    try:
        delete_job_file(job)
    except Exception:
        logger.debug('Could not delete media file for job %s', getattr(job, 'id', None), exc_info=True)
    db.session.delete(job)


def _force_purge_cancelled_job(app, job_id, delay_seconds=8):
    """
    After a short wait, remove jobs still stuck in cancelling/processing cancel.
    yt-dlp may ignore cancel for a while; don't leave zombie rows in the list.
    """
    def _run():
        try:
            time.sleep(max(1, int(delay_seconds)))
            with app.app_context():
                job = MediaDownloadJob.query.get(job_id)
                if not job:
                    return
                if job.status in ('cancelling', 'cancelled'):
                    _purge_job(job)
                    db.session.commit()
                    logger.info('Purged cancelled media job %s after timeout', job_id)
                elif job.status == 'processing' and _is_job_cancelled(job_id):
                    _purge_job(job)
                    db.session.commit()
                    logger.info('Purged stuck processing media job %s after cancel timeout', job_id)
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
    """Mark job as cancelling and schedule auto-purge. Returns True if already removed."""
    if job.status == 'pending':
        _mark_job_cancelled(job.id)
        _purge_job(job)
        return True

    if job.status in ('processing', 'cancelling'):
        _mark_job_cancelled(job.id)
        job.status = 'cancelling'
        job.error_message = translate(
            'media_downloader.flash.cancelling',
            language=_job_language(job),
        )
        _force_purge_cancelled_job(app, job.id, delay_seconds=8)
        return False

    # completed / failed / cancelled → hard delete
    _purge_job(job)
    return True


def _job_language(job):
    """User language for background threads (no request context)."""
    try:
        user = getattr(job, 'user', None)
        lang = getattr(user, 'language', None) if user else None
        if lang:
            return lang
    except Exception:
        pass
    return None


def _pack_error(error_key, text):
    """Persist machine key with human message without a new DB column."""
    if error_key:
        return f'[{error_key}] {text}'
    return text


def _unpack_error(message):
    """Return (error_key|None, display_message)."""
    if not message:
        return None, None
    text = str(message)
    if text.startswith('[') and ']' in text[:64]:
        key, _, rest = text[1:].partition(']')
        key = key.strip()
        rest = rest.lstrip(' ')
        if key.startswith('err_') or key in ('cancelled', 'output_not_found'):
            return key, rest or text
    return None, text


def _apply_job_result(job, success, error_message):
    """
    Apply download outcome to the job.

    Returns:
        str: 'deleted' when the job row was removed, otherwise 'updated'.
    """
    lang = _job_language(job)

    if success:
        job.status = 'completed'
        job.error_message = None
        return 'updated'

    if error_message == 'cancelled':
        # Abbruch → Eintrag nicht in der Liste stehen lassen
        _purge_job(job)
        return 'deleted'

    job.status = 'failed'
    key_map = {
        'err_http_403': 'media_downloader.flash.err_http_403',
        'err_bot_check': 'media_downloader.flash.err_bot_check',
        'err_cookies_needed': 'media_downloader.flash.err_cookies_needed',
        'err_age_restricted': 'media_downloader.flash.err_age_restricted',
        'err_video_unavailable': 'media_downloader.flash.err_video_unavailable',
        'err_download_failed': 'media_downloader.flash.err_download_failed',
        'output_not_found': 'media_downloader.flash.file_missing',
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


def _dispatch_pending_jobs(app, user_id):
    with app.app_context():
        max_concurrent = _get_max_concurrent_for_user(app)
        jobs_to_start = []

        with _queue_lock:
            active = _user_active_downloads[user_id]
            slots = max(0, max_concurrent - active)
            if slots == 0:
                return

            pending_jobs = MediaDownloadJob.query.filter_by(
                user_id=user_id,
                status='pending',
            ).order_by(MediaDownloadJob.created_at.asc()).limit(slots).all()

            for job in pending_jobs:
                _user_active_downloads[user_id] += 1
                jobs_to_start.append(job.id)

        for job_id in jobs_to_start:
            thread = threading.Thread(
                target=_process_download,
                args=(app, user_id, job_id),
                daemon=True,
                name=f'media-download-{job_id}',
            )
            thread.start()


def _process_download(app, user_id, job_id):
    try:
        with app.app_context():
            job = MediaDownloadJob.query.get(job_id)
            if not job:
                return

            if job.status != 'pending':
                return

            if _is_job_cancelled(job.id):
                _purge_job(job)
                db.session.commit()
                return

            job.status = 'processing'
            db.session.commit()

            # Cancel requested while we flipped to processing
            if _is_job_cancelled(job.id) or job.status == 'cancelling':
                # re-read in case another request set cancelling
                db.session.refresh(job)
                if _is_job_cancelled(job.id) or job.status == 'cancelling':
                    _purge_job(job)
                    db.session.commit()
                    return

            success, error_message = run_download(
                job,
                should_cancel=lambda: _is_job_cancelled(job.id),
            )

            # Job may have been purged by cancel-timeout thread
            job = MediaDownloadJob.query.get(job_id)
            if not job:
                return

            if job.status == 'cancelling' or _is_job_cancelled(job.id):
                error_message = 'cancelled'
                success = False

            _apply_job_result(job, success, error_message)
            db.session.commit()
    except Exception:
        logger.exception('Media download thread crashed for job %s', job_id)
        try:
            with app.app_context():
                job = MediaDownloadJob.query.get(job_id)
                if job and job.status in ('pending', 'processing', 'cancelling'):
                    if _is_job_cancelled(job.id) or job.status == 'cancelling':
                        _purge_job(job)
                    else:
                        job.status = 'failed'
                        job.error_message = _pack_error(
                            'err_download_failed',
                            translate(
                                'media_downloader.flash.err_download_failed',
                                language=_job_language(job),
                            ),
                        )
                        job.expires_at = datetime.utcnow() + get_retention_timedelta()
                    db.session.commit()
        except Exception:
            logger.exception('Could not mark media job %s as failed after crash', job_id)
    finally:
        _clear_job_cancelled(job_id)
        with _queue_lock:
            _user_active_downloads[user_id] = max(0, _user_active_downloads[user_id] - 1)
        _dispatch_pending_jobs(app, user_id)


def _start_download_thread(app, job_id):
    with app.app_context():
        job = MediaDownloadJob.query.get(job_id)
        if not job:
            return
        _dispatch_pending_jobs(app, job.user_id)


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
    return job


def _serialize_job_status(job):
    error_key, error_message = _unpack_error(job.error_message)
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
    }


@media_downloader_bp.route('/')
@login_required
@check_module_access('module_media_downloader')
def index():
    if not _require_downloader():
        return redirect(url_for('dashboard.index'))

    # Alte Abbruch-Zombies sofort entfernen (blieben sonst ewig in der Liste)
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

    active_jobs_count = sum(
        1 for job in jobs if job.status in ('pending', 'processing', 'cancelling')
    )

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


@media_downloader_bp.route('/download', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('5 per hour')
def start_download():
    if not _require_downloader():
        return redirect(url_for('media_downloader.index'))

    source_url = normalize_media_url(request.form.get('source_url', ''))
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
        # Re-open client playlist modal instead of a dead-end flash
        playlist_url = canonicalize_playlist_url(source_url) or source_url
        return redirect(url_for('media_downloader.index', playlist_url=playlist_url))

    max_concurrent = current_app.config.get('MEDIA_DOWNLOADER_MAX_CONCURRENT', 2)
    if _active_job_count(current_user.id) >= max_concurrent:
        flash(translate('media_downloader.flash.too_many_jobs', max=max_concurrent), 'warning')
        return redirect(url_for('media_downloader.index'))

    _create_and_start_job(
        current_user.id,
        source_url,
        output_format,
        start_parsed,
        end_parsed,
        current_app._get_current_object(),
    )
    db.session.commit()
    _dispatch_pending_jobs(current_app._get_current_object(), current_user.id)

    get_upload_dir()

    flash(translate('media_downloader.flash.started'), 'success')
    return redirect(url_for('media_downloader.index') + '#jobs')


@media_downloader_bp.route('/playlist-preview', methods=['POST'])
@login_required
@check_module_access('module_media_downloader')
@limiter.limit('30 per hour')
def playlist_preview():
    if not is_media_downloader_compatible():
        return jsonify({
            'error': translate('media_downloader.flash.incompatible'),
            'error_key': 'incompatible',
        }), 503

    data = request.get_json(silent=True) or {}
    source_url = normalize_media_url(data.get('source_url') or '')
    if is_playlist_url(source_url):
        source_url = canonicalize_playlist_url(source_url) or source_url

    is_valid, error_key = validate_media_url(source_url)
    if not is_valid:
        return jsonify({
            'error': translate(f'media_downloader.flash.{error_key}'),
            'error_key': error_key,
        }), 400

    if not is_playlist_url(source_url):
        return jsonify({
            'error': translate('media_downloader.flash.not_a_playlist'),
            'error_key': 'not_a_playlist',
        }), 400

    result, error_key = extract_playlist_entries(source_url)
    if error_key:
        return jsonify({
            'error': translate(f'media_downloader.flash.{error_key}'),
            'error_key': error_key,
        }), 400

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

        source_url = normalize_media_url(item.get('source_url') or '')
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
    _dispatch_pending_jobs(app, current_user.id)

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
        if job.status in ('pending', 'processing', 'cancelling'):
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

    # Already done / stuck cancel → immer hart löschen
    if force or job.status in ('cancelled', 'cancelling', 'failed', 'completed'):
        _mark_job_cancelled(job.id)
        _purge_job(job)
        db.session.commit()
        _clear_job_cancelled(job_id)
        return jsonify({'success': True, 'removed': True, 'cancelling': False})

    # pending / processing → Abbruch anstoßen (processing wird nach kurzer Zeit gepurged)
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
