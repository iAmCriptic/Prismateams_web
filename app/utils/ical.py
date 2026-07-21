"""
iCal Import/Export Utility Functions
"""

from icalendar import Calendar, Event as ICalEvent
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from app.models.calendar import CalendarEvent
from pytz import UTC
import logging
import requests

logger = logging.getLogger(__name__)

MAX_ICAL_BYTES = 5 * 1024 * 1024  # 5 MB
FETCH_TIMEOUT_SECONDS = 30


def export_event_to_ical(event: CalendarEvent) -> ICalEvent:
    """
    Konvertiert ein CalendarEvent zu einem iCal Event.
    
    Args:
        event: Das CalendarEvent-Objekt
    
    Returns:
        ICalEvent-Objekt
    """
    ical_event = ICalEvent()
    ical_event.add('summary', event.title)
    ical_event.add('dtstart', event.start_time)
    ical_event.add('dtend', event.end_time)
    
    if event.description:
        ical_event.add('description', event.description)
    
    if event.location:
        ical_event.add('location', event.location)
    
    # Wiederkehrende Termine
    if event.is_master_event and event.recurrence_type != 'none':
        rrule = generate_rrule(event)
        if rrule:
            ical_event.add('rrule', rrule)
    
    # UID für eindeutige Identifikation
    if event.ical_uid:
        ical_event.add('uid', event.ical_uid)
    else:
        ical_event.add('uid', f'event-{event.id}@prismateams')
    
    # Erstellt/Geändert
    ical_event.add('created', event.created_at)
    ical_event.add('last-modified', event.updated_at)
    
    return ical_event


def generate_rrule(event: CalendarEvent):
    """
    Generiert eine RRULE für wiederkehrende Termine.
    
    Args:
        event: Das CalendarEvent mit Wiederholungsinformationen
    
    Returns:
        RRULE-Dictionary oder None
    """
    if event.recurrence_type == 'none':
        return None
    
    rrule = {}
    
    # FREQ (Frequency)
    freq_map = {
        'daily': 'DAILY',
        'weekly': 'WEEKLY',
        'monthly': 'MONTHLY',
        'yearly': 'YEARLY'
    }
    rrule['FREQ'] = freq_map.get(event.recurrence_type)
    
    # INTERVAL
    if event.recurrence_interval > 1:
        rrule['INTERVAL'] = event.recurrence_interval
    
    # BYDAY für wöchentliche Wiederholung mit spezifischen Wochentagen
    if event.recurrence_type == 'weekly' and event.recurrence_days:
        days = [int(d) for d in event.recurrence_days.split(',')]
        day_map = {0: 'MO', 1: 'TU', 2: 'WE', 3: 'TH', 4: 'FR', 5: 'SA', 6: 'SU'}
        byday = [day_map.get(d) for d in days if d in day_map]
        if byday:
            rrule['BYDAY'] = ','.join(byday)
    
    # UNTIL (Enddatum)
    if event.recurrence_end_date:
        rrule['UNTIL'] = event.recurrence_end_date
    
    return rrule


def generate_ical_feed(events, feed_name='Kalender') -> str:
    """
    Generiert einen vollständigen iCal-String aus einer Liste von Events.
    
    Args:
        events: Liste von CalendarEvent-Objekten
        feed_name: Name des Kalenders
    
    Returns:
        iCal-String
    """
    cal = Calendar()
    cal.add('prodid', '-//Prismateams//Kalender//DE')
    cal.add('version', '2.0')
    cal.add('calscale', 'GREGORIAN')
    cal.add('X-WR-CALNAME', feed_name)
    cal.add('X-WR-TIMEZONE', 'Europe/Berlin')
    
    for event in events:
        ical_event = export_event_to_ical(event)
        cal.add_component(ical_event)
    
    return cal.to_ical().decode('utf-8')


def normalize_ical_url(url: str) -> str:
    """Normalisiert webcal:// zu https:// und trimmt Whitespace."""
    if not url:
        return ''
    cleaned = url.strip()
    lower = cleaned.lower()
    if lower.startswith('webcal://'):
        return 'https://' + cleaned[9:]
    if lower.startswith('webcals://'):
        return 'https://' + cleaned[10:]
    return cleaned


def fetch_ical_from_url(url: str) -> str:
    """Lädt eine iCal-Datei von einer URL (mit Timeout und Größenlimit)."""
    normalized = normalize_ical_url(url)
    if not normalized.lower().startswith(('http://', 'https://')):
        raise ValueError('Ungültige URL. Erlaubt sind http(s):// oder webcal://')

    response = requests.get(
        normalized,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={'User-Agent': 'Prismateams-Calendar-Sync/1.0'},
        stream=True,
    )
    response.raise_for_status()

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_ICAL_BYTES:
            raise ValueError('iCal-Datei ist zu groß (max. 5 MB).')
        chunks.append(chunk)

    raw = b''.join(chunks)
    # Versuche UTF-8, Fallback latin-1
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', errors='replace')


def _parse_vevent_component(component):
    """Parst ein VEVENT zu einem Dict mit Feldern für CalendarEvent."""
    title = str(component.get('summary', 'Unbenannter Termin'))

    dtstart = component.get('dtstart')
    dtend = component.get('dtend')
    if not dtstart:
        return None

    start_time = dtstart.dt
    if not isinstance(start_time, datetime):
        start_time = datetime.combine(start_time, datetime.min.time())

    if dtend:
        end_time = dtend.dt
        if not isinstance(end_time, datetime):
            end_time = datetime.combine(end_time, datetime.max.time())
    else:
        end_time = start_time + timedelta(hours=1)

    description = str(component.get('description', '')) or None
    location = str(component.get('location', '')) or None

    uid_raw = component.get('uid')
    ical_uid = str(uid_raw) if uid_raw else None

    rrule = component.get('rrule')
    recurrence_type = 'none'
    recurrence_end_date = None
    recurrence_interval = 1
    recurrence_days = None

    if rrule:
        rrule_dict = dict(rrule)
        freq = rrule_dict.get('FREQ', [None])[0]

        freq_map = {
            'DAILY': 'daily',
            'WEEKLY': 'weekly',
            'MONTHLY': 'monthly',
            'YEARLY': 'yearly'
        }
        recurrence_type = freq_map.get(freq, 'none')

        if 'INTERVAL' in rrule_dict:
            recurrence_interval = int(rrule_dict['INTERVAL'][0])

        if 'BYDAY' in rrule_dict:
            byday = rrule_dict['BYDAY']
            day_map = {'MO': 0, 'TU': 1, 'WE': 2, 'TH': 3, 'FR': 4, 'SA': 5, 'SU': 6}
            days = [str(day_map.get(d, '')) for d in byday if d in day_map]
            recurrence_days = ','.join([d for d in days if d]) or None

        if 'UNTIL' in rrule_dict:
            until = rrule_dict['UNTIL'][0]
            if isinstance(until, datetime):
                recurrence_end_date = until

    return {
        'title': title[:200],
        'description': description,
        'start_time': start_time,
        'end_time': end_time,
        'location': location[:255] if location else None,
        'ical_uid': ical_uid[:255] if ical_uid else None,
        'recurrence_type': recurrence_type,
        'recurrence_end_date': recurrence_end_date,
        'recurrence_interval': recurrence_interval,
        'recurrence_days': recurrence_days,
    }


def import_events_from_ical(ical_data: str, user_id: int):
    """
    Importiert Events aus einem iCal-String.
    
    Args:
        ical_data: iCal-String
        user_id: ID des Benutzers, der die Events importiert
    
    Returns:
        Liste von CalendarEvent-Objekten (noch nicht gespeichert)
    """
    cal = Calendar.from_ical(ical_data)
    events = []

    for component in cal.walk():
        if component.name != 'VEVENT':
            continue
        parsed = _parse_vevent_component(component)
        if not parsed:
            continue

        event = CalendarEvent(
            title=parsed['title'],
            description=parsed['description'],
            start_time=parsed['start_time'],
            end_time=parsed['end_time'],
            location=parsed['location'],
            created_by=user_id,
            recurrence_type=parsed['recurrence_type'],
            recurrence_end_date=parsed['recurrence_end_date'],
            recurrence_interval=parsed['recurrence_interval'],
            recurrence_days=parsed['recurrence_days'],
            is_recurring_instance=False,
            ical_uid=parsed['ical_uid'],
        )
        events.append(event)

    return events


def sync_calendar_source(source, user_id=None):
    """
    Synchronisiert eine CalendarSyncSource: Upsert per ical_uid, entfernt fehlende UIDs.

    Returns:
        (success: bool, message: str, created: int, updated: int, deleted: int)
    """
    from app import db
    from app.models.calendar import CalendarSyncSource

    if not isinstance(source, CalendarSyncSource):
        raise TypeError('source must be a CalendarSyncSource')

    owner_id = user_id or source.created_by

    try:
        ical_data = fetch_ical_from_url(source.url)
        cal = Calendar.from_ical(ical_data)

        seen_uids = set()
        created = 0
        updated = 0

        for component in cal.walk():
            if component.name != 'VEVENT':
                continue
            parsed = _parse_vevent_component(component)
            if not parsed:
                continue

            uid = parsed['ical_uid']
            if not uid:
                # Ohne UID: stabile Fallback-UID aus Inhalt
                uid = f"sync-{source.id}-{parsed['title']}-{parsed['start_time'].isoformat()}"
                parsed['ical_uid'] = uid[:255]

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
                )
                db.session.add(event)
                created += 1

        # Entferne Events dieser Source, die nicht mehr im Feed sind
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
        logger.exception('Calendar sync failed for source %s', source.id)
        return False, error_msg, 0, 0, 0


def sync_all_active_sources():
    """Synchronisiert alle aktiven CalendarSyncSources. Returns summary dict."""
    from app.models.calendar import CalendarSyncSource

    sources = CalendarSyncSource.query.filter_by(is_active=True).all()
    results = {'ok': 0, 'fail': 0, 'errors': []}
    for source in sources:
        success, message, *_ = sync_calendar_source(source)
        if success:
            results['ok'] += 1
        else:
            results['fail'] += 1
            results['errors'].append({'id': source.id, 'name': source.name, 'error': message})
    return results
