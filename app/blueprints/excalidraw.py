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
from werkzeug.utils import secure_filename

from app import db
from app.models.excalidraw import ExcalidrawDrawing, ExcalidrawDrawingVersion
from app.utils.access_control import check_module_access
from app.utils.excalidraw import (
    EMPTY_SCENE,
    MAX_VERSIONS,
    download_name,
    get_excalidraw_editor_asset_urls,
    get_excalidraw_room_url,
    is_excalidraw_collab_enabled,
    new_scene_path,
    normalize_scene,
    read_scene_file,
    remove_file_quietly,
    save_thumbnail_data,
    write_scene_file,
)
from app.utils.i18n import _
from app.utils.module_visibility import (
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_edit_item,
    can_view_item,
    parse_section_args,
    visibility_nav_context,
)

excalidraw_bp = Blueprint('excalidraw', __name__, url_prefix='/excalidraw')

MODULE = 'excalidraw'


def _denied():
    flash(_('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('excalidraw.index'))


def _index_url(section=None, team_id=None):
    if section is None:
        section = session.get('excalidraw_last_view') or 'all'
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


def _prune_versions(drawing_id):
    versions = ExcalidrawDrawingVersion.query.filter_by(drawing_id=drawing_id).order_by(
        ExcalidrawDrawingVersion.version_number.desc()
    ).all()
    for old in versions[MAX_VERSIONS:]:
        remove_file_quietly(old.file_path)
        db.session.delete(old)


def _snapshot_current(drawing):
    if not drawing.file_path:
        return
    version = ExcalidrawDrawingVersion(
        drawing_id=drawing.id,
        version_number=drawing.version_number,
        file_path=drawing.file_path,
        created_by=current_user.id,
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


@excalidraw_bp.route('/')
@login_required
@check_module_access('module_excalidraw')
def index():
    search_query = (request.args.get('q') or '').strip()
    section, filter_team_id = parse_section_args(MODULE, current_user)
    _remember_section(section, filter_team_id)

    query = accessible_query(current_user, ExcalidrawDrawing, MODULE)
    if section in ('private', 'team', 'public'):
        query = apply_section_filter(query, ExcalidrawDrawing, section, filter_team_id)
    if search_query:
        query = query.filter(ExcalidrawDrawing.name.ilike(f'%{search_query}%'))
    drawings = query.order_by(ExcalidrawDrawing.updated_at.desc()).all()

    nav = visibility_nav_context(MODULE, current_user, section, filter_team_id)
    heading = _heading_for_section(section, nav.get('visibility_teams') or [], filter_team_id)
    return render_template(
        'excalidraw/index.html',
        drawings=drawings,
        search_query=search_query,
        heading_label=heading,
        **nav,
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
    collab_enabled = is_excalidraw_collab_enabled()
    theme_dark = bool(getattr(current_user, 'dark_mode', False))
    theme_oled = bool(getattr(current_user, 'oled_mode', False))
    username = current_user.full_name or current_user.username or f'User {current_user.id}'
    user_color = (
        f'#{(current_user.id * 47) % 200 + 30:02x}'
        f'{(current_user.id * 91) % 160 + 40:02x}'
        f'{(current_user.id * 13) % 180 + 50:02x}'
    )

    assets = get_excalidraw_editor_asset_urls()
    return render_template(
        'excalidraw/edit.html',
        drawing=drawing,
        can_edit=can_edit,
        return_url=_index_url(),
        download_url=url_for('excalidraw.download', drawing_id=drawing.id),
        scene_url=url_for('excalidraw.scene', drawing_id=drawing.id),
        collab_enabled=collab_enabled,
        room_url=get_excalidraw_room_url(),
        room_id=drawing.room_id,
        room_key=drawing.room_key,
        theme_dark=theme_dark,
        theme_oled=theme_oled,
        username=username,
        user_color=user_color,
        user_id=current_user.id,
        excalidraw_version=assets['version'],
        excalidraw_css_url=assets['css_url'],
        excalidraw_asset_path=assets['asset_path'],
        excalidraw_cdn_base=assets['cdn_base'],
        excalidraw_module_url=assets['module_url'],
        excalidraw_module_fallback=assets['module_fallback'],
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
    try:
        scene_data = normalize_scene(payload.get('scene') or payload)
    except ValueError:
        return jsonify({'success': False, 'error': _('excalidraw.save.invalid')}), 400

    try:
        path = new_scene_path(drawing.id, drawing.name)
        write_scene_file(path, scene_data)
    except ValueError:
        return jsonify({'success': False, 'error': _('excalidraw.save.too_large')}), 413

    _snapshot_current(drawing)
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
    for version in list(drawing.versions):
        remove_file_quietly(version.file_path)
    remove_file_quietly(drawing.file_path)
    remove_file_quietly(drawing.thumbnail_path)
    db.session.delete(drawing)
    db.session.commit()
    flash(_('excalidraw.flash.deleted', name=name), 'success')
    return redirect(_index_url())
