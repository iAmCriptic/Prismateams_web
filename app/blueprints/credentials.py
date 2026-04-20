from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.credential import Credential, CredentialFolder
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from cryptography.fernet import Fernet
import os
import requests
from urllib.parse import urlparse

credentials_bp = Blueprint('credentials', __name__)


def get_encryption_key():
    """Get or create encryption key for credentials."""
    # Versuche zuerst aus Umgebungsvariable zu lesen
    key = os.environ.get('CREDENTIAL_ENCRYPTION_KEY')
    if key:
        # Wenn als String, in Bytes konvertieren
        if isinstance(key, str):
            return key.encode('utf-8')
        return key
    
    # Fallback: Versuche aus Datei zu lesen (für Migration)
    key_file = 'credential_key.key'
    if os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            return f.read()
    
    # Wenn nichts gefunden, generiere neuen Key (nur für Entwicklung)
    # In Produktion sollte der Key immer in .env gesetzt sein
    key = Fernet.generate_key()
    print("WARNUNG: CREDENTIAL_ENCRYPTION_KEY nicht in .env gefunden! Bitte setzen Sie den Key in der .env-Datei.")
    return key


def get_favicon_url(website_url):
    """Get favicon URL for a website."""
    try:
        parsed = urlparse(website_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try common favicon locations
        favicon_urls = [
            f"{domain}/favicon.ico",
            f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32",
        ]
        
        for url in favicon_urls:
            try:
                response = requests.head(url, timeout=2)
                if response.status_code == 200:
                    return url
            except:
                continue
        
        # Fallback to Google's favicon service
        return f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=32"
    except:
        return None


def normalize_folder_color(raw_color):
    """Normalize folder color input to #RRGGBB."""
    if not raw_color:
        return '#0d6efd'

    value = raw_color.strip()
    if not value.startswith('#'):
        value = f'#{value}'

    if len(value) != 7:
        return '#0d6efd'

    try:
        int(value[1:], 16)
    except ValueError:
        return '#0d6efd'

    return value.lower()


def parse_folder_id(raw_folder_id):
    """Parse and validate folder id from form/json value."""
    if raw_folder_id in (None, '', 'null'):
        return None

    try:
        folder_id = int(raw_folder_id)
    except (TypeError, ValueError):
        return None

    folder = CredentialFolder.query.get(folder_id)
    return folder.id if folder else None


@credentials_bp.route('/')
@login_required
@check_module_access('module_credentials')
def index():
    """List all credentials."""
    credentials = Credential.query.order_by(Credential.website_name).all()
    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()

    credentials_by_folder = {folder.id: [] for folder in folders}
    root_credentials = []

    for credential in credentials:
        if credential.folder_id in credentials_by_folder:
            credentials_by_folder[credential.folder_id].append(credential)
        else:
            root_credentials.append(credential)

    return render_template(
        'credentials/index.html',
        folders=folders,
        root_credentials=root_credentials,
        credentials_by_folder=credentials_by_folder
    )


@credentials_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_credentials')
def create():
    """Create a new credential entry."""
    if request.method == 'POST':
        website_url = request.form.get('website_url', '').strip()
        website_name = request.form.get('website_name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        notes = request.form.get('notes', '').strip()
        folder_id = parse_folder_id(request.form.get('folder_id'))
        is_favorite = request.form.get('is_favorite') == 'on'
        
        if not all([website_url, website_name, username, password]):
            flash(translate('credentials.flash.fill_all_fields'), 'danger')
            folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()
            return render_template('credentials/create.html', folders=folders)
        
        # Get favicon
        favicon_url = get_favicon_url(website_url)
        
        # Create credential
        credential = Credential(
            website_url=website_url,
            website_name=website_name,
            username=username,
            notes=notes,
            favicon_url=favicon_url,
            folder_id=folder_id,
            is_favorite=is_favorite,
            created_by=current_user.id
        )
        
        # Encrypt and set password
        key = get_encryption_key()
        credential.set_password(password, key)
        
        db.session.add(credential)
        db.session.commit()
        
        flash(translate('credentials.flash.saved', website_name=website_name), 'success')
        return redirect(url_for('credentials.index'))
    
    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()
    return render_template('credentials/create.html', folders=folders)


@credentials_bp.route('/edit/<int:credential_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_credentials')
def edit(credential_id):
    """Edit a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    key = get_encryption_key()
    
    if request.method == 'POST':
        credential.website_url = request.form.get('website_url', '').strip()
        credential.website_name = request.form.get('website_name', '').strip()
        credential.username = request.form.get('username', '').strip()
        credential.notes = request.form.get('notes', '').strip()
        credential.folder_id = parse_folder_id(request.form.get('folder_id'))
        credential.is_favorite = request.form.get('is_favorite') == 'on'
        
        new_password = request.form.get('password', '').strip()
        if new_password:
            credential.set_password(new_password, key)
        
        # Update favicon
        credential.favicon_url = get_favicon_url(credential.website_url)
        
        db.session.commit()
        
        flash(translate('credentials.flash.updated', website_name=credential.website_name), 'success')
        return redirect(url_for('credentials.index'))
    
    # Decrypt password for display
    decrypted_password = credential.get_password(key)
    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()

    return render_template(
        'credentials/edit.html',
        credential=credential,
        password=decrypted_password,
        folders=folders
    )


@credentials_bp.route('/delete/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def delete(credential_id):
    """Delete a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    
    db.session.delete(credential)
    db.session.commit()
    
    flash(translate('credentials.flash.deleted', website_name=credential.website_name), 'success')
    return redirect(url_for('credentials.index'))


@credentials_bp.route('/view-password/<int:credential_id>')
@login_required
@check_module_access('module_credentials')
def view_password(credential_id):
    """View decrypted password (AJAX endpoint)."""
    credential = Credential.query.get_or_404(credential_id)
    key = get_encryption_key()
    
    try:
        password = credential.get_password(key)
        return jsonify({'password': password})
    except Exception as e:
        return jsonify({'error': translate('credentials.errors.decrypt_error')}), 500


@credentials_bp.route('/folders/create', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def create_folder():
    """Create a new credential folder."""
    folder_name = request.form.get('name', '').strip()
    folder_color = normalize_folder_color(request.form.get('color', '#0d6efd'))

    if not folder_name:
        flash(translate('credentials.flash.folder_name_required'), 'danger')
        return redirect(url_for('credentials.index'))

    max_position = db.session.query(db.func.max(CredentialFolder.position)).scalar() or 0
    folder = CredentialFolder(
        name=folder_name[:120],
        color=folder_color,
        position=max_position + 1,
        created_by=current_user.id
    )
    db.session.add(folder)
    db.session.commit()

    flash(translate('credentials.flash.folder_created', folder_name=folder.name), 'success')
    return redirect(url_for('credentials.index'))


@credentials_bp.route('/folders/<int:folder_id>/move-up', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_folder_up(folder_id):
    """Move folder one position up."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    previous_folder = CredentialFolder.query.filter(
        CredentialFolder.position < folder.position
    ).order_by(CredentialFolder.position.desc()).first()

    if previous_folder:
        folder.position, previous_folder.position = previous_folder.position, folder.position
        db.session.commit()

    return redirect(url_for('credentials.index'))


@credentials_bp.route('/move/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_credential(credential_id):
    """Move credential into folder or root."""
    credential = Credential.query.get_or_404(credential_id)
    data = request.get_json(silent=True) or {}
    credential.folder_id = parse_folder_id(data.get('folder_id'))
    db.session.commit()
    return jsonify({'success': True})


@credentials_bp.route('/favorite/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def toggle_favorite(credential_id):
    """Toggle credential favorite status."""
    credential = Credential.query.get_or_404(credential_id)
    credential.is_favorite = not credential.is_favorite
    db.session.commit()
    return jsonify({'success': True, 'is_favorite': credential.is_favorite})



