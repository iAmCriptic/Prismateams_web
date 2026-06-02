"""Media Downloader utilities (YouTube / YouTube Music via yt-dlp + FFmpeg)."""
import glob
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from urllib.parse import urlparse

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


def get_ffmpeg_path():
    """Return configured FFmpeg path or discover it on PATH."""
    configured = current_app.config.get('FFMPEG_PATH', '')
    if configured and os.path.isfile(configured):
        return configured
    return shutil.which('ffmpeg')


def is_media_downloader_compatible():
    """True when FFmpeg is available (system requirement for downloads)."""
    return bool(get_ffmpeg_path())


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


def run_download(job):
    """
    Download and convert media for a MediaDownloadJob instance.

    Returns:
        tuple: (success: bool, error_message: str | None)
    """
    import yt_dlp

    upload_dir = get_upload_dir()
    output_ext = 'mp3' if job.format == 'audio' else 'mp4'
    output_template = os.path.join(upload_dir, f'{job.id}_%(title).200B.%(ext)s')

    ffmpeg_path = get_ffmpeg_path()
    max_bytes = current_app.config.get('MAX_CONTENT_LENGTH', 524288000)

    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        'max_filesize': max_bytes,
    }

    if ffmpeg_path:
        ffmpeg_dir = os.path.dirname(ffmpeg_path)
        ydl_opts['ffmpeg_location'] = ffmpeg_dir or ffmpeg_path

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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
    except Exception as exc:
        logger.error('Media download failed for job %s: %s', job.id, exc, exc_info=True)
        return False, str(exc)


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
