"""Helpers for Dienstplan: permissions, month bootstrap, hours & overtime."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Iterable

import logging

from app import db
from sqlalchemy import inspect, text

from app.models.duty_roster import (
    MONTH_NAMES_DE,
    WEEKDAY_NAMES_DE,
    DutyExternalPerson,
    DutyPersonConfig,
    DutyRoster,
    DutyRosterColumn,
    DutyRosterDay,
    DutyRosterEntry,
    DutyRosterPlanner,
    DutyTimeEntry,
    ENTRY_TYPE_SHIFT,
    TIME_ENTRY_WORK,
)
from app.models.team import Team, TeamMember
from app.utils.multi_mailboxes import can_manage_team
from app.utils.team_module_settings import is_team_section_enabled
from app.utils.user_content_access import user_may_access_public

# Alternating KW background colors (Excel-Screenshot: Rosa / Hellblau / …)
KW_COLORS = ('#f4c2c8', '#b8d4f0', '#ffe0b2', '#d4c4f0', '#c8e6c9')

logger = logging.getLogger(__name__)
_duty_schema_ready = False


def ensure_duty_schema() -> bool:
    """Neue Tabellen/Spalten für bestehende DBs nachziehen.

    Returns True wenn Schema nutzbar ist. Fehler werden geloggt (kein stilles pass).
    """
    global _duty_schema_ready
    if _duty_schema_ready:
        return True

    try:
        db.create_all()
    except Exception:
        logger.exception('duty_roster: db.create_all() fehlgeschlagen')
        return False

    try:
        insp = inspect(db.engine)
        table_names = set(insp.get_table_names())
        if 'duty_person_configs' not in table_names:
            # create_all hätte die Tabelle anlegen sollen — ohne sie kein Dienstplan
            logger.error(
                'duty_roster: Tabelle duty_person_configs fehlt nach create_all'
            )
            return False

        alters: list[str] = []
        cols = {c['name'] for c in insp.get_columns('duty_person_configs')}
        if 'valid_from' not in cols:
            alters.append('ALTER TABLE duty_person_configs ADD COLUMN valid_from DATE')
        if 'valid_until' not in cols:
            alters.append('ALTER TABLE duty_person_configs ADD COLUMN valid_until DATE')

        if 'duty_roster_columns' in table_names:
            col_cols = {c['name'] for c in insp.get_columns('duty_roster_columns')}
            if 'external_person_id' not in col_cols:
                alters.append(
                    'ALTER TABLE duty_roster_columns ADD COLUMN external_person_id INTEGER'
                )

        for stmt in alters:
            try:
                with db.engine.begin() as conn:
                    conn.execute(text(stmt))
                logger.info('duty_roster: Schema aktualisiert (%s)', stmt)
            except Exception:
                logger.exception('duty_roster: Schema-ALTER fehlgeschlagen: %s', stmt)
                return False

        _duty_schema_ready = True
        return True
    except Exception:
        logger.exception('duty_roster: Schema-Prüfung fehlgeschlagen')
        return False


def user_team_ids(user) -> list[int]:
    if not user or not getattr(user, 'id', None):
        return []
    return [m.team_id for m in TeamMember.query.filter_by(user_id=user.id).all()]


def get_user_teams(user) -> list[Team]:
    ids = user_team_ids(user)
    if not ids:
        return []
    return Team.query.filter(Team.id.in_(ids)).order_by(Team.name).all()


def can_plan_team(user, team_id: int) -> bool:
    """Admin, team leader, or explicit planner grant."""
    if not user or not team_id:
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'is_super_admin', False):
        return True
    if can_manage_team(user, team_id):
        return True
    return (
        DutyRosterPlanner.query.filter_by(team_id=team_id, user_id=user.id).first() is not None
    )


def can_view_team_roster(user, team_id: int) -> bool:
    if not user or not team_id:
        return False
    if getattr(user, 'is_admin', False) or getattr(user, 'is_super_admin', False):
        return True
    if not is_team_section_enabled(team_id, 'duty_roster'):
        # Still allow planners/leaders to open settings even if section off? Keep strict: members need section on.
        if can_plan_team(user, team_id):
            return True
        return False
    return team_id in user_team_ids(user)


def can_view_published_roster(user, roster: DutyRoster) -> bool:
    if not roster or not roster.is_published:
        return False
    if not user:
        return False
    if getattr(user, 'is_admin', False):
        return True
    return bool(user_may_access_public(user))


def ensure_person_config(team_id: int, user_id: int) -> DutyPersonConfig:
    cfg = DutyPersonConfig.query.filter_by(team_id=team_id, user_id=user_id).first()
    if cfg:
        return cfg
    cfg = DutyPersonConfig(
        team_id=team_id,
        user_id=user_id,
        available_for_roster=True,
        vacation_days_used=0.0,
    )
    db.session.add(cfg)
    return cfg


def adjust_vacation_days_for_entry_change(
    team_id: int,
    user_id: int | None,
    *,
    was_vacation: bool,
    is_vacation: bool,
    days: float = 1.0,
) -> float | None:
    """Zählt Resturlaub: URLAUB → used +1; Wechsel weg von URLAUB → used −1.

    Gibt den neuen Resturlaub zurück (oder None ohne Soll/Stammdaten).
    """
    if not user_id or was_vacation == is_vacation:
        cfg = (
            DutyPersonConfig.query.filter_by(team_id=team_id, user_id=user_id).first()
            if user_id
            else None
        )
        return cfg.vacation_days_remaining if cfg else None

    cfg = ensure_person_config(team_id, user_id)
    used = float(cfg.vacation_days_used or 0.0)
    if is_vacation and not was_vacation:
        used += float(days)
    elif was_vacation and not is_vacation:
        used = max(0.0, used - float(days))
    cfg.vacation_days_used = round(used, 2)
    return cfg.vacation_days_remaining


def get_or_create_person_configs(team_id: int) -> list[DutyPersonConfig]:
    members = TeamMember.query.filter_by(team_id=team_id).all()
    configs = []
    for m in members:
        configs.append(ensure_person_config(team_id, m.user_id))
    db.session.flush()
    return configs


def available_roster_users(team_id: int, range_start: date | None = None, range_end: date | None = None):
    """Team-User die im Plan erscheinen (optional Zeitraum-Filter)."""
    from app.models.user import User

    configs = {
        c.user_id: c
        for c in DutyPersonConfig.query.filter_by(team_id=team_id).all()
    }
    members = (
        TeamMember.query.filter_by(team_id=team_id)
        .join(User, User.id == TeamMember.user_id)
        .order_by(User.first_name, User.last_name)
        .all()
    )
    result = []
    for m in members:
        cfg = configs.get(m.user_id)
        if cfg is None:
            result.append(m.user)
            continue
        if not cfg.available_for_roster:
            continue
        if range_start and range_end and not cfg.overlaps_range(range_start, range_end):
            continue
        result.append(m.user)
    return result


def available_external_persons(team_id: int, range_start: date | None = None, range_end: date | None = None):
    q = DutyExternalPerson.query.filter_by(team_id=team_id, is_active=True).order_by(
        DutyExternalPerson.sort_order, DutyExternalPerson.name
    )
    result = []
    for p in q.all():
        if range_start and range_end and not p.overlaps_range(range_start, range_end):
            continue
        result.append(p)
    return result


def column_active_on(
    column: DutyRosterColumn,
    d: date,
    person_configs: dict[int, DutyPersonConfig] | None = None,
) -> bool:
    """Ob die Person an diesem Tag im Plan aktiv ist (Start/Ende)."""
    if column.user_id:
        cfg = None
        if person_configs is not None:
            cfg = person_configs.get(column.user_id)
        elif column.roster:
            cfg = DutyPersonConfig.query.filter_by(
                team_id=column.roster.team_id, user_id=column.user_id
            ).first()
        if cfg:
            return cfg.is_active_on(d)
        return True
    if column.external_person:
        return column.external_person.is_active_on(d)
    return True


def full_week_date_range(year: int, month: int) -> tuple[date, date]:
    """Montag der ersten KW bis Sonntag der letzten KW, die den Monat berühren."""
    month_start = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    # Montag = weekday 0
    range_start = month_start - timedelta(days=month_start.weekday())
    range_end = month_end + timedelta(days=(6 - month_end.weekday()))
    return range_start, range_end


def bootstrap_roster_days(roster: DutyRoster) -> list[DutyRosterDay]:
    """Create day rows for full weeks (Mon–Sun) covering the calendar month."""
    existing = {d.date: d for d in roster.days}
    created = []
    range_start, range_end = full_week_date_range(roster.year, roster.month)
    d = range_start
    while d <= range_end:
        if d not in existing:
            day = DutyRosterDay(
                roster_id=roster.id,
                date=d,
                weekday=WEEKDAY_NAMES_DE[d.weekday()],
            )
            db.session.add(day)
            created.append(day)
        d += timedelta(days=1)
    db.session.flush()
    return created


def day_is_in_roster_month(day: DutyRosterDay, roster: DutyRoster | None = None) -> bool:
    r = roster or day.roster
    if not r:
        return True
    return day.date.year == r.year and day.date.month == r.month


def bootstrap_columns_from_team(roster: DutyRoster) -> list[DutyRosterColumn]:
    """Spalten für aktive Team-/Externe Personen ergänzen (Zeitraum = Planmonat inkl. KW)."""
    range_start, range_end = full_week_date_range(roster.year, roster.month)
    existing_user_ids = {c.user_id for c in roster.columns if c.user_id}
    existing_ext_ids = {c.external_person_id for c in roster.columns if c.external_person_id}
    max_order = max((c.sort_order for c in roster.columns), default=-1)
    created = []

    for user in available_roster_users(roster.team_id, range_start, range_end):
        if user.id in existing_user_ids:
            continue
        max_order += 1
        col = DutyRosterColumn(
            roster_id=roster.id,
            user_id=user.id,
            sort_order=max_order,
            show_in_plan=True,
        )
        db.session.add(col)
        created.append(col)

    for ext in available_external_persons(roster.team_id, range_start, range_end):
        if ext.id in existing_ext_ids:
            continue
        max_order += 1
        col = DutyRosterColumn(
            roster_id=roster.id,
            external_person_id=ext.id,
            external_name=ext.name,
            sort_order=max_order,
            show_in_plan=True,
        )
        db.session.add(col)
        created.append(col)

    db.session.flush()
    return created


def create_monthly_roster(team_id: int, year: int, month: int, created_by_id: int | None, title: str | None = None) -> DutyRoster:
    """Titel kommt immer aus Monat/Jahr (display_title); Parameter title wird ignoriert."""
    roster = DutyRoster(
        team_id=team_id,
        year=year,
        month=month,
        title=None,
        is_published=False,
        created_by_id=created_by_id,
    )
    db.session.add(roster)
    db.session.flush()
    bootstrap_roster_days(roster)
    bootstrap_columns_from_team(roster)
    pull_boundary_days_from_owners(roster)
    return roster


def parse_time(raw: str) -> time | None:
    """Parst Uhrzeiten: ``8``, ``8:00``, ``17:30``, ``8.30``, ``24:00``."""
    raw = (raw or '').strip().lower()
    if not raw:
        return None
    # 24:00 = Mitternacht Folgetag (Anzeige oft so in Excel-Plänen)
    if raw in ('24:00', '24.00', '24:00:00', '24'):
        return time(0, 0)

    # Nur Ziffern: 8 → 08:00; 830/1730 → 8:30/17:30
    if raw.isdigit():
        if len(raw) <= 2:
            hour = int(raw)
            if 0 <= hour <= 23:
                return time(hour, 0)
            if hour == 24:
                return time(0, 0)
            return None
        if len(raw) == 3:
            hour, minute = int(raw[0]), int(raw[1:])
        elif len(raw) == 4:
            hour, minute = int(raw[:2]), int(raw[2:])
        else:
            return None
        if hour == 24 and minute == 0:
            return time(0, 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
        return None

    normalized = raw.replace('.', ':')
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(normalized, fmt).time()
        except ValueError:
            continue
    return None


def parse_cell_value(raw: str) -> dict:
    """Parse free-text cell into entry fields.

    Erkannt: Zeiten (``8-17``, ``8 - 17:30``), Urlaub, Krank.
    Alles andere bleibt Freitext (Notiz), z.B. ``Halloween``, ``Seminar``.
    """
    text = (raw or '').strip()
    if not text:
        return {'clear': True}

    # Groß-/Kleinschreibung egal; Umlaute normalisieren
    key = (
        text.upper()
        .replace('Ä', 'AE')
        .replace('Ö', 'OE')
        .replace('Ü', 'UE')
        .replace('ß', 'SS')
    )
    key_compact = ''.join(key.split())
    if key_compact in ('URLAUB', 'UR', 'URLAUBSTAG'):
        return {
            'entry_type': 'vacation',
            'label': 'URLAUB',
            'start_time': None,
            'end_time': None,
            'ends_next_day': False,
        }
    if key_compact in ('KRANK', 'KK', 'KRANKHEIT'):
        return {
            'entry_type': 'sick',
            'label': 'KRANK',
            'start_time': None,
            'end_time': None,
            'ends_next_day': False,
        }

    # Zeitspanne nur wenn BEIDE Seiten gültige Uhrzeiten sind
    for sep in ('–', '—', ' bis ', ' bis', ' - ', '-'):
        if sep not in text:
            continue
        left, right = text.split(sep, 1)
        start = parse_time(left)
        end_raw = (right or '').strip()
        end_is_midnight = end_raw.lower().replace('.', ':') in (
            '24:00', '24:00:00', '24', '24.00',
        )
        end = parse_time(right)
        if start and end:
            ends_next = end_is_midnight or end <= start
            return {
                'entry_type': ENTRY_TYPE_SHIFT,
                'label': None,
                'start_time': start,
                'end_time': end,
                'ends_next_day': ends_next,
            }
        # Kein gültiges Zeitpaar → als Freitext behalten (nicht weiter raten)
        break

    # Fallback: unveränderter Freitext
    return {
        'entry_type': 'note',
        'label': text[:200],
        'start_time': None,
        'end_time': None,
        'ends_next_day': False,
    }


def entry_map_for_roster(roster: DutyRoster) -> dict[tuple[int, int], DutyRosterEntry]:
    """Map (day_id, column_id) -> entry."""
    day_ids = [d.id for d in roster.days]
    if not day_ids:
        return {}
    entries = DutyRosterEntry.query.filter(DutyRosterEntry.day_id.in_(day_ids)).all()
    return {(e.day_id, e.column_id): e for e in entries}


def planned_hours_for_column(roster: DutyRoster, column_id: int, week: int | None = None) -> float:
    total = 0.0
    entries = entry_map_for_roster(roster)
    for day in roster.days:
        if week is not None and day.iso_week != week:
            continue
        e = entries.get((day.id, column_id))
        if e:
            total += e.duration_hours()
    return round(total, 2)


def planned_hours_by_column_week(roster: DutyRoster) -> dict[int, dict[int, float]]:
    """column_id -> {iso_week -> hours}."""
    result: dict[int, dict[int, float]] = {}
    entries = entry_map_for_roster(roster)
    for day in roster.days:
        week = day.iso_week
        for col in roster.columns:
            e = entries.get((day.id, col.id))
            if not e:
                continue
            hours = e.duration_hours()
            if hours <= 0:
                continue
            result.setdefault(col.id, {})
            result[col.id][week] = round(result[col.id].get(week, 0.0) + hours, 2)
    return result


def kw_color_for_week(week: int) -> str:
    """Stabile KW-Farbe über Monatsgrenzen hinweg (gleicher Index pro ISO-Woche)."""
    return KW_COLORS[(int(week) - 1) % len(KW_COLORS)]


def week_boundary_rows(
    days: Iterable[DutyRosterDay],
    roster: DutyRoster | None = None,
) -> list[dict]:
    """Build render rows: KW separators + day rows with alternating colors."""
    rows = []
    last_week = None
    day_list = list(days)
    if roster is None and day_list:
        roster = day_list[0].roster
    for day in day_list:
        week = day.iso_week
        color = kw_color_for_week(week)
        if week != last_week:
            rows.append({
                'kind': 'kw',
                'week': week,
                'color': color,
            })
            last_week = week
        in_month = day_is_in_roster_month(day, roster)
        rows.append({
            'kind': 'day',
            'day': day,
            'color': day.row_color or color,
            'week': week,
            'out_of_month': not in_month,
        })
    return rows


def _column_match_key(col: DutyRosterColumn) -> tuple | None:
    if col.user_id:
        return ('u', col.user_id)
    if col.external_person_id:
        return ('e', col.external_person_id)
    name = (col.external_name or '').strip().lower()
    return ('n', name) if name else None


def find_roster_for_month(
    team_id: int,
    year: int,
    month: int,
    *,
    published_only: bool = False,
) -> DutyRoster | None:
    q = DutyRoster.query.filter_by(team_id=team_id, year=year, month=month)
    if published_only:
        q = q.filter_by(is_published=True)
    return q.first()


def shift_year_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def copy_day_data(source_roster: DutyRoster, target_roster: DutyRoster, day_date: date) -> bool:
    """Kopiert Farbe, WAS IST LOS? und Zellenzeiten für ein Datum zwischen zwei Plänen."""
    if source_roster.id == target_roster.id:
        return False
    src_day = next((d for d in source_roster.days if d.date == day_date), None)
    tgt_day = next((d for d in target_roster.days if d.date == day_date), None)
    if not src_day or not tgt_day:
        return False

    tgt_day.whats_happening = src_day.whats_happening
    tgt_day.row_color = src_day.row_color

    src_by_key = {_column_match_key(c): c for c in source_roster.columns if _column_match_key(c)}
    tgt_by_key = {_column_match_key(c): c for c in target_roster.columns if _column_match_key(c)}
    src_entries = entry_map_for_roster(source_roster)

    for key, tgt_col in tgt_by_key.items():
        src_col = src_by_key.get(key)
        if not src_col:
            continue
        src_e = src_entries.get((src_day.id, src_col.id))
        tgt_e = DutyRosterEntry.query.filter_by(day_id=tgt_day.id, column_id=tgt_col.id).first()
        if not src_e:
            if tgt_e:
                db.session.delete(tgt_e)
            continue
        if not tgt_e:
            tgt_e = DutyRosterEntry(day_id=tgt_day.id, column_id=tgt_col.id)
            db.session.add(tgt_e)
        tgt_e.entry_type = src_e.entry_type
        tgt_e.label = src_e.label
        tgt_e.start_time = src_e.start_time
        tgt_e.end_time = src_e.end_time
        tgt_e.ends_next_day = bool(src_e.ends_next_day)
    return True


def pull_boundary_days_from_owners(roster: DutyRoster) -> bool:
    """Übernimmt Farbe/Zeiten für Tage außerhalb des Planmonats vom Eigentümer-Monat."""
    changed = False
    for day in list(roster.days):
        if day_is_in_roster_month(day, roster):
            continue
        owner = find_roster_for_month(roster.team_id, day.date.year, day.date.month)
        if owner and owner.id != roster.id:
            if copy_day_data(owner, roster, day.date):
                changed = True
    return changed


def push_day_to_peer_rosters(roster: DutyRoster, day_date: date) -> None:
    """Spiegelt einen Tag in alle anderen Team-Pläne, die dieses Datum enthalten."""
    peers = DutyRoster.query.filter(
        DutyRoster.team_id == roster.team_id,
        DutyRoster.id != roster.id,
    ).all()
    for peer in peers:
        if any(d.date == day_date for d in peer.days):
            copy_day_data(roster, peer, day_date)


def resolve_pager_target(
    roster: DutyRoster,
    view: str,
    focus: date | None,
    delta: int,
    *,
    published_only: bool = False,
) -> dict | None:
    """Ziel für Prev/Next. None = Blättern nicht möglich (kein Nachbarplan)."""
    focus = focus or roster.month_start
    if view == 'month':
        y, m = shift_year_month(roster.year, roster.month, delta)
        other = find_roster_for_month(roster.team_id, y, m, published_only=published_only)
        if not other:
            return None
        return {'roster_id': other.id, 'focus': other.month_start}

    step = 1 if view == 'day' else 7
    target = focus + timedelta(days=step * delta)
    current_dates = {d.date for d in roster.days}
    if target in current_dates:
        return {'roster_id': roster.id, 'focus': target}

    other = find_roster_for_month(
        roster.team_id, target.year, target.month, published_only=published_only
    )
    if not other:
        return None
    # Nachbarplan hat den Tag evtl. noch nicht (Fransen) — trotzdem dorthin
    return {'roster_id': other.id, 'focus': target}


def partition_rosters_by_current_month(rosters: list[DutyRoster], today: date | None = None) -> dict:
    """Aktueller Monat, dann zukünftige (aufsteigend), dann vergangene (absteigend)."""
    today = today or date.today()
    current, future, past = [], [], []
    for r in rosters:
        key = (r.year, r.month)
        if key == (today.year, today.month):
            current.append(r)
        elif key > (today.year, today.month):
            future.append(r)
        else:
            past.append(r)
    future.sort(key=lambda r: (r.year, r.month))
    past.sort(key=lambda r: (r.year, r.month), reverse=True)
    return {'current': current, 'future': future, 'past': past}


def _month_slot(year: int, month: int, roster: DutyRoster | None, *, kind: str) -> dict:
    return {
        'year': year,
        'month': month,
        'label': f'{MONTH_NAMES_DE[month - 1]} - {year}',
        'roster': roster,
        'kind': kind,  # current | upcoming | past
    }


def build_team_month_slots(
    rosters: list[DutyRoster],
    today: date | None = None,
    *,
    upcoming_count: int = 2,
    past_create_months: int = 12,
) -> dict:
    """Monats-Slots für Team-Index: aktuell + nächste Monate, ggf. Anlege-Platzhalter; Vergangenheit nachträglich."""
    today = today or date.today()
    by_key = {(r.year, r.month): r for r in rosters}

    forward = []
    for offset in range(0, upcoming_count + 1):
        y, m = shift_year_month(today.year, today.month, offset)
        kind = 'current' if offset == 0 else 'upcoming'
        forward.append(_month_slot(y, m, by_key.get((y, m)), kind=kind))

    # Weitere bereits angelegte Zukunftsmonate jenseits der Platzhalter
    covered = {(s['year'], s['month']) for s in forward}
    extra_future = []
    for r in sorted(
        (r for r in rosters if (r.year, r.month) > (today.year, today.month)),
        key=lambda r: (r.year, r.month),
    ):
        if (r.year, r.month) in covered:
            continue
        extra_future.append(_month_slot(r.year, r.month, r, kind='upcoming'))

    past_existing = []
    past_create = []
    for offset in range(1, past_create_months + 1):
        y, m = shift_year_month(today.year, today.month, -offset)
        roster = by_key.get((y, m))
        if roster:
            past_existing.append(_month_slot(y, m, roster, kind='past'))
        else:
            past_create.append(_month_slot(y, m, None, kind='past'))

    # Ältere vorhandene Pläne jenseits des Fensters
    window_past = {(s['year'], s['month']) for s in past_existing}
    for r in sorted(
        (r for r in rosters if (r.year, r.month) < (today.year, today.month)),
        key=lambda r: (r.year, r.month),
        reverse=True,
    ):
        if (r.year, r.month) in window_past:
            continue
        past_existing.append(_month_slot(r.year, r.month, r, kind='past'))

    return {
        'forward': forward,
        'extra_future': extra_future,
        'past_existing': past_existing,
        'past_create': past_create,
    }


def work_hours_ist(user_id: int, start: date, end: date, team_id: int | None = None) -> float:
    q = DutyTimeEntry.query.filter(
        DutyTimeEntry.user_id == user_id,
        DutyTimeEntry.date >= start,
        DutyTimeEntry.date <= end,
        DutyTimeEntry.entry_type == TIME_ENTRY_WORK,
    )
    if team_id:
        q = q.filter(DutyTimeEntry.team_id == team_id)
    total = 0.0
    for e in q.all():
        total += e.duration_hours()
    return round(total, 2)


def daily_soll_hours(weekly_hours: float | None, workdays_per_week: float = 5.0) -> float | None:
    """Tages-Soll aus Wochen-Soll (Standard: 5 Arbeitstage)."""
    if weekly_hours is None:
        return None
    if workdays_per_week <= 0:
        return None
    return float(weekly_hours) / float(workdays_per_week)


def overtime_hours(
    user_id: int,
    weekly_hours_soll: float | None,
    start: date,
    end: date,
    team_id: int | None = None,
) -> float | None:
    """Überstunden nur an Tagen mit Ist-Eintrag (Typ Arbeit).

    Pro Tag mit Arbeitseintrag: Σ Ist − Tages-Soll (Wochen-Soll / 5).
    Tage ohne Eintrag (auch vergangene): ±0.
    Krank / Urlaub / leer: kein Minusstunden-Effekt.
    """
    daily = daily_soll_hours(weekly_hours_soll)
    if daily is None:
        return None

    q = DutyTimeEntry.query.filter(
        DutyTimeEntry.user_id == user_id,
        DutyTimeEntry.date >= start,
        DutyTimeEntry.date <= end,
        DutyTimeEntry.entry_type == TIME_ENTRY_WORK,
    )
    if team_id:
        q = q.filter(DutyTimeEntry.team_id == team_id)

    by_date: dict[date, float] = {}
    for e in q.all():
        by_date[e.date] = by_date.get(e.date, 0.0) + e.duration_hours()

    if not by_date:
        return 0.0

    total = 0.0
    for _d, ist in by_date.items():
        total += ist - daily
    return round(total, 2)


def person_stats_for_team(team_id: int, user_id: int, ref_date: date | None = None) -> dict:
    """Stats shown next to a person in the team editor."""
    ref = ref_date or date.today()
    # Current ISO week
    week_start = ref - timedelta(days=ref.weekday())
    week_end = week_start + timedelta(days=6)
    # Year-to-date for overtime
    year_start = date(ref.year, 1, 1)

    cfg = DutyPersonConfig.query.filter_by(team_id=team_id, user_id=user_id).first()
    weekly_soll = cfg.weekly_hours_soll if cfg else None
    vacation_remaining = cfg.vacation_days_remaining if cfg else None

    return {
        'weekly_hours_soll': weekly_soll,
        'vacation_days_remaining': vacation_remaining,
        'vacation_days_total': cfg.vacation_days_total if cfg else None,
        'available_for_roster': cfg.available_for_roster if cfg else True,
        'overtime_ytd': overtime_hours(user_id, weekly_soll, year_start, ref, team_id=team_id),
        'ist_week': work_hours_ist(user_id, week_start, week_end, team_id=team_id),
    }


def filter_days_by_view(days: list[DutyRosterDay], view: str, focus: date | None) -> list[DutyRosterDay]:
    focus = focus or date.today()
    if view == 'day':
        return [d for d in days if d.date == focus]
    if view == 'week':
        week = focus.isocalendar()[1]
        year = focus.isocalendar()[0]
        return [d for d in days if d.date.isocalendar()[0] == year and d.iso_week == week]
    return list(days)


def visible_columns(roster: DutyRoster) -> list[DutyRosterColumn]:
    return [c for c in roster.columns if c.show_in_plan]
