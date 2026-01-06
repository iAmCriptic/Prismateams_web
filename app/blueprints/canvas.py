from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, url_for as flask_url_for, current_app
from flask_login import login_required, current_user
from app.utils.i18n import _
from app import db
from app.models.canvas import Canvas
from app.models.user import User
from app.utils.access_control import check_module_access
from datetime import datetime
import uuid

canvas_bp = Blueprint('canvas', __name__)


@canvas_bp.route('/')
@login_required
@check_module_access('module_canvas')
def index():
    """List all canvases."""
    from app.utils.excalidraw import is_excalidraw_enabled
    if not is_excalidraw_enabled():
        flash('Excalidraw ist nicht aktiviert. Bitte aktivieren Sie Excalidraw in den Einstellungen.', 'warning')
        return redirect(url_for('settings.index'))
    
    canvases = Canvas.query.order_by(Canvas.updated_at.desc()).all()
    return render_template('canvas/index.html', canvases=canvases)


@canvas_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_canvas')
def create():
    """Create a new canvas."""
    from app.utils.excalidraw import is_excalidraw_enabled
    if not is_excalidraw_enabled():
        flash('Excalidraw ist nicht aktiviert. Bitte aktivieren Sie Excalidraw in den Einstellungen.', 'warning')
        return redirect(url_for('canvas.index'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash(_('canvas.create.alerts.name_required', default='Name ist erforderlich.'), 'danger')
            return render_template('canvas/create.html')
        
        room_id = str(uuid.uuid4())
        
        initial_data = {
            'type': 'excalidraw',
            'version': 2,
            'source': 'https://excalidraw.com',
            'elements': [],
            'appState': {
                'gridSize': None,
                'viewBackgroundColor': '#ffffff'
            },
            'files': {}
        }
        
        canvas = Canvas(
            name=name,
            description=description,
            room_id=room_id,
            created_by=current_user.id
        )
        canvas.set_excalidraw_data(initial_data)
        
        db.session.add(canvas)
        db.session.commit()
        
        flash(_('canvas.flash.created', name=name, default=f'Canvas "{name}" wurde erfolgreich erstellt.'), 'success')
        return redirect(url_for('canvas.edit', canvas_id=canvas.id))
    
    return render_template('canvas/create.html')


@canvas_bp.route('/edit/<int:canvas_id>')
@login_required
@check_module_access('module_canvas')
def edit(canvas_id):
    """Edit a canvas with Excalidraw."""
    from app.utils.excalidraw import is_excalidraw_enabled, validate_excalidraw_config
    if not is_excalidraw_enabled():
        flash('Excalidraw ist nicht aktiviert. Bitte aktivieren Sie Excalidraw in den Einstellungen.', 'warning')
        return redirect(url_for('canvas.index'))
    
    # Validiere Excalidraw-Konfiguration
    config_warnings = validate_excalidraw_config()
    if config_warnings:
        for warning in config_warnings:
            current_app.logger.warning(f"Excalidraw-Konfigurationswarnung: {warning}")
            flash(f'Excalidraw-Konfigurationswarnung: {warning}', 'warning')
    
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    excalidraw_data = canvas_obj.get_excalidraw_data()
    
    if not canvas_obj.room_id:
        canvas_obj.room_id = str(uuid.uuid4())
        db.session.commit()
    
    from app.utils.excalidraw import get_excalidraw_url, get_excalidraw_room_url, get_excalidraw_public_url
    excalidraw_url = get_excalidraw_url()
    room_url = get_excalidraw_room_url()
    public_url = get_excalidraw_public_url()
    
    # Validiere URLs
    if not excalidraw_url or excalidraw_url.strip() == '':
        flash('Excalidraw URL ist nicht konfiguriert. Bitte überprüfen Sie die Einstellungen.', 'danger')
        return redirect(url_for('canvas.index'))
    
    # Generiere absolute URLs für Load und Save
    # Verwende EXCALIDRAW_PUBLIC_URL wenn gesetzt, sonst _external=True
    try:
        if public_url:
            # Entferne führendes / von public_url falls vorhanden, da url_for bereits / hinzufügt
            public_url_clean = public_url.rstrip('/')
            document_url = f"{public_url_clean}{flask_url_for('canvas.load', canvas_id=canvas_id)}"
            save_url = f"{public_url_clean}{flask_url_for('canvas.save', canvas_id=canvas_id)}"
        else:
            document_url = flask_url_for('canvas.load', canvas_id=canvas_id, _external=True)
            save_url = flask_url_for('canvas.save', canvas_id=canvas_id, _external=True)
    except Exception as e:
        # Fallback auf relative URLs bei Fehler
        current_app.logger.error(f"Fehler bei URL-Generierung: {e}", exc_info=True)
        document_url = flask_url_for('canvas.load', canvas_id=canvas_id)
        save_url = flask_url_for('canvas.save', canvas_id=canvas_id)
    
    return render_template(
        'canvas/edit.html',
        canvas=canvas_obj,
        excalidraw_data=excalidraw_data,
        excalidraw_url=excalidraw_url,
        room_url=room_url,
        room_id=canvas_obj.room_id,
        document_url=document_url,
        save_url=save_url,
        current_user=current_user
    )


@canvas_bp.route('/delete/<int:canvas_id>', methods=['POST'])
@login_required
@check_module_access('module_canvas')
def delete(canvas_id):
    """Delete a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    if canvas_obj.created_by != current_user.id and not current_user.is_admin:
        flash('Sie haben keine Berechtigung, diesen Canvas zu löschen.', 'danger')
        return redirect(url_for('canvas.index'))
    
    db.session.delete(canvas_obj)
    db.session.commit()
    
    flash(_('canvas.flash.deleted', name=canvas_obj.name, default=f'Canvas "{canvas_obj.name}" wurde erfolgreich gelöscht.'), 'success')
    return redirect(url_for('canvas.index'))


@canvas_bp.route('/<int:canvas_id>/load', methods=['GET', 'OPTIONS'])
@login_required
@check_module_access('module_canvas')
def load(canvas_id):
    """Load Excalidraw data for a canvas."""
    from flask import current_app
    from urllib.parse import urlparse
    from app.utils.excalidraw import get_excalidraw_room_url
    
    if request.method == 'OPTIONS':
        response = jsonify({})
        room_url = get_excalidraw_room_url()
        
        # Setze CORS-Header für Excalidraw Room Server
        # Wenn room_url absolut ist, extrahiere den Origin
        if room_url.startswith('http://') or room_url.startswith('https://'):
            try:
                parsed = urlparse(room_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                response.headers['Access-Control-Allow-Origin'] = origin
            except Exception:
                pass
        
        # Setze auch generische CORS-Header für Excalidraw
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    excalidraw_data = canvas_obj.get_excalidraw_data()
    
    if not excalidraw_data:
        excalidraw_data = {
            'type': 'excalidraw',
            'version': 2,
            'source': 'https://excalidraw.com',
            'elements': [],
            'appState': {
                'gridSize': None,
                'viewBackgroundColor': '#ffffff'
            },
            'files': {}
        }
    
    response = jsonify(excalidraw_data)
    
    # Setze CORS-Header für Excalidraw Room Server
    room_url = get_excalidraw_room_url()
    if room_url.startswith('http://') or room_url.startswith('https://'):
        try:
            parsed = urlparse(room_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            response.headers['Access-Control-Allow-Origin'] = origin
        except Exception:
            pass
    
    # Setze auch generische CORS-Header
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response


@canvas_bp.route('/<int:canvas_id>/save', methods=['POST', 'OPTIONS'])
@login_required
@check_module_access('module_canvas')
def save(canvas_id):
    """Save Excalidraw data for a canvas."""
    from flask import current_app
    from urllib.parse import urlparse
    from app.utils.excalidraw import get_excalidraw_room_url
    
    if request.method == 'OPTIONS':
        response = jsonify({})
        room_url = get_excalidraw_room_url()
        
        # Setze CORS-Header für Excalidraw Room Server
        # Wenn room_url absolut ist, extrahiere den Origin
        if room_url.startswith('http://') or room_url.startswith('https://'):
            try:
                parsed = urlparse(room_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                response.headers['Access-Control-Allow-Origin'] = origin
            except Exception:
                pass
        
        # Setze auch generische CORS-Header für Excalidraw
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response
    
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    try:
        data = request.get_json()
        
        if data:
            canvas_obj.set_excalidraw_data(data)
            canvas_obj.updated_at = datetime.utcnow()
            db.session.commit()
            
            response = jsonify({'success': True})
            
            # Setze CORS-Header für Excalidraw Room Server
            room_url = get_excalidraw_room_url()
            if room_url.startswith('http://') or room_url.startswith('https://'):
                try:
                    parsed = urlparse(room_url)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    response.headers['Access-Control-Allow-Origin'] = origin
                except Exception:
                    pass
            
            # Setze auch generische CORS-Header
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            
            return response
        else:
            return jsonify({'error': 'No data provided'}), 400
    except Exception as e:
        current_app.logger.error(f"Fehler beim Speichern des Canvas {canvas_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
