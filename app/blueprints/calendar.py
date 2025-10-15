from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.user import User
from datetime import datetime

calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/')
@login_required
def index():
    """Calendar overview."""
    # Get all events
    events = CalendarEvent.query.order_by(CalendarEvent.start_time).all()
    
    # Get user's participation status for each event
    participations = {}
    for event in events:
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        participations[event.id] = participation
    
    return render_template(
        'calendar/index.html',
        events=events,
        participations=participations
    )


@calendar_bp.route('/event/<int:event_id>')
@login_required
def view_event(event_id):
    """View event details."""
    event = CalendarEvent.query.get_or_404(event_id)
    participants = EventParticipant.query.filter_by(event_id=event_id).all()
    
    # Get user's participation status
    user_participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()
    
    return render_template(
        'calendar/view.html',
        event=event,
        participants=participants,
        user_participation=user_participation
    )


@calendar_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_event():
    """Create a new event."""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        location = request.form.get('location', '').strip()
        
        if not all([title, start_time, end_time]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('calendar/create.html')
        
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
            
            if end_dt <= start_dt:
                flash('Das Enddatum muss nach dem Startdatum liegen.', 'danger')
                return render_template('calendar/create.html')
        except ValueError:
            flash('Ungültiges Datums-/Zeitformat.', 'danger')
            return render_template('calendar/create.html')
        
        # Create event
        event = CalendarEvent(
            title=title,
            description=description,
            start_time=start_dt,
            end_time=end_dt,
            location=location,
            created_by=current_user.id
        )
        db.session.add(event)
        db.session.flush()
        
        # Add all active users as participants with "pending" status
        active_users = User.query.filter_by(is_active=True).all()
        for user in active_users:
            participant = EventParticipant(
                event_id=event.id,
                user_id=user.id,
                status='pending'
            )
            db.session.add(participant)
        
        db.session.commit()
        
        flash(f'Termin "{title}" wurde erstellt.', 'success')
        return redirect(url_for('calendar.view_event', event_id=event.id))
    
    return render_template('calendar/create.html')


@calendar_bp.route('/edit/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    """Edit an event."""
    event = CalendarEvent.query.get_or_404(event_id)
    
    if request.method == 'POST':
        event.title = request.form.get('title', '').strip()
        event.description = request.form.get('description', '').strip()
        event.location = request.form.get('location', '').strip()
        
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        
        try:
            event.start_time = datetime.fromisoformat(start_time)
            event.end_time = datetime.fromisoformat(end_time)
            
            if event.end_time <= event.start_time:
                flash('Das Enddatum muss nach dem Startdatum liegen.', 'danger')
                return render_template('calendar/edit.html', event=event)
        except ValueError:
            flash('Ungültiges Datums-/Zeitformat.', 'danger')
            return render_template('calendar/edit.html', event=event)
        
        db.session.commit()
        flash('Termin wurde aktualisiert.', 'success')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    return render_template('calendar/edit.html', event=event)


@calendar_bp.route('/delete/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    """Delete an event (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren können Termine löschen.', 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    event = CalendarEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    
    flash('Termin wurde gelöscht.', 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/participate/<int:event_id>/<status>', methods=['POST'])
@login_required
def set_participation(event_id, status):
    """Set user's participation status for an event."""
    if status not in ['accepted', 'declined']:
        return jsonify({'error': 'Ungültiger Status'}), 400
    
    event = CalendarEvent.query.get_or_404(event_id)
    
    participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()
    
    if not participation:
        participation = EventParticipant(
            event_id=event_id,
            user_id=current_user.id,
            status=status,
            responded_at=datetime.utcnow()
        )
        db.session.add(participation)
    else:
        if participation.status == 'removed':
            flash('Sie wurden von diesem Termin entfernt und können nicht mehr teilnehmen.', 'warning')
            return redirect(url_for('calendar.view_event', event_id=event_id))
        
        participation.status = status
        participation.responded_at = datetime.utcnow()
    
    db.session.commit()
    
    status_text = 'zugesagt' if status == 'accepted' else 'abgesagt'
    flash(f'Sie haben für "{event.title}" {status_text}.', 'success')
    return redirect(url_for('calendar.view_event', event_id=event_id))


@calendar_bp.route('/remove-participant/<int:event_id>/<int:user_id>', methods=['POST'])
@login_required
def remove_participant(event_id, user_id):
    """Remove a user from an event (admin only)."""
    if not current_user.is_admin:
        return jsonify({'error': 'Nicht autorisiert'}), 403
    
    participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=user_id
    ).first_or_404()
    
    participation.status = 'removed'
    db.session.commit()
    
    flash('Teilnehmer wurde entfernt.', 'success')
    return redirect(url_for('calendar.view_event', event_id=event_id))


@calendar_bp.route('/api/events/<int:year>/<int:month>')
@login_required
def get_events_for_month(year, month):
    """Get all events for a specific month."""
    # Get start and end dates for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)
    
    # Get all events in this month
    events = CalendarEvent.query.filter(
        CalendarEvent.start_time >= start_date,
        CalendarEvent.start_time < end_date
    ).order_by(CalendarEvent.start_time).all()
    
    # Get user's participation status for each event
    events_data = []
    for event in events:
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        
        events_data.append({
            'id': event.id,
            'title': event.title,
            'start_time': event.start_time.isoformat(),
            'end_time': event.end_time.isoformat(),
            'location': event.location,
            'description': event.description,
            'day': event.start_time.day,
            'time': event.start_time.strftime('%H:%M'),
            'participation_status': participation.status if participation else None,
            'url': url_for('calendar.view_event', event_id=event.id)
        })
    
        return jsonify(events_data)


@calendar_bp.route('/api/events/range/<start_date>/<end_date>')
@login_required
def get_events_for_range(start_date, end_date):
    """Get all events for a date range."""
    try:
        start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
        # Include the entire end date
        end_datetime = end_datetime.replace(hour=23, minute=59, second=59)
        
        events = CalendarEvent.query.filter(
            CalendarEvent.start_time >= start_datetime,
            CalendarEvent.start_time <= end_datetime
        ).order_by(CalendarEvent.start_time).all()
        
        events_data = []
        for event in events:
            participation = EventParticipant.query.filter_by(
                event_id=event.id,
                user_id=current_user.id
            ).first()
            
            events_data.append({
                'id': event.id,
                'title': event.title,
                'start_time': event.start_time.isoformat(),
                'end_time': event.end_time.isoformat(),
                'location': event.location,
                'description': event.description,
                'day': event.start_time.day,
                'time': event.start_time.strftime('%H:%M'),
                'participation_status': participation.status if participation else None,
                'url': url_for('calendar.view_event', event_id=event.id)
            })
        
        return jsonify(events_data)
    except ValueError as e:
        return jsonify({'error': 'Invalid date format'}), 400



