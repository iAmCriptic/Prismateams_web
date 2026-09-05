from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from app import db
from app.models.credential import Credential, CredentialFolder, CredentialFavorite
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.module_visibility import (
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TEAM,
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_edit_item,
    can_view_item,
    parse_section_args,
    visibility_form_context,
    visibility_nav_context,
)
import os
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

credentials_bp = Blueprint('credentials', __name__)


class CredentialEncryptionError(RuntimeError):
    """Raised when CREDENTIAL_ENCRYPTION_KEY is missing or unusable."""


def get_encryption_key():
    """
    Load Fernet key for credential passwords.

    Fail-closed: only from CREDENTIAL_ENCRYPTION_KEY (env/config). No ephemeral
    key and no CWD file fallback — those break at-rest encryption guarantees.
    """
    key = (current_app.config.get('CREDENTIAL_ENCRYPTION_KEY') or '').strip()
    if not key:
        key = (os.environ.get('CREDENTIAL_ENCRYPTION_KEY') or '').strip()
    if not key:
        raise CredentialEncryptionError(
            "CREDENTIAL_ENCRYPTION_KEY fehlt in der .env. "
            "Erzeugen mit: python scripts/generate_encryption_keys.py"
        )
    return key.encode('utf-8')


def _credentials_key_missing_response(*, as_json=False):
    msg = translate('credentials.errors.encryption_key_missing')
    logger.error("CREDENTIAL_ENCRYPTION_KEY fehlt — Credentials-Aktion abgebrochen.")
    if as_json:
        return jsonify({'error': msg}), 503
    flash(msg, 'danger')
    return redirect(url_for('credentials.index'))


def get_favicon_url(website_url):
    """
    Favicon-URL nur über öffentliches CDN aus dem Domain-Label.

    Kein Server-seitiger Fetch gegen User-URLs (SSRF-/Intranet-Probe).
    """
    try:
        parsed = urlparse((website_url or '').strip())
        host = (parsed.hostname or '').strip().lower().rstrip('.')
        if not host:
            # Fallback: netloc ohne Port/Userinfo grob parsen
            netloc = (parsed.netloc or '').strip().lower()
            if '@' in netloc:
                netloc = netloc.rsplit('@', 1)[-1]
            host = netloc.split(':', 1)[0].rstrip('.')
        if not host or host in {'localhost', '127.0.0.1', '::1'} or host.endswith('.local'):
            return None
        # Nur Label an CDN — keine Requests vom Server
        return f'https://www.google.com/s2/favicons?domain={host}&sz=32'
    except Exception:
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


def _folder_scope(folder):
    """Return (visibility, team_id) for a folder."""
    if not folder:
        return VISIBILITY_PUBLIC, None
    vis = (folder.visibility or VISIBILITY_PUBLIC).strip().lower()
    if vis == VISIBILITY_TEAM and folder.team_id:
        return VISIBILITY_TEAM, folder.team_id
    if vis == VISIBILITY_PRIVATE:
        return VISIBILITY_PRIVATE, None
    return VISIBILITY_PUBLIC, None


def _group_folders_by_scope(folders):
    """Group folders for sidebar navigation."""
    grouped = {
        VISIBILITY_PRIVATE: [],
        VISIBILITY_PUBLIC: [],
        'teams': {},
    }
    for folder in folders:
        vis, team_id = _folder_scope(folder)
        if vis == VISIBILITY_TEAM and team_id:
            grouped['teams'].setdefault(team_id, []).append(folder)
        elif vis == VISIBILITY_PRIVATE:
            grouped[VISIBILITY_PRIVATE].append(folder)
        else:
            grouped[VISIBILITY_PUBLIC].append(folder)
    return grouped


def _folders_for_scope(all_folders, section, filter_team_id):
    """Return folders matching the current visibility scope."""
    if section == VISIBILITY_PRIVATE:
        return [f for f in all_folders if _folder_scope(f)[0] == VISIBILITY_PRIVATE]
    if section == VISIBILITY_PUBLIC:
        return [f for f in all_folders if _folder_scope(f)[0] == VISIBILITY_PUBLIC]
    if section == VISIBILITY_TEAM and filter_team_id:
        return [
            f for f in all_folders
            if _folder_scope(f) == (VISIBILITY_TEAM, filter_team_id)
        ]
    return list(all_folders)


def _index_url_kwargs(folder=None, view=None, team_id=None, folder_id=None):
    """Build query args for credentials.index redirects."""
    kwargs = {}
    if folder_id:
        kwargs['folder_id'] = folder_id
    if folder:
        vis, tid = _folder_scope(folder)
        if vis == VISIBILITY_TEAM and tid:
            kwargs['view'] = VISIBILITY_TEAM
            kwargs['team_id'] = tid
        elif vis in (VISIBILITY_PRIVATE, VISIBILITY_PUBLIC):
            kwargs['view'] = vis
    elif view and view not in ('all', 'favorites'):
        kwargs['view'] = view
        if view == VISIBILITY_TEAM and team_id:
            kwargs['team_id'] = team_id
    return kwargs


def _scope_folder_query(folder):
    """Base query for folders in the same scope as *folder*."""
    vis, team_id = _folder_scope(folder)
    query = CredentialFolder.query.filter(CredentialFolder.visibility == vis)
    if vis == VISIBILITY_TEAM and team_id:
        return query.filter(CredentialFolder.team_id == team_id)
    return query.filter(CredentialFolder.team_id.is_(None))


def _parse_folder_scope_from_form():
    """Read visibility scope for new folders from form hidden fields."""
    raw_view = (request.form.get('return_view') or '').strip().lower()
    raw_team_id = request.form.get('return_team_id')
    team_id = None
    if raw_view == VISIBILITY_TEAM:
        try:
            team_id = int(raw_team_id or 0) or None
        except (TypeError, ValueError):
            team_id = None
        if team_id:
            return VISIBILITY_TEAM, team_id
        return VISIBILITY_PRIVATE, None
    if raw_view == VISIBILITY_PRIVATE:
        return VISIBILITY_PRIVATE, None
    return VISIBILITY_PUBLIC, None


def _credentials_form_kwargs(item=None, folder_id=None):
    section, filter_team_id = parse_section_args('credentials', current_user)
    pre_section = None
    pre_team_id = None

    if item is None:
        if folder_id:
            folder = CredentialFolder.query.get(folder_id)
            if folder:
                pre_section, pre_team_id = _folder_scope(folder)
        elif section in (VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, VISIBILITY_TEAM):
            pre_section = section
            pre_team_id = filter_team_id

    all_folders = CredentialFolder.query.order_by(
        CredentialFolder.position.asc(), CredentialFolder.name.asc()
    ).all()

    ctx = visibility_form_context(
        'credentials',
        current_user,
        item=item,
        preselect_section=pre_section,
        preselect_team_id=pre_team_id,
    )
    ctx['scope_folders'] = all_folders
    return ctx


def _render_create_form(folder_id=None, is_favorite=False, **extra):
    selected_folder_id = folder_id
    form_ctx = _credentials_form_kwargs(folder_id=selected_folder_id)
    return render_template(
        'credentials/create.html',
        selected_folder_id=selected_folder_id,
        is_favorite=is_favorite,
        **form_ctx,
        **extra,
    )


@credentials_bp.route('/')
@login_required
@check_module_access('module_credentials')
def index():
    """List credentials for root, folder, space, or personal favorites view."""
    all_folders = CredentialFolder.query.order_by(
        CredentialFolder.position.asc(), CredentialFolder.name.asc()
    ).all()
    folders_by_scope = _group_folders_by_scope(all_folders)
    section, filter_team_id = parse_section_args('credentials', current_user)
    active_favorites = section == 'favorites'
    space_view = section in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC)
    search_query = request.args.get('q', '').strip()
    raw_folder_id = parse_folder_id(request.args.get('folder_id'))

    active_folder_id = None
    active_folder = None
    if raw_folder_id and not active_favorites:
        active_folder = CredentialFolder.query.get(raw_folder_id)
        if active_folder:
            active_folder_id = raw_folder_id
            folder_vis, folder_team_id = _folder_scope(active_folder)
            if not space_view:
                section = folder_vis
                filter_team_id = folder_team_id
                space_view = section in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC)
        else:
            active_folder_id = None
    elif not active_favorites and not space_view:
        active_folder_id = None

    favorite_ids = get_user_favorite_ids(current_user.id)
    show_favorites_nav = bool(favorite_ids)

    credentials_query = accessible_query(current_user, Credential, 'credentials').order_by(Credential.website_name.asc())
    if active_favorites:
        if favorite_ids:
            credentials_query = credentials_query.filter(Credential.id.in_(favorite_ids))
        else:
            return redirect(url_for('credentials.index'))
    elif active_folder_id:
        credentials_query = credentials_query.filter(Credential.folder_id == active_folder_id)
    elif space_view:
        credentials_query = apply_section_filter(credentials_query, Credential, section, filter_team_id)
        if not search_query:
            credentials_query = credentials_query.filter(Credential.folder_id.is_(None))
    # "Alle"-Ansicht: alle sichtbaren Einträge (ohne Ordner-Filter)

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
        folders=all_folders,
        folders_by_scope=folders_by_scope,
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
            return _render_create_form(folder_id=folder_id, is_favorite=is_favorite)

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

        try:
            key = get_encryption_key()
        except CredentialEncryptionError:
            return _credentials_key_missing_response()
        credential.set_password(password, key)

        db.session.add(credential)
        db.session.flush()
        if is_favorite:
            set_credential_favorite(current_user.id, credential.id, True)
        db.session.commit()

        flash(translate('credentials.flash.saved', website_name=website_name), 'success')
        folder = CredentialFolder.query.get(folder_id) if folder_id else None
        if folder:
            redirect_kwargs = _index_url_kwargs(folder=folder, folder_id=folder_id)
        else:
            redirect_kwargs = _index_url_kwargs(
                view=credential.visibility,
                team_id=credential.team_id if credential.visibility == VISIBILITY_TEAM else None,
            )
        return redirect(url_for('credentials.index', **redirect_kwargs))

    selected_folder_id = parse_folder_id(request.args.get('folder_id'))
    return _render_create_form(folder_id=selected_folder_id, is_favorite=False)


@credentials_bp.route('/edit/<int:credential_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_credentials')
def edit(credential_id):
    """Edit a credential entry."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_edit_item(current_user, credential, 'credentials'):
        return _credentials_denied()
    try:
        key = get_encryption_key()
    except CredentialEncryptionError:
        return _credentials_key_missing_response()
    
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
        folder = CredentialFolder.query.get(credential.folder_id) if credential.folder_id else None
        return redirect(url_for('credentials.index', **_index_url_kwargs(folder=folder, folder_id=credential.folder_id)))
    
    # Decrypt password for display
    decrypted_password = credential.get_password(key)
    is_favorite = CredentialFavorite.query.filter_by(
        user_id=current_user.id,
        credential_id=credential.id
    ).first() is not None

    return render_template(
        'credentials/edit.html',
        credential=credential,
        password=decrypted_password,
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
    folder = CredentialFolder.query.get(folder_id) if folder_id else None
    return redirect(url_for('credentials.index', **_index_url_kwargs(folder=folder, folder_id=folder_id)))


@credentials_bp.route('/view-password/<int:credential_id>')
@login_required
@check_module_access('module_credentials')
def view_password(credential_id):
    """View decrypted password (AJAX endpoint)."""
    credential = Credential.query.get_or_404(credential_id)
    if not can_view_item(current_user, credential, 'credentials'):
        return jsonify({'error': translate('visibility.flash.access_denied')}), 403
    try:
        key = get_encryption_key()
    except CredentialEncryptionError:
        return _credentials_key_missing_response(as_json=True)
    
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
        return redirect(url_for('credentials.index', **_index_url_kwargs(
            view=request.form.get('return_view'),
            team_id=request.form.get('return_team_id'),
            folder_id=parse_folder_id(request.form.get('return_folder_id')),
        )))

    folder_visibility, folder_team_id = _parse_folder_scope_from_form()
    scope_query = CredentialFolder.query.filter(CredentialFolder.visibility == folder_visibility)
    if folder_visibility == VISIBILITY_TEAM and folder_team_id:
        scope_query = scope_query.filter(CredentialFolder.team_id == folder_team_id)
    else:
        scope_query = scope_query.filter(CredentialFolder.team_id.is_(None))
    max_position = scope_query.with_entities(db.func.max(CredentialFolder.position)).scalar() or 0

    folder = CredentialFolder(
        name=folder_name[:120],
        color=folder_color,
        position=max_position + 1,
        visibility=folder_visibility,
        team_id=folder_team_id,
        created_by=current_user.id
    )
    db.session.add(folder)
    db.session.commit()

    flash(translate('credentials.flash.folder_created', folder_name=folder.name), 'success')
    return_folder_id = parse_folder_id(request.form.get('return_folder_id'))
    return redirect(url_for('credentials.index', **_index_url_kwargs(
        folder=folder,
        folder_id=return_folder_id,
        view=request.form.get('return_view'),
        team_id=request.form.get('return_team_id'),
    )))


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
    return redirect(url_for('credentials.index', **_index_url_kwargs(folder=folder, folder_id=folder.id)))


@credentials_bp.route('/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def delete_folder(folder_id):
    """Delete folder; move credentials back to root."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    folder_name = folder.name
    redirect_kwargs = _index_url_kwargs(folder=folder)

    Credential.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()

    flash(translate('credentials.flash.folder_deleted', folder_name=folder_name), 'success')
    return redirect(url_for('credentials.index', **redirect_kwargs))


@credentials_bp.route('/folders/<int:folder_id>/move-up', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_folder_up(folder_id):
    """Move folder one position up."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    previous_folder = _scope_folder_query(folder).filter(
        CredentialFolder.position < folder.position
    ).order_by(CredentialFolder.position.desc()).first()

    if previous_folder:
        folder.position, previous_folder.position = previous_folder.position, folder.position
        db.session.commit()

    return redirect(url_for('credentials.index', **_index_url_kwargs(folder=folder, folder_id=folder_id)))


@credentials_bp.route('/folders/<int:folder_id>/move-down', methods=['POST'])
@login_required
@check_module_access('module_credentials')
def move_folder_down(folder_id):
    """Move folder one position down."""
    folder = CredentialFolder.query.get_or_404(folder_id)
    next_folder = _scope_folder_query(folder).filter(
        CredentialFolder.position > folder.position
    ).order_by(CredentialFolder.position.asc()).first()

    if next_folder:
        folder.position, next_folder.position = next_folder.position, folder.position
        db.session.commit()

    return redirect(url_for('credentials.index', **_index_url_kwargs(folder=folder, folder_id=folder_id)))


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



