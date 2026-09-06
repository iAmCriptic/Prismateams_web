"""Request hooks and CSRF handling."""


from flask import flash, jsonify, redirect, request, session, url_for as flask_url_for
from flask_wtf.csrf import CSRFError

from app import db
from app.factory._util import is_same_origin as _is_same_origin
from app.utils.i18n import translate

def register_request_hooks(app):
    """before_request guards, CSRF error page, indexing headers."""
    @app.before_request
    def redirect_loopback_ip_to_localhost():
        """Passkeys/WebAuthn: Browser lehnen 127.0.0.1 ab — lokal auf localhost umleiten."""
        if not app.debug:
            return
        from flask import redirect
        host = (request.host or '').split(':')[0].lower()
        if host != '127.0.0.1':
            return
        port = request.host.split(':', 1)[1] if ':' in (request.host or '') else ''
        target_host = f'localhost:{port}' if port else 'localhost'
        scheme = request.headers.get('X-Forwarded-Proto', request.scheme or 'http')
        path = request.full_path
        if path.endswith('?') and not request.query_string:
            path = path[:-1]
        return redirect(f'{scheme}://{target_host}{path}', code=302)

    @app.before_request
    def prune_session_bloat():
        """Begrenzt große Session-Keys (Share-Passwords, Auth-Flags, Cart)."""
        if request.path.startswith('/socket.io/'):
            return
        try:
            from flask import session as flask_session
            from app.utils.server_session import prune_bulky_session_keys
            prune_bulky_session_keys(flask_session)
        except Exception:
            pass

    @app.before_request
    def csrf_same_origin_guard():
        """
        CSRF mitigation without breaking existing forms/AJAX:
        enforce same-origin on state-changing requests.
        """
        if request.method in {'GET', 'HEAD', 'OPTIONS', 'TRACE'}:
            return

        # Ignore Socket.IO transport paths.
        if request.path.startswith('/socket.io/'):
            return

        endpoint = request.endpoint or ''

        # Machine callbacks/webhooks and token/public paths are excluded.
        if (
            endpoint.startswith('files.onlyoffice') or
            endpoint.startswith('files.share_onlyoffice') or
            endpoint.startswith('kanban.onlyoffice') or
            request.path.startswith('/onlyoffice') or
            '/onlyoffice-callback' in request.path
        ):
            return

        origin = request.headers.get('Origin', '')
        referer = request.headers.get('Referer', '')
        sec_fetch_site = (request.headers.get('Sec-Fetch-Site') or '').strip().lower()
        host = request.host

        if origin:
            if _is_same_origin(origin, host):
                return
            app.logger.warning("CSRF blocked by Origin mismatch: %s -> %s", origin, host)
            return jsonify({'error': 'CSRF validation failed'}), 403

        if referer:
            if _is_same_origin(referer, host):
                return
            app.logger.warning("CSRF blocked by Referer mismatch: %s -> %s", referer, host)
            return jsonify({'error': 'CSRF validation failed'}), 403

        # Einige Reverse-Proxy/Client-Kombinationen senden kein Origin/Referer.
        # Dann greift CSRFProtect (Token). Sec-Fetch-Site allein reicht nicht mehr.
        if sec_fetch_site in {'same-origin', 'same-site'}:
            return

        app.logger.warning("CSRF blocked: missing Origin/Referer for %s %s", request.method, request.path)
        return jsonify({'error': 'CSRF validation failed'}), 403

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        app.logger.warning("CSRFProtect rejected %s %s: %s", request.method, request.path, error.description)
        wants_json = (
            request.is_json
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in (request.accept_mimetypes.best or '')
        )
        if wants_json:
            return jsonify({'error': 'CSRF validation failed', 'detail': error.description}), 400
        flash('Sicherheitsprüfung fehlgeschlagen. Bitte laden Sie die Seite neu und versuchen Sie es erneut.', 'danger')
        target = request.referrer if request.referrer and _is_same_origin(request.referrer, request.host) else None
        return redirect(target or flask_url_for('dashboard.index'))

    @app.before_request
    def check_email_confirmation():
        """Prüft E-Mail-Bestätigung für alle Routen außer Auth und Setup."""
        from flask import request, redirect, url_for, flash
        from flask_login import current_user

        if session.get('user_scope') == 'assessment':
            if request.path.startswith('/assessment'):
                return
            if request.endpoint in {'auth.login', 'auth.logout', 'manifest', 'static'}:
                return
            return redirect(url_for('assessment.general.home'))
        
        # WICHTIG: Socket.IO-Requests ausschließen (verhindert 401-Fehler)
        # Socket.IO verwendet /socket.io/ als Pfad und hat keinen normalen Endpoint
        if request.path.startswith('/socket.io/'):
            return
        
        # Öffentliche Musikwunschliste-Route ausschließen (keine Authentifizierung erforderlich)
        if request.path.startswith('/music/wishlist'):
            return
        
        if (request.endpoint and 
            (request.endpoint.startswith('auth.') or 
             request.endpoint.startswith('setup.') or
             request.endpoint.startswith('static') or
             request.endpoint.startswith('api.') or
             request.endpoint.startswith('files.onlyoffice') or
             request.endpoint.startswith('files.share_onlyoffice') or
             request.endpoint.startswith('booking.public') or
             request.endpoint.startswith('booking.public_') or
             request.endpoint == 'booking.public_booking' or
             request.endpoint == 'booking.public_form' or
             request.endpoint == 'booking.public_view' or
             request.endpoint == 'manifest' or
             request.endpoint == 'settings.portal_logo' or
             request.endpoint == 'settings.auth_brand_image' or
             request.endpoint == 'music.public_wishlist' or
             request.endpoint == 'music.public_search' or
             request.endpoint.startswith('surveys.public_') or
             request.endpoint == 'surveys.public_fill' or
             request.endpoint == 'surveys.public_done' or
             request.endpoint == 'surveys.public_header' or
             request.endpoint == 'shortlinks.resolve')):
            return
        
        if not current_user.is_authenticated:
            return
        
        if not current_user.is_email_confirmed:
            if request.endpoint == 'auth.confirm_email':
                return
            flash('Bitte bestätigen Sie Ihre E-Mail-Adresse, um fortzufahren.', 'info')
            return redirect(url_for('auth.confirm_email'))

    @app.before_request
    def ensure_portal_session_tracking():
        """Portal: user_sessions; Assessment: kürzere Session-Lifetime per Flask-Session."""
        from flask import redirect, url_for, flash
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return

        # Socket.IO-Handshake/Events sind keine klassischen HTTP-Seitenaufrufe.
        if request.path.startswith('/socket.io/'):
            return

        if request.endpoint and request.endpoint.startswith('static'):
            return

        # Assessment-Logins: separates Tracking (kein FK auf users.id).
        if session.get('user_scope') == 'assessment':
            from datetime import datetime, timedelta
            from app.utils.session_manager import (
                assessment_session_is_expired,
                touch_assessment_session,
                rotate_session_on_login,
            )

            try:
                if not getattr(current_user, 'is_active', True):
                    logout_user()
                    rotate_session_on_login()
                    return redirect(url_for('auth.login'))

                if not session.get('assessment_session_started'):
                    # Remember-/Restored-Session ohne Tracking → neu starten nicht erlaubt
                    logout_user()
                    rotate_session_on_login()
                    flash(translate('settings.admin.system.flash_inactivity_logout'), 'info')
                    return redirect(url_for('auth.login'))

                expired, _reason = assessment_session_is_expired(
                    app.config.get('ASSESSMENT_SESSION_MAX_HOURS', 12),
                    app.config.get('ASSESSMENT_SESSION_INACTIVITY_HOURS', 8),
                )
                if expired:
                    logout_user()
                    rotate_session_on_login()
                    flash(translate('settings.admin.system.flash_inactivity_logout'), 'info')
                    return redirect(url_for('auth.login'))

                last = session.get('assessment_last_activity')
                try:
                    last_dt = datetime.fromisoformat(str(last)) if last else None
                except (TypeError, ValueError):
                    last_dt = None
                if not last_dt or (datetime.utcnow() - last_dt) >= timedelta(minutes=1):
                    touch_assessment_session()
            except Exception as exc:
                app.logger.warning("Assessment-Session-Tracking fehlgeschlagen: %s", exc)
            return

        # Setup-Wizard: Session-Tracking erst nach Abschluss erzwingen.
        # Sonst landet man nach Admin-Anlage (login_user ohne session_id) sofort auf /login.
        if request.endpoint and request.endpoint.startswith('setup.'):
            return

        from app.utils.session_manager import revoke_all_sessions
        from app.utils.common import portal_now_naive

        try:
            # Abgelaufene Gast-Accounts sofort deaktivieren und abmelden.
            if getattr(current_user, 'is_guest', False) and current_user.guest_expires_at:
                if portal_now_naive() > current_user.guest_expires_at:
                    if current_user.is_active:
                        current_user.is_active = False
                        revoke_all_sessions(current_user.id, exclude_current=False)
                        db.session.commit()
                    logout_user()
                    session.clear()
                    if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                        return jsonify({'error': 'Guest access expired'}), 401
                    flash(translate('auth.flash.guest_access_expired_contact_admin'), 'warning')
                    return redirect(url_for('auth.login'))

            if not getattr(current_user, 'is_active', True):
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Account deactivated'}), 401
                return redirect(url_for('auth.login'))

            current_session_id = session.get('session_id')
            if not current_session_id:
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    return jsonify({'error': 'Session invalidated'}), 401
                return redirect(url_for('auth.login'))

            from app.utils.session_manager import touch_portal_session_cached

            status, reason = touch_portal_session_cached(current_user.id)
            if status == 'invalid':
                logout_user()
                session.clear()
                if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
                    err = (
                        'Session expired due to inactivity'
                        if reason == 'inactivity'
                        else 'Session invalidated'
                    )
                    return jsonify({'error': err}), 401
                if reason == 'inactivity':
                    flash(translate('settings.admin.system.flash_inactivity_logout'), 'info')
                return redirect(url_for('auth.login'))
        except Exception as exc:
            app.logger.warning("Session-Tracking konnte nicht aktualisiert werden: %s", exc)

    @app.after_request
    def apply_search_indexing_headers(response):
        if request.endpoint in ('robots_txt', 'sitemap_xml'):
            return response
        mimetype = response.mimetype or ''
        if 'html' not in mimetype:
            return response
        try:
            from app.utils.search_indexing import robots_meta_content
            response.headers.setdefault('X-Robots-Tag', robots_meta_content())
        except Exception:
            pass
        return response
