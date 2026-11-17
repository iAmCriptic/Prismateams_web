"""Post-config startup: schema, jobs, WebDAV."""

import logging
import os
import threading
from pathlib import Path

from app.blueprints.email import start_email_sync
from app.factory._util import env_flag as _env_flag
from app.utils.startup_bootstrap import log_startup as _log_startup

logger = logging.getLogger(__name__)

_background_jobs_leader = None
_leader_heartbeat_stop = threading.Event()


def _background_jobs_leader_heartbeat():
    """Hält background_jobs_leader-Lock frisch (Stale-Detection ~120s)."""
    while not _leader_heartbeat_stop.wait(30):
        held = _background_jobs_leader
        if held is None:
            break
        try:
            held.heartbeat()
        except Exception as exc:
            logger.debug("Background-Jobs-Leader-Heartbeat fehlgeschlagen: %s", exc)


def _start_background_jobs(app):
    """IntervalScheduler + E-Mail-Sync — nur auf dem Leader-Worker (QA G05)."""
    global _background_jobs_leader

    from app.utils.common import is_module_enabled
    from app.utils.lock_manager import try_acquire_background_jobs_leader

    lock_dir = str(Path(app.instance_path) / 'locks')
    leader = try_acquire_background_jobs_leader(lock_dir=lock_dir)
    if leader is None:
        _log_startup(
            "[INFO] Background-Jobs: anderer Gunicorn-Worker ist Leader — Scheduler übersprungen"
        )
        return False

    _background_jobs_leader = leader
    _leader_heartbeat_stop.clear()
    threading.Thread(
        target=_background_jobs_leader_heartbeat,
        daemon=True,
        name="background-jobs-leader-hb",
    ).start()
    _log_startup("[OK] Background-Jobs-Leader übernommen (dieser Worker)")

    # PERF-01: E-Mail-Sync nur wenn Modul adminseitig aktiv
    if is_module_enabled('module_email'):
        start_email_sync(app)

    from app.tasks.notification_scheduler import start_notification_scheduler
    start_notification_scheduler(app)

    # PERF-02: Kalender-Sync nur wenn Modul adminseitig aktiv
    if is_module_enabled('module_calendar'):
        from app.tasks.calendar_sync_scheduler import start_calendar_sync_scheduler
        start_calendar_sync_scheduler(app)

    # PERF-03: Modulgebundene Cleanups nur bei aktivem Modul
    if is_module_enabled('module_media_downloader'):
        from app.tasks.media_downloader_cleanup import start_media_downloader_cleanup
        start_media_downloader_cleanup(app)

    if is_module_enabled('module_file_converter'):
        from app.tasks.file_converter_cleanup import start_file_converter_cleanup
        start_file_converter_cleanup(app)

    if is_module_enabled('module_files'):
        from app.tasks.files_trash_cleanup import start_files_trash_cleanup
        start_files_trash_cleanup(app)

    if is_module_enabled('module_booking'):
        from app.tasks.booking_archiver import start_booking_archiver
        start_booking_archiver(app)

    from app.tasks.access_log_cleanup import start_access_log_cleanup
    start_access_log_cleanup(app)
    return True


def run_app_startup(app):
    """Schema/seed, background jobs, WebDAV."""
    # Schema-Init: immer (außer Reloader-Parent / explizitem Skip).
    # Background-Jobs: nicht im Reloader-Parent und nicht während Migrationen.
    werkzeug_run_main = os.environ.get('WERKZEUG_RUN_MAIN')
    is_debug = app.config.get('DEBUG', False)
    from app.utils.schema_init import should_run_startup_schema
    run_schema_init = should_run_startup_schema(debug=is_debug)
    run_startup_migrations = _env_flag('PRISMATEAMS_STARTUP_MIGRATIONS', False)
    # Legacy-Name: Background-Jobs nur im „Hauptprozess“ (kein Reloader-Parent)
    is_main_process = (werkzeug_run_main == 'true') or (not is_debug)

    from app.utils.startup_bootstrap import run_startup_database
    run_startup_database(
        app,
        run_schema_init=run_schema_init,
        run_startup_migrations=run_startup_migrations,
    )

    # Background-Jobs: ein Leader unter allen Gunicorn-Workern (QA G05)
    if is_main_process and not os.getenv('PRISMATEAMS_SKIP_BACKGROUND_JOBS'):
        try:
            _start_background_jobs(app)
        except Exception as jobs_err:
            _log_startup(f"[WARNUNG] Background-Jobs-Start fehlgeschlagen: {jobs_err}")

    try:
        from app.utils.webdav import mount_webdav
        mount_webdav(app)
    except Exception as webdav_err:
        _log_startup(f"[WARNUNG] WebDAV-Mount fehlgeschlagen: {webdav_err}")
