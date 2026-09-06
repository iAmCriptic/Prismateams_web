"""Calendar pages, event CRUD, participation, and event APIs."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, current_app
from flask_login import login_required, current_user
from app import db
from app.models.calendar import Calendar, CalendarEvent, EventParticipant, PublicCalendarFeed, CalendarSyncSource
from app.models.user import User
from app.models.booking import BookingRequest
from app.utils.access_control import check_module_access
from app.utils.common import portal_now_naive
from app.utils.dashboard_events import emit_dashboard_update_multiple
from app.utils.i18n import translate
from app.utils.multi_calendars import (
    calendar_display_name,
    calendar_to_dict,
    can_create_in_calendar,
    can_delete_event,
    can_edit_event,
    create_extra_calendar,
    default_calendar_for_user,
    delete_extra_calendar,
    display_color_for_event,
    ensure_imported_calendar_for_source,
    events_query_for_calendars,
    filter_events_for_calendars,
    get_or_create_events_calendar,
    get_or_create_personal_calendar,
    get_public_calendar,
    is_calendar_export_enabled,
    is_calendar_import_enabled,
    is_calendar_multi_enabled,
    is_calendar_personal_enabled,
    is_calendar_team_enabled,
    list_sidebar_calendars,
    list_writable_calendars,
    parse_calendar_ids_param,
    participations_for_user,
    update_calendar_meta,
    user_calendar_team_ids,
)
from app.utils.ical import (
    generate_ical_feed,
    import_events_from_ical,
    normalize_ical_url,
    sync_calendar_source,
)
from sqlalchemy import or_
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging
import threading
import secrets
import calendar

from app.blueprints.calendar._bp import DEFAULT_EVENT_COLOR, calendar_bp, logger
from app.blueprints.calendar.helpers import *  # noqa: F401,F403

@calendar_bp.route('/')
@login_required
@check_module_access('module_calendar')
def index():
    """Calendar overview (list view: ±1 year window, batched participations)."""
    ctx = _sidebar_context(current_user)
    selected_ids = ctx['selected_calendar_ids']
    multi = ctx['calendar_multi_enabled']

    now = portal_now_naive()
    window_start = now - relativedelta(years=1)
    window_end = now + relativedelta(years=1)
    date_window = [
        CalendarEvent.start_time >= window_start,
        CalendarEvent.start_time <= window_end,
    ]

    if multi:
        q = events_query_for_calendars(
            current_user,
            selected_ids,
            base_filters=[CalendarEvent.is_recurring_instance == False, *date_window],
        )
        events = q.order_by(CalendarEvent.start_time).all()
    else:
        events = (
            CalendarEvent.query.filter(*date_window)
            .order_by(CalendarEvent.start_time)
            .all()
        )

    event_ids = [event.id for event in events]
    participations = participations_for_user(event_ids, current_user.id)

    return render_template(
        'calendar/index.html',
        events=events,
        participations=participations,
        display_color_for_event=display_color_for_event,
        **ctx,
    )


@calendar_bp.route('/event/<int:event_id>')
@login_required
@check_module_access('module_calendar')
def view_event(event_id):
    """View event details."""
    event = CalendarEvent.query.get_or_404(event_id)
    participants = EventParticipant.query.filter_by(event_id=event_id).all()
    
    # Get user's participation status
    user_participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=current_user.id
    ).first()
    
    # Lade Buchungsanfrage falls vorhanden
    booking_request = event.booking_request_obj if hasattr(event, 'booking_request_obj') else None
    if not booking_request and event.booking_request_id:
        from app.models.booking import BookingRequest
        booking_request = BookingRequest.query.get(event.booking_request_id)

    try:
        from app.utils.notifications import mark_in_app_notifications_read
        mark_in_app_notifications_read(
            current_user.id,
            notification_types=['calendar', 'calendar_invite'],
            source_id=event_id,
            commit=True,
        )
    except Exception:
        pass
    
    return render_template(
        'calendar/view.html',
        event=event,
        participants=participants,
        user_participation=user_participation,
        booking_request=booking_request,
        can_edit=can_edit_event(current_user, event),
        can_delete=can_delete_event(current_user, event),
        calendar_display_name=calendar_display_name(event.calendar, current_user),
        **_page_shell_context(),
    )


@calendar_bp.route('/create', methods=['GET', 'POST'])
@login_required
@check_module_access('module_calendar')
def create_event():
    """Create a new event."""
    multi = is_calendar_multi_enabled()
    invite_users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all() if multi else []
    writable = []
    default_calendar_id = None
    personal_calendar_id = None
    public_calendar_id = None
    if multi:
        writable = list_writable_calendars(current_user)
        default = default_calendar_for_user(current_user)
        public = get_public_calendar()
        personal = get_or_create_personal_calendar(current_user) if is_calendar_personal_enabled() else None
        personal_calendar_id = personal.id if personal else None
        public_calendar_id = public.id
        writable_ids = {c.id for c in writable}
        focus = request.args.get('calendar_id', type=int) or request.form.get('calendar_id', type=int)
        if focus in writable_ids:
            default_calendar_id = focus
        else:
            default_calendar_id = default.id if default else public.id

    def _create_template(**extra):
        invite_payload = [
            {'id': u.id, 'name': u.full_name}
            for u in invite_users
            if u.id != current_user.id
        ]
        return render_template(
            'calendar/create.html',
            invite_users=invite_users,
            invite_users_json=invite_payload,
            writable_calendars=[calendar_to_dict(c, current_user) for c in writable],
            default_calendar_id=default_calendar_id,
            personal_calendar_id=personal_calendar_id,
            public_calendar_id=public_calendar_id,
            **_page_shell_context(),
            **extra,
        )

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        start_date = request.form.get('start_date')
        start_time = request.form.get('start_time')
        end_date = request.form.get('end_date')
        end_time = request.form.get('end_time')
        location = request.form.get('location', '').strip()
        event_color = sanitize_event_color(request.form.get('event_color'))

        is_recurring = request.form.get('is_recurring') == 'on'
        recurrence_type = request.form.get('recurrence_type', 'none')
        recurrence_end_date_str = request.form.get('recurrence_end_date')
        recurrence_interval = int(request.form.get('recurrence_interval', 1))
        recurrence_days = request.form.get('recurrence_days', '')

        if not all([title, start_date, end_date]):
            flash(translate('calendar.flash.fill_all_fields'), 'danger')
            return _create_template()

        try:
            if not start_time:
                start_time = '00:00'
            if not end_time:
                end_time = '23:59'

            start_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")

            if end_dt <= start_dt:
                flash(translate('calendar.flash.end_after_start'), 'danger')
                return _create_template()

            recurrence_end_date = None
            if is_recurring and recurrence_type != 'none' and recurrence_end_date_str:
                try:
                    recurrence_end_date = datetime.fromisoformat(recurrence_end_date_str)
                    if recurrence_end_date < start_dt:
                        flash(translate('calendar.flash.recurrence_end_after_start'), 'danger')
                        return _create_template()
                except ValueError:
                    flash(translate('calendar.flash.invalid_recurrence_end'), 'danger')
                    return _create_template()
        except ValueError:
            flash(translate('calendar.flash.invalid_datetime_format'), 'danger')
            return _create_template()

        calendar_id = None
        target_calendar = None
        if multi:
            calendar_id = request.form.get('calendar_id', type=int) or default_calendar_id
            target_calendar = Calendar.query.get(calendar_id)
            if not target_calendar or not can_create_in_calendar(current_user, target_calendar):
                flash(translate('calendar.flash.no_create_permission'), 'danger')
                return _create_template()
            calendar_id = target_calendar.id
            if not event_color or event_color == DEFAULT_EVENT_COLOR:
                event_color = target_calendar.color or event_color

        event = CalendarEvent(
            title=title,
            description=description,
            start_time=start_dt,
            end_time=end_dt,
            location=location,
            event_color=event_color,
            created_by=current_user.id,
            calendar_id=calendar_id,
            recurrence_type=recurrence_type if is_recurring else 'none',
            recurrence_end_date=recurrence_end_date,
            recurrence_interval=recurrence_interval,
            recurrence_days=recurrence_days if recurrence_days else None,
            is_recurring_instance=False
        )
        db.session.add(event)
        db.session.flush()

        invitee_ids = []
        if multi and target_calendar and target_calendar.calendar_type == 'personal':
            invitee_ids = _parse_invitee_ids()
        notify_ids = _add_participants_for_event(event, multi, invitee_ids)
        db.session.commit()

        if multi and notify_ids:
            _notify_event_invites(event, notify_ids)

        try:
            from app.utils.dashboard_events import emit_dashboard_update
            now = portal_now_naive()
            week_from_now = now + timedelta(days=7)
            upcoming_count = CalendarEvent.query.filter(
                CalendarEvent.start_time > now,
                CalendarEvent.start_time <= week_from_now
            ).count()
            targets = set(invitee_ids) | {current_user.id}
            if not multi:
                targets = {u.id for u in User.query.filter_by(is_active=True).all()}
            for uid in targets:
                emit_dashboard_update(uid, 'calendar_update', {'count': upcoming_count})
        except Exception as e:
            import logging
            logging.error(f"Fehler beim Senden der Dashboard-Updates fuer Kalender: {e}")

        flash(f'Termin "{title}" wurde erstellt.', 'success')
        return redirect(url_for('calendar.view_event', event_id=event.id))

    return _create_template()


@calendar_bp.route('/edit/<int:event_id>', methods=['GET', 'POST'])
@login_required
@check_module_access('module_calendar')
def edit_event(event_id):
    """Edit an event."""
    event = CalendarEvent.query.get_or_404(event_id)

    if not can_edit_event(current_user, event):
        flash(translate('calendar.flash.no_edit_permission'), 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))

    if event.is_recurring_instance and event.parent_event_id:
        flash(translate('calendar.flash.instance_edit_warning'), 'warning')
        return redirect(url_for('calendar.view_event', event_id=event.parent_event_id))

    multi = is_calendar_multi_enabled()
    invite_users = User.query.filter_by(is_active=True).order_by(User.first_name, User.last_name).all() if multi else []

    def _edit_template(**extra):
        return render_template(
            'calendar/edit.html',
            event=event,
            invite_users=invite_users,
            invite_users_json=[
                {'id': u.id, 'name': u.full_name}
                for u in invite_users
                if u.id != current_user.id
            ],
            existing_invitee_ids=[
                p.user_id for p in EventParticipant.query.filter_by(event_id=event.id).all()
                if p.user_id != current_user.id and p.status in ('pending', 'accepted')
            ],
            show_invitees=bool(
                multi and event.calendar and event.calendar.calendar_type == 'personal'
            ),
            **_page_shell_context(),
            **extra,
        )

    if request.method == 'POST':
        event.title = request.form.get('title', '').strip()
        event.description = request.form.get('description', '').strip()
        event.location = request.form.get('location', '').strip()
        event.event_color = sanitize_event_color(request.form.get('event_color'))

        start_date = request.form.get('start_date')
        start_time = request.form.get('start_time')
        end_date = request.form.get('end_date')
        end_time = request.form.get('end_time')

        is_recurring = request.form.get('is_recurring') == 'on'
        recurrence_type = request.form.get('recurrence_type', 'none')
        recurrence_end_date_str = request.form.get('recurrence_end_date')
        recurrence_interval = int(request.form.get('recurrence_interval', 1))
        recurrence_days = request.form.get('recurrence_days', '')

        if not all([start_date, end_date]):
            flash(translate('calendar.flash.fill_all_fields'), 'danger')
            return _edit_template()

        try:
            if not start_time:
                start_time = '00:00'
            if not end_time:
                end_time = '23:59'

            event.start_time = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            event.end_time = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")

            if event.end_time <= event.start_time:
                flash(translate('calendar.flash.end_after_start'), 'danger')
                return _edit_template()

            recurrence_end_date = None
            if is_recurring and recurrence_type != 'none' and recurrence_end_date_str:
                try:
                    recurrence_end_date = datetime.fromisoformat(recurrence_end_date_str)
                    if recurrence_end_date < event.start_time:
                        flash(translate('calendar.flash.recurrence_end_after_start'), 'danger')
                        return _edit_template()
                except ValueError:
                    flash(translate('calendar.flash.invalid_recurrence_end'), 'danger')
                    return _edit_template()
        except ValueError:
            flash(translate('calendar.flash.invalid_datetime_format'), 'danger')
            return _edit_template()

        event.recurrence_type = recurrence_type if is_recurring else 'none'
        event.recurrence_end_date = recurrence_end_date
        event.recurrence_interval = recurrence_interval
        event.recurrence_days = recurrence_days if recurrence_days else None

        new_invite_ids = []
        if multi:
            existing = {p.user_id: p for p in EventParticipant.query.filter_by(event_id=event.id).all()}
            for uid in _parse_invitee_ids():
                if uid == event.created_by:
                    continue
                if uid not in existing:
                    user = User.query.filter_by(id=uid, is_active=True).first()
                    if user:
                        db.session.add(EventParticipant(event_id=event.id, user_id=uid, status='pending'))
                        new_invite_ids.append(uid)

        db.session.commit()
        if new_invite_ids:
            _notify_event_invites(event, new_invite_ids)

        try:
            from app.utils.dashboard_events import emit_dashboard_update
            now = portal_now_naive()
            week_from_now = now + timedelta(days=7)
            upcoming_count = CalendarEvent.query.filter(
                CalendarEvent.start_time > now,
                CalendarEvent.start_time <= week_from_now
            ).count()
            participants = EventParticipant.query.filter_by(event_id=event_id).all()
            for participant in participants:
                emit_dashboard_update(participant.user_id, 'calendar_update', {'count': upcoming_count})
        except Exception as e:
            import logging
            logging.error(f"Fehler beim Senden der Dashboard-Updates fuer Kalender: {e}")

        flash(translate('calendar.flash.updated'), 'success')
        return redirect(url_for('calendar.view_event', event_id=event_id))

    return _edit_template()


@calendar_bp.route('/delete/<int:event_id>', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def delete_event(event_id):
    """Delete an event."""
    event = CalendarEvent.query.get_or_404(event_id)

    if not can_delete_event(current_user, event):
        flash(translate('calendar.flash.admin_only_delete'), 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    # Entferne die Verknüpfung zu BookingRequests, bevor das Event gelöscht wird
    booking_requests = BookingRequest.query.filter_by(calendar_event_id=event.id).all()
    for booking_request in booking_requests:
        booking_request.calendar_event_id = None
    
    # Wenn es ein Master-Event ist, lösche alle Instanzen
    if event.is_master_event:
        # Lösche alle Instanzen (falls welche gespeichert wurden)
        instances = CalendarEvent.query.filter_by(parent_event_id=event.id).all()
        for instance in instances:
            # Auch für Instanzen die BookingRequest-Verknüpfungen entfernen
            instance_booking_requests = BookingRequest.query.filter_by(calendar_event_id=instance.id).all()
            for booking_request in instance_booking_requests:
                booking_request.calendar_event_id = None
            db.session.delete(instance)
    
    # Hole Teilnehmer-IDs vor dem Löschen
    participant_ids = [p.user_id for p in EventParticipant.query.filter_by(event_id=event_id).all()]
    
    db.session.delete(event)
    db.session.commit()
    
    # Sende Dashboard-Updates an alle Event-Teilnehmer
    try:
        from app.utils.dashboard_events import emit_dashboard_update
        
        # Berechne upcoming_count
        now = portal_now_naive()
        week_from_now = now + timedelta(days=7)
        upcoming_count = CalendarEvent.query.filter(
            CalendarEvent.start_time > now,
            CalendarEvent.start_time <= week_from_now
        ).count()
        
        # Emittiere Update für alle ehemaligen Event-Teilnehmer
        for user_id in participant_ids:
            emit_dashboard_update(user_id, 'calendar_update', {'count': upcoming_count})
    except Exception as e:
        import logging
        logging.error(f"Fehler beim Senden der Dashboard-Updates für Kalender: {e}")
    
    flash(translate('calendar.flash.deleted'), 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/participate/<int:event_id>/<status>', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def set_participation(event_id, status):
    """Set user's participation status for an event."""
    if status not in ['accepted', 'declined']:
        return jsonify({'error': translate('calendar.errors.invalid_status')}), 400
    
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
            flash(translate('calendar.flash.removed_from_event'), 'warning')
            return redirect(url_for('calendar.view_event', event_id=event_id))
        
        participation.status = status
        participation.responded_at = datetime.utcnow()
    
    db.session.commit()
    
    status_text = translate('calendar.flash.accepted') if status == 'accepted' else translate('calendar.flash.declined')
    flash(translate('calendar.flash.participation_status', event_title=event.title, status=status_text), 'success')
    return redirect(url_for('calendar.view_event', event_id=event_id))


@calendar_bp.route('/remove-participant/<int:event_id>/<int:user_id>', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def remove_participant(event_id, user_id):
    """Remove a user from an event (admin only)."""
    if not current_user.is_admin:
        return jsonify({'error': translate('calendar.errors.unauthorized')}), 403
    
    # Prüfe ob der zu entfernende Benutzer ein Administrator ist
    user_to_remove = User.query.get_or_404(user_id)
    if user_to_remove.is_admin:
        flash(translate('calendar.flash.admin_cannot_remove'), 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    participation = EventParticipant.query.filter_by(
        event_id=event_id,
        user_id=user_id
    ).first_or_404()
    
    participation.status = 'removed'
    db.session.commit()
    
    flash(translate('calendar.flash.participant_removed'), 'success')
    return redirect(url_for('calendar.view_event', event_id=event_id))


@calendar_bp.route('/api/events/<int:year>/<int:month>')
@login_required
@check_module_access('module_calendar')
def get_events_for_month(year, month):
    """Get all events for a specific month."""
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    selected_ids = _selected_calendar_ids_from_request(current_user)
    multi = is_calendar_multi_enabled()

    base = [
        CalendarEvent.start_time < end_date,
        CalendarEvent.end_time > start_date,
        CalendarEvent.is_recurring_instance == False,
    ]
    if multi:
        events = events_query_for_calendars(current_user, selected_ids, base).order_by(CalendarEvent.start_time).all()
        master_q = events_query_for_calendars(
            current_user,
            selected_ids,
            [
                CalendarEvent.recurrence_type != 'none',
                CalendarEvent.is_recurring_instance == False,
                CalendarEvent.start_time < end_date,
                or_(
                    CalendarEvent.recurrence_end_date.is_(None),
                    CalendarEvent.recurrence_end_date >= start_date,
                ),
            ],
        )
        master_events = master_q.all()
    else:
        events = CalendarEvent.query.filter(*base).order_by(CalendarEvent.start_time).all()
        master_events = CalendarEvent.query.filter(
            CalendarEvent.recurrence_type != 'none',
            CalendarEvent.is_recurring_instance == False,
            CalendarEvent.start_time < end_date,
            or_(
                CalendarEvent.recurrence_end_date.is_(None),
                CalendarEvent.recurrence_end_date >= start_date
            )
        ).all()

    participations = participations_for_user(
        [event.id for event in events] + [master.id for master in master_events],
        current_user.id,
    )
    events_data = []

    for event in events:
        if event.recurrence_type != 'none':
            continue
        events_data.append(event_to_api_dict(
            event,
            _participation_status(participations, event.id),
        ))

    for master_event in master_events:
        status = _participation_status(participations, master_event.id)
        for instance in generate_recurring_instances(master_event, start_date, end_date):
            events_data.append(_recurring_instance_api_dict(master_event, instance, status))
    
    events_data.sort(key=lambda x: x['start_time'])
    return jsonify(events_data)


@calendar_bp.route('/api/events/search')
@login_required
@check_module_access('module_calendar')
def search_events():
    """Search events by title, location, or description."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify([])

    like = f'%{q}%'
    selected_ids = _selected_calendar_ids_from_request(current_user)
    multi = is_calendar_multi_enabled()
    text_filter = or_(
        CalendarEvent.title.ilike(like),
        CalendarEvent.location.ilike(like),
        CalendarEvent.description.ilike(like),
    )
    base = [
        CalendarEvent.is_recurring_instance == False,
        text_filter,
    ]
    if multi:
        events = (
            events_query_for_calendars(current_user, selected_ids, base)
            .order_by(CalendarEvent.start_time.desc())
            .limit(25)
            .all()
        )
    else:
        events = (
            CalendarEvent.query.filter(*base)
            .order_by(CalendarEvent.start_time.desc())
            .limit(25)
            .all()
        )

    participations = participations_for_user(
        [event.id for event in events],
        current_user.id,
    )
    events_data = []
    for event in events:
        events_data.append(event_to_api_dict(
            event,
            _participation_status(participations, event.id),
        ))
    return jsonify(events_data)


@calendar_bp.route('/api/events/range/<start_date>/<end_date>')
@login_required
@check_module_access('module_calendar')
def get_events_for_range(start_date, end_date):
    """Get all events for a date range."""
    try:
        start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
        end_datetime = end_datetime.replace(hour=23, minute=59, second=59)

        selected_ids = _selected_calendar_ids_from_request(current_user)
        multi = is_calendar_multi_enabled()
        base = [
            CalendarEvent.start_time <= end_datetime,
            CalendarEvent.end_time >= start_datetime,
            CalendarEvent.is_recurring_instance == False,
        ]
        if multi:
            events = events_query_for_calendars(current_user, selected_ids, base).order_by(CalendarEvent.start_time).all()
            master_events = events_query_for_calendars(
                current_user,
                selected_ids,
                [
                    CalendarEvent.recurrence_type != 'none',
                    CalendarEvent.is_recurring_instance == False,
                    CalendarEvent.start_time <= end_datetime,
                    or_(
                        CalendarEvent.recurrence_end_date.is_(None),
                        CalendarEvent.recurrence_end_date >= start_datetime,
                    ),
                ],
            ).all()
        else:
            events = CalendarEvent.query.filter(*base).order_by(CalendarEvent.start_time).all()
            master_events = CalendarEvent.query.filter(
                CalendarEvent.recurrence_type != 'none',
                CalendarEvent.is_recurring_instance == False,
                CalendarEvent.start_time <= end_datetime,
                or_(
                    CalendarEvent.recurrence_end_date.is_(None),
                    CalendarEvent.recurrence_end_date >= start_datetime
                )
            ).all()

        participations = participations_for_user(
            [event.id for event in events] + [master.id for master in master_events],
            current_user.id,
        )
        events_data = []
        for event in events:
            if event.recurrence_type != 'none':
                continue
            events_data.append(event_to_api_dict(
                event,
                _participation_status(participations, event.id),
            ))

        for master_event in master_events:
            status = _participation_status(participations, master_event.id)
            for instance in generate_recurring_instances(master_event, start_datetime, end_datetime):
                events_data.append(_recurring_instance_api_dict(master_event, instance, status))

        events_data.sort(key=lambda x: x['start_time'])
        return jsonify(events_data)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400


@calendar_bp.route('/recurring/<int:event_id>/delete-all', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def delete_recurring_event_all(event_id):
    """Delete master event and all instances."""
    event = CalendarEvent.query.get_or_404(event_id)
    if not can_delete_event(current_user, event):
        flash(translate('calendar.flash.admin_only_delete'), 'danger')
        return redirect(url_for('calendar.view_event', event_id=event_id))

    
    if not event.is_master_event:
        flash(translate('calendar.flash.not_recurring'), 'warning')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    # Lösche alle Instanzen (falls welche gespeichert wurden)
    instances = CalendarEvent.query.filter_by(parent_event_id=event.id).all()
    for instance in instances:
        db.session.delete(instance)
    
    db.session.delete(event)
    db.session.commit()
    
    flash(translate('calendar.flash.recurring_deleted'), 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/recurring/<int:event_id>/instances')
@login_required
@check_module_access('module_calendar')
def view_recurring_instances(event_id):
    """View all instances of a recurring event."""
    event = CalendarEvent.query.get_or_404(event_id)
    
    if not event.is_master_event:
        flash(translate('calendar.flash.not_recurring'), 'warning')
        return redirect(url_for('calendar.view_event', event_id=event_id))
    
    # Generiere Instanzen für die nächsten 2 Jahre
    end_date = datetime.now() + relativedelta(years=2)
    instances = generate_recurring_instances(event, event.start_time, end_date)
    
    return render_template(
        'calendar/recurring_instances.html',
        master_event=event,
        instances=instances
    )
