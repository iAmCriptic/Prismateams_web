"""Post-config startup: schema, jobs, WebDAV."""


import os

from app.blueprints.email import start_email_sync
from app.factory._util import env_flag as _env_flag
from app.utils.startup_bootstrap import log_startup as _log_startup

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

    # Background-Jobs nur im Hauptprozess starten
    if is_main_process and not os.getenv('PRISMATEAMS_SKIP_BACKGROUND_JOBS'):
        start_email_sync(app)
        
        from app.tasks.notification_scheduler import start_notification_scheduler
        start_notification_scheduler(app)

        from app.tasks.calendar_sync_scheduler import start_calendar_sync_scheduler
        start_calendar_sync_scheduler(app)

        from app.tasks.media_downloader_cleanup import start_media_downloader_cleanup
        start_media_downloader_cleanup(app)

        from app.tasks.file_converter_cleanup import start_file_converter_cleanup
        start_file_converter_cleanup(app)

        from app.tasks.files_trash_cleanup import start_files_trash_cleanup
        start_files_trash_cleanup(app)

        from app.tasks.access_log_cleanup import start_access_log_cleanup
        start_access_log_cleanup(app)

    try:
        from app.utils.webdav import mount_webdav
        mount_webdav(app)
    except Exception as webdav_err:
        _log_startup(f"[WARNUNG] WebDAV-Mount fehlgeschlagen: {webdav_err}")
