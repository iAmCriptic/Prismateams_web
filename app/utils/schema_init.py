"""
Zuverlässige DB-Schema-Initialisierung (First-Boot, Installer, App-Start).

Problemlage:
- create_all() bricht bei einem Fehler ab → viele Tabellen fehlen
- DEBUG/Reloader-Logik kann Init überspringen
- Multi-Worker-Starts brauchen eine Sperre

Dieses Modul importiert alle Modelle, legt fehlende Tabellen an und prüft
kritische Tabellen explizit nach.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Iterable

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

# Kritische Tabellen, die nach Fresh-Install existieren müssen
CRITICAL_TABLES = (
    "users",
    "user_sessions",
    "chats",
    "chat_messages",
    "chat_members",
    "files",
    "file_versions",
    "folders",
    "calendar_events",
    "event_participants",
    "calendars",
    "email_messages",
    "email_attachments",
    "email_permissions",
    "mailboxes",
    "mailbox_memberships",
    "mailbox_user_prefs",
    "mailbox_auto_replies",
    "mailbox_auto_reply_logs",
    "teams",
    "team_members",
    "credentials",
    "manuals",
    "manual_folders",
    "system_settings",
    "cookie_consent_logs",
    "whitelist_entries",
    "products",
    "checkouts",
    "checkout_items",
    "wiki_pages",
    "wiki_favorites",
    "events",
    "event_appointments",
    "event_assignments",
    "event_inventory_needs",
    "event_contacts",
    "event_timeline_items",
    "contacts",
    "public_shares",
    "booking_forms",
    "booking_requests",
    "surveys",
    "survey_pages",
    "survey_questions",
    "survey_logic_rules",
    "survey_responses",
    "survey_answers",
    "survey_email_verifications",
    "survey_response_locks",
    "protocols",
    "protocol_agenda_items",
    "meetings",
    "meeting_invites",
    "conversion_jobs",
    "schema_migrations",
)


def import_all_models() -> None:
    """Lädt alle Modelle in SQLAlchemy-Metadata (auch Module außerhalb von app.models)."""
    import app.models  # noqa: F401

    from app.models.booking import (  # noqa: F401
        BookingForm,
        BookingFormField,
        BookingFormImage,
        BookingFormRole,
        BookingFormRoleUser,
        BookingRequest,
        BookingRequestApproval,
        BookingRequestField,
        BookingRequestFile,
        BookingRequestMessage,
    )
    from app.models.calendar import Calendar  # noqa: F401
    from app.models.contact import Contact, ContactFavorite  # noqa: F401
    from app.models.email import EmailFolder, MailboxAutoReply, MailboxAutoReplyLog  # noqa: F401
    from app.models.event import (  # noqa: F401
        Event,
        EventAppointment,
        EventAssignment,
        EventContact,
        EventInventoryNeed,
        EventTimelineItem,
    )
    from app.models.guest import GuestShareAccess  # noqa: F401
    from app.models.inventory import Checkout, CheckoutItem  # noqa: F401
    from app.models.manual import Manual, ManualFolder  # noqa: F401
    from app.models.public_share import PublicShare, ShareAccessLog  # noqa: F401
    from app.models.team import Team, TeamMember, TeamModuleSetting, TeamInviteCode  # noqa: F401
    from app.models.wiki import WikiFavorite  # noqa: F401
    from app.models.survey import (  # noqa: F401
        Survey,
        SurveyPage,
        SurveyQuestion,
        SurveyLogicRule,
        SurveyResponse,
        SurveyAnswer,
        SurveyEmailVerification,
        SurveyResponseLock,
    )
    from app.models.protocol import Protocol, ProtocolAgendaItem  # noqa: F401
    from app.models.meetings import Meeting, MeetingInvite  # noqa: F401


def should_run_startup_schema(*, debug: bool = False) -> bool:
    """
    True außer im Flask-Debug-Reloader-Parent (Child initialisiert).

    Gunicorn / One-Shot / CLI: immer True.
    """
    if os.environ.get("PRISMATEAMS_SKIP_SCHEMA_INIT", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("PRISMATEAMS_FORCE_SCHEMA_INIT", "").lower() in ("1", "true", "yes"):
        return True
    if debug and os.environ.get("WERKZEUG_SERVER_FD") and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


class _SchemaLock:
    """Prozessübergreifende Sperre (MySQL GET_LOCK oder Datei-Fallback)."""

    def __init__(self, db, lock_name: str = "prismateams_schema_init", timeout: int = 120):
        self.db = db
        self.lock_name = lock_name
        self.timeout = timeout
        self._conn = None
        self._file = None
        self._mode = None

    def __enter__(self):
        dialect = self.db.engine.dialect.name
        if dialect in ("mysql", "mariadb"):
            try:
                # Connection offen halten – GET_LOCK gilt pro Session
                self._conn = self.db.engine.connect()
                row = self._conn.execute(
                    text("SELECT GET_LOCK(:name, :timeout)"),
                    {"name": self.lock_name, "timeout": self.timeout},
                ).fetchone()
                if row and row[0] == 1:
                    self._mode = "mysql"
                    return self
                logger.warning("Schema-Lock Timeout – fahre ohne exklusiven Lock fort")
                self._conn.close()
                self._conn = None
            except Exception as exc:
                logger.warning("MySQL Schema-Lock fehlgeschlagen: %s", exc)
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None

        # Datei-Lock (Linux Installer / Fallback)
        lock_path = os.environ.get(
            "PRISMATEAMS_SCHEMA_LOCK_FILE",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".schema_init.lock"),
        )
        try:
            self._file = open(lock_path, "a+", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
            self._mode = "file"
        except Exception as exc:
            logger.warning("Datei-Schema-Lock fehlgeschlagen: %s", exc)
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._mode == "mysql" and self._conn is not None:
            try:
                self._conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": self.lock_name})
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._file is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        return False


def _is_mysql_orphan_error(exc: BaseException) -> bool:
    """MySQL 1932 (Dictionary ohne Engine) / 1813 (orphan Tablespace)."""
    msg = str(exc).lower()
    return any(
        needle in msg
        for needle in (
            "1932",
            "doesn't exist in engine",
            "1813",
            "tablespace for table",
            "please discard the tablespace",
        )
    )


def _quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _drop_mysql_table(db, table_name: str) -> bool:
    """Droppt eine Tabelle mit deaktivierten FK-Checks (MySQL/MariaDB)."""
    try:
        with db.engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            conn.execute(text(f"DROP TABLE IF EXISTS {_quote_ident(table_name)}"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        return True
    except Exception as exc:
        logger.warning("Drop von '%s' fehlgeschlagen: %s", table_name, exc)
        return False


def _repair_unreadable_mysql_tables(db, *, table_names: Iterable[str] | None = None) -> list[str]:
    """
    Erkennt unlesbare MySQL-Tabellen (1932) und droppt sie, damit create_all sie neu anlegen kann.
    Prüft nur die angegebenen Namen (kritische), sonst alle sichtbaren Tabellen.
    """
    if db.engine.dialect.name not in ("mysql", "mariadb"):
        return []

    inspector = inspect(db.engine)
    existing = set(inspector.get_table_names())
    if table_names is None:
        candidates = sorted(existing)
    else:
        candidates = [n for n in table_names if n in existing]

    repaired: list[str] = []
    for name in candidates:
        try:
            with db.engine.connect() as conn:
                conn.execute(text(f"SELECT 1 FROM {_quote_ident(name)} LIMIT 1"))
        except Exception as exc:
            if not _is_mysql_orphan_error(exc):
                logger.warning("Tabelle '%s' unlesbar (kein Orphan): %s", name, exc)
                continue
            if _drop_mysql_table(db, name):
                repaired.append(name)
                logger.warning("Orphan-Tabelle '%s' gedroppt (MySQL 1932/1813) – wird neu angelegt", name)
    return repaired


def _create_missing_tables(db, table_names: Iterable[str]) -> list[str]:
    """Erstellt fehlende Tabellen einzeln; gibt weiterhin fehlende Namen zurück."""
    still_missing: list[str] = []
    for name in table_names:
        table = db.metadata.tables.get(name)
        if table is None:
            still_missing.append(name)
            logger.warning("Tabelle '%s' nicht in Metadata – Modell fehlt?", name)
            continue
        try:
            table.create(db.engine, checkfirst=True)
            logger.info("Tabelle '%s' sichergestellt", name)
        except Exception as exc:
            if _is_mysql_orphan_error(exc) and _drop_mysql_table(db, name):
                try:
                    table.create(db.engine, checkfirst=True)
                    logger.info("Tabelle '%s' nach Orphan-Repair neu angelegt", name)
                    continue
                except Exception as retry_exc:
                    logger.warning("Tabelle '%s' nach Repair weiterhin fehlgeschlagen: %s", name, retry_exc)
                    still_missing.append(name)
                    continue
            logger.warning("Tabelle '%s' konnte nicht erstellt werden: %s", name, exc)
            still_missing.append(name)
    return still_missing


def ensure_all_tables(db=None, *, critical_tables: Iterable[str] | None = None) -> tuple[bool, list[str]]:
    """
    Stellt sicher, dass das Schema (create_all + kritische Tabellen) steht.

    Returns:
        (ok, still_missing)
    """
    if db is None:
        from app import db as _db

        db = _db

    critical = tuple(critical_tables) if critical_tables is not None else CRITICAL_TABLES
    import_all_models()

    with _SchemaLock(db):
        # Vor create_all: unlesbare kritische Tabellen (MySQL 1932) droppen
        try:
            repaired = _repair_unreadable_mysql_tables(db, table_names=critical)
            if repaired:
                logger.warning("Orphan-Repair: %s Tabelle(n) neu anzulegen: %s", len(repaired), ", ".join(repaired))
        except Exception as repair_err:
            logger.warning("Orphan-Repair übersprungen: %s", repair_err)

        try:
            db.create_all()
            logger.info("db.create_all() ausgeführt")
        except Exception as create_error:
            logger.warning("db.create_all() fehlgeschlagen: %s", create_error)
            if _is_mysql_orphan_error(create_error):
                # create_all bricht oft an der ersten kaputten Tabelle ab – breiter Repair
                try:
                    repaired = _repair_unreadable_mysql_tables(db)
                    if repaired:
                        logger.warning("Breiter Orphan-Repair: %s Tabelle(n)", len(repaired))
                        try:
                            db.create_all()
                            logger.info("db.create_all() nach Orphan-Repair ausgeführt")
                            create_error = None
                        except Exception as retry_err:
                            create_error = retry_err
                            logger.warning("db.create_all() nach Repair weiterhin fehlgeschlagen: %s", retry_err)
                except Exception as broad_err:
                    logger.warning("Breiter Orphan-Repair fehlgeschlagen: %s", broad_err)
            if create_error is not None:
                logger.info("Versuche fehlende Tabellen einzeln zu erstellen...")

        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        missing = [name for name in critical if name not in existing]

        if missing:
            logger.info("%s kritische Tabelle(n) fehlen: %s", len(missing), ', '.join(missing))
            pending = list(missing)
            for attempt in range(1, 4):
                if not pending:
                    break
                logger.info("Tabellen-Erstellung Durchlauf %s/3 ...", attempt)
                pending = _create_missing_tables(db, pending)
                try:
                    db.create_all()
                except Exception:
                    pass
                existing = set(inspect(db.engine).get_table_names())
                pending = [name for name in pending if name not in existing]

            missing = pending

        if "schema_migrations" not in set(inspect(db.engine).get_table_names()):
            try:
                from app.utils.auto_migrate import _ensure_schema_migrations_table

                _ensure_schema_migrations_table(db)
            except Exception as mig_tbl_err:
                logger.warning("schema_migrations konnte nicht angelegt werden: %s", mig_tbl_err)

        existing = set(inspect(db.engine).get_table_names())
        still_missing = [name for name in critical if name not in existing]
        if still_missing:
            logger.error("Nach Schema-Init fehlen noch: %s", ', '.join(still_missing))
            return False, still_missing

        # Lesbarkeit kritischer Tabellen final prüfen
        unreadables = _repair_unreadable_mysql_tables(db, table_names=critical)
        if unreadables:
            pending = _create_missing_tables(db, unreadables)
            if pending:
                logger.error("Nach Orphan-Repair weiterhin unlesbar/fehlend: %s", ", ".join(pending))
                return False, pending
            try:
                db.create_all()
            except Exception:
                pass

        logger.info("Schema vollständig (%s Tabellen, kritische geprüft)", len(inspect(db.engine).get_table_names()))
        return True, []
