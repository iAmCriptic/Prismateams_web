"""iCal feeds, calendar CRUD, export, and iCal import/sync."""

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


@calendar_bp.route('/calendars/create', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def create_calendar():
    """Create an extra personal, team or public calendar."""
    name = request.form.get('name', '').strip()
    calendar_type = request.form.get('calendar_type', '').strip().lower()
    color = request.form.get('color', '').strip() or None
    team_id = request.form.get('team_id', '').strip() or None
    cal, err = create_extra_calendar(
        current_user,
        name,
        calendar_type,
        color=color,
        team_id=team_id,
    )
    if err:
        flash(translate(f'calendar.flash.calendar_{err}'), 'danger')
        return redirect(url_for('calendar.index'))
    db.session.commit()
    flash(translate('calendar.flash.calendar_created', name=cal.name), 'success')
    return redirect(url_for('calendar.index', calendars=cal.id))


@calendar_bp.route('/calendars/<int:calendar_id>/update', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def update_calendar(calendar_id):
    cal = Calendar.query.get_or_404(calendar_id)
    name = request.form.get('name')
    color = request.form.get('color')
    hidden_raw = request.form.get('hidden_from_others')
    hidden = None
    if request.form.get('meta_form') == '1':
        hidden = hidden_raw in ('1', 'on', 'true', 'True')
    elif hidden_raw is not None:
        hidden = hidden_raw in ('1', 'on', 'true', 'True')
    if not update_calendar_meta(current_user, cal, name=name, color=color, hidden_from_others=hidden):
        flash(translate('calendar.flash.no_manage_permission'), 'danger')
        return redirect(url_for('calendar.index'))
    db.session.commit()
    flash(translate('calendar.flash.calendar_updated'), 'success')
    return redirect(url_for('calendar.index'))


@calendar_bp.route('/calendars/<int:calendar_id>/delete', methods=['POST'])
@login_required
@check_module_access('module_calendar')
def delete_user_calendar(calendar_id):
    cal = Calendar.query.get_or_404(calendar_id)
    if cal.calendar_type == 'imported':
        return delete_imported_calendar(calendar_id)
    if not delete_extra_calendar(current_user, cal):
        flash(translate('calendar.flash.cannot_delete_calendar'), 'danger')
        return redirect(url_for('calendar.index'))
    db.session.commit()
    flash(translate('calendar.flash.calendar_deleted'), 'success')
    return redirect(url_for('calendar.index'))


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

            _enqueue_calendar_source_sync(source.id, current_user.id)
            flash(translate('calendar.flash.sync_started'), 'info')
            return redirect(url_for('calendar.import_calendar'))

        if action == 'sync_now':
            source_id = request.form.get('source_id', type=int)
            source = CalendarSyncSource.query.get_or_404(source_id)
            _enqueue_calendar_source_sync(source.id, current_user.id)
            flash(translate('calendar.flash.sync_started'), 'info')
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
