#!/usr/bin/env python3
"""
Konsolidierte Upgrade-/Repair-Migration: Legacy (2.4 / 2.5+) -> 3.1.0.

Idempotent und modellbasiert. Ersetzt alle früheren Einzel-Skripte
(3.0.0 / 3.0.1 Full Upgrade, Google Login, Multi-Mailbox, OAuth, Wizard UX).

  1. Fehlende Tabellen aus SQLAlchemy-Models anlegen
  2. Fehlende Spalten per ALTER TABLE nachziehen
  3. Spezielle Schema-Fixes (Shares, BIGINT, E-Mail, Google-Index, Mailbox-Indexes)
  4. Daten-Backfills + SystemSettings-Seeds

Aufruf:
  python migrations/migrate_to_3_1_0.py
  python migrations/migrate_to_3_1_0.py --force
  python migrations/run_all.py

Läuft beim App-Start über app.utils.auto_migrate (Release-Wechsel oder
PRISMATEAMS_STARTUP_MIGRATIONS=true). Ab Version 3.1.0.
"""

from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Column, inspect, text
from sqlalchemy.schema import CreateColumn

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Einmal-Marker: verhindert Doppel-Lauf nach erfolgreichem 3.1.0-Sync
_SYNC_MARKER = "_internal_full_schema_sync_v3_1_0"
_PREVIOUS_SYNC_MARKERS = (
    "_internal_full_schema_sync_v1",
)

# Legacy-Schrittnamen - nach erfolgreichem Lauf als angewendet markieren,
# falls jemand noch Tracking-Einträge aus der alten Einzel-Skript-Zeit erwartet.
_LEGACY_STEP_MARKERS = (
    "migrate_calendar_sync.py",
    "migrate_to_2_4_3.py",
    "migrate_to_2_5_0_events.py",
    "migrate_to_2_6_0_shares.py",
    "migrate_to_2_7_0_multi_calendars.py",
    "migrate_to_2_7_0_private_files.py",
    "migrate_to_2_7_1_folder_favorites.py",
    "migrate_to_2_7_2_chat_pins.py",
    "migrate_to_2_7_3_manual_folders.py",
    "migrate_to_2_7_4_inventory_checkouts.py",
    "migrate_to_2_7_5_checkout_contact_email.py",
    "migrate_to_2_7_6_booking_notifications.py",
    "migrate_to_2_7_7_checkout_event_link.py",
    "migrate_to_2_7_8_credential_favorites.py",
    "migrate_to_2_7_9_contact_favorites.py",
    "migrate_to_2_7_10_file_edit_locks.py",
    "migrate_to_2_7_11_inventory_counted_quantity.py",
    "migrate_to_2_7_12_booking_messages.py",
    "migrate_to_2_7_13_booking_message_notifications.py",
    "migrate_to_2_7_13_checkout_item_source_set.py",
    "migrate_to_3_0_0.py",
    "migrate_to_3_0_0_whats_new.py",
    "migrate_to_3_0_1_full_upgrade.py",
    "migrate_google_login.py",
    "migrate_mailbox_provider_oauth.py",
    "migrate_mailbox_wizard_ux.py",
    "migrate_to_multi_mailbox.py",
    "migrate_to_3_1_0_file_storage_quotas.py",
    "migrate_to_3_1_1_events_calendar.py",
    "migrate_to_3_1_1_fix_email_attachments.py",
    "migrate_to_3_1_2_checkout_email_flags.py",
)


class MigrationReport:
    def __init__(self) -> None:
        self.ok: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def note_ok(self, msg: str) -> None:
        self.ok.append(msg)
        print(f"[OK] {msg}")

    def note_skip(self, msg: str) -> None:
        self.skipped.append(msg)
        print(f"[INFO] {msg}")

    def note_warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"[WARNUNG] {msg}")

    def note_error(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"[FEHLER] {msg}")


def _safe_ident(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"Ungültiger SQL-Identifier: {name!r}")
    return name


def _table_exists(engine, table_name: str) -> bool:
    return table_name in inspect(engine).get_table_names()


def _column_exists(engine, table_name: str, column_name: str) -> bool:
    if not _table_exists(engine, table_name):
        return False
    return column_name in {c["name"] for c in inspect(engine).get_columns(table_name)}


def _index_exists(engine, table_name: str, index_name: str) -> bool:
    if not _table_exists(engine, table_name):
        return False
    return any(idx.get("name") == index_name for idx in inspect(engine).get_indexes(table_name))


def _unique_exists(engine, table_name: str, name: str) -> bool:
    if not _table_exists(engine, table_name):
        return False
    try:
        if any(u.get("name") == name for u in inspect(engine).get_unique_constraints(table_name)):
            return True
    except Exception:
        pass
    return _index_exists(engine, table_name, name)


def _already_exists_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        needle in msg
        for needle in (
            "duplicate column",
            "already exists",
            "duplicate key name",
            "1060",
            "1050",
            "42s21",
        )
    )


def _compile_add_column_ddl(column: Column, dialect) -> str:
    """
    Baut ADD-COLUMN-DDL ohne Foreign Keys (FK später optional).
    NOT NULL ohne Default wird als NULL angelegt, damit Bestandsdaten nicht blockieren.
    """
    safe = Column(
        column.name,
        column.type,
        primary_key=False,
        autoincrement=False,
        nullable=True if (not column.nullable and column.server_default is None and column.default is None) else column.nullable,
        server_default=column.server_default,
    )
    # Boolean-Defaults aus Python-default übernehmen, wenn kein server_default gesetzt ist
    if safe.server_default is None and column.default is not None and column.default.is_scalar:
        try:
            from sqlalchemy.sql import false as sql_false
            from sqlalchemy.sql import true as sql_true

            val = column.default.arg
            if val is True:
                safe.server_default = sql_true()
                safe.nullable = column.nullable
            elif val is False:
                safe.server_default = sql_false()
                safe.nullable = column.nullable
            elif isinstance(val, (int, float, str)):
                from sqlalchemy.sql import literal

                safe.server_default = literal(val)
                safe.nullable = column.nullable
        except Exception:
            pass

    compiled = str(CreateColumn(safe).compile(dialect=dialect)).strip()
    # CreateColumn liefert "colname TYPE ..." - für ALTER TABLE ADD COLUMN geeignet
    return compiled


def step_import_models(report: MigrationReport) -> None:
    from app.utils.schema_init import import_all_models

    import_all_models()
    # Zusätzliche Modelle, die schema_init ggf. nicht vollständig lädt
    import app.models  # noqa: F401
    from app.models.api_token import ApiToken  # noqa: F401
    from app.models.comment import Comment, CommentMention  # noqa: F401
    from app.models.credential import Credential, CredentialFavorite, CredentialFolder  # noqa: F401
    from app.models.email import (  # noqa: F401
        EmailAttachment,
        EmailFolder,
        EmailMessage,
        EmailPermission,
        Mailbox,
        MailboxMembership,
        MailboxUserPref,
    )
    from app.models.file import (  # noqa: F401
        File,
        FileEditLock,
        FileStorageException,
        FileVersion,
        Folder,
        FolderFavorite,
        ResourceACL,
    )
    from app.models.guest import GuestShareAccess  # noqa: F401
    from app.models.media_downloader import MediaDownloadJob  # noqa: F401
    from app.models.music import MusicProviderToken, MusicQueue, MusicSettings, MusicWish  # noqa: F401
    from app.models.notification import (  # noqa: F401
        ChatNotificationSettings,
        NotificationLog,
        NotificationSettings,
        PushSubscription,
    )
    from app.models.onlyoffice_session import OnlyOfficeSession  # noqa: F401
    from app.models.role import UserModuleRole  # noqa: F401
    from app.models.shortlink import ShortLink  # noqa: F401
    from app.models.user import User  # noqa: F401
    from app.models.user_session import UserSession  # noqa: F401
    from app.models.whitelist import WhitelistEntry  # noqa: F401
    from app.models.wiki import WikiCategory, WikiFavorite, WikiPage, WikiPageVersion, WikiTag  # noqa: F401

    report.note_ok("Alle Modelle geladen")


def step_sync_tables(db, report: MigrationReport) -> None:
    from app.utils.schema_init import ensure_all_tables

    try:
        db.create_all()
        report.note_ok("db.create_all() ausgeführt")
    except Exception as exc:
        report.note_warn(f"db.create_all() teilweise fehlgeschlagen: {exc}")

    ok, missing = ensure_all_tables(db)
    if ok:
        report.note_ok("Kritische Tabellen vollständig")
    else:
        report.note_error(f"Kritische Tabellen fehlen weiterhin: {', '.join(missing)}")

    # Alle Metadata-Tabellen einzeln nachziehen (auch nicht-kritische)
    inspector = inspect(db.engine)
    existing = set(inspector.get_table_names())
    for table_name, table in db.metadata.tables.items():
        if table_name in existing:
            continue
        try:
            table.create(db.engine, checkfirst=True)
            report.note_ok(f"Tabelle angelegt: {table_name}")
        except Exception as exc:
            if _already_exists_error(exc):
                report.note_skip(f"Tabelle {table_name} existiert bereits")
            else:
                report.note_warn(f"Tabelle {table_name} nicht anlegbar: {exc}")


def step_sync_columns(db, report: MigrationReport) -> None:
    engine = db.engine
    dialect = engine.dialect
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    added = 0
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        try:
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        except Exception as exc:
            report.note_warn(f"Spalten von {table_name} nicht lesbar: {exc}")
            continue

        for column in table.columns:
            if column.name in existing_cols:
                continue
            # Autoincrement-PKs nicht per ADD nachziehen
            if column.primary_key:
                report.note_warn(
                    f"{table_name}.{column.name} fehlt als PK - bitte manuell prüfen"
                )
                continue
            try:
                ddl = _compile_add_column_ddl(column, dialect)
                table_sql = _safe_ident(table_name)
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN {ddl}"))
                added += 1
                report.note_ok(f"Spalte hinzugefügt: {table_name}.{column.name}")
                existing_cols.add(column.name)
            except Exception as exc:
                if _already_exists_error(exc):
                    report.note_skip(f"{table_name}.{column.name} existiert bereits")
                    existing_cols.add(column.name)
                else:
                    report.note_warn(
                        f"Spalte {table_name}.{column.name} nicht hinzufügbar: {exc}"
                    )

        # Inspector-Cache invalidieren für nächste Tabelle
        try:
            inspector = inspect(engine)
        except Exception:
            pass

    if added == 0:
        report.note_skip("Keine fehlenden Spalten - Schema aktuell")
    else:
        report.note_ok(f"{added} Spalte(n) nachgezogen")


def step_fix_public_shares_constraint(db, report: MigrationReport) -> None:
    """Entfernt veraltetes Unique(resource_type, resource_id, mode) aus 2.5."""
    engine = db.engine
    if not _table_exists(engine, "public_shares"):
        report.note_skip("public_shares fehlt - Constraint-Fix übersprungen")
        return

    constraint_name = "uq_public_share_resource_mode"
    dialect = engine.dialect.name

    if dialect == "sqlite":
        # SQLite: nur wenn Constraint noch als Unique-Index existiert
        if not _unique_exists(engine, "public_shares", constraint_name):
            # Prüfe ob irgendein Unique auf (resource_type, resource_id, mode) liegt
            try:
                uniques = inspect(engine).get_unique_constraints("public_shares")
                has_triple = any(
                    set(u.get("column_names") or [])
                    >= {"resource_type", "resource_id", "mode"}
                    for u in uniques
                )
            except Exception:
                has_triple = False
            if not has_triple:
                report.note_skip("public_shares Unique-Constraint bereits entfernt")
                return
        report.note_warn(
            "SQLite: Unique auf public_shares ggf. noch aktiv - "
            "bei Problemen Tabelle manuell neu aufbauen"
        )
        return

    if not _unique_exists(engine, "public_shares", constraint_name):
        report.note_skip(f"{constraint_name} nicht vorhanden")
        return

    with engine.begin() as conn:
        try:
            conn.execute(text(f"ALTER TABLE public_shares DROP INDEX `{constraint_name}`"))
            report.note_ok(f"Index {constraint_name} entfernt")
            return
        except Exception:
            pass
        try:
            conn.execute(
                text(f"ALTER TABLE public_shares DROP CONSTRAINT `{constraint_name}`")
            )
            report.note_ok(f"Constraint {constraint_name} entfernt")
        except Exception as exc:
            report.note_warn(f"Constraint {constraint_name} nicht entfernt: {exc}")


def step_ensure_bigint_file_sizes(db, report: MigrationReport) -> None:
    engine = db.engine
    dialect = engine.dialect.name
    if dialect == "sqlite":
        report.note_skip("SQLite Integer dynamisch - BIGINT-ALTER unnötig")
        return

    for table_name, column_name in (("files", "file_size"), ("file_versions", "file_size")):
        if not _column_exists(engine, table_name, column_name):
            continue
        type_name = ""
        for col in inspect(engine).get_columns(table_name):
            if col["name"] == column_name:
                type_name = str(col["type"]).upper()
                break
        if "BIGINT" in type_name:
            report.note_skip(f"{table_name}.{column_name} bereits BIGINT")
            continue
        try:
            with engine.begin() as conn:
                if dialect in ("mysql", "mariadb"):
                    conn.execute(
                        text(
                            f"ALTER TABLE {_safe_ident(table_name)} "
                            f"MODIFY COLUMN {_safe_ident(column_name)} BIGINT NOT NULL"
                        )
                    )
                elif dialect == "postgresql":
                    conn.execute(
                        text(
                            f"ALTER TABLE {_safe_ident(table_name)} "
                            f"ALTER COLUMN {_safe_ident(column_name)} TYPE BIGINT"
                        )
                    )
                else:
                    report.note_skip(f"{table_name}.{column_name}: Dialekt {dialect}")
                    continue
            report.note_ok(f"{table_name}.{column_name} -> BIGINT")
        except Exception as exc:
            report.note_warn(f"BIGINT-Konvertierung {table_name}.{column_name}: {exc}")


def step_repair_email_attachments(db, report: MigrationReport) -> None:
    """Repariert verwaiste/unlesbare email_attachments (MySQL 1932)."""
    engine = db.engine
    table_name = "email_attachments"
    if not _table_exists(engine, table_name):
        try:
            from app.models.email import EmailAttachment

            EmailAttachment.__table__.create(engine, checkfirst=True)
            report.note_ok("email_attachments neu angelegt")
        except Exception as exc:
            report.note_warn(f"email_attachments nicht anlegbar: {exc}")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {_safe_ident(table_name)} LIMIT 1"))
        report.note_skip("email_attachments lesbar")
        return
    except Exception:
        pass

    dialect = engine.dialect.name
    if dialect not in ("mysql", "mariadb"):
        report.note_warn("email_attachments unlesbar - bitte manuell prüfen")
        return

    try:
        from app.models.email import EmailAttachment

        with engine.begin() as conn:
            bak = f"{table_name}_bak_mig"
            try:
                conn.execute(text(f"RENAME TABLE `{table_name}` TO `{bak}`"))
                report.note_ok(f"Alte Tabelle umbenannt nach {bak}")
            except Exception:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
                report.note_ok("Orphan email_attachments gedroppt")
        EmailAttachment.__table__.create(engine, checkfirst=True)
        report.note_ok("email_attachments neu erstellt")
    except Exception as exc:
        report.note_error(f"email_attachments-Repair fehlgeschlagen: {exc}")


def _seed_setting(db, key: str, value: str, description: str = "") -> bool:
    from app.models.settings import SystemSettings

    existing = SystemSettings.query.filter_by(key=key).first()
    if existing:
        return False
    db.session.add(
        SystemSettings(key=key, value=value, description=description or None)
    )
    return True


def step_seed_settings(db, report: MigrationReport) -> None:
    seeds = [
        ("calendar_multi_enabled", "False", "Multi-Kalender aktiv"),
        ("calendar_personal_enabled", "False", "Private Kalender aktiv"),
        ("calendar_team_enabled", "False", "Team-Kalender aktiv"),
        ("calendar_export_enabled", "True", "Kalender-Export aktiv"),
        ("calendar_import_enabled", "True", "Kalender-Import aktiv"),
        ("files_private_folders_enabled", "False", "Private Ordner aktiv"),
        ("files_team_folders_enabled", "False", "Team-Ablagen aktiv"),
        ("files_max_file_size_bytes", "104857600", "Max. Dateigröße Bytes"),
        ("files_storage_quota_enabled", "false", "Speicherkontingente aktiv"),
        ("files_storage_quota_bytes", "16106127360", "Standard-Kontingent Bytes"),
        ("module_assessment", "True", "Assessment-Modul"),
        ("default_language", "de", "Standard-Sprache"),
        ("email_multi_enabled", "False", "Multi-Postfach aktiv"),
        ("email_max_private_mailboxes", "3", "Max. private Postfächer pro Nutzer"),
        ("email_compose_html_design_default", "True", "Standard: HTML-Design beim Verfassen"),
        ("credentials_allow_private", "true", "Zugangsdaten: Privat"),
        ("credentials_allow_team", "true", "Zugangsdaten: Team"),
        ("credentials_allow_public", "true", "Zugangsdaten: Public"),
        ("manuals_allow_private", "true", "Handbücher: Privat"),
        ("manuals_allow_team", "true", "Handbücher: Team"),
        ("manuals_allow_public", "true", "Handbücher: Public"),
        ("contacts_allow_private", "true", "Kontakte: Privat"),
        ("contacts_allow_team", "true", "Kontakte: Team"),
        ("contacts_allow_public", "true", "Kontakte: Public"),
        ("wiki_allow_private", "true", "Wiki: Privat"),
        ("wiki_allow_team", "true", "Wiki: Team"),
        ("wiki_allow_public", "true", "Wiki: Public"),
        ("shortlinks_allow_private", "true", "Kurzlinks: Privat"),
        ("shortlinks_allow_team", "true", "Kurzlinks: Team"),
        ("shortlinks_allow_public", "true", "Kurzlinks: Public"),
    ]
    created = 0
    for key, value, desc in seeds:
        try:
            if _seed_setting(db, key, value, desc):
                created += 1
        except Exception as exc:
            report.note_warn(f"Setting {key}: {exc}")
            db.session.rollback()
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        report.note_warn(f"Settings-Commit: {exc}")
        return
    if created:
        report.note_ok(f"{created} SystemSettings angelegt")
    else:
        report.note_skip("SystemSettings bereits vorhanden")


def step_backfill_private_files_space(db, report: MigrationReport) -> None:
    engine = db.engine
    with engine.begin() as conn:
        for table_name in ("folders", "files"):
            if not _column_exists(engine, table_name, "space"):
                continue
            result = conn.execute(
                text(
                    f"UPDATE {_safe_ident(table_name)} SET space='public' "
                    f"WHERE space IS NULL OR space=''"
                )
            )
            report.note_ok(
                f"{table_name}.space Backfill ({result.rowcount or 0} Zeilen)"
            )


def step_backfill_contacts_sort_name(db, report: MigrationReport) -> None:
    engine = db.engine
    if not _column_exists(engine, "contacts", "sort_name"):
        return
    if not _column_exists(engine, "contacts", "name"):
        return
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE contacts SET sort_name = name "
                "WHERE sort_name IS NULL OR TRIM(sort_name) = ''"
            )
        )
    report.note_ok(f"contacts.sort_name initialisiert ({result.rowcount or 0})")


def step_backfill_multi_calendars(db, report: MigrationReport) -> None:
    if not _table_exists(db.engine, "calendars"):
        report.note_skip("calendars fehlt - Multi-Kalender-Backfill übersprungen")
        return
    if not _column_exists(db.engine, "calendar_events", "calendar_id"):
        report.note_skip("calendar_events.calendar_id fehlt")
        return

    try:
        from app.models.calendar import Calendar, CalendarEvent, CalendarSyncSource
        from app.models.user import User
        from app.utils.multi_calendars import (
            DEFAULT_IMPORT_COLOR,
            DEFAULT_PUBLIC_COLOR,
            PUBLIC_CALENDAR_NAME,
            _color_for_user,
        )

        public = Calendar.query.filter_by(calendar_type="public").first()
        if not public:
            public = Calendar(
                name=PUBLIC_CALENDAR_NAME,
                calendar_type="public",
                owner_id=None,
                color=DEFAULT_PUBLIC_COLOR,
            )
            db.session.add(public)
            db.session.flush()
            report.note_ok("Public-Kalender angelegt")
        else:
            report.note_skip("Public-Kalender existiert")

        updated = (
            CalendarEvent.query.filter(CalendarEvent.calendar_id.is_(None))
            .update({CalendarEvent.calendar_id: public.id}, synchronize_session=False)
        )
        db.session.commit()
        report.note_ok(f"{updated} Events -> Public-Kalender")

        created_personal = 0
        for user in User.query.filter_by(is_active=True).all():
            existing = Calendar.query.filter_by(
                calendar_type="personal", owner_id=user.id
            ).first()
            if existing:
                continue
            db.session.add(
                Calendar(
                    name=user.full_name or f"User {user.id}",
                    calendar_type="personal",
                    owner_id=user.id,
                    color=_color_for_user(user.id),
                )
            )
            created_personal += 1
        db.session.commit()
        report.note_ok(f"{created_personal} Personal-Kalender angelegt")

        if _table_exists(db.engine, "calendar_sync_sources"):
            for source in CalendarSyncSource.query.all():
                cal = Calendar.query.filter_by(sync_source_id=source.id).first()
                if not cal:
                    cal = Calendar(
                        name=source.name,
                        calendar_type="imported",
                        owner_id=source.created_by,
                        sync_source_id=source.id,
                        color=DEFAULT_IMPORT_COLOR,
                    )
                    db.session.add(cal)
                    db.session.flush()
                moved = (
                    CalendarEvent.query.filter_by(sync_source_id=source.id)
                    .update(
                        {CalendarEvent.calendar_id: cal.id},
                        synchronize_session=False,
                    )
                )
                if moved:
                    report.note_ok(f"{moved} Sync-Events -> Kalender {cal.id}")
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        report.note_warn(f"Multi-Kalender-Backfill: {exc}")


def step_backfill_events_calendar(db, report: MigrationReport) -> None:
    engine = db.engine
    if not _table_exists(engine, "calendars"):
        return
    if not _column_exists(engine, "calendar_events", "calendar_id"):
        return

    events_name = "Veranstaltungen"
    events_color = "#e85d04"
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM calendars WHERE calendar_type = 'events' LIMIT 1")
        ).fetchone()
        if row:
            events_id = row[0]
            report.note_skip(f"Veranstaltungen-Kalender existiert (id={events_id})")
        else:
            conn.execute(
                text(
                    "INSERT INTO calendars (name, calendar_type, owner_id, color, created_at) "
                    "VALUES (:name, 'events', NULL, :color, CURRENT_TIMESTAMP)"
                ),
                {"name": events_name, "color": events_color},
            )
            row = conn.execute(
                text("SELECT id FROM calendars WHERE calendar_type = 'events' LIMIT 1")
            ).fetchone()
            events_id = row[0]
            report.note_ok(f"Veranstaltungen-Kalender angelegt (id={events_id})")

        public_row = conn.execute(
            text("SELECT id FROM calendars WHERE calendar_type = 'public' LIMIT 1")
        ).fetchone()
        if not public_row:
            return
        public_id = public_row[0]
        moved = 0
        if _column_exists(engine, "calendar_events", "booking_request_id"):
            result = conn.execute(
                text(
                    "UPDATE calendar_events SET calendar_id = :events_id "
                    "WHERE calendar_id = :public_id AND booking_request_id IS NOT NULL"
                ),
                {"events_id": events_id, "public_id": public_id},
            )
            moved += result.rowcount or 0
        if _table_exists(engine, "event_appointments") and _column_exists(
            engine, "event_appointments", "calendar_event_id"
        ):
            result = conn.execute(
                text(
                    "UPDATE calendar_events SET calendar_id = :events_id "
                    "WHERE calendar_id = :public_id "
                    "AND id IN ("
                    "  SELECT calendar_event_id FROM event_appointments "
                    "  WHERE calendar_event_id IS NOT NULL"
                    ")"
                ),
                {"events_id": events_id, "public_id": public_id},
            )
            moved += result.rowcount or 0
        report.note_ok(f"{moved} Termine -> Veranstaltungen-Kalender")


def step_backfill_module_visibility(db, report: MigrationReport) -> None:
    engine = db.engine
    tables = (
        ("credentials", "public"),
        ("contacts", "public"),
        ("wiki_pages", "public"),
        ("manuals", "public"),
        ("short_links", "private"),
    )
    with engine.begin() as conn:
        for table_name, default_vis in tables:
            if not _column_exists(engine, table_name, "visibility"):
                continue
            result = conn.execute(
                text(
                    f"UPDATE {_safe_ident(table_name)} SET visibility=:vis "
                    f"WHERE visibility IS NULL OR TRIM(visibility) = ''"
                ),
                {"vis": default_vis},
            )
            report.note_ok(
                f"{table_name}.visibility Backfill ({result.rowcount or 0} Zeilen → {default_vis})"
            )


def step_backfill_credential_favorites(db, report: MigrationReport) -> None:
    engine = db.engine
    if not _table_exists(engine, "credential_favorites"):
        return
    if not _column_exists(engine, "credentials", "is_favorite"):
        return
    dialect = engine.dialect.name
    try:
        with engine.begin() as conn:
            if dialect == "sqlite":
                sql = """
                    INSERT OR IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                    SELECT created_by, id, CURRENT_TIMESTAMP
                    FROM credentials
                    WHERE is_favorite = 1
                """
            else:
                sql = """
                    INSERT IGNORE INTO credential_favorites (user_id, credential_id, created_at)
                    SELECT created_by, id, CURRENT_TIMESTAMP
                    FROM credentials
                    WHERE is_favorite = 1
                """
            result = conn.execute(text(sql))
        report.note_ok(
            f"Legacy Credential-Favoriten migriert ({result.rowcount or 0})"
        )
    except Exception as exc:
        report.note_warn(f"Credential-Favoriten-Backfill: {exc}")


def step_migrate_dropboxes(db, report: MigrationReport) -> None:
    engine = db.engine
    if not _table_exists(engine, "folders") or not _table_exists(engine, "public_shares"):
        return
    if not _column_exists(engine, "folders", "is_dropbox"):
        return
    if not _column_exists(engine, "folders", "dropbox_token"):
        return

    dialect = engine.dialect.name
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, dropbox_token, dropbox_password_hash, created_by
                    FROM folders
                    WHERE is_dropbox = 1
                      AND dropbox_token IS NOT NULL
                      AND dropbox_token != ''
                    """
                )
            ).fetchall()
            migrated = 0
            for row in rows:
                folder_id, token, password_hash, created_by = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                )
                exists = conn.execute(
                    text(
                        "SELECT id FROM public_shares "
                        "WHERE resource_type='folder' AND resource_id=:rid AND mode='dropbox' "
                        "LIMIT 1"
                    ),
                    {"rid": folder_id},
                ).fetchone()
                if exists:
                    continue
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            """
                            INSERT INTO public_shares (
                                resource_type, resource_id, mode, token, enabled,
                                password_hash, created_by, created_at, label
                            ) VALUES (
                                'folder', :rid, 'dropbox', :token, 1,
                                :pw, :uid, CURRENT_TIMESTAMP, 'Dropbox'
                            )
                            """
                        ),
                        {
                            "rid": folder_id,
                            "token": token,
                            "pw": password_hash,
                            "uid": created_by,
                        },
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO public_shares (
                                resource_type, resource_id, mode, token, enabled,
                                password_hash, created_by, created_at, label
                            ) VALUES (
                                'folder', :rid, 'dropbox', :token, 1,
                                :pw, :uid, CURRENT_TIMESTAMP, 'Dropbox'
                            )
                            """
                        ),
                        {
                            "rid": folder_id,
                            "token": token,
                            "pw": password_hash,
                            "uid": created_by,
                        },
                    )
                migrated += 1
        report.note_ok(f"{migrated} Dropbox-Ordner -> public_shares")
    except Exception as exc:
        report.note_warn(f"Dropbox-Migration: {exc}")


def step_assessment_defaults(db, report: MigrationReport) -> None:
    try:
        from app.blueprints.assessment.migration import run_assessment_migrations
        from app.models.assessment import AssessmentAppSetting, AssessmentRole

        default_roles = [
            "Administrator",
            "Bewerter",
            "Betrachter",
            "Inspektor",
            "Verwarner",
        ]
        for role_name in default_roles:
            if not AssessmentRole.query.filter_by(name=role_name).first():
                db.session.add(AssessmentRole(name=role_name))
        assessment_defaults = {
            "welcome_title": "Willkommen im Bewertungstool",
            "welcome_subtitle": "Bewerten, Ränge prüfen und Verwaltung - alles an einem Ort.",
            "ranking_active_mode": "standard",
            "ranking_sort_mode": "total",
        }
        for key, value in assessment_defaults.items():
            if not AssessmentAppSetting.query.filter_by(setting_key=key).first():
                db.session.add(
                    AssessmentAppSetting(setting_key=key, setting_value=value)
                )
        db.session.commit()
        run_assessment_migrations()
        report.note_ok("Assessment-Defaults / Migrationen")
    except Exception as exc:
        db.session.rollback()
        report.note_warn(f"Assessment-Migration übersprungen: {exc}")


def step_google_login_index(db, report: MigrationReport) -> None:
    """Unique-Index users.google_sub (Spalten kommen über step_sync_columns)."""
    engine = db.engine
    if not _column_exists(engine, "users", "google_sub"):
        report.note_skip("users.google_sub fehlt - Index übersprungen")
        return
    if _index_exists(engine, "users", "uq_users_google_sub"):
        report.note_skip("uq_users_google_sub bereits vorhanden")
        return
    dialect = engine.dialect.name
    try:
        with engine.begin() as conn:
            if dialect == "sqlite":
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_sub "
                        "ON users(google_sub)"
                    )
                )
            else:
                conn.execute(
                    text("CREATE UNIQUE INDEX uq_users_google_sub ON users(google_sub)")
                )
        report.note_ok("Unique-Index users.google_sub")
    except Exception as exc:
        if _already_exists_error(exc):
            report.note_skip("uq_users_google_sub existiert bereits")
        else:
            report.note_warn(f"Index google_sub: {exc}")


def step_multi_mailbox_indexes(db, report: MigrationReport) -> None:
    """
    Multi-Postfach: alte Unique(name) auf email_folders entfernen und
    Unique(name, mailbox_id) anlegen (MySQL/MariaDB).
    Spalten/Tabellen kommen über step_sync_tables/columns.
    """
    engine = db.engine
    dialect = engine.dialect.name
    if dialect == "sqlite":
        report.note_skip("SQLite: email_folders Unique-Anpassung ohne Rebuild übersprungen")
        return
    if not _table_exists(engine, "email_folders"):
        report.note_skip("email_folders fehlt - Index-Fix übersprungen")
        return

    try:
        indexes = inspect(engine).get_indexes("email_folders")
        for idx in indexes:
            cols = idx.get("column_names") or []
            if idx.get("unique") and cols == ["name"]:
                name = idx.get("name")
                if not name:
                    continue
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE email_folders DROP INDEX `{name}`"))
                report.note_ok(f"Alten Unique-Index {name} auf email_folders.name entfernt")
    except Exception as exc:
        report.note_warn(f"Unique-Index Anpassung email_folders: {exc}")

    if _unique_exists(engine, "email_folders", "uq_email_folder_name_mailbox"):
        report.note_skip("uq_email_folder_name_mailbox bereits vorhanden")
        return
    if not _column_exists(engine, "email_folders", "mailbox_id"):
        report.note_skip("email_folders.mailbox_id fehlt - Unique übersprungen")
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE email_folders "
                    "ADD UNIQUE KEY uq_email_folder_name_mailbox (name, mailbox_id)"
                )
            )
        report.note_ok("Unique (name, mailbox_id) auf email_folders")
    except Exception as exc:
        if _already_exists_error(exc):
            report.note_skip("uq_email_folder_name_mailbox existiert bereits")
        else:
            report.note_warn(f"Unique (name, mailbox_id): {exc}")


def _marker_applied(db, filename: str) -> bool:
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE filename = :f LIMIT 1"),
                {"f": filename},
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _mark_filename(db, filename: str) -> None:
    from datetime import datetime

    from app.utils.auto_migrate import _ensure_schema_migrations_table

    _ensure_schema_migrations_table(db)
    if _marker_applied(db, filename):
        return
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schema_migrations (filename, applied_at) "
                "VALUES (:filename, :applied_at)"
            ),
            {"filename": filename, "applied_at": datetime.utcnow()},
        )


def step_mark_legacy_applied(db, report: MigrationReport) -> None:
    """Markiert alte Einzel-Skript-Namen als angewendet (Tracking-Kompatibilität)."""
    try:
        for filename in _LEGACY_STEP_MARKERS:
            _mark_filename(db, filename)
        for marker in _PREVIOUS_SYNC_MARKERS:
            _mark_filename(db, marker)
        _mark_filename(db, _SYNC_MARKER)
        report.note_ok(
            f"{len(_LEGACY_STEP_MARKERS)} Legacy-Migrationsmarker + Sync-Marker gesetzt"
        )
    except Exception as exc:
        report.note_warn(f"Legacy-Marker: {exc}")


def _run_step(name: str, fn, report: MigrationReport, *args) -> None:
    print("")
    print(f"--- {name} ---")
    try:
        fn(*args, report)
    except Exception as exc:
        report.note_error(f"{name}: {exc}")
        traceback.print_exc()
        try:
            from app import db

            db.session.rollback()
        except Exception:
            pass


def migrate(*, force: bool = False) -> bool:
    print("=" * 60)
    print("Upgrade-Migration: Legacy (2.5+) -> 3.1.0")
    print("=" * 60)

    os.environ.setdefault("PRISMATEAMS_SKIP_BACKGROUND_JOBS", "1")
    os.environ["PRISMATEAMS_RUNNING_MIGRATIONS"] = "1"

    report = MigrationReport()

    try:
        from app import create_app, db

        app = create_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            from app.utils.auto_migrate import _ensure_schema_migrations_table

            _ensure_schema_migrations_table(db)
            if not force and _marker_applied(db, _SYNC_MARKER):
                print(
                    "[OK] Vollständiger Schema-Sync bereits angewendet "
                    f"({_SYNC_MARKER}). Erneut mit --force."
                )
                return True

            _run_step("01 Modelle laden", step_import_models, report)
            _run_step("02 Tabellen synchronisieren", step_sync_tables, report, db)
            _run_step("03 Spalten synchronisieren", step_sync_columns, report, db)
            _run_step(
                "04 public_shares Constraint",
                step_fix_public_shares_constraint,
                report,
                db,
            )
            _run_step("05 BIGINT Dateigrößen", step_ensure_bigint_file_sizes, report, db)
            _run_step(
                "06 email_attachments Repair",
                step_repair_email_attachments,
                report,
                db,
            )
            _run_step(
                "07 Spalten Nachzug (2. Pass)",
                step_sync_columns,
                report,
                db,
            )
            _run_step("08 Google-Login Index", step_google_login_index, report, db)
            _run_step(
                "09 Multi-Mailbox Indexes",
                step_multi_mailbox_indexes,
                report,
                db,
            )
            _run_step("10 SystemSettings", step_seed_settings, report, db)
            _run_step(
                "11 Private-Files space",
                step_backfill_private_files_space,
                report,
                db,
            )
            _run_step(
                "12 contacts.sort_name",
                step_backfill_contacts_sort_name,
                report,
                db,
            )
            _run_step(
                "13 Multi-Kalender Backfill",
                step_backfill_multi_calendars,
                report,
                db,
            )
            _run_step(
                "14 Veranstaltungen-Kalender",
                step_backfill_events_calendar,
                report,
                db,
            )
            _run_step(
                "15 Credential-Favoriten",
                step_backfill_credential_favorites,
                report,
                db,
            )
            _run_step(
                "15b Modul-Visibility Backfill",
                step_backfill_module_visibility,
                report,
                db,
            )
            _run_step("16 Dropbox -> Shares", step_migrate_dropboxes, report, db)
            _run_step("17 Assessment", step_assessment_defaults, report, db)

            print("")
            print("=" * 60)
            print(
                f"Zusammenfassung: {len(report.ok)} OK, "
                f"{len(report.skipped)} uebersprungen, "
                f"{len(report.warnings)} Warnungen, "
                f"{len(report.errors)} Fehler"
            )
            print("=" * 60)

            critical = [
                e
                for e in report.errors
                if "fehlen weiterhin" in e or "Repair fehlgeschlagen" in e
            ]
            if critical:
                print("[FEHLER] Migration mit kritischen Fehlern beendet")
                for err in critical:
                    print(f"  - {err}")
                return False

            # Marker erst nach erfolgreichem Lauf setzen
            _run_step("18 Legacy-Marker", step_mark_legacy_applied, report, db)

            if report.errors:
                print("[WARNUNG] Nicht-kritische Fehler - Schema sollte nutzbar sein")
                for err in report.errors:
                    print(f"  - {err}")

            print("[OK] Upgrade-Migration 3.1.0 abgeschlossen")
            return True
    except Exception as exc:
        print(f"[FEHLER] Migration abgebrochen: {exc}")
        traceback.print_exc()
        return False
    finally:
        os.environ.pop("PRISMATEAMS_RUNNING_MIGRATIONS", None)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Konsolidierter Schema-/Daten-Upgrade auf 3.1.0"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Auch wenn der Sync-Marker schon gesetzt ist, erneut ausführen",
    )
    args = parser.parse_args()
    ok = migrate(force=args.force)
    sys.exit(0 if ok else 1)
