"""Startup schema patches and default-data seed (called from create_app)."""

from __future__ import annotations

import json
import logging
import os


def log_startup(message, level=None):
    """Structured startup log (migrations, schema patches)."""
    logger = logging.getLogger("app.startup")
    text = str(message)
    if level is None:
        if text.startswith("[FEHLER]"):
            level = "error"
        elif text.startswith("[WARNUNG]") or text.startswith("WARNING:"):
            level = "warning"
        else:
            level = "info"
    getattr(logger, level, logger.info)(text)


def current_release_marker(app):
    release = str(app.config.get("ABOUT_RELEASE_VERSION") or "").strip()
    build = str(app.config.get("ABOUT_BUILD_NUMBER") or "").strip()
    if release and build:
        return f"{release}:{build}"
    return release or build or "unknown"


def should_run_migrations_after_update(app):
    """
    Auto-Migration nur nach Update:
    Läuft, wenn der gespeicherte Release-Marker vom aktuellen Marker abweicht.
    """
    try:
        from app.models.settings import SystemSettings
        marker = current_release_marker(app)
        setting = SystemSettings.query.filter_by(key="last_auto_migrated_release").first()
        if not setting:
            return True, marker
        return (str(setting.value or "").strip() != marker), marker
    except Exception:
        return True, current_release_marker(app)


def run_startup_database(app, *, run_schema_init, run_startup_migrations):
    from app import db

    with app.app_context():
        if run_schema_init:
            try:
                from app.utils.schema_init import ensure_all_tables
                from app.models.user import User
                from app.models.chat import Chat, ChatMessage, ChatMember, ChatPin
                from app.models.file import File, FileVersion, Folder, FileEditLock
                from app.models.calendar import CalendarEvent, EventParticipant, PublicCalendarFeed, CalendarSyncSource
                from app.models.email import EmailMessage, EmailPermission, EmailAttachment, EmailFolder
                from app.models.credential import Credential, CredentialFolder, CredentialFavorite
                from app.models.manual import Manual
                from app.models.settings import SystemSettings
                from app.models.whitelist import WhitelistEntry
                from app.models.notification import NotificationSettings, ChatNotificationSettings, PushSubscription, NotificationLog
                from app.models.inventory import Product, BorrowTransaction, ProductFolder, ProductSet, ProductSetItem, ProductDocument, SavedFilter, ProductFavorite, Inventory, InventoryItem, ProductLot, StockMovement, ProductStatusHistory, InventoryItemLock, Checkout, CheckoutItem
                from app.models.api_token import ApiToken
                from app.models.passkey import UserPasskey
                from app.models.wiki import WikiPage, WikiPageVersion, WikiCategory, WikiTag, WikiFavorite
                from app.models.comment import Comment, CommentMention
                from app.models.music import MusicProviderToken, MusicWish, MusicQueue, MusicSettings
                from app.models.media_downloader import MediaDownloadJob
                from app.models.file_converter import ConversionJob
                from app.models.shortlink import ShortLink
                from app.models.kanban import (
                    KanbanBoard, KanbanBoardMember, KanbanList, KanbanCard,
                    KanbanLabel, KanbanCardLabel, KanbanCardAssignee,
                    KanbanChecklist, KanbanChecklistItem, KanbanAttachment,
                    KanbanCardVote, KanbanActivity, KanbanBoardTemplate, KanbanBoardView,
                    KanbanCustomField, KanbanCardFieldValue,
                )
                from app.models.booking import BookingRequest, BookingForm, BookingFormField, BookingFormImage, BookingRequestField, BookingRequestFile, BookingFormRole, BookingFormRoleUser, BookingRequestApproval
                from app.models.event import Event, EventAppointment, EventAssignment, EventInventoryNeed, EventContact, EventTimelineItem
                from app.models.user_session import UserSession
                from app.models.assessment import (
                    AssessmentUser,
                    AssessmentRole,
                    AssessmentUserRole,
                    AssessmentStandType,
                    AssessmentList,
                    AssessmentListSubject,
                    AssessmentRoom,
                    AssessmentStand,
                    AssessmentCriterion,
                    AssessmentEvaluation,
                    AssessmentEvaluationScore,
                    AssessmentVisitorEvaluation,
                    AssessmentVisitorEvaluationScore,
                    AssessmentWarning,
                    AssessmentRoomInspection,
                    AssessmentAppSetting,
                )
                from sqlalchemy import inspect, text

                # Robust: create_all + kritische Tabellen einzeln nachziehen (MySQL-Lock bei Multi-Worker)
                schema_ok, missing_tables = ensure_all_tables(db)
                if not schema_ok:
                    log_startup(f"[WARNUNG] Schema unvollständig, fehlend: {', '.join(missing_tables)}")

                auto_migrate_after_update, release_marker = should_run_migrations_after_update(app)
                should_run_startup_migrations = run_startup_migrations or auto_migrate_after_update

                # Migrationen laufen automatisch nach Update (Release-Marker-Wechsel)
                # oder explizit via PRISMATEAMS_STARTUP_MIGRATIONS=true.
                if should_run_startup_migrations and not os.getenv("PRISMATEAMS_RUNNING_MIGRATIONS"):
                    try:
                        from app.utils.auto_migrate import run_pending_migrations
                        run_pending_migrations(db)
                    except Exception as auto_mig_err:
                        log_startup(f"[WARNUNG] Auto-Migration fehlgeschlagen: {auto_mig_err}")
                    # Nach Migrationen nochmals kritische Tabellen sicherstellen
                    try:
                        ensure_all_tables(db)
                    except Exception as schema_again_err:
                        log_startup(f"[WARNUNG] Schema-Nachprüfung fehlgeschlagen: {schema_again_err}")
                else:
                    log_startup("[INFO] Startup-Migrationen übersprungen (kein Update erkannt)")
                
                try:
                    from sqlalchemy import inspect
                    inspector = inspect(db.engine)
                    if 'folders' in inspector.get_table_names():
                        columns = {col['name']: col for col in inspector.get_columns('folders')}
                        if 'color' not in columns:
                            log_startup("[INFO] Ergänze folders.color ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE folders ADD COLUMN color VARCHAR(16)"))
                            log_startup("[OK] folders.color hinzugefügt")
                        if 'team_id' not in columns:
                            log_startup("[INFO] Ergänze folders.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE folders ADD COLUMN team_id INTEGER NULL"))
                            log_startup("[OK] folders.team_id hinzugefügt")
                        if 'is_team_root' not in columns:
                            log_startup("[INFO] Ergänze folders.is_team_root ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE folders ADD COLUMN is_team_root BOOLEAN NOT NULL DEFAULT 0"
                                ))
                            log_startup("[OK] folders.is_team_root hinzugefügt")

                    if 'files' in inspector.get_table_names():
                        file_cols = {col['name'] for col in inspector.get_columns('files')}
                        if 'team_id' not in file_cols:
                            log_startup("[INFO] Ergänze files.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE files ADD COLUMN team_id INTEGER NULL"))
                            log_startup("[OK] files.team_id hinzugefügt")

                    if 'resource_acl' in inspector.get_table_names():
                        acl_cols = {col['name'] for col in inspector.get_columns('resource_acl')}
                        if 'grantee_team_id' not in acl_cols:
                            log_startup("[INFO] Ergänze resource_acl.grantee_team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE resource_acl ADD COLUMN grantee_team_id INTEGER NULL"
                                ))
                            log_startup("[OK] resource_acl.grantee_team_id hinzugefügt")

                    if 'kanban_cards' in inspector.get_table_names():
                        kanban_cols = {col['name'] for col in inspector.get_columns('kanban_cards')}
                        if 'poll_text' not in kanban_cols:
                            log_startup("[INFO] Ergänze kanban_cards.poll_text ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_cards ADD COLUMN poll_text TEXT"))
                            log_startup("[OK] kanban_cards.poll_text hinzugefügt")
                        if 'completed_at' not in kanban_cols:
                            log_startup("[INFO] Ergänze kanban_cards.completed_at ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_cards ADD COLUMN completed_at DATETIME NULL"))
                            log_startup("[OK] kanban_cards.completed_at hinzugefügt")

                    if 'kanban_attachments' in inspector.get_table_names():
                        att_cols = {col['name']: col for col in inspector.get_columns('kanban_attachments')}
                        if 'url' not in att_cols:
                            log_startup("[INFO] Ergänze kanban_attachments.url ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE kanban_attachments ADD COLUMN url VARCHAR(1000) NULL"))
                            log_startup("[OK] kanban_attachments.url hinzugefügt")
                        dialect = db.engine.dialect.name
                        if dialect == 'mysql':
                            for col_name in ('filename', 'original_filename', 'storage_path'):
                                col = att_cols.get(col_name)
                                if col and not col.get('nullable', True):
                                    log_startup(f"[INFO] Lockere kanban_attachments.{col_name} (nullable) ...")
                                    with db.engine.begin() as connection:
                                        connection.execute(text(
                                            f"ALTER TABLE kanban_attachments MODIFY COLUMN {col_name} VARCHAR(500) NULL"
                                            if col_name == 'storage_path'
                                            else f"ALTER TABLE kanban_attachments MODIFY COLUMN {col_name} VARCHAR(255) NULL"
                                        ))
                                    log_startup(f"[OK] kanban_attachments.{col_name} nullable")
                        elif dialect == 'sqlite':
                            # SQLite: nullable change via recreate is heavy; new rows can use NULL if column allows
                            pass

                    table_names = inspector.get_table_names()
                    if 'credential_folders' not in table_names:
                        log_startup("[INFO] Erstelle credential_folders ...")
                        CredentialFolder.__table__.create(db.engine, checkfirst=True)
                        log_startup("[OK] credential_folders erstellt")
                    elif 'credential_folders' in table_names:
                        folder_columns = {col['name'] for col in inspector.get_columns('credential_folders')}
                        if 'visibility' not in folder_columns:
                            log_startup("[INFO] Ergänze credential_folders.visibility ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE credential_folders ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'public'"
                                ))
                            log_startup("[OK] credential_folders.visibility hinzugefügt")
                        if 'team_id' not in folder_columns:
                            log_startup("[INFO] Ergänze credential_folders.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE credential_folders ADD COLUMN team_id INTEGER NULL"
                                ))
                            log_startup("[OK] credential_folders.team_id hinzugefügt")

                    if 'manual_folders' in table_names:
                        manual_folder_columns = {col['name'] for col in inspector.get_columns('manual_folders')}
                        if 'visibility' not in manual_folder_columns:
                            log_startup("[INFO] Ergänze manual_folders.visibility ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE manual_folders ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'public'"
                                ))
                            log_startup("[OK] manual_folders.visibility hinzugefügt")
                        if 'team_id' not in manual_folder_columns:
                            log_startup("[INFO] Ergänze manual_folders.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE manual_folders ADD COLUMN team_id INTEGER NULL"
                                ))
                            log_startup("[OK] manual_folders.team_id hinzugefügt")

                    if 'credentials' in table_names:
                        credential_columns = {col['name'] for col in inspector.get_columns('credentials')}
                        if 'folder_id' not in credential_columns:
                            log_startup("[INFO] Ergänze credentials.folder_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE credentials ADD COLUMN folder_id INTEGER NULL"))
                            log_startup("[OK] credentials.folder_id hinzugefügt")

                        if 'is_favorite' not in credential_columns:
                            log_startup("[INFO] Ergänze credentials.is_favorite ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE credentials ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
                            log_startup("[OK] credentials.is_favorite hinzugefügt")

                    if 'credential_favorites' not in inspector.get_table_names():
                        log_startup("[INFO] Erstelle credential_favorites ...")
                        CredentialFavorite.__table__.create(db.engine, checkfirst=True)
                        log_startup("[OK] credential_favorites erstellt")
                        # Legacy-Favoriten auf Ersteller übernehmen
                        try:
                            dialect = db.engine.dialect.name
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
                            with db.engine.begin() as connection:
                                connection.execute(text(sql))
                            log_startup("[OK] Legacy credential favorites migriert")
                        except Exception as fav_err:
                            log_startup(f"[WARNUNG] Legacy-Favoriten-Migration: {fav_err}")

                    if ('users' in inspector.get_table_names() and
                            'language' not in {col['name'] for col in inspector.get_columns('users')}):
                        log_startup("[INFO] Ergänze users.language ...")
                        with db.engine.begin() as connection:
                            connection.execute(text(
                                "ALTER TABLE users ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'de'"
                            ))
                        log_startup("[OK] users.language hinzugefügt")
                    
                    # Sicherheitsfeatures-Migration (2FA, Rate Limiting, Session-Management)
                    # Vollständige Migration läuft über Auto-Migration (migrate_to_2_4_3.py).
                    # Hier nur Notfall-Fallback, falls Spalten noch fehlen.
                    if 'users' in inspector.get_table_names():
                        columns = {col['name'] for col in inspector.get_columns('users')}
                        security_columns = {
                            ('totp_secret', 'VARCHAR(255)'),
                            ('totp_enabled', 'BOOLEAN DEFAULT 0'),
                            ('password_changed_at', 'DATETIME'),
                            ('failed_login_attempts', 'INTEGER DEFAULT 0'),
                            ('failed_login_until', 'DATETIME'),
                        }
                        missing = [(n, d) for n, d in security_columns if n not in columns]
                        if missing:
                            log_startup("[INFO] Ergänze fehlende Security-Spalten an users ...")
                            with db.engine.begin() as connection:
                                for col_name, col_ddl in missing:
                                    connection.execute(text(
                                        f"ALTER TABLE users ADD COLUMN {col_name} {col_ddl}"
                                    ))
                            log_startup("[OK] Security-Spalten ergänzt")
                        if 'user_sessions' not in inspector.get_table_names():
                            log_startup("[INFO] user_sessions fehlt – wird von Auto-Migration (2.4.3) angelegt")

                    # Kalender-Events: event_color ergänzen
                    if 'calendar_events' in inspector.get_table_names():
                        calendar_columns = {col['name'] for col in inspector.get_columns('calendar_events')}
                        if 'event_color' not in calendar_columns:
                            log_startup("[INFO] Ergänze calendar_events.event_color ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events "
                                    "ADD COLUMN event_color VARCHAR(7) NOT NULL DEFAULT '#0d6efd'"
                                ))
                            log_startup("[OK] calendar_events.event_color hinzugefügt")
                        if 'sync_source_id' not in calendar_columns:
                            log_startup("[INFO] Ergänze calendar_events.sync_source_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN sync_source_id INTEGER NULL"
                                ))
                            log_startup("[OK] calendar_events.sync_source_id hinzugefügt")
                        if 'ical_uid' not in calendar_columns:
                            log_startup("[INFO] Ergänze calendar_events.ical_uid ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN ical_uid VARCHAR(255) NULL"
                                ))
                            log_startup("[OK] calendar_events.ical_uid hinzugefügt")

                    # Kalender Sync-Sources Tabelle
                    if 'calendar_sync_sources' not in inspector.get_table_names():
                        log_startup("[INFO] Erstelle calendar_sync_sources ...")
                        from app.models.calendar import CalendarSyncSource as _CalendarSyncSource
                        _CalendarSyncSource.__table__.create(db.engine, checkfirst=True)
                        log_startup("[OK] calendar_sync_sources erstellt")

                    # Multi-Kalender: calendars + calendar_id
                    if 'calendars' not in inspector.get_table_names():
                        log_startup("[INFO] Erstelle calendars ...")
                        from app.models.calendar import Calendar as _Calendar
                        _Calendar.__table__.create(db.engine, checkfirst=True)
                        log_startup("[OK] calendars erstellt")
                    if 'calendar_events' in inspector.get_table_names():
                        calendar_columns = {col['name'] for col in inspector.get_columns('calendar_events')}
                        if 'calendar_id' not in calendar_columns:
                            log_startup("[INFO] Ergänze calendar_events.calendar_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    "ALTER TABLE calendar_events ADD COLUMN calendar_id INTEGER NULL"
                                ))
                            log_startup("[OK] calendar_events.calendar_id hinzugefügt")

                    if 'calendars' in inspector.get_table_names():
                        cal_cols = {col['name'] for col in inspector.get_columns('calendars')}
                        cal_alters = []
                        if 'team_id' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN team_id INTEGER NULL")
                        if 'is_default' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0")
                        if 'hidden_from_others' not in cal_cols:
                            cal_alters.append("ALTER TABLE calendars ADD COLUMN hidden_from_others BOOLEAN NOT NULL DEFAULT 0")
                        if cal_alters:
                            log_startup("[INFO] Ergänze calendars Team-/Default-Spalten ...")
                            with db.engine.begin() as connection:
                                for stmt in cal_alters:
                                    connection.execute(text(stmt))
                            log_startup("[OK] calendars Team-/Default-Spalten ergänzt")

                    if 'chats' in inspector.get_table_names():
                        chat_cols = {col['name'] for col in inspector.get_columns('chats')}
                        if 'team_id' not in chat_cols:
                            log_startup("[INFO] Ergänze chats.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE chats ADD COLUMN team_id INTEGER NULL"))
                            log_startup("[OK] chats.team_id hinzugefügt")
                        chat_indexes = inspector.get_indexes('chats')
                        has_team_unique = any(
                            ix.get('unique') and ix.get('column_names') == ['team_id']
                            for ix in chat_indexes
                        ) or any(
                            u.get('column_names') == ['team_id']
                            for u in inspector.get_unique_constraints('chats')
                        )
                        if not has_team_unique:
                            log_startup("[INFO] Lege Unique-Index chats.team_id an ...")
                            try:
                                with db.engine.begin() as connection:
                                    connection.execute(text(
                                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_team_id ON chats(team_id)"
                                    ))
                                log_startup("[OK] Unique-Index chats.team_id angelegt")
                            except Exception as idx_error:
                                log_startup(f"[WARNUNG] Unique-Index chats.team_id: {idx_error}")

                    # Veranstaltungsmodul: Rückwärtskompatibilität für ältere Datenbanken
                    table_names = set(inspector.get_table_names())
                    if 'events' in table_names:
                        event_columns = {col['name'] for col in inspector.get_columns('events')}
                        with db.engine.begin() as connection:
                            if 'is_archived' not in event_columns:
                                connection.execute(
                                    text("ALTER TABLE events ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0")
                                )
                                log_startup("[OK] events.is_archived hinzugefügt")
                            if 'archived_at' not in event_columns:
                                connection.execute(
                                    text("ALTER TABLE events ADD COLUMN archived_at DATETIME NULL")
                                )
                                log_startup("[OK] events.archived_at hinzugefügt")

                    if 'event_timeline_items' in table_names:
                        timeline_columns = {
                            col['name'] for col in inspector.get_columns('event_timeline_items')
                        }
                        if 'appointment_id' not in timeline_columns:
                            with db.engine.begin() as connection:
                                connection.execute(
                                    text(
                                        "ALTER TABLE event_timeline_items "
                                        "ADD COLUMN appointment_id INTEGER NULL"
                                    )
                                )
                            log_startup("[OK] event_timeline_items.appointment_id hinzugefügt")

                    # Chat-Messages: metadata_json für strukturierte Nachrichtentypen ergänzen
                    if 'chat_messages' in inspector.get_table_names():
                        chat_columns = {col['name'] for col in inspector.get_columns('chat_messages')}
                        if 'metadata_json' not in chat_columns:
                            log_startup("[INFO] Ergänze chat_messages.metadata_json ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT"))
                            log_startup("[OK] chat_messages.metadata_json hinzugefügt")

                    # Kontakte: sort_name für flexible Sortierung ergänzen
                    if 'contacts' in inspector.get_table_names():
                        contact_columns = {col['name'] for col in inspector.get_columns('contacts')}
                        if 'salutation' not in contact_columns:
                            log_startup("[INFO] Ergänze contacts.salutation ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE contacts ADD COLUMN salutation VARCHAR(50)"))
                            log_startup("[OK] contacts.salutation hinzugefügt")
                        if 'sort_name' not in contact_columns:
                            log_startup("[INFO] Ergänze contacts.sort_name ...")
                            with db.engine.begin() as connection:
                                connection.execute(text("ALTER TABLE contacts ADD COLUMN sort_name VARCHAR(255)"))
                                connection.execute(text(
                                    "UPDATE contacts SET sort_name = name "
                                    "WHERE sort_name IS NULL OR TRIM(sort_name) = ''"
                                ))
                            log_startup("[OK] contacts.sort_name hinzugefügt und initialisiert")

                    visibility_tables = (
                        ('credentials', 'public'),
                        ('contacts', 'public'),
                        ('wiki_pages', 'public'),
                        ('manuals', 'public'),
                        ('short_links', 'private'),
                    )
                    current_tables = set(inspector.get_table_names())
                    for vis_table, vis_default in visibility_tables:
                        if vis_table not in current_tables:
                            continue
                        vis_cols = {col['name'] for col in inspector.get_columns(vis_table)}
                        if 'visibility' not in vis_cols:
                            log_startup(f"[INFO] Ergänze {vis_table}.visibility ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    f"ALTER TABLE {vis_table} ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT '{vis_default}'"
                                ))
                            log_startup(f"[OK] {vis_table}.visibility hinzugefügt")
                        if 'team_id' not in vis_cols:
                            log_startup(f"[INFO] Ergänze {vis_table}.team_id ...")
                            with db.engine.begin() as connection:
                                connection.execute(text(
                                    f"ALTER TABLE {vis_table} ADD COLUMN team_id INTEGER NULL"
                                ))
                            log_startup(f"[OK] {vis_table}.team_id hinzugefügt")

                    # E-Mail-Manager-Großupdate: Farbpunkt/Keyword-Sync-Spalten ergänzen
                    if 'email_messages' in inspector.get_table_names():
                        email_columns = {col['name'] for col in inspector.get_columns('email_messages')}
                        mail_manager_columns = []
                        if 'color_dot' not in email_columns:
                            mail_manager_columns.append(("color_dot", "VARCHAR(24) NULL"))
                        if 'is_flagged' not in email_columns:
                            mail_manager_columns.append(("is_flagged", "BOOLEAN NOT NULL DEFAULT 0"))
                        if 'imap_color_keyword' not in email_columns:
                            mail_manager_columns.append(("imap_color_keyword", "VARCHAR(64) NULL"))
                        if 'last_flag_sync_at' not in email_columns:
                            mail_manager_columns.append(("last_flag_sync_at", "DATETIME NULL"))
                        if mail_manager_columns:
                            log_startup("[INFO] Ergänze email_messages Mail-Manager-Spalten ...")
                            try:
                                with db.engine.begin() as connection:
                                    for col_name, col_def in mail_manager_columns:
                                        connection.execute(text(
                                            f"ALTER TABLE email_messages ADD COLUMN {col_name} {col_def}"
                                        ))
                                log_startup(
                                    "[OK] email_messages Mail-Manager-Spalten hinzugefügt: "
                                    + ", ".join(c[0] for c in mail_manager_columns)
                                )
                            except Exception as mail_col_error:
                                log_startup(f"[WARNUNG] Mail-Manager-Spalten konnten nicht hinzugefügt werden: {mail_col_error}")
                except Exception as migration_error:
                    log_startup(f"[WARNUNG] Inline-Schema-Nachrüstung fehlgeschlagen: {migration_error}")
                    log_startup("[INFO] Bitte prüfen: python migrations/run_all.py")

                try:
                    from sqlalchemy import inspect, text
                    from app.models.assessment import (
                        AssessmentAppSetting,
                        AssessmentRole,
                    )

                    inspector = inspect(db.engine)
                    dialect = db.engine.dialect.name
                    existing_tables = set(inspector.get_table_names())

                    if 'ass_users' in existing_tables:
                        user_columns = {col['name'] for col in inspector.get_columns('ass_users')}
                        if 'theme_mode' not in user_columns:
                            log_startup("[INFO] Ergänze ass_users.theme_mode ...")
                            stmt = "ALTER TABLE ass_users ADD COLUMN theme_mode VARCHAR(16) NOT NULL DEFAULT 'light'"
                            with db.engine.begin() as connection:
                                connection.execute(text(stmt))
                            log_startup("[OK] ass_users.theme_mode hinzugefügt")

                    default_roles = ['Administrator', 'Bewerter', 'Betrachter', 'Inspektor', 'Verwarner']
                    for role_name in default_roles:
                        role = AssessmentRole.query.filter_by(name=role_name).first()
                        if not role:
                            role = AssessmentRole(name=role_name)
                            db.session.add(role)
                            db.session.flush()

                    assessment_defaults = {
                        'welcome_title': 'Willkommen im Bewertungstool',
                        'welcome_subtitle': 'Bewerten, Ränge prüfen und Verwaltung – alles an einem Ort.',
                        'ranking_active_mode': 'standard',
                        'ranking_sort_mode': 'total',
                    }
                    for key, value in assessment_defaults.items():
                        if not AssessmentAppSetting.query.filter_by(setting_key=key).first():
                            db.session.add(AssessmentAppSetting(setting_key=key, setting_value=value))
                    db.session.commit()

                    if should_run_startup_migrations:
                        from app.blueprints.assessment.migration import run_assessment_migrations
                        run_assessment_migrations()
                except Exception as assessment_error:
                    db.session.rollback()
                    log_startup(f"[WARNUNG] Assessment-Modul-Migration übersprungen: {assessment_error}")

                if should_run_startup_migrations:
                    try:
                        from app.models.settings import SystemSettings
                        marker_setting = SystemSettings.query.filter_by(
                            key='last_auto_migrated_release'
                        ).first()
                        if not marker_setting:
                            marker_setting = SystemSettings(
                                key='last_auto_migrated_release',
                                value=release_marker,
                                description='Letzter Release-Marker mit erfolgreicher Startup-Auto-Migration'
                            )
                            db.session.add(marker_setting)
                        else:
                            marker_setting.value = release_marker
                            if not marker_setting.description:
                                marker_setting.description = (
                                    'Letzter Release-Marker mit erfolgreicher Startup-Auto-Migration'
                                )
                        db.session.commit()
                    except Exception as marker_err:
                        db.session.rollback()
                        log_startup(f"[WARNUNG] Release-Marker für Auto-Migration konnte nicht gespeichert werden: {marker_err}")
                
                from app.models.email import EmailFolder
                
                standard_folders = [
                    {'name': 'INBOX', 'display_name': 'Posteingang', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Sent', 'display_name': 'Gesendet', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Drafts', 'display_name': 'Entwürfe', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Trash', 'display_name': 'Papierkorb', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Spam', 'display_name': 'Spam', 'folder_type': 'standard', 'is_system': True},
                    {'name': 'Archive', 'display_name': 'Archiv', 'folder_type': 'standard', 'is_system': True}
                ]
                
                for folder_data in standard_folders:
                    existing_folder = EmailFolder.query.filter_by(
                        name=folder_data['name'], mailbox_id=None
                    ).first()
                    if not existing_folder:
                        folder = EmailFolder(**folder_data)
                        db.session.add(folder)
                        log_startup(f"Created standard folder: {folder_data['display_name']}")
                
                db.session.commit()
                log_startup("[OK] Standard email folders ensured")
                
                from app.models.settings import SystemSettings
                from app.models.chat import Chat
                from app.models.user import User
                from sqlalchemy import inspect, text
                
                if not SystemSettings.query.filter_by(key='module_assessment').first():
                    db.session.add(SystemSettings(
                        key='module_assessment',
                        value='True',
                        description='Modul module_assessment aktiviert'
                    ))
                
                if not SystemSettings.query.filter_by(key='email_footer_text').first():
                    footer = SystemSettings(
                        key='email_footer_text',
                        value='Mit freundlichen Grüßen\nIhr Team',
                        description='Standard-Footer für E-Mails'
                    )
                    db.session.add(footer)
                
                if not SystemSettings.query.filter_by(key='email_footer_image').first():
                    footer_img = SystemSettings(
                        key='email_footer_image',
                        value='',
                        description='Footer-Bild URL für E-Mails'
                    )
                    db.session.add(footer_img)

                if not SystemSettings.query.filter_by(key='default_language').first():
                    db.session.add(SystemSettings(
                        key='default_language',
                        value='de',
                        description='Standardsprache für die Benutzeroberfläche'
                    ))

                if not SystemSettings.query.filter_by(key='email_language').first():
                    db.session.add(SystemSettings(
                        key='email_language',
                        value='de',
                        description='Standardsprache für System-E-Mails'
                    ))

                if not SystemSettings.query.filter_by(key='available_languages').first():
                    db.session.add(SystemSettings(
                        key='available_languages',
                        value='["de","en","pt","es","ru"]',
                        description='Liste der aktivierten Sprachen'
                    ))

                if not SystemSettings.query.filter_by(key='portal_timezone').first():
                    db.session.add(SystemSettings(
                        key='portal_timezone',
                        value='Europe/Berlin',
                        description='Globale Zeitzone für Datums- und Zeitangaben'
                    ))
                
                language_settings = {
                    'default_language': (
                        'de',
                        'Standardsprache der Benutzeroberfläche für neue Benutzer.'
                    ),
                    'email_language': (
                        'de',
                        'Sprache für automatisch versendete System-E-Mails.'
                    ),
                    'available_languages': (
                        json.dumps(['de', 'en', 'pt', 'es', 'ru']),
                        'Aktivierte Sprachen im Portal (JSON-Liste).'
                    )
                }
                
                for key, (value, description) in language_settings.items():
                    setting = SystemSettings.query.filter_by(key=key).first()
                    if not setting:
                        db.session.add(SystemSettings(key=key, value=value, description=description))
                    else:
                        if not setting.value:
                            setting.value = value
                        if description and not setting.description:
                            setting.description = description

                from app.utils.bot_protection import ensure_default_settings
                ensure_default_settings()
                from app.utils.search_indexing import ensure_default_settings as ensure_indexing_settings
                ensure_indexing_settings()
                
                try:
                    inspector = inspect(db.engine)
                    if 'users' in inspector.get_table_names():
                        columns = {col['name'] for col in inspector.get_columns('users')}
                        if 'language' in columns:
                            with db.engine.begin() as connection:
                                connection.execute(
                                    text("""
                                        UPDATE users
                                        SET language = :default_lang
                                        WHERE language IS NULL OR TRIM(language) = ''
                                    """),
                                    {'default_lang': 'de'}
                                )
                except Exception as e:
                    app.logger.warning("Konnte Benutzersprachen nicht aktualisieren: %s", e)

                main_chat = Chat.query.filter_by(is_main_chat=True).first()
                if not main_chat:
                    main_chat = Chat(
                        name='Team Chat',
                        is_main_chat=True,
                        is_direct_message=False
                    )
                    db.session.add(main_chat)
                    db.session.flush()
                    
                    from app.models.chat import ChatMember
                    # Prüfe ob has_full_access Spalte existiert
                    try:
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                for user in active_users:
                                    if has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                for user in active_users:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        log_startup(f"WARNING: Could not check has_full_access column: {e}")
                        # Fallback: Füge alle aktiven Benutzer hinzu
                        from app.models.chat import ChatMember
                        active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                        for user in active_users:
                            member = ChatMember(
                                chat_id=main_chat.id,
                                user_id=user.id
                            )
                            db.session.add(member)
                else:
                    from app.models.chat import ChatMember
                    try:
                        # Prüfe ob has_full_access Spalte existiert
                        from sqlalchemy import inspect
                        inspector = inspect(db.engine)
                        if 'users' in inspector.get_table_names():
                            columns = {col['name'] for col in inspector.get_columns('users')}
                            if 'has_full_access' in columns:
                                from app.utils.access_control import has_module_access
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids and has_module_access(user, 'module_chat'):
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                            else:
                                # Spalte existiert noch nicht - füge alle aktiven Benutzer hinzu (Rückwärtskompatibilität)
                                active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                                existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                                existing_user_ids = [member.user_id for member in existing_members]
                                
                                for user in active_users:
                                    if user.id not in existing_user_ids:
                                        member = ChatMember(
                                            chat_id=main_chat.id,
                                            user_id=user.id
                                        )
                                        db.session.add(member)
                        else:
                            # Fallback: Füge alle aktiven Benutzer hinzu
                            active_users = User.query.filter_by(is_active=True, is_guest=False).all()
                            existing_members = ChatMember.query.filter_by(chat_id=main_chat.id).all()
                            existing_user_ids = [member.user_id for member in existing_members]
                            
                            for user in active_users:
                                if user.id not in existing_user_ids:
                                    member = ChatMember(
                                        chat_id=main_chat.id,
                                        user_id=user.id
                                    )
                                    db.session.add(member)
                    except Exception as e:
                        log_startup(f"WARNING: Could not update main chat members: {e}")

                try:
                    from app.models.settings import SystemSettings as _Sys
                    if not _Sys.query.filter_by(key='calendar_personal_enabled').first():
                        multi = _Sys.query.filter_by(key='calendar_multi_enabled').first()
                        val = 'True' if multi and str(multi.value).lower() == 'true' else 'False'
                        db.session.add(_Sys(key='calendar_personal_enabled', value=val, description='Private Kalender aktiv'))
                    if not _Sys.query.filter_by(key='calendar_team_enabled').first():
                        db.session.add(_Sys(key='calendar_team_enabled', value='False', description='Team-Kalender aktiv'))
                except Exception as e:
                    log_startup(f"WARNING: Kalender-Settings konnten nicht migriert werden: {e}")

                try:
                    inspector = inspect(db.engine)
                    chat_cols = {c['name'] for c in inspector.get_columns('chats')} if 'chats' in inspector.get_table_names() else set()
                    if 'team_id' in chat_cols:
                        from app.utils.team_chat import ensure_all_team_chats
                        ensure_all_team_chats()
                except Exception as e:
                    log_startup(f"WARNING: Team-Chats konnten nicht angelegt werden: {e}")

                try:
                    inspector = inspect(db.engine)
                    cal_cols = {c['name'] for c in inspector.get_columns('calendars')} if 'calendars' in inspector.get_table_names() else set()
                    if 'is_default' in cal_cols:
                        from app.utils.multi_calendars import backfill_space_calendars
                        from app.models.calendar import Calendar as _Cal
                        first_public = _Cal.query.filter_by(calendar_type='public').order_by(_Cal.id.asc()).first()
                        if first_public and not first_public.is_default:
                            first_public.is_default = True
                        backfill_space_calendars()
                except Exception as e:
                    log_startup(f"WARNING: Kalender-Backfill fehlgeschlagen: {e}")
                
                db.session.commit()
                
            except Exception as e:
                log_startup(f"[WARNUNG] Warnung beim Erstellen der Datenbank-Tabellen: {e}")

        try:
            from app.utils.file_storage_limits import sync_flask_max_content_length
            synced = sync_flask_max_content_length(app)
            log_startup(f"[INFO] MAX_CONTENT_LENGTH aus Datei-Einstellungen: {synced} Bytes")
        except Exception as sync_err:
            log_startup(f"[WARNUNG] MAX_CONTENT_LENGTH-Sync fehlgeschlagen: {sync_err}")
    
