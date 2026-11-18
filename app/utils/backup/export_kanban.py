"""Backup exporter for the Kanban module (all 19 models + cover & attachment files)."""

from __future__ import annotations

import os
from typing import Dict

from app.models.kanban import (
    KanbanActivity,
    KanbanActivityRead,
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardTemplate,
    KanbanBoardView,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardFieldEnabled,
    KanbanCardFieldValue,
    KanbanCardLabel,
    KanbanCardVote,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanCustomField,
    KanbanCustomFieldCategory,
    KanbanLabel,
    KanbanList,
)
from app.utils.backup.file_io import read_file_base64, upload_root
from app.utils.backup_lookups import lookup_team_name, lookup_user_email


def export_kanban_bundle() -> Dict:
    """Export all Kanban entities and binary attachments/covers."""
    kanban_root = os.path.join(upload_root(), "kanban")
    boards_root = os.path.join(kanban_root, "boards")

    boards_out = []
    for b in KanbanBoard.query.order_by(KanbanBoard.id).all():
        entry = {
            "old_id": b.id,
            "public_id": b.public_id,
            "title": b.title,
            "description": b.description,
            "cover_path": b.cover_path,
            "background": b.background,
            "visibility": b.visibility,
            "team_name": lookup_team_name(b.team_id) if b.team_id else None,
            "created_by_email": lookup_user_email(b.created_by),
            "position": b.position,
            "archived_at": b.archived_at.isoformat() if b.archived_at else None,
            "closed_at": b.closed_at.isoformat() if b.closed_at else None,
            "last_viewed_at": b.last_viewed_at.isoformat() if b.last_viewed_at else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        }
        if b.cover_path and not b.cover_path.startswith(("http://", "https://")):
            b64 = read_file_base64([
                b.cover_path,
                os.path.join(kanban_root, b.cover_path),
                os.path.join(boards_root, os.path.basename(b.cover_path)),
            ])
            if b64:
                entry["cover_content_base64"] = b64
                entry["cover_original_name"] = os.path.basename(b.cover_path)
        boards_out.append(entry)

    members_out = [{
        "old_board_id": m.board_id,
        "user_email": lookup_user_email(m.user_id),
        "role": m.role,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    } for m in KanbanBoardMember.query.all()]

    labels_out = [{
        "old_id": lb.id,
        "old_board_id": lb.board_id,
        "name": lb.name,
        "color": lb.color,
        "position": lb.position,
    } for lb in KanbanLabel.query.order_by(KanbanLabel.id).all()]

    cf_categories_out = [{
        "old_id": c.id,
        "old_board_id": c.board_id,
        "name": c.name,
        "position": c.position,
    } for c in KanbanCustomFieldCategory.query.order_by(KanbanCustomFieldCategory.id).all()]

    lists_out = [{
        "old_id": lst.id,
        "old_board_id": lst.board_id,
        "title": lst.title,
        "position": lst.position,
        "archived_at": lst.archived_at.isoformat() if lst.archived_at else None,
        "default_custom_field_ids": lst.default_custom_field_ids,
        "created_at": lst.created_at.isoformat() if lst.created_at else None,
        "updated_at": lst.updated_at.isoformat() if lst.updated_at else None,
    } for lst in KanbanList.query.order_by(KanbanList.id).all()]

    cards_out = [{
        "old_id": c.id,
        "old_list_id": c.list_id,
        "title": c.title,
        "description": c.description,
        "poll_text": c.poll_text,
        "due_date": c.due_date.isoformat() if c.due_date else None,
        "cover_attachment_id": c.cover_attachment_id,
        "position": c.position,
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "archived_at": c.archived_at.isoformat() if c.archived_at else None,
        "created_by_email": lookup_user_email(c.created_by),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    } for c in KanbanCard.query.order_by(KanbanCard.id).all()]

    custom_fields_out = [{
        "old_id": f.id,
        "old_board_id": f.board_id,
        "old_category_id": f.category_id,
        "old_card_id": f.card_id,
        "field_type": f.field_type,
        "label": f.label,
        "position": f.position,
        "options": f.options,
        "placeholder": f.placeholder,
    } for f in KanbanCustomField.query.order_by(KanbanCustomField.id).all()]

    card_field_enabled_out = [{
        "old_card_id": e.card_id,
        "old_field_id": e.field_id,
    } for e in KanbanCardFieldEnabled.query.all()]

    card_field_values_out = [{
        "old_card_id": v.card_id,
        "old_field_id": v.field_id,
        "value": v.value,
    } for v in KanbanCardFieldValue.query.all()]

    card_labels_out = [{
        "old_card_id": cl.card_id,
        "old_label_id": cl.label_id,
    } for cl in KanbanCardLabel.query.all()]

    card_assignees_out = [{
        "old_card_id": ca.card_id,
        "user_email": lookup_user_email(ca.user_id),
    } for ca in KanbanCardAssignee.query.all()]

    checklists_out = [{
        "old_id": ch.id,
        "old_card_id": ch.card_id,
        "title": ch.title,
        "position": ch.position,
    } for ch in KanbanChecklist.query.order_by(KanbanChecklist.id).all()]

    checklist_items_out = [{
        "old_checklist_id": it.checklist_id,
        "text": it.text,
        "done": it.done,
        "position": it.position,
        "due_date": it.due_date.isoformat() if it.due_date else None,
        "assignee_email": lookup_user_email(it.assignee_id) if it.assignee_id else None,
    } for it in KanbanChecklistItem.query.order_by(KanbanChecklistItem.id).all()]

    attachments_out = []
    for att in KanbanAttachment.query.order_by(KanbanAttachment.id).all():
        item = {
            "old_id": att.id,
            "old_card_id": att.card_id,
            "filename": att.filename,
            "original_filename": att.original_filename,
            "mime_type": att.mime_type,
            "file_size": att.file_size,
            "storage_path": att.storage_path,
            "url": att.url,
            "uploaded_by_email": lookup_user_email(att.uploaded_by),
            "created_at": att.created_at.isoformat() if att.created_at else None,
        }
        if att.storage_path:
            b64 = read_file_base64([
                att.storage_path,
                os.path.join(kanban_root, att.storage_path),
                os.path.join(kanban_root, os.path.basename(att.storage_path)),
            ])
            if b64:
                item["content_base64"] = b64
        attachments_out.append(item)

    votes_out = [{
        "old_card_id": v.card_id,
        "user_email": lookup_user_email(v.user_id),
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in KanbanCardVote.query.all()]

    activities_out = [{
        "old_id": a.id,
        "old_board_id": a.board_id,
        "old_card_id": a.card_id,
        "user_email": lookup_user_email(a.user_id) if a.user_id else None,
        "action": a.action,
        "detail": a.detail,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in KanbanActivity.query.order_by(KanbanActivity.id).all()]

    activity_reads_out = [{
        "old_activity_id": r.activity_id,
        "user_email": lookup_user_email(r.user_id),
        "read_at": r.read_at.isoformat() if r.read_at else None,
    } for r in KanbanActivityRead.query.all()]

    templates_out = [{
        "name": t.name,
        "description": t.description,
        "payload_json": t.payload_json,
        "created_by_email": lookup_user_email(t.created_by),
        "is_global": t.is_global,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in KanbanBoardTemplate.query.order_by(KanbanBoardTemplate.id).all()]

    views_out = [{
        "old_board_id": v.board_id,
        "user_email": lookup_user_email(v.user_id),
        "viewed_at": v.viewed_at.isoformat() if v.viewed_at else None,
    } for v in KanbanBoardView.query.all()]

    return {
        "kanban_boards": boards_out,
        "kanban_board_members": members_out,
        "kanban_labels": labels_out,
        "kanban_custom_field_categories": cf_categories_out,
        "kanban_lists": lists_out,
        "kanban_cards": cards_out,
        "kanban_custom_fields": custom_fields_out,
        "kanban_card_field_enabled": card_field_enabled_out,
        "kanban_card_field_values": card_field_values_out,
        "kanban_card_labels": card_labels_out,
        "kanban_card_assignees": card_assignees_out,
        "kanban_checklists": checklists_out,
        "kanban_checklist_items": checklist_items_out,
        "kanban_attachments": attachments_out,
        "kanban_card_votes": votes_out,
        "kanban_activities": activities_out,
        "kanban_activity_reads": activity_reads_out,
        "kanban_board_templates": templates_out,
        "kanban_board_views": views_out,
    }
