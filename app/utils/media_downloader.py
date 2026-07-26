"""Media Downloader utilities (YouTube / YouTube Music via yt-dlp + FFmpeg)."""
import glob
import logging
import os
import re
import shutil
import subprocess
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

# True playlists / albums / library lists. RD (mix/radio) intentionally excluded.
PLAYLIST_LIST_PREFIXES = ('PL', 'OL', 'LL', 'FL', 'VL', 'PU', 'UU')

FFMPEG_FALLBACK_PATHS = (
    '/usr/bin/ffmpeg',
    '/usr/local/bin/ffmpeg',
)


class DownloadCancelledError(Exception):
    """Raised when an active download should be cancelled."""


def normalize_media_url(url):
    """Trim, strip wrapping junk, and ensure http(s) scheme for YouTube URLs."""
    if not url or not str(url).strip():
        return ''

    cleaned = str(url).strip()
    # First URL in pasted text (chat messages, etc.)
    match = re.search(r'https?://[^\s<>"\']+', cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = match.group(0)
    else:
        # Bare youtube.com / youtu.be without scheme
        bare = re.search(
            r'(?:www\.)?(?:music\.)?(?:m\.)?(?:youtube\.com|youtu\.be)/\S+',
            cleaned,
            flags=re.IGNORECASE,
        )
        if bare:
            cleaned = 'https://' + bare.group(0).lstrip('/')

    cleaned = cleaned.rstrip(').,;\'"')
    return cleaned


def _normalize_host(netloc):
    host = (netloc or '').lower().split(':')[0]
    if host.startswith('www.'):
        host = host[4:]
    return host


def _is_allowed_host(host):
    if not host:
        return False
    if host in ALLOWED_HOSTS:
        return True
    if f'www.{host}' in ALLOWED_HOSTS:
        return True
    # m.youtube.com / music.youtube.com already covered; allow *.youtube.com
    if host.endswith('.youtube.com') or host == 'youtube.com' or host == 'youtu.be':
        return True
    return False


def get_ffmpeg_path():
    """Return configured FFmpeg path or discover it on PATH / common locations."""
    configured = current_app.config.get('FFMPEG_PATH', '')
    if configured and os.path.isfile(configured):
        return configured

    found = shutil.which('ffmpeg')
    if found:
        return found

    for candidate in FFMPEG_FALLBACK_PATHS:
        if os.path.isfile(candidate):
            return candidate

    return None


def is_media_downloader_compatible():
    """True when FFmpeg is available (system requirement for downloads)."""
    return bool(get_ffmpeg_path())


def get_ffmpeg_version():
    """Return installed FFmpeg version string, or None if unavailable."""
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        return None

    try:
        result = subprocess.run(
            [ffmpeg_path, '-version'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        first_line = (result.stdout or '').splitlines()[0] if result.stdout else ''
        match = re.search(r'ffmpeg version\s+(\S+)', first_line, flags=re.IGNORECASE)
        return match.group(1) if match else None
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        logger.debug('Could not determine FFmpeg version', exc_info=True)
        return None


def _get_playlist_list_id(parsed):
    list_vals = parse_qs(parsed.query).get('list', [])
    if not list_vals:
        return None
    list_id = list_vals[0].strip()
    return list_id or None


def _is_true_playlist_list_id(list_id):
    """True when list= ID looks like a real playlist (not mix/radio RD…)."""
    if not list_id:
        return False
    upper = list_id.upper()
    return any(upper.startswith(prefix) for prefix in PLAYLIST_LIST_PREFIXES)


def is_playlist_url(url):
    """Return True when the URL refers to a YouTube / YouTube Music playlist."""
    url = normalize_media_url(url)
    if not url:
        return False

    parsed = urlparse(url)
    host = _normalize_host(parsed.netloc)
    if not _is_allowed_host(host):
        return False

    path = parsed.path.rstrip('/').lower() or '/'
    list_id = _get_playlist_list_id(parsed)

    # Explicit playlist pages (YouTube + YouTube Music)
    if path == '/playlist' or path.endswith('/playlist'):
        return bool(list_id)

    # Any allowed host with a real playlist list= id (watch, share, music browse…)
    if _is_true_playlist_list_id(list_id):
        return True

    if host.startswith('music.') or host == 'music.youtube.com':
        if path.startswith('/browse/') and list_id:
            return True
        if path.startswith('/playlist'):
            return bool(list_id)

    return False


def canonicalize_playlist_url(url):
    """
    Rewrite watch/share/music URLs with list= to a canonical /playlist?list= URL.

    yt-dlp often returns _type=url (no entries) for watch?v=…&list=PL… links;
    /playlist?list=… extracts entries reliably.
    """
    url = normalize_media_url(url)
    if not url or not is_playlist_url(url):
        return url

    parsed = urlparse(url)
    list_id = _get_playlist_list_id(parsed)
    if not list_id:
        return url

    host = _normalize_host(parsed.netloc)
    if host.startswith('music.') or host == 'music.youtube.com':
        return f'https://music.youtube.com/playlist?list={list_id}'
    return f'https://www.youtube.com/playlist?list={list_id}'


def validate_media_url(url):
    """
    Validate that URL points to an allowed YouTube / YouTube Music host.

    Returns:
        tuple: (is_valid: bool, error_key: str | None)
    """
    url = normalize_media_url(url)
    if not url:
        return False, 'empty_url'

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False, 'invalid_scheme'

    host = _normalize_host(parsed.netloc)
    raw_host = (parsed.netloc or '').lower().split(':')[0]
    if raw_host not in ALLOWED_HOSTS and not _is_allowed_host(host):
        return False, 'invalid_host'

    if host in ('youtu.be',) and not parsed.path.strip('/'):
        return False, 'invalid_url'

    path = parsed.path.rstrip('/').lower() or '/'
    list_id = _get_playlist_list_id(parsed)

    # Playlist URLs are always valid when they carry a list id
    if path == '/playlist' or path.endswith('/playlist'):
        if list_id:
            return True, None
        return False, 'invalid_url'

    if _is_true_playlist_list_id(list_id):
        return True, None

    if host.startswith('music.') or host == 'music.youtube.com':
        if path.strip('/') or list_id:
            return True, None
        return False, 'invalid_url'

    if path.startswith('/watch') or path.startswith('/shorts') or host == 'youtu.be':
        return True, None

    if path in ('/', ''):
        return False, 'invalid_url'

    return False, 'invalid_url'


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
    if not os.path.isabs(base):
        # Defense: avoid Flask send_file resolving relative paths under app.root_path
        project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        base = os.path.join(project_root, base)
    target = os.path.abspath(os.path.join(base, 'media_downloader'))
    os.makedirs(target, exist_ok=True)
    return target


def get_retention_timedelta():
    hours = current_app.config.get('MEDIA_DOWNLOADER_RETENTION_HOURS', 1)
    return timedelta(hours=max(1, int(hours)))


def _get_common_ydl_opts():
    """Shared yt-dlp options for metadata extraction and downloads."""
    max_bytes = current_app.config.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024)
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

    url = canonicalize_playlist_url(normalize_media_url(url))
    if not url:
        return None, 'empty_url'

    def _pull(target_url, opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(target_url, download=False)

    def _materialize_entries(raw):
        if raw is None:
            return None
        try:
            return [e for e in raw]
        except TypeError:
            return []

    def _has_usable_entries(info):
        if not info:
            return False
        materialized = _materialize_entries(info.get('entries'))
        if materialized is None:
            return False
        # Cache list back onto info so generators are not consumed twice
        info['entries'] = materialized
        return any(bool(e) for e in materialized)

    base_opts = _get_common_ydl_opts()
    attempts = [
        {
            **base_opts,
            'extract_flat': True,
            'skip_download': True,
            'noplaylist': False,
            'yes_playlist': True,
            'playlistend': 500,
            'ignoreerrors': True,
        },
        {
            **base_opts,
            'extract_flat': 'in_playlist',
            'skip_download': True,
            'noplaylist': False,
            'ignoreerrors': True,
        },
        {
            **base_opts,
            'skip_download': True,
            'noplaylist': False,
            'yes_playlist': True,
            'playlistend': 200,
            'ignoreerrors': True,
        },
    ]

    info = None
    last_exc = None
    tried_urls = []
    urls_to_try = [url]

    for target_url in urls_to_try:
        if target_url in tried_urls:
            continue
        tried_urls.append(target_url)

        for opts in attempts:
            try:
                candidate = _pull(target_url, opts)
            except Exception as exc:
                last_exc = exc
                logger.warning('Playlist preview attempt failed for %s: %s', target_url, exc)
                continue

            if not candidate:
                continue

            # watch?list=… often returns a redirect stub — follow once
            if candidate.get('_type') == 'url' and candidate.get('url'):
                redirect = normalize_media_url(candidate.get('url'))
                if redirect:
                    redirect = canonicalize_playlist_url(redirect) or redirect
                    if redirect not in tried_urls and redirect not in urls_to_try:
                        urls_to_try.append(redirect)
                info = candidate
                continue

            info = candidate
            if _has_usable_entries(candidate):
                break
        if _has_usable_entries(info):
            break

    if not info:
        if last_exc:
            logger.error('Playlist preview failed for %s: %s', url, last_exc, exc_info=True)
        return None, 'preview_failed'

    entries_raw = _materialize_entries(info.get('entries'))
    if entries_raw is None:
        if info.get('_type') == 'url' and info.get('url'):
            redirect = canonicalize_playlist_url(info.get('url')) or normalize_media_url(info.get('url'))
            if redirect and redirect not in tried_urls:
                try:
                    info = _pull(redirect, attempts[0]) or {}
                    entries_raw = _materialize_entries(info.get('entries'))
                except Exception as exc:
                    logger.warning('Playlist redirect follow failed for %s: %s', redirect, exc)
                    return None, 'preview_failed'
        if entries_raw is None:
            if info.get('_type') == 'playlist':
                entries_raw = []
            else:
                return None, 'not_a_playlist'
    else:
        info['entries'] = entries_raw

    entries = []
    for entry in entries_raw or []:
        if not entry:
            continue

        video_id = (entry.get('id') or '').strip()
        # Flat extracts sometimes put the video id in ie_key/url fields only
        if not video_id:
            raw_url = (entry.get('url') or '').strip()
            if raw_url and not raw_url.startswith(('http://', 'https://')) and '/' not in raw_url:
                video_id = raw_url

        title = (entry.get('title') or '').strip()
        if title in ('[Private video]', '[Deleted video]', '[Unavailable video]'):
            continue

        entry_url = (entry.get('webpage_url') or '').strip()
        if not entry_url:
            entry_url = (entry.get('url') or '').strip()
        if entry_url and not entry_url.startswith(('http://', 'https://')):
            if 'watch?' in entry_url:
                entry_url = f'https://www.youtube.com/{entry_url.lstrip("/")}'
            else:
                # Flat mode: url is often just the video id
                entry_url = f'https://www.youtube.com/watch?v={entry_url}'
        if not entry_url:
            if not video_id:
                continue
            entry_url = f'https://www.youtube.com/watch?v={video_id}'

        # Never keep playlist URLs as entry targets
        if is_playlist_url(entry_url) and video_id:
            entry_url = f'https://www.youtube.com/watch?v={video_id}'

        entries.append({
            'id': video_id or entry_url,
            'title': title or video_id or entry_url,
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
    ydl_opts['noplaylist'] = True

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
        if (
            'sign in to confirm your age' in message
            or 'confirm your age' in message
            or 'age-restricted' in message
            or 'age restricted' in message
        ):
            return False, 'err_age_restricted'
        if 'video is unavailable' in message or 'video unavailable' in message:
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
