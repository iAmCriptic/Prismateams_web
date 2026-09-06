"""Sync trigger, delete/move, flags, and IMAP folder CRUD routes."""

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

from app.blueprints.email.imap_client import (
    COLOR_DOT_CHOICES,
    _encode_imap_folder,
    _imap_error_payload,
    _imap_success_payload,
    connect_imap,
    delete_email_from_imap,
    imap_create_folder,
    imap_delete_folder,
    imap_mark_seen,
    imap_move_message,
    imap_set_keyword,
    move_email_in_imap,
)
from app.blueprints.email.mailbox import (
    _find_email_folder,
    _folder_tree_context,
    _resolve_request_mailbox,
    check_email_permission,
)
from app.blueprints.email.sync import (
    sync_emails_from_folder,
    sync_emails_from_server,
    sync_imap_folders,
)

@email_bp.route('/sync', methods=['POST'])
@login_required
@check_module_access('module_email')
def sync_emails():
    """Sync emails from IMAP server (always runs in a background thread)."""
    if not check_email_permission('read'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept', '').startswith('application/json'):
            return jsonify({'success': False, 'error': 'Nicht autorisiert'}), 403
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    is_async_request = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.headers.get('Accept', '').startswith('application/json')
    )
    current_folder = request.form.get('folder') or None
    _, mailbox_id = _resolve_request_mailbox('read')
    folder_label = None
    if current_folder:
        folder_obj = _find_email_folder(current_folder, mailbox_id)
        folder_label = folder_obj.display_name if folder_obj else current_folder

    # Always background — never run IMAP in the request worker
    user_id = current_user.id
    job_id = f"{user_id}-{uuid4().hex}"
    app_instance = current_app._get_current_object()
    sync_mailbox_id = mailbox_id
    
    def emit_status(status: str, message: str, level: str = 'info', **extras):
        payload = {
            'jobId': job_id,
            'status': status,
            'message': message,
            'level': level,
            'folder': current_folder,
            'folderLabel': folder_label,
            'mailboxId': sync_mailbox_id,
        }
        if extras:
            payload.update(extras)
        # SSE-Update senden (funktioniert mit mehreren Gunicorn-Workern)
        emit_email_sync_status(user_id, 'sync_status', payload)
    
    def sync_in_background():
        with app_instance.app_context():
            start_msg = 'Synchronisation gestartet.'
            if sync_mailbox_id:
                start_msg = 'Postfach-Synchronisation gestartet (inkl. Ordner).'
            elif folder_label:
                start_msg = f"Synchronisation für '{folder_label}' gestartet."
            emit_status('started', start_msg, 'info', shouldRefresh=False)
            
            try:
                from app.models.email import Mailbox as MailboxModel
                mb_obj = MailboxModel.query.get(sync_mailbox_id) if sync_mailbox_id else None
                # Non-blocking Lock — sofort „läuft bereits“ statt 60s warten
                with acquire_email_sync_lock(timeout=0) as acquired:
                    if acquired:
                        if mb_obj is not None:
                            logger.info(
                                "E-Mail-Synchronisation wird gestartet (vollständiges Postfach, mailbox=%s)",
                                sync_mailbox_id,
                            )
                            success, message = sync_emails_from_server(mailbox=mb_obj)
                            logger.info(
                                "E-Mail-Synchronisation wurde beendet (mailbox=%s)",
                                sync_mailbox_id,
                            )
                        elif current_folder:
                            logger.info(
                                "E-Mail-Synchronisation wird gestartet (Ordner: %s)",
                                folder_label or current_folder,
                            )
                            sync_imap_folders(mailbox=None)
                            success, message = sync_emails_from_folder(
                                current_folder, mailbox=None
                            )
                            logger.info(
                                "E-Mail-Synchronisation wurde beendet (Ordner: %s)",
                                folder_label or current_folder,
                            )
                        else:
                            # Nur Hauptpostfach synchronisieren
                            success, message = sync_emails_from_server(mailbox=None)
                        
                        if success:
                            emit_status('success', message, 'success', shouldRefresh=True)
                        else:
                            emit_status('error', message, 'danger', shouldRefresh=False)
                    else:
                        logger.debug("E-Mail-Synchronisation: Bereits in einem anderen Worker aktiv")
                        emit_status('warning', 'Synchronisation läuft bereits in einem anderen Worker. Bitte warten Sie einen Moment.', 'warning', shouldRefresh=False)
            except Exception as exc:
                app_instance.logger.error(f"E-Mail-Synchronisation Fehler: {exc}", exc_info=True)
                emit_status('error', str(exc), 'danger', shouldRefresh=False)
    
    thread = threading.Thread(target=sync_in_background, name=f"email-sync-{job_id}")
    thread.daemon = True
    thread.start()

    if not is_async_request:
        flash(translate('email.flash.sync_started'), 'info')
        target_endpoint = 'email.folder_view' if current_folder else 'email.index'
        target_kwargs = {'folder_name': current_folder} if current_folder else {}
        if mailbox_id:
            target_kwargs['mailbox'] = mailbox_id
        return redirect(url_for(target_endpoint, **target_kwargs))
    
    response_message = 'Synchronisation gestartet.'
    if sync_mailbox_id:
        response_message = 'Postfach-Synchronisation gestartet (inkl. Ordner).'
    elif folder_label:
        response_message = f"Synchronisation für '{folder_label}' gestartet."
    
    return jsonify({
        'success': True,
        'jobId': job_id,
        'message': response_message,
        'folder': current_folder,
        'folderLabel': folder_label,
        'mailboxId': sync_mailbox_id,
    }), 202


def _wants_json_response():
    """Detect if client expects JSON rather than HTML redirect."""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    return False


@email_bp.route('/delete/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def delete_email(email_id):
    """Delete email from both portal and IMAP."""
    if not check_email_permission('read'):
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403
        return jsonify({'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    original_folder = email.folder

    imap_warning = None
    if email.imap_uid:
        success, message = delete_email_from_imap(email.imap_uid, email.folder)
        if not success:
            imap_warning = message

    db.session.delete(email)
    db.session.commit()

    unread_count = 0
    by_folder = {}
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    if _wants_json_response():
        payload = {
            'success': True,
            'message': translate('email.flash.deleted'),
            'folder': original_folder,
            'email_id': email_id,
            'unread_count': unread_count,
            'by_folder': by_folder,
        }
        if imap_warning:
            payload['imap_warning'] = imap_warning
        return jsonify(payload)

    if imap_warning:
        flash(f'WARNING: E-Mail konnte nicht in IMAP gelöscht werden: {imap_warning}', 'warning')
    flash(translate('email.flash.deleted'), 'success')
    return redirect(url_for('email.folder_view', folder_name=original_folder))


@email_bp.route('/move/<int:email_id>', methods=['POST'])
@login_required
@check_module_access('module_email')
def move_email(email_id):
    """Move email to another folder in both portal and IMAP (JSON or classic form)."""
    if not check_email_permission('read'):
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403
        return jsonify({'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    new_folder = (
        request.form.get('folder')
        or request.values.get('folder')
        or payload.get('folder')
    )

    if not new_folder:
        if _wants_json_response():
            return jsonify({'success': False, 'error': translate('email.flash.target_folder_not_specified')}), 400
        flash(translate('email.flash.target_folder_not_specified'), 'danger')
        return redirect(url_for('email.folder_view', folder_name=email.folder))

    if new_folder == email.folder:
        if _wants_json_response():
            return jsonify({'success': True, 'message': 'Bereits in Zielordner', 'folder': new_folder, 'email_id': email.id})
        return redirect(url_for('email.folder_view', folder_name=new_folder))

    target_folder_obj = EmailFolder.query.filter_by(name=new_folder).first()
    if not target_folder_obj:
        if _wants_json_response():
            return jsonify({'success': False, 'error': f"Zielordner '{new_folder}' nicht gefunden"}), 404
        flash(f"Zielordner '{new_folder}' nicht gefunden", 'danger')
        return redirect(url_for('email.folder_view', folder_name=email.folder))

    imap_warning = None
    if email.imap_uid:
        imap_result = imap_move_message(email.imap_uid, email.folder, new_folder)
        if not imap_result.get('success'):
            imap_warning = imap_result.get('message')
            if _wants_json_response():
                return jsonify({
                    'success': False,
                    'error': f"IMAP-Verschiebung fehlgeschlagen: {imap_warning}",
                    'retryable': imap_result.get('retryable', False),
                }), 502

    old_folder = email.folder
    email.folder = new_folder
    email.last_imap_sync = datetime.utcnow()
    db.session.commit()

    by_folder = {}
    unread_count = 0
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    if _wants_json_response():
        return jsonify({
            'success': True,
            'message': f'E-Mail nach {new_folder} verschoben',
            'folder': new_folder,
            'previous_folder': old_folder,
            'email_id': email.id,
            'imap_warning': imap_warning,
            'unread_count': unread_count,
            'by_folder': by_folder,
        })

    if imap_warning:
        flash(f'WARNING: E-Mail konnte nicht in IMAP verschoben werden: {imap_warning}', 'warning')
    flash(f'E-Mail wurde erfolgreich von {old_folder} nach {new_folder} verschoben.', 'success')
    return redirect(url_for('email.folder_view', folder_name=new_folder))


@email_bp.route('/messages/<int:email_id>/read-state', methods=['POST'])
@login_required
@check_module_access('module_email')
def set_email_read_state(email_id):
    """Mark email as read or unread (IMAP-synchronised)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    state = (payload.get('state') or request.form.get('state') or '').strip().lower()
    if state not in ('read', 'unread'):
        return jsonify({'success': False, 'error': "Ungültiger Status (erwartet 'read' oder 'unread')"}), 400

    seen = state == 'read'
    imap_warning = None
    if email.imap_uid:
        imap_result = imap_mark_seen(email.imap_uid, email.folder, seen=seen)
        if not imap_result.get('success'):
            imap_warning = imap_result.get('message')

    email.is_read = seen
    db.session.commit()

    unread_count = 0
    by_folder = {}
    try:
        from app.utils.email_counts import count_unread_emails_by_folder, emit_email_unread_update
        unread_count = emit_email_unread_update(current_user.id) or 0
        by_folder = count_unread_emails_by_folder()
    except Exception:
        pass

    return jsonify({
        'success': True,
        'state': state,
        'email_id': email.id,
        'is_read': email.is_read,
        'imap_warning': imap_warning,
        'unread_count': unread_count,
        'by_folder': by_folder,
    })


@email_bp.route('/messages/<int:email_id>/color-dot', methods=['POST'])
@login_required
@check_module_access('module_email')
def set_email_color_dot(email_id):
    """Set/clear the colored label (dot) for an email."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    email = EmailMessage.query.get_or_404(email_id)
    payload = request.get_json(silent=True) or {}
    color = (payload.get('color') or request.form.get('color') or '').strip().lower()

    if color not in COLOR_DOT_CHOICES:
        return jsonify({'success': False, 'error': f"Unbekannte Farbe: {color}"}), 400

    # Remove previous keyword on server if a different one was set
    previous_keyword = email.imap_color_keyword
    new_keyword = COLOR_DOT_CHOICES.get(color)

    imap_status = None
    imap_message = None
    keyword_supported = None
    if email.imap_uid:
        if previous_keyword and previous_keyword != new_keyword:
            remove_result = imap_set_keyword(email.imap_uid, email.folder, previous_keyword, enabled=False)
            imap_status = remove_result.get('imap_status')
            imap_message = remove_result.get('message')
            keyword_supported = remove_result.get('keyword_supported', keyword_supported)
        if new_keyword:
            add_result = imap_set_keyword(email.imap_uid, email.folder, new_keyword, enabled=True)
            imap_status = add_result.get('imap_status')
            imap_message = add_result.get('message')
            keyword_supported = add_result.get('keyword_supported', keyword_supported)

    email.color_dot = color if color and color != 'none' else None
    email.imap_color_keyword = new_keyword if keyword_supported else None
    email.last_flag_sync_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'email_id': email.id,
        'color': email.color_dot,
        'imap_status': imap_status,
        'imap_message': imap_message,
        'keyword_supported': keyword_supported,
    })


@email_bp.route('/folders', methods=['POST'])
@login_required
@check_module_access('module_email')
def create_folder():
    """Create a new IMAP folder (optionally as subfolder of parent)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or request.form.get('name') or '').strip()
    parent = (payload.get('parent') or request.form.get('parent') or '').strip()
    separator = (payload.get('separator') or request.form.get('separator') or '/').strip() or '/'

    if not name:
        return jsonify({'success': False, 'error': 'Ordnername fehlt'}), 400

    invalid_chars = set('\\"')
    if any(ch in name for ch in invalid_chars):
        return jsonify({'success': False, 'error': 'Ungültige Zeichen im Ordnernamen'}), 400

    if parent:
        parent_obj = EmailFolder.query.filter_by(name=parent).first()
        if not parent_obj:
            return jsonify({'success': False, 'error': f"Übergeordneter Ordner '{parent}' nicht gefunden"}), 404
        separator = parent_obj.separator or separator
        full_path = f"{parent}{separator}{name}"
    else:
        full_path = name

    existing = EmailFolder.query.filter_by(name=full_path).first()
    if existing:
        return jsonify({'success': False, 'error': f"Ordner '{full_path}' existiert bereits"}), 409

    result = imap_create_folder(full_path)
    if not result.get('success'):
        return jsonify({
            'success': False,
            'error': result.get('message'),
            'retryable': result.get('retryable', False),
        }), 502

    now = datetime.utcnow()
    new_folder = EmailFolder(
        name=full_path,
        display_name=name,
        folder_type='custom',
        is_system=False,
        parent_folder=parent or None,
        separator=separator,
        created_at=now,
        last_synced=now,
    )
    db.session.add(new_folder)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': result.get('message'),
        'folder': {
            'name': new_folder.name,
            'display_name': new_folder.display_name,
            'parent_folder': new_folder.parent_folder,
            'separator': new_folder.separator,
            'folder_type': new_folder.folder_type,
            'is_system': new_folder.is_system,
        },
    })


@email_bp.route('/folders/delete', methods=['POST', 'DELETE'])
@login_required
@check_module_access('module_email')
def delete_folder():
    """Delete a custom IMAP folder (folder name in JSON body or query param)."""
    if not check_email_permission('read'):
        return jsonify({'success': False, 'error': translate('email.errors.unauthorized')}), 403

    payload = request.get_json(silent=True) or {}
    folder_name = (
        payload.get('name')
        or request.values.get('name')
        or request.args.get('name')
        or ''
    ).strip()
    if not folder_name:
        return jsonify({'success': False, 'error': 'Ordnername fehlt'}), 400

    folder_obj = EmailFolder.query.filter_by(name=folder_name).first()
    if not folder_obj:
        return jsonify({'success': False, 'error': f"Ordner '{folder_name}' nicht gefunden"}), 404
    if folder_obj.is_system or folder_obj.folder_type == 'standard':
        return jsonify({'success': False, 'error': 'Systemordner können nicht gelöscht werden'}), 400

    force = bool(request.args.get('force') or payload.get('force'))

    contained_children = EmailFolder.query.filter_by(parent_folder=folder_name).count()
    contained_emails = EmailMessage.query.filter_by(folder=folder_name).count()
    if (contained_children or contained_emails) and not force:
        return jsonify({
            'success': False,
            'requires_confirmation': True,
            'error': f"Ordner enthält {contained_emails} E-Mails und {contained_children} Unterordner. Bestätigen Sie mit force=true.",
            'emails_count': contained_emails,
            'children_count': contained_children,
        }), 409

    result = imap_delete_folder(folder_name)
    if not result.get('success'):
        return jsonify({
            'success': False,
            'error': result.get('message'),
            'retryable': result.get('retryable', False),
        }), 502

    # Remove child folders and emails bound to this folder locally
    if contained_children:
        EmailFolder.query.filter_by(parent_folder=folder_name).delete(synchronize_session=False)
    if contained_emails:
        EmailMessage.query.filter_by(folder=folder_name).delete(synchronize_session=False)
    db.session.delete(folder_obj)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': result.get('message'),
        'folder': folder_name,
    })
