"""Template context and Jinja filters."""


from datetime import datetime

from flask import request, session, url_for as flask_url_for, g
from flask_login import current_user

from app.utils import format_datetime, format_time

def register_template_helpers(app):
    """Context processors and Jinja filters."""
    def _asset_version():
        build = str(app.config.get('ABOUT_BUILD_NUMBER') or '').strip()
        release = str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip()
        return build or release or 'dev'

    def versioned_url_for(endpoint, **values):
        """Jinja url_for with cache-busting query for static assets."""
        if endpoint in ('static', 'core_css'):
            values.setdefault('v', _asset_version())
        return flask_url_for(endpoint, **values)

    @app.context_processor
    def inject_versioned_url_for():
        return {
            'url_for': versioned_url_for,
            'asset_version': _asset_version(),
            'app_version': str(app.config.get('ABOUT_RELEASE_VERSION') or '').strip() or 'unknown',
        }
    
    @app.context_processor
    def inject_app_config():
        from app.utils.common import is_module_enabled
        from app.utils.access_control import has_module_access
        from app.utils.multi_mailboxes import is_email_multi_enabled
        from app.utils.system_settings_cache import get_setting
        from flask_login import current_user
        app_name = app.config.get('APP_NAME', 'Prismateams')
        app_logo = app.config.get('APP_LOGO')
        color_gradient = None
        portal_logo_filename = None
        
        try:
            portal_name = get_setting('portal_name')
            if portal_name and str(portal_name).strip():
                app_name = str(portal_name).strip()
            else:
                org_name = get_setting('organization_name')
                if org_name and str(org_name).strip():
                    app_name = str(org_name).strip()
                else:
                    app_name = app.config.get('APP_NAME', 'Prismateams')

            portal_logo = get_setting('portal_logo')
            if portal_logo:
                portal_logo_filename = portal_logo
                app_logo = None

            gradient = get_setting('color_gradient')
            if gradient:
                color_gradient = gradient
        except Exception:
            pass

        if app_logo and app_logo.startswith('static/'):
            app_logo = app_logo[7:]

        from app.utils.onlyoffice import is_onlyoffice_enabled
        from app.utils.auth_branding import get_auth_branding_context

        onlyoffice_available = is_onlyoffice_enabled()
        auth_branding = get_auth_branding_context()

        def get_chat_display_name(chat):
            """Display name for a chat. Uses eager-loaded members / request cache."""
            if not chat:
                return ''
            cache = g.setdefault('_chat_display_name', {})
            cached = cache.get(chat.id)
            if cached is not None:
                return cached
            from app.utils.chat_nav import display_name_for_chat
            uid = current_user.id if current_user.is_authenticated else None
            name = display_name_for_chat(chat, uid)
            cache[chat.id] = name
            return name

        def get_other_chat_user(chat):
            """Other user in a DM. Uses eager-loaded members / request cache."""
            if not chat:
                return None
            cache = g.setdefault('_other_chat_user', {})
            if chat.id in cache:
                return cache[chat.id]
            from app.utils.chat_nav import other_user_for_chat
            uid = current_user.id if current_user.is_authenticated else None
            user = other_user_for_chat(chat, uid)
            cache[chat.id] = user
            return user
        
        mobile_nav_slots = None
        mobile_nav_left = None
        mobile_nav_right = None
        desktop_nav_modules = []
        desktop_nav_favorites = []
        current_nav_module = None
        nav_storage_usage = None
        # Assessment-Scope: keine Portal-Mobile-Nav (nur Modul-Sidebar inkl. Logout).
        if current_user.is_authenticated and session.get('user_scope') != 'assessment':
            from flask import request as _req
            from app.utils.navigation import (
                get_current_nav_module,
                get_desktop_nav_modules,
                get_mobile_nav_slots,
                get_nav_favorites,
                resolve_nav_link,
            )
            mobile_nav_slots = get_mobile_nav_slots(current_user)
            mobile_nav_left = resolve_nav_link(mobile_nav_slots['left'], current_user)
            mobile_nav_right = resolve_nav_link(mobile_nav_slots['right'], current_user)
            desktop_nav_modules = get_desktop_nav_modules(current_user)
            desktop_nav_favorites = get_nav_favorites(current_user)
            current_nav_module = get_current_nav_module(_req.endpoint, current_user)
            try:
                from app.utils.file_storage_limits import is_quota_enabled, usage_payload_for_user
                # P24: keine SUM-Queries wenn Quota aus; sonst TTL-/Request-Cache
                if is_quota_enabled():
                    nav_storage_usage = usage_payload_for_user(current_user.id)
                    if not nav_storage_usage.get('quota_enabled'):
                        nav_storage_usage = None
            except Exception:
                nav_storage_usage = None

        can_compose_email = False
        if current_user.is_authenticated:
            try:
                can_compose_email = bool(
                    is_module_enabled('module_email')
                    and has_module_access(current_user, 'module_email')
                )
            except Exception:
                can_compose_email = False

        robots_meta = 'noindex, nofollow'
        try:
            from app.utils.search_indexing import robots_meta_content
            robots_meta = robots_meta_content()
        except Exception:
            pass

        passkeys_supported = False
        passkeys_localhost_url = None
        try:
            from app.utils.webauthn_helper import passkeys_supported_for_request, localhost_passkey_url
            passkeys_supported = passkeys_supported_for_request()
            passkeys_localhost_url = localhost_passkey_url()
        except Exception:
            pass

        return {
            'app_name': app_name,
            'app_logo': app_logo,
            'color_gradient': color_gradient,
            'portal_logo_filename': portal_logo_filename,
            **auth_branding,
            'onlyoffice_available': onlyoffice_available,
            'is_module_enabled': is_module_enabled,
            'is_email_multi_enabled': is_email_multi_enabled,
            'has_module_access': has_module_access,
            'can_compose_email': can_compose_email,
            'get_chat_display_name': get_chat_display_name,
            'get_other_chat_user': get_other_chat_user,
            'mobile_nav_slots': mobile_nav_slots,
            'mobile_nav_left': mobile_nav_left,
            'mobile_nav_right': mobile_nav_right,
            'desktop_nav_modules': desktop_nav_modules,
            'desktop_nav_favorites': desktop_nav_favorites,
            'current_nav_module': current_nav_module,
            'nav_storage_usage': nav_storage_usage,
            'robots_meta': robots_meta,
            'passkeys_supported': passkeys_supported,
            'passkeys_localhost_url': passkeys_localhost_url,
        }
    
    @app.template_filter('decode_email_header')
    def decode_email_header_filter(header):
        """Decode email header fields properly."""
        if not header:
            return ''
        
        try:
            from email.header import decode_header
            decoded_parts = decode_header(str(header))
            decoded_string = ''
            
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    if encoding:
                        decoded_string += part.decode(encoding)
                    else:
                        decoded_string += part.decode('utf-8', errors='ignore')
                else:
                    decoded_string += str(part)
            
            return decoded_string.strip()
        except Exception:
            return str(header)
    
    @app.template_filter('email_sender_initials')
    def email_sender_initials_filter(sender):
        """Initialen für Avatar: Anzeigenamen ohne Anführungszeichen, Vorname+Nachname wenn möglich."""
        if not sender:
            return '??'

        def _strip_outer_quotes(s: str) -> str:
            t = (s or '').strip()
            while len(t) >= 2 and t[0] in '"\'' and t[-1] == t[0]:
                t = t[1:-1].strip()
            return t

        def _initials_from_local_part(local: str) -> str:
            alnum = ''.join(c for c in (local or '') if c.isalnum())
            if len(alnum) >= 2:
                return alnum[0:2].upper()
            if len(alnum) == 1:
                return (alnum[0] * 2).upper()
            return '??'

        try:
            import re

            decoded = decode_email_header_filter(sender).strip()
            display = ''
            addr = ''

            m = re.match(r'^(?P<dn>.*?)\s*<(?P<em>[^>\s]+@[^>\s]+)>\s*$', decoded, re.DOTALL)
            if m:
                display = (m.group('dn') or '').strip()
                addr = (m.group('em') or '').strip()
            elif re.match(r'^[^\s<]+@[^\s>]+$', decoded):
                addr = decoded.strip()
            else:
                display = decoded

            display = _strip_outer_quotes(display)

            parts = [p for p in re.split(r'\s+', display) if p]
            if len(parts) >= 2:
                return (parts[0][0] + parts[-1][0]).upper()
            if len(parts) == 1:
                w = parts[0]
                if len(w) >= 2:
                    return w[0:2].upper()
                if len(w) == 1:
                    return (w[0] * 2).upper()
            if addr and '@' in addr:
                return _initials_from_local_part(addr.split('@', 1)[0])
            if display and '@' in display:
                return _initials_from_local_part(display.split('@', 1)[0])
            return '??'
        except Exception:
            return '??'
    
    
    from app.utils import format_time, format_datetime
    
    @app.template_filter('localtime')
    def localtime_filter(dt, format_string='%H:%M'):
        """Filter to format datetime in local timezone."""
        return format_time(dt, format_string)
    
    @app.template_filter('localdatetime')
    def localdatetime_filter(dt, format_string='%d.%m.%Y %H:%M'):
        """Filter to format datetime in local timezone."""
        return format_datetime(dt, format_string)
    
    @app.template_filter('smart_datetime')
    def smart_datetime_filter(dt):
        """Smart datetime formatting: Today shows time only, Yesterday shows 'Gestern HH:MM', older shows date."""
        if not dt:
            return ''
        
        from app.utils.common import get_local_time, now_in_portal_timezone
        
        local_dt = get_local_time(dt)
        if isinstance(local_dt, str):
            try:
                local_dt = datetime.fromisoformat(local_dt.replace('Z', '+00:00'))
            except:
                return str(dt)
        
        now = now_in_portal_timezone()
        today = now.date()
        message_date = local_dt.date()
        
        days_diff = (today - message_date).days
        
        if days_diff == 0:
            return local_dt.strftime('%H:%M')
        elif days_diff == 1:
            return f"Gestern {local_dt.strftime('%H:%M')}"
        else:
            return local_dt.strftime('%d.%m.%Y %H:%M')
    
    @app.template_filter('markdown')
    def markdown_filter(text):
        """Filter to render markdown text."""
        try:
            from app.utils.markdown import process_markdown
            return process_markdown(text, wiki_mode=False)
            
        except Exception as e:
            from flask import current_app
            current_app.logger.warning(f"Markdown processing failed: {e}, using plain text fallback")
            return text.replace('\n', '<br>')
