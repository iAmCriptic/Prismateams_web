from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app, session
from flask_login import login_required, current_user
from app.utils.i18n import get_current_language, translate
from app import db
from app.models.file import File, FileVersion, Folder
from app.models.user import User
from app.models.settings import SystemSettings
from app.utils.notifications import send_file_notification
from app.utils.access_control import check_module_access
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.webhook_dispatcher import emit_webhook_event
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask import url_for as flask_url_for
import os
import shutil
import logging
import secrets
import requests

files_bp = Blueprint('files', __name__)

MAX_FILE_VERSIONS = 3


@files_bp.route('/')
@login_required
@check_module_access('module_files')
def index():
    """File manager root view."""
    return browse_folder(None)


@files_bp.route('/folder/<int:folder_id>')
@login_required
@check_module_access('module_files')
def browse_folder(folder_id):
    """Browse a specific folder."""
    # Gast-Accounts: Nur Freigabelinks anzeigen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        from app.utils.access_control import get_guest_accessible_items
        accessible_files, accessible_folders = get_guest_accessible_items(current_user)
        
        # Filtere nach aktuell angezeigtem Ordner
        current_folder = None
        if folder_id:
            # Prüfe ob Gast Zugriff auf diesen Ordner hat
            folder_with_access = next((f for f in accessible_folders if f.id == folder_id), None)
            if not folder_with_access:
                flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                return redirect(url_for('files.index'))
            current_folder = folder_with_access
        
        # Zeige nur zugängliche Unterordner des aktuellen Ordners
        if folder_id:
            subfolders = [f for f in accessible_folders if f.parent_id == folder_id]
        else:
            subfolders = [f for f in accessible_folders if f.parent_id is None]
        
        # Zeige nur zugängliche Dateien im aktuellen Ordner
        # (get_guest_accessible_items gibt bereits alle Dateien inkl. Unterordnern zurück)
        if folder_id:
            files = [f for f in accessible_files if f.folder_id == folder_id]
        else:
            files = [f for f in accessible_files if f.folder_id is None]
        
        # Sortiere
        subfolders = sorted(subfolders, key=lambda x: x.name)
        files = sorted(files, key=lambda x: x.name)
    else:
        # Normale Benutzer: Alle Dateien/Ordner
        current_folder = None
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
        
        # Get subfolders
        if folder_id:
            subfolders = Folder.query.filter_by(parent_id=folder_id).order_by(Folder.name).all()
        else:
            # Wenn kein Ordner, zeige Ordner ohne Parent (parent_id IS NULL)
            subfolders = Folder.query.filter(Folder.parent_id.is_(None)).order_by(Folder.name).all()
        
        # Get files in current folder
        if folder_id:
            files = File.query.filter_by(
                folder_id=folder_id,
                is_current=True
            ).order_by(File.name).all()
        else:
            # Wenn kein Ordner, zeige Dateien ohne Ordner (folder_id IS NULL)
            # Verwende explizit filter() mit is_(None) für korrekte NULL-Prüfung
            files = File.query.filter(
                File.folder_id.is_(None),
                File.is_current == True
            ).order_by(File.name).all()
            
            # Stelle sicher, dass files eine Liste ist (nicht None)
            if files is None:
                files = []
        
        # Stelle sicher, dass files immer eine Liste ist
        if files is None:
            files = []
    
    # Build breadcrumbs starting from root to current folder
    breadcrumb_folders = []
    if current_folder:
        ancestors = []
        node = current_folder
        while node:
            ancestors.append(node)
            node = node.parent
        ancestors.reverse()
        breadcrumb_folders = [
            {
                'id': folder.id,
                'name': folder.name,
                'url': url_for('files.browse_folder', folder_id=folder.id)
            }
            for folder in ancestors
        ]

    # Feature flags
    dropbox_setting = SystemSettings.query.filter_by(key='files_dropbox_enabled').first()
    sharing_setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    files_dropbox_enabled = (dropbox_setting and str(dropbox_setting.value).lower() == 'true') or False
    files_sharing_enabled = (sharing_setting and str(sharing_setting.value).lower() == 'true') or False
    
    # Check ONLYOFFICE availability
    from app.utils.onlyoffice import is_onlyoffice_enabled
    onlyoffice_available = is_onlyoffice_enabled()

    return render_template(
        'files/index.html',
        current_folder=current_folder,
        subfolders=subfolders,
        files=files,
        files_dropbox_enabled=files_dropbox_enabled,
        files_sharing_enabled=files_sharing_enabled,
        onlyoffice_available=onlyoffice_available,
        breadcrumb_folders=breadcrumb_folders
    )


@files_bp.route('/create-folder', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_folder():
    """Create a new folder."""
    # Gast-Accounts können keine Ordner erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner erstellen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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


@files_bp.route('/file/<int:file_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_files')
def rename_file(file_id):
    """Benennt eine Datei um."""
    # Gast-Accounts können keine Dateien umbenennen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien umbenennen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    file = File.query.get_or_404(file_id)
    new_name = request.form.get('new_name', '').strip()
    
    if not new_name:
        flash('Neuer Dateiname darf nicht leer sein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Keine Pfadseparatoren erlauben
    if '/' in new_name or '\\' in new_name:
        flash('Ungültiger Dateiname.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Prüfe ob bereits eine Datei mit diesem Namen im selben Ordner existiert
    existing_file = File.query.filter_by(
        name=new_name,
        folder_id=file.folder_id,
        is_current=True
    ).first()
    
    if existing_file and existing_file.id != file.id:
        flash(f'Eine Datei mit dem Namen "{new_name}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    file.name = new_name
    db.session.commit()
    flash('Datei wurde umbenannt.', 'success')
    
    if file.folder_id:
        return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
    return redirect(url_for('files.index'))


@files_bp.route('/folder/<int:folder_id>/rename', methods=['POST'])
@login_required
@check_module_access('module_files')
def rename_folder(folder_id):
    """Benennt einen Ordner um."""
    # Gast-Accounts können keine Ordner umbenennen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner umbenennen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    folder = Folder.query.get_or_404(folder_id)
    new_name = request.form.get('new_name', '').strip()
    
    if not new_name:
        flash('Neuer Ordnername darf nicht leer sein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    if '/' in new_name or '\\' in new_name:
        flash('Ungültiger Ordnername.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    folder.name = new_name
    db.session.commit()
    flash('Ordner wurde umbenannt.', 'success')
    
    if folder.parent_id:
        return redirect(url_for('files.browse_folder', folder_id=folder.parent_id))
    return redirect(url_for('files.index'))

@files_bp.route('/create-file', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_file():
    """Create a new text or markdown file."""
    # Gast-Accounts können keine Dateien erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien erstellen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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
    
    # Emit webhook event for file upload
    emit_webhook_event('file.uploaded', {
        'file_id': new_file.id,
        'name': new_file.name,
        'original_name': new_file.original_name,
        'mime_type': new_file.mime_type,
        'file_size': new_file.file_size,
        'folder_id': new_file.folder_id,
        'uploaded_by': current_user.id,
        'uploaded_by_name': current_user.full_name,
    }, context={'user_id': current_user.id})
    
    # Sende Dashboard-Update an den Benutzer
    try:
        recent_files = File.query.filter_by(
            uploaded_by=current_user.id
        ).order_by(File.updated_at.desc()).limit(3).all()
        
        files_data = [{
            'id': file.id,
            'name': file.name,
            'original_name': file.original_name,
            'updated_at': file.updated_at.isoformat(),
            'mime_type': file.mime_type,
            'url': flask_url_for('files.view_file', file_id=file.id)
        } for file in recent_files]
        
        emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
    except Exception as e:
        logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")
    
    flash(f'Datei "{filename}" wurde erstellt.', 'success')
    
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    return redirect(url_for('files.index'))


@files_bp.route('/create-office-file', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_office_file():
    """Create a new empty Office file (DOCX, XLSX, PPTX)."""
    # Gast-Accounts können keine Office-Dateien erstellen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien erstellen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    filename = request.form.get('filename', '').strip()
    file_type = request.form.get('file_type', 'docx')  # docx, xlsx, pptx
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    
    if not filename:
        flash('Bitte geben Sie einen Dateinamen ein.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Validate file type
    if file_type not in ['docx', 'xlsx', 'pptx']:
        flash('Ungültiger Dateityp.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Add file extension if not present
    if not filename.endswith(f'.{file_type}'):
        filename += f'.{file_type}'
    
    # Check if file with same name exists in folder
    existing_file = File.query.filter_by(
        name=filename,
        folder_id=folder_id,
        is_current=True
    ).first()
    
    if existing_file:
        flash(f'Datei "{filename}" existiert bereits in diesem Ordner.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Create empty Office file
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    stored_filename = f"{timestamp}_{filename}"
    filepath = os.path.join('uploads', 'files', stored_filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    try:
        if file_type == 'docx':
            from docx import Document
            doc = Document()
            doc.save(filepath)
            mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        elif file_type == 'xlsx':
            from openpyxl import Workbook
            wb = Workbook()
            wb.save(filepath)
            mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif file_type == 'pptx':
            from pptx import Presentation
            prs = Presentation()
            prs.save(filepath)
            mime_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    except ImportError as e:
        flash(f'Fehler: Erforderliche Bibliothek nicht installiert. Bitte installieren Sie python-docx, openpyxl und python-pptx.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    except Exception as e:
        logging.error(f"Fehler beim Erstellen der Office-Datei: {e}")
        flash(f'Fehler beim Erstellen der Datei: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    new_file = File(
        name=filename,
        original_name=filename,
        folder_id=folder_id,
        uploaded_by=current_user.id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type=mime_type,
        version_number=1,
        is_current=True
    )
    db.session.add(new_file)
    db.session.commit()
    
    # Sende Dashboard-Update an den Benutzer
    try:
        recent_files = File.query.filter_by(
            uploaded_by=current_user.id
        ).order_by(File.updated_at.desc()).limit(3).all()
        
        files_data = [{
            'id': file.id,
            'name': file.name,
            'original_name': file.original_name,
            'updated_at': file.updated_at.isoformat(),
            'mime_type': file.mime_type,
            'url': flask_url_for('files.view_file', file_id=file.id)
        } for file in recent_files]
        
        emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
    except Exception as e:
        logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")
    
    flash(f'Datei "{filename}" wurde erstellt.', 'success')
    
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    return redirect(url_for('files.index'))


@files_bp.route('/upload', methods=['POST'])
@login_required
@check_module_access('module_files')
def upload_file():
    """Upload a file or folder."""
    # Gast-Accounts können nur in freigegebenen Ordnern hochladen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        folder_id = request.form.get('folder_id')
        folder_id = int(folder_id) if folder_id else None
        
        # Prüfe ob Gast Zugriff auf diesen Ordner hat
        if folder_id:
            from app.utils.access_control import get_guest_accessible_items
            accessible_files, accessible_folders = get_guest_accessible_items(current_user)
            folder_with_access = next((f for f in accessible_folders if f.id == folder_id), None)
            if not folder_with_access:
                flash('Sie haben keinen Zugriff auf diesen Ordner.', 'danger')
                return redirect(request.referrer or url_for('files.index'))
        else:
            flash('Gast-Accounts können nur in freigegebenen Ordnern Dateien hochladen.', 'danger')
            return redirect(request.referrer or url_for('files.index'))
    
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id else None
    
    max_size = 100 * 1024 * 1024  # 100MB in bytes
    
    # Check for folder upload
    if 'folder_upload' in request.files:
        folder_files = request.files.getlist('folder_upload')
        if folder_files and folder_files[0].filename:
            uploaded_count = 0
            skipped_count = 0
            skipped_files = []
            
            for file in folder_files:
                if not file.filename:
                    continue
                
                # Check file size
                file.seek(0, 2)  # Seek to end
                file_size = file.tell()
                file.seek(0)  # Reset to beginning
                
                if file_size > max_size:
                    skipped_count += 1
                    skipped_files.append(file.filename)
                    continue
                
                # Process file path to maintain folder structure
                file_path_parts = file.filename.replace('\\', '/').split('/')
                file_name = secure_filename(file_path_parts[-1])
                
                # Determine target folder - create subfolders if needed
                target_folder_id = folder_id
                if len(file_path_parts) > 1:
                    # Create folder structure
                    current_parent_id = folder_id
                    for folder_name in file_path_parts[:-1]:
                        folder_name_clean = secure_filename(folder_name)
                        if not folder_name_clean:
                            continue
                        
                        # Check if folder exists
                        existing_folder = Folder.query.filter_by(
                            name=folder_name_clean,
                            parent_id=current_parent_id
                        ).first()
                        
                        if not existing_folder:
                            # Create new folder
                            new_folder = Folder(
                                name=folder_name_clean,
                                parent_id=current_parent_id,
                                created_by=current_user.id
                            )
                            db.session.add(new_folder)
                            db.session.flush()  # Get the ID
                            current_parent_id = new_folder.id
                        else:
                            current_parent_id = existing_folder.id
                    
                    target_folder_id = current_parent_id
                
                # Process file upload
                try:
                    _process_file_upload(file, file_name, target_folder_id, current_user.id)
                    uploaded_count += 1
                except Exception as e:
                    logging.error(f"Fehler beim Hochladen von {file_name}: {e}")
                    skipped_count += 1
                    skipped_files.append(file_name)
            
            db.session.commit()
            
            # Send notifications for uploaded files
            if uploaded_count > 0:
                try:
                    # Get recently uploaded files to send notifications
                    recent_files = File.query.filter_by(
                        uploaded_by=current_user.id
                    ).order_by(File.created_at.desc()).limit(uploaded_count).all()
                    for f in recent_files:
                        try:
                            send_file_notification(f.id, 'new')
                        except Exception as e:
                            logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
                except Exception as e:
                    logging.error(f"Fehler beim Senden von Benachrichtigungen: {e}")
            
            # Flash messages
            if uploaded_count > 0:
                flash(f'{uploaded_count} Datei(en) wurden hochgeladen.', 'success')
            if skipped_count > 0:
                flash(f'{skipped_count} Datei(en) wurden übersprungen (zu groß oder Fehler).', 'warning')
                if skipped_files:
                    flash(f'Übersprungene Dateien: {", ".join(skipped_files[:5])}{"..." if len(skipped_files) > 5 else ""}', 'info')
            
            if folder_id:
                return redirect(url_for('files.browse_folder', folder_id=folder_id))
            return redirect(url_for('files.index'))
    
    # Single file upload
    if 'file' not in request.files:
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
    # Check file size (100MB limit)
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    
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
        
        # Sende Benachrichtigung für geänderte Datei
        try:
            send_file_notification(existing_file.id, 'modified')
        except Exception as e:
            logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
        
        # Sende Dashboard-Update an den Benutzer
        try:
            recent_files = File.query.filter_by(
                uploaded_by=current_user.id
            ).order_by(File.updated_at.desc()).limit(3).all()
            
            files_data = [{
                'id': file.id,
                'name': file.name,
                'original_name': file.original_name,
                'updated_at': file.updated_at.isoformat(),
                'mime_type': file.mime_type,
                'url': flask_url_for('files.view_file', file_id=file.id)
            } for file in recent_files]
            
            emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
        except Exception as e:
            logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")
        
        flash(f'Datei "{original_name}" wurde aktualisiert (Version {version_number}).', 'success')
    else:
        # Create new file
        _process_file_upload(file, original_name, folder_id, current_user.id)
        db.session.commit()
        
        # Sende Benachrichtigung für neue Datei
        new_file = File.query.filter_by(
            name=original_name,
            folder_id=folder_id,
            uploaded_by=current_user.id
        ).order_by(File.created_at.desc()).first()
        
        if new_file:
            try:
                send_file_notification(new_file.id, 'new')
            except Exception as e:
                logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
            
            # Sende Dashboard-Update an den Benutzer
            try:
                recent_files = File.query.filter_by(
                    uploaded_by=current_user.id
                ).order_by(File.updated_at.desc()).limit(3).all()
                
                files_data = [{
                    'id': file.id,
                    'name': file.name,
                    'original_name': file.original_name,
                    'updated_at': file.updated_at.isoformat(),
                    'mime_type': file.mime_type,
                    'url': flask_url_for('files.view_file', file_id=file.id)
                } for file in recent_files]
                
                emit_dashboard_update(current_user.id, 'files_update', {'files': files_data})
            except Exception as e:
                logging.error(f"Fehler beim Senden der Dashboard-Updates für Dateien: {e}")
        
        flash(f'Datei "{original_name}" wurde hochgeladen.', 'success')
    
    if folder_id:
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    return redirect(url_for('files.index'))


def _process_file_upload(file, original_name, folder_id, user_id):
    """Helper function to process a single file upload."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{original_name}"
    filepath = os.path.join('uploads', 'files', filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    new_file = File(
        name=original_name,
        original_name=original_name,
        folder_id=folder_id,
        uploaded_by=user_id,
        file_path=absolute_filepath,
        file_size=os.path.getsize(absolute_filepath),
        mime_type=file.content_type,
        version_number=1,
        is_current=True
    )
    db.session.add(new_file)


@files_bp.route('/serve-pdf/<int:file_id>')
@login_required
@check_module_access('module_files')
def serve_pdf(file_id):
    """Serve a PDF file for inline viewing (without forcing download)."""
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
    
    # Only serve PDFs
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext != '.pdf':
        flash('Diese Route ist nur für PDF-Dateien.', 'danger')
        return redirect(url_for('files.index'))
    
    return send_file(file_path, mimetype='application/pdf')


@files_bp.route('/download/<int:file_id>')
@login_required
@check_module_access('module_files')
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
    
    # Determine MIME type based on file extension
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext == '.md':
        mimetype = 'text/markdown'
    elif file_ext == '.txt':
        mimetype = 'text/plain'
    elif file_ext == '.pdf':
        mimetype = 'application/pdf'
    elif file_ext in ['.jpg', '.jpeg']:
        mimetype = 'image/jpeg'
    elif file_ext == '.png':
        mimetype = 'image/png'
    elif file_ext == '.gif':
        mimetype = 'image/gif'
    elif file_ext == '.webp':
        mimetype = 'image/webp'
    else:
        mimetype = 'application/octet-stream'
    
    return send_file(
        file_path, 
        as_attachment=True, 
        download_name=file.original_name,
        mimetype=mimetype
    )


@files_bp.route('/download-version/<int:version_id>')
@login_required
@check_module_access('module_files')
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
    
    # Determine MIME type based on file extension
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext == '.md':
        mimetype = 'text/markdown'
    elif file_ext == '.txt':
        mimetype = 'text/plain'
    elif file_ext == '.pdf':
        mimetype = 'application/pdf'
    elif file_ext in ['.jpg', '.jpeg']:
        mimetype = 'image/jpeg'
    elif file_ext == '.png':
        mimetype = 'image/png'
    elif file_ext == '.gif':
        mimetype = 'image/gif'
    elif file_ext == '.webp':
        mimetype = 'image/webp'
    else:
        mimetype = 'application/octet-stream'
    
    # Create versioned filename
    name_without_ext = os.path.splitext(file.original_name)[0]
    file_ext = os.path.splitext(file.original_name)[1]
    versioned_filename = f"{name_without_ext}_v{version.version_number}{file_ext}"
    
    return send_file(
        file_path, 
        as_attachment=True, 
        download_name=versioned_filename,
        mimetype=mimetype
    )


@files_bp.route('/edit/<int:file_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_files')
def edit_file(file_id):
    """Edit a text file online."""
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
            return redirect(url_for('files.index'))
    
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


@files_bp.route('/preview/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def preview_file(file_id):
    """Vorschau-Endpoint für Editor (nutzt gleiche Logik wie /view/)."""
    file = File.query.get_or_404(file_id)
    
    # Check if file is viewable
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if file_ext not in viewable_extensions:
        return jsonify({'error': translate('files.errors.file_type_not_supported')}), 400
    
    content = request.form.get('content', '')
    
    # Process markdown if it's a markdown file
    if file.name.endswith('.md'):
        try:
            from app.utils.markdown import process_markdown
            processed_content = process_markdown(content, wiki_mode=False)
        except Exception as e:
            current_app.logger.error(f"Markdown processing error: {e}")
            processed_content = content
    else:
        processed_content = content
    
    return jsonify({'html': processed_content})


@files_bp.route('/view/<int:file_id>')
@login_required
@check_module_access('module_files')
def view_file(file_id):
    """View a file in fullscreen mode (for markdown/text/PDF files)."""
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
            return redirect(url_for('files.index'))
    
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    # Handle PDF files - display in browser
    if file_ext == '.pdf':
        # Ensure we have an absolute path
        if not os.path.isabs(file.file_path):
            file_path = os.path.join(os.getcwd(), file.file_path)
        else:
            file_path = file.file_path
        
        # Check if file exists
        if not os.path.exists(file_path):
            flash(f'Datei "{file.original_name}" wurde nicht gefunden.', 'danger')
            if file.folder_id:
                return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
            else:
                return redirect(url_for('files.index'))
        
        # Return PDF for inline viewing (similar to manuals)
        return render_template('files/view.html', file=file, is_pdf=True)
    
    # Handle text/markdown files (existing logic)
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    
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
            from app.utils.markdown import process_markdown
            processed_content = process_markdown(content, wiki_mode=False)
            current_app.logger.info(f"Markdown processed. Table detected: {'<table>' in processed_content}")
        except Exception as e:
            current_app.logger.error(f"Markdown processing error: {e}")
            processed_content = content
    else:
        processed_content = content
    
    return render_template('files/view.html', file=file, content=content, processed_content=processed_content, is_pdf=False)


@files_bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
@check_module_access('module_files')
def delete_file(file_id):
    """Delete a file."""
    # Gast-Accounts können keine Dateien löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Dateien löschen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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
@check_module_access('module_files')
def delete_folder(folder_id):
    """Delete a folder and all its contents."""
    # Gast-Accounts können keine Ordner löschen
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        flash('Gast-Accounts können keine Ordner löschen.', 'danger')
        return redirect(request.referrer or url_for('files.index'))
    
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


@files_bp.route('/api/file-details/<int:file_id>')
@login_required
@check_module_access('module_files')
def get_file_details(file_id):
    """Get file details for the side menu."""
    file = File.query.get_or_404(file_id)
    
    # Get file versions
    versions = FileVersion.query.filter_by(file_id=file.id).order_by(
        FileVersion.version_number.desc()
    ).all()
    
    # Format file size
    if file.file_size > 1024*1024:
        file_size_str = f"{file.file_size / (1024*1024):.1f} MB"
    else:
        file_size_str = f"{file.file_size / 1024:.1f} KB"
    
    # Get file type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    if file_ext == '.md':
        file_type = 'Markdown'
    elif file_ext == '.txt':
        file_type = 'Text'
    elif file_ext == '.pdf':
        file_type = 'PDF'
    elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        file_type = 'Bild'
    else:
        file_type = 'Datei'
    
    # Check if file is editable
    editable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    is_editable = file_ext in editable_extensions
    
    # Check if file is viewable
    viewable_extensions = {'.txt', '.md', '.markdown', '.json', '.xml', '.csv', '.log'}
    is_viewable = file_ext in viewable_extensions
    
    return jsonify({
        'success': True,
        'file': {
            'id': file.id,
            'name': file.original_name,
            'size': file_size_str,
            'type': file_type,
            'uploader': file.uploader.full_name,
            'created_at': file.created_at.strftime('%d.%m.%Y %H:%M'),
            'version': file.version_number,
            'is_editable': is_editable,
            'is_viewable': is_viewable
        },
        'versions': [
            {
                'id': version.id,
                'version_number': version.version_number,
                'is_current': version.version_number == file.version_number,
                'download_url': url_for('files.download_version', version_id=version.id)
            }
            for version in versions
        ],
        'actions': {
            'download_url': url_for('files.download_file', file_id=file.id),
            'view_url': url_for('files.view_file', file_id=file.id) if is_viewable else None,
            'edit_url': url_for('files.edit_file', file_id=file.id) if is_editable else None
        }
    })


# Briefkasten (Dropbox) Routes
@files_bp.route('/folder/<int:folder_id>/make-dropbox', methods=['POST'])
@login_required
@check_module_access('module_files')
def make_dropbox(folder_id):
    """Aktiviere Briefkasten für einen Ordner."""
    folder = Folder.query.get_or_404(folder_id)
    
    # Generate unique token
    token = secrets.token_urlsafe(32)
    while Folder.query.filter_by(dropbox_token=token).first():
        token = secrets.token_urlsafe(32)
    
    folder.is_dropbox = True
    folder.dropbox_token = token
    db.session.commit()
    
    flash(f'Briefkasten für Ordner "{folder.name}" wurde aktiviert.', 'success')
    return redirect(url_for('files.browse_folder', folder_id=folder_id))


@files_bp.route('/folder/<int:folder_id>/dropbox-settings', methods=['GET', 'POST'])
@login_required
@check_module_access('module_files')
def dropbox_settings(folder_id):
    """Briefkasten-Einstellungen anzeigen und bearbeiten."""
    folder = Folder.query.get_or_404(folder_id)
    
    if not folder.is_dropbox:
        flash('Dieser Ordner ist kein Briefkasten.', 'danger')
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_password':
            password = request.form.get('password', '').strip()
            if password:
                folder.dropbox_password_hash = generate_password_hash(password)
                db.session.commit()
                flash('Passwort wurde gesetzt.', 'success')
            else:
                flash('Bitte geben Sie ein Passwort ein.', 'danger')
        
        elif action == 'remove_password':
            folder.dropbox_password_hash = None
            db.session.commit()
            flash('Passwort wurde entfernt.', 'success')
        
        elif action == 'regenerate_token':
            # Generate new token
            token = secrets.token_urlsafe(32)
            while Folder.query.filter_by(dropbox_token=token).first():
                token = secrets.token_urlsafe(32)
            folder.dropbox_token = token
            db.session.commit()
            flash('Link wurde neu generiert.', 'success')
        
        # Redirect back to folder view
        return redirect(url_for('files.browse_folder', folder_id=folder_id))
    
    # GET: Return JSON for AJAX call
    dropbox_url = url_for('files.dropbox_upload', token=folder.dropbox_token, _external=True)
    return jsonify({
        'success': True,
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'dropbox_url': dropbox_url,
            'has_password': folder.dropbox_password_hash is not None
        }
    })


@files_bp.route('/folder/<int:folder_id>/disable-dropbox', methods=['POST'])
@login_required
@check_module_access('module_files')
def disable_dropbox(folder_id):
    """Deaktiviere Briefkasten für einen Ordner."""
    folder = Folder.query.get_or_404(folder_id)
    
    folder.is_dropbox = False
    folder.dropbox_token = None
    folder.dropbox_password_hash = None
    db.session.commit()
    
    flash(f'Briefkasten für Ordner "{folder.name}" wurde deaktiviert.', 'success')
    return redirect(url_for('files.browse_folder', folder_id=folder_id))


@files_bp.route('/dropbox/<token>', methods=['GET', 'POST'])
def dropbox_upload(token):
    """Öffentliche Upload-Seite für Briefkasten (ohne Login)."""
    folder = Folder.query.filter_by(dropbox_token=token, is_dropbox=True).first_or_404()
    
    # Check password if set
    if folder.dropbox_password_hash:
        # Check if password is provided in session or form
        if request.method == 'POST':
            password = request.form.get('password', '')
            if check_password_hash(folder.dropbox_password_hash, password):
                session[f'dropbox_auth_{token}'] = True
                return redirect(url_for('files.dropbox_upload', token=token))
            else:
                flash('Ungültiges Passwort.', 'danger')
        elif not session.get(f'dropbox_auth_{token}'):
            return render_template('files/dropbox_auth.html', token=token, folder_name=folder.name)
    
    # Show upload form
    return render_template('files/dropbox_upload.html', token=token, folder=folder)


@files_bp.route('/dropbox/<token>/upload', methods=['POST'])
def dropbox_upload_file(token):
    """Öffentlicher Upload-Endpoint für Briefkasten (ohne Login)."""
    folder = Folder.query.filter_by(dropbox_token=token, is_dropbox=True).first_or_404()
    
    # Check password if set
    if folder.dropbox_password_hash:
        if not session.get(f'dropbox_auth_{token}'):
            password = request.form.get('password', '')
            if not check_password_hash(folder.dropbox_password_hash, password):
                flash('Ungültiges Passwort.', 'danger')
                return redirect(url_for('files.dropbox_upload', token=token))
            session[f'dropbox_auth_{token}'] = True
    
    max_size = 100 * 1024 * 1024  # 100MB in bytes
    uploaded_count = 0
    skipped_count = 0
    uploader_name = request.form.get('uploader_name', '').strip() or 'Anonym'
    
    # Handle single file or multiple files
    if 'file' in request.files:
        files = request.files.getlist('file')
        for file in files:
            if not file.filename:
                continue
            
            # Check file size
            file.seek(0, 2)  # Seek to end
            file_size = file.tell()
            file.seek(0)  # Reset to beginning
            
            if file_size > max_size:
                skipped_count += 1
                continue
            
            # Process filename with date suffix if duplicate
            original_name = secure_filename(file.filename)
            file_name = original_name
            
            # Check for duplicate
            existing_file = File.query.filter_by(
                name=file_name,
                folder_id=folder.id,
                is_current=True
            ).first()
            
            if existing_file:
                # Add date suffix
                date_str = datetime.utcnow().strftime('%Y-%m-%d')
                name_without_ext, ext = os.path.splitext(original_name)
                file_name = f"{name_without_ext}_V{date_str}{ext}"
                
                # Check if this name also exists, append number if needed
                counter = 1
                while File.query.filter_by(name=file_name, folder_id=folder.id, is_current=True).first():
                    file_name = f"{name_without_ext}_V{date_str}_{counter}{ext}"
                    counter += 1
            
            try:
                # Create a special user entry for anonymous uploads or use uploader name
                # For now, we'll use a placeholder user or create a system user
                # Check if there's a system/anonymous user
                anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
                if not anonymous_user:
                    # Create anonymous user if needed
                    anonymous_user = User(
                        email='anonymous@system.local',
                        first_name=uploader_name,
                        last_name='',
                        password_hash='',  # No password needed
                        is_active=True,
                        is_admin=False,
                        is_email_confirmed=True
                    )
                    db.session.add(anonymous_user)
                    db.session.flush()
                
                _process_file_upload(file, file_name, folder.id, anonymous_user.id)
                uploaded_count += 1
            except Exception as e:
                logging.error(f"Fehler beim Hochladen von {file_name}: {e}")
                skipped_count += 1
        
        db.session.commit()
        
        if uploaded_count > 0:
            flash(f'{uploaded_count} Datei(en) wurden erfolgreich hochgeladen.', 'success')
        if skipped_count > 0:
            flash(f'{skipped_count} Datei(en) wurden übersprungen (zu groß oder Fehler).', 'warning')
    
    return redirect(url_for('files.dropbox_upload', token=token))


# =========================
# Sharing (Freigaben)
# =========================

def _is_sharing_enabled() -> bool:
    setting = SystemSettings.query.filter_by(key='files_sharing_enabled').first()
    return (setting and str(setting.value).lower() == 'true') or False


def _generate_unique_share_token():
    token = secrets.token_urlsafe(32)
    while File.query.filter_by(share_token=token).first() or Folder.query.filter_by(share_token=token).first():
        token = secrets.token_urlsafe(32)
    return token


def _check_share_access(token):
    """Prüft ob ein Share-Token gültig ist und gibt (item, guest_name) zurück.
    Der guest_name wird aus der Session gelesen (wird beim ersten Zugriff eingegeben).
    """
    shared_file = File.query.filter_by(share_token=token, share_enabled=True).first()
    shared_folder = None if shared_file else Folder.query.filter_by(share_token=token, share_enabled=True).first()
    
    if not shared_file and not shared_folder:
        return None, None
    
    item = shared_file or shared_folder
    
    # Check expiry
    if item.share_expires_at and datetime.utcnow() > item.share_expires_at:
        return None, None
    
    # Check password if set
    if item.share_password_hash:
        session_key = f'share_auth_{token}'
        if not session.get(session_key):
            return None, None
    
    # Get guest name from session
    guest_name_key = f'share_guest_name_{token}'
    guest_name = session.get(guest_name_key)
    
    # Wenn kein Name in Session, ist Zugriff verweigert (muss vorher eingegeben werden)
    if not guest_name:
        return None, None
    
    return item, guest_name


@files_bp.route('/file/<int:file_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_file_share(file_id):
    if not _is_sharing_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(request.referrer or url_for('files.index'))
    file = File.query.get_or_404(file_id)
    password = request.form.get('password', '').strip()
    expires_at = request.form.get('expires_at', '').strip()

    file.share_enabled = True
    file.share_token = _generate_unique_share_token()
    file.share_password_hash = generate_password_hash(password) if password else None
    file.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
    file.share_name = None  # Wird beim ersten Zugriff vom Gast eingegeben
    db.session.commit()

    flash('Freigabe erstellt.', 'success')
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/folder/<int:folder_id>/share', methods=['POST'])
@login_required
@check_module_access('module_files')
def create_folder_share(folder_id):
    if not _is_sharing_enabled():
        flash('Freigaben sind deaktiviert.', 'warning')
        return redirect(request.referrer or url_for('files.index'))
    folder = Folder.query.get_or_404(folder_id)
    password = request.form.get('password', '').strip()
    expires_at = request.form.get('expires_at', '').strip()

    folder.share_enabled = True
    folder.share_token = _generate_unique_share_token()
    folder.share_password_hash = generate_password_hash(password) if password else None
    folder.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
    folder.share_name = None  # Wird beim ersten Zugriff vom Gast eingegeben
    db.session.commit()

    flash('Freigabe erstellt.', 'success')
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/file/<int:file_id>/share-settings')
@login_required
@check_module_access('module_files')
def file_share_settings(file_id):
    file = File.query.get_or_404(file_id)
    if not file.share_enabled or not file.share_token:
        return jsonify({'success': False}), 404
    share_url = url_for('files.public_share', token=file.share_token, _external=True)
    return jsonify({'success': True, 'item': {'type': 'file', 'id': file.id, 'name': file.name, 'share_url': share_url, 'has_password': file.share_password_hash is not None, 'expires_at': file.share_expires_at.isoformat() if file.share_expires_at else None, 'share_name': file.share_name}})


@files_bp.route('/folder/<int:folder_id>/share-settings')
@login_required
@check_module_access('module_files')
def folder_share_settings(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if not folder.share_enabled or not folder.share_token:
        return jsonify({'success': False}), 404
    share_url = url_for('files.public_share', token=folder.share_token, _external=True)
    return jsonify({'success': True, 'item': {'type': 'folder', 'id': folder.id, 'name': folder.name, 'share_url': share_url, 'has_password': folder.share_password_hash is not None, 'expires_at': folder.share_expires_at.isoformat() if folder.share_expires_at else None, 'share_name': folder.share_name}})


@files_bp.route('/file/<int:file_id>/share-settings', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_file_share(file_id):
    file = File.query.get_or_404(file_id)
    action = request.form.get('action')
    if action == 'disable':
        file.share_enabled = False
        file.share_token = None
        file.share_password_hash = None
        file.share_expires_at = None
        file.share_name = None
    else:
        password = request.form.get('password', '').strip()
        expires_at = request.form.get('expires_at', '').strip()
        file.share_password_hash = generate_password_hash(password) if password else file.share_password_hash
        file.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/folder/<int:folder_id>/share-settings', methods=['POST'])
@login_required
@check_module_access('module_files')
def update_folder_share(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    action = request.form.get('action')
    if action == 'disable':
        folder.share_enabled = False
        folder.share_token = None
        folder.share_password_hash = None
        folder.share_expires_at = None
        folder.share_name = None
    else:
        password = request.form.get('password', '').strip()
        expires_at = request.form.get('expires_at', '').strip()
        folder.share_password_hash = generate_password_hash(password) if password else folder.share_password_hash
        folder.share_expires_at = datetime.fromisoformat(expires_at) if expires_at else None
    db.session.commit()
    flash('Freigabe aktualisiert.', 'success')
    return redirect(request.referrer or url_for('files.index'))


@files_bp.route('/share/<token>', methods=['GET', 'POST'])
def public_share(token):
    # Find file or folder by token
    shared_file = File.query.filter_by(share_token=token, share_enabled=True).first()
    shared_folder = None if shared_file else Folder.query.filter_by(share_token=token, share_enabled=True).first()
    if not shared_file and not shared_folder:
        flash('Freigabe existiert nicht mehr.', 'danger')
        return redirect(url_for('files.index'))

    item = shared_file or shared_folder
    # Check expiry
    if item.share_expires_at and datetime.utcnow() > item.share_expires_at:
        flash('Freigabe ist abgelaufen.', 'danger')
        return redirect(url_for('files.index'))

    # Password gate
    if item.share_password_hash:
        session_key = f'share_auth_{token}'
        if request.method == 'POST' and 'password' in request.form:
            if check_password_hash(item.share_password_hash, request.form.get('password','')):
                session[session_key] = True
                return redirect(url_for('files.public_share', token=token))
            else:
                flash('Ungültiges Passwort.', 'danger')
        elif not session.get(session_key):
            return render_template('files/share_auth.html', token=token, item=item)

    # Name-Eingabe verpflichtend (Gast-Name)
    # Name wird in Session gespeichert, damit er innerhalb derselben Browser-Session wiederverwendet wird
    guest_name_key = f'share_guest_name_{token}'
    
    # Prüfe ob Name bereits in Session vorhanden
    guest_name = session.get(guest_name_key)
    
    # Wenn POST-Request mit neuem Namen
    if request.method == 'POST' and 'guest_name' in request.form:
        guest_name = request.form.get('guest_name', '').strip()
        if guest_name:
            # Speichere in Session für diese Browser-Session
            session[guest_name_key] = guest_name
            # Weiterleitung zur Freigabe-Seite
            return redirect(url_for('files.public_share', token=token))
        else:
            flash('Bitte geben Sie einen Namen ein.', 'danger')
    
    # Wenn kein Name in Session, zeige Eingabe-Formular
    if not guest_name:
        return render_template('files/share_name.html', token=token, item=item)

    # Check ONLYOFFICE availability
    from app.utils.onlyoffice import is_onlyoffice_enabled
    onlyoffice_available = is_onlyoffice_enabled()
    
    # Render file or folder view
    if shared_file:
        # Provide download and edit option
        return render_template('files/share.html', item_type='file', file=shared_file, token=token, guest_name=guest_name, onlyoffice_available=onlyoffice_available)
    else:
        # Get files in the shared folder
        folder_files = File.query.filter_by(
            folder_id=shared_folder.id,
            is_current=True
        ).order_by(File.name).all()
        
        # Show upload list and files in folder
        return render_template('files/share.html', item_type='folder', folder=shared_folder, folder_files=folder_files, token=token, guest_name=guest_name, onlyoffice_available=onlyoffice_available)


@files_bp.route('/share/<token>/download', methods=['GET'])
def public_share_download(token):
    """Download für direkt freigegebene Datei."""
    shared_file = File.query.filter_by(share_token=token, share_enabled=True).first_or_404()
    
    # Prüfe Zugriff (Passwort, Ablaufdatum, Name)
    item, guest_name = _check_share_access(token)
    if not item or not guest_name:
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))
    
    # Ensure path
    file_path = shared_file.file_path if os.path.isabs(shared_file.file_path) else os.path.join(os.getcwd(), shared_file.file_path)
    return send_file(file_path, as_attachment=True, download_name=shared_file.original_name)


@files_bp.route('/share/<token>/file/<int:file_id>/download', methods=['GET'])
def public_share_folder_file_download(token, file_id):
    """Download für Datei in freigegebenem Ordner."""
    # Prüfe ob Ordner freigegeben ist
    shared_folder = Folder.query.filter_by(share_token=token, share_enabled=True).first_or_404()
    
    # Prüfe ob Datei im Ordner ist
    file = File.query.filter_by(id=file_id, folder_id=shared_folder.id, is_current=True).first_or_404()
    
    # Prüfe Zugriff (Passwort, Ablaufdatum, Name)
    item, guest_name = _check_share_access(token)
    if not item or not guest_name:
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('files.public_share', token=token))
    
    # Ensure path
    file_path = file.file_path if os.path.isabs(file.file_path) else os.path.join(os.getcwd(), file.file_path)
    return send_file(file_path, as_attachment=True, download_name=file.original_name)


@files_bp.route('/share/<token>/upload', methods=['POST'])
def public_share_upload(token):
    shared_folder = Folder.query.filter_by(share_token=token, share_enabled=True).first_or_404()
    # Password gate
    if shared_folder.share_password_hash:
        if not session.get(f'share_auth_{token}'):
            password = request.form.get('password', '')
            if not check_password_hash(shared_folder.share_password_hash, password):
                flash('Ungültiges Passwort.', 'danger')
                return redirect(url_for('files.public_share', token=token))
            session[f'share_auth_{token}'] = True

    uploader_name = request.form.get('uploader_name', '').strip() or 'Anonym'
    if 'file' in request.files:
        files = request.files.getlist('file')
        for f in files:
            if not f.filename:
                continue
            # Derive unique name
            original_name = secure_filename(f.filename)
            name = original_name
            existing = File.query.filter_by(name=name, folder_id=shared_folder.id, is_current=True).first()
            if existing:
                date_str = datetime.utcnow().strftime('%Y-%m-%d')
                base, ext = os.path.splitext(original_name)
                name = f"{base}_V{date_str}{ext}"
            anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
            if not anonymous_user:
                anonymous_user = User(
                    email='anonymous@system.local',
                    first_name=uploader_name,
                    last_name='',
                    password_hash='',
                    is_active=True,
                    is_admin=False,
                    is_email_confirmed=True
                )
                db.session.add(anonymous_user)
                db.session.flush()
            _process_file_upload(f, name, shared_folder.id, anonymous_user.id)
        db.session.commit()
        flash('Upload abgeschlossen.', 'success')
    return redirect(url_for('files.public_share', token=token))

# ONLYOFFICE Routes
@files_bp.route('/api/onlyoffice-debug', methods=['GET'])
@login_required
@check_module_access('module_files')
def onlyoffice_debug():
    """Debug endpoint to show OnlyOffice configuration and URLs."""
    from flask import url_for
    from urllib.parse import quote
    
    # Get a test file if available
    test_file = File.query.filter(File.original_name.like('%.docx')).first()
    if not test_file:
        test_file = File.query.first()
    
    debug_info = {
        'config': {
            'ONLYOFFICE_ENABLED': current_app.config.get('ONLYOFFICE_ENABLED', False),
            'ONLYOFFICE_DOCUMENT_SERVER_URL': current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice'),
            'ONLYOFFICE_PUBLIC_URL': current_app.config.get('ONLYOFFICE_PUBLIC_URL', ''),
            'ONLYOFFICE_SECRET_KEY_SET': bool(current_app.config.get('ONLYOFFICE_SECRET_KEY', '').strip()),
        },
        'request_info': {
            'scheme': request.scheme,
            'host': request.host,
            'url': request.url,
            'base_url': request.url_root,
        }
    }
    
    if test_file:
        # Generate URLs like in edit_onlyoffice
        from app.utils.onlyoffice import generate_onlyoffice_access_token
        access_token = generate_onlyoffice_access_token(test_file.id, current_user.id)
        public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
        
        if public_url:
            public_url = public_url.rstrip('/')
            from urllib.parse import quote
            base_url = url_for('files.onlyoffice_document', file_id=test_file.id)
            encoded_token = quote(access_token, safe='')
            document_url = f"{public_url}{base_url}?token={encoded_token}"
        else:
            from urllib.parse import quote
            base_url = url_for('files.onlyoffice_document', file_id=test_file.id, _external=True)
            encoded_token = quote(access_token, safe='')
            document_url = f"{base_url}?token={encoded_token}"
        
        debug_info['test_file'] = {
            'id': test_file.id,
            'name': test_file.original_name,
            'file_path': test_file.file_path,
            'document_url': document_url,
            'access_token_length': len(access_token),
        }
        
        # Check file permissions
        import stat
        file_path = test_file.file_path if os.path.isabs(test_file.file_path) else os.path.join(os.getcwd(), test_file.file_path)
        if os.path.exists(file_path):
            try:
                file_stat = os.stat(file_path)
                debug_info['test_file']['permissions'] = {
                    'exists': True,
                    'readable': os.access(file_path, os.R_OK),
                    'permissions_octal': oct(stat.S_IMODE(file_stat.st_mode)),
                    'owner_uid': file_stat.st_uid,
                    'group_gid': file_stat.st_gid,
                }
            except Exception as e:
                debug_info['test_file']['permissions'] = {'error': str(e)}
        else:
            debug_info['test_file']['permissions'] = {'exists': False}
    
    return jsonify(debug_info)


@files_bp.route('/api/onlyoffice-diagnose', methods=['GET'])
@login_required
@check_module_access('module_files')
def onlyoffice_diagnose():
    """Diagnose OnlyOffice Document Server connectivity."""
    import requests
    from urllib.parse import urljoin
    
    results = {
        'onlyoffice_enabled': current_app.config.get('ONLYOFFICE_ENABLED', False),
        'onlyoffice_url': current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice'),
        'tests': {}
    }
    
    if not results['onlyoffice_enabled']:
        return jsonify(results)
    
    onlyoffice_url = results['onlyoffice_url']
    
    # Test 1: Direct connection to OnlyOffice on port 8080
    try:
        response = requests.get('http://127.0.0.1:8080/welcome/', timeout=5)
        results['tests']['direct_8080'] = {
            'status': 'success' if response.status_code == 200 else 'failed',
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'message': 'OnlyOffice is reachable on port 8080' if response.status_code == 200 else f'OnlyOffice returned status {response.status_code}'
        }
    except requests.exceptions.ConnectionError:
        results['tests']['direct_8080'] = {
            'status': 'failed',
            'message': 'Cannot connect to OnlyOffice on port 8080. Is the Docker container running?'
        }
    except Exception as e:
        results['tests']['direct_8080'] = {
            'status': 'error',
            'message': f'Error: {str(e)}'
        }
    
    # Test 2: OnlyOffice API via Nginx proxy
    if onlyoffice_url.startswith('http'):
        api_url = f"{onlyoffice_url.rstrip('/')}/web-apps/apps/api/documents/api.js"
    else:
        scheme = request.scheme
        host = request.host
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    try:
        response = requests.get(api_url, timeout=5)
        content_type = response.headers.get('Content-Type', '')
        is_javascript = 'javascript' in content_type.lower() or response.text.strip().startswith(('var ', 'function ', '!function', '(function'))
        is_html = '<html' in response.text.lower() or '<!doctype' in response.text.lower()
        
        results['tests']['api_via_nginx'] = {
            'status': 'success' if is_javascript and not is_html else 'failed',
            'status_code': response.status_code,
            'content_type': content_type,
            'url': api_url,
            'is_javascript': is_javascript,
            'is_html': is_html,
            'content_preview': response.text[:200] if len(response.text) > 0 else '(empty)',
            'message': 'API file is correctly served as JavaScript' if is_javascript and not is_html else 'API file is NOT served as JavaScript (likely HTML error page)'
        }
    except Exception as e:
        results['tests']['api_via_nginx'] = {
            'status': 'error',
            'url': api_url,
            'message': f'Error accessing API via Nginx: {str(e)}'
        }
    
    # Test 3: OnlyOffice welcome page via Nginx
    if onlyoffice_url.startswith('http'):
        welcome_url = f"{onlyoffice_url.rstrip('/')}/welcome/"
    else:
        welcome_url = f"{scheme}://{host}{onlyoffice_url}/welcome/"
    
    try:
        response = requests.get(welcome_url, timeout=5)
        results['tests']['welcome_via_nginx'] = {
            'status': 'success' if response.status_code == 200 else 'failed',
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'url': welcome_url,
            'message': 'Welcome page is accessible via Nginx' if response.status_code == 200 else f'Welcome page returned status {response.status_code}'
        }
    except Exception as e:
        results['tests']['welcome_via_nginx'] = {
            'status': 'error',
            'url': welcome_url,
            'message': f'Error accessing welcome page via Nginx: {str(e)}'
        }
    
    return jsonify(results)


@files_bp.route('/edit-onlyoffice/<int:file_id>')
@login_required
@check_module_access('module_files')
def edit_onlyoffice(file_id):
    """Edit a file using ONLYOFFICE editor."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        flash('ONLYOFFICE ist nicht aktiviert.', 'warning')
        return redirect(url_for('files.index'))
    
    file = File.query.get_or_404(file_id)
    
    # Für Gast-Accounts: Prüfe ob Zugriff über Freigabelink besteht
    if hasattr(current_user, 'is_guest') and current_user.is_guest:
        from app.utils.access_control import guest_has_file_access
        if not guest_has_file_access(current_user, file):
            flash('Sie haben keinen Zugriff auf diese Datei.', 'danger')
            return redirect(url_for('files.index'))
    
    # Check if file type is supported by ONLYOFFICE
    from app.utils.onlyoffice import is_onlyoffice_file_type, get_onlyoffice_document_type, get_onlyoffice_file_type, generate_onlyoffice_token
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if not is_onlyoffice_file_type(file_ext):
        flash('Dieser Dateityp wird von ONLYOFFICE nicht unterstützt.', 'warning')
        if file.folder_id:
            return redirect(url_for('files.browse_folder', folder_id=file.folder_id))
        else:
            return redirect(url_for('files.index'))
    
    # Get document type and file type
    document_type = get_onlyoffice_document_type(file_ext)
    file_type = get_onlyoffice_file_type(file_ext)
    
    # Generate unique document key for versioning
    # IMPORTANT: For co-editing to work, all users opening the same file version must have the same key
    # The key should only change when a new version is saved (version_number increases)
    import hashlib
    key_string = f"{file.id}_{file.version_number}"
    document_key = hashlib.md5(key_string.encode()).hexdigest()
    
    # Generate access token for OnlyOffice to access the document
    from app.utils.onlyoffice import generate_onlyoffice_access_token
    access_token = generate_onlyoffice_access_token(file.id, current_user.id)
    
    # Build document URL - use public URL if OnlyOffice is on different server
    public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
    if public_url:
        # Use configured public URL (required when OnlyOffice runs on different server)
        public_url = public_url.rstrip('/')
        # Build URL manually to ensure token is included as query parameter
        # IMPORTANT: Use urllib.parse.quote to properly encode the token
        from urllib.parse import quote
        base_url = url_for('files.onlyoffice_document', file_id=file.id)
        encoded_token = quote(access_token, safe='')
        document_url = f"{public_url}{base_url}?token={encoded_token}"
        callback_url = f"{public_url}{url_for('files.onlyoffice_callback', file_id=file.id)}"
    else:
        # Use _external=True (works if OnlyOffice is on same server or accessible via same domain)
        from urllib.parse import quote
        base_url = url_for('files.onlyoffice_document', file_id=file.id, _external=True)
        encoded_token = quote(access_token, safe='')
        document_url = f"{base_url}?token={encoded_token}"
        callback_url = url_for('files.onlyoffice_callback', file_id=file.id, _external=True)
    
    # Log URLs for debugging
    logging.info(f"ONLYOFFICE document_url: {document_url}")
    logging.info(f"ONLYOFFICE callback_url: {callback_url}")
    logging.info(f"ONLYOFFICE access_token: {access_token[:8]}... (length: {len(access_token)})")
    
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    
    # Build full URL to ONLYOFFICE API
    if onlyoffice_url.startswith('http'):
        # Absolute URL - normalize (remove trailing slash if present)
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    else:
        # Relative path - use request host and scheme
        scheme = request.scheme
        host = request.host
        # Ensure onlyoffice_url starts with /
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        # Remove trailing slash
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    # Build editor configuration for token generation
    editor_config = {
        "document": {
            "fileType": file_type,
            "key": document_key,
            "title": file.name,
            "url": document_url
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit",
            "user": {
                "id": str(current_user.id),
                "name": current_user.full_name
            }
        }
    }
    
    # Generate token if secret key is configured
    token = generate_onlyoffice_token(editor_config)
    
    # Log token status for debugging
    if token:
        logging.debug(f"ONLYOFFICE token generated for file {file.id}")
    else:
        secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', '')
        if secret_key:
            logging.warning(f"ONLYOFFICE token generation failed for file {file.id} (secret key is set)")
        else:
            logging.debug(f"ONLYOFFICE token not generated for file {file.id} (no secret key configured)")
    
    # Calculate return URL
    if file.folder_id:
        return_url = url_for('files.browse_folder', folder_id=file.folder_id)
    else:
        return_url = url_for('files.index')
    
    # Get user accent color/style
    accent_color = current_user.accent_color if current_user.is_authenticated else '#0d6efd'
    accent_style = current_user.accent_style if current_user.is_authenticated else 'linear-gradient(45deg, #0d6efd, #0d6efd)'
    
    current_language = get_current_language()
    
    return render_template(
        'files/edit_onlyoffice.html',
        file=file,
        document_key=document_key,
        document_type=document_type,
        file_type=file_type,
        document_url=document_url,
        callback_url=callback_url,
        onlyoffice_api_url=api_url,
        onlyoffice_url=onlyoffice_url,
        token=token or '',  # Pass empty string instead of None
        guest_mode=False,
        return_url=return_url,
        accent_color=accent_color,
        accent_style=accent_style,
        current_language=current_language
    )


@files_bp.route('/share/<token>/edit-onlyoffice')
def share_edit_onlyoffice(token):
    """Edit a shared file using ONLYOFFICE editor (Gast-Zugriff)."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        flash('ONLYOFFICE ist nicht aktiviert.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    
    item, guest_name = _check_share_access(token)
    if not item or not guest_name:
        flash('Bitte geben Sie zuerst Ihren Namen ein.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    
    # Prüfe ob eine spezifische Datei aus einem Ordner bearbeitet werden soll
    file_id = request.args.get('file_id')
    if file_id:
        try:
            file_id = int(file_id)
            # Prüfe ob es ein freigegebener Ordner ist
            if isinstance(item, Folder):
                file = File.query.filter_by(id=file_id, folder_id=item.id, is_current=True).first_or_404()
            else:
                # Direkt freigegebene Datei
                file = item
        except (ValueError, TypeError):
            flash('Ungültige Datei-ID.', 'danger')
            return redirect(url_for('files.public_share', token=token))
    else:
        # Direkt freigegebene Datei
        if not isinstance(item, File):
            flash('Ordner können nicht mit ONLYOFFICE bearbeitet werden. Bitte wählen Sie eine Datei aus.', 'warning')
            return redirect(url_for('files.public_share', token=token))
        file = item
    
    # Check if file type is supported by ONLYOFFICE
    from app.utils.onlyoffice import is_onlyoffice_file_type, get_onlyoffice_document_type, get_onlyoffice_file_type, generate_onlyoffice_token
    file_ext = os.path.splitext(file.original_name)[1].lower()
    
    if not is_onlyoffice_file_type(file_ext):
        flash('Dieser Dateityp wird von ONLYOFFICE nicht unterstützt.', 'warning')
        return redirect(url_for('files.public_share', token=token))
    
    # Get document type and file type
    document_type = get_onlyoffice_document_type(file_ext)
    file_type = get_onlyoffice_file_type(file_ext)
    
    # Generate unique document key for versioning
    # IMPORTANT: For co-editing to work, all users opening the same file version must have the same key
    # The key should only change when a new version is saved (version_number increases)
    import hashlib
    key_string = f"{file.id}_{file.version_number}"
    document_key = hashlib.md5(key_string.encode()).hexdigest()
    
    # Build document URL with token and file_id (guest_name ist in Session)
    # Share endpoints don't need additional token as they use share_token
    public_url = current_app.config.get('ONLYOFFICE_PUBLIC_URL', '').strip()
    if public_url:
        # Use configured public URL (required when OnlyOffice runs on different server)
        public_url = public_url.rstrip('/')
        document_url = f"{public_url}{url_for('files.share_onlyoffice_document', token=token, file_id=file.id)}"
        callback_url = f"{public_url}{url_for('files.share_onlyoffice_callback', token=token, file_id=file.id)}"
    else:
        # Use _external=True (works if OnlyOffice is on same server or accessible via same domain)
        document_url = url_for('files.share_onlyoffice_document', token=token, file_id=file.id, _external=True)
        callback_url = url_for('files.share_onlyoffice_callback', token=token, file_id=file.id, _external=True)
    
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    
    # Build full URL to ONLYOFFICE API
    if onlyoffice_url.startswith('http'):
        # Absolute URL - normalize (remove trailing slash if present)
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    else:
        # Relative path - use request host and scheme
        scheme = request.scheme
        host = request.host
        # Ensure onlyoffice_url starts with /
        if not onlyoffice_url.startswith('/'):
            onlyoffice_url = '/' + onlyoffice_url
        # Remove trailing slash
        onlyoffice_url = onlyoffice_url.rstrip('/')
        api_url = f"{scheme}://{host}{onlyoffice_url}/web-apps/apps/api/documents/api.js"
    
    # Build editor configuration for token generation
    editor_config = {
        "document": {
            "fileType": file_type,
            "key": document_key,
            "title": file.name,
            "url": document_url
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit",
            "user": {
                "id": f"guest_{token}",
                "name": guest_name
            }
        }
    }
    
    # Generate token if secret key is configured
    onlyoffice_token = generate_onlyoffice_token(editor_config)
    
    # Log token status for debugging
    if onlyoffice_token:
        logging.debug(f"ONLYOFFICE token generated for shared file {file.id}")
    else:
        secret_key = current_app.config.get('ONLYOFFICE_SECRET_KEY', '')
        if secret_key:
            logging.warning(f"ONLYOFFICE token generation failed for shared file {file.id} (secret key is set)")
        else:
            logging.debug(f"ONLYOFFICE token not generated for shared file {file.id} (no secret key configured)")
    
    # Calculate return URL for shared files
    return_url = url_for('files.public_share', token=token)
    
    # For guest users, use default accent color
    accent_color = '#0d6efd'
    accent_style = 'linear-gradient(45deg, #0d6efd, #0d6efd)'
    
    current_language = get_current_language()
    
    return render_template(
        'files/edit_onlyoffice.html',
        file=file,
        document_key=document_key,
        document_type=document_type,
        file_type=file_type,
        document_url=document_url,
        callback_url=callback_url,
        onlyoffice_api_url=api_url,
        onlyoffice_url=onlyoffice_url,
        token=onlyoffice_token or '',  # Pass empty string instead of None
        guest_mode=True,
        guest_name=guest_name,
        share_token=token,
        return_url=return_url,
        accent_color=accent_color,
        accent_style=accent_style,
        current_language=current_language
    )


@files_bp.route('/api/onlyoffice-document/<int:file_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def onlyoffice_document(file_id):
    """Serve document to ONLYOFFICE editor."""
    # IMPORTANT: This endpoint must NOT require login, as OnlyOffice Document Server
    # cannot send session cookies. It uses token-based authentication instead.
    
    # Handle OPTIONS request for CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            # OnlyOffice läuft auf demselben Server - verwende Request-Origin
            origin = request.headers.get('Origin', '*')
            if origin == 'null' or not origin or origin == '*':
                origin = f"{request.scheme}://{request.host}"
        
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    # Log ALL requests to this endpoint (including failed ones)
    logging.info(f"ONLYOFFICE document endpoint called - method: {request.method}, file_id: {file_id}, remote_addr: {request.remote_addr}, user_agent: {request.headers.get('User-Agent', 'Unknown')}")
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        logging.warning(f"ONLYOFFICE document request rejected - OnlyOffice not enabled")
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    # Check for access token (REQUIRED for OnlyOffice access)
    access_token = request.args.get('token')
    # Log full token info to verify it's complete
    if access_token:
        token_length = len(access_token)
        token_preview = access_token[:8] + '...' + access_token[-4:] if token_length > 12 else access_token
        logging.info(f"ONLYOFFICE document request - file_id: {file_id}, token_length: {token_length}, token_preview: {token_preview}, full_token: {access_token}")
    else:
        logging.warning(f"ONLYOFFICE document request - file_id: {file_id}, NO TOKEN in request!")
    logging.info(f"ONLYOFFICE request details - method: {request.method}, remote_addr: {request.remote_addr}, referer: {request.headers.get('Referer', 'None')}, user_agent: {request.headers.get('User-Agent', 'Unknown')}")
    
    # Token is REQUIRED - OnlyOffice cannot use session cookies
    if not access_token:
        logging.error(f"ONLYOFFICE document access denied - NO TOKEN provided for file {file_id}. OnlyOffice Document Server cannot use session cookies!")
        # Return JSON error, NOT HTML redirect
        return jsonify({'error': 'Access token required'}), 403
    
    # Validate token
    from app.utils.onlyoffice import validate_onlyoffice_access_token
    if not validate_onlyoffice_access_token(access_token, file_id):
        logging.error(f"ONLYOFFICE document access denied - INVALID TOKEN for file {file_id}")
        return jsonify({'error': 'Invalid access token'}), 403
    
    logging.info(f"ONLYOFFICE document access granted via token for file {file_id}")
    
    file = File.query.get_or_404(file_id)
    logging.info(f"ONLYOFFICE document request - file_id: {file_id}, file: {file.original_name}, token_present: {bool(access_token)}")
    
    # Additional security: if no token, verify user has access to file
    if not access_token and current_user.is_authenticated:
        # Check if user has access to this file
        # (User must own the file or have access through folder permissions)
        if file.uploaded_by != current_user.id:
            # Check folder access if file is in a folder
            if file.folder_id:
                folder = Folder.query.get(file.folder_id)
                if not folder or folder.created_by != current_user.id:
                    logging.warning(f"ONLYOFFICE access denied - user {current_user.id} has no access to file {file_id}")
                    return jsonify({'error': 'Access denied'}), 403
            else:
                logging.warning(f"ONLYOFFICE access denied - user {current_user.id} has no access to file {file_id}")
                return jsonify({'error': 'Access denied'}), 403
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        logging.error(f"ONLYOFFICE file not found: {file_path} (file_id: {file_id}, original_name: {file.original_name})")
        return jsonify({'error': 'File not found'}), 404
    
    logging.info(f"ONLYOFFICE serving file: {file.original_name} from {file_path} (size: {os.path.getsize(file_path)} bytes)")
    
    # Determine MIME type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    mime_types = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.odt': 'application/vnd.oasis.opendocument.text',
        '.rtf': 'application/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.markdown': 'text/markdown',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
        '.csv': 'text/csv',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.odp': 'application/vnd.oasis.opendocument.presentation',
        '.pdf': 'application/pdf'
    }
    mimetype = mime_types.get(file_ext, 'application/octet-stream')
    
    # Create response with CORS headers for cross-origin requests
    response = send_file(
        file_path,
        mimetype=mimetype,
        download_name=file.original_name,
        as_attachment=False
    )
    
    # Add CORS headers to allow OnlyOffice (auch wenn auf demselben Server über Proxy)
    # OnlyOffice läuft über einen Proxy, daher benötigen wir CORS-Header
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        # Extract origin from OnlyOffice URL
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    else:
        # OnlyOffice läuft auf demselben Server, aber über Proxy - verwende Request-Origin
        origin = request.headers.get('Origin', '*')
        if origin == 'null' or not origin or origin == '*':
            # Fallback: verwende die aktuelle Request-URL als Origin
            origin = f"{request.scheme}://{request.host}"
    
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response


@files_bp.route('/share/<token>/api/onlyoffice-document/<int:file_id>', methods=['GET', 'HEAD', 'OPTIONS'])
def share_onlyoffice_document(token, file_id):
    """Serve document to ONLYOFFICE editor (Gast-Zugriff)."""
    # Handle OPTIONS request for CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
        else:
            # OnlyOffice läuft auf demselben Server - verwende Request-Origin
            origin = request.headers.get('Origin', '*')
            if origin == 'null' or not origin or origin == '*':
                origin = f"{request.scheme}://{request.host}"
        
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    # Log ALL requests to this endpoint
    logging.info(f"ONLYOFFICE share document endpoint called - method: {request.method}, token: {token[:8]}..., file_id: {file_id}, remote_addr: {request.remote_addr}")
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        logging.warning(f"ONLYOFFICE share document request rejected - OnlyOffice not enabled")
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    # IMPORTANT: OnlyOffice callbacks don't have session cookies, so we need to validate
    # the token differently. We'll check if the share token is valid by querying the database.
    # Don't use _check_share_access as it requires session data.
    shared_file = File.query.filter_by(share_token=token, share_enabled=True).first()
    shared_folder = None
    if not shared_file:
        shared_folder = Folder.query.filter_by(share_token=token, share_enabled=True).first()
    
    if not shared_file and not shared_folder:
        logging.warning(f"ONLYOFFICE share document access denied - Invalid share token: {token[:8]}...")
        return jsonify({'error': 'Invalid share token'}), 403
    
    # Determine which item was shared (file or folder)
    item = shared_file if shared_file else shared_folder
    
    # Prüfe ob es eine Datei aus einem Ordner ist oder direkt freigegebene Datei
    if isinstance(item, Folder):
        file = File.query.filter_by(id=file_id, folder_id=item.id, is_current=True).first_or_404()
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            logging.warning(f"ONLYOFFICE share document access denied - File ID mismatch: expected {item.id}, got {file_id}")
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    logging.info(f"ONLYOFFICE share document access granted - file_id: {file_id}, file: {file.original_name}")
    
    # Ensure we have an absolute path
    if not os.path.isabs(file.file_path):
        file_path = os.path.join(os.getcwd(), file.file_path)
    else:
        file_path = file.file_path
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    # Determine MIME type
    file_ext = os.path.splitext(file.original_name)[1].lower()
    mime_types = {
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.doc': 'application/msword',
        '.odt': 'application/vnd.oasis.opendocument.text',
        '.rtf': 'application/rtf',
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.markdown': 'text/markdown',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.xls': 'application/vnd.ms-excel',
        '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
        '.csv': 'text/csv',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.odp': 'application/vnd.oasis.opendocument.presentation',
        '.pdf': 'application/pdf'
    }
    mimetype = mime_types.get(file_ext, 'application/octet-stream')
    
    # Create response with CORS headers for cross-origin requests
    response = send_file(
        file_path,
        mimetype=mimetype,
        download_name=file.original_name,
        as_attachment=False
    )
    
    # Add CORS headers to allow OnlyOffice (auch wenn auf demselben Server über Proxy)
    # OnlyOffice läuft über einen Proxy, daher benötigen wir CORS-Header
    onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    if onlyoffice_url.startswith('http'):
        # Extract origin from OnlyOffice URL
        from urllib.parse import urlparse
        parsed = urlparse(onlyoffice_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    else:
        # OnlyOffice läuft auf demselben Server, aber über Proxy - verwende Request-Origin
        origin = request.headers.get('Origin', '*')
        if origin == 'null' or not origin or origin == '*':
            # Fallback: verwende die aktuelle Request-URL als Origin
            origin = f"{request.scheme}://{request.host}"
    
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response


@files_bp.route('/api/onlyoffice-save/<int:file_id>', methods=['POST'])
@login_required
def onlyoffice_save(file_id):
    """Save document from ONLYOFFICE."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    file = File.query.get_or_404(file_id)
    
    # Get file content from request
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request'}), 400
    
    uploaded_file = request.files['file']
    
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
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    uploaded_file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    file.file_path = absolute_filepath
    file.file_size = os.path.getsize(absolute_filepath)
    file.version_number += 1
    file.uploaded_by = current_user.id
    file.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    # Send notification
    try:
        send_file_notification(file.id, 'modified')
    except Exception as e:
        logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
    
    return jsonify({'success': True, 'message': 'File saved successfully'})


@files_bp.route('/share/<token>/api/onlyoffice-save/<int:file_id>', methods=['POST'])
def share_onlyoffice_save(token, file_id):
    """Save document from ONLYOFFICE (Gast-Zugriff)."""
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    item, guest_name = _check_share_access(token)
    if not item or not guest_name:
        return jsonify({'error': 'Access denied'}), 403
    
    # Prüfe ob es eine Datei aus einem Ordner ist oder direkt freigegebene Datei
    if isinstance(item, Folder):
        file = File.query.filter_by(id=file_id, folder_id=item.id, is_current=True).first_or_404()
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    # Get file content from request
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request'}), 400
    
    uploaded_file = request.files['file']
    
    # Get anonymous user for guest edits
    anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
    if not anonymous_user:
        anonymous_user = User(
            email='anonymous@system.local',
            first_name=guest_name,
            last_name='',
            password_hash='',
            is_active=True,
            is_admin=False,
            is_email_confirmed=True
        )
        db.session.add(anonymous_user)
        db.session.flush()
    
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
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    uploaded_file.save(filepath)
    
    # Store absolute path in database
    absolute_filepath = os.path.abspath(filepath)
    
    file.file_path = absolute_filepath
    file.file_size = os.path.getsize(absolute_filepath)
    file.version_number += 1
    file.uploaded_by = anonymous_user.id
    file.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'File saved successfully'})


@files_bp.route('/onlyoffice-callback', methods=['POST', 'OPTIONS'])
def onlyoffice_callback():
    """Handle callbacks from ONLYOFFICE Document Server."""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        status = data.get('status')
        key = data.get('key')
        
        logging.info(f"ONLYOFFICE callback received - status: {status}, key: {key}")
        
        # Status values:
        # 0 - document is being edited
        # 1 - document is ready for saving (informational, don't save yet)
        # 2 - document saving error has occurred
        # 3 - document is closed with no changes
        # 4 - document is being edited, but the current document state is saved (auto-save) - SAVE THIS for collaborative editing
        # 6 - document is being edited, but the current document state is saved (force save) - SAVE THIS
        # 7 - error has occurred while force saving the document
        
        # IMPORTANT: Save on status 6 (force save) and status 4 (auto-save)
        # Status 4 enables collaborative editing without manual saving
        # Status 1 is informational and should NOT trigger a save (would cause version conflicts)
        # We save both status 4 and 6 to enable real-time collaborative editing
        if status in [4, 6]:
            # Get file_id from callback URL parameter
            file_id = request.args.get('file_id')
            
            if file_id:
                try:
                    file_id = int(file_id)
                    file = File.query.get(file_id)
                    
                    if file:
                        # IMPORTANT: Prevent saving during initial load to avoid "Version wurde geändert" messages
                        # Check if file was recently opened (within last 10 seconds)
                        # This prevents callbacks during initial document load from causing version conflicts
                        time_since_update = (datetime.utcnow() - file.updated_at).total_seconds() if file.updated_at else 999
                        
                        # If file was updated very recently (less than 10 seconds ago), it might be from initial load
                        # Only skip auto-save (status 4), but always allow force save (status 6)
                        if status == 4 and time_since_update < 10:
                            logging.info(f"ONLYOFFICE: Skipping auto-save for file {file_id} (recently updated, likely initial load)")
                            # Still return success to OnlyOffice
                            response = jsonify({'error': 0})
                            onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
                            if onlyoffice_url.startswith('http'):
                                from urllib.parse import urlparse
                                parsed = urlparse(onlyoffice_url)
                                origin = f"{parsed.scheme}://{parsed.netloc}"
                                response.headers['Access-Control-Allow-Origin'] = origin
                                response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
                                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
                                response.headers['Access-Control-Allow-Credentials'] = 'true'
                            return response
                        
                        saved_file_url = data.get('url')
                        
                        if saved_file_url:
                            # Download the saved file from ONLYOFFICE
                            response = requests.get(saved_file_url)
                            
                            if response.status_code == 200:
                                # Save new version
                                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                                filename = f"{timestamp}_{file.original_name}"
                                filepath = os.path.join('uploads', 'files', filename)
                                
                                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                                
                                with open(filepath, 'wb') as f:
                                    f.write(response.content)
                                
                                absolute_filepath = os.path.abspath(filepath)
                                
                                # IMPORTANT: For collaborative editing, we need to be careful about version increments
                                # Status 6 (force save) always increments version and creates version history
                                # Status 4 (auto-save) should NOT increment version to avoid "Version wurde geändert" messages
                                
                                if status == 6:
                                    # Force save: Create new version with history
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
                                    
                                    file.file_path = absolute_filepath
                                    file.file_size = os.path.getsize(absolute_filepath)
                                    file.version_number += 1
                                    file.updated_at = datetime.utcnow()
                                    
                                    db.session.commit()
                                    
                                    logging.info(f"ONLYOFFICE: File {file_id} force saved (new version {file.version_number})")
                                else:
                                    # Auto-save (status 4): Update file in place without version increment
                                    # This allows collaborative editing without "Version wurde geändert" messages
                                    old_file_path = file.file_path
                                    file.file_path = absolute_filepath
                                    file.file_size = os.path.getsize(absolute_filepath)
                                    file.updated_at = datetime.utcnow()
                                    # Keep same version_number for auto-save
                                    
                                    db.session.commit()
                                    
                                    # Delete old file if it's different (but keep versions)
                                    if old_file_path != absolute_filepath and os.path.exists(old_file_path):
                                        # Only delete if it's not a version file
                                        try:
                                            os.remove(old_file_path)
                                        except Exception as e:
                                            logging.warning(f"Could not delete old file {old_file_path}: {e}")
                                    
                                    logging.info(f"ONLYOFFICE: File {file_id} auto-saved (version {file.version_number} updated)")
                                
                                # Send notification
                                try:
                                    send_file_notification(file.id, 'modified')
                                except Exception as e:
                                    logging.error(f"Fehler beim Senden der Datei-Benachrichtigung: {e}")
                except (ValueError, TypeError) as e:
                    logging.error(f"ONLYOFFICE callback: Invalid file_id: {e}")
                except Exception as e:
                    logging.error(f"ONLYOFFICE callback: Error saving file: {e}")
            else:
                logging.warning("ONLYOFFICE callback: No file_id provided in callback URL")
        
        # Create response with CORS headers
        response = jsonify({'error': 0})  # Success response for ONLYOFFICE
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
        
    except Exception as e:
        logging.error(f"ONLYOFFICE callback error: {e}")
        error_response = jsonify({'error': str(e)})
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            error_response.headers['Access-Control-Allow-Origin'] = origin
            error_response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            error_response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            error_response.headers['Access-Control-Allow-Credentials'] = 'true'
        return error_response, 500


@files_bp.route('/share/<token>/onlyoffice-callback', methods=['POST', 'OPTIONS'])
def share_onlyoffice_callback(token):
    """Handle callbacks from ONLYOFFICE Document Server (Gast-Zugriff)."""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        response = jsonify({})
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    # Check if ONLYOFFICE is enabled
    if not current_app.config.get('ONLYOFFICE_ENABLED', False):
        return jsonify({'error': 'ONLYOFFICE not enabled'}), 404
    
    # IMPORTANT: OnlyOffice callbacks don't have session cookies, so we need to validate
    # the token differently. We'll check if the share token is valid by querying the database.
    # Don't use _check_share_access as it requires session data.
    shared_file = File.query.filter_by(share_token=token, share_enabled=True).first()
    shared_folder = None
    if not shared_file:
        shared_folder = Folder.query.filter_by(share_token=token, share_enabled=True).first()
    
    if not shared_file and not shared_folder:
        logging.warning(f"ONLYOFFICE share callback: Invalid share token: {token}")
        return jsonify({'error': 'Invalid share token'}), 403
    
    # Use a default guest name for callbacks (OnlyOffice doesn't send session info)
    guest_name = 'Gast' if not shared_file else (shared_file.share_name or 'Gast')
    item = shared_file if shared_file else shared_folder
    
    # Get file_id from callback URL parameter
    file_id = request.args.get('file_id')
    if not file_id:
        return jsonify({'error': 'File ID required'}), 400
    
    try:
        file_id = int(file_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid file ID'}), 400
    
    # Prüfe ob es eine Datei aus einem Ordner ist oder direkt freigegebene Datei
    if isinstance(item, Folder):
        file = File.query.filter_by(id=file_id, folder_id=item.id, is_current=True).first_or_404()
    else:
        # Direkt freigegebene Datei
        if item.id != file_id:
            return jsonify({'error': 'File ID mismatch'}), 403
        file = item
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        status = data.get('status')
        
        logging.info(f"ONLYOFFICE share callback received - status: {status}")
        
        # Status values:
        # 0 - document is being edited
        # 1 - document is ready for saving (informational, don't save yet)
        # 2 - document saving error has occurred
        # 3 - document is closed with no changes
        # 4 - document is being edited, but the current document state is saved (auto-save) - SAVE THIS for collaborative editing
        # 6 - document is being edited, but the current document state is saved (force save) - SAVE THIS
        # 7 - error has occurred while force saving the document
        
        # IMPORTANT: Save on status 6 (force save) and status 4 (auto-save)
        # Status 4 enables collaborative editing without manual saving
        # Status 1 is informational and should NOT trigger a save (would cause version conflicts)
        if status in [4, 6]:
            # IMPORTANT: Prevent saving during initial load to avoid "Version wurde geändert" messages
            # Check if file was recently opened (within last 10 seconds)
            # This prevents callbacks during initial document load from causing version conflicts
            time_since_update = (datetime.utcnow() - file.updated_at).total_seconds() if file.updated_at else 999
            
            # If file was updated very recently (less than 10 seconds ago), it might be from initial load
            # Only skip auto-save (status 4), but always allow force save (status 6)
            if status == 4 and time_since_update < 10:
                logging.info(f"ONLYOFFICE: Skipping auto-save for shared file {file.id} (recently updated, likely initial load)")
                # Still return success to OnlyOffice
                response = jsonify({'error': 0})
                onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
                if onlyoffice_url.startswith('http'):
                    from urllib.parse import urlparse
                    parsed = urlparse(onlyoffice_url)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    response.headers['Access-Control-Allow-Origin'] = origin
                    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
                    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
                    response.headers['Access-Control-Allow-Credentials'] = 'true'
                return response
            
            saved_file_url = data.get('url')
            
            if saved_file_url:
                # Download the saved file from ONLYOFFICE
                response = requests.get(saved_file_url)
                
                if response.status_code == 200:
                    # Get anonymous user for guest edits
                    anonymous_user = User.query.filter_by(email='anonymous@system.local').first()
                    if not anonymous_user:
                        anonymous_user = User(
                            email='anonymous@system.local',
                            first_name=guest_name,
                            last_name='',
                            password_hash='',
                            is_active=True,
                            is_admin=False,
                            is_email_confirmed=True
                        )
                        db.session.add(anonymous_user)
                        db.session.flush()
                    
                    # Save new version
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{file.original_name}"
                    filepath = os.path.join('uploads', 'files', filename)
                    
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    absolute_filepath = os.path.abspath(filepath)
                    
                    # IMPORTANT: For collaborative editing, we need to be careful about version increments
                    # Status 6 (force save) always increments version and creates version history
                    # Status 4 (auto-save) should NOT increment version to avoid "Version wurde geändert" messages
                    
                    if status == 6:
                        # Force save: Create new version with history
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
                        
                        file.file_path = absolute_filepath
                        file.file_size = os.path.getsize(absolute_filepath)
                        file.version_number += 1
                        file.uploaded_by = anonymous_user.id
                        file.updated_at = datetime.utcnow()
                        
                        db.session.commit()
                        
                        logging.info(f"ONLYOFFICE: Shared file {file.id} force saved (new version {file.version_number}) by guest {guest_name}")
                    else:
                        # Auto-save (status 4): Update file in place without version increment
                        old_file_path = file.file_path
                        file.file_path = absolute_filepath
                        file.file_size = os.path.getsize(absolute_filepath)
                        file.updated_at = datetime.utcnow()
                        # Keep same version_number and uploaded_by for auto-save
                        
                        db.session.commit()
                        
                        # Delete old file if it's different (but keep versions)
                        if old_file_path != absolute_filepath and os.path.exists(old_file_path):
                            try:
                                os.remove(old_file_path)
                            except Exception as e:
                                logging.warning(f"Could not delete old file {old_file_path}: {e}")
                        
                        logging.info(f"ONLYOFFICE: Shared file {file.id} auto-saved (version {file.version_number} updated) by guest {guest_name}")
        
        # Create response with CORS headers
        response = jsonify({'error': 0})  # Success response for ONLYOFFICE
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
        
    except Exception as e:
        logging.error(f"ONLYOFFICE callback error (share): {e}")
        error_response = jsonify({'error': str(e)})
        onlyoffice_url = current_app.config.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
        if onlyoffice_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(onlyoffice_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            error_response.headers['Access-Control-Allow-Origin'] = origin
            error_response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            error_response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            error_response.headers['Access-Control-Allow-Credentials'] = 'true'
        return error_response, 500



