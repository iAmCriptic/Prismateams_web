"""Nextcloud CalDAV client for calendar discovery, sync, creation, and event writeback."""

from __future__ import annotations

import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse
from xml.sax.saxutils import escape as xml_escape

import requests

logger = logging.getLogger(__name__)

NS = {
    'd': 'DAV:',
    'cal': 'urn:ietf:params:xml:ns:caldav',
    'cs': 'http://calendarserver.org/ns/',
    'apple': 'http://apple.com/ns/ical/',
}


@dataclass
class RemoteCalendar:
    url: str
    name: str
    color: str = '#0d6efd'
    ctag: str = ''
    read_only: bool = False


@dataclass
class RemoteCalEvent:
    href: str
    etag: str
    uid: str
    title: str
    description: str
    location: str
    start_time: datetime
    end_time: datetime
    recurrence_type: str = 'none'
    recurrence_interval: int = 1
    recurrence_end_date: Optional[datetime] = None
    recurrence_days: Optional[str] = None
    attendees: list[dict[str, str]] = field(default_factory=list)


def _strip_etag(raw: str | None) -> str:
    val = (raw or '').strip()
    if val.startswith('W/'):
        val = val[2:].strip()
    return val.strip('"')


def _ok_prop_elements(resp_el: ET.Element) -> list[ET.Element]:
    props: list[ET.Element] = []
    for ps in resp_el.findall('d:propstat', NS):
        st = ps.find('d:status', NS)
        if st is not None and st.text and '200' not in st.text:
            continue
        p_el = ps.find('d:prop', NS)
        if p_el is not None:
            props.append(p_el)
    if not props:
        first_p = resp_el.find('.//d:propstat/d:prop', NS)
        if first_p is not None:
            props.append(first_p)
    return props


def _normalize_color(raw: str | None, default: str = '#0d6efd') -> str:
    val = (raw or '').strip()
    if not val:
        return default
    if re.fullmatch(r'#[0-9a-fA-F]{6}', val):
        return val.lower()
    if re.fullmatch(r'#[0-9a-fA-F]{8}', val):
        return val[:7].lower()
    return default


def _to_naive_portal_dt(dt_val: Any, *, is_end: bool = False) -> datetime:
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is not None:
            try:
                from app.utils.common import get_portal_timezone
                tz = get_portal_timezone()
                return dt_val.astimezone(tz).replace(tzinfo=None)
            except Exception:
                return dt_val.astimezone(timezone.utc).replace(tzinfo=None)
        return dt_val
    if isinstance(dt_val, date):
        return datetime.combine(dt_val, time(0, 0) if not is_end else time(23, 59))
    return datetime.utcnow()


def _format_ics_dt(dt: datetime) -> str:
    return dt.strftime('%Y%m%dT%H%M%S')


def _escape_ics_text(val: str | None) -> str:
    if not val:
        return ''
    return (
        str(val)
        .replace('\\', '\\\\')
        .replace('\r\n', '\n')
        .replace('\n', '\\n')
        .replace(';', '\\;')
        .replace(',', '\\,')
    )


def _slugify(name: str) -> str:
    raw = re.sub(r'[^a-zA-Z0-9_-]+', '-', (name or 'calendar').strip().lower()).strip('-')
    return raw or 'calendar'


class NextcloudCalDAVClient:
    def __init__(self, server_url: str, username: str, app_password: str):
        self.server_url = (server_url or '').rstrip('/')
        self.username = (username or '').strip()
        self.app_password = app_password or ''
        if not self.server_url or not self.username or not self.app_password:
            raise ValueError('nextcloud_credentials_incomplete')
        self._session = requests.Session()
        self._session.auth = (self.username, self.app_password)
        self._session.headers.update({'User-Agent': 'PrismaTeams-CalDAV/1.0'})

    def _abs_url(self, href: str) -> str:
        if href.startswith('http://') or href.startswith('https://'):
            return href
        parsed = urlparse(self.server_url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        return urljoin(origin + '/', href.lstrip('/'))

    def discover_calendar_home(self) -> str:
        principal_url = f'{self.server_url}/remote.php/dav/principals/users/{quote(self.username, safe="")}/'
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><cal:calendar-home-set/></d:prop>'
            '</d:propfind>'
        )
        try:
            resp = self._session.request(
                'PROPFIND',
                principal_url,
                headers={'Depth': '0', 'Content-Type': 'application/xml; charset=utf-8'},
                data=body.encode('utf-8'),
                timeout=30,
            )
            if resp.status_code in (200, 207) and resp.content:
                root = ET.fromstring(resp.content)
                href_el = root.find('.//cal:calendar-home-set/d:href', NS)
                if href_el is not None and href_el.text:
                    return self._abs_url(href_el.text.strip()).rstrip('/') + '/'
        except Exception as exc:
            logger.debug('CalDAV principal discovery fallback: %s', exc)
        return f'{self.server_url}/remote.php/dav/calendars/{quote(self.username, safe="")}/'

    def discover_calendars(self) -> list[RemoteCalendar]:
        home_url = self.discover_calendar_home()
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav" '
            'xmlns:cs="http://calendarserver.org/ns/" xmlns:apple="http://apple.com/ns/ical/">'
            '<d:prop>'
            '<d:displayname/>'
            '<d:resourcetype/>'
            '<apple:calendar-color/>'
            '<cs:getctag/>'
            '<d:current-user-privilege-set/>'
            '</d:prop>'
            '</d:propfind>'
        )
        resp = self._session.request(
            'PROPFIND',
            home_url,
            headers={'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'},
            data=body.encode('utf-8'),
            timeout=30,
        )
        if resp.status_code not in (200, 207):
            raise ConnectionError(f'nextcloud_caldav_discover_failed:{resp.status_code}')

        if not resp.content:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return []
        calendars: list[RemoteCalendar] = []
        home_norm = home_url.rstrip('/')
        for resp_el in root.findall('d:response', NS):
            href_el = resp_el.find('d:href', NS)
            if href_el is None or not href_el.text:
                continue
            cal_url = self._abs_url(href_el.text.strip()).rstrip('/') + '/'
            if cal_url.rstrip('/') == home_norm:
                continue

            props = _ok_prop_elements(resp_el)
            if not props:
                continue
            rt = next((p.find('d:resourcetype', NS) for p in props if p.find('d:resourcetype', NS) is not None), None)
            if rt is None or rt.find('cal:calendar', NS) is None:
                continue
            # Skip scheduling inbox/outbox or trashbin
            if (
                rt.find('cal:schedule-inbox', NS) is not None
                or rt.find('cal:schedule-outbox', NS) is not None
            ):
                continue

            dn_el = next((p.find('d:displayname', NS) for p in props if p.find('d:displayname', NS) is not None), None)
            name = (dn_el.text or '').strip() if dn_el is not None and dn_el.text else ''
            if not name:
                name = cal_url.rstrip('/').rsplit('/', 1)[-1]

            color_el = next((p.find('apple:calendar-color', NS) for p in props if p.find('apple:calendar-color', NS) is not None), None)
            color = _normalize_color(color_el.text if color_el is not None else None)

            ctag_el = next((p.find('cs:getctag', NS) for p in props if p.find('cs:getctag', NS) is not None), None)
            ctag = (ctag_el.text or '').strip() if ctag_el is not None and ctag_el.text else ''

            read_only = False
            priv_set = next((p.find('d:current-user-privilege-set', NS) for p in props if p.find('d:current-user-privilege-set', NS) is not None), None)
            if priv_set is not None:
                privs = priv_set.findall('.//d:privilege', NS)
                if privs:
                    has_write = (
                        priv_set.find('.//d:write', NS) is not None
                        or priv_set.find('.//d:write-content', NS) is not None
                        or priv_set.find('.//d:write-properties', NS) is not None
                        or priv_set.find('.//d:bind', NS) is not None
                        or priv_set.find('.//d:all', NS) is not None
                        or priv_set.find('.//cal:write', NS) is not None
                    )
                    if not has_write:
                        read_only = True

            calendars.append(
                RemoteCalendar(
                    url=cal_url,
                    name=name,
                    color=color,
                    ctag=ctag,
                    read_only=read_only,
                )
            )
        calendars.sort(key=lambda c: c.name.lower())
        return calendars

    def create_calendar(self, name: str, color: str = '#0d6efd') -> RemoteCalendar:
        home_url = self.discover_calendar_home()
        slug = _slugify(name)
        cal_url = f'{home_url.rstrip("/")}/{slug}/'
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:apple="http://apple.com/ns/ical/">'
            '<d:set><d:prop>'
            f'<d:displayname>{xml_escape(name)}</d:displayname>'
            f'<apple:calendar-color>{xml_escape(_normalize_color(color))}</apple:calendar-color>'
            '<c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'
            '</d:prop></d:set>'
            '</c:mkcalendar>'
        )
        resp = self._session.request(
            'MKCALENDAR',
            cal_url,
            headers={'Content-Type': 'application/xml; charset=utf-8'},
            data=body.encode('utf-8'),
            timeout=30,
        )
        if resp.status_code not in (200, 201, 204, 405):
            raise ConnectionError(f'nextcloud_mkcalendar_failed:{resp.status_code}')
        return RemoteCalendar(url=cal_url, name=name, color=_normalize_color(color), ctag='', read_only=False)

    def update_calendar_properties(
        self,
        calendar_url: str,
        *,
        name: str | None = None,
        color: str | None = None,
    ) -> None:
        props: list[str] = []
        if name is not None and name.strip():
            props.append(f'<d:displayname>{xml_escape(name.strip())}</d:displayname>')
        if color is not None and color.strip():
            props.append(f'<apple:calendar-color>{xml_escape(_normalize_color(color))}</apple:calendar-color>')
        if not props:
            return
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propertyupdate xmlns:d="DAV:" xmlns:apple="http://apple.com/ns/ical/">'
            f'<d:set><d:prop>{"".join(props)}</d:prop></d:set>'
            '</d:propertyupdate>'
        )
        resp = self._session.request(
            'PROPPATCH',
            calendar_url,
            headers={'Content-Type': 'application/xml; charset=utf-8'},
            data=body.encode('utf-8'),
            timeout=30,
        )
        if resp.status_code not in (200, 207):
            raise ConnectionError(f'nextcloud_proppatch_failed:{resp.status_code}')

    def delete_calendar(self, calendar_url: str) -> None:
        if not calendar_url:
            return
        resp = self._session.delete(calendar_url, timeout=30)
        if resp.status_code not in (200, 204, 404):
            raise ConnectionError(f'nextcloud_delete_calendar_failed:{resp.status_code}')

    def fetch_events(self, calendar_url: str, start: datetime, end: datetime) -> list[RemoteCalEvent]:
        start_utc = start.strftime('%Y%m%dT%H%M%SZ')
        end_utc = end.strftime('%Y%m%dT%H%M%SZ')
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><cal:calendar-data/></d:prop>'
            '<cal:filter><cal:comp-filter name="VCALENDAR">'
            '<cal:comp-filter name="VEVENT">'
            f'<cal:time-range start="{start_utc}" end="{end_utc}"/>'
            '</cal:comp-filter>'
            '</cal:comp-filter></cal:filter>'
            '</cal:calendar-query>'
        )
        resp = self._session.request(
            'REPORT',
            calendar_url,
            headers={'Depth': '1', 'Content-Type': 'application/xml; charset=utf-8'},
            data=body.encode('utf-8'),
            timeout=60,
        )
        if resp.status_code not in (200, 207):
            raise ConnectionError(f'nextcloud_caldav_report_failed:{resp.status_code}')

        if not resp.content:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return []
        events: list[RemoteCalEvent] = []
        for resp_el in root.findall('d:response', NS):
            href_el = resp_el.find('d:href', NS)
            props = _ok_prop_elements(resp_el)
            if href_el is None or not href_el.text or not props:
                continue
            cal_data_el = next((p.find('cal:calendar-data', NS) for p in props if p.find('cal:calendar-data', NS) is not None), None)
            if cal_data_el is None or not cal_data_el.text:
                continue
            etag_el = next((p.find('d:getetag', NS) for p in props if p.find('d:getetag', NS) is not None), None)
            etag = _strip_etag(etag_el.text if etag_el is not None else None)
            href = self._abs_url(href_el.text.strip())
            parsed = self._parse_ics_event(cal_data_el.text, href=href, etag=etag)
            if parsed:
                events.append(parsed)
        return events

    def _parse_ics_event(self, ics_text: str, *, href: str, etag: str) -> Optional[RemoteCalEvent]:
        try:
            from icalendar import Calendar as ICalParser
            cal = ICalParser.from_ical(ics_text)
            for comp in cal.walk('VEVENT'):
                uid = str(comp.get('UID') or '').strip()
                if not uid:
                    continue
                summary = str(comp.get('SUMMARY') or 'Termin').strip()
                description = str(comp.get('DESCRIPTION') or '').strip()
                location = str(comp.get('LOCATION') or '').strip()
                dtstart_prop = comp.get('DTSTART')
                dtend_prop = comp.get('DTEND')
                if not dtstart_prop:
                    continue
                start_dt = _to_naive_portal_dt(dtstart_prop.dt, is_end=False)
                if dtend_prop:
                    end_dt = _to_naive_portal_dt(dtend_prop.dt, is_end=True)
                else:
                    end_dt = start_dt + timedelta(hours=1)
                if end_dt < start_dt:
                    end_dt = start_dt + timedelta(hours=1)

                rec_type = 'none'
                rec_interval = 1
                rec_end = None
                rec_days = None
                rrule = comp.get('RRULE')
                if rrule:
                    freq_list = rrule.get('FREQ') or []
                    freq = str(freq_list[0]).lower() if freq_list else ''
                    if freq in ('daily', 'weekly', 'monthly', 'yearly'):
                        rec_type = freq
                    iv_list = rrule.get('INTERVAL') or []
                    if iv_list:
                        try:
                            rec_interval = max(1, int(iv_list[0]))
                        except (TypeError, ValueError):
                            rec_interval = 1
                    until_list = rrule.get('UNTIL') or []
                    if until_list:
                        rec_end = _to_naive_portal_dt(until_list[0], is_end=True)

                attendees: list[dict[str, str]] = []
                raw_attendees = comp.get('ATTENDEE')
                if raw_attendees:
                    att_list = raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]
                    seen_emails: set[str] = set()
                    partstat_map = {
                        'ACCEPTED': 'accepted',
                        'DECLINED': 'declined',
                        'TENTATIVE': 'tentative',
                        'NEEDS-ACTION': 'pending',
                    }
                    for att in att_list:
                        val_str = str(att).strip()
                        if val_str.lower().startswith('mailto:'):
                            email = val_str[7:].strip().lower()
                        elif '@' in val_str:
                            email = val_str.lower()
                        else:
                            continue
                        if not email or email in seen_emails:
                            continue
                        seen_emails.add(email)
                        params = getattr(att, 'params', {}) or {}
                        cn = str(params.get('CN') or '').strip()
                        partstat = str(params.get('PARTSTAT') or 'NEEDS-ACTION').strip().upper()
                        attendees.append({
                            'email': email,
                            'name': cn or email,
                            'status': partstat_map.get(partstat, 'pending'),
                        })

                return RemoteCalEvent(
                    href=href,
                    etag=etag,
                    uid=uid,
                    title=summary[:200],
                    description=description,
                    location=location[:255],
                    start_time=start_dt,
                    end_time=end_dt,
                    recurrence_type=rec_type,
                    recurrence_interval=rec_interval,
                    recurrence_end_date=rec_end,
                    recurrence_days=rec_days,
                    attendees=attendees,
                )
        except Exception as exc:
            logger.warning('Failed to parse CalDAV ICS from %s: %s', href, exc)
        return None

    def build_ics_for_event(self, event) -> tuple[str, str]:
        uid = (getattr(event, 'ical_uid', None) or '').strip() or f'prismateams-{uuid.uuid4().hex}'
        now_utc = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        lines = [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'PRODID:-//PrismaTeams//Nextcloud CalDAV//EN',
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{now_utc}',
            f'DTSTART:{_format_ics_dt(event.start_time)}',
            f'DTEND:{_format_ics_dt(event.end_time)}',
            f'SUMMARY:{_escape_ics_text(event.title)}',
        ]
        if getattr(event, 'description', None):
            lines.append(f'DESCRIPTION:{_escape_ics_text(event.description)}')
        if getattr(event, 'location', None):
            lines.append(f'LOCATION:{_escape_ics_text(event.location)}')

        creator = getattr(event, 'creator', None)
        if creator and getattr(creator, 'email', None):
            cn = (getattr(creator, 'full_name', None) or creator.email).replace('"', '').replace(';', ' ')
            lines.append(f'ORGANIZER;CN="{cn}":mailto:{creator.email}')

        status_to_partstat = {
            'accepted': 'ACCEPTED',
            'declined': 'DECLINED',
            'tentative': 'TENTATIVE',
            'pending': 'NEEDS-ACTION',
        }
        seen_att_emails: set[str] = set()
        for part in getattr(event, 'participants', None) or []:
            if getattr(part, 'status', None) == 'removed':
                continue
            u = getattr(part, 'user', None)
            email = (getattr(u, 'email', None) or '').strip().lower()
            if not email or email in seen_att_emails:
                continue
            seen_att_emails.add(email)
            cn = (getattr(u, 'full_name', None) or email).replace('"', '').replace(';', ' ')
            ps = status_to_partstat.get(getattr(part, 'status', 'pending'), 'NEEDS-ACTION')
            lines.append(f'ATTENDEE;CN="{cn}";PARTSTAT={ps};ROLE=REQ-PARTICIPANT:mailto:{email}')

        raw_ext = getattr(event, 'remote_attendees_json', None)
        if raw_ext:
            try:
                ext_list = json.loads(raw_ext)
            except (TypeError, ValueError, json.JSONDecodeError):
                ext_list = []
            if isinstance(ext_list, list):
                for item in ext_list:
                    if not isinstance(item, dict):
                        continue
                    email = (item.get('email') or '').strip().lower()
                    if not email or email in seen_att_emails:
                        continue
                    seen_att_emails.add(email)
                    cn = (item.get('name') or email).replace('"', '').replace(';', ' ')
                    ps = status_to_partstat.get(item.get('status', 'pending'), 'NEEDS-ACTION')
                    lines.append(f'ATTENDEE;CN="{cn}";PARTSTAT={ps};ROLE=REQ-PARTICIPANT:mailto:{email}')

        rec = (getattr(event, 'recurrence_type', None) or 'none').lower()
        if rec in ('daily', 'weekly', 'monthly', 'yearly') and not getattr(event, 'is_recurring_instance', False):
            rule = f'FREQ={rec.upper()};INTERVAL={max(1, int(getattr(event, "recurrence_interval", 1) or 1))}'
            if getattr(event, 'recurrence_end_date', None):
                rule += f';UNTIL={event.recurrence_end_date.strftime("%Y%m%dT235959Z")}'
            lines.append(f'RRULE:{rule}')
        lines.extend(['END:VEVENT', 'END:VCALENDAR', ''])
        return uid, '\r\n'.join(lines)

    def upsert_event(self, calendar_url: str, event) -> tuple[str, str, str]:
        uid, ics_body = self.build_ics_for_event(event)
        href = (getattr(event, 'remote_href', None) or '').strip()
        is_new = not href
        if is_new:
            href = f'{calendar_url.rstrip("/")}/{quote(uid, safe="")}.ics'
        headers = {'Content-Type': 'text/calendar; charset=utf-8'}
        etag = (getattr(event, 'remote_etag', None) or '').strip()
        if not is_new and etag:
            headers['If-Match'] = f'"{etag}"'
        resp = self._session.put(href, data=ics_body.encode('utf-8'), headers=headers, timeout=30)
        if resp.status_code not in (200, 201, 204):
            raise ConnectionError(f'nextcloud_caldav_put_failed:{resp.status_code}')
        new_etag = _strip_etag(resp.headers.get('ETag'))
        return uid, href, new_etag

    def delete_event(self, remote_href: str, etag: str | None = None) -> None:
        if not remote_href:
            return
        headers = {}
        if etag:
            headers['If-Match'] = f'"{etag}"'
        resp = self._session.delete(remote_href, headers=headers, timeout=30)
        if resp.status_code not in (200, 204, 404):
            raise ConnectionError(f'nextcloud_caldav_delete_failed:{resp.status_code}')
