"""Backup importers for sub-models of existing categories."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Optional

from app import db
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
from app.models.booking import BookingForm, BookingRequest
from app.models.calendar import Calendar
from app.models.chat import Chat
from app.models.contact import Contact
from app.models.credential import Credential
from app.models.inventory import LengthColorMapping, ProductDocument
from app.utils.backup.file_io import (
    parse_date,
    parse_dt,
    parse_time,
    resolve_team_id,
    resolve_user_id,
    write_base64_file,
)


def import_settings_submodels(backup_data: Dict, user_map: Dict[str, int]):
    for row in backup_data.get("cloud_import_connections") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        provider = row.get("provider")
        if not uid or not provider:
            continue
        existing = CloudImportConnection.query.filter_by(user_id=uid, provider=provider).first()
        if not existing:
            db.session.add(CloudImportConnection(
                user_id=uid,
                provider=provider,
                display_name=row.get("display_name"),
                credentials_enc=row.get("credentials_enc") or "",
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            ))


def import_user_submodels(backup_data: Dict, user_map: Dict[str, int]):
    chat_by_name = {c.name: c.id for c in Chat.query.all() if c.name}
    for row in backup_data.get("chat_notification_settings") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        cid = chat_by_name.get(row.get("chat_name"))
        if uid and cid and not ChatNotificationSettings.query.filter_by(user_id=uid, chat_id=cid).first():
            db.session.add(ChatNotificationSettings(
                user_id=uid,
                chat_id=cid,
                notifications_enabled=bool(row.get("notifications_enabled", True)),
            ))

    for row in backup_data.get("api_tokens") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        tok = row.get("token")
        if uid and tok and not ApiToken.query.filter_by(token=tok).first():
            db.session.add(ApiToken(
                user_id=uid,
                token=tok,
                token_prefix=row.get("token_prefix") or tok[:8],
                name=row.get("name") or "Token",
                expires_at=parse_dt(row.get("expires_at")),
                created_at=parse_dt(row.get("created_at")),
                last_used_at=parse_dt(row.get("last_used_at")),
            ))

    for row in backup_data.get("app_passwords") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        uname = row.get("username")
        if uid and uname and not AppPassword.query.filter_by(username=uname).first():
            db.session.add(AppPassword(
                user_id=uid,
                username=uname,
                name=row.get("name") or "App",
                password_hash=row.get("password_hash") or "",
                hint=row.get("hint"),
                created_at=parse_dt(row.get("created_at")),
                last_used_at=parse_dt(row.get("last_used_at")),
            ))


def import_email_submodels(
    backup_data: Dict,
    user_map: Dict[str, int],
    team_map: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    mailbox_map: Dict[str, int] = {m.name: m.id for m in Mailbox.query.all()}

    for row in backup_data.get("mailboxes") or []:
        name = row.get("name")
        if not name:
            continue
        mb = Mailbox.query.filter_by(name=name).first()
        if not mb:
            logo_name = row.get("logo_filename")
            if row.get("logo_content_base64"):
                saved = write_base64_file(row["logo_content_base64"], "mailboxes", logo_name or "logo.png")
                if saved:
                    logo_name = os.path.basename(saved)
            mb = Mailbox(
                name=name,
                display_name=row.get("display_name") or name,
                mailbox_type=row.get("mailbox_type") or "shared",
                owner_id=resolve_user_id(row.get("owner_email"), user_map),
                team_id=resolve_team_id(row.get("team_name"), team_map),
                provider=row.get("provider"),
                auth_type=row.get("auth_type") or "password",
                smtp_server=row.get("smtp_server"),
                smtp_port=row.get("smtp_port"),
                smtp_use_tls=bool(row.get("smtp_use_tls", True)),
                smtp_use_ssl=bool(row.get("smtp_use_ssl", False)),
                smtp_username=row.get("smtp_username"),
                smtp_password_enc=row.get("smtp_password_enc"),
                imap_server=row.get("imap_server"),
                imap_port=row.get("imap_port"),
                imap_use_ssl=bool(row.get("imap_use_ssl", True)),
                imap_username=row.get("imap_username"),
                imap_password_enc=row.get("imap_password_enc"),
                oauth_access_token_enc=row.get("oauth_access_token_enc"),
                oauth_refresh_token_enc=row.get("oauth_refresh_token_enc"),
                oauth_expires_at=parse_dt(row.get("oauth_expires_at")),
                oauth_email=row.get("oauth_email"),
                footer_html=row.get("footer_html"),
                logo_filename=logo_name,
                color=row.get("color"),
                is_active=bool(row.get("is_active", True)),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(mb)
            db.session.flush()
        mailbox_map[name] = mb.id

    for row in backup_data.get("mailbox_memberships") or []:
        mid = mailbox_map.get(row.get("mailbox_name"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if mid and uid and not MailboxMembership.query.filter_by(mailbox_id=mid, user_id=uid).first():
            db.session.add(MailboxMembership(
                mailbox_id=mid,
                user_id=uid,
                can_read=bool(row.get("can_read", True)),
                can_send=bool(row.get("can_send", True)),
            ))

    for row in backup_data.get("mailbox_user_prefs") or []:
        mid = mailbox_map.get(row.get("mailbox_name"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if mid and uid and not MailboxUserPref.query.filter_by(mailbox_id=mid, user_id=uid).first():
            db.session.add(MailboxUserPref(
                mailbox_id=mid,
                user_id=uid,
                use_logo=bool(row.get("use_logo", True)),
            ))

    for row in backup_data.get("mailbox_auto_replies") or []:
        mkey = row.get("mailbox_key")
        if not mkey or MailboxAutoReply.query.filter_by(mailbox_key=mkey).first():
            continue
        db.session.add(MailboxAutoReply(
            mailbox_key=mkey,
            mailbox_id=mailbox_map.get(row.get("mailbox_name")) if row.get("mailbox_name") else None,
            enabled=bool(row.get("enabled", False)),
            subject=row.get("subject") or "",
            body_html=row.get("body_html") or "",
            start_at=parse_dt(row.get("start_at")),
            end_at=parse_dt(row.get("end_at")),
        ))

    for row in backup_data.get("email_folders") or []:
        name = row.get("name")
        mid = mailbox_map.get(row.get("mailbox_name")) if row.get("mailbox_name") else None
        if not name or EmailFolder.query.filter_by(name=name, mailbox_id=mid).first():
            continue
        db.session.add(EmailFolder(
            name=name,
            display_name=row.get("display_name") or name,
            folder_type=row.get("folder_type") or "custom",
            is_system=bool(row.get("is_system", False)),
            parent_folder=row.get("parent_folder"),
            separator=row.get("separator") or "/",
            mailbox_id=mid,
            created_at=parse_dt(row.get("created_at")),
            last_synced=parse_dt(row.get("last_synced")),
        ))

    return mailbox_map


def import_credential_submodels(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    team_map: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    folder_map: Dict[str, int] = {f.name: f.id for f in CredentialFolder.query.all()}
    for row in backup_data.get("credential_folders") or []:
        name = row.get("name")
        if not name or name in folder_map:
            continue
        uid = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not uid:
            continue
        cf = CredentialFolder(
            name=name,
            color=row.get("color"),
            position=row.get("position", 0),
            visibility=row.get("visibility") or "public",
            team_id=resolve_team_id(row.get("team_name"), team_map),
            created_by=uid,
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(cf)
        db.session.flush()
        folder_map[name] = cf.id
    return folder_map


def import_credential_favorites(backup_data: Dict, user_map: Dict[str, int]):
    creds = {(c.website_name, c.username): c.id for c in Credential.query.all()}
    for row in backup_data.get("credential_favorites") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        cid = creds.get((row.get("website_name"), row.get("username")))
        if uid and cid and not CredentialFavorite.query.filter_by(user_id=uid, credential_id=cid).first():
            db.session.add(CredentialFavorite(user_id=uid, credential_id=cid))


def import_manual_submodels(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    team_map: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    folder_map: Dict[str, int] = {f.name: f.id for f in ManualFolder.query.all()}
    for row in backup_data.get("manual_folders") or []:
        name = row.get("name")
        if not name or name in folder_map:
            continue
        uid = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not uid:
            continue
        mf = ManualFolder(
            name=name,
            color=row.get("color"),
            position=row.get("position", 0),
            visibility=row.get("visibility") or "public",
            team_id=resolve_team_id(row.get("team_name"), team_map),
            created_by=uid,
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(mf)
        db.session.flush()
        folder_map[name] = mf.id
    return folder_map


def import_wiki_submodels(backup_data: Dict, page_map: Dict[str, int], user_map: Dict[str, int]):
    from app.models.wiki import WikiPage

    slug_to_id = dict(page_map)
    for p in WikiPage.query.all():
        slug_to_id.setdefault(p.slug, p.id)

    for row in backup_data.get("wiki_favorites") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        pid = slug_to_id.get(row.get("page_slug"))
        if uid and pid and not WikiFavorite.query.filter_by(user_id=uid, wiki_page_id=pid).first():
            db.session.add(WikiFavorite(user_id=uid, wiki_page_id=pid))


def import_contact_submodels(backup_data: Dict, user_map: Dict[str, int]):
    contacts = {(c.name, c.email): c.id for c in Contact.query.all()}
    for row in backup_data.get("contact_favorites") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        cid = contacts.get((row.get("contact_name"), row.get("contact_email")))
        if uid and cid and not ContactFavorite.query.filter_by(user_id=uid, contact_id=cid).first():
            db.session.add(ContactFavorite(user_id=uid, contact_id=cid))


def import_event_submodels(
    backup_data: Dict,
    event_id_map: Dict[int, int],
    user_map: Dict[str, int],
    bp_event_map: Optional[Dict[int, int]] = None,
):
    day_map: Dict[int, int] = {}
    todo_list_map: Dict[int, int] = {}
    cf_map: Dict[int, int] = {}

    for row in backup_data.get("event_days") or []:
        eid = event_id_map.get(row.get("old_event_id"))
        if not eid:
            continue
        old_id = row.get("old_id")
        day = EventDay(
            event_id=eid,
            day_number=row.get("day_number", 1),
            date=parse_date(row.get("date")),
            start_time=parse_time(row.get("start_time")),
            end_time=parse_time(row.get("end_time")),
            location=row.get("location"),
            label=row.get("label"),
            notes=row.get("notes"),
            created_at=parse_dt(row.get("created_at")),
        )
        db.session.add(day)
        db.session.flush()
        if old_id is not None:
            day_map[old_id] = day.id

    for row in backup_data.get("event_todo_lists") or []:
        eid = event_id_map.get(row.get("old_event_id"))
        if not eid:
            continue
        old_id = row.get("old_id")
        tl = EventTodoList(
            event_id=eid,
            day_id=day_map.get(row.get("old_day_id")) if row.get("old_day_id") else None,
            title=row.get("title") or "To-Do",
            created_by=resolve_user_id(row.get("created_by_email"), user_map),
            created_at=parse_dt(row.get("created_at")),
        )
        db.session.add(tl)
        db.session.flush()
        if old_id is not None:
            todo_list_map[old_id] = tl.id

    for row in backup_data.get("event_todo_items") or []:
        tl_id = todo_list_map.get(row.get("old_todo_list_id"))
        if not tl_id:
            continue
        db.session.add(EventTodoItem(
            todo_list_id=tl_id,
            title=row.get("title") or "",
            is_completed=bool(row.get("is_completed", False)),
            completed_at=parse_dt(row.get("completed_at")),
            completed_by_id=resolve_user_id(row.get("completed_by_email"), user_map),
            assigned_to_user_id=resolve_user_id(row.get("assigned_to_email"), user_map),
            due_date=parse_date(row.get("due_date")),
            due_time=parse_time(row.get("due_time")),
            position=row.get("position", 0),
            created_at=parse_dt(row.get("created_at")),
        ))

    for row in backup_data.get("event_booking_personal_links") or []:
        eid = event_id_map.get(row.get("old_event_id"))
        old_bp_id = row.get("old_booking_personal_event_id")
        bp_id = (bp_event_map or {}).get(old_bp_id, old_bp_id)
        if eid and bp_id and not EventBookingPersonalLink.query.filter_by(event_id=eid, booking_personal_event_id=bp_id).first():
            db.session.add(EventBookingPersonalLink(event_id=eid, booking_personal_event_id=bp_id))

    for row in backup_data.get("event_custom_fields") or []:
        old_id = row.get("old_id")
        cf = EventCustomField.query.filter_by(label=row.get("label"), category=row.get("category")).first()
        if not cf:
            cf = EventCustomField(
                label=row.get("label") or "Feld",
                category=row.get("category"),
                field_type=row.get("field_type") or "text",
                options=row.get("options"),
                placeholder=row.get("placeholder"),
                position=row.get("position", 0),
                is_active=bool(row.get("is_active", True)),
                created_at=parse_dt(row.get("created_at")),
            )
            db.session.add(cf)
            db.session.flush()
        if old_id is not None:
            cf_map[old_id] = cf.id

    for row in backup_data.get("event_custom_field_values") or []:
        eid = event_id_map.get(row.get("old_event_id"))
        fid = cf_map.get(row.get("old_field_id"))
        if eid and fid and not EventCustomFieldValue.query.filter_by(event_id=eid, field_id=fid).first():
            db.session.add(EventCustomFieldValue(
                event_id=eid,
                field_id=fid,
                value=row.get("value"),
            ))

    for row in backup_data.get("event_links") or []:
        eid = event_id_map.get(row.get("old_event_id"))
        if eid and row.get("url"):
            db.session.add(EventLink(
                event_id=eid,
                title=row.get("title") or row["url"],
                url=row["url"],
                created_at=parse_dt(row.get("created_at")),
            ))


def import_booking_submodels(backup_data: Dict, user_map: Dict[str, int]):
    cal_by_name = {c.name: c.id for c in Calendar.query.all()}
    form_by_name = {f.name: f.id for f in BookingForm.query.all()}
    req_by_token = {r.access_token: r.id for r in BookingRequest.query.all() if r.access_token}

    for row in backup_data.get("booking_rooms") or []:
        name = row.get("name")
        if not name or BookingRoom.query.filter_by(name=name).first():
            continue
        room = BookingRoom(
            name=name,
            description=row.get("description"),
            location=row.get("location"),
            capacity=row.get("capacity"),
            color=row.get("color"),
            is_active=bool(row.get("is_active", True)),
            calendar_id=cal_by_name.get(row.get("calendar_name")) if row.get("calendar_name") else None,
            default_form_id=form_by_name.get(row.get("default_form_name")) if row.get("default_form_name") else None,
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(room)
        db.session.flush()
        if row.get("image_content_base64"):
            saved = write_base64_file(
                row["image_content_base64"],
                os.path.join("booking_rooms", str(room.id)),
                row.get("image_original_name") or "room.png",
            )
            if saved:
                room.image_path = os.path.basename(saved)

    for row in backup_data.get("booking_request_messages") or []:
        rid = req_by_token.get(row.get("request_access_token"))
        if not rid:
            continue
        db.session.add(BookingRequestMessage(
            request_id=rid,
            direction=row.get("direction") or "outbound",
            subject=row.get("subject"),
            body_text=row.get("body_text"),
            body_html=row.get("body_html"),
            from_email=row.get("from_email"),
            to_email=row.get("to_email"),
            message_id=row.get("message_id"),
            in_reply_to=row.get("in_reply_to"),
            is_read=bool(row.get("is_read", True)),
            created_by=resolve_user_id(row.get("created_by_email"), user_map),
            created_at=parse_dt(row.get("created_at")),
        ))

    for row in backup_data.get("booking_request_files") or []:
        rid = req_by_token.get(row.get("request_access_token"))
        if not rid:
            continue
        fpath = row.get("file_path") or ""
        if row.get("file_content_base64"):
            saved = write_base64_file(
                row["file_content_base64"],
                os.path.join("bookings", str(rid)),
                row.get("original_filename") or "file.bin",
            )
            if saved:
                fpath = saved
        db.session.add(BookingRequestFile(
            request_id=rid,
            file_path=fpath,
            original_filename=row.get("original_filename") or "file",
            uploaded_at=parse_dt(row.get("uploaded_at")),
        ))


def import_inventory_submodels(
    backup_data: Dict,
    product_map: Dict[str, int],
    set_map: Dict[str, int],
    user_map: Dict[str, int],
    current_user_id: Optional[int],
):
    from app.models.inventory import Product

    prod_ids = dict(product_map)
    for p in Product.query.all():
        prod_ids.setdefault(p.name, p.id)

    for row in backup_data.get("length_color_mappings") or []:
        lm = row.get("length_meters")
        if lm is not None and not LengthColorMapping.query.filter_by(length_meters=lm).first():
            db.session.add(LengthColorMapping(length_meters=lm, color_hex=row.get("color_hex") or "#6c757d"))

    checkout_map: Dict[int, int] = {}
    for row in backup_data.get("checkouts") or []:
        old_id = row.get("old_id")
        num = row.get("checkout_number")
        ch = Checkout.query.filter_by(checkout_number=num).first() if num else None
        if not ch:
            ch = Checkout(
                checkout_number=num,
                event_name=row.get("event_name"),
                borrower_name=row.get("borrower_name") or "Unbekannt",
                borrower_id=resolve_user_id(row.get("borrower_email"), user_map),
                contact_email=row.get("contact_email"),
                start_date=parse_dt(row.get("start_date")) or datetime.utcnow(),
                end_date=parse_dt(row.get("end_date")) or datetime.utcnow(),
                status=row.get("status") or "active",
                created_by=resolve_user_id(row.get("created_by_email"), user_map, current_user_id) or current_user_id,
                qr_code_data=row.get("qr_code_data"),
                legacy_borrow_group_id=row.get("legacy_borrow_group_id"),
                receipt_email_sent=bool(row.get("receipt_email_sent", False)),
                return_email_sent=bool(row.get("return_email_sent", False)),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(ch)
            db.session.flush()
        if old_id is not None:
            checkout_map[old_id] = ch.id

    for row in backup_data.get("checkout_items") or []:
        cid = checkout_map.get(row.get("old_checkout_id"))
        pid = prod_ids.get(row.get("product_name"))
        if cid and pid:
            db.session.add(CheckoutItem(
                checkout_id=cid,
                product_id=pid,
                source_set_id=set_map.get(row.get("source_set_name")) if row.get("source_set_name") else None,
                returned_at=parse_dt(row.get("returned_at")),
                return_email_sent=bool(row.get("return_email_sent", False)),
                created_at=parse_dt(row.get("created_at")),
            ))

    docs_by_name = {d.file_name: d.id for d in ProductDocument.query.all()}
    for row in backup_data.get("dguv_examinations") or []:
        pid = prod_ids.get(row.get("product_name"))
        if not pid:
            continue
        db.session.add(DguvExamination(
            product_id=pid,
            examiner_user_id=resolve_user_id(row.get("examiner_email"), user_map),
            examiner_name=row.get("examiner_name"),
            examiner_email=row.get("examiner_email_str"),
            device_name=row.get("device_name"),
            device_serial=row.get("device_serial"),
            device_calibration_date=parse_date(row.get("device_calibration_date")),
            visual_ok=bool(row.get("visual_ok", True)),
            r_pe_ohm=row.get("r_pe_ohm"),
            r_iso_mohm=row.get("r_iso_mohm"),
            i_pe_ma=row.get("i_pe_ma"),
            i_touch_ma=row.get("i_touch_ma"),
            function_ok=bool(row.get("function_ok", True)),
            r_pe_limit=row.get("r_pe_limit"),
            r_iso_limit=row.get("r_iso_limit"),
            r_pe_pass=row.get("r_pe_pass"),
            r_iso_pass=row.get("r_iso_pass"),
            overall_result=row.get("overall_result") or "pass",
            interval_months=row.get("interval_months", 12),
            exam_date=parse_date(row.get("exam_date")),
            next_exam_date=parse_date(row.get("next_exam_date")),
            pdf_sha256=row.get("pdf_sha256"),
            pdf_document_id=docs_by_name.get(row.get("pdf_document_name")) if row.get("pdf_document_name") else None,
            signature_serial=row.get("signature_serial"),
            signed_at=parse_dt(row.get("signed_at")),
            otp_verified_at=parse_dt(row.get("otp_verified_at")),
            created_at=parse_dt(row.get("created_at")),
        ))

    lot_lookup: Dict[tuple, int] = {}
    for row in backup_data.get("product_lots") or []:
        pid = prod_ids.get(row.get("product_name"))
        lcode = row.get("lot_code")
        if not pid or not lcode:
            continue
        lot = ProductLot.query.filter_by(product_id=pid, lot_code=lcode).first()
        if not lot:
            lot = ProductLot(
                product_id=pid,
                lot_code=lcode,
                supplier=row.get("supplier"),
                expiration_date=parse_date(row.get("expiration_date")),
                quantity_on_hand=row.get("quantity_on_hand", 0),
                quantity_reserved=row.get("quantity_reserved", 0),
                unit_cost_cents=row.get("unit_cost_cents"),
                created_by=resolve_user_id(row.get("created_by_email"), user_map, current_user_id),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(lot)
            db.session.flush()
        lot_lookup[(pid, lcode)] = lot.id

    for row in backup_data.get("stock_movements") or []:
        pid = prod_ids.get(row.get("product_name"))
        if not pid:
            continue
        lcode = row.get("lot_code")
        db.session.add(StockMovement(
            product_id=pid,
            lot_id=lot_lookup.get((pid, lcode)) if lcode else None,
            movement_type=row.get("movement_type") or "adjust",
            quantity_delta=row.get("quantity_delta", 0),
            quantity_after=row.get("quantity_after", 0),
            reason=row.get("reason"),
            context_type=row.get("context_type"),
            context_id=row.get("context_id"),
            performed_by=resolve_user_id(row.get("performed_by_email"), user_map),
            created_at=parse_dt(row.get("created_at")),
        ))

    for row in backup_data.get("product_status_history") or []:
        pid = prod_ids.get(row.get("product_name"))
        if not pid:
            continue
        db.session.add(ProductStatusHistory(
            product_id=pid,
            old_status=row.get("old_status"),
            new_status=row.get("new_status") or "available",
            reason=row.get("reason"),
            note=row.get("note"),
            changed_by=resolve_user_id(row.get("changed_by_email"), user_map),
            changed_at=parse_dt(row.get("changed_at")),
        ))
