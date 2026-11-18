"""Backup exporters for sub-models of existing categories."""

from __future__ import annotations

import os
from typing import Dict

from app.models import (
    ApiToken,
    AppPassword,
    BookingRequestFile,
    BookingRequestMessage,
    BookingRoom,
    ChatNotificationSettings,
    Checkout,
    CheckoutItem,
    CloudImportConnection,
    ContactFavorite,
    CredentialFavorite,
    CredentialFolder,
    DguvExamination,
    EmailFolder,
    EventBookingPersonalLink,
    EventCustomField,
    EventCustomFieldValue,
    EventDay,
    EventLink,
    EventTodoItem,
    EventTodoList,
    Mailbox,
    MailboxAutoReply,
    MailboxMembership,
    MailboxUserPref,
    ManualFolder,
    ProductLot,
    ProductStatusHistory,
    StockMovement,
    WikiFavorite,
)
from app.models.inventory import LengthColorMapping
from app.utils.backup.file_io import read_file_base64, upload_root
from app.utils.backup_lookups import lookup_entity_name, lookup_team_name, lookup_user_email


def export_settings_submodels() -> Dict:
    return {
        "cloud_import_connections": [{
            "user_email": lookup_user_email(c.user_id),
            "provider": c.provider,
            "display_name": c.display_name,
            "credentials_enc": c.credentials_enc,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        } for c in CloudImportConnection.query.all()],
    }


def export_user_submodels() -> Dict:
    return {
        "chat_notification_settings": [{
            "user_email": lookup_user_email(s.user_id),
            "chat_name": lookup_entity_name("chat", s.chat_id),
            "notifications_enabled": s.notifications_enabled,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        } for s in ChatNotificationSettings.query.all()],
        "api_tokens": [{
            "user_email": lookup_user_email(t.user_id),
            "token": t.token,
            "token_prefix": t.token_prefix,
            "name": t.name,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        } for t in ApiToken.query.all()],
        "app_passwords": [{
            "user_email": lookup_user_email(p.user_id),
            "username": p.username,
            "name": p.name,
            "password_hash": p.password_hash,
            "hint": p.hint,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
        } for p in AppPassword.query.all()],
    }


def export_email_submodels() -> Dict:
    mailboxes_dir = os.path.join(upload_root(), "mailboxes")
    mailboxes_out = []
    mailbox_names = {}
    for m in Mailbox.query.order_by(Mailbox.id).all():
        mailbox_names[m.id] = m.name
        entry = {
            "old_id": m.id,
            "name": m.name,
            "display_name": m.display_name,
            "mailbox_type": m.mailbox_type,
            "owner_email": lookup_user_email(m.owner_id) if m.owner_id else None,
            "team_name": lookup_team_name(m.team_id) if m.team_id else None,
            "provider": m.provider,
            "auth_type": m.auth_type,
            "smtp_server": m.smtp_server,
            "smtp_port": m.smtp_port,
            "smtp_use_tls": m.smtp_use_tls,
            "smtp_use_ssl": m.smtp_use_ssl,
            "smtp_username": m.smtp_username,
            "smtp_password_enc": m.smtp_password_enc,
            "imap_server": m.imap_server,
            "imap_port": m.imap_port,
            "imap_use_ssl": m.imap_use_ssl,
            "imap_username": m.imap_username,
            "imap_password_enc": m.imap_password_enc,
            "oauth_access_token_enc": m.oauth_access_token_enc,
            "oauth_refresh_token_enc": m.oauth_refresh_token_enc,
            "oauth_expires_at": m.oauth_expires_at.isoformat() if m.oauth_expires_at else None,
            "oauth_email": m.oauth_email,
            "footer_html": m.footer_html,
            "logo_filename": m.logo_filename,
            "color": m.color,
            "is_active": m.is_active,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        }
        if m.logo_filename:
            b64 = read_file_base64([m.logo_filename, os.path.join(mailboxes_dir, m.logo_filename)])
            if b64:
                entry["logo_content_base64"] = b64
        mailboxes_out.append(entry)

    return {
        "mailboxes": mailboxes_out,
        "mailbox_memberships": [{
            "mailbox_name": mailbox_names.get(mm.mailbox_id),
            "user_email": lookup_user_email(mm.user_id),
            "can_read": mm.can_read,
            "can_send": mm.can_send,
            "created_at": mm.created_at.isoformat() if mm.created_at else None,
        } for mm in MailboxMembership.query.all()],
        "mailbox_user_prefs": [{
            "mailbox_name": mailbox_names.get(up.mailbox_id),
            "user_email": lookup_user_email(up.user_id),
            "use_logo": up.use_logo,
            "updated_at": up.updated_at.isoformat() if up.updated_at else None,
        } for up in MailboxUserPref.query.all()],
        "mailbox_auto_replies": [{
            "mailbox_key": ar.mailbox_key,
            "mailbox_name": mailbox_names.get(ar.mailbox_id) if ar.mailbox_id else None,
            "enabled": ar.enabled,
            "subject": ar.subject,
            "body_html": ar.body_html,
            "start_at": ar.start_at.isoformat() if ar.start_at else None,
            "end_at": ar.end_at.isoformat() if ar.end_at else None,
            "updated_at": ar.updated_at.isoformat() if ar.updated_at else None,
        } for ar in MailboxAutoReply.query.all()],
        "email_folders": [{
            "name": ef.name,
            "display_name": ef.display_name,
            "folder_type": ef.folder_type,
            "is_system": ef.is_system,
            "parent_folder": ef.parent_folder,
            "separator": ef.separator,
            "mailbox_name": mailbox_names.get(ef.mailbox_id) if ef.mailbox_id else None,
            "created_at": ef.created_at.isoformat() if ef.created_at else None,
            "last_synced": ef.last_synced.isoformat() if ef.last_synced else None,
        } for ef in EmailFolder.query.all()],
    }


def export_credential_submodels() -> Dict:
    from app.models.credential import Credential

    cred_map = {c.id: (c.website_name, c.username) for c in Credential.query.all()}
    return {
        "credential_folders": [{
            "old_id": f.id,
            "name": f.name,
            "color": f.color,
            "position": f.position,
            "visibility": f.visibility,
            "team_name": lookup_team_name(f.team_id) if f.team_id else None,
            "created_by_email": lookup_user_email(f.created_by),
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        } for f in CredentialFolder.query.order_by(CredentialFolder.id).all()],
        "credential_favorites": [{
            "user_email": lookup_user_email(fav.user_id),
            "website_name": cred_map.get(fav.credential_id, (None, None))[0],
            "username": cred_map.get(fav.credential_id, (None, None))[1],
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
        } for fav in CredentialFavorite.query.all()],
    }


def export_manual_submodels() -> Dict:
    return {
        "manual_folders": [{
            "old_id": f.id,
            "name": f.name,
            "color": f.color,
            "position": f.position,
            "visibility": f.visibility,
            "team_name": lookup_team_name(f.team_id) if f.team_id else None,
            "created_by_email": lookup_user_email(f.created_by),
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        } for f in ManualFolder.query.order_by(ManualFolder.id).all()],
    }


def export_wiki_submodels() -> Dict:
    return {
        "wiki_favorites": [{
            "user_email": lookup_user_email(fav.user_id),
            "page_slug": lookup_entity_name("wiki_page_slug", fav.wiki_page_id),
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
        } for fav in WikiFavorite.query.all()],
    }


def export_contact_submodels() -> Dict:
    from app.models.contact import Contact

    contact_names = {c.id: (c.name, c.email) for c in Contact.query.all()}
    return {
        "contact_favorites": [{
            "user_email": lookup_user_email(fav.user_id),
            "contact_name": contact_names.get(fav.contact_id, (None, None))[0],
            "contact_email": contact_names.get(fav.contact_id, (None, None))[1],
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
        } for fav in ContactFavorite.query.all()],
    }


def export_event_submodels() -> Dict:
    return {
        "event_days": [{
            "old_id": d.id,
            "old_event_id": d.event_id,
            "day_number": d.day_number,
            "date": d.date.isoformat() if d.date else None,
            "start_time": d.start_time.isoformat() if d.start_time else None,
            "end_time": d.end_time.isoformat() if d.end_time else None,
            "location": d.location,
            "label": d.label,
            "notes": d.notes,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in EventDay.query.order_by(EventDay.id).all()],
        "event_todo_lists": [{
            "old_id": tl.id,
            "old_event_id": tl.event_id,
            "old_day_id": tl.day_id,
            "title": tl.title,
            "created_by_email": lookup_user_email(tl.created_by) if tl.created_by else None,
            "created_at": tl.created_at.isoformat() if tl.created_at else None,
        } for tl in EventTodoList.query.order_by(EventTodoList.id).all()],
        "event_todo_items": [{
            "old_todo_list_id": ti.todo_list_id,
            "title": ti.title,
            "is_completed": ti.is_completed,
            "completed_at": ti.completed_at.isoformat() if ti.completed_at else None,
            "completed_by_email": lookup_user_email(ti.completed_by_id) if ti.completed_by_id else None,
            "assigned_to_email": lookup_user_email(ti.assigned_to_user_id) if ti.assigned_to_user_id else None,
            "due_date": ti.due_date.isoformat() if ti.due_date else None,
            "due_time": ti.due_time.isoformat() if ti.due_time else None,
            "position": ti.position,
            "created_at": ti.created_at.isoformat() if ti.created_at else None,
        } for ti in EventTodoItem.query.order_by(EventTodoItem.id).all()],
        "event_booking_personal_links": [{
            "old_event_id": lnk.event_id,
            "old_booking_personal_event_id": lnk.booking_personal_event_id,
            "created_at": lnk.created_at.isoformat() if lnk.created_at else None,
        } for lnk in EventBookingPersonalLink.query.all()],
        "event_custom_fields": [{
            "old_id": cf.id,
            "label": cf.label,
            "category": cf.category,
            "field_type": cf.field_type,
            "options": cf.options,
            "placeholder": cf.placeholder,
            "position": cf.position,
            "is_active": cf.is_active,
            "created_at": cf.created_at.isoformat() if cf.created_at else None,
        } for cf in EventCustomField.query.order_by(EventCustomField.id).all()],
        "event_custom_field_values": [{
            "old_event_id": v.event_id,
            "old_field_id": v.field_id,
            "value": v.value,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        } for v in EventCustomFieldValue.query.all()],
        "event_links": [{
            "old_event_id": lnk.event_id,
            "title": lnk.title,
            "url": lnk.url,
            "created_at": lnk.created_at.isoformat() if lnk.created_at else None,
        } for lnk in EventLink.query.order_by(EventLink.id).all()],
    }


def export_booking_submodels() -> Dict:
    from app.models.booking import BookingForm, BookingRequest
    from app.models.calendar import Calendar

    cal_names = {c.id: c.name for c in Calendar.query.all()}
    form_names = {f.id: f.name for f in BookingForm.query.all()}
    req_tokens = {r.id: r.access_token for r in BookingRequest.query.all()}

    rooms_out = []
    for r in BookingRoom.query.order_by(BookingRoom.id).all():
        entry = {
            "name": r.name,
            "description": r.description,
            "location": r.location,
            "capacity": r.capacity,
            "color": r.color,
            "image_path": r.image_path,
            "is_active": r.is_active,
            "calendar_name": cal_names.get(r.calendar_id) if r.calendar_id else None,
            "default_form_name": form_names.get(r.default_form_id) if r.default_form_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        if r.image_path:
            b64 = read_file_base64([
                r.image_path,
                os.path.join(upload_root(), "booking_rooms", str(r.id), os.path.basename(r.image_path)),
            ])
            if b64:
                entry["image_content_base64"] = b64
                entry["image_original_name"] = os.path.basename(r.image_path)
        rooms_out.append(entry)

    messages_out = [{
        "request_access_token": req_tokens.get(m.request_id),
        "direction": m.direction,
        "subject": m.subject,
        "body_text": m.body_text,
        "body_html": m.body_html,
        "from_email": m.from_email,
        "to_email": m.to_email,
        "message_id": m.message_id,
        "in_reply_to": m.in_reply_to,
        "is_read": m.is_read,
        "created_by_email": lookup_user_email(m.created_by) if m.created_by else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in BookingRequestMessage.query.order_by(BookingRequestMessage.id).all()]

    files_out = []
    for bf in BookingRequestFile.query.order_by(BookingRequestFile.id).all():
        item = {
            "request_access_token": req_tokens.get(bf.request_id),
            "file_path": bf.file_path,
            "original_filename": bf.original_filename,
            "uploaded_at": bf.uploaded_at.isoformat() if bf.uploaded_at else None,
        }
        if bf.file_path:
            b64 = read_file_base64([
                bf.file_path,
                os.path.join(upload_root(), "bookings", str(bf.request_id), os.path.basename(bf.file_path)),
            ])
            if b64:
                item["file_content_base64"] = b64
        files_out.append(item)

    return {
        "booking_rooms": rooms_out,
        "booking_request_messages": messages_out,
        "booking_request_files": files_out,
    }


def export_inventory_submodels() -> Dict:
    from app.models.inventory import ProductDocument

    doc_map = {d.id: d.file_name for d in ProductDocument.query.all()}
    lot_map = {lot.id: (lookup_entity_name("product", lot.product_id), lot.lot_code) for lot in ProductLot.query.all()}

    return {
        "length_color_mappings": [{
            "length_meters": m.length_meters,
            "color_hex": m.color_hex,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in LengthColorMapping.query.all()],
        "checkouts": [{
            "old_id": c.id,
            "checkout_number": c.checkout_number,
            "event_name": c.event_name,
            "borrower_name": c.borrower_name,
            "borrower_email": lookup_user_email(c.borrower_id) if c.borrower_id else None,
            "contact_email": c.contact_email,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "status": c.status,
            "created_by_email": lookup_user_email(c.created_by),
            "qr_code_data": c.qr_code_data,
            "legacy_borrow_group_id": c.legacy_borrow_group_id,
            "receipt_email_sent": c.receipt_email_sent,
            "return_email_sent": c.return_email_sent,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        } for c in Checkout.query.order_by(Checkout.id).all()],
        "checkout_items": [{
            "old_checkout_id": ci.checkout_id,
            "product_name": lookup_entity_name("product", ci.product_id),
            "source_set_name": lookup_entity_name("product_set", ci.source_set_id) if ci.source_set_id else None,
            "returned_at": ci.returned_at.isoformat() if ci.returned_at else None,
            "return_email_sent": ci.return_email_sent,
            "created_at": ci.created_at.isoformat() if ci.created_at else None,
        } for ci in CheckoutItem.query.order_by(CheckoutItem.id).all()],
        "dguv_examinations": [{
            "product_name": lookup_entity_name("product", d.product_id),
            "examiner_email": lookup_user_email(d.examiner_user_id) if d.examiner_user_id else None,
            "examiner_name": d.examiner_name,
            "examiner_email_str": d.examiner_email,
            "device_name": d.device_name,
            "device_serial": d.device_serial,
            "device_calibration_date": d.device_calibration_date.isoformat() if d.device_calibration_date else None,
            "visual_ok": d.visual_ok,
            "r_pe_ohm": d.r_pe_ohm,
            "r_iso_mohm": d.r_iso_mohm,
            "i_pe_ma": d.i_pe_ma,
            "i_touch_ma": d.i_touch_ma,
            "function_ok": d.function_ok,
            "r_pe_limit": d.r_pe_limit,
            "r_iso_limit": d.r_iso_limit,
            "r_pe_pass": d.r_pe_pass,
            "r_iso_pass": d.r_iso_pass,
            "overall_result": d.overall_result,
            "interval_months": d.interval_months,
            "exam_date": d.exam_date.isoformat() if d.exam_date else None,
            "next_exam_date": d.next_exam_date.isoformat() if d.next_exam_date else None,
            "pdf_sha256": d.pdf_sha256,
            "pdf_document_name": doc_map.get(d.pdf_document_id) if d.pdf_document_id else None,
            "signature_serial": d.signature_serial,
            "signed_at": d.signed_at.isoformat() if d.signed_at else None,
            "otp_verified_at": d.otp_verified_at.isoformat() if d.otp_verified_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in DguvExamination.query.order_by(DguvExamination.id).all()],
        "product_lots": [{
            "product_name": lookup_entity_name("product", lot.product_id),
            "lot_code": lot.lot_code,
            "supplier": lot.supplier,
            "expiration_date": lot.expiration_date.isoformat() if lot.expiration_date else None,
            "quantity_on_hand": lot.quantity_on_hand,
            "quantity_reserved": lot.quantity_reserved,
            "unit_cost_cents": lot.unit_cost_cents,
            "created_by_email": lookup_user_email(lot.created_by) if lot.created_by else None,
            "created_at": lot.created_at.isoformat() if lot.created_at else None,
            "updated_at": lot.updated_at.isoformat() if lot.updated_at else None,
        } for lot in ProductLot.query.order_by(ProductLot.id).all()],
        "stock_movements": [{
            "product_name": lookup_entity_name("product", sm.product_id),
            "lot_code": lot_map.get(sm.lot_id, (None, None))[1] if sm.lot_id else None,
            "movement_type": sm.movement_type,
            "quantity_delta": sm.quantity_delta,
            "quantity_after": sm.quantity_after,
            "reason": sm.reason,
            "context_type": sm.context_type,
            "context_id": sm.context_id,
            "performed_by_email": lookup_user_email(sm.performed_by) if sm.performed_by else None,
            "created_at": sm.created_at.isoformat() if sm.created_at else None,
        } for sm in StockMovement.query.order_by(StockMovement.id).all()],
        "product_status_history": [{
            "product_name": lookup_entity_name("product", h.product_id),
            "old_status": h.old_status,
            "new_status": h.new_status,
            "reason": h.reason,
            "note": h.note,
            "changed_by_email": lookup_user_email(h.changed_by) if h.changed_by else None,
            "changed_at": h.changed_at.isoformat() if h.changed_at else None,
        } for h in ProductStatusHistory.query.order_by(ProductStatusHistory.id).all()],
    }
