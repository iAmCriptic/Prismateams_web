"""Media Downloader utilities (client-side fetch + server FFmpeg conversion)."""
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
    r'C:\ffmpeg\bin\ffmpeg.exe',
    r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
    os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe'),
)


class DownloadCancelledError(Exception):
    """Raised when an active conversion should be cancelled."""


class ConvertError(Exception):
    """Raised when FFmpeg conversion fails."""

    def __init__(self, error_key='err_convert_failed', message=None):
        super().__init__(message or error_key)
        self.error_key = error_key


def normalize_media_url(url):
    """Trim, strip wrapping junk, and ensure http(s) scheme for YouTube URLs."""
    if not url or not str(url).strip():
        return ''

    cleaned = str(url).strip()
    match = re.search(r'https?://[^\s<>"\']+', cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = match.group(0)
    else:
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
    """True when FFmpeg is available (required for server-side conversion)."""
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

    if path == '/playlist' or path.endswith('/playlist'):
        return bool(list_id)

    if _is_true_playlist_list_id(list_id):
        return True

    if host.startswith('music.') or host == 'music.youtube.com':
        if path.startswith('/browse/') and list_id:
            return True
        if path.startswith('/playlist'):
            return bool(list_id)

    return False


def canonicalize_playlist_url(url):
    """Rewrite watch/share/music URLs with list= to a canonical /playlist?list= URL."""
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
        project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        base = os.path.join(project_root, base)
    target = os.path.abspath(os.path.join(base, 'media_downloader'))
    os.makedirs(target, exist_ok=True)
    return target


def get_raw_dir(job_id):
    target = os.path.abspath(os.path.join(get_upload_dir(), 'raw', str(job_id)))
    os.makedirs(target, exist_ok=True)
    return target


def get_retention_timedelta():
    hours = current_app.config.get('MEDIA_DOWNLOADER_RETENTION_HOURS', 1)
    return timedelta(hours=max(1, int(hours)))


def _slugify_title(title, fallback='download'):
    text = (title or fallback).strip() or fallback
    text = re.sub(r'[^\w\s.-]', '', text, flags=re.UNICODE)
    text = re.sub(r'\s+', '_', text).strip('._')
    return (text[:200] or fallback)


def _run_ffmpeg(args, should_cancel=None):
    ffmpeg_path = get_ffmpeg_path()
    if not ffmpeg_path:
        raise ConvertError('incompatible', 'FFmpeg not available')

    cmd = [ffmpeg_path, '-y', '-hide_banner', '-loglevel', 'error', *args]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        while proc.poll() is None:
            if should_cancel and should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise DownloadCancelledError('cancelled')
        stdout, stderr = proc.communicate(timeout=1)
        if proc.returncode != 0:
            logger.error('FFmpeg failed (%s): %s', proc.returncode, stderr or stdout)
            raise ConvertError('err_convert_failed', stderr or stdout)
    except DownloadCancelledError:
        raise
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ConvertError('err_convert_failed', 'FFmpeg timeout')
    except OSError as exc:
        raise ConvertError('err_convert_failed', str(exc)) from exc


def _list_raw_files(raw_dir):
    if not os.path.isdir(raw_dir):
        return []
    files = []
    for name in os.listdir(raw_dir):
        path = os.path.join(raw_dir, name)
        if os.path.isfile(path) and not name.endswith('.part'):
            files.append(path)
    return sorted(files)


def _classify_raw_files(raw_files):
    video_path = None
    audio_path = None
    muxed_path = None

    for path in raw_files:
        base = os.path.basename(path).lower()
        if base.startswith('video.'):
            video_path = path
        elif base.startswith('audio.'):
            audio_path = path
        elif base.startswith('muxed.'):
            muxed_path = path
        elif muxed_path is None:
            muxed_path = path

    return video_path, audio_path, muxed_path


def run_convert(job, should_cancel=None):
    """
    Convert uploaded raw media files for a MediaDownloadJob.

    Returns:
        tuple: (success: bool, error_message: str | None)
    """
    raw_dir = get_raw_dir(job.id)
    raw_files = _list_raw_files(raw_dir)
    if not raw_files:
        return False, 'output_not_found'

    upload_dir = get_upload_dir()
    output_ext = 'mp3' if job.format == 'audio' else 'mp4'
    title_slug = _slugify_title(job.title, f'job_{job.id}')
    output_path = os.path.join(upload_dir, f'{job.id}_{title_slug}.{output_ext}')
    # ASCII temp name with correct extension — FFmpeg uses the suffix for the muxer
    # (e.g. *.mp3.tmp would fail); non-ASCII titles can break FFmpeg on Windows.
    temp_path = os.path.join(upload_dir, f'{job.id}_converting.{output_ext}')

    if os.path.isfile(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    video_path, audio_path, muxed_path = _classify_raw_files(raw_files)
    start_sec = _time_string_to_seconds(job.start_time) if job.start_time else None
    end_sec = _time_string_to_seconds(job.end_time) if job.end_time else None

    try:
        if should_cancel and should_cancel():
            return False, 'cancelled'

        if job.format == 'audio':
            source = audio_path or muxed_path or raw_files[0]
            args = ['-i', source, '-vn', '-codec:a', 'libmp3lame', '-b:a', '192k']
            if start_sec is not None and end_sec is not None:
                args = ['-ss', str(start_sec), '-to', str(end_sec), *args]
            args.append(temp_path)
            _run_ffmpeg(args, should_cancel=should_cancel)
        elif video_path and audio_path:
            args = [
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
            ]
            if start_sec is not None and end_sec is not None:
                args = ['-ss', str(start_sec), '-to', str(end_sec), *args]
            args.extend(['-map', '0:v:0', '-map', '1:a:0', temp_path])
            _run_ffmpeg(args, should_cancel=should_cancel)
        else:
            source = muxed_path or video_path or audio_path or raw_files[0]
            args = ['-i', source, '-c', 'copy', '-movflags', '+faststart']
            if start_sec is not None and end_sec is not None:
                args = ['-ss', str(start_sec), '-to', str(end_sec), *args]
            args.append(temp_path)
            _run_ffmpeg(args, should_cancel=should_cancel)

        if should_cancel and should_cancel():
            if os.path.isfile(temp_path):
                os.remove(temp_path)
            return False, 'cancelled'

        if not os.path.isfile(temp_path):
            return False, 'output_not_found'

        if os.path.isfile(output_path):
            os.remove(output_path)
        os.rename(temp_path, output_path)

        job.filename = os.path.basename(output_path)
        job.file_size = os.path.getsize(output_path)
        job.completed_at = datetime.utcnow()
        job.expires_at = job.completed_at + get_retention_timedelta()
        return True, None
    except DownloadCancelledError:
        if os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, 'cancelled'
    except ConvertError as exc:
        if os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, exc.error_key
    except Exception as exc:
        logger.error('Media convert failed for job %s: %s', job.id, exc, exc_info=True)
        if os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False, 'err_convert_failed'
    finally:
        delete_job_raw_dir(job.id)


def delete_job_raw_dir(job_id):
    """Remove temporary raw upload directory for a job."""
    raw_dir = os.path.join(get_upload_dir(), 'raw', str(job_id))
    if os.path.isdir(raw_dir):
        try:
            shutil.rmtree(raw_dir)
        except OSError as exc:
            logger.warning('Could not delete raw dir %s: %s', raw_dir, exc)


def delete_job_file(job):
    """Remove the physical output file and raw uploads for a job."""
    delete_job_raw_dir(job.id)

    if not job.filename:
        return

    filepath = os.path.join(get_upload_dir(), job.filename)
    if os.path.isfile(filepath):
        try:
            os.remove(filepath)
        except OSError as exc:
            logger.warning('Could not delete media file %s: %s', filepath, exc)

    pattern = os.path.join(get_upload_dir(), f'{job.id}_*')
    for path in glob.glob(pattern):
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


YOUTUBE_PROXY_ALLOWED_SUFFIXES = (
    '.youtube.com',
    '.googlevideo.com',
    '.ggpht.com',
    '.googleusercontent.com',
    '.googleapis.com',
    '.gstatic.com',
    '.ytimg.com',
    'youtubei.googleapis.com',
)

YOUTUBE_PROXY_SKIP_REQUEST_HEADERS = frozenset({
    'host', 'connection', 'content-length', 'transfer-encoding',
})

YOUTUBE_PROXY_IOS_UA = (
    'com.google.ios.youtube/20.11.6 (iPhone10,4; U; CPU iOS 16_7_7 like Mac OS X)'
)
YOUTUBE_PROXY_ANDROID_UA = (
    'com.google.android.youtube/21.03.36'
    '(Linux; U; Android 16; en_US; SM-S908E Build/TP1A.220624.014) gzip'
)

YOUTUBE_PROXY_SKIP_RESPONSE_HEADERS = frozenset({
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'content-encoding',
})

YOUTUBE_PROXY_DEFAULT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)


def is_allowed_youtube_proxy_url(url):
    """Return True when URL may be fetched through the media downloader proxy."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme != 'https':
        return False

    host = (parsed.hostname or '').lower().rstrip('.')
    if not host:
        return False
    if host == 'youtu.be':
        return True

    return any(
        host == suffix.lstrip('.') or host.endswith(suffix)
        for suffix in YOUTUBE_PROXY_ALLOWED_SUFFIXES
    )


def build_youtube_proxy_request(data):
    """
    Build kwargs for requests.request() from a JSON proxy payload.

    Returns:
        tuple: (request_kwargs dict, error_key | None)
    """
    import base64
    import requests

    target_url = (data.get('url') or '').strip()
    if not target_url or not is_allowed_youtube_proxy_url(target_url):
        return None, 'forbidden_host'

    method = (data.get('method') or 'GET').upper()
    if method not in ('GET', 'POST', 'HEAD'):
        return None, 'invalid_method'

    headers = {}
    raw_headers = data.get('headers') or {}
    if isinstance(raw_headers, dict):
        for key, value in raw_headers.items():
            if not key or value is None:
                continue
            lower = key.lower()
            if lower in YOUTUBE_PROXY_SKIP_REQUEST_HEADERS:
                continue
            headers[key] = str(value)

    parsed = urlparse(target_url)
    host = (parsed.hostname or '').lower()
    is_googlevideo = host.endswith('.googlevideo.com')

    if is_googlevideo:
        # Stream URLs are signature-bound to the Innertube client UA. Keep headers minimal.
        range_header = headers.get('Range') or headers.get('range')
        if 'c=IOS' in target_url or 'c=iOS' in target_url:
            headers = {'User-Agent': YOUTUBE_PROXY_IOS_UA, 'Accept': '*/*'}
        elif 'c=ANDROID' in target_url:
            headers = {'User-Agent': YOUTUBE_PROXY_ANDROID_UA, 'Accept': '*/*'}
        else:
            headers = {
                'User-Agent': headers.get('User-Agent') or YOUTUBE_PROXY_DEFAULT_UA,
                'Accept': '*/*',
            }
        if range_header:
            headers['Range'] = range_header
    elif not any(k.lower() == 'user-agent' for k in headers):
        headers['User-Agent'] = YOUTUBE_PROXY_DEFAULT_UA

    body = None
    if method == 'POST':
        encoding = (data.get('encoding') or 'utf8').lower()
        raw_body = data.get('body')
        if raw_body is not None and raw_body != '':
            if encoding == 'base64':
                try:
                    body = base64.b64decode(raw_body)
                except (ValueError, TypeError):
                    return None, 'invalid_body'
            else:
                body = str(raw_body).encode('utf-8')

    return {
        'method': method,
        'url': target_url,
        'headers': headers,
        'data': body,
        'stream': True,
        'timeout': (15, 600),
        'allow_redirects': True,
    }, None


def iter_youtube_proxy_response(requests_response):
    """Yield chunks from a requests response for Flask streaming."""
    try:
        for chunk in requests_response.iter_content(chunk_size=65536):
            if chunk:
                yield chunk
    finally:
        requests_response.close()


YOUTUBEI_JS_VERSION = '18.0.0'
YOUTUBEI_JS_URL = f'https://unpkg.com/youtubei.js@{YOUTUBEI_JS_VERSION}/bundle/browser.js'
YOUTUBEI_JS_MIN_BYTES = 100_000


def youtubei_vendor_path(app=None):
    app = app or current_app
    static_root = app.static_folder or os.path.join(app.root_path, 'static')
    return os.path.join(static_root, 'vendor', 'youtubei.js', 'browser.js')


def ensure_youtubei_vendor(app=None):
    """Download youtubei.js browser bundle if missing (not shipped in git)."""
    import urllib.request

    app = app or current_app
    target = youtubei_vendor_path(app)
    if os.path.isfile(target) and os.path.getsize(target) > YOUTUBEI_JS_MIN_BYTES:
        return target

    os.makedirs(os.path.dirname(target), exist_ok=True)
    req = urllib.request.Request(YOUTUBEI_JS_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if len(data) < YOUTUBEI_JS_MIN_BYTES:
        raise RuntimeError(f'youtubei.js bundle too small ({len(data)} bytes)')
    with open(target, 'wb') as handle:
        handle.write(data)
    logger.info('Downloaded youtubei.js %s browser bundle (%s bytes)', YOUTUBEI_JS_VERSION, len(data))
    return target
