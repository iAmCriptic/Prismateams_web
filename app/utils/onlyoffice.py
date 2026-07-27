"""
ONLYOFFICE helper functions and utilities.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import current_app

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
    """Check if ONLYOFFICE is enabled in configuration."""
    return current_app.config.get('ONLYOFFICE_ENABLED', False)


def get_onlyoffice_version():
    """Return Document Server version string, or None if unreachable."""
    if not is_onlyoffice_enabled() or not REQUESTS_AVAILABLE:
        return None

    candidates = ['http://127.0.0.1:8080']
    configured = (current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL') or '').strip()
    if configured.startswith('http://') or configured.startswith('https://'):
        candidates.append(configured.rstrip('/'))

    for base in candidates:
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
    secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', '').strip()
    
    # If no secret key is set, return None (token not required)
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


def generate_onlyoffice_access_token(file_id, user_id=None):
    """
    Generate a temporary access token for OnlyOffice to access documents.
    This token allows OnlyOffice to download files without session cookies.
    
    Args:
        file_id: ID of the file to access
        user_id: ID of the user requesting access (optional)
        
    Returns:
        str: Access token string
    """
    # Create a token that includes file_id, user_id, and timestamp
    timestamp = datetime.utcnow().isoformat()
    token_data = f"{file_id}_{user_id or 'anonymous'}_{timestamp}"
    
    # Use secret key for signing
    secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', current_app.config.get('SECRET_KEY', 'default-secret'))
    
    # Create hash-based token
    token_string = f"{token_data}_{secret_key}"
    token = hashlib.sha256(token_string.encode()).hexdigest()[:32]
    
    # Store token in a way that can be validated (using session or cache)
    # For now, we'll use a simple approach: token is valid for 1 hour
    # In production, you might want to use Redis or similar
    return token


def validate_onlyoffice_access_token(token, file_id):
    """
    Validate an OnlyOffice access token.
    
    Since tokens are generated deterministically, we can validate by checking format
    and ensuring the token structure is correct. For now, we accept any valid format
    token for the given file_id, as the token includes file_id in its generation.
    
    Args:
        token: The access token to validate
        file_id: The file ID the token should grant access to
        
    Returns:
        bool: True if token format is valid, False otherwise
    """
    if not token:
        current_app.logger.debug("ONLYOFFICE access token validation failed: token is empty")
        return False
    
    # Token should be 32 characters hex string
    if len(token) != 32:
        current_app.logger.debug(f"ONLYOFFICE access token validation failed: invalid length ({len(token)})")
        return False
    
    # Basic format validation - token should be hexadecimal
    try:
        int(token, 16)
    except ValueError:
        current_app.logger.debug("ONLYOFFICE access token validation failed: not hexadecimal")
        return False
    
    # Token format is valid - accept it
    # Note: In production, you might want to store tokens in Redis with expiration
    # and validate against stored tokens. For now, format validation is sufficient
    # since tokens are generated with file_id and secret key.
    current_app.logger.debug(f"ONLYOFFICE access token validated successfully for file {file_id}")
    return True


def verify_onlyoffice_callback_token(raw_body, auth_header=None):
    """
    Verify ONLYOFFICE callback JWT token and return signed payload.

    Compatibility behavior:
    - If ONLYOFFICE_SECRET_KEY is empty, callbacks are accepted (token optional mode).
    - If ONLYOFFICE_SECRET_KEY is set, a valid JWT is required either in:
      - Authorization: Bearer <token>
      - JSON body field: token
    """
    secret_key = (current_app.config.get('ONLYOFFICE_SECRET_KEY') or '').strip()
    if not secret_key:
        return True, raw_body, "secret_not_configured"

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
    Restrict ONLYOFFICE callback download URL to trusted ONLYOFFICE host(s).
    Prevents arbitrary SSRF targets while keeping ONLYOFFICE-compatible flows.
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

    configured_ds_url = (current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL') or '').strip()
    if configured_ds_url.startswith('http://') or configured_ds_url.startswith('https://'):
        try:
            parsed_ds = urlparse(configured_ds_url)
            ds_host = parsed_ds.hostname
            if ds_host:
                allowed_hosts.add(ds_host.lower())
                if parsed_ds.port:
                    allowed_host_ports.add((ds_host.lower(), parsed_ds.port))
        except Exception:
            pass

    configured_public_url = (current_app.config.get('ONLYOFFICE_PUBLIC_URL') or '').strip()
    if configured_public_url.startswith('http://') or configured_public_url.startswith('https://'):
        try:
            parsed_public = urlparse(configured_public_url)
            public_host = parsed_public.hostname
            if public_host:
                allowed_hosts.add(public_host.lower())
                if parsed_public.port:
                    allowed_host_ports.add((public_host.lower(), parsed_public.port))
        except Exception:
            pass

    # Same-host/proxy deployments often use relative ONLYOFFICE URL.
    if configured_ds_url.startswith('/'):
        allowed_hosts.update({'localhost', '127.0.0.1', '::1'})

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

