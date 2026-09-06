"""Shared helpers for the calendar module."""

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

def _enqueue_calendar_source_sync(source_id, user_id):
    """P22: iCal-Sync im Background — Request wartet nicht auf Download/Parse."""
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            try:
                source = CalendarSyncSource.query.get(source_id)
                if not source:
                    return
                sync_calendar_source(source, user_id)
            except Exception as exc:
                logger.exception('Background iCal-Sync fehlgeschlagen (source=%s): %s', source_id, exc)

    threading.Thread(
        target=_run,
        name=f'ical-sync-{source_id}',
        daemon=True,
    ).start()

def sanitize_event_color(raw_color):
    """Validiert einen Hex-Farbwert und liefert eine sichere Standardfarbe."""
    if not raw_color:
        return DEFAULT_EVENT_COLOR
    color = raw_color.strip().lower()
    if len(color) == 7 and color.startswith('#') and all(c in '0123456789abcdef' for c in color[1:]):
        return color
    return DEFAULT_EVENT_COLOR


def _selected_calendar_ids_from_request(user):
    """Parse ?calendars= from query; default = personal (or public) when multi on."""
    multi = is_calendar_multi_enabled()
    if not multi:
        return []
    default = default_calendar_for_user(user)
    raw = request.args.get('calendars')
    ids = parse_calendar_ids_param(raw, default_ids=[default.id] if default else [])
    if not ids and default:
        ids = [default.id]
    return ids


def _sidebar_context(user, selected_ids=None):
    multi = is_calendar_multi_enabled()
    if not multi:
        return {
            'calendar_multi_enabled': False,
            'calendar_personal_enabled': is_calendar_personal_enabled(),
            'calendar_team_enabled': is_calendar_team_enabled(),
            'calendar_export_enabled': is_calendar_export_enabled(),
            'calendar_import_enabled': is_calendar_import_enabled(),
            'sidebar_calendars': None,
            'selected_calendar_ids': [],
            'focus_calendar_id': None,
            'can_create_focus': True,
            'user_calendar_teams': [],
        }
    sidebar = list_sidebar_calendars(user)
    if selected_ids is None:
        selected_ids = _selected_calendar_ids_from_request(user)
    default = sidebar.get('personal') or sidebar.get('public')
    focus_raw = request.args.get('focus', type=int)
    focus_id = focus_raw or (selected_ids[0] if selected_ids else (default.id if default else None))
    focus_cal = Calendar.query.get(focus_id) if focus_id else default
    from app.models.team import Team
    team_ids = list(user_calendar_team_ids(user))
    teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.name).all() if team_ids else []
    return {
        'calendar_multi_enabled': True,
        'calendar_personal_enabled': is_calendar_personal_enabled(),
        'calendar_team_enabled': is_calendar_team_enabled(),
        'calendar_export_enabled': is_calendar_export_enabled(),
        'calendar_import_enabled': is_calendar_import_enabled(),
        'sidebar_calendars': {
            'personal': calendar_to_dict(sidebar['personal'], user) if sidebar.get('personal') else None,
            'personals': [calendar_to_dict(c, user) for c in sidebar.get('personals') or []],
            'public': calendar_to_dict(sidebar['public'], user) if sidebar.get('public') else None,
            'publics': [calendar_to_dict(c, user) for c in sidebar.get('publics') or []],
            'events': calendar_to_dict(sidebar['events'], user) if sidebar.get('events') else None,
            'teams': [calendar_to_dict(c, user) for c in sidebar.get('teams') or []],
            'others': [calendar_to_dict(c, user) for c in sidebar.get('others') or []],
        },
        'selected_calendar_ids': selected_ids,
        'focus_calendar_id': focus_cal.id if focus_cal else None,
        'can_create_focus': can_create_in_calendar(user, focus_cal) if focus_cal else True,
        'user_calendar_teams': [{'id': t.id, 'name': t.name} for t in teams],
    }


def _page_shell_context(user=None):
    """Sidebar context for create/edit/view pages (non-interactive list)."""
    return _sidebar_context(user or current_user)


def _notify_event_invites(event, invitee_ids):
    import logging

    from app.models.user import User
    from app.utils.access_control import has_module_access
    from app.utils.module_roles_cache import clear_module_roles_fallback, prefetch_user_module_roles
    from app.utils.notifications import get_notification_settings_map, notify_user

    ids = []
    seen = set()
    for uid in invitee_ids or []:
        if uid == event.created_by or uid in seen:
            continue
        seen.add(uid)
        ids.append(uid)
    if not ids:
        return

    users_by_id = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
    prefetch_user_module_roles(ids)
    settings_by_id = get_notification_settings_map(ids)
    try:
        for uid in ids:
            try:
                user = users_by_id.get(uid)
                if not user:
                    continue
                if not has_module_access(user, 'module_calendar'):
                    continue
                settings = settings_by_id.get(uid)
                if not settings or not settings.calendar_notifications_enabled:
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
                logging.exception('Invite notification failed for user %s event %s', uid, event.id)
    finally:
        clear_module_roles_fallback()


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


def _participation_status(participations, event_id):
    row = participations.get(event_id)
    return row.status if row else None


def _recurring_instance_api_dict(master_event, instance, participation_status):
    duration = (instance['end_time'].date() - instance['start_time'].date()).days + 1
    is_all_day = (
        instance['start_time'].strftime('%H:%M') == '00:00'
        and instance['end_time'].strftime('%H:%M') == '23:59'
    )
    return {
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
        'participation_status': participation_status,
        'is_recurring': True,
        'parent_event_id': master_event.id,
        'calendar_id': master_event.calendar_id,
        'calendar_type': master_event.calendar.calendar_type if master_event.calendar else None,
        'calendar_color': (master_event.calendar.color if master_event.calendar else None),
        'url': url_for('calendar.view_event', event_id=master_event.id),
    }


__all__ = [
    '_enqueue_calendar_source_sync',
    'sanitize_event_color',
    '_selected_calendar_ids_from_request',
    '_sidebar_context',
    '_page_shell_context',
    '_notify_event_invites',
    '_parse_invitee_ids',
    '_add_participants_for_event',
    'event_to_api_dict',
    'generate_recurring_instances',
    '_participation_status',
    '_recurring_instance_api_dict',
]
