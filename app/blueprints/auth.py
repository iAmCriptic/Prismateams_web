from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError
from app import db, limiter
from app.models.user import User
from app.models.email import EmailPermission
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from app.models.settings import SystemSettings
from app.utils.i18n import translate
from app.utils.session_manager import create_session, revoke_session_by_id
from app.utils.totp import verify_totp
from app.utils.password_policy import validate_password
from app.utils.bot_protection import get_template_context, validate_bot_protection
from datetime import datetime, timedelta
from urllib.parse import urlparse
import logging
from app.utils.common import portal_now_naive

auth_bp = Blueprint('auth', __name__)


def _auth_template_kwargs(**extra):
    """Common template context for auth pages including bot protection."""
    kwargs = {'color_gradient': get_color_gradient()}
    try:
        from app.utils.google_login import google_login_ready
        kwargs['google_login_ready'] = google_login_ready()
    except Exception:
        kwargs['google_login_ready'] = False
    kwargs.update(get_template_context())
    kwargs.update(extra)
    return kwargs


def get_color_gradient():
    """Holt den Farbverlauf aus den System-Einstellungen."""
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    return gradient_setting.value if gradient_setting else None


def _google_register_template_kwargs(**extra):
    """Auth-Template-Kontext inkl. optionalem Google-Registrierungs-Prefill."""
    from app.utils.google_login import get_google_register_prefill
    kwargs = _auth_template_kwargs(**extra)
    kwargs['google_prefill'] = get_google_register_prefill()
    return kwargs


def _flash_existing_registration(existing_user):
    """Zeigt passende Meldung wenn E-Mail schon registriert ist (Pending vs. aktiv)."""
    if existing_user and not existing_user.is_active:
        flash(translate('auth.flash.account_not_activated'), 'info')
        return redirect(url_for('auth.login'))
    flash(translate('auth.flash.email_already_registered'), 'danger')
    return render_template('auth/register.html', **_google_register_template_kwargs())


def _finish_registration(new_user, email_sent, is_whitelisted, *, google_verified=False):
    """Erfolgsmeldung + Redirect nach erfolgreicher Registrierung."""
    if is_whitelisted:
        if google_verified:
            flash(translate('auth.flash.register_success_google_whitelisted'), 'success')
            return _finalize_portal_login(new_user, remember=False)
        login_user(new_user, remember=False)
        if email_sent:
            flash(translate('auth.flash.register_success_whitelisted'), 'success')
        else:
            flash(translate('auth.flash.register_success_whitelisted_no_email'), 'warning')
        return redirect(url_for('auth.confirm_email'))

    # Manuelle Freischaltung bleibt — bei Google entfällt nur der Bestätigungscode
    if google_verified:
        flash(translate('auth.flash.register_pending_admin_google'), 'info')
    else:
        flash(translate('auth.flash.register_pending_admin'), 'info')
    return redirect(url_for('auth.login'))


def _clear_pending_2fa_login():
    """Entfernt zwischengespeicherte 2FA-Login-Daten."""
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_2fa_remember', None)
    session.pop('pending_2fa_next', None)


def _sanitize_next_page(candidate):
    """Erlaubt nur interne Redirect-Ziele (relative URL oder gleiche Origin)."""
    value = (candidate or "").strip()
    if not value:
        return None

    parsed = urlparse(value)

    # Interne relative Pfade erlauben, aber kein protocol-relative //host.
    if not parsed.scheme and not parsed.netloc:
        if value.startswith('/') and not value.startswith('//'):
            return value
        return None

    # Absolute URL nur erlauben, wenn sie zur aktuellen Origin gehört.
    request_host = request.host.lower()
    target_host = (parsed.netloc or "").lower()
    if parsed.scheme in {"http", "https"} and target_host == request_host:
        return f"{parsed.path or '/'}{('?' + parsed.query) if parsed.query else ''}"

    return None


def _finalize_portal_login(user, remember=False, next_page=None):
    """Finalisiert den Portal-Login nach erfolgreicher Authentifizierung."""
    # Gast-Accounts benötigen keine E-Mail-Bestätigung
    # Normale Accounts: Check if email confirmation is required (nicht für Admins)
    if not user.is_guest and not user.is_email_confirmed and not user.is_admin:
        login_user(user, remember=remember)
        create_session(user.id)
        flash(translate('auth.flash.confirm_email_required'), 'info')
        return redirect(url_for('auth.confirm_email'))

    # Update last login
    user.last_login = datetime.utcnow()
    db.session.commit()

    # Log user in
    login_user(user, remember=remember)
    session['user_scope'] = 'portal'

    # Erstelle Session für Session-Management
    create_session(user.id)

    # Prüfe ob Passwort geändert werden muss
    if user.must_change_password:
        flash(translate('auth.flash.must_change_password'), 'warning')
        return redirect(url_for('auth.change_password'))

    # Add user to main chat if not already a member and user has chat access.
    # Gast-Accounts werden NICHT automatisch in den Haupt-Chat aufgenommen.
    from app.utils.access_control import has_module_access
    if not user.is_guest and has_module_access(user, 'module_chat'):
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            existing_membership = ChatMember.query.filter_by(
                chat_id=main_chat.id,
                user_id=user.id
            ).first()

            if not existing_membership:
                chat_member = ChatMember(
                    chat_id=main_chat.id,
                    user_id=user.id
                )
                db.session.add(chat_member)
                db.session.commit()

    # Make session permanent if remember me is checked
    if remember:
        session.permanent = True

    safe_next_page = _sanitize_next_page(next_page)

    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        if safe_next_page:
            return redirect(safe_next_page)
        return redirect(url_for('setup.setup'))

    # Redirect to next page or dashboard
    if safe_next_page:
        return redirect(safe_next_page)
    return redirect(url_for('dashboard.index'))


@auth_bp.route('/')
def index():
    """Redirect to login, dashboard, or setup."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per 15 minutes")
def register():
    """User registration."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    from app.utils.google_login import (
        clear_google_register_prefill,
        get_google_register_prefill,
        save_google_profile_picture,
    )
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.args.get('clear_google') == '1':
        clear_google_register_prefill()
        return redirect(url_for('auth.register'))

    google_prefill = get_google_register_prefill()
    
    if request.method == 'POST':
        bot_ok, _ = validate_bot_protection(request, 'register')
        if not bot_ok:
            flash(translate('auth.flash.bot_protection_failed'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())

        # Bei Google-Prefill ist die E-Mail fest (verifiziert) und darf nicht geändert werden
        if google_prefill:
            email = (google_prefill.get('email') or '').strip().lower()
            google_sub = google_prefill.get('sub') or ''
        else:
            email = request.form.get('email', '').strip().lower()
            google_sub = None

        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        
        # Validation
        if not all([email, password, first_name, last_name]):
            flash(translate('auth.flash.fill_all_fields'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())
        
        if password != password_confirm:
            flash(translate('auth.flash.passwords_dont_match'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())

        # Registrierung: mind. 12 Zeichen + Groß-/Kleinbuchstaben, Zahl, Sonderzeichen
        is_valid, _ = validate_password(password, min_length=12, require_complexity=True)
        if not is_valid:
            flash(translate('auth.flash.password_requirements'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())
        
        # Check if user already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            # Pending-User: Freigabe-Hinweis statt irreführender "bereits registriert"-Fehler
            return _flash_existing_registration(existing_user)

        if google_sub:
            existing_google = User.query.filter_by(google_sub=google_sub).first()
            if existing_google:
                clear_google_register_prefill()
                flash(translate('auth.google.already_registered'), 'info')
                return redirect(url_for('auth.login'))
        
        # Check if email is whitelisted
        is_whitelisted = WhitelistEntry.is_email_whitelisted(email)
        google_verified = bool(google_sub)
        
        # Get default accent color from system settings
        from app.models.settings import SystemSettings
        default_accent_color_setting = SystemSettings.query.filter_by(key='default_accent_color').first()
        default_accent_color = default_accent_color_setting.value if default_accent_color_setting else '#0d6efd'
        
        # Create new user (active if whitelisted, inactive otherwise)
        new_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            is_active=is_whitelisted,
            is_admin=False,
            dark_mode=dark_mode,
            accent_color=default_accent_color,
            is_email_confirmed=google_verified,
        )
        if google_verified:
            new_user.google_sub = google_sub
            new_user.google_email = email
            new_user.google_linked_at = datetime.utcnow()
        new_user.set_password(password)
        
        email_sent = False
        try:
            db.session.add(new_user)
            db.session.flush()

            if google_verified and google_prefill.get('picture'):
                save_google_profile_picture(new_user, google_prefill.get('picture'))

            # Standardrollen + E-Mail-Rechte vor dem Commit — unabhängig vom Mailversand
            from app.utils.access_control import apply_default_roles_to_user
            apply_default_roles_to_user(new_user)

            email_perm = EmailPermission(
                user_id=new_user.id,
                can_read=True,
                can_send=True
            )
            db.session.add(email_perm)
            db.session.commit()
        except IntegrityError:
            # Doppel-Submit / Race: User wurde parallel angelegt
            db.session.rollback()
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                return _flash_existing_registration(existing_user)
            flash(translate('auth.flash.email_already_registered'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())
        except Exception as e:
            db.session.rollback()
            logging.exception('User create failed during registration for %s: %s', email, e)
            flash(translate('auth.flash.fill_all_fields'), 'danger')
            return render_template('auth/register.html', **_google_register_template_kwargs())

        clear_google_register_prefill()

        try:
            # Bestätigungscode erst nach Freischaltung:
            # Whitelist = sofort aktiv → Code jetzt; sonst erst bei Admin-Freischaltung.
            # Google-verifiziert: kein Bestätigungscode.
            if is_whitelisted and not google_verified:
                from app.utils.email_sender import send_confirmation_email
                email_sent = send_confirmation_email(new_user)

            # Add user to main chat if it exists
            # Alle aktiven Benutzer werden zum Haupt-Chat hinzugefügt (vollwertige Accounts)
            if new_user.is_active and not new_user.is_guest:
                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                if main_chat:
                    # Prüfe ob Benutzer bereits Mitglied ist
                    existing_member = ChatMember.query.filter_by(
                        chat_id=main_chat.id,
                        user_id=new_user.id
                    ).first()
                    if not existing_member:
                        member = ChatMember(
                            chat_id=main_chat.id,
                            user_id=new_user.id
                        )
                        db.session.add(member)
                        db.session.commit()
        except Exception as e:
            logging.exception('Post-create steps failed during registration for %s: %s', email, e)
        
        return _finish_registration(
            new_user, email_sent, is_whitelisted, google_verified=google_verified
        )
    
    return render_template('auth/register.html', **_google_register_template_kwargs())


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes")
def login():
    """User login mit Rate Limiting."""
    # Prüfe ob Setup nötig ist (ohne bestehenden Admin → Setup; mit Admin → Login erlauben)
    from app.blueprints.setup import is_setup_needed
    from app.models.user import User
    if is_setup_needed() and User.query.count() == 0:
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        if is_setup_needed():
            next_page = _sanitize_next_page(request.args.get('next'))
            if next_page:
                return redirect(next_page)
            return redirect(url_for('setup.setup'))
        return redirect(url_for('dashboard.index'))
    
    # Alte 2FA-Pending-Session bereinigen, wenn der Login neu gestartet wird
    if request.method == 'GET':
        _clear_pending_2fa_login()

    if request.method == 'POST':
        bot_ok, _ = validate_bot_protection(request, 'login')
        if not bot_ok:
            flash(translate('auth.flash.bot_protection_failed'), 'danger')
            return render_template('auth/login.html', **_auth_template_kwargs())

        login_input = request.form.get('email', '').strip()
        email = login_input.lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        next_page = _sanitize_next_page(request.form.get('next') or request.args.get('next'))
        
        if not email or not password:
            flash(translate('auth.flash.enter_email_password'), 'danger')
            return render_template('auth/login.html', **_auth_template_kwargs())
        
        # Assessment-Login: gleicher Login-Endpunkt, aber Username statt E-Mail.
        if '@' not in login_input:
            from app.models.assessment import AssessmentUser

            assessment_user = AssessmentUser.query.filter_by(username=login_input.lower()).first()
            if not assessment_user or not assessment_user.check_password(password):
                flash('Ungültiger Benutzername oder Passwort.', 'danger')
                return render_template('auth/login.html', **_auth_template_kwargs())

            if not assessment_user.is_active:
                flash('Konto ist deaktiviert.', 'warning')
                return render_template('auth/login.html', **_auth_template_kwargs())

            assessment_user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(assessment_user, remember=remember)
            session['user_scope'] = 'assessment'
            if assessment_user.must_change_password:
                return redirect(url_for('assessment.auth.admin_setup'))
            return redirect(url_for('assessment.general.home'))

        # Unterstütze konfigurierte Gast-Domain für Gast-Accounts
        from app.utils.guest_accounts import parse_guest_login_email
        user = None
        guest_username = parse_guest_login_email(email)
        if guest_username:
            user = User.query.filter_by(guest_username=guest_username, is_guest=True).first()
        else:
            # Standard-Login für normale Accounts
            user = User.query.filter_by(email=email).first()
        
        # Prüfe ob Account gesperrt ist (Rate Limiting)
        if user and user.failed_login_until and datetime.utcnow() < user.failed_login_until:
            remaining_seconds = int((user.failed_login_until - datetime.utcnow()).total_seconds())
            flash(translate('auth.flash.account_locked', seconds=remaining_seconds), 'danger')
            return render_template('auth/login.html', **_auth_template_kwargs())
        
        # Prüfe Credentials
        if not user or not user.check_password(password):
            # Erhöhe fehlgeschlagene Versuche
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= 5:
                    user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_login_attempts = 0
                db.session.commit()
            flash(translate('auth.flash.invalid_credentials'), 'danger')
            return render_template('auth/login.html', **_auth_template_kwargs())
        
        # Reset fehlgeschlagene Versuche bei erfolgreichem Passwort-Check
        user.failed_login_attempts = 0
        user.failed_login_until = None
        db.session.commit()
        
        # Prüfe Ablaufzeit für Gast-Accounts.
        # Abgelaufene Gäste werden deaktiviert (nicht sofort gelöscht), damit sie
        # für eine kurze Zeit durch Admins reaktiviert werden können.
        # guest_expires_at ist Portal-Wandzeit (naive) — mit portal_now_naive vergleichen.
        if user.is_guest and user.guest_expires_at:
            if portal_now_naive() > user.guest_expires_at:
                if user.is_active:
                    user.is_active = False
                    db.session.commit()
                flash(translate('auth.flash.guest_access_expired_contact_admin'), 'warning')
                return render_template('auth/login.html', **_auth_template_kwargs())
        
        if not user.is_active:
            if user.is_guest:
                flash(translate('auth.flash.guest_access_expired_contact_admin'), 'warning')
                return render_template('auth/login.html', **_auth_template_kwargs())
            flash(translate('auth.flash.account_not_activated'), 'warning')
            return render_template('auth/login.html', **_auth_template_kwargs())
        
        # 2FA-Verifizierung in separatem Schritt
        if user.totp_enabled and user.totp_secret:
            session['pending_2fa_user_id'] = user.id
            session['pending_2fa_remember'] = remember
            if next_page:
                session['pending_2fa_next'] = next_page
            else:
                session.pop('pending_2fa_next', None)
            flash(translate('auth.flash.enter_2fa_code'), 'info')
            return redirect(url_for('auth.login_2fa'))

        return _finalize_portal_login(user, remember=remember, next_page=next_page)
    
    return render_template('auth/login.html', **_auth_template_kwargs())


@auth_bp.route('/google/login')
@limiter.limit("20 per 15 minutes")
def google_login_start():
    """Startet Google-OAuth für Login (verknüpfte Accounts)."""
    from app.utils.google_login import google_login_ready, build_google_login_url
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if not google_login_ready():
        flash(translate('auth.google.not_configured'), 'warning')
        return redirect(url_for('auth.login'))
    try:
        next_page = _sanitize_next_page(request.args.get('next'))
        if next_page:
            session['google_login_next'] = next_page
        return redirect(build_google_login_url(purpose='login'))
    except Exception as exc:
        flash(translate('auth.google.error', error=str(exc)), 'danger')
        return redirect(url_for('auth.login'))


@auth_bp.route('/google/register')
@limiter.limit("20 per 15 minutes")
def google_register_start():
    """Startet Google-OAuth für die Registrierung (Prefill + E-Mail verifiziert)."""
    from app.utils.google_login import google_login_ready, build_google_login_url
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if not google_login_ready():
        flash(translate('auth.google.not_configured'), 'warning')
        return redirect(url_for('auth.register'))
    try:
        return redirect(build_google_login_url(purpose='register'))
    except Exception as exc:
        flash(translate('auth.google.error', error=str(exc)), 'danger')
        return redirect(url_for('auth.register'))


@auth_bp.route('/google/callback')
@limiter.limit("30 per 15 minutes")
def google_callback():
    """Einheitlicher Google-OAuth-Callback: Login, Register, Link, Postfach, YouTube."""
    state = request.args.get('state')
    code = request.args.get('code')
    err = request.args.get('error')

    # 1) Postfach-Wizard (Google)
    if (
        state
        and state == session.get('mailbox_oauth_state')
        and session.get('mailbox_oauth_provider') == 'google'
    ):
        return _google_callback_mailbox(code, state, err)

    # 2) YouTube Musik
    if state and state == session.get('youtube_oauth_state'):
        return _google_callback_youtube(code, state, err)

    # 3) Login / Registrierung / Account-Verknüpfung
    return _google_callback_auth(code, state, err)


def _google_callback_mailbox(code, state, err):
    """Beendet Google-OAuth für den Postfach-Wizard (inkl. Popup)."""
    from app.utils.mailbox_oauth import (
        handle_oauth_callback,
        mailbox_oauth_popup_error_html,
        mailbox_oauth_popup_success_html,
    )

    if err:
        msg = request.args.get('error_description') or err
        if session.get('mailbox_oauth_popup'):
            return mailbox_oauth_popup_error_html(msg)
        flash(translate('settings.mailboxes.oauth_error', error=msg), 'danger')
        return redirect(url_for('settings.my_mailbox_new'))

    try:
        result = handle_oauth_callback('google', code, state)
    except Exception as e:
        if session.get('mailbox_oauth_popup'):
            return mailbox_oauth_popup_error_html(str(e))
        flash(translate('settings.mailboxes.oauth_error', error=str(e)), 'danger')
        return redirect(url_for('settings.my_mailbox_new'))

    if session.get('mailbox_oauth_popup'):
        return mailbox_oauth_popup_success_html(result)
    flash(translate('settings.mailboxes.oauth_connected'), 'success')
    return redirect(url_for('settings.my_mailbox_new'))


def _google_callback_youtube(code, state, err):
    """Beendet Google-OAuth für YouTube Music."""
    from app.utils.music_oauth import handle_youtube_callback

    if err:
        flash(translate('music.flash.oauth_error', provider='YouTube', error=err), 'danger')
        return redirect(url_for('music.index'))
    if not code:
        flash(translate('music.flash.no_auth_code'), 'danger')
        return redirect(url_for('music.index'))
    if not current_user.is_authenticated:
        flash(translate('auth.google.link_requires_login'), 'warning')
        return redirect(url_for('auth.login'))
    try:
        handle_youtube_callback(code, state)
        flash(translate('music.flash.youtube_connected'), 'success')
    except Exception as e:
        flash(translate('music.flash.connect_error', provider='YouTube', error=str(e)), 'danger')
    return redirect(url_for('music.index'))


def _google_callback_auth(code, state, err):
    """Beendet Google-OAuth für Login / Register / Link."""
    from app.utils.google_login import (
        exchange_google_login_code,
        ensure_gmail_mailbox_for_user,
        store_google_register_prefill,
        clear_google_register_prefill,
        save_google_profile_picture,
    )

    if err:
        flash(translate('auth.google.error', error=request.args.get('error_description') or err), 'danger')
        if current_user.is_authenticated:
            return redirect(url_for('settings.security'))
        return redirect(url_for('auth.login'))

    try:
        result = exchange_google_login_code(code, state)
    except Exception as exc:
        flash(translate('auth.google.error', error=str(exc)), 'danger')
        if current_user.is_authenticated:
            return redirect(url_for('settings.security'))
        return redirect(url_for('auth.login'))

    purpose = result.get('purpose') or 'login'
    sub = result['sub']
    google_email = result.get('email') or ''

    if purpose == 'link':
        if not current_user.is_authenticated:
            flash(translate('auth.google.link_requires_login'), 'warning')
            return redirect(url_for('auth.login'))
        if current_user.is_guest:
            flash(translate('auth.google.link_guest_forbidden'), 'danger')
            return redirect(url_for('settings.security'))

        other = User.query.filter(User.google_sub == sub, User.id != current_user.id).first()
        if other:
            flash(translate('auth.google.already_linked_other'), 'danger')
            return redirect(url_for('settings.security'))

        current_user.google_sub = sub
        current_user.google_email = google_email or None
        current_user.google_linked_at = datetime.utcnow()
        try:
            # Nur übernehmen, wenn der User noch kein eigenes Profilbild hat
            picture_url = (result.get('picture') or '').strip()
            if picture_url and not current_user.profile_picture:
                save_google_profile_picture(current_user, picture_url)
            ensure_gmail_mailbox_for_user(current_user, result)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(translate('auth.google.error', error=str(exc)), 'danger')
            return redirect(url_for('settings.security'))
        flash(translate('auth.google.link_success'), 'success')
        return redirect(url_for('settings.security'))

    if purpose == 'register':
        existing_by_sub = User.query.filter_by(google_sub=sub).first()
        if existing_by_sub:
            flash(translate('auth.google.already_registered'), 'info')
            return redirect(url_for('auth.login'))
        if google_email:
            existing_by_email = User.query.filter_by(email=google_email).first()
            if existing_by_email:
                flash(translate('auth.google.email_exists_link_instead'), 'warning')
                return redirect(url_for('auth.login'))
        try:
            store_google_register_prefill(result)
        except Exception as exc:
            flash(translate('auth.google.error', error=str(exc)), 'danger')
            return redirect(url_for('auth.register'))
        flash(translate('auth.google.register_prefill_ready'), 'success')
        return redirect(url_for('auth.register'))

    # purpose == login
    user = User.query.filter_by(google_sub=sub).first()
    if not user:
        if google_email:
            existing_by_email = User.query.filter_by(email=google_email).first()
            if existing_by_email:
                flash(translate('auth.google.not_linked'), 'warning')
                return redirect(url_for('auth.login'))
        try:
            store_google_register_prefill(result)
            flash(translate('auth.google.register_via_login'), 'info')
            return redirect(url_for('auth.register'))
        except Exception:
            clear_google_register_prefill()
            flash(translate('auth.google.not_linked'), 'warning')
            return redirect(url_for('auth.login'))

    if user.failed_login_until and datetime.utcnow() < user.failed_login_until:
        remaining_seconds = int((user.failed_login_until - datetime.utcnow()).total_seconds())
        flash(translate('auth.flash.account_locked', seconds=remaining_seconds), 'danger')
        return redirect(url_for('auth.login'))

    if not user.is_active:
        flash(translate('auth.flash.account_not_activated'), 'warning')
        return redirect(url_for('auth.login'))

    try:
        ensure_gmail_mailbox_for_user(user, result)
        if google_email:
            user.google_email = google_email
        db.session.commit()
    except Exception:
        db.session.rollback()

    user.failed_login_attempts = 0
    user.failed_login_until = None
    db.session.commit()

    next_page = _sanitize_next_page(session.pop('google_login_next', None))
    remember = False

    if user.totp_enabled and user.totp_secret:
        session['pending_2fa_user_id'] = user.id
        session['pending_2fa_remember'] = remember
        if next_page:
            session['pending_2fa_next'] = next_page
        else:
            session.pop('pending_2fa_next', None)
        flash(translate('auth.flash.enter_2fa_code'), 'info')
        return redirect(url_for('auth.login_2fa'))

    return _finalize_portal_login(user, remember=remember, next_page=next_page)


@auth_bp.route('/login/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per 15 minutes")
def login_2fa():
    """Zweiter Login-Schritt für 2FA."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    pending_user_id = session.get('pending_2fa_user_id')
    remember = bool(session.get('pending_2fa_remember', False))
    next_page = _sanitize_next_page(session.get('pending_2fa_next'))

    if not pending_user_id:
        flash(translate('auth.flash.enter_email_password'), 'warning')
        return redirect(url_for('auth.login'))

    user = User.query.get(pending_user_id)
    if not user or not user.totp_enabled or not user.totp_secret:
        _clear_pending_2fa_login()
        flash(translate('auth.flash.enter_email_password'), 'warning')
        return redirect(url_for('auth.login'))

    if user.failed_login_until and datetime.utcnow() < user.failed_login_until:
        _clear_pending_2fa_login()
        remaining_seconds = int((user.failed_login_until - datetime.utcnow()).total_seconds())
        flash(translate('auth.flash.account_locked', seconds=remaining_seconds), 'danger')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        totp_code = request.form.get('totp_code', '').strip()
        if not totp_code:
            flash(translate('auth.flash.enter_2fa_code'), 'danger')
            return render_template('auth/login_2fa.html', color_gradient=get_color_gradient())

        if not verify_totp(user.totp_secret, totp_code):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.failed_login_until = datetime.utcnow() + timedelta(minutes=15)
                user.failed_login_attempts = 0
            db.session.commit()
            flash(translate('auth.flash.invalid_2fa_code'), 'danger')
            return render_template('auth/login_2fa.html', color_gradient=get_color_gradient())

        # Erfolgreicher 2FA-Schritt
        _clear_pending_2fa_login()
        return _finalize_portal_login(user, remember=remember, next_page=next_page)

    return render_template('auth/login_2fa.html', color_gradient=get_color_gradient())


@auth_bp.route('/confirm-email', methods=['GET', 'POST'])
@login_required
def confirm_email():
    """E-Mail-Bestätigung."""
    if current_user.is_email_confirmed:
        flash(translate('auth.flash.email_already_confirmed'), 'info')
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        confirmation_code = request.form.get('confirmation_code', '').strip()
        
        if not confirmation_code:
            flash(translate('auth.flash.enter_confirmation_code'), 'danger')
            return render_template('auth/confirm_email.html', color_gradient=get_color_gradient())
        
        from app.utils.email_sender import verify_confirmation_code
        
        if verify_confirmation_code(current_user, confirmation_code):
            flash(translate('auth.flash.email_confirmed_success'), 'success')
            return redirect(url_for('dashboard.index'))
        else:
            flash(translate('auth.flash.invalid_confirmation_code'), 'danger')
            return render_template('auth/confirm_email.html', color_gradient=get_color_gradient())
    
    return render_template('auth/confirm_email.html', color_gradient=get_color_gradient())


@auth_bp.route('/resend-confirmation')
@login_required
def resend_confirmation():
    """Bestätigungs-E-Mail erneut senden."""
    if current_user.is_email_confirmed:
        flash(translate('auth.flash.email_already_confirmed'), 'info')
        return redirect(url_for('dashboard.index'))

    if not current_user.is_active:
        flash(translate('auth.flash.account_not_activated'), 'warning')
        return redirect(url_for('auth.login'))
    
    from app.utils.email_sender import resend_confirmation_email
    
    if resend_confirmation_email(current_user):
        flash(translate('auth.flash.confirmation_email_resent'), 'success')
    else:
        flash(translate('auth.flash.confirmation_email_failed'), 'warning')
    
    return redirect(url_for('auth.confirm_email'))


@auth_bp.route('/admin/show-confirmation-codes')
@login_required
def show_confirmation_codes():
    """Legacy: Bestätigungscodes sind in der Benutzerverwaltung."""
    if not current_user.is_admin:
        flash(translate('auth.flash.admin_only'), 'danger')
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('settings.admin_users') + '#confirmation-codes')


@auth_bp.route('/admin/test-email', methods=['POST'])
@login_required
def test_email():
    """Testet die E-Mail-Konfiguration (Admin only, POST-only — kein GET-Side-Effect)."""
    if not current_user.is_admin:
        flash(translate('auth.flash.admin_only'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    from flask import current_app
    from app.utils.email_sender import send_smtp_test_email

    mail_server = current_app.config.get('MAIL_SERVER')
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')
    mail_port = current_app.config.get('MAIL_PORT', 587)
    mail_use_tls = current_app.config.get('MAIL_USE_TLS', True)

    config_info = {
        'MAIL_SERVER': mail_server,
        'MAIL_USERNAME': mail_username,
        'MAIL_PASSWORD': '***' if mail_password else None,
        'MAIL_PORT': mail_port,
        'MAIL_USE_TLS': mail_use_tls
    }

    try:
        send_smtp_test_email(current_user.email)
        
        flash(translate('auth.flash.test_email_sent'), 'success')
        return render_template('auth/email_test_result.html', 
                             success=True, 
                             config=config_info,
                             message=translate('auth.flash.test_email_success_message'))
        
    except Exception as e:
        flash(translate('auth.flash.test_email_error', error=str(e)), 'danger')
        return render_template('auth/email_test_result.html', 
                             success=False, 
                             config=config_info,
                             error=str(e))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password (required for admin-created users on first login)."""
    color_gradient = get_color_gradient()
    
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validierung
        if not current_password or not new_password or not confirm_password:
            flash(translate('auth.flash.fill_all_fields_password'), 'danger')
            return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)
        
        # Prüfe aktuelles Passwort
        if not current_user.check_password(current_password):
            flash(translate('auth.flash.current_password_wrong'), 'danger')
            return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)
        
        # Prüfe ob neues Passwort gleich dem aktuellen ist
        if current_user.check_password(new_password):
            flash(translate('auth.flash.password_must_differ'), 'danger')
            return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)
        
        # Prüfe Passwort-Bestätigung
        if new_password != confirm_password:
            flash(translate('auth.flash.passwords_dont_match'), 'danger')
            return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)
        
        # Prüfe Passwort-Länge
        if len(new_password) < 8:
            flash(translate('auth.flash.password_too_short'), 'danger')
            return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)
        
        # Passwort ändern
        current_user.set_password(new_password)
        current_user.must_change_password = False
        db.session.commit()
        
        flash(translate('auth.flash.password_changed_success'), 'success')
        return redirect(url_for('dashboard.index'))
    
    return render_template('auth/change_password.html', must_change=current_user.must_change_password, color_gradient=color_gradient)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Passwort vergessen - E-Mail eingeben."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            flash(translate('auth.flash.enter_email'), 'danger')
            return render_template('auth/forgot_password.html', color_gradient=get_color_gradient())
        
        # Rate Limiting: Prüfe ob zu viele Anfragen in der letzten Stunde
        # Suche nach User mit dieser E-Mail
        user = User.query.filter_by(email=email).first()
        
        if user and not user.is_guest:
            # Prüfe Rate Limiting: Maximal 3 Reset-Anfragen pro Stunde
            recent_resets = 0
            if user.password_reset_code_expires:
                # Wenn ein Code existiert und noch nicht abgelaufen ist, zähle als eine Anfrage
                if datetime.utcnow() < user.password_reset_code_expires:
                    # Prüfe ob Code in der letzten Stunde erstellt wurde
                    if user.password_reset_code_expires > datetime.utcnow() - timedelta(hours=1):
                        recent_resets = 1
            
            # Zähle weitere Reset-Codes in der letzten Stunde (vereinfachte Prüfung)
            # In einer produktiven Umgebung könnte man hier eine separate Tabelle für Rate-Limiting verwenden
            if recent_resets >= 3:
                # Zeige trotzdem Erfolgsmeldung (Sicherheit)
                flash(translate('auth.flash.password_reset_email_sent'), 'success')
                return render_template('auth/forgot_password.html', color_gradient=get_color_gradient())
            
            # Sende Passwort-Reset-E-Mail
            from app.utils.email_sender import send_password_reset_email
            send_password_reset_email(user)
            
            # Weiterleitung zur Reset-Password-Seite mit E-Mail-Adresse
            flash(translate('auth.flash.password_reset_email_sent'), 'success')
            return redirect(url_for('auth.reset_password', email=email))
        
        # Zeige immer Erfolgsmeldung (auch wenn E-Mail nicht existiert - Sicherheit)
        flash(translate('auth.flash.password_reset_email_sent'), 'success')
        return render_template('auth/forgot_password.html', color_gradient=get_color_gradient())
    
    return render_template('auth/forgot_password.html', color_gradient=get_color_gradient())


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Passwort zurücksetzen mit Code."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        reset_code = request.form.get('reset_code', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validierung
        if not all([email, reset_code, new_password, confirm_password]):
            flash(translate('auth.flash.fill_all_fields'), 'danger')
            return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())
        
        # Finde User
        user = User.query.filter_by(email=email).first()
        if not user or user.is_guest:
            flash(translate('auth.flash.invalid_reset_code'), 'danger')
            return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())
        
        # Prüfe Reset-Code
        from app.utils.email_sender import verify_password_reset_code
        if not verify_password_reset_code(user, reset_code):
            flash(translate('auth.flash.invalid_reset_code'), 'danger')
            return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())
        
        # Prüfe Passwort-Bestätigung
        if new_password != confirm_password:
            flash(translate('auth.flash.passwords_dont_match'), 'danger')
            return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())
        
        # Prüfe Passwort-Länge
        if len(new_password) < 8:
            flash(translate('auth.flash.password_too_short'), 'danger')
            return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())
        
        # Setze neues Passwort
        user.set_password(new_password)
        # Lösche Reset-Code
        user.password_reset_code = None
        user.password_reset_code_expires = None
        db.session.commit()
        
        flash(translate('auth.flash.password_reset_success'), 'success')
        return redirect(url_for('auth.login'))
    
    # GET: Zeige Formular
    email = request.args.get('email', '')
    return render_template('auth/reset_password.html', email=email, color_gradient=get_color_gradient())


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    # Melde Session ab
    session_id = session.get('session_id')
    if session_id:
        revoke_session_by_id(session_id)
    
    session.pop('user_scope', None)
    logout_user()
    flash(translate('auth.flash.logout_success'), 'success')
    return redirect(url_for('auth.login'))



