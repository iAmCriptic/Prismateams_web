from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from app.models.settings import SystemSettings
from app.utils.i18n import translate
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


def get_color_gradient():
    """Holt den Farbverlauf aus den System-Einstellungen."""
    gradient_setting = SystemSettings.query.filter_by(key='color_gradient').first()
    return gradient_setting.value if gradient_setting else None


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
def register():
    """User registration."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dark_mode = request.form.get('dark_mode') == 'on'
        
        # Validation
        if not all([email, password, first_name, last_name]):
            flash(translate('auth.flash.fill_all_fields'), 'danger')
            return render_template('auth/register.html', color_gradient=get_color_gradient())
        
        if password != password_confirm:
            flash(translate('auth.flash.passwords_dont_match'), 'danger')
            return render_template('auth/register.html', color_gradient=get_color_gradient())
        
        if len(password) < 8:
            flash(translate('auth.flash.password_too_short'), 'danger')
            return render_template('auth/register.html', color_gradient=get_color_gradient())
        
        # Check if user already exists
        if User.query.filter_by(email=email).first():
            flash(translate('auth.flash.email_already_registered'), 'danger')
            return render_template('auth/register.html', color_gradient=get_color_gradient())
        
        # Check if email is whitelisted
        is_whitelisted = WhitelistEntry.is_email_whitelisted(email)
        
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
            accent_color=default_accent_color
        )
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        # Create email permissions (default: can read and send)
        email_perm = EmailPermission(
            user_id=new_user.id,
            can_read=True,
            can_send=True
        )
        db.session.add(email_perm)
        
        # Send confirmation email
        from app.utils.email_sender import send_confirmation_email
        email_sent = send_confirmation_email(new_user)
        
        # Zuweise Standardrollen
        from app.models.settings import SystemSettings
        from app.models.role import UserModuleRole
        from app.utils.access_control import has_module_access
        from app.utils.common import is_module_enabled
        import json
        
        default_roles_setting = SystemSettings.query.filter_by(key='default_module_roles').first()
        if default_roles_setting:
            try:
                default_roles = json.loads(default_roles_setting.value)
                
                if default_roles.get('full_access', False):
                    new_user.has_full_access = True
                else:
                    # Modulspezifische Rollen zuweisen
                    all_modules = [
                        'module_chat', 'module_files', 'module_calendar', 'module_email',
                        'module_credentials', 'module_manuals',
                        'module_inventory', 'module_wiki', 'module_booking', 'module_music'
                    ]
                    
                    for module_key in all_modules:
                        if default_roles.get(module_key, False) and is_module_enabled(module_key):
                            role = UserModuleRole(
                                user_id=new_user.id,
                                module_key=module_key,
                                has_access=True
                            )
                            db.session.add(role)
            except:
                pass  # Bei Fehler: Keine Standardrollen zuweisen
        
        # Commit rollen first, so has_module_access works correctly
        db.session.commit()
        
        # Add user to main chat if it exists
        # Alle aktiven Benutzer werden zum Haupt-Chat hinzugefügt (vollwertige Accounts)
        from app.models.chat import Chat, ChatMember
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
        
        if is_whitelisted:
            # Benutzer ist whitelisted - direkt einloggen und zur E-Mail-Bestätigung weiterleiten
            login_user(new_user, remember=False)
            if email_sent:
                flash(translate('auth.flash.register_success_whitelisted'), 'success')
            else:
                flash(translate('auth.flash.register_success_whitelisted_no_email'), 'warning')
            return redirect(url_for('auth.confirm_email'))
        else:
            # Benutzer ist nicht whitelisted - zurück zum Login mit entsprechender Meldung
            if email_sent:
                flash(translate('auth.flash.register_pending_admin'), 'info')
            else:
                flash(translate('auth.flash.register_pending_admin_no_email'), 'warning')
            return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html', color_gradient=get_color_gradient())


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    # Prüfe ob Setup nötig ist
    from app.blueprints.setup import is_setup_needed
    if is_setup_needed():
        return redirect(url_for('setup.setup'))
    
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        
        if not email or not password:
            flash(translate('auth.flash.enter_email_password'), 'danger')
            return render_template('auth/login.html', color_gradient=get_color_gradient())
        
        # Unterstütze @gast.system.local Format für Gast-Accounts
        user = None
        if email.endswith('@gast.system.local'):
            # Extrahiere Gast-Benutzernamen
            guest_username = email.replace('@gast.system.local', '')
            user = User.query.filter_by(guest_username=guest_username, is_guest=True).first()
        else:
            # Standard-Login für normale Accounts
            user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash(translate('auth.flash.invalid_credentials'), 'danger')
            return render_template('auth/login.html', color_gradient=get_color_gradient())
        
        # Prüfe Ablaufzeit für Gast-Accounts
        if user.is_guest and user.guest_expires_at:
            if datetime.utcnow() > user.guest_expires_at:
                # Account ist abgelaufen - lösche ihn
                db.session.delete(user)
                db.session.commit()
                flash(translate('auth.flash.guest_account_expired'), 'danger')
                return render_template('auth/login.html', color_gradient=get_color_gradient())
        
        if not user.is_active:
            flash(translate('auth.flash.account_not_activated'), 'warning')
            return render_template('auth/login.html', color_gradient=get_color_gradient())
        
        # Gast-Accounts benötigen keine E-Mail-Bestätigung
        # Normale Accounts: Check if email confirmation is required (nicht für Admins)
        if not user.is_guest and not user.is_email_confirmed and not user.is_admin:
            login_user(user, remember=remember)
            flash(translate('auth.flash.confirm_email_required'), 'info')
            return redirect(url_for('auth.confirm_email'))
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Log user in
        login_user(user, remember=remember)
        
        # Add user to main chat if not already a member and user has chat access
        from app.utils.access_control import has_module_access
        if has_module_access(user, 'module_chat'):
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
        
        # Redirect to next page or dashboard
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('dashboard.index'))
    
    return render_template('auth/login.html', color_gradient=get_color_gradient())


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
    
    from app.utils.email_sender import resend_confirmation_email
    
    if resend_confirmation_email(current_user):
        flash(translate('auth.flash.confirmation_email_resent'), 'success')
    else:
        flash(translate('auth.flash.confirmation_email_failed'), 'warning')
    
    return redirect(url_for('auth.confirm_email'))


@auth_bp.route('/admin/show-confirmation-codes')
@login_required
def show_confirmation_codes():
    """Zeigt alle ausstehenden Bestätigungscodes an (Admin only)."""
    if not current_user.is_admin:
        flash(translate('auth.flash.admin_only'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    from app.models.user import User
    
    # Hole alle Benutzer mit ausstehenden Bestätigungen
    pending_users = User.query.filter(
        User.is_email_confirmed == False,
        User.confirmation_code.isnot(None)
    ).all()
    
    # Filtere abgelaufene Codes
    current_time = datetime.utcnow()
    valid_users = []
    for user in pending_users:
        if user.confirmation_code_expires and user.confirmation_code_expires > current_time:
            valid_users.append(user)
    
    return render_template('auth/admin_confirmation_codes.html', users=valid_users)


@auth_bp.route('/admin/test-email', methods=['GET', 'POST'])
@login_required
def test_email():
    """Testet die E-Mail-Konfiguration (Admin only)."""
    if not current_user.is_admin:
        flash(translate('auth.flash.admin_only'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    from flask import current_app
    from flask_mail import Message
    from app import mail
    from app.utils.email_sender import send_email_with_lock
    
    try:
        # Prüfe E-Mail-Konfiguration
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
        
        # Versuche Test-E-Mail zu senden
        from config import get_formatted_sender
        sender = get_formatted_sender() or mail_username
        msg = Message(
            subject='Test-E-Mail - Prismateams',
            recipients=[current_user.email],
            sender=sender
        )
        msg.body = 'Dies ist eine Test-E-Mail von Prismateams.'
        
        send_email_with_lock(msg)
        
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


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash(translate('auth.flash.logout_success'), 'success')
    return redirect(url_for('auth.login'))



