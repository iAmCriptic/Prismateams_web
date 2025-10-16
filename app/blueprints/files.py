from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.file import File, FileVersion, Folder
from app.models.user import User
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import shutil

files_bp = Blueprint('files', __name__)

MAX_FILE_VERSIONS = 3


@files_bp.route('/')
@login_required
def index():
    """File manager root view."""
    return browse_folder(None)


@files_bp.route('/folder/<int:folder_id>')
@login_required
def browse_folder(folder_id):
    """Browse a specific folder."""
    current_folder = None
    if folder_id:
        current_folder = Folder.query.get_or_404(folder_id)
    
    # Get subfolders
    if folder_id:
        subfolders = Folder.query.filter_by(parent_id=folder_id).order_by(Folder.name).all()
    else:
        subfolders = Folder.query.filter_by(parent_id=None).order_by(Folder.name).all()
    
    # Get files in current folder
    files = File.query.filter_by(
        folder_id=folder_id,
        is_current=True
    ).order_by(File.name).all()
    
    return render_template(
        'files/index.html',
        current_folder=current_folder,
        subfolders=subfolders,
        files=files
    )


@files_bp.route('/create-folder', methods=['POST'])
@login_required
def create_folder():
    """Create a new folder."""
    folder_name = request.form.get('folder_name', '').strip()
    parent_id = request.form.get('parent_id')
    
    if not folder_name:
        flash('Bitte geben Sie einen Ordnernamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    parent_id = int(parent_id) if parent_id else None
    
    new_folder = Folder(
        name=folder_name,
        parent_id=parent_id,
        created_by=current_user.id
    )
    db.session.add(new_folder)
    db.session.commit()
    
    flash(f'Ordner "{folder_name}" wurde erstellt.', 'success')
    
    if parent_id:
        return redirect(url_for('files.browse_folder', folder_id=parent_id))
    return redirect(url_for('files.index'))


@files_bp.route('/create-file', methods=['POST'])
@login_required
def create_file():
    """Create a new text or markdown file."""
    filename = request.form.get('filename', '').strip()
    content = request.form.get('content', '')
    file_type = request.form.get('file_type', 'txt')
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    
    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Add file extension
    if file_type == 'md' and not filename.endswith('.md'):
        filename += '.md'
    elif file_type == 'txt' and not filename.endswith('.txt'):
        filename += '.txt'
    
    # Check if file with same name exists in folder
    existing_file = File.query.filter_by(
        name=filename,
        folder_id=folder_id,
        is_current=True
    ).first()
    
    if existing_file:
        flash(f'Datei "{filename}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Create file
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    stored_filename = f"{timestamp}_{filename}"
    filepath = os.path.join('uploads', 'files', stored_filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Write content to file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    new_file = File(
        name=filename,
        original_name=filename,
        folder_id=folder_id,
        uploaded_by=current_user.id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type='text/plain' if file_type == 'txt' else 'text/markdown',
        version_number=1,
        is_current=True
    )
    db.session.add(new_file)
    db.session.commit()
    
    flash(f'Datei "{filename}" wurde erstellt.', 'success')
    
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    return redirect(url_for('files.index'))


@files_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """Upload a file."""
    if 'file' not in request.files:
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    file = request.files['file']
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Check file size (100MB limit)
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    
    max_size = 100 * 1024 * 1024  # 100MB in bytes
    if file_size > max_size:
        flash(f'Datei ist zu groß. Maximale Größe: 100MB. Ihre Datei: {file_size / (1024*1024):.1f}MB', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    original_name = secure_filename(file.filename)
    
    # Check if file with same name exists in folder
    existing_file = File.query.filter_by(
        name=original_name,
        folder_id=folder_id,
        is_current=True
    ).first()
    
    if existing_file:
        overwrite = request.form.get('overwrite')
        if overwrite != 'yes':
            flash(f'Datei "{original_name}" existiert bereits. Möchten Sie sie überschreiben?', 'warning')
            return render_template(
                'files/confirm_overwrite.html',
                filename=original_name,
                folder_id=folder_id
            )
        
        # Create new version
        version_number = existing_file.version_number + 1
        
        # Save old version to version history
        old_version = FileVersion(
            file_id=existing_file.id,
            version_number=existing_file.version_number,
            file_path=os.path.abspath(existing_file.file_path),
            file_size=existing_file.file_size,
            uploaded_by=existing_file.uploaded_by
        )
        db.session.add(old_version)
        
        # Delete oldest version if we have more than MAX_FILE_VERSIONS
        versions = FileVersion.query.filter_by(file_id=existing_file.id).order_by(
            FileVersion.version_number.desc()
        ).all()
        
        if len(versions) >= MAX_FILE_VERSIONS:
            oldest = versions[-1]
            if os.path.exists(oldest.file_path):
                os.remove(oldest.file_path)
            db.session.delete(oldest)
        
        # Update existing file
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{original_name}"
        filepath = os.path.join('uploads', 'files', filename)
        file.save(filepath)
        
        # Store absolute path in database
        absolute_filepath = os.path.abspath(filepath)
        
        existing_file.file_path = absolute_filepath
        existing_file.file_size = os.path.getsize(absolute_filepath)
        existing_file.version_number = version_number
        existing_file.uploaded_by = current_user.id
        existing_file.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash(f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).', 'success')
    else:
        # Create new file
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{original_name}"
        filepath = os.path.join('uploads', 'files', filename)
        file.save(filepath)
        
        # Store absolute path in database
        absolute_filepath = os.path.abspath(filepath)
        
        new_file = File(
            name=original_name,
            original_name=original_name,
            folder_id=folder_id,
            uploaded_by=current_user.id,
            file_path=absolute_filepath,
            file_size=os.path.getsize(absolute_filepath),
            mime_type=file.content_type,
            version_number=1,
            is_current=True
        )
        db.session.add(new_file)
        db.session.commit()
        flash(f'Datei "{original_name}" wurde hochgeladen.', 'success')
    
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    return redirect(url_for('files.index'))


@files_bp.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
    """Download a file."""
    file = File.query.get_or_404(file_id)
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
        return redirect(url_for('files.index'))
    
    return send_file(file_path, as_attachment=True, download_name=file.original_name)


@files_bp.route('/download-version/<int:version_id>')
@login_required
def download_version(version_id):
    """Download a specific file version."""
    version = FileVersion.query.get_or_404(version_id)
    file = File.query.get_or_404(version.file_id)
    
    # Ensure we have an absolute path
    if not os.path.isabs(version.file_path):
        file_path = os.path.join(os.getcwd(), version.file_path)
    else:
        file_path = version.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        flash(f'Datei-Version "{file.original_name} v{version.version_number}" wurde nicht gefunden.', 'danger')
        return redirect(url_for('files.index'))
    
    return send_file(file_path, as_attachment=True, download_name=f"{file.original_name}_v{version.version_number}")


@files_bp.route('/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
def edit_file(file_id):
    """Edit a text file online."""
    file = File.query.get_or_404(file_id)
    
    # Check if file is editable (text file)
    editable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if file_ext not in editable_extensions:
        flash('Dieser Dateityp kann nicht online bearbeitet werden.', 'warning')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    if request.method == 'POST':
        content = request.form.get('content', '')
        
        # Save current version to history
        version = FileVersion(
            file_id=file.id,
            version_number=file.version_number,
            file_path=os.path.abspath(file.file_path),
            file_size=file.file_size,
            uploaded_by=file.uploaded_by
        )
        db.session.add(version)
        
        # Delete oldest version if needed
        versions = FileVersion.query.filter_by(file_id=file.id).order_by(
            FileVersion.version_number.desc()
        ).all()
        
        if len(versions) >= MAX_FILE_VERSIONS:
            oldest = versions[-1]
            if os.path.exists(oldest.file_path):
                os.remove(oldest.file_path)
            db.session.delete(oldest)
        
        # Save new version
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{file.original_name}"
        filepath = os.path.join('uploads', 'files', filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Store absolute path in database
        absolute_filepath = os.path.abspath(filepath)
        
        file.file_path = absolute_filepath
        file.file_size = os.path.getsize(absolute_filepath)
        file.version_number += 1
        file.uploaded_by = current_user.id
        file.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        flash('Datei wurde gespeichert.', 'success')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    # Read file content
    try:
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    return render_template('files/edit.html', file=file, content=content)


@files_bp.route('/view/<int:file_id>')
@login_required
def view_file(file_id):
    """View a file in fullscreen mode (for markdown/text files)."""
    file = File.query.get_or_404(file_id)
    
    # Check if file is viewable
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if file_ext not in viewable_extensions:
        flash('Dieser Dateityp kann nicht angezeigt werden.', 'warning')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    # Read file content
    try:
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f'Fehler beim Lesen der Datei: {str(e)}', 'danger')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    # Process markdown if it's a markdown file
    if file.name.endswith('.md'):
        try:
            import markdown
            md = markdown.Markdown(extensions=['tables', 'fenced_code', 'codehilite', 'nl2br'])
            processed_content = md.convert(content)
            current_app.logger.info(f"Markdown processed. Table detected: {'<table>' in processed_content}")
        except Exception as e:
            current_app.logger.error(f"Markdown processing error: {e}")
            processed_content = content
    else:
        processed_content = content
    
    return render_template('files/view.html', file=file, content=content, processed_content=processed_content)


@files_bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    """Delete a file."""
    file = File.query.get_or_404(file_id)
    folder_id = file.folder_id
    
    # Delete file and all versions
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
        
    if os.path.exists(file_path):
        os.remove(file_path)
    
    for version in file.versions:
        if not os.path.isabs(version.file_path):
            version_path = os.path.join(os.getcwd(), version.file_path)
        else:
            version_path = version.file_path
            
        if os.path.exists(version_path):
            os.remove(version_path)
    
    db.session.delete(file)
    db.session.commit()
    
    flash(f'Datei "{file.original_name}" wurde gelöscht.', 'success')
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    else:
        return redirect(url_for('files.index'))


@files_bp.route('/delete-folder/<int:folder_id>', methods=['POST'])
@login_required
def delete_folder(folder_id):
    """Delete a folder and all its contents."""
    folder = Folder.query.get_or_404(folder_id)
    parent_id = folder.parent_id
    
    def delete_folder_recursive(folder):
        # Delete all files in folder
        for file in folder.files:
            if not os.path.isabs(file.file_path):
                file_path = os.path.join(os.getcwd(), file.file_path)
            else:
                file_path = file.file_path
                
            if os.path.exists(file_path):
                os.remove(file_path)
                
            for version in file.versions:
                if not os.path.isabs(version.file_path):
                    version_path = os.path.join(os.getcwd(), version.file_path)
                else:
                    version_path = version.file_path
                    
                if os.path.exists(version_path):
                    os.remove(version_path)
        
        # Delete all subfolders
        for subfolder in folder.subfolders:
            delete_folder_recursive(subfolder)
        
        db.session.delete(folder)
    
    delete_folder_recursive(folder)
    db.session.commit()
    
    flash(f'Ordner "{folder.name}" wurde gelöscht.', 'success')
    if parent_id:
        return redirect(url_for('files.browse_folder', folder_id=parent_id))
    else:
        return redirect(url_for('files.index'))



