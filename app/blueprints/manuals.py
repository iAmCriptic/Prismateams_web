from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.manual import Manual, ManualFolder
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
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


def redirect_to_folder(folder_id=None):
    if folder_id:
        return redirect(url_for('manuals.index', folder_id=folder_id))
    return redirect(url_for('manuals.index'))


@manuals_bp.route('/')
@login_required
@check_module_access('module_manuals')
def index():
    """List manuals for the active folder (root when folder_id is empty)."""
    folders = ManualFolder.query.order_by(ManualFolder.position.asc(), ManualFolder.name.asc()).all()
    active_folder_id = parse_folder_id(request.args.get('folder_id'))
    active_folder = ManualFolder.query.get(active_folder_id) if active_folder_id else None

    manuals_query = Manual.query.order_by(Manual.uploaded_at.desc())
    if active_folder_id is None:
        manuals = manuals_query.filter(Manual.folder_id.is_(None)).all()
    else:
        manuals = manuals_query.filter(Manual.folder_id == active_folder_id).all()

    return render_template(
        'manuals/index.html',
        manuals=manuals,
        folders=folders,
        active_folder_id=active_folder_id,
        active_folder=active_folder,
    )


@manuals_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@check_module_access('module_manuals')
def upload():
    """Upload a new manual (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.upload_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folders = ManualFolder.query.order_by(ManualFolder.position.asc(), ManualFolder.name.asc()).all()
    selected_folder_id = parse_folder_id(
        request.form.get('folder_id') if request.method == 'POST' else request.args.get('folder_id')
    )

    if request.method == 'POST':
        if 'file' not in request.files:
            flash(translate('manuals.flash.no_file_selected'), 'danger')
            return render_template(
                'manuals/upload.html',
                folders=folders,
                selected_folder_id=selected_folder_id,
            )

        file = request.files['file']
        title = request.form.get('title', '').strip()

        if file.filename == '':
            flash(translate('manuals.flash.no_file_selected'), 'danger')
            return render_template(
                'manuals/upload.html',
                folders=folders,
                selected_folder_id=selected_folder_id,
            )

        if not title:
            title = file.filename

        if not file.filename.lower().endswith('.pdf'):
            flash(translate('manuals.flash.only_pdf'), 'danger')
            return render_template(
                'manuals/upload.html',
                folders=folders,
                selected_folder_id=selected_folder_id,
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

        db.session.add(manual)
        db.session.commit()

        flash(translate('manuals.flash.uploaded', title=title), 'success')
        return redirect_to_folder(selected_folder_id)

    return render_template(
        'manuals/upload.html',
        folders=folders,
        selected_folder_id=selected_folder_id,
    )


@manuals_bp.route('/view/<int:manual_id>')
@login_required
@check_module_access('module_manuals')
def view(manual_id):
    """View a manual in the embedded PDF viewer."""
    manual = Manual.query.get_or_404(manual_id)
    file_path = resolve_manual_file_path(manual)

    if not os.path.exists(file_path):
        flash(translate('manuals.flash.file_not_found'), 'danger')
        return redirect_to_folder(manual.folder_id)

    back_url = (
        url_for('manuals.index', folder_id=manual.folder_id)
        if manual.folder_id
        else url_for('manuals.index')
    )
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
        return redirect(url_for('manuals.index'))

    max_position = db.session.query(db.func.max(ManualFolder.position)).scalar() or 0
    folder = ManualFolder(
        name=folder_name[:120],
        color=folder_color,
        position=max_position + 1,
        created_by=current_user.id
    )
    db.session.add(folder)
    db.session.commit()

    flash(translate('manuals.flash.folder_created', folder_name=folder.name), 'success')
    return_folder_id = parse_folder_id(request.form.get('return_folder_id'))
    return redirect_to_folder(return_folder_id)


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
        return redirect_to_folder(folder_id)

    folder.name = folder_name[:120]
    folder.color = folder_color
    db.session.commit()

    flash(translate('manuals.flash.folder_renamed', folder_name=folder.name), 'success')
    return redirect_to_folder(folder_id)


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

    Manual.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()

    flash(translate('manuals.flash.folder_deleted', folder_name=folder_name), 'success')
    return redirect(url_for('manuals.index'))


@manuals_bp.route('/folders/<int:folder_id>/move-up', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def move_folder_up(folder_id):
    """Move folder one position up (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    previous_folder = ManualFolder.query.filter(
        ManualFolder.position < folder.position
    ).order_by(ManualFolder.position.desc()).first()

    if previous_folder:
        folder.position, previous_folder.position = previous_folder.position, folder.position
        db.session.commit()

    return redirect_to_folder(folder_id)


@manuals_bp.route('/folders/<int:folder_id>/move-down', methods=['POST'])
@login_required
@check_module_access('module_manuals')
def move_folder_down(folder_id):
    """Move folder one position down (admin only)."""
    if not current_user.is_admin:
        flash(translate('manuals.flash.folder_admin_only'), 'danger')
        return redirect(url_for('manuals.index'))

    folder = ManualFolder.query.get_or_404(folder_id)
    next_folder = ManualFolder.query.filter(
        ManualFolder.position > folder.position
    ).order_by(ManualFolder.position.asc()).first()

    if next_folder:
        folder.position, next_folder.position = next_folder.position, folder.position
        db.session.commit()

    return redirect_to_folder(folder_id)


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
