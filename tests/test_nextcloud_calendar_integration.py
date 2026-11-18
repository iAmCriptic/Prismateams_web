"""Tests for Nextcloud CalDAV integration in the Calendar & Events modules."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import db
from app.models.calendar import Calendar, CalendarEvent
from app.models.event import Event, EventAppointment
from app.models.settings import SystemSettings
from app.models.user import User
from app.services.event_service import EventService
from app.utils.nextcloud_caldav import RemoteCalEvent, RemoteCalendar
from app.utils.nextcloud_calendar_settings import (
    SETTING_NC_CAL_ENABLED,
    SETTING_NC_CAL_EVENTS_NC_URL,
    SETTING_NC_CAL_EVENTS_TARGET,
    SETTING_NC_CAL_MODE,
    get_calendar_storage_mode,
    get_events_sync_target,
)
from app.utils.nextcloud_calendar_sync import (
    invalidate_caldav_sync_cache,
    sync_all_nextcloud_calendars,
)
from app.utils.multi_calendars import can_create_in_calendar, can_edit_event
from app.utils.system_settings_cache import invalidate_system_settings_cache


@pytest.fixture(autouse=True)
def _clear_caches():
    invalidate_system_settings_cache()
    invalidate_caldav_sync_cache()
    yield
    invalidate_system_settings_cache()
    invalidate_caldav_sync_cache()


class FakeCalDAVClient:
    """In-memory Nextcloud CalDAV mock."""

    def __init__(self):
        self.calendars: dict[str, RemoteCalendar] = {
            'https://cloud.example.com/remote.php/dav/calendars/svc/personal/': RemoteCalendar(
                url='https://cloud.example.com/remote.php/dav/calendars/svc/personal/',
                name='Persönlich (NC)',
                color='#198754',
                read_only=False,
            ),
            'https://cloud.example.com/remote.php/dav/calendars/svc/holidays/': RemoteCalendar(
                url='https://cloud.example.com/remote.php/dav/calendars/svc/holidays/',
                name='Feiertage (Read-Only)',
                color='#6c757d',
                read_only=True,
            ),
        }
        self.events: dict[str, list[RemoteCalEvent]] = {
            'https://cloud.example.com/remote.php/dav/calendars/svc/personal/': [
                RemoteCalEvent(
                    href='https://cloud.example.com/remote.php/dav/calendars/svc/personal/ev1.ics',
                    etag='etag-1',
                    uid='nc-uid-1',
                    title='Nextcloud Meeting',
                    description='Sync test',
                    location='Raum 1',
                    start_time=datetime.utcnow() + timedelta(days=1),
                    end_time=datetime.utcnow() + timedelta(days=1, hours=1),
                )
            ],
            'https://cloud.example.com/remote.php/dav/calendars/svc/holidays/': [],
        }
        self.created_calendars: list[str] = []
        self.upserted: list[tuple[str, str]] = []
        self.deleted_hrefs: list[str] = []

    def discover_calendars(self):
        return sorted(self.calendars.values(), key=lambda c: c.name.lower())

    def create_calendar(self, name: str, color: str = '#0d6efd'):
        url = f'https://cloud.example.com/remote.php/dav/calendars/svc/{name.lower()}/'
        rc = RemoteCalendar(url=url, name=name, color=color, read_only=False)
        self.calendars[url] = rc
        self.events[url] = []
        self.created_calendars.append(name)
        return rc

    def fetch_events(self, calendar_url: str, start: datetime, end: datetime):
        return list(self.events.get(calendar_url, []))

    def upsert_event(self, calendar_url: str, event):
        uid = event.ical_uid or f'pt-{event.id}'
        href = event.remote_href or f'{calendar_url.rstrip("/")}/{uid}.ics'
        etag = f'etag-{len(self.upserted) + 10}'
        self.upserted.append((calendar_url, event.title))
        # Keep in-memory list up to date
        ev_list = self.events.setdefault(calendar_url, [])
        ev_list[:] = [e for e in ev_list if e.href != href]
        ev_list.append(
            RemoteCalEvent(
                href=href,
                etag=etag,
                uid=uid,
                title=event.title,
                description=event.description or '',
                location=event.location or '',
                start_time=event.start_time,
                end_time=event.end_time,
            )
        )
        return uid, href, etag

    def delete_event(self, remote_href: str, etag: str | None = None):
        self.deleted_hrefs.append(remote_href)
        for ev_list in self.events.values():
            ev_list[:] = [e for e in ev_list if e.href != remote_href]

    def update_calendar_properties(self, calendar_url: str, *, name: str | None = None, color: str | None = None):
        rc = self.calendars.get(calendar_url)
        if rc:
            if name:
                rc.name = name
            if color:
                rc.color = color

    def delete_calendar(self, calendar_url: str):
        self.calendars.pop(calendar_url, None)
        self.events.pop(calendar_url, None)


def _create_user(username='cal_admin', is_admin=True):
    u = User(
        email=f'{username}@example.com',
        first_name=username.title(),
        last_name='Test',
        is_active=True,
        is_admin=is_admin,
        is_guest=False,
        is_email_confirmed=True,
        has_full_access=True,
    )
    u.set_password('Password123!@#')
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, user):
    client.post('/logout', follow_redirects=True)
    client.post('/login', data={'email': user.email, 'password': 'Password123!@#'}, follow_redirects=True)


def _set_setting(key: str, value: str):
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(SystemSettings(key=key, value=value))
    db.session.commit()


def test_admin_calendar_settings_and_discovery(app, client):
    invalidate_caldav_sync_cache()
    admin = _create_user('cal_adm', is_admin=True)
    _login(client, admin)

    resp = client.post('/settings/admin/calendar-settings', data={
        'calendar_export_enabled': 'on',
        'calendar_import_enabled': 'on',
        'calendar_nextcloud_enabled': 'on',
        'calendar_storage_mode': 'hybrid',
        'calendar_events_sync_target': 'nextcloud',
        'calendar_events_nextcloud_url': '',
    })
    assert resp.status_code in (200, 302)
    assert get_calendar_storage_mode() == 'hybrid'
    assert get_events_sync_target() == 'nextcloud'

    _set_setting('nextcloud_url', 'https://cloud.example.com')
    _set_setting('nextcloud_username', 'svc')
    _set_setting('nextcloud_password_enc', 'dummy')

    fake = FakeCalDAVClient()
    with patch('app.utils.nextcloud_calendar_sync.get_portal_caldav_client', return_value=fake), \
         patch('app.utils.nextcloud_calendar_sync.nextcloud_configured', return_value=True):
        disc = client.get('/settings/admin/calendar-settings/nextcloud-calendars')
        assert disc.status_code == 200
        payload = disc.get_json()
        assert payload['success'] is True
        assert len(payload['calendars']) == 2
        ro = next(c for c in payload['calendars'] if 'Read-Only' in c['name'])
        assert ro['read_only'] is True


def test_caldav_sync_readonly_and_crud_writeback(app, client):
    invalidate_caldav_sync_cache()
    _set_setting('nextcloud_url', 'https://cloud.example.com')
    _set_setting('nextcloud_username', 'svc')
    _set_setting('nextcloud_password_enc', 'dummy')
    _set_setting(SETTING_NC_CAL_ENABLED, 'true')
    _set_setting(SETTING_NC_CAL_MODE, 'hybrid')

    user = _create_user('cal_user', is_admin=False)
    fake = FakeCalDAVClient()

    with patch('app.utils.nextcloud_calendar_sync.get_portal_caldav_client', return_value=fake), \
         patch('app.utils.nextcloud_calendar_sync.nextcloud_configured', return_value=True):
        res = sync_all_nextcloud_calendars(force=True)
        assert res['ok'] == 2

        nc_rw = Calendar.query.filter_by(storage_backend='nextcloud', remote_read_only=False).first()
        nc_ro = Calendar.query.filter_by(storage_backend='nextcloud', remote_read_only=True).first()
        assert nc_rw is not None and nc_ro is not None
        assert can_create_in_calendar(user, nc_rw) is True
        assert can_create_in_calendar(user, nc_ro) is False

        ev = CalendarEvent.query.filter_by(calendar_id=nc_rw.id, ical_uid='nc-uid-1').first()
        assert ev is not None
        assert ev.title == 'Nextcloud Meeting'
        assert can_edit_event(user, ev) is True

        # Hybrid sidebar shows both collapsible sections
        _login(client, user)
        page = client.get('/calendar/')
        assert page.status_code == 200
        assert b'calendarPortalRootCollapse' in page.data
        assert b'calendarNextcloudRootCollapse' in page.data
        assert b'Pers\xc3\xb6nlich (NC)' in page.data

        # Create event in Nextcloud calendar via portal -> pushes via CalDAV PUT
        day_str = (datetime.utcnow() + timedelta(days=2)).strftime('%Y-%m-%d')
        c_resp = client.post('/calendar/create', data={
            'title': 'Portal Created NC Event',
            'calendar_id': str(nc_rw.id),
            'start_date': day_str,
            'start_time': '10:00',
            'end_date': day_str,
            'end_time': '11:00',
            'location': 'Online',
            'description': 'Test',
        }, follow_redirects=False)
        assert c_resp.status_code in (200, 302)
        created = CalendarEvent.query.filter_by(title='Portal Created NC Event').first()
        assert created is not None
        assert created.remote_href is not None
        assert any(t == 'Portal Created NC Event' for _, t in fake.upserted)

        # Delete event -> pushes CalDAV DELETE
        d_resp = client.post(f'/calendar/delete/{created.id}', follow_redirects=False)
        assert d_resp.status_code in (200, 302)
        assert created.remote_href in fake.deleted_hrefs


def test_events_module_auto_creates_nextcloud_calendar_and_syncs(app):
    invalidate_caldav_sync_cache()
    _set_setting('nextcloud_url', 'https://cloud.example.com')
    _set_setting('nextcloud_username', 'svc')
    _set_setting('nextcloud_password_enc', 'dummy')
    _set_setting(SETTING_NC_CAL_ENABLED, 'true')
    _set_setting(SETTING_NC_CAL_MODE, 'nextcloud')
    _set_setting(SETTING_NC_CAL_EVENTS_TARGET, 'nextcloud')
    _set_setting(SETTING_NC_CAL_EVENTS_NC_URL, '')

    admin = _create_user('ev_adm', is_admin=True)
    fake = FakeCalDAVClient()

    with patch('app.utils.nextcloud_calendar_sync.get_portal_caldav_client', return_value=fake), \
         patch('app.utils.nextcloud_calendar_sync.nextcloud_configured', return_value=True):
        ev_obj = Event(name='Sommerfest', owner_id=admin.id, created_by=admin.id)
        db.session.add(ev_obj)
        db.session.flush()
        appt = EventAppointment(
            event_id=ev_obj.id,
            label='Aufbau',
            start_time=datetime.utcnow() + timedelta(days=5),
            end_time=datetime.utcnow() + timedelta(days=5, hours=2),
        )
        db.session.add(appt)
        db.session.flush()

        EventService.sync_calendar_for_event(ev_obj, admin.id)
        db.session.commit()

        assert 'Veranstaltungen' in fake.created_calendars
        assert appt.calendar_event is not None
        assert appt.calendar_event.calendar.storage_backend == 'nextcloud'
        assert appt.calendar_event.remote_href is not None
        assert any('Sommerfest - Aufbau' in t for _, t in fake.upserted)

        href = appt.calendar_event.remote_href
        EventService.remove_orphan_calendar_entries(ev_obj)
        db.session.commit()
        assert href in fake.deleted_hrefs


def test_create_update_delete_nextcloud_calendar_via_portal(app, client):
    _set_setting('nextcloud_url', 'https://cloud.example.com')
    _set_setting('nextcloud_username', 'svc')
    _set_setting('nextcloud_password_enc', 'dummy')
    _set_setting(SETTING_NC_CAL_ENABLED, 'true')
    _set_setting(SETTING_NC_CAL_MODE, 'hybrid')

    user = _create_user('cal_mgr', is_admin=False)
    _login(client, user)
    fake = FakeCalDAVClient()

    with patch('app.utils.nextcloud_calendar_sync.get_portal_caldav_client', return_value=fake), \
         patch('app.utils.integrations.nextcloud_configured', return_value=True):
        # Create Nextcloud calendar via portal UI
        c_resp = client.post('/calendar/calendars/create', data={
            'name': 'Projektplan',
            'calendar_type': 'nextcloud',
            'color': '#e83e8c',
        }, follow_redirects=False)
        assert c_resp.status_code in (200, 302)
        assert 'Projektplan' in fake.created_calendars
        cal = Calendar.query.filter_by(name='Projektplan', storage_backend='nextcloud').first()
        assert cal is not None
        assert cal.color == '#e83e8c'

        # Rename & recolor via PROPPATCH
        u_resp = client.post(f'/calendar/calendars/{cal.id}/update', data={
            'name': 'Projektplan 2027',
            'color': '#6f42c1',
            'meta_form': '1',
        }, follow_redirects=False)
        assert u_resp.status_code in (200, 302)
        db.session.refresh(cal)
        assert cal.name == 'Projektplan 2027'
        assert cal.color == '#6f42c1'
        assert fake.calendars[cal.remote_url].name == 'Projektplan 2027'
        assert fake.calendars[cal.remote_url].color == '#6f42c1'

        # Delete via CalDAV DELETE
        remote_url = cal.remote_url
        d_resp = client.post(f'/calendar/calendars/{cal.id}/delete', follow_redirects=False)
        assert d_resp.status_code in (200, 302)
        assert Calendar.query.get(cal.id) is None
        assert remote_url not in fake.calendars


def test_deleted_nextcloud_calendar_cleanup_and_recurring_delete(app, client):
    from app.models.calendar import Calendar, CalendarEvent, EventParticipant
    from app.utils.nextcloud_caldav import _strip_etag
    from app.utils.nextcloud_calendar_sync import (
        invalidate_caldav_sync_cache,
        sync_nextcloud_calendars,
    )

    assert _strip_etag('W/"abc-123"') == 'abc-123'
    assert _strip_etag('"xyz"') == 'xyz'

    invalidate_caldav_sync_cache()
    _set_setting(SETTING_NC_CAL_ENABLED, 'true')
    _set_setting(SETTING_NC_CAL_MODE, 'hybrid')

    admin = _create_user('cal_del_adm', is_admin=True)
    _login(client, admin)

    fake = FakeCalDAVClient()
    with patch('app.utils.nextcloud_calendar_sync.get_portal_caldav_client', return_value=fake), \
         patch('app.utils.nextcloud_calendar_sync.nextcloud_configured', return_value=True):
        cals = sync_nextcloud_calendars(force=True)
        work = next(c for c in cals if not c.remote_read_only)

        # Create recurring master event in Nextcloud calendar with participant
        ev = CalendarEvent(
            title='Weekly Sync',
            start_time=datetime.utcnow() + timedelta(days=1),
            end_time=datetime.utcnow() + timedelta(days=1, hours=1),
            created_by=admin.id,
            calendar_id=work.id,
            recurrence_type='weekly',
            recurrence_interval=1,
            remote_href='https://nc.example.com/remote.php/dav/calendars/admin/work/weekly.ics',
        )
        db.session.add(ev)
        db.session.flush()
        db.session.add(EventParticipant(event_id=ev.id, user_id=admin.id, status='accepted'))
        db.session.commit()

        # delete_recurring_event_all must delete from Nextcloud too
        resp = client.post(f'/calendar/recurring/{ev.id}/delete-all')
        assert resp.status_code in (302, 200)
        assert 'https://nc.example.com/remote.php/dav/calendars/admin/work/weekly.ics' in fake.deleted_hrefs

        # Deleting a Nextcloud calendar that has events + participants must not hit FK IntegrityError
        ev2 = CalendarEvent(
            title='Remaining Event',
            start_time=datetime.utcnow() + timedelta(days=2),
            end_time=datetime.utcnow() + timedelta(days=2, hours=1),
            created_by=admin.id,
            calendar_id=work.id,
        )
        db.session.add(ev2)
        db.session.flush()
        db.session.add(EventParticipant(event_id=ev2.id, user_id=admin.id, status='accepted'))
        db.session.commit()

        fake.calendars.pop(work.remote_url, None)
        remaining = sync_nextcloud_calendars(force=True)
        assert all(c.id != work.id for c in remaining)
        assert CalendarEvent.query.filter_by(id=ev2.id).first() is None
