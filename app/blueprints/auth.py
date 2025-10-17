from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.email import EmailPermission
from app.models.chat import Chat, ChatMember
from app.models.whitelist import WhitelistEntry
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    """Redirect to login or dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # Validation
        if not all([email, password, first_name, last_name]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('auth/register.html')
        
        if password != password_confirm:
            flash('Die Passwörter stimmen nicht überein.', 'danger')
            return render_template('auth/register.html')
        
        if len(password) < 8:
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'danger')
            return render_template('auth/register.html')
        
        # Check if user already exists
        if User.query.filter_by(email=email).first():
            flash('Diese E-Mail-Adresse ist bereits registriert.', 'danger')
            return render_template('auth/register.html')
        
        # Check if email is whitelisted
        is_whitelisted = WhitelistEntry.is_email_whitelisted(email)
        
        # Create new user (active if whitelisted, inactive otherwise)
        new_user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            is_active=is_whitelisted,
            is_admin=False
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
        
        # Add user to main chat if it exists
        from app.models.chat import Chat, ChatMember
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        if main_chat:
            member = ChatMember(
                chat_id=main_chat.id,
                user_id=new_user.id
            )
            db.session.add(member)
        
        db.session.commit()
        
        if is_whitelisted:
            flash('Registrierung erfolgreich! Ihr Konto wurde automatisch aktiviert.', 'success')
        else:
            flash('Registrierung erfolgreich! Ein Administrator muss Ihr Konto noch freischalten.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        
        if not email or not password:
            flash('Bitte geben Sie E-Mail und Passwort ein.', 'danger')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash('Ungültige E-Mail oder Passwort.', 'danger')
            return render_template('auth/login.html')
        
        if not user.is_active:
            flash('Ihr Konto wurde noch nicht aktiviert. Bitte warten Sie auf die Freischaltung durch einen Administrator.', 'warning')
            return render_template('auth/login.html')
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Log user in
        login_user(user, remember=remember)
        
        # Add user to main chat if not already a member
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
    
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('Sie wurden erfolgreich abgemeldet.', 'success')
    return redirect(url_for('auth.login'))



