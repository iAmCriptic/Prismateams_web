from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from app import db
from app.models.calendar import CalendarEvent, EventParticipant, PublicCalendarFeed
from app.models.user import User
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from app.utils.ical import generate_ical_feed, import_events_from_ical
import secrets
import calendar

calendar_bp = Blueprint('calendar', __name__)


def generate_recurring_instances(master_event, start_date, end_date):
    """
    Generiert wiederkehrende Event-Instanzen für einen gegebenen Zeitraum.
    
    Args:
        master_event: Das Master-Event mit Wiederholungsinformationen
        start_date: Startdatum des Zeitraums
        end_date: Enddatum des Zeitraums
    
    Returns:
        Liste von Event-Instanzen (als Dictionary-Repräsentationen)
    """
    instances = []
    current_date = master_event.start_time
    duration = master_event.end_time - master_event.start_time
    sequence = 0
    
    # Enddatum für Wiederholungen bestimmen
    recurrence_end = master_event.recurrence_end_date if master_event.recurrence_end_date else end_date
    recurrence_end = min(recurrence_end, end_date)
    
    # Wenn Startdatum vor dem gewünschten Zeitraum liegt, springe vor
    if current_date < start_date:
        # Berechne wie viele Wiederholungen bis zum Startdatum
        if master_event.recurrence_type == 'daily':
            days_diff = (start_date - current_date).days
            skip_count = days_diff // master_event.recurrence_interval
            current_date += timedelta(days=skip_count * master_event.recurrence_interval)
            sequence = skip_count
        elif master_event.recurrence_type == 'weekly':
            weeks_diff = (start_date - current_date).days // 7
            skip_count = weeks_diff // master_event.recurrence_interval
            current_date += timedelta(weeks=skip_count * master_event.recurrence_interval)
            sequence = skip_count
        elif master_event.recurrence_type == 'monthly':
            # Für monatlich/jährlich verwenden wir relativedelta
            while current_date < start_date and current_date <= recurrence_end:
                if master_event.recurrence_type == 'monthly':
                    current_date += relativedelta(months=master_event.recurrence_interval)
                elif master_event.recurrence_type == 'yearly':
                    current_date += relativedelta(years=master_event.recurrence_interval)
                sequence += 1
    
    while current_date <= recurrence_end and current_date <= end_date:
        # Prüfe ob Instanz im gewünschten Zeitraum liegt
        if current_date >= start_date:
            instance_end = current_date + duration
            
            instance = {
                'id': master_event.id,  # Verwende Master-ID für Instanzen
                'title': master_event.title,
                'description': master_event.description,
                'location': master_event.location,
                'start_time': current_date,
                'end_time': instance_end,
                'is_recurring': True,
                'parent_event_id': master_event.id,
                'recurrence_sequence': sequence,
                'participation_status': None  # Wird später gesetzt
            }
            instances.append(instance)
        
        # Berechne nächsten Termin basierend auf Wiederholungstyp
        if master_event.recurrence_type == 'daily':
            current_date += timedelta(days=master_event.recurrence_interval)
        elif master_event.recurrence_type == 'weekly':
            if master_event.recurrence_days:
                # Spezielle Wochentage
                days = [int(d) for d in master_event.recurrence_days.split(',')]
                # Finde nächsten passenden Wochentag
                current_weekday = current_date.weekday()  # 0=Mo, 6=So
                next_day = None
                for day in sorted(days):
                    if day > current_weekday:
                        next_day = day
                        break
                if next_day is None:
                    # Nächste Woche, erster Tag
                    next_day = min(days)
                    current_date += timedelta(days=7 * master_event.recurrence_interval - (current_weekday - min(days)))
                else:
                    current_date += timedelta(days=next_day - current_weekday)
                # Wenn Intervall > 1, springe Wochen
                if master_event.recurrence_interval > 1:
                    current_date += timedelta(weeks=master_event.recurrence_interval - 1)
            else:
                current_date += timedelta(weeks=master_event.recurrence_interval)
        elif master_event.recurrence_type == 'monthly':
            current_date += relativedelta(months=master_event.recurrence_interval)
        elif master_event.recurrence_type == 'yearly':
            current_date += relativedelta(years=master_event.recurrence_interval)
        else:
            break
        
        sequence += 1
    
    return instances


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
    
    # Get current month for display
    current_month = datetime.now()
    
    return render_template(
        'calendar/index.html',
        events=events,
        participations=participations,
        current_month=current_month
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
        start_date = request.form.get('start_date')
        start_time = request.form.get('start_time')
        end_date = request.form.get('end_date')
        end_time = request.form.get('end_time')
        location = request.form.get('location', '').strip()
        
        # Wiederholungsoptionen
        is_recurring = request.form.get('is_recurring') == 'on'
        recurrence_type = request.form.get('recurrence_type', 'none')
        recurrence_end_date_str = request.form.get('recurrence_end_date')
        recurrence_interval = int(request.form.get('recurrence_interval', 1))
        recurrence_days = request.form.get('recurrence_days', '')  # Komma-getrennte Liste von Wochentagen
        
        if not all([title, start_date, start_time, end_date, end_time]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('calendar/create.html')
        
        try:
            # Kombiniere Datum und Zeit zu datetime-Objekten
            start_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
            
            if end_dt <= start_dt:
                flash('Das Enddatum muss nach dem Startdatum liegen.', 'danger')
                return render_template('calendar/create.html')
            
            # Wiederholungs-Enddatum parsen
            recurrence_end_date = None
            if is_recurring and recurrence_type != 'none' and recurrence_end_date_str:
                try:
                    recurrence_end_date = datetime.fromisoformat(recurrence_end_date_str)
                    if recurrence_end_date < start_dt:
                        flash('Das Wiederholungs-Enddatum muss nach dem Startdatum liegen.', 'danger')
                        return render_template('calendar/create.html')
                except ValueError:
                    flash('Ungültiges Wiederholungs-Enddatum.', 'danger')
                    return render_template('calendar/create.html')
        except ValueError as e:
            flash('Ungültiges Datums-/Zeitformat.', 'danger')
            return render_template('calendar/create.html')
        
        # Create event
        event = CalendarEvent(
            title=title,
            description=description,
            start_time=start_dt,
            end_time=end_dt,
            location=location,
            created_by=current_user.id,
            recurrence_type=recurrence_type if is_recurring else 'none',
            recurrence_end_date=recurrence_end_date,
            recurrence_interval=recurrence_interval,
            recurrence_days=recurrence_days if recurrence_days else None,
            is_recurring_instance=False
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
    
    # Prüfe ob es eine Instanz eines wiederkehrenden Termins ist
    if event.is_recurring_instance and event.parent_event_id:
        flash('Dies ist eine Instanz eines wiederkehrenden Termins. Bearbeiten Sie das Master-Event.', 'warning')
        return redirect(url_for('calendar.view_event', event_id=event.parent_event_id))
    
    if request.method == 'POST':
        event.title = request.form.get('title', '').strip()
        event.description = request.form.get('description', '').strip()
        event.location = request.form.get('location', '').strip()
        
        start_date = request.form.get('start_date')
        start_time = request.form.get('start_time')
        end_date = request.form.get('end_date')
        end_time = request.form.get('end_time')
        
        # Wiederholungsoptionen
        is_recurring = request.form.get('is_recurring') == 'on'
        recurrence_type = request.form.get('recurrence_type', 'none')
        recurrence_end_date_str = request.form.get('recurrence_end_date')
        recurrence_interval = int(request.form.get('recurrence_interval', 1))
        recurrence_days = request.form.get('recurrence_days', '')
        
        if not all([start_date, start_time, end_date, end_time]):
            flash('Bitte füllen Sie alle Pflichtfelder aus.', 'danger')
            return render_template('calendar/edit.html', event=event)
        
        try:
            # Kombiniere Datum und Zeit zu datetime-Objekten
            event.start_time = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            event.end_time = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
            
            if event.end_time <= event.start_time:
                flash('Das Enddatum muss nach dem Startdatum liegen.', 'danger')
                return render_template('calendar/edit.html', event=event)
            
            # Wiederholungs-Enddatum parsen
            recurrence_end_date = None
            if is_recurring and recurrence_type != 'none' and recurrence_end_date_str:
                try:
                    recurrence_end_date = datetime.fromisoformat(recurrence_end_date_str)
                    if recurrence_end_date < event.start_time:
                        flash('Das Wiederholungs-Enddatum muss nach dem Startdatum liegen.', 'danger')
                        return render_template('calendar/edit.html', event=event)
                except ValueError:
                    flash('Ungültiges Wiederholungs-Enddatum.', 'danger')
                    return render_template('calendar/edit.html', event=event)
        except ValueError:
            flash('Ungültiges Datums-/Zeitformat.', 'danger')
            return render_template('calendar/edit.html', event=event)
        
        # Aktualisiere Wiederholungsoptionen
        event.recurrence_type = recurrence_type if is_recurring else 'none'
        event.recurrence_end_date = recurrence_end_date
        event.recurrence_interval = recurrence_interval
        event.recurrence_days = recurrence_days if recurrence_days else None
        
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
    
    # Wenn es ein Master-Event ist, lösche alle Instanzen
    if event.is_master_event:
        # Lösche alle Instanzen (falls welche gespeichert wurden)
        instances = CalendarEvent.query.filter_by(parent_event_id=event.id).all()
        for instance in instances:
            db.session.delete(instance)
    
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
    
    # Get all regular events in this month
    events = CalendarEvent.query.filter(
        CalendarEvent.start_time >= start_date,
        CalendarEvent.start_time < end_date,
        CalendarEvent.is_recurring_instance == False
    ).order_by(CalendarEvent.start_time).all()
    
    # Get all master events that might have instances in this month
    master_events = CalendarEvent.query.filter(
        CalendarEvent.recurrence_type != 'none',
        CalendarEvent.is_recurring_instance == False,
        CalendarEvent.start_time < end_date
    ).all()
    
    # Get user's participation status for each event
    events_data = []
    
    # Add regular events
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
            'is_recurring': False,
            'url': url_for('calendar.view_event', event_id=event.id)
        })
    
    # Generate recurring instances
    for master_event in master_events:
        instances = generate_recurring_instances(master_event, start_date, end_date)
        for instance in instances:
            participation = EventParticipant.query.filter_by(
                event_id=master_event.id,
                user_id=current_user.id
            ).first()
            
            events_data.append({
                'id': master_event.id,
                'title': instance['title'],
                'start_time': instance['start_time'].isoformat(),
                'end_time': instance['end_time'].isoformat(),
                'location': instance['location'],
                'description': instance['description'],
                'day': instance['start_time'].day,
                'time': instance['start_time'].strftime('%H:%M'),
                'participation_status': participation.status if participation else None,
                'is_recurring': True,
                'parent_event_id': master_event.id,
                'url': url_for('calendar.view_event', event_id=master_event.id)
            })
    
    # Sortiere nach Startzeit
    events_data.sort(key=lambda x: x['start_time'])
    
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
        
        # Get all regular events in this range
        events = CalendarEvent.query.filter(
            CalendarEvent.start_time >= start_datetime,
            CalendarEvent.start_time <= end_datetime,
            CalendarEvent.is_recurring_instance == False
        ).order_by(CalendarEvent.start_time).all()
        
        # Get all master events that might have instances in this range
        master_events = CalendarEvent.query.filter(
            CalendarEvent.recurrence_type != 'none',
            CalendarEvent.is_recurring_instance == False,
            CalendarEvent.start_time <= end_datetime
        ).all()
        
        events_data = []
        
        # Add regular events
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
                'is_recurring': False,
                'url': url_for('calendar.view_event', event_id=event.id)
            })
        
        # Generate recurring instances
        for master_event in master_events:
            instances = generate_recurring_instances(master_event, start_datetime, end_datetime)
            for instance in instances:
                participation = EventParticipant.query.filter_by(
                    event_id=master_event.id,
                    user_id=current_user.id
                ).first()
                
                events_data.append({
                    'id': master_event.id,
                    'title': instance['title'],
                    'start_time': instance['start_time'].isoformat(),
                    'end_time': instance['end_time'].isoformat(),
                    'location': instance['location'],
                    'description': instance['description'],
                    'day': instance['start_time'].day,
                    'time': instance['start_time'].strftime('%H:%M'),
                    'participation_status': participation.status if participation else None,
                    'is_recurring': True,
                    'parent_event_id': master_event.id,
                    'url': url_for('calendar.view_event', event_id=master_event.id)
                })
        
        # Sortiere nach Startzeit
        events_data.sort(key=lambda x: x['start_time'])
        
        return jsonify(events_data)
    except ValueError as e:
        return jsonify({'error': 'Invalid date format'}), 400


@calendar_bp.route('/recurring/<int:event_id>/delete-all', methods=['POST'])
@login_required
def delete_recurring_event_all(event_id):
    """Delete master event and all instances (admin only)."""
    if not current_user.is_admin:
        flash('Nur Administratoren können Termine löschen.', 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    event = CalendarEvent.query.get_or_404(event_id)
    
    if not event.is_master_event:
        flash('Dies ist kein wiederkehrender Termin.', 'warning')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    # Lösche alle Instanzen (falls welche gespeichert wurden)
    instances = CalendarEvent.query.filter_by(parent_event_id=event.id).all()
    for instance in instances:
        db.session.delete(instance)
    
    db.session.delete(event)
    db.session.commit()
    
    flash('Wiederkehrender Termin und alle Instanzen wurden gelöscht.', 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/recurring/<int:event_id>/instances')
@login_required
def view_recurring_instances(event_id):
    """View all instances of a recurring event."""
    event = CalendarEvent.query.get_or_404(event_id)
    
    if not event.is_master_event:
        flash('Dies ist kein wiederkehrender Termin.', 'warning')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    # Generiere Instanzen für die nächsten 2 Jahre
    end_date = datetime.now() + relativedelta(years=2)
    instances = generate_recurring_instances(event, event.start_time, end_date)
    
    return render_template(
        'calendar/recurring_instances.html',
        master_event=event,
        instances=instances
    )


# iCal Feed Routes

@calendar_bp.route('/feed/public/<token>.ics')
def public_ical_feed(token):
    """Öffentlicher iCal-Feed (keine Authentifizierung erforderlich)."""
    feed = PublicCalendarFeed.query.filter_by(token=token).first_or_404()
    
    # Hole alle Events für den Feed
    if feed.include_all_events:
        events = CalendarEvent.query.filter(
            CalendarEvent.is_recurring_instance == False
        ).order_by(CalendarEvent.start_time).all()
    else:
        # Hier könnte man später spezifische Events filtern
        events = CalendarEvent.query.filter(
            CalendarEvent.is_recurring_instance == False
        ).order_by(CalendarEvent.start_time).all()
    
    # Aktualisiere last_synced
    feed.last_synced = datetime.utcnow()
    db.session.commit()
    
    # Generiere iCal-String
    feed_name = feed.name or 'Kalender'
    ical_string = generate_ical_feed(events, feed_name)
    
    return Response(
        ical_string,
        mimetype='text/calendar',
        headers={
            'Content-Disposition': f'attachment; filename="{feed_name}.ics"',
            'Content-Type': 'text/calendar; charset=utf-8'
        }
    )


@calendar_bp.route('/feed/create', methods=['GET', 'POST'])
@login_required
def create_feed():
    """Erstellt einen neuen öffentlichen iCal-Feed."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        include_all_events = request.form.get('include_all_events') == 'on'
        
        # Generiere eindeutigen Token
        token = secrets.token_urlsafe(32)
        
        # Stelle sicher, dass Token eindeutig ist
        while PublicCalendarFeed.query.filter_by(token=token).first():
            token = secrets.token_urlsafe(32)
        
        feed = PublicCalendarFeed(
            token=token,
            created_by=current_user.id,
            name=name if name else None,
            include_all_events=include_all_events
        )
        
        db.session.add(feed)
        db.session.commit()
        
        flash('Öffentlicher Kalender wurde erstellt.', 'success')
        return redirect(url_for('calendar.manage_feeds'))
    
    return render_template('calendar/feed_create.html')


@calendar_bp.route('/feed/manage')
@login_required
def manage_feeds():
    """Übersicht aller erstellten Feeds."""
    feeds = PublicCalendarFeed.query.filter_by(created_by=current_user.id).all()
    
    # Generiere vollständige URLs für jeden Feed
    feed_urls = []
    for feed in feeds:
        feed_url = url_for('calendar.public_ical_feed', token=feed.token, _external=True)
        feed_urls.append({
            'feed': feed,
            'url': feed_url
        })
    
    return render_template('calendar/feed_manage.html', feed_urls=feed_urls)


@calendar_bp.route('/feed/delete/<int:feed_id>', methods=['POST'])
@login_required
def delete_feed(feed_id):
    """Löscht einen Feed."""
    feed = PublicCalendarFeed.query.get_or_404(feed_id)
    
    # Prüfe ob Benutzer der Ersteller ist
    if feed.created_by != current_user.id and not current_user.is_admin:
        flash('Sie haben keine Berechtigung, diesen Feed zu löschen.', 'danger')
        return redirect(url_for('calendar.manage_feeds'))
    
    db.session.delete(feed)
    db.session.commit()
    
    flash('Feed wurde gelöscht.', 'success')
    return redirect(url_for('calendar.manage_feeds'))


@calendar_bp.route('/export')
@login_required
def export_calendar():
    """Exportiert alle Events des Benutzers als iCal-Datei."""
    # Hole alle Events
    events = CalendarEvent.query.filter(
        CalendarEvent.is_recurring_instance == False
    ).order_by(CalendarEvent.start_time).all()
    
    ical_string = generate_ical_feed(events, 'Mein Kalender')
    
    return Response(
        ical_string,
        mimetype='text/calendar',
        headers={
            'Content-Disposition': 'attachment; filename="kalender.ics"',
            'Content-Type': 'text/calendar; charset=utf-8'
        }
    )


@calendar_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_calendar():
    """Importiert Events aus einer iCal-Datei."""
    if request.method == 'POST':
        if 'ical_file' not in request.files:
            flash('Bitte wählen Sie eine Datei aus.', 'danger')
            return render_template('calendar/import.html')
        
        file = request.files['ical_file']
        if file.filename == '':
            flash('Bitte wählen Sie eine Datei aus.', 'danger')
            return render_template('calendar/import.html')
        
        if not file.filename.endswith('.ics'):
            flash('Bitte wählen Sie eine .ics-Datei aus.', 'danger')
            return render_template('calendar/import.html')
        
        try:
            ical_data = file.read().decode('utf-8')
            imported_events = import_events_from_ical(ical_data, current_user.id)
            
            # Speichere Events
            count = 0
            for event in imported_events:
                # Prüfe auf Duplikate (optional)
                existing = CalendarEvent.query.filter_by(
                    title=event.title,
                    start_time=event.start_time,
                    created_by=current_user.id
                ).first()
                
                if not existing:
                    db.session.add(event)
                    count += 1
            
            db.session.commit()
            
            flash(f'{count} Termine wurden erfolgreich importiert.', 'success')
            return redirect(url_for('calendar.index'))
        except Exception as e:
            flash(f'Fehler beim Importieren: {str(e)}', 'danger')
            return render_template('calendar/import.html')
    
    return render_template('calendar/import.html')



