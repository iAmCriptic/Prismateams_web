from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from app import db
from app.models.credential import Credential, CredentialFolder, CredentialFavorite
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.module_visibility import (
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_edit_item,
    can_view_item,
    parse_section_args,
    visibility_form_context,
    visibility_nav_context,
)
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


def get_user_favorite_ids(user_id):
    """Return set of credential ids favorited by user."""
    rows = CredentialFavorite.query.filter_by(user_id=user_id).with_entities(CredentialFavorite.credential_id).all()
    return {row[0] for row in rows}


def set_credential_favorite(user_id, credential_id, should_favorite):
    """Add or remove a per-user favorite. Returns current is_favorite for user."""
    existing = CredentialFavorite.query.filter_by(user_id=user_id, credential_id=credential_id).first()
    if should_favorite and not existing:
        db.session.add(CredentialFavorite(user_id=user_id, credential_id=credential_id))
        db.session.flush()
        return True
    if not should_favorite and existing:
        db.session.delete(existing)
        db.session.flush()
        return False
    return bool(existing)


def _credentials_denied():
    flash(translate('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('credentials.index'))


def _credentials_form_kwargs(item=None):
    section, filter_team_id = parse_section_args('credentials', current_user)
    pre_section = section if section in ('private', 'public', 'team') else None
    return visibility_form_context(
        'credentials',
        current_user,
        item=item,
        preselect_section=pre_section,
        preselect_team_id=filter_team_id,
    )


@credentials_bp.route('/')
@login_required
@check_module_access('module_credentials')
def index():
    """List credentials for root, folder, space, or personal favorites view."""
    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()
    section, filter_team_id = parse_section_args('credentials', current_user)
    active_favorites = section == 'favorites'
    space_view = section in ('private', 'team', 'public')
    search_query = request.args.get('q', '').strip()
    active_folder_id = None if active_favorites or space_view else parse_folder_id(request.args.get('folder_id'))
    active_folder = CredentialFolder.query.get(active_folder_id) if active_folder_id else None
    favorite_ids = get_user_favorite_ids(current_user.id)
    show_favorites_nav = bool(favorite_ids)

    credentials_query = accessible_query(current_user, Credential, 'credentials').order_by(Credential.website_name.asc())
    if active_favorites:
        if favorite_ids:
            credentials_query = credentials_query.filter(Credential.id.in_(favorite_ids))
        else:
            return redirect(url_for('credentials.index'))
    elif space_view:
        credentials_query = apply_section_filter(credentials_query, Credential, section, filter_team_id)
    elif not search_query:
        if active_folder_id is None:
            credentials_query = credentials_query.filter(Credential.folder_id.is_(None))
        else:
            credentials_query = credentials_query.filter(Credential.folder_id == active_folder_id)

    if search_query:
        like = f'%{search_query}%'
        credentials_query = credentials_query.filter(
            or_(
                Credential.website_name.ilike(like),
                Credential.username.ilike(like),
                Credential.website_url.ilike(like),
                Credential.notes.ilike(like),
            )
        )

    credentials = credentials_query.all()
    nav = visibility_nav_context('credentials', current_user, section, filter_team_id)

    return render_template(
        'credentials/index.html',
        folders=folders,
        credentials=credentials,
        active_folder_id=active_folder_id,
        active_folder=active_folder,
        active_favorites=active_favorites,
        favorite_ids=favorite_ids,
        show_favorites_nav=show_favorites_nav,
        search_query=search_query,
        **nav,
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
            return render_template(
                'credentials/create.html',
                folders=folders,
                selected_folder_id=folder_id,
                is_favorite=is_favorite,
                **_credentials_form_kwargs(),
            )

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
            is_favorite=False,
            created_by=current_user.id
        )
        apply_visibility_from_form(credential, 'credentials', current_user)

        # Encrypt and set password
        key = get_encryption_key()
        credential.set_password(password, key)

        db.session.add(credential)
        db.session.flush()
        if is_favorite:
            set_credential_favorite(current_user.id, credential.id, True)
        db.session.commit()

        flash(translate('credentials.flash.saved', website_name=website_name), 'success')
        return redirect(url_for('credentials.index', folder_id=folder_id) if folder_id else url_for('credentials.index'))

    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()
    selected_folder_id = parse_folder_id(request.args.get('folder_id'))
    return render_template(
        'credentials/create.html',
        folders=folders,
        selected_folder_id=selected_folder_id,
        is_favorite=False,
        **_credentials_form_kwargs(),
    )


@credentials_bp.route('/edit/<int:credential_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_credentials')
def edit(credential_id):
    """Edit a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_edit_item(current_user, credential, 'credentials'):
        return _credentials_denied()
    key = get_encryption_key()
    
    if request.method == 'POST':
        credential.website_url = request.form.get('website_url', '').strip()
        credential.website_name = request.form.get('website_name', '').strip()
        credential.username = request.form.get('username', '').strip()
        credential.notes = request.form.get('notes', '').strip()
        credential.folder_id = parse_folder_id(request.form.get('folder_id'))
        want_favorite = request.form.get('is_favorite') == 'on'
        apply_visibility_from_form(credential, 'credentials', current_user)
        
        new_password = request.form.get('password', '').strip()
        if new_password:
            credential.set_password(new_password, key)
        
        # Update favicon
        credential.favicon_url = get_favicon_url(credential.website_url)
        set_credential_favorite(current_user.id, credential.id, want_favorite)
        
        db.session.commit()
        
        flash(translate('credentials.flash.updated', website_name=credential.website_name), 'success')
        folder_id = credential.folder_id
        return redirect(url_for('credentials.index', folder_id=folder_id) if folder_id else url_for('credentials.index'))
    
    # Decrypt password for display
    decrypted_password = credential.get_password(key)
    folders = CredentialFolder.query.order_by(CredentialFolder.position.asc(), CredentialFolder.name.asc()).all()
    is_favorite = CredentialFavorite.query.filter_by(
        user_id=current_user.id,
        credential_id=credential.id
    ).first() is not None

    return render_template(
        'credentials/edit.html',
        credential=credential,
        password=decrypted_password,
        folders=folders,
        is_favorite=is_favorite,
        **_credentials_form_kwargs(credential),
    )


@credentials_bp.route('/delete/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def delete(credential_id):
    """Delete a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_edit_item(current_user, credential, 'credentials'):
        return _credentials_denied()
    website_name = credential.website_name
    folder_id = credential.folder_id

    CredentialFavorite.query.filter_by(credential_id=credential.id).delete()
    db.session.delete(credential)
    db.session.commit()

    flash(translate('credentials.flash.deleted', website_name=website_name), 'success')
    return redirect(url_for('credentials.index', folder_id=folder_id) if folder_id else url_for('credentials.index'))


@credentials_bp.route('/view-password/<int:credential_id>')
@login_required
@check_module_access('module_credentials')
def view_password(credential_id):
    """View decrypted password (AJAX endpoint)."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_view_item(current_user, credential, 'credentials'):
        return jsonify({'error': translate('visibility.flash.access_denied')}), 403
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
    return_folder_id = parse_folder_id(request.form.get('return_folder_id'))
    return redirect(
        url_for('credentials.index', folder_id=return_folder_id)
        if return_folder_id
        else url_for('credentials.index')
    )


@credentials_bp.route('/folders/<int:folder_id>/update', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def update_folder(folder_id):
    """Rename folder and/or change color."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    folder_name = request.form.get('name', '').strip()
    folder_color = normalize_folder_color(request.form.get('color', folder.color))

    if not folder_name:
        flash(translate('credentials.flash.folder_name_required'), 'danger')
        return redirect(url_for('credentials.index', folder_id=folder_id))

    folder.name = folder_name[:120]
    folder.color = folder_color
    db.session.commit()

    flash(translate('credentials.flash.folder_updated', folder_name=folder.name), 'success')
    return redirect(url_for('credentials.index', folder_id=folder.id))


@credentials_bp.route('/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def delete_folder(folder_id):
    """Delete folder; move credentials back to root."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    folder_name = folder.name

    Credential.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()

    flash(translate('credentials.flash.folder_deleted', folder_name=folder_name), 'success')
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

    return redirect(url_for('credentials.index', folder_id=folder_id))


@credentials_bp.route('/folders/<int:folder_id>/move-down', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_folder_down(folder_id):
    """Move folder one position down."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    next_folder = CredentialFolder.query.filter(
        CredentialFolder.position > folder.position
    ).order_by(CredentialFolder.position.asc()).first()

    if next_folder:
        folder.position, next_folder.position = next_folder.position, folder.position
        db.session.commit()

    return redirect(url_for('credentials.index', folder_id=folder_id))


@credentials_bp.route('/move/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_credential(credential_id):
    """Move credential into folder or root."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_edit_item(current_user, credential, 'credentials'):
        return jsonify({'success': False, 'error': translate('visibility.flash.access_denied')}), 403
    data = request.get_json(silent=True) or {}
    credential.folder_id = parse_folder_id(data.get('folder_id'))
    db.session.commit()
    return jsonify({'success': True})


@credentials_bp.route('/favorite/<int:credential_id>', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def toggle_favorite(credential_id):
    """Toggle per-user credential favorite status."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_view_item(current_user, credential, 'credentials'):
        return jsonify({'success': False, 'error': translate('visibility.flash.access_denied')}), 403
    existing = CredentialFavorite.query.filter_by(
        user_id=current_user.id,
        credential_id=credential.id
    ).first()

    if existing:
        db.session.delete(existing)
        is_favorite = False
    else:
        db.session.add(CredentialFavorite(user_id=current_user.id, credential_id=credential.id))
        is_favorite = True

    db.session.commit()
    favorites_count = CredentialFavorite.query.filter_by(user_id=current_user.id).count()
    return jsonify({
        'success': True,
        'is_favorite': is_favorite,
        'favorites_count': favorites_count,
    })



