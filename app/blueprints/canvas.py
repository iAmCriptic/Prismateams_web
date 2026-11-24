from datetime import datetime
import os

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app import db
from app.models.canvas import CanvasDocument
from app.models.user import User
from app.utils.access_control import check_module_access
from app.utils.canvas import (
    CANVAS_PRESET_CATEGORIES,
    CANVAS_PRESET_MAP,
    authenticate_hycanvas_session,
    build_hycanvas_sso_jwt,
    get_hycanvas_browser_url,
    get_hycanvas_embed_url,
    hycanvas_create_design,
    hycanvas_delete_design,
    hycanvas_export_hyc,
    hycanvas_export_thumbnail,
    is_canvas_enabled,
    load_canvas_avatar_user_id,
    remove_file_quietly,
    save_canvas_hyc_file,
    save_canvas_thumbnail,
)
from app.utils.i18n import _
from app.utils.list_pagination import paginate_list
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

canvas_bp = Blueprint('canvas', __name__, url_prefix='/canvas')

MODULE = 'canvas'


def _denied():
    flash(_('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('canvas.index'))


def _index_url(section=None, team_id=None):
    if section is None:
        section = session.get('canvas_last_view') or 'private'
        team_id = session.get('canvas_last_team_id')
    kwargs = {}
    if section and section != 'all':
        kwargs['view'] = section
    if section == 'team' and team_id:
        kwargs['team_id'] = team_id
    return url_for('canvas.index', **kwargs)


def _remember_section(section, filter_team_id):
    session['canvas_last_view'] = section
    session['canvas_last_team_id'] = filter_team_id


def _resolve_default_section(user):
    allowed = set(get_allowed_visibilities(MODULE))
    teams = user_visibility_teams(user, MODULE)
    last = (session.get('canvas_last_view') or '').strip().lower()
    last_team = session.get('canvas_last_team_id')

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
    return _('canvas.index.heading')


def _apply_create_visibility(doc):
    raw = (request.form.get('visibility') or '').strip()
    if not raw:
        view = (request.form.get('view') or request.args.get('view') or '').strip().lower()
        team_raw = request.form.get('team_id') or request.args.get('team_id')
        if view == 'team' and team_raw:
            raw = f'team:{team_raw}'
        elif view in ('private', 'public'):
            raw = view
    apply_visibility_from_form(doc, MODULE, current_user, raw)


def _attach_hycanvas_cookies(resp, user):
    cookie_secure = bool(current_app.config.get('SESSION_COOKIE_SECURE', False)) and request.is_secure
    hycanvas_sess = authenticate_hycanvas_session(user)
    if hycanvas_sess:
        for cookie in hycanvas_sess.cookies:
            resp.set_cookie(
                cookie.name,
                cookie.value,
                httponly=True,
                samesite='Lax',
                secure=cookie_secure,
                path='/',
            )
    else:
        sso_jwt = build_hycanvas_sso_jwt(user)
        if sso_jwt:
            resp.set_cookie(
                'hycanvas_token',
                sso_jwt,
                httponly=True,
                samesite='Lax',
                secure=cookie_secure,
                path='/',
            )
    return resp


@canvas_bp.route('/')
@login_required
@check_module_access('module_canvas')
def index():
    hycanvas_url = f'{get_hycanvas_browser_url()}/'
    resp = make_response(
        render_template(
            'canvas/index.html',
            hycanvas_url=hycanvas_url,
            hycanvas_enabled=is_canvas_enabled(),
        )
    )
    return _attach_hycanvas_cookies(resp, current_user)


@canvas_bp.route('/create', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def create():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash(_('canvas.create.alerts.name_required'), 'danger')
        return redirect(_index_url())

    preset_key = (request.form.get('preset') or 'whiteboard').strip()
    preset = CANVAS_PRESET_MAP.get(preset_key) or CANVAS_PRESET_MAP['whiteboard']
    design_type = preset['type']
    width = preset['width']
    height = preset['height']

    if preset_key == 'custom':
        try:
            width = max(64, min(8000, int(request.form.get('custom_width') or 1920)))
            height = max(64, min(8000, int(request.form.get('custom_height') or 1080)))
        except (TypeError, ValueError):
            width, height = 1920, 1080

    remote_id = hycanvas_create_design(
        title=name[:255],
        design_type=design_type,
        width=width,
        height=height,
        user=current_user,
    )

    doc = CanvasDocument(
        name=name[:255],
        design_type=design_type,
        preset_key=preset['key'],
        width=width,
        height=height,
        hycanvas_design_id=remote_id,
        created_by=current_user.id,
    )
    _apply_create_visibility(doc)
    db.session.add(doc)
    db.session.commit()

    return redirect(url_for('canvas.edit', doc_id=doc.id))


@canvas_bp.route('/<int:doc_id>/edit')
@login_required
@check_module_access('module_canvas')
def edit(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_view_item(current_user, doc, MODULE):
        return _denied()

    can_edit = can_edit_item(current_user, doc, MODULE)
    if not doc.hycanvas_design_id and can_edit:
        remote_id = hycanvas_create_design(
            title=doc.name,
            design_type=doc.design_type,
            width=doc.width,
            height=doc.height,
            user=current_user,
        )
        if remote_id:
            doc.hycanvas_design_id = remote_id
            db.session.commit()

    return_url = _index_url()
    embed_url = get_hycanvas_embed_url(doc, user=current_user)
    preset = CANVAS_PRESET_MAP.get(doc.preset_key)

    resp = make_response(
        render_template(
            'canvas/edit.html',
            doc=doc,
            preset=preset,
            can_edit=can_edit,
            return_url=return_url,
            hycanvas_embed_url=embed_url,
            hycanvas_enabled=is_canvas_enabled(),
            theme_dark=bool(getattr(current_user, 'dark_mode', False)),
            theme_oled=bool(getattr(current_user, 'oled_mode', False)),
        )
    )
    return _attach_hycanvas_cookies(resp, current_user)


@canvas_bp.route('/<int:doc_id>/save', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def save(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_edit_item(current_user, doc, MODULE):
        return jsonify({'success': False, 'error': _('visibility.flash.access_denied')}), 403

    payload = request.get_json(silent=True) or {}
    new_name = (payload.get('name') or request.form.get('name') or '').strip()
    if new_name and new_name != doc.name:
        doc.name = new_name[:255]

    snapshot_saved = False
    if doc.hycanvas_design_id:
        hyc_bytes = hycanvas_export_hyc(doc.hycanvas_design_id, user=current_user)
        if hyc_bytes:
            old_path = doc.file_path
            doc.file_path = save_canvas_hyc_file(doc.id, doc.name, hyc_bytes)
            if old_path and old_path != doc.file_path:
                remove_file_quietly(old_path)
            snapshot_saved = True

        thumb_bytes = hycanvas_export_thumbnail(doc.hycanvas_design_id, user=current_user)
        if thumb_bytes:
            doc.thumbnail_path = save_canvas_thumbnail(doc.id, thumb_bytes)

    doc.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'name': doc.name,
        'snapshot_saved': snapshot_saved,
        'updated_at': doc.updated_at.isoformat() if doc.updated_at else None,
    })


@canvas_bp.route('/<int:doc_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def rename(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_edit_item(current_user, doc, MODULE):
        return _denied()
    new_name = (request.form.get('name') or '').strip()
    if new_name:
        doc.name = new_name[:255]
        doc.updated_at = datetime.utcnow()
        db.session.commit()
        flash(_('canvas.flash.renamed', name=doc.name), 'success')
    return redirect(_index_url())


@canvas_bp.route('/<int:doc_id>/visibility', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def visibility(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_edit_item(current_user, doc, MODULE):
        return _denied()
    apply_visibility_from_form(doc, MODULE, current_user, request.form.get('visibility'))
    doc.updated_at = datetime.utcnow()
    db.session.commit()
    flash(_('canvas.flash.visibility_updated'), 'success')
    return redirect(_index_url())


@canvas_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def delete(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_edit_item(current_user, doc, MODULE):
        return _denied()
    name = doc.name
    if doc.hycanvas_design_id:
        hycanvas_delete_design(doc.hycanvas_design_id, user=current_user)
    remove_file_quietly(doc.file_path)
    remove_file_quietly(doc.thumbnail_path)
    db.session.delete(doc)
    db.session.commit()
    flash(_('canvas.flash.deleted', name=name), 'success')
    return redirect(_index_url())


@canvas_bp.route('/<int:doc_id>/thumbnail')
@login_required
@check_module_access('module_canvas')
def thumbnail(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_view_item(current_user, doc, MODULE):
        abort(403)
    if not doc.thumbnail_path or not os.path.exists(doc.thumbnail_path):
        abort(404)
    return send_file(os.path.abspath(doc.thumbnail_path), mimetype='image/png')


@canvas_bp.route('/<int:doc_id>/download')
@login_required
@check_module_access('module_canvas')
def download(doc_id):
    doc = CanvasDocument.query.get_or_404(doc_id)
    if not can_view_item(current_user, doc, MODULE):
        return _denied()
    if doc.file_path and os.path.exists(doc.file_path):
        return send_file(
            os.path.abspath(doc.file_path),
            as_attachment=True,
            download_name=f'{doc.name}.hyc',
        )
    flash(_('canvas.flash.no_snapshot'), 'warning')
    return redirect(_index_url())


@canvas_bp.route('/avatar/<token>')
def avatar(token):
    user_id = load_canvas_avatar_user_id(token)
    if not user_id:
        abort(404)
    user = User.query.get(user_id)
    if not user or not user.profile_picture:
        abort(404)
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(upload_dir):
        project_root = os.path.dirname(current_app.root_path)
        upload_dir = os.path.join(project_root, upload_dir)
    path = os.path.abspath(os.path.join(upload_dir, 'profile_pics', user.profile_picture))
    if not os.path.isfile(path):
        abort(404)
    return send_file(path)
