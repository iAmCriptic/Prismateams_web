"""Inbox, folder, message view, print, and attachment download."""

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

from app.blueprints.email.html_render import (
    backfill_inline_attachments_from_imap,
    build_rich_email_iframe_document,
    is_simple_html_email,
    process_email_body_html_for_inline_view,
)
from app.blueprints.email.imap_client import COLOR_DOT_CHOICES
from app.blueprints.email.mailbox import (
    _emails_for_folder,
    _escape_like,
    _find_email_folder,
    _folder_tree_context,
    _message_mailbox_filter,
    _multi_mailbox_sidebar_trees,
    _resolve_request_mailbox,
    _restore_false_deleted_flags,
    check_email_permission,
)

@email_bp.route('/')
@login_required
@check_module_access('module_email')
def index():
    """Email inbox with folder support."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    current_folder = request.args.get('folder', 'INBOX')
    search_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int) or 1
    active_mailbox, mailbox_id = _resolve_request_mailbox('read')
    pagination = _emails_for_folder(
        current_folder, search_query, mailbox_id=mailbox_id, page=page
    )
    emails = pagination.items
    _restore_false_deleted_flags(emails, current_folder)

    folder_obj = _find_email_folder(current_folder, mailbox_id)
    folder_display_name = folder_obj.display_name if folder_obj else current_folder

    folders, folder_tree = _folder_tree_context(mailbox_id=mailbox_id)

    try:
        from app.utils.notifications import mark_in_app_notifications_read
        mark_in_app_notifications_read(
            current_user.id,
            notification_type='email',
        )
    except Exception:
        pass

    db.session.commit()

    from app.utils.email_counts import count_unread_emails_by_folder
    from app.utils.multi_mailboxes import is_email_multi_enabled, get_accessible_mailboxes

    multi_on = is_email_multi_enabled()
    accessible = get_accessible_mailboxes(current_user) if multi_on else []
    mailbox_folder_trees = {}
    mailbox_unread_counts = {}
    if multi_on:
        mailbox_folder_trees, mailbox_unread_counts = _multi_mailbox_sidebar_trees(
            current_user, accessible
        )

    return render_template(
        'email/index.html',
        emails=emails,
        pagination=pagination,
        email_has_more=pagination.has_next,
        folders=folders,
        folder_tree=folder_tree,
        folder_unread_counts=count_unread_emails_by_folder(
            user=current_user, mailbox_id=mailbox_id
        ),
        current_folder=current_folder,
        folder_display_name=folder_display_name,
        search_query=search_query,
        color_dot_choices=[c for c in COLOR_DOT_CHOICES.keys() if c not in ('', 'none')],
        email_multi_enabled=multi_on,
        accessible_mailboxes=accessible,
        active_mailbox=active_mailbox,
        active_mailbox_id=mailbox_id,
        mailbox_folder_trees=mailbox_folder_trees,
        mailbox_unread_counts=mailbox_unread_counts,
    )


@email_bp.route('/folder/<imap_folder:folder_name>')
@login_required
@check_module_access('module_email')
def folder_view(folder_name):
    """View emails in a specific folder."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))

    # Converter dekodiert bereits; unquote bleibt harmlos für Alt-Links
    folder_name = unquote(folder_name or '')
    
    # Reject invalid folder names
    if not folder_name or folder_name.strip() == '' or folder_name == '/':
        flash(translate('email.flash.invalid_folder_name'), 'danger')
        return redirect(url_for('email.index'))

    active_mailbox, mailbox_id = _resolve_request_mailbox('read')
    
    # Check if folder exists, if not redirect to index
    folder_obj = _find_email_folder(folder_name, mailbox_id)
    if not folder_obj:
        existing_emails = (
            EmailMessage.query.filter_by(folder=folder_name)
            .filter(_message_mailbox_filter(mailbox_id))
            .count()
        )
        if existing_emails > 0:
            logging.warning(f"Folder '{folder_name}' exists in emails but not in folders table")
        flash(f'Ordner "{folder_name}" nicht gefunden.', 'warning')
        return redirect(url_for('email.index', mailbox=mailbox_id or 'main'))
    
    search_query = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int) or 1
    pagination = _emails_for_folder(
        folder_name, search_query, mailbox_id=mailbox_id, page=page
    )
    emails = pagination.items
    _restore_false_deleted_flags(emails, folder_name)
    
    logging.info(f"Viewing folder '{folder_name}' with {len(emails)} emails (page {pagination.page}/{pagination.pages or 1})")

    folders, folder_tree = _folder_tree_context(mailbox_id=mailbox_id)
    folder_display_name = folder_obj.display_name if folder_obj else folder_name

    from app.utils.email_counts import count_unread_emails_by_folder
    from app.utils.multi_mailboxes import is_email_multi_enabled, get_accessible_mailboxes

    multi_on = is_email_multi_enabled()
    accessible = get_accessible_mailboxes(current_user) if multi_on else []
    mailbox_folder_trees = {}
    mailbox_unread_counts = {}
    if multi_on:
        mailbox_folder_trees, mailbox_unread_counts = _multi_mailbox_sidebar_trees(
            current_user, accessible
        )

    return render_template(
        'email/index.html',
        emails=emails,
        pagination=pagination,
        email_has_more=pagination.has_next,
        folders=folders,
        folder_tree=folder_tree,
        folder_unread_counts=count_unread_emails_by_folder(
            user=current_user, mailbox_id=mailbox_id
        ),
        current_folder=folder_name,
        folder_display_name=folder_display_name,
        search_query=search_query,
        color_dot_choices=[c for c in COLOR_DOT_CHOICES.keys() if c not in ('', 'none')],
        email_multi_enabled=multi_on,
        accessible_mailboxes=accessible,
        active_mailbox=active_mailbox,
        active_mailbox_id=mailbox_id,
        mailbox_folder_trees=mailbox_folder_trees,
        mailbox_unread_counts=mailbox_unread_counts,
    )


@email_bp.route('/view/<int:email_id>')
@login_required
@check_module_access('module_email')
def view_email(email_id):
    """View a specific email."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))
    
    email_msg = EmailMessage.query.get_or_404(email_id)

    # Multi-Postfach: kein Zugriff auf fremde Postfächer
    if email_msg.mailbox_id is not None:
        from app.utils.multi_mailboxes import user_has_mailbox_access, is_email_multi_enabled
        if is_email_multi_enabled():
            mb = email_msg.mailbox
            if not mb or not user_has_mailbox_access(current_user, mb, 'read'):
                flash(translate('email.flash.no_read_permission'), 'danger')
                return redirect(url_for('email.index'))
    
    # Wenn es sich um einen Entwurf handelt, weiterleiten zur Bearbeitungsseite
    if email_msg.folder == 'Drafts':
        # Prüfe, ob der Benutzer Zugriff auf diesen Entwurf hat
        if email_msg.sent_by_user_id == current_user.id:
            return redirect(url_for('email.compose', draft_id=email_id))
        else:
            flash('Sie haben keinen Zugriff auf diesen Entwurf.', 'danger')
            return redirect(url_for('email.index'))
    
    if not email_msg.is_read:
        email_msg.is_read = True
        try:
            from app.utils.notifications import mark_in_app_notifications_read
            mark_in_app_notifications_read(
                current_user.id,
                notification_type='email',
            )
        except Exception:
            pass
        db.session.commit()
        try:
            from app.utils.email_counts import emit_email_unread_update
            emit_email_unread_update(current_user.id)
        except Exception:
            pass
    else:
        try:
            from app.utils.notifications import mark_in_app_notifications_read
            mark_in_app_notifications_read(
                current_user.id,
                notification_type='email',
                commit=True,
            )
        except Exception:
            pass
    
    
    raw_html = None
    if email_msg.body_html:
        try:
            if isinstance(email_msg.body_html, bytes):
                raw_html = email_msg.body_html.decode('utf-8', errors='replace')
            else:
                raw_html = str(email_msg.body_html)
        except Exception as e:
            logging.error(f"HTML decode error: {e}")
            raw_html = None

    # Inline-Bilder (cid:) nachladen, falls sie bei einem früheren Sync nicht erfasst wurden
    if raw_html and re.search(r'src\s*=\s*["\']?cid:', raw_html, flags=re.IGNORECASE):
        try:
            backfill_inline_attachments_from_imap(email_msg)
        except Exception as backfill_err:
            logging.debug(f"Inline backfill skipped: {backfill_err}")

    is_simple_html = is_simple_html_email(raw_html) if raw_html else True

    html_iframe_html = None
    html_content = None

    if raw_html:
        if not is_simple_html:
            # Rich HTML: full document in sandboxed iframe so sender CSS/layout stay intact
            viewer_dark = bool(
                current_user.is_authenticated and getattr(current_user, 'dark_mode', False)
            )
            viewer_oled = bool(
                current_user.is_authenticated and getattr(current_user, 'oled_mode', False)
            )
            html_iframe_html = build_rich_email_iframe_document(
                raw_html, email_msg, viewer_dark=viewer_dark, viewer_oled=viewer_oled
            )
            if not html_iframe_html:
                try:
                    html_content = process_email_body_html_for_inline_view(raw_html, email_msg)
                except Exception as e:
                    logging.error(f"HTML inline fallback error: {e}")
                    html_content = None
        else:
            try:
                html_content = process_email_body_html_for_inline_view(raw_html, email_msg)
            except Exception as e:
                logging.error(f"HTML processing error: {e}")
                html_content = None

    return render_template(
        'email/view.html',
        email=email_msg,
        html_content=html_content,
        html_iframe_html=html_iframe_html,
        is_simple_html=is_simple_html
    )


@email_bp.route('/print/<int:email_id>')
@login_required
@check_module_access('module_email')
def print_email_pdf(email_id):
    """Druck-PDF einer einzelnen E-Mail (Portal-Layout)."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('dashboard.index'))

    email_msg = EmailMessage.query.get_or_404(email_id)
    if email_msg.folder == 'Drafts':
        flash(translate('email.flash.draft_no_print'), 'warning')
        return redirect(url_for('email.compose', draft_id=email_id))

    from app.utils.email_pdf_generator import generate_email_print_pdf, safe_email_pdf_filename

    inline_preview = request.args.get('inline') == '1'
    pdf_buffer = generate_email_print_pdf(email_msg)
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=not inline_preview,
        download_name=safe_email_pdf_filename(email_msg),
    )
@email_bp.route('/attachment/<int:attachment_id>')
@login_required
@check_module_access('module_email')
def download_attachment(attachment_id):
    """Download an email attachment with support for large files."""
    if not check_email_permission('read'):
        flash(translate('email.flash.no_read_permission'), 'danger')
        return redirect(url_for('email.index'))
    
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    email_msg = attachment.email
    if not email_msg:
        flash(translate('email.flash.attachment_not_found'), 'danger')
        return redirect(url_for('email.index'))
    
    try:
        if attachment.size > 1 * 1024 * 1024:
            logging.info(f"Downloading large attachment: '{attachment.filename}' ({attachment.size / (1024*1024):.2f} MB)")
        
        if attachment.is_large_file and attachment.file_path:
            import os
            if os.path.exists(attachment.file_path):
                def generate():
                    with open(attachment.file_path, 'rb') as f:
                        while True:
                            data = f.read(8192)
                            if not data:
                                break
                            yield data
                
                response = Response(generate(), mimetype=attachment.content_type)
                import urllib.parse
                encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
                response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                response.headers['Content-Length'] = str(attachment.size)
                response.headers['Accept-Ranges'] = 'bytes'
                return response
            else:
                flash(translate('email.flash.attachment_file_not_found'), 'danger')
                return redirect(url_for('email.view_email', email_id=email_msg.id))
        else:
            content = attachment.get_content()
            if not content:
                flash(translate('email.flash.attachment_corrupted'), 'danger')
                return redirect(url_for('email.index'))
            
            file_obj = io.BytesIO(content)
            
            response = send_file(
                file_obj,
                as_attachment=True,
                download_name=attachment.filename,
                mimetype=attachment.content_type
            )
            
            import urllib.parse
            encoded_filename = urllib.parse.quote(attachment.filename.encode('utf-8'))
            response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
            
            response.headers['Content-Length'] = str(attachment.size)
            response.headers['Accept-Ranges'] = 'bytes'
            
            return response
        
    except Exception as e:
        logging.error(f"Error downloading attachment {attachment_id} ({attachment.filename}): {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        flash(f'Fehler beim Herunterladen des Anhangs: {str(e)}', 'danger')
        return redirect(url_for('email.view_email', email_id=email_msg.id))
