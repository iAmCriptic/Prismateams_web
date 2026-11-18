"""Backup importer for the Kanban module (all 19 models + ID remapping + files)."""

from __future__ import annotations

import json
import os
from typing import Dict, Optional, Tuple

from app import db
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
from app.utils.backup.file_io import (
    parse_dt,
    resolve_team_id,
    resolve_user_id,
    write_base64_file,
)


def import_kanban_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
) -> Tuple[Dict[int, int], Dict[int, int]]:
    """Import all Kanban models and return ``(board_map, card_map)``."""
    board_map: Dict[int, int] = {}
    list_map: Dict[int, int] = {}
    card_map: Dict[int, int] = {}
    label_map: Dict[int, int] = {}
    cf_cat_map: Dict[int, int] = {}
    field_map: Dict[int, int] = {}
    checklist_map: Dict[int, int] = {}
    attachment_map: Dict[int, int] = {}
    activity_map: Dict[int, int] = {}

    # 1. Boards
    for row in backup_data.get("kanban_boards") or []:
        old_id = row.get("old_id")
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not creator_id:
            continue
        pub_id = row.get("public_id")
        board = KanbanBoard.query.filter_by(public_id=pub_id).first() if pub_id else None
        if not board:
            board = KanbanBoard(
                public_id=pub_id,
                title=row.get("title") or "Board",
                description=row.get("description"),
                background=row.get("background"),
                visibility=row.get("visibility") or "private",
                team_id=resolve_team_id(row.get("team_name"), team_map),
                created_by=creator_id,
                position=row.get("position", 0),
                archived_at=parse_dt(row.get("archived_at")),
                closed_at=parse_dt(row.get("closed_at")),
                last_viewed_at=parse_dt(row.get("last_viewed_at")),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            if row.get("cover_content_base64"):
                saved = write_base64_file(
                    row["cover_content_base64"],
                    os.path.join("kanban", "boards"),
                    row.get("cover_original_name") or "cover.png",
                    prefix="board_cover",
                )
                board.cover_path = saved or row.get("cover_path")
            else:
                board.cover_path = row.get("cover_path")
            db.session.add(board)
            db.session.flush()
        if old_id is not None:
            board_map[old_id] = board.id

    if backup_data.get("kanban_boards"):
        results["imported"].append("kanban_boards")

    # 2. Board Members
    for row in backup_data.get("kanban_board_members") or []:
        board_id = board_map.get(row.get("old_board_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if not board_id or not uid:
            continue
        if not KanbanBoardMember.query.filter_by(board_id=board_id, user_id=uid).first():
            db.session.add(KanbanBoardMember(
                board_id=board_id,
                user_id=uid,
                role=row.get("role") or "member",
                joined_at=parse_dt(row.get("joined_at")),
            ))

    # 3. Labels
    for row in backup_data.get("kanban_labels") or []:
        board_id = board_map.get(row.get("old_board_id"))
        if not board_id:
            continue
        old_id = row.get("old_id")
        lb = KanbanLabel.query.filter_by(board_id=board_id, name=row.get("name")).first()
        if not lb:
            lb = KanbanLabel(
                board_id=board_id,
                name=row.get("name") or "Label",
                color=row.get("color") or "#0d6efd",
                position=row.get("position", 0),
            )
            db.session.add(lb)
            db.session.flush()
        if old_id is not None:
            label_map[old_id] = lb.id

    # 4. Custom Field Categories
    for row in backup_data.get("kanban_custom_field_categories") or []:
        board_id = board_map.get(row.get("old_board_id"))
        if not board_id:
            continue
        old_id = row.get("old_id")
        cat = KanbanCustomFieldCategory.query.filter_by(board_id=board_id, name=row.get("name")).first()
        if not cat:
            cat = KanbanCustomFieldCategory(
                board_id=board_id,
                name=row.get("name") or "Kategorie",
                position=row.get("position", 0),
            )
            db.session.add(cat)
            db.session.flush()
        if old_id is not None:
            cf_cat_map[old_id] = cat.id

    # 5. Lists (defer default_custom_field_ids remapping until custom fields are created)
    deferred_list_defaults = []
    for row in backup_data.get("kanban_lists") or []:
        board_id = board_map.get(row.get("old_board_id"))
        if not board_id:
            continue
        old_id = row.get("old_id")
        lst = KanbanList(
            board_id=board_id,
            title=row.get("title") or "Liste",
            position=row.get("position", 0),
            archived_at=parse_dt(row.get("archived_at")),
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(lst)
        db.session.flush()
        if old_id is not None:
            list_map[old_id] = lst.id
        if row.get("default_custom_field_ids"):
            deferred_list_defaults.append((lst, row["default_custom_field_ids"]))

    if backup_data.get("kanban_lists"):
        results["imported"].append("kanban_lists")

    # 6. Cards (defer cover_attachment_id remapping until attachments are created)
    deferred_card_covers = []
    for row in backup_data.get("kanban_cards") or []:
        list_id = list_map.get(row.get("old_list_id"))
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not list_id or not creator_id:
            continue
        old_id = row.get("old_id")
        card = KanbanCard(
            list_id=list_id,
            title=row.get("title") or "Karte",
            description=row.get("description"),
            poll_text=row.get("poll_text"),
            due_date=parse_dt(row.get("due_date")),
            position=row.get("position", 0),
            completed_at=parse_dt(row.get("completed_at")),
            archived_at=parse_dt(row.get("archived_at")),
            created_by=creator_id,
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(card)
        db.session.flush()
        if old_id is not None:
            card_map[old_id] = card.id
        if row.get("cover_attachment_id") is not None:
            deferred_card_covers.append((card, row["cover_attachment_id"]))

    if backup_data.get("kanban_cards"):
        results["imported"].append("kanban_cards")

    # 7. Custom Fields (board templates + card-local)
    for row in backup_data.get("kanban_custom_fields") or []:
        board_id = board_map.get(row.get("old_board_id"))
        if not board_id:
            continue
        old_id = row.get("old_id")
        old_card_id = row.get("old_card_id")
        new_card_id = card_map.get(old_card_id) if old_card_id is not None else None
        if old_card_id is not None and new_card_id is None:
            continue
        cf = KanbanCustomField(
            board_id=board_id,
            category_id=cf_cat_map.get(row.get("old_category_id")) if row.get("old_category_id") else None,
            card_id=new_card_id,
            field_type=row.get("field_type") or "text",
            label=row.get("label") or "Feld",
            position=row.get("position", 0),
            options=row.get("options"),
            placeholder=row.get("placeholder"),
        )
        db.session.add(cf)
        db.session.flush()
        if old_id is not None:
            field_map[old_id] = cf.id

    # Remap KanbanList.default_custom_field_ids
    for lst, raw_ids in deferred_list_defaults:
        try:
            old_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            remapped = [field_map[fid] for fid in (old_ids or []) if fid in field_map]
            lst.set_default_custom_field_ids(remapped)
        except Exception:
            pass

    # 8. Card Field Enabled & Values
    for row in backup_data.get("kanban_card_field_enabled") or []:
        cid = card_map.get(row.get("old_card_id"))
        fid = field_map.get(row.get("old_field_id"))
        if cid and fid and not KanbanCardFieldEnabled.query.filter_by(card_id=cid, field_id=fid).first():
            db.session.add(KanbanCardFieldEnabled(card_id=cid, field_id=fid))

    for row in backup_data.get("kanban_card_field_values") or []:
        cid = card_map.get(row.get("old_card_id"))
        fid = field_map.get(row.get("old_field_id"))
        if cid and fid and not KanbanCardFieldValue.query.filter_by(card_id=cid, field_id=fid).first():
            db.session.add(KanbanCardFieldValue(card_id=cid, field_id=fid, value=row.get("value")))

    # 9. Card Labels & Assignees & Votes
    for row in backup_data.get("kanban_card_labels") or []:
        cid = card_map.get(row.get("old_card_id"))
        lid = label_map.get(row.get("old_label_id"))
        if cid and lid and not KanbanCardLabel.query.filter_by(card_id=cid, label_id=lid).first():
            db.session.add(KanbanCardLabel(card_id=cid, label_id=lid))

    for row in backup_data.get("kanban_card_assignees") or []:
        cid = card_map.get(row.get("old_card_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if cid and uid and not KanbanCardAssignee.query.filter_by(card_id=cid, user_id=uid).first():
            db.session.add(KanbanCardAssignee(card_id=cid, user_id=uid))

    for row in backup_data.get("kanban_card_votes") or []:
        cid = card_map.get(row.get("old_card_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if cid and uid and not KanbanCardVote.query.filter_by(card_id=cid, user_id=uid).first():
            db.session.add(KanbanCardVote(card_id=cid, user_id=uid, created_at=parse_dt(row.get("created_at"))))

    # 10. Checklists & Items
    for row in backup_data.get("kanban_checklists") or []:
        cid = card_map.get(row.get("old_card_id"))
        if not cid:
            continue
        old_id = row.get("old_id")
        ch = KanbanChecklist(
            card_id=cid,
            title=row.get("title") or "Checkliste",
            position=row.get("position", 0),
        )
        db.session.add(ch)
        db.session.flush()
        if old_id is not None:
            checklist_map[old_id] = ch.id

    for row in backup_data.get("kanban_checklist_items") or []:
        chid = checklist_map.get(row.get("old_checklist_id"))
        if not chid:
            continue
        db.session.add(KanbanChecklistItem(
            checklist_id=chid,
            text=row.get("text") or "",
            done=bool(row.get("done", False)),
            position=row.get("position", 0),
            due_date=parse_dt(row.get("due_date")),
            assignee_id=resolve_user_id(row.get("assignee_email"), user_map),
        ))

    # 11. Attachments (and remap card cover_attachment_id)
    for row in backup_data.get("kanban_attachments") or []:
        cid = card_map.get(row.get("old_card_id"))
        uid = resolve_user_id(row.get("uploaded_by_email"), user_map, current_user_id)
        if not cid or not uid:
            continue
        old_id = row.get("old_id")
        saved_path = None
        if row.get("content_base64"):
            saved_path = write_base64_file(
                row["content_base64"],
                "kanban",
                row.get("original_filename") or row.get("filename") or "attachment.bin",
            )
        att = KanbanAttachment(
            card_id=cid,
            filename=os.path.basename(saved_path) if saved_path else row.get("filename"),
            original_filename=row.get("original_filename"),
            mime_type=row.get("mime_type"),
            file_size=row.get("file_size"),
            storage_path=saved_path or row.get("storage_path"),
            url=row.get("url"),
            uploaded_by=uid,
            created_at=parse_dt(row.get("created_at")),
        )
        db.session.add(att)
        db.session.flush()
        if old_id is not None:
            attachment_map[old_id] = att.id

    for card, old_att_id in deferred_card_covers:
        if old_att_id in attachment_map:
            card.cover_attachment_id = attachment_map[old_att_id]

    if backup_data.get("kanban_attachments"):
        results["imported"].append("kanban_attachments")

    # 12. Activities & Reads
    for row in backup_data.get("kanban_activities") or []:
        board_id = board_map.get(row.get("old_board_id"))
        if not board_id:
            continue
        old_id = row.get("old_id")
        act = KanbanActivity(
            board_id=board_id,
            card_id=card_map.get(row.get("old_card_id")) if row.get("old_card_id") else None,
            user_id=resolve_user_id(row.get("user_email"), user_map),
            action=row.get("action") or "update",
            detail=row.get("detail"),
            created_at=parse_dt(row.get("created_at")),
        )
        db.session.add(act)
        db.session.flush()
        if old_id is not None:
            activity_map[old_id] = act.id

    for row in backup_data.get("kanban_activity_reads") or []:
        act_id = activity_map.get(row.get("old_activity_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if act_id and uid and not KanbanActivityRead.query.filter_by(activity_id=act_id, user_id=uid).first():
            db.session.add(KanbanActivityRead(
                activity_id=act_id,
                user_id=uid,
                read_at=parse_dt(row.get("read_at")),
            ))

    # 13. Board Templates & Views
    for row in backup_data.get("kanban_board_templates") or []:
        uid = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not uid:
            continue
        if not KanbanBoardTemplate.query.filter_by(name=row.get("name"), created_by=uid).first():
            db.session.add(KanbanBoardTemplate(
                name=row.get("name") or "Vorlage",
                description=row.get("description"),
                payload_json=row.get("payload_json") or "{}",
                created_by=uid,
                is_global=bool(row.get("is_global", False)),
                created_at=parse_dt(row.get("created_at")),
            ))

    for row in backup_data.get("kanban_board_views") or []:
        board_id = board_map.get(row.get("old_board_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if board_id and uid and not KanbanBoardView.query.filter_by(board_id=board_id, user_id=uid).first():
            db.session.add(KanbanBoardView(
                board_id=board_id,
                user_id=uid,
                viewed_at=parse_dt(row.get("viewed_at")),
            ))

    return board_map, card_map
