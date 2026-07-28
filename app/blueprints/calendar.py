from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
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
    list_sidebar_calendars,
    parse_calendar_ids_param,
)
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from app.utils.ical import (
    generate_ical_feed,
    import_events_from_ical,
    normalize_ical_url,
    sync_calendar_source,
)
from sqlalchemy import or_
import secrets
import calendar

calendar_bp = Blueprint('calendar', __name__)
DEFAULT_EVENT_COLOR = '#0d6efd'


def sanitize_event_color(raw_color):
    """Validiert einen Hex-Farbwert und liefert eine sichere Standardfarbe."""
    if not raw_color:
        return DEFAULT_EVENT_COLOR
    color = raw_color.strip().lower()
    if len(color) == 7 and color.startswith('#') and all(c in '0123456789abcdef' for c in color[1:]):
        return color
    return DEFAULT_EVENT_COLOR


def _selected_calendar_ids_from_request(user):
    """Parse ?calendars= from query; default = personal only when multi on."""
    multi = is_calendar_multi_enabled()
    if not multi:
        return []
    personal = get_or_create_personal_calendar(user)
    raw = request.args.get('calendars')
    ids = parse_calendar_ids_param(raw, default_ids=[personal.id])
    if not ids:
        ids = [personal.id]
    return ids


def _sidebar_context(user, selected_ids=None):
    multi = is_calendar_multi_enabled()
    if not multi:
        return {
            'calendar_multi_enabled': False,
            'calendar_export_enabled': is_calendar_export_enabled(),
            'calendar_import_enabled': is_calendar_import_enabled(),
            'sidebar_calendars': None,
            'selected_calendar_ids': [],
            'focus_calendar_id': None,
            'can_create_focus': True,
        }
    sidebar = list_sidebar_calendars(user)
    if selected_ids is None:
        selected_ids = _selected_calendar_ids_from_request(user)
    personal = sidebar['personal']
    focus_raw = request.args.get('focus', type=int)
    focus_id = focus_raw or (selected_ids[0] if selected_ids else personal.id)
    focus_cal = Calendar.query.get(focus_id) or personal
    return {
        'calendar_multi_enabled': True,
        'calendar_export_enabled': is_calendar_export_enabled(),
        'calendar_import_enabled': is_calendar_import_enabled(),
        'sidebar_calendars': {
            'personal': calendar_to_dict(sidebar['personal'], user),
            'public': calendar_to_dict(sidebar['public'], user),
            'events': calendar_to_dict(sidebar['events'], user),
            'others': [calendar_to_dict(c, user) for c in sidebar['others']],
        },
        'selected_calendar_ids': selected_ids,
        'focus_calendar_id': focus_cal.id,
        'can_create_focus': can_create_in_calendar(user, focus_cal),
    }


def _page_shell_context(user=None):
    """Sidebar context for create/edit/view pages (non-interactive list)."""
    return _sidebar_context(user or current_user)


def _notify_event_invites(event, invitee_ids):
    from app.models.user import User
    from app.utils.access_control import has_module_access
    from app.utils.notifications import get_or_create_notification_settings, notify_user
    for uid in invitee_ids:
        if uid == event.created_by:
            continue
        try:
            user = User.query.get(uid)
            if not user:
                continue
            if not has_module_access(user, 'module_calendar'):
                continue
            settings = get_or_create_notification_settings(uid)
            if not settings.calendar_notifications_enabled:
                continue
            notify_user(
                uid,
                title=translate('calendar.notifications.invite_title', language=user.language),
                body=translate('calendar.notifications.invite_body', language=user.language, title=event.title),
                url=url_for('calendar.view_event', event_id=event.id, _external=False),
                notification_type='calendar_invite',
                dedup_key=f'calendar_invite:{event.id}:{uid}',
                source_id=event.id,
                data={'event_id': event.id, 'type': 'calendar_invite'},
            )
        except Exception:
            import logging
            logging.exception('Invite notification failed for user %s event %s', uid, event.id)


def _parse_invitee_ids():
    raw = request.form.getlist('invitee_ids')
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _add_participants_for_event(event, multi_mode, invitee_ids=None):
    """Legacy: all users pending. Multi: creator accepted + selected invitees pending."""
    if multi_mode:
        db.session.add(EventParticipant(
            event_id=event.id,
            user_id=event.created_by,
            status='accepted',
            responded_at=datetime.utcnow(),
        ))
        notify_ids = []
        for uid in (invitee_ids or []):
            if uid == event.created_by:
                continue
            user = User.query.filter_by(id=uid, is_active=True).first()
            if not user:
                continue
            db.session.add(EventParticipant(
                event_id=event.id,
                user_id=uid,
                status='pending',
            ))
            notify_ids.append(uid)
        return notify_ids

    active_users = User.query.filter_by(is_active=True).all()
    for user in active_users:
        db.session.add(EventParticipant(
            event_id=event.id,
            user_id=user.id,
            status='pending',
        ))
    return []


def event_to_api_dict(event, participation_status=None, extra=None, user=None):
    duration = (event.end_time.date() - event.start_time.date()).days + 1
    is_all_day = (
        event.start_time.strftime('%H:%M') == '00:00'
        and event.end_time.strftime('%H:%M') == '23:59'
    )
    viewer = user if user is not None else current_user
    display_color = display_color_for_event(event, viewer)
    data = {
        'id': event.id,
        'title': event.title,
        'start_time': event.start_time.isoformat(),
        'end_time': event.end_time.isoformat(),
        'start_date': event.start_time.date().isoformat(),
        'end_date': event.end_time.date().isoformat(),
        'duration_days': duration,
        'is_all_day': is_all_day,
        'location': event.location,
        'event_color': event.event_color or DEFAULT_EVENT_COLOR,
        'display_color': display_color,
        'description': event.description,
        'day': event.start_time.day,
        'time': None if is_all_day else event.start_time.strftime('%H:%M'),
        'participation_status': participation_status,
        'is_recurring': False,
        'calendar_id': event.calendar_id,
        'url': url_for('calendar.view_event', event_id=event.id),
    }
    if event.calendar:
        data['calendar_color'] = event.calendar.color or data['event_color']
        data['calendar_name'] = calendar_display_name(event.calendar, viewer)
        data['calendar_type'] = event.calendar.calendar_type
        data['calendar_owner_id'] = event.calendar.owner_id
    else:
        data['calendar_type'] = None
        data['calendar_owner_id'] = None
        data['calendar_name'] = None
    if extra:
        data.update(extra)
    return data


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
                'event_color': master_event.event_color or DEFAULT_EVENT_COLOR,
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
@check_module_access('module_calendar')
def index():
    """Calendar overview."""
    ctx = _sidebar_context(current_user)
    selected_ids = ctx['selected_calendar_ids']
    multi = ctx['calendar_multi_enabled']

    if multi:
        q = events_query_for_calendars(
            current_user,
            selected_ids,
            base_filters=[CalendarEvent.is_recurring_instance == False],
        )
        events = q.order_by(CalendarEvent.start_time).all()
    else:
        events = CalendarEvent.query.order_by(CalendarEvent.start_time).all()

    participations = {}
    for event in events:
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        if participation:
            participations[event.id] = participation

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
        personal = get_or_create_personal_calendar(current_user)
        public = get_public_calendar()
        writable = [personal, public]
        personal_calendar_id = personal.id
        public_calendar_id = public.id
        # Standard: eigener Kalender. Explizit ?calendar_id= nur wenn writable.
        focus = request.args.get('calendar_id', type=int) or request.form.get('calendar_id', type=int)
        if focus in (personal.id, public.id):
            default_calendar_id = focus
        else:
            default_calendar_id = personal.id

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
    
    events_data = []
    
    for event in events:
        if event.recurrence_type != 'none':
            continue
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id
        ).first()
        events_data.append(event_to_api_dict(
            event,
            participation.status if participation else None,
        ))
    
    for master_event in master_events:
        instances = generate_recurring_instances(master_event, start_date, end_date)
        for instance in instances:
            participation = EventParticipant.query.filter_by(
                event_id=master_event.id,
                user_id=current_user.id
            ).first()
            duration = (instance['end_time'].date() - instance['start_time'].date()).days + 1
            is_all_day = (
                instance['start_time'].strftime('%H:%M') == '00:00'
                and instance['end_time'].strftime('%H:%M') == '23:59'
            )
            events_data.append({
                'id': master_event.id,
                'title': instance['title'],
                'start_time': instance['start_time'].isoformat(),
                'end_time': instance['end_time'].isoformat(),
                'start_date': instance['start_time'].date().isoformat(),
                'end_date': instance['end_time'].date().isoformat(),
                'duration_days': duration,
                'is_all_day': is_all_day,
                'location': instance['location'],
                'event_color': instance['event_color'],
                'display_color': display_color_for_event(master_event, current_user),
                'description': instance['description'],
                'day': instance['start_time'].day,
                'time': None if is_all_day else instance['start_time'].strftime('%H:%M'),
                'participation_status': participation.status if participation else None,
                'is_recurring': True,
                'parent_event_id': master_event.id,
                'calendar_id': master_event.calendar_id,
                'calendar_type': master_event.calendar.calendar_type if master_event.calendar else None,
                'calendar_color': (master_event.calendar.color if master_event.calendar else None),
                'url': url_for('calendar.view_event', event_id=master_event.id)
            })
    
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

    events_data = []
    for event in events:
        participation = EventParticipant.query.filter_by(
            event_id=event.id,
            user_id=current_user.id,
        ).first()
        events_data.append(event_to_api_dict(
            event,
            participation.status if participation else None,
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

        events_data = []
        for event in events:
            if event.recurrence_type != 'none':
                continue
            participation = EventParticipant.query.filter_by(
                event_id=event.id,
                user_id=current_user.id
            ).first()
            events_data.append(event_to_api_dict(
                event,
                participation.status if participation else None,
            ))

        for master_event in master_events:
            instances = generate_recurring_instances(master_event, start_datetime, end_datetime)
            for instance in instances:
                participation = EventParticipant.query.filter_by(
                    event_id=master_event.id,
                    user_id=current_user.id
                ).first()
                duration = (instance['end_time'].date() - instance['start_time'].date()).days + 1
                is_all_day = (
                    instance['start_time'].strftime('%H:%M') == '00:00'
                    and instance['end_time'].strftime('%H:%M') == '23:59'
                )
                events_data.append({
                    'id': master_event.id,
                    'title': instance['title'],
                    'start_time': instance['start_time'].isoformat(),
                    'end_time': instance['end_time'].isoformat(),
                    'start_date': instance['start_time'].date().isoformat(),
                    'end_date': instance['end_time'].date().isoformat(),
                    'duration_days': duration,
                    'is_all_day': is_all_day,
                    'location': instance['location'],
                    'event_color': instance['event_color'],
                    'display_color': display_color_for_event(master_event, current_user),
                    'description': instance['description'],
                    'day': instance['start_time'].day,
                    'time': None if is_all_day else instance['start_time'].strftime('%H:%M'),
                    'participation_status': participation.status if participation else None,
                    'is_recurring': True,
                    'parent_event_id': master_event.id,
                    'calendar_id': master_event.calendar_id,
                    'calendar_type': master_event.calendar.calendar_type if master_event.calendar else None,
                    'calendar_color': (master_event.calendar.color if master_event.calendar else None),
                    'url': url_for('calendar.view_event', event_id=master_event.id)
                })

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


# iCal Feed Routes

def _generate_unique_feed_token():
    token = secrets.token_urlsafe(32)
    while PublicCalendarFeed.query.filter_by(token=token).first():
        token = secrets.token_urlsafe(32)
    return token


def get_or_create_user_feed(user_id):
    """Stellt sicher, dass jeder User genau einen Outbound-Feed hat."""
    feeds = (
        PublicCalendarFeed.query
        .filter_by(created_by=user_id)
        .order_by(PublicCalendarFeed.created_at.asc(), PublicCalendarFeed.id.asc())
        .all()
    )
    if feeds:
        keep = feeds[0]
        extras = feeds[1:]
        if extras:
            for extra in extras:
                db.session.delete(extra)
            db.session.commit()
        if not keep.name:
            keep.name = 'Team-Kalender'
            db.session.commit()
        return keep

    feed = PublicCalendarFeed(
        token=_generate_unique_feed_token(),
        created_by=user_id,
        name='Team-Kalender',
        include_all_events=True,
    )
    db.session.add(feed)
    db.session.commit()
    return feed


def https_to_webcal(url: str) -> str:
    if url.startswith('https://'):
        return 'webcal://' + url[8:]
    if url.startswith('http://'):
        return 'webcal://' + url[7:]
    return url


@calendar_bp.route('/feed/public/<token>.ics')
def public_ical_feed(token):
    """Öffentlicher iCal-Feed (keine Authentifizierung erforderlich)."""
    if not is_calendar_export_enabled():
        return Response('Export disabled', status=403)

    feed = PublicCalendarFeed.query.filter_by(token=token).first_or_404()

    events = CalendarEvent.query.filter(
        CalendarEvent.is_recurring_instance == False
    ).order_by(CalendarEvent.start_time).all()

    feed.last_synced = datetime.utcnow()
    db.session.commit()

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
@check_module_access('module_calendar')
def create_feed():
    """Legacy: Create-Seite entfernt — Redirect auf Integrationsseite."""
    return redirect(url_for('calendar.manage_feeds'))


@calendar_bp.route('/feed/manage')
@login_required
@check_module_access('module_calendar')
def manage_feeds():
    """Ein fester Kalender-Link pro User zum Einbinden in externe Apps."""
    if not is_calendar_export_enabled():
        flash(translate('calendar.flash.export_disabled'), 'warning')
        return redirect(url_for('calendar.index'))
    feed = get_or_create_user_feed(current_user.id)
    feed_url = url_for('calendar.public_ical_feed', token=feed.token, _external=True)
    webcal_url = https_to_webcal(feed_url)
    return render_template(
        'calendar/feed_manage.html',
        feed=feed,
        feed_url=feed_url,
        webcal_url=webcal_url,
        **_page_shell_context(),
    )


@calendar_bp.route('/feed/delete/<int:feed_id>', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def delete_feed(feed_id):
    """Nur Admins: Feed löschen (danach wird beim nächsten Besuch neu angelegt)."""
    if not current_user.is_admin:
        flash(translate('calendar.flash.no_permission_delete_feed'), 'danger')
        return redirect(url_for('calendar.manage_feeds'))

    feed = PublicCalendarFeed.query.get_or_404(feed_id)
    db.session.delete(feed)
    db.session.commit()

    flash(translate('calendar.flash.feed_deleted'), 'success')
    return redirect(url_for('calendar.manage_feeds'))


@calendar_bp.route('/export')
@login_required
@check_module_access('module_calendar')
def export_calendar():
    """Exportiert Events als iCal-Datei."""
    if not is_calendar_export_enabled():
        flash(translate('calendar.flash.export_disabled'), 'warning')
        return redirect(url_for('calendar.index'))

    selected_ids = _selected_calendar_ids_from_request(current_user)
    multi = is_calendar_multi_enabled()
    if multi:
        events = events_query_for_calendars(
            current_user,
            selected_ids,
            [CalendarEvent.is_recurring_instance == False],
        ).order_by(CalendarEvent.start_time).all()
    else:
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


@calendar_bp.route('/calendar/<int:calendar_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def delete_imported_calendar(calendar_id):
    """Delete an imported calendar (and its sync source / events)."""
    cal = Calendar.query.get_or_404(calendar_id)
    if cal.calendar_type != 'imported':
        flash(translate('calendar.flash.cannot_delete_calendar'), 'danger')
        return redirect(url_for('calendar.index'))
    if not (current_user.is_admin or cal.owner_id == current_user.id):
        flash(translate('calendar.flash.no_permission_delete_feed'), 'danger')
        return redirect(url_for('calendar.index'))

    source = None
    if cal.sync_source_id:
        source = CalendarSyncSource.query.get(cal.sync_source_id)

    # Events cascade via sync source; also clear calendar link
    for ev in CalendarEvent.query.filter_by(calendar_id=cal.id).all():
        db.session.delete(ev)
    db.session.delete(cal)
    if source:
        db.session.delete(source)
    db.session.commit()
    flash(translate('calendar.flash.sync_deleted'), 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/import', methods=['GET', 'POST'])
@login_required
@check_module_access('module_calendar')
def import_calendar():
    """Importiert Events aus einer iCal-Datei und verwaltet Sync-Quellen."""
    if not is_calendar_import_enabled():
        flash(translate('calendar.flash.import_disabled'), 'warning')
        return redirect(url_for('calendar.index'))

    multi = is_calendar_multi_enabled()

    if request.method == 'POST':
        action = request.form.get('action', 'import_file')

        if action == 'add_sync':
            name = request.form.get('sync_name', '').strip()
            url = normalize_ical_url(request.form.get('sync_url', ''))
            if not name or not url:
                flash(translate('calendar.flash.sync_missing_fields'), 'danger')
                return redirect(url_for('calendar.import_calendar'))
            if not url.lower().startswith(('http://', 'https://')):
                flash(translate('calendar.flash.sync_invalid_url'), 'danger')
                return redirect(url_for('calendar.import_calendar'))

            source = CalendarSyncSource(
                name=name[:200],
                url=url[:1000],
                created_by=current_user.id,
                is_active=True,
            )
            db.session.add(source)
            db.session.flush()
            if multi:
                ensure_imported_calendar_for_source(source)
            db.session.commit()

            success, message, *_ = sync_calendar_source(source, current_user.id)
            if success:
                flash(translate('calendar.flash.sync_added') + ' ' + message, 'success')
            else:
                flash(translate('calendar.flash.sync_added_with_error') + ' ' + message, 'warning')
            return redirect(url_for('calendar.import_calendar'))

        if action == 'sync_now':
            source_id = request.form.get('source_id', type=int)
            source = CalendarSyncSource.query.get_or_404(source_id)
            success, message, *_ = sync_calendar_source(source, current_user.id)
            flash(message, 'success' if success else 'danger')
            return redirect(url_for('calendar.import_calendar'))

        if action == 'delete_sync':
            source_id = request.form.get('source_id', type=int)
            source = CalendarSyncSource.query.get_or_404(source_id)
            if not (current_user.is_admin or source.created_by == current_user.id):
                flash(translate('calendar.flash.sync_edit_denied'), 'danger')
                return redirect(url_for('calendar.import_calendar'))
            cal = Calendar.query.filter_by(sync_source_id=source.id).first()
            if cal:
                for ev in CalendarEvent.query.filter_by(calendar_id=cal.id).all():
                    db.session.delete(ev)
                db.session.delete(cal)
            db.session.delete(source)
            db.session.commit()
            flash(translate('calendar.flash.sync_deleted'), 'success')
            return redirect(url_for('calendar.import_calendar'))

        if action == 'edit_sync':
            source_id = request.form.get('source_id', type=int)
            source = CalendarSyncSource.query.get_or_404(source_id)
            if not (current_user.is_admin or source.created_by == current_user.id):
                flash(translate('calendar.flash.sync_edit_denied'), 'danger')
                return redirect(url_for('calendar.import_calendar'))
            name = request.form.get('sync_name', '').strip()
            url = normalize_ical_url(request.form.get('sync_url', ''))
            color = sanitize_event_color(request.form.get('sync_color', ''))
            if not name or not url:
                flash(translate('calendar.flash.sync_missing_fields'), 'danger')
                return redirect(url_for('calendar.import_calendar'))
            if not url.lower().startswith(('http://', 'https://', 'file://')):
                flash(translate('calendar.flash.sync_invalid_url'), 'danger')
                return redirect(url_for('calendar.import_calendar'))
            source.name = name[:200]
            source.url = url[:1000]
            cal = Calendar.query.filter_by(sync_source_id=source.id).first()
            if cal:
                cal.name = source.name
                cal.color = color
            elif multi:
                cal = ensure_imported_calendar_for_source(source)
                cal.color = color
            db.session.commit()
            flash(translate('calendar.flash.sync_updated'), 'success')
            return redirect(url_for('calendar.import_calendar'))

        if 'ical_file' not in request.files:
            flash(translate('calendar.flash.select_file'), 'danger')
            return redirect(url_for('calendar.import_calendar'))

        file = request.files['ical_file']
        if file.filename == '':
            flash(translate('calendar.flash.select_file'), 'danger')
            return redirect(url_for('calendar.import_calendar'))

        if not file.filename.endswith('.ics'):
            flash(translate('calendar.flash.select_ics_file'), 'danger')
            return redirect(url_for('calendar.import_calendar'))

        try:
            ical_data = file.read().decode('utf-8')
            target_calendar_id = None
            if multi:
                # File import creates a dedicated imported calendar
                import_name = request.form.get('import_name', '').strip() or file.filename
                source = CalendarSyncSource(
                    name=import_name[:200],
                    url=f'file://{file.filename}'[:1000],
                    created_by=current_user.id,
                    is_active=False,
                )
                db.session.add(source)
                db.session.flush()
                cal = ensure_imported_calendar_for_source(source)
                target_calendar_id = cal.id

            imported_events = import_events_from_ical(
                ical_data, current_user.id, calendar_id=target_calendar_id
            )

            count = 0
            for event in imported_events:
                existing = CalendarEvent.query.filter_by(
                    title=event.title,
                    start_time=event.start_time,
                    created_by=current_user.id,
                    sync_source_id=None,
                    calendar_id=target_calendar_id,
                ).first()

                if not existing:
                    if multi and not event.calendar_id:
                        event.calendar_id = get_or_create_personal_calendar(current_user).id
                    db.session.add(event)
                    count += 1

            db.session.commit()

            flash(f'{count} Termine wurden erfolgreich importiert.', 'success')
            return redirect(url_for('calendar.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Importieren: {str(e)}', 'danger')
            return redirect(url_for('calendar.import_calendar'))

    sync_sources = CalendarSyncSource.query.order_by(CalendarSyncSource.created_at.desc()).all()
    source_calendars = {}
    for source in sync_sources:
        cal = Calendar.query.filter_by(sync_source_id=source.id).first()
        if cal:
            source_calendars[source.id] = cal
    return render_template(
        'calendar/import.html',
        sync_sources=sync_sources,
        source_calendars=source_calendars,
        **_page_shell_context(),
    )

