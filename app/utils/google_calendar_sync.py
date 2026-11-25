"""Google Calendar API v3 OAuth & Sync (readonly, inkl. geteilter Kalender)."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlencode

import requests
from flask import session
from flask_login import current_user

from app import db
from app.models.calendar import CalendarEvent, CalendarSyncSource
from app.models.cloud_import import CloudImportConnection
from app.utils.cloud_import.base import decrypt_credentials, encrypt_credentials
from app.utils.common import as_portal_wall_time
from app.utils.integrations import (
    get_google_credentials,
    google_oauth_configured,
    google_oauth_redirect_uri,
)

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly'
GOOGLE_CALENDAR_PROVIDER = 'google_calendar'
GOOGLE_CALENDAR_URL_PREFIX = 'google-calendar://'
SESSION_STATE_KEY = 'calendar_google_oauth_state'

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'
GOOGLE_CALENDAR_API_BASE = 'https://www.googleapis.com/calendar/v3'

_TIMEOUT = 30


class GoogleCalendarAuthError(RuntimeError):
    """Wird geworfen, wenn OAuth-Tokens fehlen, widerrufen wurden oder Scope fehlt."""


def is_google_calendar_url(url: Optional[str]) -> bool:
    return bool(url and url.startswith(GOOGLE_CALENDAR_URL_PREFIX))


def extract_google_calendar_id(url: str) -> str:
    if not is_google_calendar_url(url):
        raise ValueError('Keine gültige Google-Kalender-Sync-URL')
    return url[len(GOOGLE_CALENDAR_URL_PREFIX):].strip()


def get_google_calendar_oauth_url() -> str:
    """Erstellt die Google-OAuth-URL für schreibgeschützten Kalenderzugriff."""
    if not google_oauth_configured():
        raise ValueError('google_not_configured')
    creds = get_google_credentials()
    state = os.urandom(16).hex()
    session[SESSION_STATE_KEY] = state
    params = {
        'client_id': creds['client_id'],
        'response_type': 'code',
        'redirect_uri': google_oauth_redirect_uri(),
        'scope': f'openid email {GOOGLE_CALENDAR_SCOPE}',
        'state': state,
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
    }
    return f'{GOOGLE_AUTH_URL}?{urlencode(params)}'


def save_google_calendar_connection(user, token_result: dict) -> Optional[CloudImportConnection]:
    """Speichert/aktualisiert eine Google-Calendar-OAuth-Verbindung für den Benutzer."""
    if not user or not getattr(user, 'id', None) or not token_result.get('access_token'):
        return None

    payload = {
        'access_token': token_result['access_token'],
        'refresh_token': token_result.get('refresh_token'),
        'expires_at': token_result.get('expires_at'),
        'scope': token_result.get('scope') or GOOGLE_CALENDAR_SCOPE,
    }
    existing = (
        CloudImportConnection.query
        .filter_by(user_id=user.id, provider=GOOGLE_CALENDAR_PROVIDER)
        .order_by(CloudImportConnection.id.desc())
        .first()
    )
    email = (token_result.get('email') or '').strip()
    display = f'Google Calendar ({email})' if email else 'Google Calendar'

    if existing:
        if not payload.get('refresh_token'):
            old = decrypt_credentials(existing.credentials_enc)
            if old.get('refresh_token'):
                payload['refresh_token'] = old['refresh_token']
        existing.credentials_enc = encrypt_credentials(payload)
        existing.display_name = display
        existing.updated_at = datetime.utcnow()
        return existing

    conn = CloudImportConnection(
        user_id=user.id,
        provider=GOOGLE_CALENDAR_PROVIDER,
        display_name=display,
        credentials_enc=encrypt_credentials(payload),
    )
    db.session.add(conn)
    return conn


def handle_google_calendar_callback(code: str, state: str) -> CloudImportConnection:
    """Verarbeitet den Google-OAuth-Callback für die Kalender-Synchronisation."""
    if state != session.get(SESSION_STATE_KEY):
        raise ValueError('invalid_state')
    session.pop(SESSION_STATE_KEY, None)

    if not google_oauth_configured():
        raise ValueError('google_not_configured')

    creds = get_google_credentials()
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': google_oauth_redirect_uri(),
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    token_data = resp.json()
    access_token = token_data.get('access_token')
    if not access_token:
        raise RuntimeError('Kein Access-Token von Google erhalten')

    email = ''
    try:
        ui = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        if ui.status_code == 200:
            email = (ui.json().get('email') or '').strip().lower()
    except Exception:
        pass

    expires_in = int(token_data.get('expires_in') or 3600)
    token_result = {
        'access_token': access_token,
        'refresh_token': token_data.get('refresh_token'),
        'expires_at': (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat(),
        'scope': token_data.get('scope') or GOOGLE_CALENDAR_SCOPE,
        'email': email,
    }
    conn = save_google_calendar_connection(current_user, token_result)
    db.session.commit()
    return conn


def get_google_calendar_connection(user_id: int) -> Optional[CloudImportConnection]:
    if not user_id:
        return None
    return (
        CloudImportConnection.query
        .filter_by(user_id=user_id, provider=GOOGLE_CALENDAR_PROVIDER)
        .order_by(CloudImportConnection.id.desc())
        .first()
    )


def _get_valid_access_token(conn: CloudImportConnection) -> str:
    """Gibt ein gültiges Access-Token zurück und erneuert es bei Bedarf über den Refresh-Token."""
    data = decrypt_credentials(conn.credentials_enc)
    access_token = data.get('access_token') or ''
    refresh_token = data.get('refresh_token') or ''
    expires_at_raw = data.get('expires_at')

    expires_at = None
    if expires_at_raw:
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except ValueError:
            expires_at = None

    if access_token and expires_at and datetime.utcnow() < expires_at - timedelta(seconds=60):
        return access_token

    if not refresh_token:
        if access_token and not expires_at:
            return access_token
        raise GoogleCalendarAuthError('Google-Token abgelaufen und kein Refresh-Token vorhanden. Bitte neu verbinden.')

    creds = get_google_credentials()
    if not creds.get('client_id') or not creds.get('client_secret'):
        raise GoogleCalendarAuthError('Google OAuth ist nicht konfiguriert.')

    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': creds['client_id'],
            'client_secret': creds['client_secret'],
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code in (400, 401):
        raise GoogleCalendarAuthError('Google-Berechtigung abgelaufen oder widerrufen. Bitte neu verbinden.')
    resp.raise_for_status()
    refreshed = resp.json()

    new_access = refreshed.get('access_token')
    if not new_access:
        raise GoogleCalendarAuthError('Kein neues Access-Token von Google erhalten.')

    new_expires = datetime.utcnow() + timedelta(seconds=int(refreshed.get('expires_in') or 3600))
    data['access_token'] = new_access
    data['expires_at'] = new_expires.isoformat()
    if refreshed.get('scope'):
        data['scope'] = refreshed['scope']
    conn.credentials_enc = encrypt_credentials(data)
    conn.updated_at = datetime.utcnow()
    db.session.commit()
    return new_access


def _google_api_get(conn: CloudImportConnection, path: str, params: Optional[dict] = None) -> dict:
    """Führt einen GET-Request gegen die Google Calendar API v3 aus."""
    token = _get_valid_access_token(conn)
    url = f'{GOOGLE_CALENDAR_API_BASE}{path}'
    resp = requests.get(
        url,
        params=params or {},
        headers={'Authorization': f'Bearer {token}'},
        timeout=_TIMEOUT,
    )
    if resp.status_code in (401, 403):
        raise GoogleCalendarAuthError(
            f'Google Kalender-Zugriff verweigert ({resp.status_code}). Bitte Google-Konto neu verbinden.'
        )
    resp.raise_for_status()
    return resp.json()


def list_google_calendars(user_id: int) -> list[dict]:
    """Listet alle Google-Kalender des Benutzers auf (eigene und geteilte/abonnierte)."""
    conn = get_google_calendar_connection(user_id)
    if not conn:
        return []

    calendars: list[dict] = []
    page_token: Optional[str] = None
    while True:
        params = {'minAccessRole': 'freeBusyReader', 'maxResults': 250}
        if page_token:
            params['pageToken'] = page_token
        payload = _google_api_get(conn, '/users/me/calendarList', params=params)
        for item in payload.get('items') or []:
            cal_id = (item.get('id') or '').strip()
            if not cal_id:
                continue
            calendars.append({
                'id': cal_id,
                'summary': (item.get('summaryOverride') or item.get('summary') or cal_id).strip(),
                'description': (item.get('description') or '').strip(),
                'access_role': item.get('accessRole') or 'reader',
                'primary': bool(item.get('primary')),
                'background_color': item.get('backgroundColor') or '#0d6efd',
            })
        page_token = payload.get('nextPageToken')
        if not page_token:
            break

    calendars.sort(key=lambda c: (not c['primary'], c['summary'].lower()))
    return calendars


def _parse_google_dt(dt_obj: Optional[dict], *, is_end: bool = False) -> Optional[datetime]:
    """Konvertiert ein Google-Event-Start/End-Objekt in eine naive Portal-Wandzeit."""
    if not isinstance(dt_obj, dict):
        return None
    if dt_obj.get('dateTime'):
        raw = dt_obj['dateTime'].replace('Z', '+00:00')
        parsed = datetime.fromisoformat(raw)
        return as_portal_wall_time(parsed)
    if dt_obj.get('date'):
        d = date.fromisoformat(dt_obj['date'])
        if is_end:
            # Google liefert bei Ganztagesterminen end.date exklusiv (Folgetag)
            d = d - timedelta(days=1)
            return datetime.combine(d, datetime.max.time().replace(microsecond=0))
        return datetime.combine(d, datetime.min.time())
    return None


def _parse_google_rrule(
    recurrence_list: Optional[list[str]],
    start_time: Optional[datetime] = None,
) -> dict:
    """Parst RRULE-Einträge aus Google Calendar Events in CalendarEvent-Felder."""
    result = {
        'recurrence_type': 'none',
        'recurrence_end_date': None,
        'recurrence_interval': 1,
        'recurrence_days': None,
    }
    if not recurrence_list:
        return result

    rrule_line = next((r for r in recurrence_list if isinstance(r, str) and r.upper().startswith('RRULE:')), None)
    if not rrule_line:
        return result

    parts = {}
    for segment in rrule_line[6:].split(';'):
        if '=' in segment:
            k, v = segment.split('=', 1)
            parts[k.upper()] = v

    freq_map = {
        'DAILY': 'daily',
        'WEEKLY': 'weekly',
        'MONTHLY': 'monthly',
        'YEARLY': 'yearly',
    }
    result['recurrence_type'] = freq_map.get(parts.get('FREQ', '').upper(), 'none')

    if parts.get('INTERVAL'):
        try:
            result['recurrence_interval'] = max(1, int(parts['INTERVAL']))
        except ValueError:
            pass

    if parts.get('BYDAY'):
        day_map = {'MO': '0', 'TU': '1', 'WE': '2', 'TH': '3', 'FR': '4', 'SA': '5', 'SU': '6'}
        days = []
        for token in parts['BYDAY'].split(','):
            code = token.strip().upper()[-2:]
            if code in day_map:
                days.append(day_map[code])
        result['recurrence_days'] = ','.join(days) or None

    if parts.get('UNTIL'):
        raw_until = parts['UNTIL'].strip()
        try:
            if len(raw_until) == 8 and raw_until.isdigit():
                d = date(int(raw_until[:4]), int(raw_until[4:6]), int(raw_until[6:8]))
                result['recurrence_end_date'] = datetime.combine(d, datetime.max.time().replace(microsecond=0))
            else:
                norm = raw_until.replace('Z', '+00:00')
                if len(norm) >= 15 and 'T' in norm and '-' not in norm[:8]:
                    # Kompaktformat YYYYMMDDTHHMMSS(+00:00)
                    dt = datetime.strptime(norm[:15], '%Y%m%dT%H%M%S')
                    result['recurrence_end_date'] = dt
                else:
                    result['recurrence_end_date'] = as_portal_wall_time(datetime.fromisoformat(norm))
        except Exception:
            pass
    elif parts.get('COUNT') and start_time is not None:
        try:
            count = max(1, int(parts['COUNT']))
            interval = result['recurrence_interval']
            steps = count - 1
            rtype = result['recurrence_type']
            if rtype == 'daily':
                end_dt = start_time + timedelta(days=steps * interval)
            elif rtype == 'weekly':
                end_dt = start_time + timedelta(weeks=steps * interval)
            elif rtype == 'monthly':
                from dateutil.relativedelta import relativedelta
                end_dt = start_time + relativedelta(months=steps * interval)
            elif rtype == 'yearly':
                from dateutil.relativedelta import relativedelta
                end_dt = start_time + relativedelta(years=steps * interval)
            else:
                end_dt = start_time
            result['recurrence_end_date'] = datetime.combine(
                end_dt.date(), datetime.max.time().replace(microsecond=0)
            )
        except Exception:
            pass

    return result


def _parse_google_event(item: dict, source_id: int, *, single_events: bool = True) -> Optional[dict]:
    """Konvertiert ein Google-Calendar-Event-JSON in ein CalendarEvent-Dict."""
    if item.get('status') == 'cancelled':
        return None

    start_time = _parse_google_dt(item.get('start'), is_end=False)
    if not start_time:
        return None
    end_time = _parse_google_dt(item.get('end'), is_end=True)
    if not end_time or end_time < start_time:
        if (item.get('start') or {}).get('date'):
            end_time = datetime.combine(start_time.date(), datetime.max.time().replace(microsecond=0))
        else:
            end_time = start_time + timedelta(hours=1)

    if single_events:
        # Bei singleEvents=true teilen sich alle Instanzen einer Serie dieselbe iCalUID,
        # aber jede Instanz besitzt eine eindeutige Google-Event-ID.
        uid_raw = (item.get('id') or item.get('iCalUID') or '').strip()
        rrule = {
            'recurrence_type': 'none',
            'recurrence_end_date': None,
            'recurrence_interval': 1,
            'recurrence_days': None,
        }
    else:
        uid_raw = (item.get('iCalUID') or item.get('id') or '').strip()
        rrule = _parse_google_rrule(item.get('recurrence'), start_time=start_time)

    if not uid_raw:
        uid_raw = f'gcal-{source_id}-{start_time.isoformat()}'

    title = (item.get('summary') or 'Unbenannter Termin').strip() or 'Unbenannter Termin'
    description = (item.get('description') or '').strip() or None
    location = (item.get('location') or '').strip() or None

    return {
        'title': title[:200],
        'description': description,
        'start_time': start_time,
        'end_time': end_time,
        'location': location[:255] if location else None,
        'ical_uid': uid_raw[:255],
        'recurrence_type': rrule['recurrence_type'],
        'recurrence_end_date': rrule['recurrence_end_date'],
        'recurrence_interval': rrule['recurrence_interval'],
        'recurrence_days': rrule['recurrence_days'],
    }


def sync_google_calendar_source(source: CalendarSyncSource, user_id=None, calendar_id=None):
    """
    Synchronisiert eine google-calendar:// CalendarSyncSource über die Google Calendar API v3.

    Returns:
        (success: bool, message: str, created: int, updated: int, deleted: int)
    """
    owner_id = user_id or source.created_by
    conn = get_google_calendar_connection(source.created_by) or get_google_calendar_connection(owner_id)
    if not conn:
        error_msg = 'Keine Google-Kalender-Verbindung für den Ersteller vorhanden. Bitte Google-Konto verbinden.'
        source.last_error = error_msg
        db.session.commit()
        return False, error_msg, 0, 0, 0

    try:
        google_cal_id = extract_google_calendar_id(source.url)
        encoded_cal_id = quote(google_cal_id, safe='')

        now_utc = datetime.utcnow()
        time_min = (now_utc - timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
        time_max = (now_utc + timedelta(days=730)).strftime('%Y-%m-%dT%H:%M:%SZ')

        items: list[dict] = []
        page_token: Optional[str] = None
        while True:
            params = {
                'singleEvents': 'true',
                'showDeleted': 'false',
                'timeMin': time_min,
                'timeMax': time_max,
                'maxResults': 2500,
            }
            if page_token:
                params['pageToken'] = page_token
            payload = _google_api_get(conn, f'/calendars/{encoded_cal_id}/events', params=params)
            items.extend(payload.get('items') or [])
            page_token = payload.get('nextPageToken')
            if not page_token:
                break

        seen_uids: set[str] = set()
        created = 0
        updated = 0

        for item in items:
            parsed = _parse_google_event(item, source.id, single_events=True)
            if not parsed:
                continue

            uid = parsed['ical_uid']
            if uid in seen_uids:
                continue
            seen_uids.add(uid)

            existing = CalendarEvent.query.filter_by(
                sync_source_id=source.id,
                ical_uid=uid,
            ).first()

            if existing:
                existing.title = parsed['title']
                existing.description = parsed['description']
                existing.start_time = parsed['start_time']
                existing.end_time = parsed['end_time']
                existing.location = parsed['location']
                existing.recurrence_type = parsed['recurrence_type']
                existing.recurrence_end_date = parsed['recurrence_end_date']
                existing.recurrence_interval = parsed['recurrence_interval']
                existing.recurrence_days = parsed['recurrence_days']
                existing.updated_at = datetime.utcnow()
                if calendar_id and existing.calendar_id != calendar_id:
                    existing.calendar_id = calendar_id
                updated += 1
            else:
                event = CalendarEvent(
                    title=parsed['title'],
                    description=parsed['description'],
                    start_time=parsed['start_time'],
                    end_time=parsed['end_time'],
                    location=parsed['location'],
                    created_by=owner_id,
                    recurrence_type=parsed['recurrence_type'],
                    recurrence_end_date=parsed['recurrence_end_date'],
                    recurrence_interval=parsed['recurrence_interval'],
                    recurrence_days=parsed['recurrence_days'],
                    is_recurring_instance=False,
                    sync_source_id=source.id,
                    ical_uid=uid,
                    calendar_id=calendar_id,
                )
                db.session.add(event)
                created += 1

        existing_events = CalendarEvent.query.filter_by(sync_source_id=source.id).all()
        deleted = 0
        for event in existing_events:
            if event.ical_uid not in seen_uids:
                db.session.delete(event)
                deleted += 1

        source.last_synced_at = datetime.utcnow()
        source.last_error = None
        db.session.commit()

        msg = f'Sync OK: {created} neu, {updated} aktualisiert, {deleted} entfernt.'
        return True, msg, created, updated, deleted

    except Exception as exc:
        db.session.rollback()
        error_msg = str(exc)[:1000]
        try:
            source.last_error = error_msg
            db.session.commit()
        except Exception:
            db.session.rollback()
        logger.exception('Google Calendar sync failed for source %s', source.id)
        return False, error_msg, 0, 0, 0
