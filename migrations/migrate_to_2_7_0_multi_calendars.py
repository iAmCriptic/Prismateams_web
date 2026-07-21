#!/usr/bin/env python3
"""
Datenbank-Migration: Multi-Kalender

- Tabelle calendars
- calendar_events.calendar_id
- SystemSettings: calendar_multi_enabled, calendar_export_enabled, calendar_import_enabled
- Bestehende Events → Public-Kalender
- Sync-Sources → imported calendars

Aufruf:
  python migrations/migrate_to_2_7_0_multi_calendars.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def column_exists(table_name, column_name):
    if not table_exists(table_name):
        return False
    columns = {col['name'] for col in inspect(db.engine).get_columns(table_name)}
    return column_name in columns


def add_column(table, column_sql):
    with db.engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column_sql}'))


def ensure_calendars_table():
    if table_exists('calendars'):
        print('[INFO] calendars existiert')
        return
    from app.models.calendar import Calendar
    Calendar.__table__.create(db.engine, checkfirst=True)
    print('[OK] calendars angelegt')


def ensure_calendar_id_column():
    if not table_exists('calendar_events'):
        print('[INFO] calendar_events fehlt')
        return
    if column_exists('calendar_events', 'calendar_id'):
        print('[INFO] calendar_events.calendar_id existiert')
        return
    add_column('calendar_events', 'calendar_id INTEGER')
    print('[OK] calendar_events.calendar_id hinzugefuegt')
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        try:
            conn.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_calendar_events_calendar_id '
                'ON calendar_events (calendar_id)'
            ))
        except Exception:
            if dialect != 'sqlite':
                try:
                    conn.execute(text(
                        'CREATE INDEX ix_calendar_events_calendar_id ON calendar_events (calendar_id)'
                    ))
                except Exception:
                    pass
    print('[OK] Index calendar_id')


def ensure_settings():
    from app.models.settings import SystemSettings
    defaults = {
        'calendar_multi_enabled': 'False',
        'calendar_export_enabled': 'True',
        'calendar_import_enabled': 'True',
    }
    for key, value in defaults.items():
        existing = SystemSettings.query.filter_by(key=key).first()
        if existing:
            print(f'[INFO] Setting {key} existiert')
            continue
        db.session.add(SystemSettings(key=key, value=value))
        print(f'[OK] Setting {key}={value}')
    db.session.commit()


def ensure_public_and_backfill():
    from app.models.calendar import Calendar, CalendarEvent, CalendarSyncSource
    from app.models.user import User
    from app.utils.multi_calendars import (
        DEFAULT_IMPORT_COLOR,
        DEFAULT_PUBLIC_COLOR,
        PUBLIC_CALENDAR_NAME,
        _color_for_user,
    )

    public = Calendar.query.filter_by(calendar_type='public').first()
    if not public:
        public = Calendar(
            name=PUBLIC_CALENDAR_NAME,
            calendar_type='public',
            owner_id=None,
            color=DEFAULT_PUBLIC_COLOR,
        )
        db.session.add(public)
        db.session.flush()
        print('[OK] Public-Kalender angelegt')
    else:
        print('[INFO] Public-Kalender existiert')

    updated = (
        CalendarEvent.query
        .filter(CalendarEvent.calendar_id.is_(None))
        .update({CalendarEvent.calendar_id: public.id}, synchronize_session=False)
    )
    db.session.commit()
    print(f'[OK] {updated} Events -> Public')

    # Personal calendars for active users
    users = User.query.filter_by(is_active=True).all()
    created_personal = 0
    for user in users:
        existing = Calendar.query.filter_by(calendar_type='personal', owner_id=user.id).first()
        if existing:
            continue
        db.session.add(Calendar(
            name=user.full_name or f'User {user.id}',
            calendar_type='personal',
            owner_id=user.id,
            color=_color_for_user(user.id),
        ))
        created_personal += 1
    db.session.commit()
    print(f'[OK] {created_personal} Personal-Kalender angelegt')

    # Sync sources → imported calendars; move their events
    sources = CalendarSyncSource.query.all()
    for source in sources:
        cal = Calendar.query.filter_by(sync_source_id=source.id).first()
        if not cal:
            cal = Calendar(
                name=source.name,
                calendar_type='imported',
                owner_id=source.created_by,
                sync_source_id=source.id,
                color=DEFAULT_IMPORT_COLOR,
            )
            db.session.add(cal)
            db.session.flush()
            print(f'[OK] Import-Kalender fuer Source {source.id}')
        moved = (
            CalendarEvent.query
            .filter_by(sync_source_id=source.id)
            .update({CalendarEvent.calendar_id: cal.id}, synchronize_session=False)
        )
        if moved:
            print(f'[OK] {moved} Sync-Events -> Kalender {cal.id}')
    db.session.commit()


def main():
    app = create_app()
    with app.app_context():
        ensure_calendars_table()
        ensure_calendar_id_column()
        ensure_settings()
        ensure_public_and_backfill()
        print('[DONE] Multi-Kalender Migration fertig')


if __name__ == '__main__':
    main()
