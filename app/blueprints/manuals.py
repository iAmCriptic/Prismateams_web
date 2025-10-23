from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models.manual import Manual
from werkzeug.utils import secure_filename
from datetime import datetime
import os

manuals_bp = Blueprint('manuals', __name__)


@manuals_bp.route('/')
@login_required
def index():
    """List all manuals."""
    manuals = Manual.query.order_by(Manual.uploaded_at.desc()).all()
    return render_template('manuals/index.html', manuals=manuals)


@manuals_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    """Upload a new manual (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren können Anleitungen hochladen.', 'danger')
        return redirect(url_for('manuals.index'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Keine Datei ausgewählt.', 'danger')
            return render_template('manuals/upload.html')
        
        file = request.files['file']
        title = request.form.get('title', '').strip()
        
        if file.filename == '':
            flash('Keine Datei ausgewählt.', 'danger')
            return render_template('manuals/upload.html')
        
        if not title:
            title = file.filename
        
        # Check if file is PDF
        if not file.filename.lower().endswith('.pdf'):
            flash('Nur PDF-Dateien sind erlaubt.', 'danger')
            return render_template('manuals/upload.html')
        
        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join('uploads', 'manuals', filename)
        
        # Ensure we use absolute path for saving
        absolute_filepath = os.path.abspath(filepath)
        file.save(absolute_filepath)
        
        # Create manual record
        manual = Manual(
            title=title,
            filename=filename,
            file_path=absolute_filepath,
            file_size=os.path.getsize(absolute_filepath),
            uploaded_by=current_user.id
        )
        
        db.session.add(manual)
        db.session.commit()
        
        flash(f'Anleitung "{title}" wurde hochgeladen.', 'success')
        return redirect(url_for('manuals.index'))
    
    return render_template('manuals/upload.html')


@manuals_bp.route('/view/<int:manual_id>')
@login_required
def view(manual_id):
    """View a manual (PDF in browser)."""
    manual = Manual.query.get_or_404(manual_id)
    
    # Ensure we have the correct absolute path
    file_path = manual.file_path
    if not os.path.isabs(file_path):
        # Convert relative path to absolute path
        file_path = os.path.abspath(file_path)
    
    # If file still doesn't exist, try to find it in uploads directory
    if not os.path.exists(file_path):
        # Try to construct the path from project root
        from flask import current_app
        project_root = current_app.root_path
        uploads_path = os.path.join(project_root, '..', 'uploads', 'manuals', manual.filename)
        file_path = os.path.abspath(uploads_path)
    
    if not os.path.exists(file_path):
        flash('Die Anleitung-Datei konnte nicht gefunden werden.', 'danger')
        return redirect(url_for('manuals.index'))
    
    return send_file(file_path, mimetype='application/pdf')


@manuals_bp.route('/download/<int:manual_id>')
@login_required
def download(manual_id):
    """Download a manual."""
    manual = Manual.query.get_or_404(manual_id)
    
    # Ensure we have the correct absolute path
    file_path = manual.file_path
    if not os.path.isabs(file_path):
        # Convert relative path to absolute path
        file_path = os.path.abspath(file_path)
    
    # If file still doesn't exist, try to find it in uploads directory
    if not os.path.exists(file_path):
        # Try to construct the path from project root
        from flask import current_app
        project_root = current_app.root_path
        uploads_path = os.path.join(project_root, '..', 'uploads', 'manuals', manual.filename)
        file_path = os.path.abspath(uploads_path)
    
    if not os.path.exists(file_path):
        flash('Die Anleitung-Datei konnte nicht gefunden werden.', 'danger')
        return redirect(url_for('manuals.index'))
    
    return send_file(file_path, as_attachment=True, download_name=f"{manual.title}.pdf")


@manuals_bp.route('/delete/<int:manual_id>', methods=['POST'])
@login_required
def delete(manual_id):
    """Delete a manual (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren können Anleitungen löschen.', 'danger')
        return redirect(url_for('manuals.index'))
    
    manual = Manual.query.get_or_404(manual_id)
    
    # Ensure we have the correct absolute path for deletion
    file_path = manual.file_path
    if not os.path.isabs(file_path):
        # Convert relative path to absolute path
        file_path = os.path.abspath(file_path)
    
    # If file still doesn't exist, try to find it in uploads directory
    if not os.path.exists(file_path):
        # Try to construct the path from project root
        from flask import current_app
        project_root = current_app.root_path
        uploads_path = os.path.join(project_root, '..', 'uploads', 'manuals', manual.filename)
        file_path = os.path.abspath(uploads_path)
    
    # Delete file if it exists
    if os.path.exists(file_path):
        os.remove(file_path)
    
    db.session.delete(manual)
    db.session.commit()
    
    flash(f'Anleitung "{manual.title}" wurde gelöscht.', 'success')
    return redirect(url_for('manuals.index'))



