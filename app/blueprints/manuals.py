from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from app import db
from app.models.manual import Manual, ManualFolder
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from app.utils.module_visibility import (
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_TEAM,
    accessible_query,
    apply_section_filter,
    apply_visibility_from_form,
    can_view_item,
    parse_section_args,
    visibility_form_context,
    visibility_nav_context,
)
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import re

manuals_bp = Blueprint('manuals', __name__)


def normalize_folder_color(raw_color):
    """Normalize folder color input to #RRGGBB."""
    color = (raw_color or '').strip()
    if re.fullmatch(r'#[0-9A-Fa-f]{6}', color):
        return color.lower()
    if re.fullmatch(r'[0-9A-Fa-f]{6}', color):
        return f'#{color.lower()}'
    return '#0d6efd'


def parse_folder_id(raw_folder_id):
    """Parse and validate folder id from form/json value."""
    if raw_folder_id in (None, '', 'null'):
        return None
    try:
        folder_id = int(raw_folder_id)
    except (TypeError, ValueError):
        return None
    folder = ManualFolder.query.get(folder_id)
    return folder.id if folder else None


def resolve_manual_file_path(manual):
    """Resolve absolute path for a manual PDF on disk."""
    file_path = manual.file_path
    if not os.path.isabs(file_path):
        file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        project_root = current_app.root_path
        uploads_path = os.path.join(project_root, '..', 'uploads', 'manuals', manual.filename)
        file_path = os.path.abspath(uploads_path)

    return file_path


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


def _index_url_kwargs(folder=None, view=None, team_id=None, folder_id=None):
    """Build query args for manuals.index redirects."""
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
    elif view and view not in ('all',):
        kwargs['view'] = view
        if view == VISIBILITY_TEAM and team_id:
            kwargs['team_id'] = team_id
    return kwargs


def redirect_to_folder(folder_id=None, folder=None, view=None, team_id=None):
    if folder is None and folder_id:
        folder = ManualFolder.query.get(folder_id)
    return redirect(url_for('manuals.index', **_index_url_kwargs(
        folder=folder,
        view=view,
        team_id=team_id,
        folder_id=folder_id,
    )))


def _scope_folder_query(folder):
    """Base query for folders in the same scope as *folder*."""
    vis, team_id = _folder_scope(folder)
    query = ManualFolder.query.filter(ManualFolder.visibility == vis)
    if vis == VISIBILITY_TEAM and team_id:
        return query.filter(ManualFolder.team_id == team_id)
    return query.filter(ManualFolder.team_id.is_(None))


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


def _manuals_denied():
    flash(translate('visibility.flash.access_denied'), 'danger')
    return redirect(url_for('manuals.index'))


def _manuals_form_kwargs(folder_id=None):
    section, filter_team_id = parse_section_args('manuals', current_user)
    pre_section = None
    pre_team_id = None

    if folder_id:
        folder = ManualFolder.query.get(folder_id)
        if folder:
            pre_section, pre_team_id = _folder_scope(folder)
    elif section in (VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, VISIBILITY_TEAM):
        pre_section = section
        pre_team_id = filter_team_id

    all_folders = ManualFolder.query.order_by(
        ManualFolder.position.asc(), ManualFolder.name.asc()
    ).all()
    ctx = visibility_form_context(
        'manuals',
        current_user,
        preselect_section=pre_section,
        preselect_team_id=pre_team_id,
    )
    ctx['folders'] = all_folders
    return ctx


@manuals_bp.route('/')
@login_required
@check_module_access('module_manuals')
def index():
    """List manuals for all, folder, or space view."""
    all_folders = ManualFolder.query.order_by(
        ManualFolder.position.asc(), ManualFolder.name.asc()
    ).all()
    folders_by_scope = _group_folders_by_scope(all_folders)
    section, filter_team_id = parse_section_args('manuals', current_user)
    space_view = section in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC)
    search_query = (request.args.get('q') or '').strip()
    raw_folder_id = parse_folder_id(request.args.get('folder_id'))

    active_folder_id = None
    active_folder = None
    if raw_folder_id:
        active_folder = ManualFolder.query.get(raw_folder_id)
        if active_folder:
            active_folder_id = raw_folder_id
            folder_vis, folder_team_id = _folder_scope(active_folder)
            if not space_view:
                section = folder_vis
                filter_team_id = folder_team_id
                space_view = section in (VISIBILITY_PRIVATE, VISIBILITY_TEAM, VISIBILITY_PUBLIC)

    manuals_query = accessible_query(current_user, Manual, 'manuals').order_by(Manual.uploaded_at.desc())
    if active_folder_id:
        manuals_query = manuals_query.filter(Manual.folder_id == active_folder_id)
    elif space_view:
        manuals_query = apply_section_filter(manuals_query, Manual, section, filter_team_id)
        if not search_query:
            manuals_query = manuals_query.filter(Manual.folder_id.is_(None))
    # "Alle"-Ansicht: alle sichtbaren Einträge (ohne Ordner-Filter)

    if search_query:
        like = f'%{search_query}%'
        manuals_query = manuals_query.filter(
            or_(
                Manual.title.ilike(like),
                Manual.filename.ilike(like),
            )
        )

    manuals = manuals_query.all()
    nav = visibility_nav_context('manuals', current_user, section, filter_team_id)

    return render_template(
        'manuals/index.html',
        manuals=manuals,
        folders=all_folders,
        folders_by_scope=folders_by_scope,
        active_folder_id=active_folder_id,
        active_folder=active_folder,
        search_query=search_query,
        **nav,
    )


@manuals_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@check_module_access('module_manuals')
def upload():
    """Upload a new manual (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.upload_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    selected_folder_id = parse_folder_id(
        request.form.get('folder_id') if request.method == 'POST' else request.args.get('folder_id')
    )
    form_ctx = _manuals_form_kwargs(folder_id=selected_folder_id)

    if request.method == 'POST':
        if 'file' not in request.files:
            flash(translate('manuals.flash.no_file_selected'), 'danger')
            return render_template(
                'manuals/upload.html',
                selected_folder_id=selected_folder_id,
                **form_ctx,
            )

        file = request.files['file']
        title = request.form.get('title', '').strip()

        if file.filename == '':
            flash(translate('manuals.flash.no_file_selected'), 'danger')
            return render_template(
                'manuals/upload.html',
                selected_folder_id=selected_folder_id,
                **form_ctx,
            )

        if not title:
            title = file.filename

        if not file.filename.lower().endswith('.pdf'):
            flash(translate('manuals.flash.only_pdf'), 'danger')
            return render_template(
                'manuals/upload.html',
                selected_folder_id=selected_folder_id,
                **form_ctx,
            )

        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join('uploads', 'manuals', filename)

        absolute_filepath = os.path.abspath(filepath)
        os.makedirs(os.path.dirname(absolute_filepath), exist_ok=True)
        file.save(absolute_filepath)

        manual = Manual(
            title=title,
            filename=filename,
            file_path=absolute_filepath,
            file_size=os.path.getsize(absolute_filepath),
            folder_id=selected_folder_id,
            uploaded_by=current_user.id
        )
        apply_visibility_from_form(manual, 'manuals', current_user)

        db.session.add(manual)
        db.session.commit()

        flash(translate('manuals.flash.uploaded', title=title), 'success')
        folder = ManualFolder.query.get(selected_folder_id) if selected_folder_id else None
        if folder:
            return redirect_to_folder(folder_id=selected_folder_id, folder=folder)
        return redirect(url_for('manuals.index', **_index_url_kwargs(
            view=manual.visibility,
            team_id=manual.team_id if manual.visibility == VISIBILITY_TEAM else None,
        )))

    return render_template(
        'manuals/upload.html',
        selected_folder_id=selected_folder_id,
        **form_ctx,
    )


@manuals_bp.route('/view/<int:manual_id>')
@login_required
@check_module_access('module_manuals')
def view(manual_id):
    """View a manual in the embedded PDF viewer."""
    manual = Manual.query.get_or_404(manual_id)
    if not can_view_item(current_user, manual, 'manuals'):
        return _manuals_denied()
    file_path = resolve_manual_file_path(manual)

    if not os.path.exists(file_path):
        flash(translate('manuals.flash.file_not_found'), 'danger')
        return redirect_to_folder(manual.folder_id)

    folder = ManualFolder.query.get(manual.folder_id) if manual.folder_id else None
    back_url = url_for('manuals.index', **_index_url_kwargs(folder=folder, folder_id=manual.folder_id))
    return render_template(
        'manuals/view.html',
        manual=manual,
        back_url=back_url,
        pdf_src=url_for('manuals.raw', manual_id=manual.id),
        download_url=url_for('manuals.download', manual_id=manual.id),
    )


@manuals_bp.route('/raw/<int:manual_id>')
@login_required
@check_module_access('module_manuals')
def raw(manual_id):
    """Serve raw PDF bytes for the viewer iframe."""
    manual = Manual.query.get_or_404(manual_id)
    if not can_view_item(current_user, manual, 'manuals'):
        return _manuals_denied()
    file_path = resolve_manual_file_path(manual)

    if not os.path.exists(file_path):
        flash(translate('manuals.flash.file_not_found'), 'danger')
        return redirect_to_folder(manual.folder_id)

    return send_file(file_path, mimetype='application/pdf')


@manuals_bp.route('/download/<int:manual_id>')
@login_required
@check_module_access('module_manuals')
def download(manual_id):
    """Download a manual."""
    manual = Manual.query.get_or_404(manual_id)
    if not can_view_item(current_user, manual, 'manuals'):
        return _manuals_denied()
    file_path = resolve_manual_file_path(manual)

    if not os.path.exists(file_path):
        flash(translate('manuals.flash.file_not_found'), 'danger')
        return redirect_to_folder(manual.folder_id)

    return send_file(file_path, as_attachment=True, download_name=f"{manual.title}.pdf")


@manuals_bp.route('/delete/<int:manual_id>', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def delete(manual_id):
    """Delete a manual (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.delete_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    manual = Manual.query.get_or_404(manual_id)
    folder_id = manual.folder_id
    file_path = resolve_manual_file_path(manual)

    if os.path.exists(file_path):
        os.remove(file_path)

    title = manual.title
    db.session.delete(manual)
    db.session.commit()

    flash(translate('manuals.flash.deleted', title=title), 'success')
    return redirect_to_folder(folder_id)


@manuals_bp.route('/folders/create', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def create_folder():
    """Create a new manual folder (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder_name = request.form.get('name', '').strip()
    folder_color = normalize_folder_color(request.form.get('color', '#0d6efd'))

    if not folder_name:
        flash(translate('manuals.flash.folder_name_required'), 'danger')
        return redirect(url_for('manuals.index', **_index_url_kwargs(
            view=request.form.get('return_view'),
            team_id=request.form.get('return_team_id'),
            folder_id=parse_folder_id(request.form.get('return_folder_id')),
        )))

    folder_visibility, folder_team_id = _parse_folder_scope_from_form()
    scope_query = ManualFolder.query.filter(ManualFolder.visibility == folder_visibility)
    if folder_visibility == VISIBILITY_TEAM and folder_team_id:
        scope_query = scope_query.filter(ManualFolder.team_id == folder_team_id)
    else:
        scope_query = scope_query.filter(ManualFolder.team_id.is_(None))
    max_position = scope_query.with_entities(db.func.max(ManualFolder.position)).scalar() or 0

    folder = ManualFolder(
        name=folder_name[:120],
        color=folder_color,
        position=max_position + 1,
        visibility=folder_visibility,
        team_id=folder_team_id,
        created_by=current_user.id
    )
    db.session.add(folder)
    db.session.commit()

    flash(translate('manuals.flash.folder_created', folder_name=folder.name), 'success')
    return_folder_id = parse_folder_id(request.form.get('return_folder_id'))
    return redirect(url_for('manuals.index', **_index_url_kwargs(
        folder=folder,
        folder_id=return_folder_id,
        view=request.form.get('return_view'),
        team_id=request.form.get('return_team_id'),
    )))


@manuals_bp.route('/folders/<int:folder_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def rename_folder(folder_id):
    """Rename a manual folder (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    folder_name = request.form.get('name', '').strip()
    folder_color = normalize_folder_color(request.form.get('color', folder.color))

    if not folder_name:
        flash(translate('manuals.flash.folder_name_required'), 'danger')
        return redirect_to_folder(folder_id, folder=folder)

    folder.name = folder_name[:120]
    folder.color = folder_color
    db.session.commit()

    flash(translate('manuals.flash.folder_renamed', folder_name=folder.name), 'success')
    return redirect_to_folder(folder_id, folder=folder)


@manuals_bp.route('/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def delete_folder(folder_id):
    """Delete a folder; move manuals to root (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    folder_name = folder.name
    redirect_kwargs = _index_url_kwargs(folder=folder)

    Manual.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()

    flash(translate('manuals.flash.folder_deleted', folder_name=folder_name), 'success')
    return redirect(url_for('manuals.index', **redirect_kwargs))


@manuals_bp.route('/folders/<int:folder_id>/move-up', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def move_folder_up(folder_id):
    """Move folder one position up (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    previous_folder = _scope_folder_query(folder).filter(
        ManualFolder.position < folder.position
    ).order_by(ManualFolder.position.desc()).first()

    if previous_folder:
        folder.position, previous_folder.position = previous_folder.position, folder.position
        db.session.commit()

    return redirect_to_folder(folder_id, folder=folder)


@manuals_bp.route('/folders/<int:folder_id>/move-down', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def move_folder_down(folder_id):
    """Move folder one position down (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    next_folder = _scope_folder_query(folder).filter(
        ManualFolder.position > folder.position
    ).order_by(ManualFolder.position.asc()).first()

    if next_folder:
        folder.position, next_folder.position = next_folder.position, folder.position
        db.session.commit()

    return redirect_to_folder(folder_id, folder=folder)


@manuals_bp.route('/move/<int:manual_id>', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def move_manual(manual_id):
    """Move manual into folder or root (admin only)."""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    manual = Manual.query.get_or_404(manual_id)
    data = request.get_json(silent=True) or {}
    manual.folder_id = parse_folder_id(data.get('folder_id'))
    db.session.commit()
    return jsonify({'success': True})
