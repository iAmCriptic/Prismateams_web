"""Leader-elected background IMAP sync thread."""

from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from uuid import uuid4
from app import db, mail
from app.blueprints.sse import emit_email_sync_status
from app.models.email import EmailAttachment, EmailFolder, EmailMessage, EmailPermission
from app.models.settings import SystemSettings
from app.utils.notifications import send_email_notification
from app.utils.access_control import check_module_access
from app.utils.i18n import translate
from flask_mail import Message
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import unquote
import imaplib
import email as email_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import threading
import time
import logging
import io
import hashlib
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func, cast, Integer, or_
from sqlalchemy.orm import defer
import re

from app.utils.email_sender import get_logo_base64, get_logo_data, send_email_with_lock
from app.utils.lock_manager import (
    acquire_email_sync_lock,
    heartbeat_email_sync_lock,
    try_acquire_email_sync_leader,
)
from app.utils.common import format_datetime
from app.blueprints.email._bp import EMAIL_LIST_PER_PAGE, email_bp, logger

from app.blueprints.email.sync import sync_all_configured_mailboxes

sync_thread = None
_sync_started = False
_sync_lock = threading.Lock()
_email_sync_leader = None
_leader_heartbeat_stop = threading.Event()

def email_sync_scheduler(app):
    """Background thread for automatic email synchronization every 15 minutes."""
    logger.info("E-Mail-Sync-Scheduler Thread gestartet, warte 30 Sekunden vor erster Synchronisation...")
    # Warte 30 Sekunden nach App-Start, bevor die erste Synchronisation startet
    time.sleep(30)
    
    while True:
        lock_acquired = False
        try:
            with app.app_context():
                from app.utils.common import is_module_enabled

                # PERF-01: Admin hat Modul abgeschaltet → keine IMAP-Arbeit
                if not is_module_enabled('module_email'):
                    logger.debug("module_email deaktiviert — Auto-Sync idle")
                else:
                    # Non-blocking: Leader-Thread wartet nicht hinter manuellem Sync
                    with acquire_email_sync_lock(timeout=0) as acquired:
                        lock_acquired = acquired
                        if acquired:
                            try:
                                success, message = sync_all_configured_mailboxes()
                                if success:
                                    logger.debug("Auto-sync: %s", message)
                                else:
                                    logger.error("Auto-sync failed: %s", message)
                            except Exception as sync_error:
                                logger.error(f"Fehler während der Synchronisation: {sync_error}", exc_info=True)
                        else:
                            logger.debug("E-Mail-Synchronisation wird bereits von anderem Worker durchgeführt, überspringe...")
        except Exception as e:
            logger.error(f"E-Mail-Sync-Scheduler Fehler: {e}", exc_info=True)
        finally:
            if lock_acquired:
                logger.debug("E-Mail-Synchronisation abgeschlossen, warte 15 Minuten bis zur nächsten...")
        
        # Nach jeder Synchronisation 15 Minuten warten
        time.sleep(900)


sync_thread = None
_sync_started = False
_sync_lock = threading.Lock()
_email_sync_leader = None
_leader_heartbeat_stop = threading.Event()


def _leader_heartbeat_loop():
    """Hält email_sync_leader-Lock frisch (Stale-Detection)."""
    while not _leader_heartbeat_stop.wait(30):
        held = _email_sync_leader
        if held is None:
            break
        try:
            held.heartbeat()
        except Exception as e:
            logging.debug("Leader-Heartbeat fehlgeschlagen: %s", e)


def start_email_sync(app):
    """Start the background email synchronization thread (nur ein Worker = Leader)."""
    global sync_thread, _sync_started, _email_sync_leader

    with app.app_context():
        from app.utils.common import is_module_enabled
        if not is_module_enabled('module_email'):
            logger.info("module_email deaktiviert — E-Mail-Sync-Scheduler startet nicht")
            return

    # Prüfe zuerst, ob bereits ein Thread mit diesem Namen läuft (auch nach Reload)
    existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
    if existing_threads:
        logger.debug(
            "E-Mail-Sync-Thread läuft bereits (gefunden %s Thread(s)), überspringe Neustart",
            len(existing_threads),
        )
        return
    
    from pathlib import Path
    lock_dir = str(Path(app.instance_path) / 'locks')
    
    # Verwende Lock, um Thread-Erstellung zu synchronisieren
    with _sync_lock:
        # Doppelte Prüfung innerhalb des Locks
        existing_threads = [t for t in threading.enumerate() if t.name == "email-sync-scheduler" and t.is_alive()]
        if existing_threads:
            logger.debug(
                "E-Mail-Sync-Thread läuft bereits (zweite Prüfung, %s Thread(s)), überspringe Neustart",
                len(existing_threads),
            )
            return
        
        if _sync_started:
            logger.debug("E-Mail-Sync-Thread wird bereits gestartet, überspringe Neustart")
            return

        leader = try_acquire_email_sync_leader(lock_dir=lock_dir)
        if leader is None:
            logger.info("E-Mail-Sync-Leader bereits aktiv — dieser Worker startet keinen Scheduler")
            return

        _email_sync_leader = leader
        _leader_heartbeat_stop.clear()
        hb_thread = threading.Thread(
            target=_leader_heartbeat_loop,
            daemon=True,
            name="email-sync-leader-hb",
        )
        hb_thread.start()
        
        _sync_started = True
        sync_thread = threading.Thread(target=email_sync_scheduler, args=(app,), daemon=True, name="email-sync-scheduler")
        sync_thread.start()
        logger.info("E-Mail Auto-Sync gestartet (Leader, alle 15 Minuten)")
