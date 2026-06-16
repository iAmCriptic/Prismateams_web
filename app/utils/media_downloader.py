"""Media Downloader utilities (YouTube / YouTube Music via yt-dlp + FFmpeg)."""
import glob
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from flask import current_app

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    'www.youtube.com',
    'youtube.com',
    'youtu.be',
    'm.youtube.com',
    'music.youtube.com',
    'www.music.youtube.com',
}

TIME_PATTERN = re.compile(r'^(\d+):([0-5]\d)(?::([0-5]\d))?$')

PLAYLIST_LIST_PREFIXES = ('PL', 'RD', 'OL', 'LL', 'FL', 'VL', 'PU', 'UU')


class DownloadCancelledError(Exception):
    """Raised when an active download should be cancelled."""


def get_ffmpeg_path():
    """Return configured FFmpeg path or discover it on PATH."""
    configured = current_app.config.get('FFMPEG_PATH', '')
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which('ffmpeg')


def is_media_downloader_compatible():
    """True when FFmpeg is available (system requirement for downloads)."""
    return bool(get_ffmpeg_path())


def _get_playlist_list_id(parsed):
    list_vals = parse_qs(parsed.query).get('list', [])
    if not list_vals:
        return None
    list_id = list_vals[0].strip()
    return list_id or None


def is_playlist_url(url):
    """Return True when the URL refers to a YouTube / YouTube Music playlist."""
    if not url or not url.strip():
        return False

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().split(':')[0]
    if host not in ALLOWED_HOSTS:
        return False

    path = parsed.path.rstrip('/').lower()
    list_id = _get_playlist_list_id(parsed)

    if path.endswith('/playlist') and list_id:
        return True

    if path in ('/watch', '') or path.startswith('/watch'):
        return list_id is not None

    if host.startswith('music.') and path.strip('/'):
        if path.endswith('/playlist') or list_id:
            return True

    return False


def validate_media_url(url):
    """
    Validate that URL points to an allowed YouTube / YouTube Music host.

    Returns:
        tuple: (is_valid: bool, error_key: str | None)
    """
    if not url or not url.strip():
        return False, 'empty_url'

    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https'):
        return False, 'invalid_scheme'

    host = parsed.netloc.lower().split(':')[0]
    if host not in ALLOWED_HOSTS:
        return False, 'invalid_host'

    if host in ('youtu.be',) and not parsed.path.strip('/'):
        return False, 'invalid_url'

    path = parsed.path.rstrip('/').lower()
    if path.endswith('/playlist'):
        if _get_playlist_list_id(parsed):
            return True, None
        return False, 'invalid_url'

    if host.endswith('youtube.com') and 'watch' not in parsed.path and 'shorts' not in parsed.path:
        if host.startswith('music.') and parsed.path.strip('/'):
            return True, None
        if host.startswith('music.'):
            return False, 'invalid_url'
        if parsed.path.strip('/') and parsed.path not in ('/', ''):
            if not parsed.path.startswith('/watch') and not parsed.path.startswith('/shorts'):
                return False, 'invalid_url'

    return True, None


def _time_string_to_seconds(time_str):
    match = TIME_PATTERN.match(time_str.strip())
    if not match:
        return None

    first, second, third = match.groups()
    if third is None:
        return int(first) * 60 + int(second)
    return int(first) * 3600 + int(second) * 60 + int(third)


def parse_time_segment(start_str, end_str):
    """
    Parse optional start/end times in M:SS, MM:SS or H:MM:SS format.

    Returns:
        tuple: (start, end, error_key)
        start/end are original strings when valid, or None when empty.
    """
    start_str = (start_str or '').strip()
    end_str = (end_str or '').strip()

    if not start_str and not end_str:
        return None, None, None

    if bool(start_str) != bool(end_str):
        return None, None, 'incomplete_segment'

    start_seconds = _time_string_to_seconds(start_str)
    end_seconds = _time_string_to_seconds(end_str)

    if start_seconds is None or end_seconds is None:
        return None, None, 'invalid_time_format'

    if start_seconds >= end_seconds:
        return None, None, 'invalid_time_range'

    return start_str, end_str, None


def get_upload_dir():
    base = current_app.config['UPLOAD_FOLDER']
    target = os.path.join(base, 'media_downloader')
    os.makedirs(target, exist_ok=True)
    return target


def get_retention_timedelta():
    hours = current_app.config.get('MEDIA_DOWNLOADER_RETENTION_HOURS', 1)
    return timedelta(hours=max(1, int(hours)))


def _get_common_ydl_opts():
    """Shared yt-dlp options for metadata extraction and downloads."""
    max_bytes = current_app.config.get('MAX_CONTENT_LENGTH', 524288000)
    ffmpeg_path = get_ffmpeg_path()

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'max_filesize': max_bytes,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/125.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash'],
            }
        },
        'retries': 3,
        'fragment_retries': 3,
    }

    if ffmpeg_path:
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ydl_opts['ffmpeg_location'] = ffmpeg_dir or ffmpeg_path

    return ydl_opts


def extract_playlist_entries(url):
    """
    Fetch playlist metadata without downloading.

    Returns:
        tuple: (result_dict | None, error_key | None)
    """
    import yt_dlp

    ydl_opts = _get_common_ydl_opts()
    ydl_opts.update({
        'extract_flat': 'in_playlist',
        'skip_download': True,
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        logger.error('Playlist preview failed for %s: %s', url, exc, exc_info=True)
        return None, 'preview_failed'

    if not info:
        return None, 'empty_playlist'

    entries = []
    for entry in info.get('entries') or []:
        if not entry:
            continue

        video_id = entry.get('id')
        if not video_id:
            continue

        title = (entry.get('title') or '').strip()
        if title in ('[Private video]', '[Deleted video]'):
            continue

        entry_url = entry.get('url') or entry.get('webpage_url')
        if not entry_url:
            entry_url = f'https://www.youtube.com/watch?v={video_id}'

        entries.append({
            'id': video_id,
            'title': title or video_id,
            'url': entry_url,
            'duration': entry.get('duration'),
        })

    if not entries:
        return None, 'empty_playlist'

    return {
        'playlist_title': info.get('title') or 'Playlist',
        'entry_count': len(entries),
        'entries': entries,
    }, None


def run_download(job, should_cancel=None):
    """
    Download and convert media for a MediaDownloadJob instance.

    Returns:
        tuple: (success: bool, error_message: str | None)
    """
    import yt_dlp

    upload_dir = get_upload_dir()
    output_ext = 'mp3' if job.format == 'audio' else 'mp4'
    output_template = os.path.join(upload_dir, f'{job.id}_%(title).200B.%(ext)s')

    ydl_opts = _get_common_ydl_opts()
    ydl_opts['outtmpl'] = output_template

    if job.format == 'audio':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        ydl_opts.update({
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
        })

    if job.start_time and job.end_time:
        ydl_opts['download_sections'] = [f'*{job.start_time}-{job.end_time}']

    def _check_cancel():
        return bool(should_cancel and should_cancel())

    def _progress_hook(_status):
        if _check_cancel():
            raise DownloadCancelledError('cancelled')

    if _check_cancel():
        return False, 'cancelled'

    ydl_opts['progress_hooks'] = [_progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if _check_cancel():
                return False, 'cancelled'
            info = ydl.extract_info(job.source_url, download=True)
            title = info.get('title') if info else None

        pattern = os.path.join(upload_dir, f'{job.id}_*.{output_ext}')
        matches = glob.glob(pattern)
        if not matches:
            pattern_any = os.path.join(upload_dir, f'{job.id}_*.*')
            matches = [p for p in glob.glob(pattern_any) if not p.endswith('.part')]

        if not matches:
            return False, 'output_not_found'

        filepath = matches[0]
        job.title = title
        job.filename = os.path.basename(filepath)
        job.file_size = os.path.getsize(filepath)
        job.completed_at = datetime.utcnow()
        job.expires_at = job.completed_at + get_retention_timedelta()
        return True, None
    except DownloadCancelledError:
        return False, 'cancelled'
    except Exception as exc:
        logger.error('Media download failed for job %s: %s', job.id, exc, exc_info=True)
        message = str(exc).lower()
        if 'http error 403' in message or 'forbidden' in message:
            return False, 'err_http_403'
        if 'sign in to confirm your age' in message:
            return False, 'err_age_restricted'
        if 'video is unavailable' in message:
            return False, 'err_video_unavailable'
        if 'output_not_found' in message:
            return False, 'output_not_found'
        return False, 'err_download_failed'


def delete_job_file(job):
    """Remove the physical file for a job if it exists."""
    if not job.filename:
        return

    filepath = os.path.join(get_upload_dir(), job.filename)
    if os.path.isfile(filepath):
        try:
            os.remove(filepath)
        except OSError as exc:
            logger.warning('Could not delete media file %s: %s', filepath, exc)
