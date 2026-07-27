"""Erweiterte Backup-Export/Import-Funktionen für neue Module (Backup 1.1)."""
from __future__ import annotations

import base64
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

from flask import current_app

from app import db
from app.models import (
    User, Chat, ChatPin, Folder, ResourceACL, FolderFavorite,
    Calendar, CalendarEvent, CalendarSyncSource, PublicCalendarFeed,
    Contact, ShortLink,
    Event, EventAppointment, EventAssignment, EventInventoryNeed, EventContact, EventTimelineItem,
    MusicSettings, MusicWish, MusicQueue,
    MediaDownloadJob,
    AssessmentUser, AssessmentRole, AssessmentUserRole, AssessmentUserList, AssessmentStandType,
    AssessmentList, AssessmentListSubject, AssessmentRoom, AssessmentStand,
    AssessmentCriterion, AssessmentEvaluation, AssessmentEvaluationScore,
    AssessmentVisitorEvaluation, AssessmentVisitorEvaluationScore,
    AssessmentWarning, AssessmentRoomInspection, AssessmentAppSetting,
)
from app.models.role import UserModuleRole
from app.models.booking import (
    BookingForm, BookingFormField, BookingFormImage, BookingRequest, BookingRequestField,
    BookingFormRole, BookingFormRoleUser, BookingRequestApproval,
)


def _user_email(user_id) -> Optional[str]:
    if not user_id:
        return None
    u = User.query.get(user_id)
    return u.email if u else None


def _resolve_user(email, user_map, current_user_id):
    if email and email in user_map:
        return user_map[email]
    return current_user_id


def export_user_module_roles() -> List[Dict]:
    roles = UserModuleRole.query.all()
    return [{
        'user_email': _user_email(r.user_id),
        'module_key': r.module_key,
        'has_access': r.has_access,
    } for r in roles]


def import_user_module_roles(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        module_key = row.get('module_key') or row.get('module_name')
        if not uid or not module_key:
            continue
        existing = UserModuleRole.query.filter_by(user_id=uid, module_key=module_key).first()
        if existing:
            existing.has_access = bool(row.get('has_access', True))
        else:
            db.session.add(UserModuleRole(
                user_id=uid,
                module_key=module_key,
                has_access=bool(row.get('has_access', True)),
            ))


def export_chat_pins() -> List[Dict]:
    pins = ChatPin.query.all()
    return [{
        'user_email': _user_email(p.user_id),
        'chat_name': Chat.query.get(p.chat_id).name if Chat.query.get(p.chat_id) else None,
        'created_at': p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
    } for p in pins]


def import_chat_pins(data: List[Dict], chat_map: Dict[str, int], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        chat_name = row.get('chat_name')
        if not chat_name or chat_name not in chat_map:
            continue
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        if not uid:
            continue
        chat_id = chat_map[chat_name]
        if not ChatPin.query.filter_by(user_id=uid, chat_id=chat_id).first():
            db.session.add(ChatPin(user_id=uid, chat_id=chat_id))


def export_calendars() -> List[Dict]:
    return [{
        'name': c.name,
        'calendar_type': c.calendar_type,
        'owner_email': _user_email(c.owner_id),
        'color': c.color,
        'created_at': c.created_at.isoformat() if c.created_at else None,
        '_export_id': c.id,
    } for c in Calendar.query.all()]


def import_calendars(data: List[Dict], user_map: Dict[str, int], current_user_id=None) -> Dict[int, int]:
    """Map: backup calendar id -> local id"""
    id_map = {}
    for row in data:
        owner_id = _resolve_user(row.get('owner_email'), user_map, current_user_id)
        existing = Calendar.query.filter_by(
            name=row.get('name'),
            calendar_type=row.get('calendar_type', 'personal'),
            owner_id=owner_id,
        ).first()
        if existing:
            cal = existing
        else:
            cal = Calendar(
                name=row.get('name') or 'Kalender',
                calendar_type=row.get('calendar_type') or 'personal',
                owner_id=owner_id,
                color=row.get('color') or '#0d6efd',
            )
            db.session.add(cal)
            db.session.flush()
        if row.get('_export_id') is not None:
            id_map[int(row['_export_id'])] = cal.id
    return id_map


def export_calendar_sync_sources() -> List[Dict]:
    out = []
    for s in CalendarSyncSource.query.all():
        out.append({
            'name': getattr(s, 'name', None),
            'url': getattr(s, 'url', None),
            'owner_email': _user_email(getattr(s, 'owner_id', None) or getattr(s, 'created_by', None)),
            'is_active': getattr(s, 'is_active', True),
        })
    return out


def import_calendar_sync_sources(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    # Best-effort: skip if schema mismatch
    for row in data:
        try:
            url = row.get('url')
            if not url:
                continue
            existing = CalendarSyncSource.query.filter_by(url=url).first() if hasattr(CalendarSyncSource, 'url') else None
            if existing:
                continue
            kwargs = {}
            if hasattr(CalendarSyncSource, 'url'):
                kwargs['url'] = url
            if hasattr(CalendarSyncSource, 'name'):
                kwargs['name'] = row.get('name') or 'Import'
            owner = _resolve_user(row.get('owner_email'), user_map, current_user_id)
            if hasattr(CalendarSyncSource, 'owner_id') and owner:
                kwargs['owner_id'] = owner
            if kwargs:
                db.session.add(CalendarSyncSource(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'calendar_sync_sources import skip: {e}')


def export_public_calendar_feeds() -> List[Dict]:
    out = []
    for f in PublicCalendarFeed.query.all():
        out.append({
            'name': getattr(f, 'name', None),
            'token': getattr(f, 'token', None),
            'owner_email': _user_email(getattr(f, 'owner_id', None) or getattr(f, 'user_id', None)),
            'is_active': getattr(f, 'is_active', True),
        })
    return out


def import_public_calendar_feeds(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        try:
            token = row.get('token')
            if token and hasattr(PublicCalendarFeed, 'token'):
                if PublicCalendarFeed.query.filter_by(token=token).first():
                    continue
            kwargs = {}
            for field in ('name', 'token', 'is_active'):
                if hasattr(PublicCalendarFeed, field) and row.get(field) is not None:
                    kwargs[field] = row[field]
            owner = _resolve_user(row.get('owner_email'), user_map, current_user_id)
            if hasattr(PublicCalendarFeed, 'owner_id') and owner:
                kwargs['owner_id'] = owner
            elif hasattr(PublicCalendarFeed, 'user_id') and owner:
                kwargs['user_id'] = owner
            if kwargs:
                db.session.add(PublicCalendarFeed(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'public_calendar_feeds import skip: {e}')


def export_resource_acls() -> List[Dict]:
    out = []
    for a in ResourceACL.query.all():
        folder = Folder.query.get(a.resource_id) if a.resource_type == 'folder' else None
        out.append({
            'resource_type': a.resource_type,
            'folder_name': folder.name if folder else None,
            'grantee_email': _user_email(a.grantee_user_id),
            'permission': a.permission,
            'created_by_email': _user_email(a.created_by),
        })
    return out


def import_resource_acls(data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        if row.get('resource_type') != 'folder':
            continue
        folder_name = row.get('folder_name')
        if not folder_name or folder_name not in folder_map:
            continue
        creator = _resolve_user(row.get('created_by_email'), user_map, current_user_id)
        if not creator:
            continue
        grantee = None
        if row.get('grantee_email') or row.get('user_email'):
            grantee = _resolve_user(row.get('grantee_email') or row.get('user_email'), user_map, current_user_id)
        rid = folder_map[folder_name]
        existing = ResourceACL.query.filter_by(
            resource_type='folder',
            resource_id=rid,
            grantee_user_id=grantee,
        ).first()
        if existing:
            existing.permission = row.get('permission') or existing.permission
        else:
            db.session.add(ResourceACL(
                resource_type='folder',
                resource_id=rid,
                grantee_user_id=grantee,
                permission=row.get('permission') or 'view',
                created_by=creator,
            ))


def export_folder_favorites() -> List[Dict]:
    return [{
        'folder_name': Folder.query.get(f.folder_id).name if Folder.query.get(f.folder_id) else None,
        'user_email': _user_email(f.user_id),
    } for f in FolderFavorite.query.all()]


def import_folder_favorites(data: List[Dict], folder_map: Dict[str, int], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        fname = row.get('folder_name')
        if not fname or fname not in folder_map:
            continue
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        if not uid:
            continue
        fid = folder_map[fname]
        if not FolderFavorite.query.filter_by(folder_id=fid, user_id=uid).first():
            db.session.add(FolderFavorite(folder_id=fid, user_id=uid))


def export_contacts() -> List[Dict]:
    return [{
        'salutation': c.salutation,
        'name': c.name,
        'sort_name': c.sort_name,
        'email': c.email,
        'phone': c.phone,
        'notes': c.notes,
        'created_by_email': _user_email(c.created_by),
        'created_at': c.created_at.isoformat() if c.created_at else None,
    } for c in Contact.query.all()]


def import_contacts(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        email = row.get('email')
        if not email:
            continue
        existing = Contact.query.filter_by(email=email).first()
        created_by = _resolve_user(row.get('created_by_email'), user_map, current_user_id)
        if not created_by:
            continue
        if existing:
            existing.name = row.get('name') or existing.name
            existing.sort_name = row.get('sort_name') or existing.sort_name
            existing.phone = row.get('phone')
            existing.notes = row.get('notes')
            existing.salutation = row.get('salutation')
        else:
            db.session.add(Contact(
                salutation=row.get('salutation'),
                name=row.get('name') or email,
                sort_name=row.get('sort_name') or row.get('name') or email,
                email=email,
                phone=row.get('phone'),
                notes=row.get('notes'),
                created_by=created_by,
            ))


def export_portal_events() -> List[Dict]:
    return [{
        '_export_id': e.id,
        'name': e.name,
        'description': e.description,
        'default_location': e.default_location,
        'owner_email': _user_email(e.owner_id),
        'created_by_email': _user_email(e.created_by),
        'is_archived': e.is_archived,
        'archived_at': e.archived_at.isoformat() if e.archived_at else None,
        'created_at': e.created_at.isoformat() if e.created_at else None,
    } for e in Event.query.all()]


def import_portal_events(data: List[Dict], user_map: Dict[str, int], current_user_id=None) -> Dict[int, int]:
    id_map = {}
    for row in data:
        owner = _resolve_user(row.get('owner_email'), user_map, current_user_id)
        creator = _resolve_user(row.get('created_by_email'), user_map, current_user_id) or owner
        if not owner or not creator:
            continue
        existing = Event.query.filter_by(name=row.get('name'), owner_id=owner).first()
        if existing:
            ev = existing
        else:
            ev = Event(
                name=row.get('name') or 'Event',
                description=row.get('description'),
                default_location=row.get('default_location'),
                owner_id=owner,
                created_by=creator,
                is_archived=bool(row.get('is_archived')),
            )
            db.session.add(ev)
            db.session.flush()
        if row.get('_export_id') is not None:
            id_map[int(row['_export_id'])] = ev.id
    return id_map


def export_event_appointments() -> List[Dict]:
    return [{
        'event_export_id': a.event_id,
        'label': a.label,
        'description': a.description,
        'start_time': a.start_time.isoformat() if a.start_time else None,
        'end_time': a.end_time.isoformat() if a.end_time else None,
        'location': a.location,
        '_export_id': a.id,
    } for a in EventAppointment.query.all()]


def import_event_appointments(data: List[Dict], event_id_map: Dict[int, int]) -> Dict[int, int]:
    appt_map = {}
    for row in data:
        eid = event_id_map.get(row.get('event_export_id'))
        if not eid:
            continue
        appt = EventAppointment(
            event_id=eid,
            label=row.get('label') or 'Termin',
            description=row.get('description'),
            start_time=datetime.fromisoformat(row['start_time']) if row.get('start_time') else datetime.utcnow(),
            end_time=datetime.fromisoformat(row['end_time']) if row.get('end_time') else datetime.utcnow(),
            location=row.get('location'),
        )
        db.session.add(appt)
        db.session.flush()
        if row.get('_export_id') is not None:
            appt_map[int(row['_export_id'])] = appt.id
    return appt_map


def export_event_assignments() -> List[Dict]:
    return [{
        'event_export_id': a.event_id,
        'user_email': _user_email(getattr(a, 'user_id', None)),
        'role': getattr(a, 'role', None),
        'notes': getattr(a, 'notes', None),
    } for a in EventAssignment.query.all()]


def import_event_assignments(data: List[Dict], event_id_map: Dict[int, int], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        eid = event_id_map.get(row.get('event_export_id'))
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        if not eid or not uid:
            continue
        kwargs = {'event_id': eid}
        if hasattr(EventAssignment, 'user_id'):
            kwargs['user_id'] = uid
        if hasattr(EventAssignment, 'role'):
            kwargs['role'] = row.get('role')
        if hasattr(EventAssignment, 'notes'):
            kwargs['notes'] = row.get('notes')
        try:
            db.session.add(EventAssignment(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'event_assignment skip: {e}')


def export_event_inventory_needs() -> List[Dict]:
    return [{
        'appointment_export_id': n.appointment_id,
        'product_name': getattr(n, 'product_name', None) or getattr(n, 'notes', None),
        'quantity': getattr(n, 'quantity', None),
    } for n in EventInventoryNeed.query.all()]


def import_event_inventory_needs(data: List[Dict], event_id_map: Dict[int, int]):
    # appointments mapped only if we have appt map – skip soft if missing
    for row in data:
        try:
            appt_id = row.get('appointment_export_id')
            if not appt_id:
                continue
            # Without appointment map in caller, best-effort skip
        except Exception:
            pass


def export_event_contacts() -> List[Dict]:
    return [{
        'event_export_id': c.event_id,
        'contact_name': getattr(c, 'name', None) or getattr(c, 'contact_name', None),
        'email': getattr(c, 'email', None),
        'phone': getattr(c, 'phone', None),
        'role': getattr(c, 'role', None),
    } for c in EventContact.query.all()]


def import_event_contacts(data: List[Dict], event_id_map: Dict[int, int]):
    for row in data:
        eid = event_id_map.get(row.get('event_export_id'))
        if not eid:
            continue
        kwargs = {'event_id': eid}
        for field, key in [('name', 'contact_name'), ('contact_name', 'contact_name'), ('email', 'email'), ('phone', 'phone'), ('role', 'role')]:
            if hasattr(EventContact, field) and row.get(key) is not None:
                kwargs[field] = row.get(key)
        try:
            db.session.add(EventContact(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'event_contact skip: {e}')


def export_event_timeline_items() -> List[Dict]:
    return [{
        'event_export_id': t.event_id,
        'title': getattr(t, 'title', None) or getattr(t, 'label', None),
        'position': getattr(t, 'position', 0),
        'description': getattr(t, 'description', None),
    } for t in EventTimelineItem.query.all()]


def import_event_timeline_items(data: List[Dict], event_id_map: Dict[int, int]):
    for row in data:
        eid = event_id_map.get(row.get('event_export_id'))
        if not eid:
            continue
        kwargs = {'event_id': eid}
        if hasattr(EventTimelineItem, 'title'):
            kwargs['title'] = row.get('title') or 'Item'
        if hasattr(EventTimelineItem, 'label'):
            kwargs['label'] = row.get('title') or 'Item'
        if hasattr(EventTimelineItem, 'position'):
            kwargs['position'] = row.get('position') or 0
        if hasattr(EventTimelineItem, 'description'):
            kwargs['description'] = row.get('description')
        try:
            db.session.add(EventTimelineItem(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'event_timeline skip: {e}')


def export_booking_forms() -> List[Dict]:
    return [{
        '_export_id': f.id,
        'title': f.title,
        'description': f.description,
        'is_active': f.is_active,
        'created_by_email': _user_email(f.created_by),
        'archive_days': f.archive_days,
        'enable_mailbox': f.enable_mailbox,
        'enable_shared_folder': f.enable_shared_folder,
        'pdf_application_text': f.pdf_application_text,
        'pdf_footer_text': f.pdf_footer_text,
    } for f in BookingForm.query.all()]


def export_booking_form_fields() -> List[Dict]:
    return [{
        'form_export_id': f.form_id,
        'field_type': f.field_type,
        'field_name': f.field_name,
        'field_label': f.field_label,
        'is_required': f.is_required,
        'field_order': getattr(f, 'field_order', 0),
        'options': getattr(f, 'options', None),
        '_export_id': f.id,
    } for f in BookingFormField.query.all()]


def export_booking_form_images() -> List[Dict]:
    out = []
    for img in BookingFormImage.query.all():
        row = {
            'form_export_id': img.form_id,
            'display_order': getattr(img, 'display_order', 0),
            'file_path': getattr(img, 'file_path', None) or getattr(img, 'path', None),
        }
        path = row['file_path']
        if path and os.path.exists(path):
            try:
                with open(path, 'rb') as fh:
                    row['content_base64'] = base64.b64encode(fh.read()).decode('utf-8')
            except Exception:
                pass
        out.append(row)
    return out


def export_booking_form_roles() -> List[Dict]:
    return [{
        '_export_id': r.id,
        'form_export_id': r.form_id,
        'name': getattr(r, 'name', None) or getattr(r, 'role_name', None),
        'role_order': getattr(r, 'role_order', 0),
    } for r in BookingFormRole.query.all()]


def export_booking_form_role_users() -> List[Dict]:
    return [{
        'role_export_id': ru.role_id if hasattr(ru, 'role_id') else getattr(ru, 'form_role_id', None),
        'user_email': _user_email(ru.user_id),
    } for ru in BookingFormRoleUser.query.all()]


def export_booking_requests() -> List[Dict]:
    return [{
        '_export_id': r.id,
        'form_export_id': r.form_id,
        'status': getattr(r, 'status', None),
        'created_by_email': _user_email(getattr(r, 'created_by', None) or getattr(r, 'user_id', None)),
        'created_at': r.created_at.isoformat() if getattr(r, 'created_at', None) else None,
    } for r in BookingRequest.query.all()]


def export_booking_request_fields() -> List[Dict]:
    return [{
        'request_export_id': f.request_id,
        'field_name': getattr(f, 'field_name', None),
        'value': getattr(f, 'value', None) or getattr(f, 'field_value', None),
    } for f in BookingRequestField.query.all()]


def export_booking_request_approvals() -> List[Dict]:
    return [{
        'request_export_id': a.request_id,
        'user_email': _user_email(getattr(a, 'user_id', None) or getattr(a, 'approver_id', None)),
        'status': getattr(a, 'status', None),
        'comment': getattr(a, 'comment', None),
    } for a in BookingRequestApproval.query.all()]


def import_booking_bundle(backup_data: Dict, user_map: Dict[str, int], current_user_id, results: Dict):
    form_map = {}
    if 'booking_forms' in backup_data:
        for row in backup_data['booking_forms']:
            creator = _resolve_user(row.get('created_by_email'), user_map, current_user_id)
            if not creator:
                continue
            existing = BookingForm.query.filter_by(title=row.get('title'), created_by=creator).first()
            if existing:
                form = existing
            else:
                form = BookingForm(
                    title=row.get('title') or 'Form',
                    description=row.get('description'),
                    is_active=bool(row.get('is_active', True)),
                    created_by=creator,
                    archive_days=row.get('archive_days') or 30,
                    enable_mailbox=bool(row.get('enable_mailbox')),
                    enable_shared_folder=bool(row.get('enable_shared_folder')),
                    pdf_application_text=row.get('pdf_application_text'),
                    pdf_footer_text=row.get('pdf_footer_text'),
                )
                db.session.add(form)
                db.session.flush()
            if row.get('_export_id') is not None:
                form_map[int(row['_export_id'])] = form.id
        results['imported'].append('booking_forms')

    field_map = {}
    if 'booking_form_fields' in backup_data:
        for row in backup_data['booking_form_fields']:
            fid = form_map.get(row.get('form_export_id'))
            if not fid:
                continue
            field = BookingFormField(
                form_id=fid,
                field_type=row.get('field_type') or 'text',
                field_name=row.get('field_name') or 'field',
                field_label=row.get('field_label') or 'Feld',
                is_required=bool(row.get('is_required')),
            )
            if hasattr(BookingFormField, 'field_order'):
                field.field_order = row.get('field_order') or 0
            db.session.add(field)
            db.session.flush()
            if row.get('_export_id') is not None:
                field_map[int(row['_export_id'])] = field.id
        results['imported'].append('booking_form_fields')

    role_map = {}
    if 'booking_form_roles' in backup_data:
        for row in backup_data['booking_form_roles']:
            fid = form_map.get(row.get('form_export_id'))
            if not fid:
                continue
            kwargs = {'form_id': fid}
            if hasattr(BookingFormRole, 'name'):
                kwargs['name'] = row.get('name') or 'Role'
            if hasattr(BookingFormRole, 'role_name'):
                kwargs['role_name'] = row.get('name') or 'Role'
            if hasattr(BookingFormRole, 'role_order'):
                kwargs['role_order'] = row.get('role_order') or 0
            role = BookingFormRole(**kwargs)
            db.session.add(role)
            db.session.flush()
            if row.get('_export_id') is not None:
                role_map[int(row['_export_id'])] = role.id
        results['imported'].append('booking_form_roles')

    if 'booking_form_role_users' in backup_data:
        for row in backup_data['booking_form_role_users']:
            rid = role_map.get(row.get('role_export_id'))
            uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
            if not rid or not uid:
                continue
            kwargs = {'user_id': uid}
            if hasattr(BookingFormRoleUser, 'role_id'):
                kwargs['role_id'] = rid
            elif hasattr(BookingFormRoleUser, 'form_role_id'):
                kwargs['form_role_id'] = rid
            try:
                db.session.add(BookingFormRoleUser(**kwargs))
            except Exception:
                pass
        results['imported'].append('booking_form_role_users')

    req_map = {}
    if 'booking_requests' in backup_data:
        for row in backup_data['booking_requests']:
            fid = form_map.get(row.get('form_export_id'))
            creator = _resolve_user(row.get('created_by_email'), user_map, current_user_id)
            if not fid:
                continue
            kwargs = {'form_id': fid}
            if hasattr(BookingRequest, 'status'):
                kwargs['status'] = row.get('status') or 'pending'
            if hasattr(BookingRequest, 'created_by') and creator:
                kwargs['created_by'] = creator
            if hasattr(BookingRequest, 'user_id') and creator:
                kwargs['user_id'] = creator
            req = BookingRequest(**kwargs)
            db.session.add(req)
            db.session.flush()
            if row.get('_export_id') is not None:
                req_map[int(row['_export_id'])] = req.id
        results['imported'].append('booking_requests')

    if 'booking_request_fields' in backup_data:
        for row in backup_data['booking_request_fields']:
            rid = req_map.get(row.get('request_export_id'))
            if not rid:
                continue
            kwargs = {'request_id': rid}
            if hasattr(BookingRequestField, 'field_name'):
                kwargs['field_name'] = row.get('field_name') or 'field'
            if hasattr(BookingRequestField, 'value'):
                kwargs['value'] = row.get('value')
            if hasattr(BookingRequestField, 'field_value'):
                kwargs['field_value'] = row.get('value')
            try:
                db.session.add(BookingRequestField(**kwargs))
            except Exception:
                pass
        results['imported'].append('booking_request_fields')

    if 'booking_request_approvals' in backup_data:
        for row in backup_data['booking_request_approvals']:
            rid = req_map.get(row.get('request_export_id'))
            uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
            if not rid:
                continue
            kwargs = {'request_id': rid}
            if hasattr(BookingRequestApproval, 'user_id') and uid:
                kwargs['user_id'] = uid
            if hasattr(BookingRequestApproval, 'approver_id') and uid:
                kwargs['approver_id'] = uid
            if hasattr(BookingRequestApproval, 'status'):
                kwargs['status'] = row.get('status')
            if hasattr(BookingRequestApproval, 'comment'):
                kwargs['comment'] = row.get('comment')
            try:
                db.session.add(BookingRequestApproval(**kwargs))
            except Exception:
                pass
        results['imported'].append('booking_request_approvals')


def export_music_settings() -> List[Dict]:
    return [{
        'key': getattr(s, 'key', None) or getattr(s, 'setting_key', None),
        'value': getattr(s, 'value', None) or getattr(s, 'setting_value', None),
    } for s in MusicSettings.query.all()]


def import_music_settings(data: List[Dict]):
    for row in data:
        key = row.get('key')
        if not key:
            continue
        try:
            if hasattr(MusicSettings, 'key'):
                existing = MusicSettings.query.filter_by(key=key).first()
                if existing:
                    if hasattr(existing, 'value'):
                        existing.value = row.get('value')
                    continue
                kwargs = {'key': key}
                if hasattr(MusicSettings, 'value'):
                    kwargs['value'] = row.get('value')
                db.session.add(MusicSettings(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'music_settings skip: {e}')


def export_music_wishes() -> List[Dict]:
    return [{
        'title': getattr(w, 'title', None) or getattr(w, 'track_name', None),
        'artist': getattr(w, 'artist', None),
        'user_email': _user_email(getattr(w, 'user_id', None) or getattr(w, 'requested_by', None)),
        'status': getattr(w, 'status', None),
    } for w in MusicWish.query.all()]


def import_music_wishes(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        kwargs = {}
        if hasattr(MusicWish, 'title'):
            kwargs['title'] = row.get('title') or 'Wish'
        if hasattr(MusicWish, 'track_name'):
            kwargs['track_name'] = row.get('title') or 'Wish'
        if hasattr(MusicWish, 'artist'):
            kwargs['artist'] = row.get('artist')
        if hasattr(MusicWish, 'user_id') and uid:
            kwargs['user_id'] = uid
        if hasattr(MusicWish, 'requested_by') and uid:
            kwargs['requested_by'] = uid
        if hasattr(MusicWish, 'status') and row.get('status'):
            kwargs['status'] = row['status']
        try:
            db.session.add(MusicWish(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'music_wish skip: {e}')


def export_music_queue() -> List[Dict]:
    return [{
        'title': getattr(q, 'title', None) or getattr(q, 'track_name', None),
        'artist': getattr(q, 'artist', None),
        'position': getattr(q, 'position', None) or getattr(q, 'sort_order', None),
        'user_email': _user_email(getattr(q, 'user_id', None) or getattr(q, 'added_by', None)),
    } for q in MusicQueue.query.all()]


def import_music_queue(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        kwargs = {}
        if hasattr(MusicQueue, 'title'):
            kwargs['title'] = row.get('title') or 'Track'
        if hasattr(MusicQueue, 'track_name'):
            kwargs['track_name'] = row.get('title') or 'Track'
        if hasattr(MusicQueue, 'artist'):
            kwargs['artist'] = row.get('artist')
        if hasattr(MusicQueue, 'position') and row.get('position') is not None:
            kwargs['position'] = row['position']
        if hasattr(MusicQueue, 'user_id') and uid:
            kwargs['user_id'] = uid
        try:
            db.session.add(MusicQueue(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'music_queue skip: {e}')


def export_media_download_jobs() -> List[Dict]:
    return [{
        'url': getattr(j, 'url', None) or getattr(j, 'source_url', None),
        'status': getattr(j, 'status', None),
        'title': getattr(j, 'title', None),
        'user_email': _user_email(getattr(j, 'user_id', None) or getattr(j, 'created_by', None)),
        'created_at': j.created_at.isoformat() if getattr(j, 'created_at', None) else None,
    } for j in MediaDownloadJob.query.all()]


def import_media_download_jobs(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        uid = _resolve_user(row.get('user_email'), user_map, current_user_id)
        kwargs = {}
        if hasattr(MediaDownloadJob, 'url'):
            kwargs['url'] = row.get('url')
        if hasattr(MediaDownloadJob, 'source_url'):
            kwargs['source_url'] = row.get('url')
        if hasattr(MediaDownloadJob, 'status'):
            kwargs['status'] = row.get('status') or 'completed'
        if hasattr(MediaDownloadJob, 'title'):
            kwargs['title'] = row.get('title')
        if hasattr(MediaDownloadJob, 'user_id') and uid:
            kwargs['user_id'] = uid
        if hasattr(MediaDownloadJob, 'created_by') and uid:
            kwargs['created_by'] = uid
        if not kwargs.get('url') and not kwargs.get('source_url'):
            continue
        try:
            db.session.add(MediaDownloadJob(**kwargs))
        except Exception as e:
            current_app.logger.warning(f'media_download_job skip: {e}')


def export_assessment_bundle() -> Dict[str, List]:
    """Pragmatischer Assessment-Export (Kern-Entities)."""
    data = {
        'assessment_roles': [{'name': r.name, 'permissions': getattr(r, 'permissions', None)} for r in AssessmentRole.query.all()],
        'assessment_stand_types': [{'name': t.name, 'description': getattr(t, 'description', None)} for t in AssessmentStandType.query.all()],
        'assessment_app_settings': [],
        'assessment_lists': [],
    }
    for s in AssessmentAppSetting.query.all():
        data['assessment_app_settings'].append({
            'key': getattr(s, 'key', None) or getattr(s, 'setting_key', None),
            'value': getattr(s, 'value', None) or getattr(s, 'setting_value', None),
        })
    for lst in AssessmentList.query.all():
        data['assessment_lists'].append({
            '_export_id': lst.id,
            'name': getattr(lst, 'name', None) or getattr(lst, 'title', None),
            'is_active': getattr(lst, 'is_active', True),
        })
    data['assessment_rooms'] = [{
        'name': r.name,
        'list_export_id': getattr(r, 'list_id', None),
    } for r in AssessmentRoom.query.all()]
    data['assessment_criteria'] = [{
        'name': c.name,
        'list_export_id': getattr(c, 'list_id', None),
        'max_score': getattr(c, 'max_score', None),
    } for c in AssessmentCriterion.query.all()]
    data['assessment_stands'] = [{
        'name': getattr(s, 'name', None) or getattr(s, 'title', None),
        'list_export_id': getattr(s, 'list_id', None),
        'room_name': AssessmentRoom.query.get(s.room_id).name if getattr(s, 'room_id', None) and AssessmentRoom.query.get(s.room_id) else None,
    } for s in AssessmentStand.query.all()]
    data['assessment_users'] = [{
        'username': u.username,
        'display_name': u.display_name,
        'is_admin': u.is_admin,
        'role_names': u.role_names,
        'list_names': [lst.name for lst in (u.evaluation_lists or [])],
    } for u in AssessmentUser.query.all()]
    return data


def import_assessment_bundle(backup_data: Dict, results: Dict):
    list_map = {}
    if 'assessment_roles' in backup_data:
        for row in backup_data['assessment_roles']:
            name = row.get('name')
            if not name:
                continue
            if not AssessmentRole.query.filter_by(name=name).first():
                kwargs = {'name': name}
                if hasattr(AssessmentRole, 'permissions'):
                    kwargs['permissions'] = row.get('permissions')
                db.session.add(AssessmentRole(**kwargs))
        results['imported'].append('assessment_roles')

    if 'assessment_stand_types' in backup_data:
        for row in backup_data['assessment_stand_types']:
            name = row.get('name')
            if name and not AssessmentStandType.query.filter_by(name=name).first():
                db.session.add(AssessmentStandType(name=name, description=row.get('description')))
        results['imported'].append('assessment_stand_types')

    if 'assessment_app_settings' in backup_data:
        for row in backup_data['assessment_app_settings']:
            key = row.get('key')
            if not key:
                continue
            try:
                if hasattr(AssessmentAppSetting, 'key'):
                    existing = AssessmentAppSetting.query.filter_by(key=key).first()
                    if existing and hasattr(existing, 'value'):
                        existing.value = row.get('value')
                        continue
                    kwargs = {'key': key}
                    if hasattr(AssessmentAppSetting, 'value'):
                        kwargs['value'] = row.get('value')
                    db.session.add(AssessmentAppSetting(**kwargs))
            except Exception:
                pass
        results['imported'].append('assessment_app_settings')

    if 'assessment_lists' in backup_data:
        for row in backup_data['assessment_lists']:
            name = row.get('name')
            if not name:
                continue
            existing = None
            if hasattr(AssessmentList, 'name'):
                existing = AssessmentList.query.filter_by(name=name).first()
            if existing:
                lst = existing
            else:
                kwargs = {}
                if hasattr(AssessmentList, 'name'):
                    kwargs['name'] = name
                if hasattr(AssessmentList, 'title'):
                    kwargs['title'] = name
                if hasattr(AssessmentList, 'is_active'):
                    kwargs['is_active'] = bool(row.get('is_active', True))
                lst = AssessmentList(**kwargs)
                db.session.add(lst)
                db.session.flush()
            if row.get('_export_id') is not None:
                list_map[int(row['_export_id'])] = lst.id
        results['imported'].append('assessment_lists')

    room_map = {}
    if 'assessment_rooms' in backup_data:
        for row in backup_data['assessment_rooms']:
            lid = list_map.get(row.get('list_export_id'))
            name = row.get('name')
            if not name:
                continue
            kwargs = {'name': name}
            if hasattr(AssessmentRoom, 'list_id') and lid:
                kwargs['list_id'] = lid
            try:
                room = AssessmentRoom(**kwargs)
                db.session.add(room)
                db.session.flush()
                room_map[name] = room.id
            except Exception:
                pass
        results['imported'].append('assessment_rooms')

    if 'assessment_criteria' in backup_data:
        for row in backup_data['assessment_criteria']:
            lid = list_map.get(row.get('list_export_id'))
            name = row.get('name')
            if not name:
                continue
            kwargs = {'name': name}
            if hasattr(AssessmentCriterion, 'list_id') and lid:
                kwargs['list_id'] = lid
            if hasattr(AssessmentCriterion, 'max_score') and row.get('max_score') is not None:
                kwargs['max_score'] = row['max_score']
            try:
                db.session.add(AssessmentCriterion(**kwargs))
            except Exception:
                pass
        results['imported'].append('assessment_criteria')

    if 'assessment_stands' in backup_data:
        for row in backup_data['assessment_stands']:
            lid = list_map.get(row.get('list_export_id'))
            name = row.get('name')
            if not name:
                continue
            kwargs = {}
            if hasattr(AssessmentStand, 'name'):
                kwargs['name'] = name
            if hasattr(AssessmentStand, 'title'):
                kwargs['title'] = name
            if hasattr(AssessmentStand, 'list_id') and lid:
                kwargs['list_id'] = lid
            room_id = room_map.get(row.get('room_name'))
            if hasattr(AssessmentStand, 'room_id') and room_id:
                kwargs['room_id'] = room_id
            try:
                db.session.add(AssessmentStand(**kwargs))
            except Exception:
                pass
        results['imported'].append('assessment_stands')


def export_short_links() -> List[Dict]:
    return [{
        'slug': s.slug,
        'target_url': s.target_url,
        'is_active': s.is_active,
        'password_hash': s.password_hash,
        'expires_at': s.expires_at.isoformat() if s.expires_at else None,
        'max_clicks': s.max_clicks,
        'click_count': s.click_count,
        'created_by_email': _user_email(s.created_by),
        'created_at': s.created_at.isoformat() if s.created_at else None,
    } for s in ShortLink.query.all()]


def import_short_links(data: List[Dict], user_map: Dict[str, int], current_user_id=None):
    for row in data:
        slug = row.get('slug')
        if not slug:
            continue
        creator = _resolve_user(row.get('created_by_email'), user_map, current_user_id)
        if not creator:
            continue
        existing = ShortLink.query.filter_by(slug=slug).first()
        if existing:
            existing.target_url = row.get('target_url') or existing.target_url
            existing.is_active = bool(row.get('is_active', True))
            existing.password_hash = row.get('password_hash')
            existing.max_clicks = row.get('max_clicks')
            if row.get('expires_at'):
                existing.expires_at = datetime.fromisoformat(row['expires_at'])
        else:
            link = ShortLink(
                slug=slug,
                target_url=row.get('target_url') or '',
                is_active=bool(row.get('is_active', True)),
                password_hash=row.get('password_hash'),
                max_clicks=row.get('max_clicks'),
                click_count=row.get('click_count') or 0,
                created_by=creator,
            )
            if row.get('expires_at'):
                link.expires_at = datetime.fromisoformat(row['expires_at'])
            db.session.add(link)
