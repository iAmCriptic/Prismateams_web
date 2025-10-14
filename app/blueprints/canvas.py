from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.canvas import Canvas, CanvasTextField

canvas_bp = Blueprint('canvas', __name__)


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
            flash('Bitte geben Sie einen Namen ein.', 'danger')
            return render_template('canvas/create.html')
        
        canvas = Canvas(
            name=name,
            description=description,
            created_by=current_user.id
        )
        
        db.session.add(canvas)
        db.session.commit()
        
        flash(f'Canvas "{name}" wurde erstellt.', 'success')
        return redirect(url_for('canvas.edit', canvas_id=canvas.id))
    
    return render_template('canvas/create.html')


@canvas_bp.route('/edit/<int:canvas_id>')
@login_required
def edit(canvas_id):
    """Edit a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    text_fields = CanvasTextField.query.filter_by(canvas_id=canvas_id).all()
    
    return render_template('canvas/edit.html', canvas=canvas_obj, text_fields=text_fields)


@canvas_bp.route('/delete/<int:canvas_id>', methods=['POST'])
@login_required
def delete(canvas_id):
    """Delete a canvas."""
    canvas_obj = Canvas.query.get_or_404(canvas_id)
    
    db.session.delete(canvas_obj)
    db.session.commit()
    
    flash(f'Canvas "{canvas_obj.name}" wurde gelöscht.', 'success')
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



