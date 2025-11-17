from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, url_for as flask_url_for
from flask_login import login_required, current_user
from app.utils.i18n import _
from app import db
from app.models.canvas import Canvas
from app.models.user import User
from datetime import datetime
import uuid

canvas_bp = Blueprint('canvas', __name__)


@canvas_bp.route('/')
@login_required
def index():
    """List all canvases."""
    # Prüfe ob Excalidraw aktiviert ist
    from app.utils.excalidraw import is_excalidraw_enabled
    if not is_excalidraw_enabled():
        flash('Excalidraw ist nicht aktiviert. Bitte aktivieren Sie Excalidraw in den Einstellungen.', 'warning')
        return redirect(url_for('settings.index'))
    
    canvases = Canvas.query.order_by(Canvas.updated_at.desc()).all()
    return render_template('canvas/index.html', canvases=canvases)


@canvas_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new canvas."""
    # Prüfe ob Excalidraw aktiviert ist
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
        
        # Generiere Room-ID für Excalidraw-Room
        room_id = str(uuid.uuid4())
        
        canvas = Canvas(
            name=name,
            description=description,
            room_id=room_id,
            created_by=current_user.id
        )
        
        db.session.add(canvas)
        db.session.commit()
        
        flash(_('canvas.flash.created', name=name, default=f'Canvas "{name}" wurde erfolgreich erstellt.'), 'success')
        return redirect(url_for('canvas.edit', canvas_id=canvas.id))
    
    return render_template('canvas/create.html')


@canvas_bp.route('/edit/<int:canvas_id>')
@login_required
def edit(canvas_id):
    """Edit a canvas with Excalidraw."""
    # Prüfe ob Excalidraw aktiviert ist
    from app.utils.excalidraw import is_excalidraw_enabled
    if not is_excalidraw_enabled():
        flash('Excalidraw ist nicht aktiviert. Bitte aktivieren Sie Excalidraw in den Einstellungen.', 'warning')
        return redirect(url_for('canvas.index'))
    
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    # Lade Excalidraw-Daten
    excalidraw_data = canvas_obj.get_excalidraw_data()
    
    # Generiere Room-ID falls nicht vorhanden
    if not canvas_obj.room_id:
        canvas_obj.room_id = str(uuid.uuid4())
        db.session.commit()
    
    # Excalidraw URLs
    from app.utils.excalidraw import get_excalidraw_url, get_excalidraw_room_url, get_excalidraw_public_url
    excalidraw_url = get_excalidraw_url()
    room_url = get_excalidraw_room_url()
    public_url = get_excalidraw_public_url()
    
    # URLs für Excalidraw
    document_url = f"{public_url}{flask_url_for('canvas.load', canvas_id=canvas_id)}" if public_url else flask_url_for('canvas.load', canvas_id=canvas_id, _external=True)
    save_url = f"{public_url}{flask_url_for('canvas.save', canvas_id=canvas_id)}" if public_url else flask_url_for('canvas.save', canvas_id=canvas_id, _external=True)
    
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
def delete(canvas_id):
    """Delete a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    # Nur Ersteller oder Admin kann löschen
    if canvas_obj.created_by != current_user.id and not current_user.is_admin:
        flash('Sie haben keine Berechtigung, diesen Canvas zu löschen.', 'danger')
        return redirect(url_for('canvas.index'))
    
    db.session.delete(canvas_obj)
    db.session.commit()
    
    flash(_('canvas.flash.deleted', name=canvas_obj.name, default=f'Canvas "{canvas_obj.name}" wurde erfolgreich gelöscht.'), 'success')
    return redirect(url_for('canvas.index'))


@canvas_bp.route('/<int:canvas_id>/load')
@login_required
def load(canvas_id):
    """Load Excalidraw data for a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    # Lade Excalidraw-Daten
    excalidraw_data = canvas_obj.get_excalidraw_data()
    
    # Wenn keine Daten vorhanden sind, gib leeres Excalidraw-Format zurück
    if not excalidraw_data:
        return jsonify({
            'type': 'excalidraw',
            'version': 2,
            'source': 'https://excalidraw.com',
            'elements': [],
            'appState': {
                'gridSize': None,
                'viewBackgroundColor': '#ffffff'
            },
            'files': {}
        })
    
    return jsonify(excalidraw_data)


@canvas_bp.route('/<int:canvas_id>/save', methods=['POST'])
@login_required
def save(canvas_id):
    """Save Excalidraw data for a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    # Nur Ersteller oder Admin kann speichern
    if canvas_obj.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        data = request.get_json()
        
        if data:
            canvas_obj.set_excalidraw_data(data)
            canvas_obj.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'No data provided'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
