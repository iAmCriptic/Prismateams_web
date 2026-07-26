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
from typing import Iterable

from sqlalchemy import inspect, text

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
    "credentials",
    "manuals",
    "manual_folders",
    "system_settings",
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
    from app.models.email import EmailFolder  # noqa: F401
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
    from app.models.wiki import WikiFavorite  # noqa: F401


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
                print("[WARNUNG] Schema-Lock Timeout – fahre ohne exklusiven Lock fort")
                self._conn.close()
                self._conn = None
            except Exception as exc:
                print(f"[WARNUNG] MySQL Schema-Lock fehlgeschlagen: {exc}")
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
            print(f"[WARNUNG] Datei-Schema-Lock fehlgeschlagen: {exc}")
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


def _create_missing_tables(db, table_names: Iterable[str]) -> list[str]:
    """Erstellt fehlende Tabellen einzeln; gibt weiterhin fehlende Namen zurück."""
    still_missing: list[str] = []
    for name in table_names:
        table = db.metadata.tables.get(name)
        if table is None:
            still_missing.append(name)
            print(f"[WARNUNG] Tabelle '{name}' nicht in Metadata – Modell fehlt?")
            continue
        try:
            table.create(db.engine, checkfirst=True)
            print(f"[OK] Tabelle '{name}' sichergestellt")
        except Exception as exc:
            print(f"[WARNUNG] Tabelle '{name}' konnte nicht erstellt werden: {exc}")
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
        try:
            db.create_all()
            print("[OK] db.create_all() ausgeführt")
        except Exception as create_error:
            print(f"[WARNUNG] db.create_all() fehlgeschlagen: {create_error}")
            print("[INFO] Versuche fehlende Tabellen einzeln zu erstellen...")

        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        missing = [name for name in critical if name not in existing]

        if missing:
            print(f"[INFO] {len(missing)} kritische Tabelle(n) fehlen: {', '.join(missing)}")
            pending = list(missing)
            for attempt in range(1, 4):
                if not pending:
                    break
                print(f"[INFO] Tabellen-Erstellung Durchlauf {attempt}/3 ...")
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
                print(f"[WARNUNG] schema_migrations konnte nicht angelegt werden: {mig_tbl_err}")

        existing = set(inspect(db.engine).get_table_names())
        still_missing = [name for name in critical if name not in existing]
        if still_missing:
            print(f"[FEHLER] Nach Schema-Init fehlen noch: {', '.join(still_missing)}")
            return False, still_missing

        print(f"[OK] Schema vollständig ({len(existing)} Tabellen, kritische geprüft)")
        return True, []
