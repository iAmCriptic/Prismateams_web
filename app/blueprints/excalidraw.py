from datetime import datetime
import json
import os

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app import db
from app.models.excalidraw import ExcalidrawDrawing, ExcalidrawDrawingVersion
from app.models.public_share import PublicShare
from app.models.user import User
from app.utils.access_control import check_module_access
from app.utils.excalidraw import (
    EMPTY_SCENE,
    MAX_VERSIONS,
    download_name,
    get_excalidraw_editor_asset_urls,
    get_excalidraw_lang_code,
    get_excalidraw_room_url,
    is_excalidraw_collab_enabled,
    new_scene_path,
    normalize_scene,
    read_scene_file,
    remove_file_quietly,
    save_thumbnail_data,
    write_scene_file,
)
from app.utils.i18n import _, get_current_language
from app.utils.module_visibility import (
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_edit_item,
    can_view_item,
    get_allowed_visibilities,
    parse_section_args,
    user_may_use_team,
    user_visibility_teams,
    visibility_form_context,
    visibility_nav_context,
)
from app.utils.public_share import (
    generate_unique_share_token,
    get_share_by_token,
    get_shares_for_resource,
    serialize_share_link,
    share_is_expired,
)

excalidraw_bp = Blueprint('excalidraw', __name__, url_prefix='/excalidraw')

MODULE = 'excalidraw'
SHARE_RESOURCE = 'excalidraw_drawing'


def _denied():
    flash(_('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('excalidraw.index'))


def _index_url(section=None, team_id=None):
    if section is None:
        section = session.get('excalidraw_last_view') or 'private'
        team_id = session.get('excalidraw_last_team_id')
    kwargs = {}
    if section and section != 'all':
        kwargs['view'] = section
    if section == 'team' and team_id:
        kwargs['team_id'] = team_id
    return url_for('excalidraw.index', **kwargs)


def _remember_section(section, filter_team_id):
    session['excalidraw_last_view'] = section
    session['excalidraw_last_team_id'] = filter_team_id


def _resolve_default_section(user):
    """Pick last remembered space or first allowed visibility."""
    allowed = set(get_allowed_visibilities(MODULE))
    teams = user_visibility_teams(user, MODULE)
    last = (session.get('excalidraw_last_view') or '').strip().lower()
    last_team = session.get('excalidraw_last_team_id')

    if last == 'private' and 'private' in allowed:
        return 'private', None
    if last == 'public' and 'public' in allowed:
        return 'public', None
    if last == 'team' and 'team' in allowed and user_may_use_team(user, MODULE, last_team):
        return 'team', int(last_team)

    if 'private' in allowed:
        return 'private', None
    if 'team' in allowed and teams:
        return 'team', teams[0].id
    if 'public' in allowed:
        return 'public', None
    return 'private', None


def _visibility_raw_from_request():
    raw = (request.form.get('visibility') or '').strip()
    if raw:
        return raw
    view = (request.form.get('view') or request.args.get('view') or '').strip().lower()
    team_raw = request.form.get('team_id') or request.args.get('team_id')
    try:
        team_id = int(team_raw) if team_raw else None
    except (TypeError, ValueError):
        team_id = None
    if view == 'private':
        return 'private'
    if view == 'public':
        return 'public'
    if view == 'team' and team_id:
        return f'team:{team_id}'
    section, filter_team_id = parse_section_args(MODULE, current_user)
    if section == 'private':
        return 'private'
    if section == 'public':
        return 'public'
    if section == 'team' and filter_team_id:
        return f'team:{filter_team_id}'
    return None


def _apply_create_visibility(drawing):
    apply_visibility_from_form(drawing, MODULE, current_user, raw=_visibility_raw_from_request())


def _visibility_selected(drawing):
    if getattr(drawing, 'visibility', None) == 'team' and getattr(drawing, 'team_id', None):
        return f'team:{drawing.team_id}'
    return getattr(drawing, 'visibility', None) or 'public'


def _prune_versions(drawing_id):
    versions = ExcalidrawDrawingVersion.query.filter_by(drawing_id=drawing_id).order_by(
        ExcalidrawDrawingVersion.version_number.desc()
    ).all()
    for old in versions[MAX_VERSIONS:]:
        remove_file_quietly(old.file_path)
        db.session.delete(old)


def _snapshot_current(drawing, user_id=None):
    if not drawing.file_path:
        return
    if user_id is None and getattr(current_user, 'is_authenticated', False):
        user_id = current_user.id
    if user_id is None:
        user_id = drawing.created_by
    version = ExcalidrawDrawingVersion(
        drawing_id=drawing.id,
        version_number=drawing.version_number,
        file_path=drawing.file_path,
        created_by=user_id,
    )
    db.session.add(version)
    _prune_versions(drawing.id)


def _heading_for_section(section, teams, filter_team_id):
    if section == 'private':
        return _('visibility.nav.private')
    if section == 'public':
        return _('visibility.nav.public')
    if section == 'team' and filter_team_id:
        for team in teams:
            if team.id == filter_team_id:
                return team.name
        return _('visibility.nav.team')
    return _('excalidraw.index.heading')


def _share_guest_ok(token: str) -> bool:
    return bool(session.get(f'share_auth_{token}'))


def _serialize_excalidraw_share(share: PublicShare) -> dict:
    data = serialize_share_link(share)
    creator = User.query.get(share.created_by) if share.created_by else None
    data['created_by'] = {
        'id': creator.id if creator else None,
        'name': (creator.full_name or creator.username) if creator else '—',
    }
    data['created_at'] = share.created_at.isoformat() if share.created_at else None
    data['created_at_display'] = (
        share.created_at.strftime('%d.%m.%Y %H:%M') if share.created_at else None
    )
    data['mode_label'] = (
        _('excalidraw.share.mode_edit') if share.mode == 'edit' else _('excalidraw.share.mode_view')
    )
    return data


def _editor_context(drawing, *, can_edit, return_url, scene_url, download_url,
                    is_share_guest=False, share_manage=False):
    collab_enabled = is_excalidraw_collab_enabled() and not is_share_guest
    if is_share_guest:
        theme_dark = False
        theme_oled = False
        username = _('excalidraw.share.guest_name')
        user_color = '#6c757d'
        user_id = 0
    else:
        theme_dark = bool(getattr(current_user, 'dark_mode', False))
        theme_oled = bool(getattr(current_user, 'oled_mode', False))
        username = current_user.full_name or current_user.username or f'User {current_user.id}'
        user_color = (
            f'#{(current_user.id * 47) % 200 + 30:02x}'
            f'{(current_user.id * 91) % 160 + 40:02x}'
            f'{(current_user.id * 13) % 180 + 50:02x}'
        )
        user_id = current_user.id

    assets = get_excalidraw_editor_asset_urls()
    ctx = {
        'drawing': drawing,
        'can_edit': can_edit,
        'return_url': return_url,
        'download_url': download_url,
        'scene_url': scene_url,
        'collab_enabled': collab_enabled,
        'room_url': get_excalidraw_room_url() if collab_enabled else '',
        'room_id': drawing.room_id if collab_enabled else '',
        'room_key': drawing.room_key if collab_enabled else '',
        'theme_dark': theme_dark,
        'theme_oled': theme_oled,
        'username': username,
        'user_color': user_color,
        'user_id': user_id,
        'excalidraw_version': assets['version'],
        'excalidraw_css_url': assets['css_url'],
        'excalidraw_asset_path': assets['asset_path'],
        'excalidraw_cdn_base': assets['cdn_base'],
        'excalidraw_module_url': assets['module_url'],
        'excalidraw_module_fallback': assets['module_fallback'],
        'excalidraw_lang_code': get_excalidraw_lang_code(get_current_language()),
        'is_share_guest': is_share_guest,
        'share_manage': share_manage,
        'visibility_selected': _visibility_selected(drawing),
    }
    if share_manage and not is_share_guest:
        ctx.update(visibility_form_context(MODULE, current_user, item=drawing))
    return ctx


def _save_scene_payload(drawing, payload, *, user_id=None):
    try:
        scene_data = normalize_scene(payload.get('scene') or payload)
    except ValueError:
        return jsonify({'success': False, 'error': _('excalidraw.save.invalid')}), 400

    try:
        path = new_scene_path(drawing.id, drawing.name)
        write_scene_file(path, scene_data)
    except ValueError:
        return jsonify({'success': False, 'error': _('excalidraw.save.too_large')}), 413

    _snapshot_current(drawing, user_id=user_id)
    drawing.file_path = path
    drawing.version_number = (drawing.version_number or 1) + 1
    drawing.updated_at = datetime.utcnow()

    thumb = save_thumbnail_data(drawing.id, payload.get('thumbnail'))
    if thumb:
        drawing.thumbnail_path = thumb

    new_name = (payload.get('name') or '').strip()
    if new_name and new_name != drawing.name:
        drawing.name = new_name[:255]

    db.session.commit()
    return jsonify({
        'success': True,
        'version_number': drawing.version_number,
        'name': drawing.name,
        'updated_at': drawing.updated_at.isoformat() if drawing.updated_at else None,
    })


@excalidraw_bp.route('/')
@login_required
@check_module_access('module_excalidraw')
def index():
    search_query = (request.args.get('q') or '').strip()
    section, filter_team_id = parse_section_args(MODULE, current_user)

    if section == 'all':
        default_section, default_team = _resolve_default_section(current_user)
        kwargs = {'view': default_section}
        if default_team:
            kwargs['team_id'] = default_team
        if search_query:
            kwargs['q'] = search_query
        return redirect(url_for('excalidraw.index', **kwargs))

    _remember_section(section, filter_team_id)

    query = accessible_query(current_user, ExcalidrawDrawing, MODULE)
    if section in ('private', 'team', 'public'):
        query = apply_section_filter(query, ExcalidrawDrawing, section, filter_team_id)
    if search_query:
        query = query.filter(ExcalidrawDrawing.name.ilike(f'%{search_query}%'))
    drawings = query.order_by(ExcalidrawDrawing.updated_at.desc()).all()
    editable_ids = {d.id for d in drawings if can_edit_item(current_user, d, MODULE)}

    nav = visibility_nav_context(MODULE, current_user, section, filter_team_id)
    heading = _heading_for_section(section, nav.get('visibility_teams') or [], filter_team_id)
    form_ctx = visibility_form_context(
        MODULE, current_user,
        preselect_section=section,
        preselect_team_id=filter_team_id,
    )
    ctx = {**nav, **form_ctx}
    return render_template(
        'excalidraw/index.html',
        drawings=drawings,
        editable_ids=editable_ids,
        search_query=search_query,
        heading_label=heading,
        **ctx,
    )


@excalidraw_bp.route('/create', methods=['POST'])
@login_required
@check_module_access('module_excalidraw')
def create():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash(_('excalidraw.create.alerts.name_required'), 'danger')
        return redirect(_index_url())

    drawing = ExcalidrawDrawing(
        name=name,
        file_path='',
        created_by=current_user.id,
        room_id=ExcalidrawDrawing.generate_room_id(),
        room_key=ExcalidrawDrawing.generate_room_key(),
        version_number=1,
    )
    _apply_create_visibility(drawing)
    db.session.add(drawing)
    db.session.flush()

    path = new_scene_path(drawing.id, name)
    write_scene_file(path, dict(EMPTY_SCENE))
    drawing.file_path = path
    db.session.commit()

    flash(_('excalidraw.flash.created', name=name), 'success')
    return redirect(_index_url())


@excalidraw_bp.route('/upload', methods=['POST'])
@login_required
@check_module_access('module_excalidraw')
def upload():
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        flash(_('excalidraw.upload.missing'), 'danger')
        return redirect(_index_url())

    filename = secure_filename(uploaded.filename)
    if not filename.lower().endswith('.excalidraw'):
        flash(_('excalidraw.upload.invalid_type'), 'danger')
        return redirect(_index_url())

    try:
        raw = uploaded.read()
        scene = normalize_scene(json.loads(raw.decode('utf-8')))
    except Exception:
        flash(_('excalidraw.upload.invalid_json'), 'danger')
        return redirect(_index_url())

    name = (request.form.get('name') or '').strip() or os.path.splitext(uploaded.filename)[0]
    drawing = ExcalidrawDrawing(
        name=name,
        file_path='',
        created_by=current_user.id,
        room_id=ExcalidrawDrawing.generate_room_id(),
        room_key=ExcalidrawDrawing.generate_room_key(),
        version_number=1,
    )
    _apply_create_visibility(drawing)
    db.session.add(drawing)
    db.session.flush()

    path = new_scene_path(drawing.id, name)
    try:
        write_scene_file(path, scene)
    except ValueError:
        db.session.rollback()
        flash(_('excalidraw.save.too_large'), 'danger')
        return redirect(_index_url())

    drawing.file_path = path
    db.session.commit()
    flash(_('excalidraw.flash.uploaded', name=name), 'success')
    return redirect(_index_url())


@excalidraw_bp.route('/edit/<int:drawing_id>')
@login_required
@check_module_access('module_excalidraw')
def edit(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_view_item(current_user, drawing, MODULE):
        return _denied()

    can_edit = can_edit_item(current_user, drawing, MODULE)
    return render_template(
        'excalidraw/edit.html',
        **_editor_context(
            drawing,
            can_edit=can_edit,
            return_url=_index_url(),
            scene_url=url_for('excalidraw.scene', drawing_id=drawing.id),
            download_url=url_for('excalidraw.download', drawing_id=drawing.id),
            share_manage=can_edit,
        ),
    )


@excalidraw_bp.route('/api/<int:drawing_id>/scene', methods=['GET', 'POST'])
@login_required
@check_module_access('module_excalidraw')
def scene(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if request.method == 'GET':
        if not can_view_item(current_user, drawing, MODULE):
            return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403
        data = read_scene_file(drawing.file_path)
        return jsonify({
            'success': True,
            'scene': data,
            'name': drawing.name,
            'version_number': drawing.version_number,
            'updated_at': drawing.updated_at.isoformat() if drawing.updated_at else None,
            'can_edit': can_edit_item(current_user, drawing, MODULE),
            'collab_enabled': is_excalidraw_collab_enabled(),
            'room_url': get_excalidraw_room_url(),
            'room_id': drawing.room_id,
            'room_key': drawing.room_key,
        })

    if not can_edit_item(current_user, drawing, MODULE):
        return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403

    payload = request.get_json(silent=True) or {}
    return _save_scene_payload(drawing, payload)


@excalidraw_bp.route('/visibility/<int:drawing_id>', methods=['POST'])
@login_required
@check_module_access('module_excalidraw')
def set_visibility(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_edit_item(current_user, drawing, MODULE):
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403
        return _denied()

    apply_visibility_from_form(drawing, MODULE, current_user)
    drawing.updated_at = datetime.utcnow()
    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'visibility': drawing.visibility,
            'team_id': drawing.team_id,
            'selected': _visibility_selected(drawing),
        })
    flash(_('excalidraw.flash.visibility_updated', name=drawing.name), 'success')
    return redirect(_index_url())


@excalidraw_bp.route('/api/<int:drawing_id>/shares', methods=['GET', 'POST'])
@login_required
@check_module_access('module_excalidraw')
def api_drawing_shares(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_edit_item(current_user, drawing, MODULE):
        return jsonify({'error': _('visibility.flash.access_denied')}), 403

    if request.method == 'GET':
        shares = get_shares_for_resource(SHARE_RESOURCE, drawing.id)
        pw_map = session.get('excalidraw_share_passwords') or {}
        out = []
        for s in shares:
            row = _serialize_excalidraw_share(s)
            known = pw_map.get(str(s.id))
            if known and s.password_hash:
                row['password'] = known
            out.append(row)
        return jsonify({'shares': out})

    data = request.get_json(silent=True) or {}
    mode = (data.get('mode') or 'view').strip().lower()
    if mode not in ('view', 'edit'):
        mode = 'view'
    password = (data.get('password') or '').strip() or None
    expires_at = None
    if data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(str(data['expires_at']).replace('Z', ''))
        except ValueError:
            pass
    share = PublicShare(
        resource_type=SHARE_RESOURCE,
        resource_id=drawing.id,
        mode=mode,
        token=generate_unique_share_token(),
        enabled=True,
        password_hash=generate_password_hash(password) if password else None,
        expires_at=expires_at,
        label=(data.get('label') or '').strip() or None,
        created_by=current_user.id,
    )
    db.session.add(share)
    db.session.commit()
    payload = _serialize_excalidraw_share(share)
    if password:
        payload['password'] = password
        pw_map = session.get('excalidraw_share_passwords') or {}
        pw_map[str(share.id)] = password
        session['excalidraw_share_passwords'] = pw_map
        session.modified = True
    return jsonify({'success': True, 'share': payload}), 201


@excalidraw_bp.route('/api/<int:drawing_id>/shares/<int:share_id>', methods=['PATCH', 'DELETE'])
@login_required
@check_module_access('module_excalidraw')
def api_drawing_share_detail(drawing_id, share_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_edit_item(current_user, drawing, MODULE):
        return jsonify({'error': _('visibility.flash.access_denied')}), 403

    share = PublicShare.query.filter_by(
        id=share_id,
        resource_type=SHARE_RESOURCE,
        resource_id=drawing.id,
    ).first_or_404()

    if request.method == 'DELETE':
        pw_map = session.get('excalidraw_share_passwords') or {}
        pw_map.pop(str(share.id), None)
        session['excalidraw_share_passwords'] = pw_map
        session.modified = True
        db.session.delete(share)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json(silent=True) or {}
    if 'mode' in data:
        mode = (data.get('mode') or 'view').strip().lower()
        if mode in ('view', 'edit'):
            share.mode = mode
    new_password = None
    if data.get('clear_password'):
        share.password_hash = None
        pw_map = session.get('excalidraw_share_passwords') or {}
        pw_map.pop(str(share.id), None)
        session['excalidraw_share_passwords'] = pw_map
        session.modified = True
    elif 'password' in data:
        raw = (data.get('password') or '').strip()
        if raw:
            share.password_hash = generate_password_hash(raw)
            new_password = raw
            pw_map = session.get('excalidraw_share_passwords') or {}
            pw_map[str(share.id)] = raw
            session['excalidraw_share_passwords'] = pw_map
            session.modified = True
    if 'enabled' in data:
        share.enabled = bool(data.get('enabled'))
    if 'expires_at' in data:
        raw_exp = data.get('expires_at')
        if not raw_exp:
            share.expires_at = None
        else:
            try:
                share.expires_at = datetime.fromisoformat(str(raw_exp).replace('Z', ''))
            except ValueError:
                pass
    share.updated_at = datetime.utcnow()
    db.session.commit()
    payload = _serialize_excalidraw_share(share)
    if new_password:
        payload['password'] = new_password
    return jsonify({'success': True, 'share': payload})


@excalidraw_bp.route('/share/<token>', methods=['GET', 'POST'])
def public_share(token):
    share = get_share_by_token(token)
    if not share or share.resource_type != SHARE_RESOURCE or share_is_expired(share):
        return render_template('excalidraw/share_unavailable.html'), 404
    drawing = ExcalidrawDrawing.query.get(share.resource_id)
    if not drawing:
        return render_template('excalidraw/share_unavailable.html'), 404

    if share.password_hash and not _share_guest_ok(token):
        if request.method == 'POST':
            pwd = request.form.get('password') or ''
            if check_password_hash(share.password_hash, pwd):
                session[f'share_auth_{token}'] = True
                return redirect(url_for('excalidraw.public_share', token=token))
            flash(_('excalidraw.share.wrong_password'), 'danger')
        return render_template('excalidraw/share_auth.html', token=token, drawing=drawing)

    can_edit_share = share.mode == 'edit'
    return render_template(
        'excalidraw/edit.html',
        **_editor_context(
            drawing,
            can_edit=can_edit_share,
            return_url='',
            scene_url=url_for('excalidraw.share_scene', token=token),
            download_url=url_for('excalidraw.share_download', token=token),
            is_share_guest=True,
            share_manage=False,
        ),
    )


@excalidraw_bp.route('/share/<token>/scene', methods=['GET', 'POST'])
def share_scene(token):
    share = get_share_by_token(token)
    if not share or share.resource_type != SHARE_RESOURCE or share_is_expired(share):
        return jsonify({'success': False, 'error': _('excalidraw.share.unavailable')}), 404
    if share.password_hash and not _share_guest_ok(token):
        return jsonify({'success': False, 'error': _('excalidraw.share.password_prompt')}), 401

    drawing = ExcalidrawDrawing.query.get(share.resource_id)
    if not drawing:
        return jsonify({'success': False, 'error': _('excalidraw.share.unavailable')}), 404

    if request.method == 'GET':
        data = read_scene_file(drawing.file_path)
        return jsonify({
            'success': True,
            'scene': data,
            'name': drawing.name,
            'version_number': drawing.version_number,
            'updated_at': drawing.updated_at.isoformat() if drawing.updated_at else None,
            'can_edit': share.mode == 'edit',
            'collab_enabled': False,
            'room_url': '',
            'room_id': '',
            'room_key': '',
        })

    if share.mode != 'edit':
        return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403

    payload = request.get_json(silent=True) or {}
    return _save_scene_payload(drawing, payload, user_id=drawing.created_by)


@excalidraw_bp.route('/share/<token>/download')
def share_download(token):
    share = get_share_by_token(token)
    if not share or share.resource_type != SHARE_RESOURCE or share_is_expired(share):
        flash(_('excalidraw.share.unavailable'), 'danger')
        return redirect(url_for('auth.login'))
    if share.password_hash and not _share_guest_ok(token):
        return redirect(url_for('excalidraw.public_share', token=token))

    drawing = ExcalidrawDrawing.query.get(share.resource_id)
    if not drawing or not drawing.file_path or not os.path.exists(drawing.file_path):
        flash(_('excalidraw.download.missing'), 'danger')
        return redirect(url_for('excalidraw.public_share', token=token))

    return send_file(
        drawing.file_path,
        as_attachment=True,
        download_name=download_name(drawing.name),
        mimetype='application/json',
    )


@excalidraw_bp.route('/download/<int:drawing_id>')
@login_required
@check_module_access('module_excalidraw')
def download(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_view_item(current_user, drawing, MODULE):
        return _denied()
    if not drawing.file_path or not os.path.exists(drawing.file_path):
        flash(_('excalidraw.download.missing'), 'danger')
        return redirect(_index_url())
    return send_file(
        drawing.file_path,
        as_attachment=True,
        download_name=download_name(drawing.name),
        mimetype='application/json',
    )


@excalidraw_bp.route('/thumbnail/<int:drawing_id>')
@login_required
@check_module_access('module_excalidraw')
def thumbnail(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_view_item(current_user, drawing, MODULE):
        return _denied()
    if not drawing.thumbnail_path or not os.path.exists(drawing.thumbnail_path):
        return ('', 404)
    return send_file(drawing.thumbnail_path, mimetype='image/png')


@excalidraw_bp.route('/rename/<int:drawing_id>', methods=['POST'])
@login_required
@check_module_access('module_excalidraw')
def rename(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    if not can_edit_item(current_user, drawing, MODULE):
        if request.is_json:
            return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403
        return _denied()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or request.form.get('name') or '').strip()
    if not name:
        if request.is_json:
            return jsonify({'success': False, 'error': _('excalidraw.create.alerts.name_required')}), 400
        flash(_('excalidraw.create.alerts.name_required'), 'danger')
        return redirect(_index_url())
    drawing.name = name[:255]
    drawing.updated_at = datetime.utcnow()
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True, 'name': drawing.name})
    flash(_('excalidraw.flash.renamed', name=drawing.name), 'success')
    return redirect(_index_url())


@excalidraw_bp.route('/delete/<int:drawing_id>', methods=['POST'])
@login_required
@check_module_access('module_excalidraw')
def delete(drawing_id):
    drawing = ExcalidrawDrawing.query.get_or_404(drawing_id)
    is_owner = drawing.created_by == current_user.id
    if not (is_owner or getattr(current_user, 'is_admin', False) or getattr(current_user, 'has_full_access', False)):
        return _denied()

    name = drawing.name
    PublicShare.query.filter_by(resource_type=SHARE_RESOURCE, resource_id=drawing.id).delete()
    for version in list(drawing.versions):
        remove_file_quietly(version.file_path)
    remove_file_quietly(drawing.file_path)
    remove_file_quietly(drawing.thumbnail_path)
    db.session.delete(drawing)
    db.session.commit()
    flash(_('excalidraw.flash.deleted', name=name), 'success')
    return redirect(_index_url())
