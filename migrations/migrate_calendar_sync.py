#!/usr/bin/env python3
"""
Datenbank-Migration: Kalender Sync-Sources + Event-Sync-Felder

Aufruf:
  python migrations/migrate_calendar_sync.py
"""

import os
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.calendar import CalendarSyncSource, PublicCalendarFeed


def table_exists(table_name):
    return table_name in inspect(db.engine).get_table_names()


def column_exists(table_name, column_name):
    if not table_exists(table_name):
        return False
    return column_name in {col['name'] for col in inspect(db.engine).get_columns(table_name)}


def migrate():
    print('=' * 60)
    print('Datenbank-Migration: Kalender Sync')
    print('=' * 60)

    app = create_app(os.getenv('FLASK_ENV', 'development'))
    with app.app_context():
        try:
            # Sync-Sources-Tabelle
            if table_exists('calendar_sync_sources'):
                print('[INFO] calendar_sync_sources existiert bereits')
            else:
                CalendarSyncSource.__table__.create(db.engine, checkfirst=True)
                print('[OK] calendar_sync_sources erstellt')

            # Spalten an calendar_events
            if table_exists('calendar_events'):
                with db.engine.begin() as connection:
                    if not column_exists('calendar_events', 'sync_source_id'):
                        connection.execute(text(
                            'ALTER TABLE calendar_events '
                            'ADD COLUMN sync_source_id INTEGER NULL'
                        ))
                        print('[OK] calendar_events.sync_source_id hinzugefügt')
                    else:
                        print('[INFO] calendar_events.sync_source_id existiert bereits')

                    if not column_exists('calendar_events', 'ical_uid'):
                        connection.execute(text(
                            'ALTER TABLE calendar_events '
                            'ADD COLUMN ical_uid VARCHAR(255) NULL'
                        ))
                        print('[OK] calendar_events.ical_uid hinzugefügt')
                    else:
                        print('[INFO] calendar_events.ical_uid existiert bereits')

                # Index / Unique (best effort, DB-abhängig)
                try:
                    with db.engine.begin() as connection:
                        connection.execute(text(
                            'CREATE INDEX IF NOT EXISTS ix_calendar_events_sync_source_id '
                            'ON calendar_events (sync_source_id)'
                        ))
                        connection.execute(text(
                            'CREATE INDEX IF NOT EXISTS ix_calendar_events_ical_uid '
                            'ON calendar_events (ical_uid)'
                        ))
                        connection.execute(text(
                            'CREATE UNIQUE INDEX IF NOT EXISTS unique_sync_source_ical_uid '
                            'ON calendar_events (sync_source_id, ical_uid)'
                        ))
                    print('[OK] Indizes für Sync-Felder geprüft/erstellt')
                except Exception as idx_exc:
                    print(f'[WARNUNG] Index-Erstellung: {idx_exc}')

            # Überzählige Public Feeds pro User bereinigen (ältesten behalten)
            if table_exists('public_calendar_feeds'):
                feeds = (
                    PublicCalendarFeed.query
                    .order_by(PublicCalendarFeed.created_by, PublicCalendarFeed.created_at.asc())
                    .all()
                )
                seen = set()
                deleted = 0
                for feed in feeds:
                    if feed.created_by in seen:
                        db.session.delete(feed)
                        deleted += 1
                    else:
                        seen.add(feed.created_by)
                if deleted:
                    db.session.commit()
                    print(f'[OK] {deleted} überzählige Public Feeds entfernt')
                else:
                    print('[INFO] Keine überzähligen Public Feeds')

            print('Migration abgeschlossen.')
        except Exception as exc:
            db.session.rollback()
            print(f'[FEHLER] {exc}')
            raise


if __name__ == '__main__':
    migrate()
