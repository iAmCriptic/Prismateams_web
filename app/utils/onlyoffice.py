"""
Euro-Office / Document Server helpers (ONLYOFFICE-compatible API).

Product branding is Euro-Office; configuration keys remain ONLYOFFICE_* for
compatibility with Document Server JWT and existing deployments.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import current_app, has_request_context, request

try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

_ONLYOFFICE_VERSION_RE = re.compile(
    r'(?:buildVersion["\']?\s*[:=]\s*["\']|ver(?:sion)?\.?\s+)(\d+(?:\.\d+)+)',
    re.IGNORECASE,
)


def is_onlyoffice_enabled():
    """Check if Euro-Office (Document Server) is enabled in configuration."""
    return current_app.config.get('ONLYOFFICE_ENABLED', False)


def get_onlyoffice_document_server_url():
    """
    Return configured Document Server base URL or path.

    Empty values normalize to ``/eurooffice`` (new installs). Legacy
    ``/onlyoffice`` remains valid when set explicitly in .env.
    """
    url = (current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL') or '').strip()
    return url or '/eurooffice'


def get_onlyoffice_secret_key():
    """Return trimmed ONLYOFFICE_SECRET_KEY (empty if unset)."""
    return (current_app.config.get('ONLYOFFICE_SECRET_KEY') or '').strip()


def onlyoffice_allows_unsigned_callbacks():
    """
    Whether callbacks may be accepted without JWT when no secret is configured.

    Compatibility:
    - Document Server with JWT_ENABLED=false needs empty ONLYOFFICE_SECRET_KEY.
    - Auto (config None): allow unsigned only in debug/testing (local setups).
    - Production: reject unsigned unless ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS=true.
    - When ONLYOFFICE_SECRET_KEY is set, JWT is always required (this flag ignored).
    """
    configured = current_app.config.get('ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS')
    if configured is not None:
        return bool(configured)
    return bool(current_app.debug or current_app.testing)


def get_file_mtime(file_path):
    """Return integer mtime for a file path, or 0 if unavailable."""
    if not file_path:
        return 0
    try:
        if os.path.isfile(file_path):
            return int(os.path.getmtime(file_path))
    except OSError:
        pass
    return 0


def build_onlyoffice_document_key(prefix, resource_id, version_token, file_path):
    """
    Build a stable OnlyOffice document key for the current file revision.

    The key stays the same while co-editing one revision (same version_token + mtime)
    and changes after a successful save updates the file on disk.

    Format embeds ``{prefix}{resource_id}-`` so callbacks can bind payload.key to
    the URL resource id and reject cross-file replay.
    """
    mtime = get_file_mtime(file_path)
    rid = int(resource_id)
    raw = f"{prefix}_{rid}_{version_token}_{mtime}"
    digest = hashlib.md5(raw.encode()).hexdigest()
    # OnlyOffice allows [0-9a-zA-Z._=] and '-' ; max length 128
    key = f"{prefix}{rid}-{digest}"
    return key[:128]


def onlyoffice_document_key_matches_resource(key, prefix, resource_id):
    """True if document key was minted for prefix+resource_id."""
    if not key or not prefix:
        return False
    try:
        rid = int(resource_id)
    except (TypeError, ValueError):
        return False
    return str(key).startswith(f"{prefix}{rid}-")


def resolve_storage_path(file_path):
    """Resolve a stored relative path to an absolute filesystem path."""
    if not file_path:
        return None
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(os.getcwd(), file_path)


def get_onlyoffice_internal_base_urls():
    """Return Document Server base URLs the app server can reach."""
    candidates = []
    seen = set()

    def add(url):
        if not url:
            return
        normalized = url.rstrip('/')
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(normalized)

    add('http://127.0.0.1:8080')
    add('http://localhost:8080')
    configured = get_onlyoffice_document_server_url()
    if configured.startswith('http://') or configured.startswith('https://'):
        add(configured)
    return candidates


def send_onlyoffice_command(command, document_key, userdata=None):
    """
    Send a command to the OnlyOffice Command Service.

    Returns (ok, error_code, detail). error_code 0 = success, 4 = no changes.
    """
    if not command or not document_key:
        return False, None, 'missing_params'
    if not REQUESTS_AVAILABLE:
        return False, None, 'requests_missing'

    payload = {'c': command, 'key': document_key}
    if userdata:
        payload['userdata'] = str(userdata)

    headers = {'Content-Type': 'application/json'}
    body = dict(payload)
    secret_key = get_onlyoffice_secret_key()
    if secret_key and JWT_AVAILABLE:
        try:
            token = jwt.encode(payload, secret_key, algorithm='HS256')
            if isinstance(token, bytes):
                token = token.decode('utf-8')
            body['token'] = token
            headers['Authorization'] = f'Bearer {token}'
        except Exception as exc:
            current_app.logger.warning('OnlyOffice command JWT failed: %s', exc)

    last_error = 'unreachable'
    for base in get_onlyoffice_internal_base_urls():
        url = f"{base}/coauthoring/CommandService.ashx"
        try:
            response = requests.post(url, json=body, headers=headers, timeout=8)
            if not response.ok:
                last_error = f'http_{response.status_code}'
                continue
            data = response.json() if response.content else {}
            error_code = data.get('error', 0)
            # 0 = ok, 4 = no changes applied
            if error_code in (0, 4):
                return True, error_code, 'ok'
            last_error = f'error_{error_code}'
            current_app.logger.warning(
                'OnlyOffice command %s for key %s returned %s',
                command, document_key, last_error,
            )
        except Exception:
            current_app.logger.debug(
                'OnlyOffice command %s failed for %s', command, url, exc_info=True
            )
            last_error = 'request_failed'
    return False, None, last_error


def get_onlyoffice_version():
    """Return Document Server version string, or None if unreachable."""
    if not is_onlyoffice_enabled() or not REQUESTS_AVAILABLE:
        return None

    for base in get_onlyoffice_internal_base_urls():
        version = _fetch_onlyoffice_version_from_base(base)
        if version:
            return version
    return None


def _fetch_onlyoffice_version_from_base(base_url):
    """Try info.json, then welcome page, for a Document Server base URL."""
    info_url = f"{base_url.rstrip('/')}/info/info.json"
    try:
        response = requests.get(info_url, timeout=3)
        if response.ok:
            data = response.json()
            server_info = data.get('serverInfo') or {}
            build_version = (server_info.get('buildVersion') or data.get('buildVersion') or '').strip()
            if build_version:
                return build_version
    except Exception:
        current_app.logger.debug('OnlyOffice info.json version lookup failed for %s', info_url, exc_info=True)

    welcome_url = f"{base_url.rstrip('/')}/welcome/"
    try:
        response = requests.get(welcome_url, timeout=3)
        if response.ok and response.text:
            match = _ONLYOFFICE_VERSION_RE.search(response.text)
            if match:
                return match.group(1)
    except Exception:
        current_app.logger.debug('OnlyOffice welcome version lookup failed for %s', welcome_url, exc_info=True)

    return None


def is_onlyoffice_file_type(file_ext):
    """
    Check if a file extension is supported by ONLYOFFICE.
    
    Args:
        file_ext: File extension (e.g., '.docx', '.md')
    
    Returns:
        bool: True if file type is supported by ONLYOFFICE
    """
    if not file_ext:
        return False
    
    # Normalize extension (remove leading dot, convert to lowercase)
    ext = file_ext.lower().lstrip('.')
    
    # Word documents
    word_extensions = {'docx', 'doc', 'odt', 'rtf', 'txt'}
    
    # Excel spreadsheets
    excel_extensions = {'xlsx', 'xls', 'ods', 'csv'}
    
    # PowerPoint presentations
    powerpoint_extensions = {'pptx', 'ppt', 'odp'}
    
    # PDF (view only)
    pdf_extensions = {'pdf'}
    
    # Markdown (with plugin)
    markdown_extensions = {'md', 'markdown'}
    
    # Combine all supported extensions
    supported_extensions = (
        word_extensions | 
        excel_extensions | 
        powerpoint_extensions | 
        pdf_extensions | 
        markdown_extensions
    )
    
    return ext in supported_extensions


def get_onlyoffice_document_type(file_ext):
    """
    Get the ONLYOFFICE document type for a file extension.
    
    Args:
        file_ext: File extension (e.g., '.docx', '.md')
    
    Returns:
        str: Document type ('word', 'cell', 'slide', 'pdf') or None
    """
    if not file_ext:
        return None
    
    ext = file_ext.lower().lstrip('.')
    
    # Word documents
    if ext in {'docx', 'doc', 'odt', 'rtf', 'txt', 'md', 'markdown'}:
        return 'word'
    
    # Excel spreadsheets
    if ext in {'xlsx', 'xls', 'ods', 'csv'}:
        return 'cell'
    
    # PowerPoint presentations
    if ext in {'pptx', 'ppt', 'odp'}:
        return 'slide'
    
    # PDF
    if ext == 'pdf':
        return 'pdf'
    
    return None


def get_onlyoffice_file_type(file_ext):
    """
    Get the ONLYOFFICE file type string for a file extension.
    
    Args:
        file_ext: File extension (e.g., '.docx', '.md')
    
    Returns:
        str: File type string (e.g., 'docx', 'xlsx') or None
    """
    if not file_ext:
        return None
    
    ext = file_ext.lower().lstrip('.')
    
    # Map common extensions to ONLYOFFICE file types
    type_mapping = {
        'docx': 'docx',
        'doc': 'doc',
        'odt': 'odt',
        'rtf': 'rtf',
        'txt': 'txt',
        'md': 'md',
        'markdown': 'md',
        'xlsx': 'xlsx',
        'xls': 'xls',
        'ods': 'ods',
        'csv': 'csv',
        'pptx': 'pptx',
        'ppt': 'ppt',
        'odp': 'odp',
        'pdf': 'pdf'
    }
    
    return type_mapping.get(ext)


def generate_onlyoffice_token(payload):
    """
    Generate a JWT token for ONLYOFFICE Document Server.
    
    Args:
        payload: Dictionary containing the configuration to sign
        
    Returns:
        str: JWT token string, or None if JWT is not available or secret key is not set
    """
    secret_key = get_onlyoffice_secret_key()
    
    # If no secret key is set, return None (token not required / unsigned DS mode)
    if not secret_key:
        current_app.logger.debug("ONLYOFFICE_SECRET_KEY not set, skipping token generation")
        return None
    
    # If JWT library is not available, log warning
    if not JWT_AVAILABLE:
        current_app.logger.warning("PyJWT library not available. Install it with: pip install PyJWT")
        return None
    
    try:
        # OnlyOffice uses HS256 algorithm
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        # jwt.encode returns a string in PyJWT 2.0+, but bytes in older versions
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        current_app.logger.debug(f"ONLYOFFICE token generated successfully (length: {len(token)})")
        return token
    except Exception as e:
        current_app.logger.error(f"Error generating ONLYOFFICE token: {e}")
        return None


_ACCESS_TOKEN_PURPOSE = 'onlyoffice_document'
_ACCESS_TOKEN_DEFAULT_TTL_SECONDS = 3600


def _onlyoffice_access_token_secret():
    """Signing secret for document access tokens (never a hardcoded default)."""
    secret = get_onlyoffice_secret_key() or (current_app.config.get('SECRET_KEY') or '').strip()
    return secret or None


def generate_onlyoffice_access_token(file_id, user_id=None, ttl_seconds=None, share_token=None):
    """
    Generate a signed, time-limited access token for OnlyOffice document download.

    Claims bind the token to a specific resource id (file or attachment) so it
    cannot be reused for another document. Optional share_token binds the token
    to a public share (issued only after share password/guest gate).
    """
    if not JWT_AVAILABLE:
        current_app.logger.error('ONLYOFFICE access token: PyJWT not available')
        return None

    secret_key = _onlyoffice_access_token_secret()
    if not secret_key:
        current_app.logger.error('ONLYOFFICE access token: no signing secret configured')
        return None

    try:
        resource_id = int(file_id)
    except (TypeError, ValueError):
        current_app.logger.error('ONLYOFFICE access token: invalid file_id %r', file_id)
        return None

    if ttl_seconds is None:
        ttl_seconds = int(
            current_app.config.get('ONLYOFFICE_ACCESS_TOKEN_TTL', _ACCESS_TOKEN_DEFAULT_TTL_SECONDS)
        )
    ttl_seconds = max(60, min(int(ttl_seconds), 24 * 3600))

    now = datetime.utcnow()
    payload = {
        'purpose': _ACCESS_TOKEN_PURPOSE,
        'fid': resource_id,
        'uid': int(user_id) if user_id is not None else None,
        'iat': now,
        'exp': now + timedelta(seconds=ttl_seconds),
    }
    if share_token:
        payload['share'] = str(share_token)
    try:
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token
    except Exception as e:
        current_app.logger.error('Error generating ONLYOFFICE access token: %s', e)
        return None


def validate_onlyoffice_access_token(token, file_id, share_token=None):
    """
    Validate a signed OnlyOffice document access token for the given resource id.

    Requires matching purpose claim, matching fid, and a non-expired signature.
    When share_token is provided, the JWT must carry the same share claim
    (tokens minted for authenticated portal use have no share claim).
    """
    if not token:
        current_app.logger.debug('ONLYOFFICE access token validation failed: token is empty')
        return False

    if not JWT_AVAILABLE:
        current_app.logger.error('ONLYOFFICE access token validation failed: PyJWT not available')
        return False

    secret_key = _onlyoffice_access_token_secret()
    if not secret_key:
        current_app.logger.error('ONLYOFFICE access token validation failed: no signing secret')
        return False

    try:
        expected_fid = int(file_id)
    except (TypeError, ValueError):
        current_app.logger.debug('ONLYOFFICE access token validation failed: invalid file_id')
        return False

    try:
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        current_app.logger.debug(
            'ONLYOFFICE access token validation failed: expired (file_id=%s)', expected_fid
        )
        return False
    except jwt.InvalidTokenError as e:
        current_app.logger.debug(
            'ONLYOFFICE access token validation failed: %s (file_id=%s)', e, expected_fid
        )
        return False

    if payload.get('purpose') != _ACCESS_TOKEN_PURPOSE:
        current_app.logger.debug('ONLYOFFICE access token validation failed: wrong purpose')
        return False

    try:
        token_fid = int(payload.get('fid'))
    except (TypeError, ValueError):
        current_app.logger.debug('ONLYOFFICE access token validation failed: missing fid claim')
        return False

    if token_fid != expected_fid:
        current_app.logger.debug(
            'ONLYOFFICE access token validation failed: fid mismatch (%s != %s)',
            token_fid,
            expected_fid,
        )
        return False

    token_share = payload.get('share')
    if share_token is not None:
        if not token_share or str(token_share) != str(share_token):
            current_app.logger.debug(
                'ONLYOFFICE access token validation failed: share claim mismatch'
            )
            return False
    elif token_share:
        current_app.logger.debug(
            'ONLYOFFICE access token validation failed: share token used on non-share endpoint'
        )
        return False

    return True


def verify_onlyoffice_callback_token(raw_body, auth_header=None):
    """
    Verify ONLYOFFICE callback JWT token and return signed payload.

    Behavior:
    - If ONLYOFFICE_SECRET_KEY is set: valid JWT required (Authorization Bearer or body.token).
    - If secret is empty and unsigned callbacks are allowed (dev/test auto, or explicit
      ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS=true): accept body as-is for JWT_ENABLED=false DS.
    - If secret is empty and unsigned is not allowed (production default): reject.
    """
    secret_key = get_onlyoffice_secret_key()
    if not secret_key:
        if onlyoffice_allows_unsigned_callbacks():
            current_app.logger.warning(
                "ONLYOFFICE callback accepted without JWT (no ONLYOFFICE_SECRET_KEY). "
                "For production set ONLYOFFICE_SECRET_KEY to match Document Server JWT_SECRET."
            )
            return True, raw_body, "secret_not_configured_allowed"
        return False, None, "secret_required"

    if not JWT_AVAILABLE:
        return False, None, "jwt_library_missing"

    token = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = (raw_body or {}).get('token', '').strip()
    if not token:
        return False, None, "missing_token"

    try:
        decoded = jwt.decode(token, secret_key, algorithms=['HS256'])
    except Exception:
        return False, None, "invalid_token"

    # ONLYOFFICE commonly signs payload under "payload".
    signed_payload = decoded.get('payload') if isinstance(decoded, dict) else None
    if not isinstance(signed_payload, dict):
        signed_payload = decoded if isinstance(decoded, dict) else {}

    if not isinstance(signed_payload, dict):
        return False, None, "invalid_payload"

    return True, signed_payload, "ok"


def is_onlyoffice_callback_download_url_allowed(saved_file_url):
    """
    Restrict Document Server callback download URL to trusted host(s).

    Prevents arbitrary SSRF while allowing Euro-Office behind a same-host
    proxy (``/eurooffice`` or legacy ``/onlyoffice``, plus ``/cache``).
    """
    if not saved_file_url:
        return False, "empty_url"

    try:
        parsed = urlparse(saved_file_url.strip())
    except Exception:
        return False, "invalid_url"

    if parsed.scheme not in {"http", "https"}:
        return False, "invalid_scheme"
    if not parsed.hostname:
        return False, "missing_host"

    allowed_hosts = set()
    allowed_host_ports = set()

    def add_url_host(url):
        if not url or not (url.startswith('http://') or url.startswith('https://')):
            return
        try:
            parsed_url = urlparse(url)
            host = parsed_url.hostname
            if not host:
                return
            host = host.lower()
            allowed_hosts.add(host)
            if parsed_url.port:
                allowed_host_ports.add((host, parsed_url.port))
        except Exception:
            pass

    def add_host_port(host, port=None):
        if not host:
            return
        host = str(host).lower().strip('[]')
        if not host:
            return
        allowed_hosts.add(host)
        if port:
            try:
                allowed_host_ports.add((host, int(port)))
            except (TypeError, ValueError):
                pass

    configured_ds_url = get_onlyoffice_document_server_url()
    add_url_host(configured_ds_url)
    add_url_host((current_app.config.get('ONLYOFFICE_PUBLIC_URL') or '').strip())
    add_url_host((current_app.config.get('PUBLIC_BASE_URL') or '').strip())

    # Same-host/proxy deployments: relative /eurooffice or /onlyoffice.
    # Document Server often returns https://portal-host/cache/... after save.
    if configured_ds_url.startswith('/'):
        allowed_hosts.update({'localhost', '127.0.0.1', '::1'})
        if has_request_context():
            try:
                parsed_req = urlparse(f'//{request.host}')
                add_host_port(parsed_req.hostname, parsed_req.port)
            except Exception:
                pass

    if not allowed_hosts:
        return False, "no_allowed_hosts_configured"

    target_host = parsed.hostname.lower()
    if target_host not in allowed_hosts:
        return False, "host_not_allowed"

    # If specific port(s) are configured for a host, enforce that port.
    if any(host == target_host for host, _port in allowed_host_ports):
        target_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if (target_host, target_port) not in allowed_host_ports:
            return False, "port_not_allowed"

    return True, "ok"

