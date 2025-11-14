from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _
from flask_socketio import emit, join_room, leave_room
from app import db, socketio
from app.models.canvas import Canvas, CanvasTextField, CanvasElement
from app.models.user import User
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime
from PIL import Image

canvas_bp = Blueprint('canvas', __name__)

# Store active users per canvas
active_canvas_users = {}


@canvas_bp.route('/')
@login_required
def index():
    """List all canvases."""
    canvases = Canvas.query.order_by(Canvas.updated_at.desc()).all()
    return render_template('canvas/index.html', canvases=canvases)


@canvas_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new canvas."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        if not name:
            flash(_('canvas.create.alerts.name_required'), 'danger')
            return render_template('canvas/create.html')
        
        canvas = Canvas(
            name=name,
            description=description,
            created_by=current_user.id
        )
        
        db.session.add(canvas)
        db.session.commit()
        
        flash(_('canvas.flash.created', name=name), 'success')
        return redirect(url_for('canvas.edit', canvas_id=canvas.id))
    
    return render_template('canvas/create.html')


@canvas_bp.route('/edit/<int:canvas_id>')
@login_required
def edit(canvas_id):
    """Edit a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    text_fields = CanvasTextField.query.filter_by(canvas_id=canvas_id).all()
    elements = CanvasElement.query.filter_by(canvas_id=canvas_id).order_by(CanvasElement.z_index).all()
    
    # Konvertiere Elemente zu JSON-Format für Frontend
    elements_data = []
    for element in elements:
        elements_data.append({
            'id': element.id,
            'type': element.element_type,
            'properties': element.get_properties(),
            'z_index': element.z_index
        })
    
    return render_template('canvas/edit.html', canvas=canvas_obj, text_fields=text_fields, elements=elements_data)


@canvas_bp.route('/delete/<int:canvas_id>', methods=['POST'])
@login_required
def delete(canvas_id):
    """Delete a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    db.session.delete(canvas_obj)
    db.session.commit()
    
    flash(_('canvas.flash.deleted', name=canvas_obj.name), 'success')
    return redirect(url_for('canvas.index'))


@canvas_bp.route('/<int:canvas_id>/add-text-field', methods=['POST'])
@login_required
def add_text_field(canvas_id):
    """Add a text field to a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    data = request.get_json()
    
    text_field = CanvasTextField(
        canvas_id=canvas_id,
        content=data.get('content', ''),
        pos_x=data.get('pos_x', 0),
        pos_y=data.get('pos_y', 0),
        width=data.get('width', 200),
        height=data.get('height', 100),
        font_size=data.get('font_size', 14),
        color=data.get('color', '#000000'),
        background_color=data.get('background_color', '#ffffff'),
        created_by=current_user.id
    )
    
    db.session.add(text_field)
    db.session.commit()
    
    return jsonify({
        'id': text_field.id,
        'content': text_field.content,
        'pos_x': text_field.pos_x,
        'pos_y': text_field.pos_y,
        'width': text_field.width,
        'height': text_field.height,
        'font_size': text_field.font_size,
        'color': text_field.color,
        'background_color': text_field.background_color
    })


@canvas_bp.route('/text-field/<int:field_id>/update', methods=['PUT', 'POST'])
@login_required
def update_text_field(field_id):
    """Update a text field."""
    text_field = CanvasTextField.query.get_or_404(field_id)
    
    data = request.get_json()
    
    if 'content' in data:
        text_field.content = data['content']
    if 'pos_x' in data:
        text_field.pos_x = data['pos_x']
    if 'pos_y' in data:
        text_field.pos_y = data['pos_y']
    if 'width' in data:
        text_field.width = data['width']
    if 'height' in data:
        text_field.height = data['height']
    if 'font_size' in data:
        text_field.font_size = data['font_size']
    if 'color' in data:
        text_field.color = data['color']
    if 'background_color' in data:
        text_field.background_color = data['background_color']
    
    db.session.commit()
    
    return jsonify({'success': True})


@canvas_bp.route('/text-field/<int:field_id>/delete', methods=['DELETE', 'POST'])
@login_required
def delete_text_field(field_id):
    """Delete a text field."""
    text_field = CanvasTextField.query.get_or_404(field_id)
    
    db.session.delete(text_field)
    db.session.commit()
    
    return jsonify({'success': True})


# CanvasElement CRUD Routes

@canvas_bp.route('/<int:canvas_id>/element', methods=['POST'])
@login_required
def create_element(canvas_id):
    """Create a new canvas element."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    data = request.get_json()
    
    element = CanvasElement(
        canvas_id=canvas_id,
        element_type=data.get('element_type'),
        z_index=data.get('z_index', 0),
        created_by=current_user.id
    )
    
    element.set_properties(data.get('properties', {}))
    
    db.session.add(element)
    db.session.commit()
    
    return jsonify({
        'id': element.id,
        'type': element.element_type,
        'properties': element.get_properties(),
        'z_index': element.z_index
    })


@canvas_bp.route('/element/<int:element_id>', methods=['PUT', 'POST'])
@login_required
def update_element(element_id):
    """Update a canvas element."""
    element = CanvasElement.query.get_or_404(element_id)
    
    data = request.get_json()
    
    if 'properties' in data:
        element.set_properties(data['properties'])
    if 'z_index' in data:
        element.z_index = data['z_index']
    
    element.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'id': element.id,
        'type': element.element_type,
        'properties': element.get_properties(),
        'z_index': element.z_index
    })


@canvas_bp.route('/element/<int:element_id>', methods=['DELETE', 'POST'])
@login_required
def delete_element(element_id):
    """Delete a canvas element."""
    element = CanvasElement.query.get_or_404(element_id)
    
    db.session.delete(element)
    db.session.commit()
    
    return jsonify({'success': True})


# Bild-Upload Route

@canvas_bp.route('/<int:canvas_id>/upload-image', methods=['POST'])
@login_required
def upload_image(canvas_id):
    """Upload an image for the canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Validiere Dateityp
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    if '.' not in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'error': 'Invalid file type'}), 400
    
    # Erstelle Upload-Verzeichnis
    project_root = os.path.dirname(current_app.root_path)
    upload_dir = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'canvas')
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generiere Dateinamen
    filename = secure_filename(file.filename)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{canvas_id}_{current_user.id}_{timestamp}_{filename}"
    
    # Speichere Datei
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    
    # Lese Bild-Dimensionen
    try:
        with Image.open(filepath) as img:
            width, height = img.size
    except Exception as e:
        width, height = 200, 200  # Fallback
    
    # Erstelle URL
    url = f"/canvas/image/{filename}"
    
    return jsonify({
        'url': url,
        'filename': filename,
        'width': width,
        'height': height
    })


@canvas_bp.route('/image/<path:filename>')
@login_required
def serve_image(filename):
    """Serve uploaded canvas images."""
    try:
        project_root = os.path.dirname(current_app.root_path)
        directory = os.path.join(project_root, current_app.config['UPLOAD_FOLDER'], 'canvas')
        return send_from_directory(directory, filename)
    except FileNotFoundError:
        return jsonify({'error': 'Image not found'}), 404


# SocketIO Events für Canvas

@socketio.on('join_canvas')
def handle_join_canvas(data):
    """Benutzer tritt Canvas bei."""
    from flask_login import current_user
    
    canvas_id = data.get('canvas_id')
    user_data = data.get('user', {})
    
    if not canvas_id:
        return
    
    # Verwende user_data falls current_user nicht verfügbar
    user_id = user_data.get('id') if user_data else None
    user_name = user_data.get('name', 'Unknown') if user_data else 'Unknown'
    user_picture = user_data.get('profilePicture') if user_data else None
    
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
        user_name = current_user.full_name
        user_picture = current_user.profile_picture
    
    if not user_id:
        return
    
    room = f'canvas_{canvas_id}'
    join_room(room)
    
    # Speichere aktiven Benutzer
    if canvas_id not in active_canvas_users:
        active_canvas_users[canvas_id] = {}
    
    active_canvas_users[canvas_id][user_id] = {
        'id': user_id,
        'name': user_name,
        'profilePicture': user_picture
    }
    
    # Sende aktive Benutzer an alle im Raum
    emit('canvas:active_users', {
        'users': list(active_canvas_users[canvas_id].values())
    }, room=room)
    
    # Informiere andere über neuen Benutzer
    emit('canvas:user_joined', {
        'user': {
            'id': user_id,
            'name': user_name,
            'profilePicture': user_picture
        }
    }, room=room, include_self=False)


@socketio.on('leave_canvas')
def handle_leave_canvas(data):
    """Benutzer verlässt Canvas."""
    from flask_login import current_user
    
    canvas_id = data.get('canvas_id')
    
    if not canvas_id:
        return
    
    user_id = None
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
    
    if not user_id:
        return
    
    room = f'canvas_{canvas_id}'
    leave_room(room)
    
    # Entferne Benutzer aus aktiven Benutzern
    if canvas_id in active_canvas_users:
        if user_id in active_canvas_users[canvas_id]:
            del active_canvas_users[canvas_id][user_id]
        
        # Informiere andere über verlassenen Benutzer
        emit('canvas:user_left', {
            'user_id': user_id
        }, room=room)


@socketio.on('canvas:element_added')
def handle_element_added(data):
    """Element wurde hinzugefügt."""
    from flask_login import current_user
    
    canvas_id = data.get('canvas_id')
    element = data.get('element')
    
    if not canvas_id or not element:
        return
    
    user_id = None
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
    
    room = f'canvas_{canvas_id}'
    
    # Broadcast an alle außer Sender
    emit('canvas:element_added', {
        'element': element,
        'user_id': user_id
    }, room=room, include_self=False)


@socketio.on('canvas:element_updated')
def handle_element_updated(data):
    """Element wurde aktualisiert."""
    from flask_login import current_user
    
    canvas_id = data.get('canvas_id')
    element = data.get('element')
    
    if not canvas_id or not element:
        return
    
    user_id = None
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
    
    room = f'canvas_{canvas_id}'
    
    # Broadcast an alle außer Sender
    emit('canvas:element_updated', {
        'element': element,
        'user_id': user_id
    }, room=room, include_self=False)


@socketio.on('canvas:element_deleted')
def handle_element_deleted(data):
    """Element wurde gelöscht."""
    from flask_login import current_user
    
    canvas_id = data.get('canvas_id')
    element_id = data.get('element_id')
    
    if not canvas_id or not element_id:
        return
    
    user_id = None
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
    
    room = f'canvas_{canvas_id}'
    
    # Broadcast an alle außer Sender
    emit('canvas:element_deleted', {
        'element_id': element_id,
        'user_id': user_id
    }, room=room, include_self=False)


@socketio.on('disconnect')
def handle_disconnect():
    """Benutzer trennt Verbindung."""
    from flask_login import current_user
    
    # Entferne Benutzer aus allen aktiven Canvas
    user_id = None
    if hasattr(current_user, 'id') and current_user.is_authenticated:
        user_id = current_user.id
    
    if not user_id:
        return
    
    for canvas_id in list(active_canvas_users.keys()):
        if user_id in active_canvas_users[canvas_id]:
            room = f'canvas_{canvas_id}'
            del active_canvas_users[canvas_id][user_id]
            
            emit('canvas:user_left', {
                'user_id': user_id
            }, room=room)



