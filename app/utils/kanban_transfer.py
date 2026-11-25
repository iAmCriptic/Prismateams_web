"""Transactional copy and move helpers for Kanban boards, lists, cards, and checklists."""

from __future__ import annotations

import os
import shutil
import uuid

from app import db
from app.models.comment import Comment
from app.models.kanban import (
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardFieldEnabled,
    KanbanCardFieldValue,
    KanbanCardLabel,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanCustomField,
    KanbanCustomFieldCategory,
    KanbanLabel,
    KanbanList,
)
from app.utils.kanban_access import is_effective_board_member


def _kanban_upload_root() -> str:
    from app.blueprints.kanban.helpers import _upload_root
    return _upload_root()


def _copy_physical_file(src_path: str | None, original_name: str | None) -> tuple[str | None, str | None]:
    """Copy a Kanban attachment file on disk if it exists, returning (new_filename, new_storage_path)."""
    if not src_path or not os.path.isfile(src_path):
        return None, src_path or ''
    base_name = os.path.basename(original_name or src_path) or 'file'
    stored = f'{uuid.uuid4().hex}_{base_name}'
    root = _kanban_upload_root()
    os.makedirs(root, exist_ok=True)
    dst_path = os.path.join(root, stored)
    shutil.copy2(src_path, dst_path)
    return stored, dst_path


def _ensure_label_map(source_board_id: int, target_board: KanbanBoard) -> dict[int, int]:
    """Return a mapping from source label IDs to target board label IDs (creating missing labels)."""
    if source_board_id == target_board.id:
        return {lbl.id: lbl.id for lbl in target_board.labels}

    existing = {(lbl.name.strip().lower(), (lbl.color or '').lower()): lbl.id for lbl in target_board.labels}
    source_labels = KanbanLabel.query.filter_by(board_id=source_board_id).order_by(KanbanLabel.position).all()
    mapping: dict[int, int] = {}
    next_pos = len(target_board.labels)
    for src in source_labels:
        key = (src.name.strip().lower(), (src.color or '').lower())
        if key in existing:
            mapping[src.id] = existing[key]
        else:
            new_lbl = KanbanLabel(
                board_id=target_board.id,
                name=src.name,
                color=src.color,
                position=next_pos,
            )
            next_pos += 1
            db.session.add(new_lbl)
            db.session.flush()
            existing[key] = new_lbl.id
            mapping[src.id] = new_lbl.id
    return mapping


def _ensure_board_field_map(source_board_id: int, target_board: KanbanBoard) -> dict[int, int]:
    """Map board-level custom fields from source board to target board (matching or creating)."""
    if source_board_id == target_board.id:
        return {f.id: f.id for f in target_board.custom_fields}

    cat_map: dict[int, int] = {}
    existing_cats = {c.name.strip().lower(): c.id for c in target_board.custom_field_categories}
    src_cats = (
        KanbanCustomFieldCategory.query
        .filter_by(board_id=source_board_id)
        .order_by(KanbanCustomFieldCategory.position)
        .all()
    )
    next_cat_pos = len(target_board.custom_field_categories)
    for sc in src_cats:
        key = sc.name.strip().lower()
        if key in existing_cats:
            cat_map[sc.id] = existing_cats[key]
        else:
            nc = KanbanCustomFieldCategory(board_id=target_board.id, name=sc.name, position=next_cat_pos)
            next_cat_pos += 1
            db.session.add(nc)
            db.session.flush()
            existing_cats[key] = nc.id
            cat_map[sc.id] = nc.id

    existing_fields = {(f.label.strip().lower(), f.field_type): f.id for f in target_board.custom_fields}
    src_fields = (
        KanbanCustomField.query
        .filter_by(board_id=source_board_id, card_id=None)
        .order_by(KanbanCustomField.position)
        .all()
    )
    field_map: dict[int, int] = {}
    next_f_pos = len(target_board.custom_fields)
    for sf in src_fields:
        key = (sf.label.strip().lower(), sf.field_type)
        if key in existing_fields:
            field_map[sf.id] = existing_fields[key]
        else:
            nf = KanbanCustomField(
                board_id=target_board.id,
                category_id=cat_map.get(sf.category_id) if sf.category_id else None,
                card_id=None,
                field_type=sf.field_type,
                label=sf.label,
                position=next_f_pos,
                options=sf.options,
                placeholder=sf.placeholder,
            )
            next_f_pos += 1
            db.session.add(nf)
            db.session.flush()
            existing_fields[key] = nf.id
            field_map[sf.id] = nf.id
    return field_map


def _insert_at_position(siblings: list, item, position: int | None, pos_attr: str = 'position') -> None:
    """Reorder a list of ORM objects and insert/move `item` to `position`."""
    ordered = [s for s in siblings if s.id != item.id]
    idx = len(ordered) if position is None else max(0, min(int(position), len(ordered)))
    ordered.insert(idx, item)
    for i, obj in enumerate(ordered):
        setattr(obj, pos_attr, i)


def copy_checklist(
    source_checklist: KanbanChecklist,
    target_card: KanbanCard,
    *,
    position: int | None = None,
) -> KanbanChecklist:
    """Copy a checklist and all its items onto `target_card`."""
    target_board = target_card.list.board
    same_board = source_checklist.card.list.board_id == target_board.id
    pos = len(target_card.checklists) if position is None else max(0, int(position))

    new_cl = KanbanChecklist(
        card_id=target_card.id,
        title=source_checklist.title or 'Checkliste',
        position=pos,
    )
    db.session.add(new_cl)
    db.session.flush()

    for idx, it in enumerate(source_checklist.items):
        assignee_id = it.assignee_id
        if assignee_id and not same_board and not is_effective_board_member(target_board, assignee_id):
            assignee_id = None
        db.session.add(
            KanbanChecklistItem(
                checklist_id=new_cl.id,
                text=it.text,
                done=it.done,
                position=idx,
                due_date=it.due_date,
                assignee_id=assignee_id,
            )
        )
    db.session.flush()
    return new_cl


def move_checklist(
    checklist: KanbanChecklist,
    target_card: KanbanCard,
    *,
    position: int | None = None,
) -> KanbanChecklist:
    """Move a checklist (and its items) to `target_card`."""
    source_card = checklist.card
    source_board_id = source_card.list.board_id
    target_board = target_card.list.board

    if source_board_id != target_board.id:
        for it in checklist.items:
            if it.assignee_id and not is_effective_board_member(target_board, it.assignee_id):
                it.assignee_id = None

    checklist.card_id = target_card.id
    db.session.flush()

    target_cls = KanbanChecklist.query.filter_by(card_id=target_card.id).order_by(KanbanChecklist.position).all()
    _insert_at_position(target_cls, checklist, position)

    if source_card.id != target_card.id:
        src_cls = KanbanChecklist.query.filter_by(card_id=source_card.id).order_by(KanbanChecklist.position).all()
        for i, c in enumerate(src_cls):
            c.position = i
    db.session.flush()
    return checklist


def _copy_card_comments(source_card_id: int, target_card_id: int) -> None:
    """Copy top-level and threaded comments for a Kanban card."""
    comments = (
        Comment.query
        .filter_by(content_type='kanban_card', content_id=source_card_id, is_deleted=False)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .all()
    )
    id_map: dict[int, int] = {}
    for c in comments:
        nc = Comment(
            content_type='kanban_card',
            content_id=target_card_id,
            author_id=c.author_id,
            content=c.content,
            parent_id=id_map.get(c.parent_id) if c.parent_id else None,
            created_at=c.created_at,
            updated_at=c.updated_at,
            is_deleted=False,
        )
        db.session.add(nc)
        db.session.flush()
        id_map[c.id] = nc.id


def copy_card(
    source_card: KanbanCard,
    target_list: KanbanList,
    actor_user_id: int,
    *,
    title: str | None = None,
    position: int | None = None,
    label_map: dict[int, int] | None = None,
    field_map: dict[int, int] | None = None,
) -> KanbanCard:
    """Copy a card with all checklists, labels, assignees, custom fields, attachments, cover, and comments."""
    source_board_id = source_card.list.board_id
    target_board = target_list.board
    same_board = source_board_id == target_board.id

    if label_map is None:
        label_map = _ensure_label_map(source_board_id, target_board)
    if field_map is None:
        field_map = _ensure_board_field_map(source_board_id, target_board)

    active_cards = [c for c in target_list.cards if not c.archived_at]
    new_card = KanbanCard(
        list_id=target_list.id,
        title=(title.strip() if title and title.strip() else source_card.title),
        description=source_card.description,
        poll_text=source_card.poll_text,
        due_date=source_card.due_date,
        position=len(active_cards),
        is_template=False,
        completed_at=source_card.completed_at,
        created_by=actor_user_id,
    )
    db.session.add(new_card)
    db.session.flush()

    if position is not None:
        _insert_at_position(active_cards + [new_card], new_card, position)

    # Assignees
    for a in source_card.assignees:
        if same_board or is_effective_board_member(target_board, a.user_id):
            db.session.add(KanbanCardAssignee(card_id=new_card.id, user_id=a.user_id))

    # Labels
    seen_labels: set[int] = set()
    for cl in source_card.card_labels:
        mapped_lid = label_map.get(cl.label_id)
        if mapped_lid and mapped_lid not in seen_labels:
            seen_labels.add(mapped_lid)
            db.session.add(KanbanCardLabel(card_id=new_card.id, label_id=mapped_lid))

    # Checklists
    for cl in source_card.checklists:
        copy_checklist(cl, new_card)

    # Card-local custom fields + board-level custom field values/enabled
    local_field_map: dict[int, int] = {}
    for lf in source_card.local_fields:
        nlf = KanbanCustomField(
            board_id=target_board.id,
            category_id=None,
            card_id=new_card.id,
            field_type=lf.field_type,
            label=lf.label,
            position=lf.position,
            options=lf.options,
            placeholder=lf.placeholder,
        )
        db.session.add(nlf)
        db.session.flush()
        local_field_map[lf.id] = nlf.id

    combined_field_map = {**field_map, **local_field_map}
    for ef in source_card.enabled_fields:
        tfid = combined_field_map.get(ef.field_id)
        if tfid:
            db.session.add(KanbanCardFieldEnabled(card_id=new_card.id, field_id=tfid))
    for fv in source_card.field_values:
        tfid = combined_field_map.get(fv.field_id)
        if tfid:
            db.session.add(KanbanCardFieldValue(card_id=new_card.id, field_id=tfid, value=fv.value))

    # Attachments + cover
    att_id_map: dict[int, int] = {}
    for att in source_card.attachments:
        if att.storage_path:
            new_fn, new_path = _copy_physical_file(att.storage_path, att.original_filename or att.filename)
        else:
            new_fn, new_path = att.filename, att.storage_path
        new_att = KanbanAttachment(
            card_id=new_card.id,
            filename=new_fn or att.filename,
            original_filename=att.original_filename,
            mime_type=att.mime_type,
            file_size=att.file_size,
            storage_path=new_path,
            url=att.url,
            uploaded_by=att.uploaded_by,
        )
        db.session.add(new_att)
        db.session.flush()
        att_id_map[att.id] = new_att.id

    if source_card.cover_attachment_id and source_card.cover_attachment_id in att_id_map:
        new_card.cover_attachment_id = att_id_map[source_card.cover_attachment_id]

    # Comments
    _copy_card_comments(source_card.id, new_card.id)
    db.session.flush()
    return new_card


def _remap_card_for_target_board(
    card: KanbanCard,
    target_board: KanbanBoard,
    label_map: dict[int, int],
    field_map: dict[int, int],
) -> None:
    """Update a card's labels, assignees, checklist assignees, and custom fields when moving across boards."""
    for a in list(card.assignees):
        if not is_effective_board_member(target_board, a.user_id):
            db.session.delete(a)

    for cl in card.checklists:
        for it in cl.items:
            if it.assignee_id and not is_effective_board_member(target_board, it.assignee_id):
                it.assignee_id = None

    existing_target_labels: set[int] = set()
    for cl in list(card.card_labels):
        mapped = label_map.get(cl.label_id)
        if not mapped or mapped in existing_target_labels:
            db.session.delete(cl)
        else:
            cl.label_id = mapped
            existing_target_labels.add(mapped)

    for lf in card.local_fields:
        lf.board_id = target_board.id

    for ef in list(card.enabled_fields):
        if ef.field_id in field_map:
            ef.field_id = field_map[ef.field_id]
    for fv in list(card.field_values):
        if fv.field_id in field_map:
            fv.field_id = field_map[fv.field_id]


def move_card_to_list(
    card: KanbanCard,
    target_list: KanbanList,
    *,
    position: int | None = None,
) -> KanbanCard:
    """Move a card to `target_list` (same board or cross-board)."""
    source_list = card.list
    source_board_id = source_list.board_id
    target_board = target_list.board

    if source_board_id != target_board.id:
        label_map = _ensure_label_map(source_board_id, target_board)
        field_map = _ensure_board_field_map(source_board_id, target_board)
        _remap_card_for_target_board(card, target_board, label_map, field_map)

    card.list_id = target_list.id
    db.session.flush()

    target_cards = (
        KanbanCard.query
        .filter_by(list_id=target_list.id, archived_at=None)
        .order_by(KanbanCard.position)
        .all()
    )
    _insert_at_position(target_cards, card, position)

    if source_list.id != target_list.id:
        src_cards = (
            KanbanCard.query
            .filter_by(list_id=source_list.id, archived_at=None)
            .order_by(KanbanCard.position)
            .all()
        )
        for i, c in enumerate(src_cards):
            c.position = i
    db.session.flush()
    return card


def copy_list(
    source_list: KanbanList,
    target_board: KanbanBoard,
    actor_user_id: int,
    *,
    title: str | None = None,
    position: int | None = None,
    label_map: dict[int, int] | None = None,
    field_map: dict[int, int] | None = None,
) -> KanbanList:
    """Copy a list and all its non-archived cards to `target_board`."""
    if label_map is None:
        label_map = _ensure_label_map(source_list.board_id, target_board)
    if field_map is None:
        field_map = _ensure_board_field_map(source_list.board_id, target_board)

    active_lists = [l for l in target_board.lists if not l.archived_at]
    new_list = KanbanList(
        board_id=target_board.id,
        title=(title.strip() if title and title.strip() else source_list.title),
        position=len(active_lists),
    )
    mapped_default_fields = [field_map[fid] for fid in source_list.get_default_custom_field_ids() if fid in field_map]
    if mapped_default_fields:
        new_list.set_default_custom_field_ids(mapped_default_fields)

    db.session.add(new_list)
    db.session.flush()

    if position is not None:
        _insert_at_position(active_lists + [new_list], new_list, position)

    active_cards = [c for c in source_list.cards if not c.archived_at]
    for idx, card in enumerate(active_cards):
        copy_card(
            card,
            new_list,
            actor_user_id,
            position=idx,
            label_map=label_map,
            field_map=field_map,
        )
    db.session.flush()
    return new_list


def move_list_to_board(
    lst: KanbanList,
    target_board: KanbanBoard,
    *,
    position: int | None = None,
) -> KanbanList:
    """Move a list (and all its cards) to `target_board` or reorder within the same board."""
    source_board = lst.board
    if source_board.id != target_board.id:
        label_map = _ensure_label_map(source_board.id, target_board)
        field_map = _ensure_board_field_map(source_board.id, target_board)
        for card in lst.cards:
            _remap_card_for_target_board(card, target_board, label_map, field_map)
        mapped_defaults = [field_map[fid] for fid in lst.get_default_custom_field_ids() if fid in field_map]
        lst.set_default_custom_field_ids(mapped_defaults)
        lst.board_id = target_board.id
        db.session.flush()

    target_lists = (
        KanbanList.query
        .filter_by(board_id=target_board.id, archived_at=None)
        .order_by(KanbanList.position)
        .all()
    )
    _insert_at_position(target_lists, lst, position)

    if source_board.id != target_board.id:
        src_lists = (
            KanbanList.query
            .filter_by(board_id=source_board.id, archived_at=None)
            .order_by(KanbanList.position)
            .all()
        )
        for i, l in enumerate(src_lists):
            l.position = i
    db.session.flush()
    return lst


def copy_board(
    source_board: KanbanBoard,
    actor_user_id: int,
    *,
    title: str | None = None,
    visibility: str | None = None,
    team_id: int | None = None,
) -> KanbanBoard:
    """Duplicate a complete Kanban board with cover, members, labels, custom fields, lists, cards, and comments."""
    new_cover_path = source_board.cover_path
    if source_board.cover_path:
        _, copied_cover = _copy_physical_file(source_board.cover_path, os.path.basename(source_board.cover_path))
        new_cover_path = copied_cover

    new_board = KanbanBoard(
        title=(title.strip() if title and title.strip() else f"{source_board.title} (Kopie)")[:200],
        description=source_board.description,
        cover_path=new_cover_path,
        background=source_board.background,
        visibility=visibility or source_board.visibility,
        team_id=team_id if visibility is not None or team_id is not None else source_board.team_id,
        created_by=actor_user_id,
        position=0,
    )
    db.session.add(new_board)
    db.session.flush()

    # Copy members (ensure actor is owner)
    db.session.add(KanbanBoardMember(board_id=new_board.id, user_id=actor_user_id, role='owner'))
    for m in source_board.members:
        if m.user_id != actor_user_id:
            db.session.add(KanbanBoardMember(board_id=new_board.id, user_id=m.user_id, role=m.role))
    db.session.flush()

    label_map = _ensure_label_map(source_board.id, new_board)
    field_map = _ensure_board_field_map(source_board.id, new_board)

    active_lists = [l for l in source_board.lists if not l.archived_at]
    for idx, lst in enumerate(active_lists):
        copy_list(
            lst,
            new_board,
            actor_user_id,
            position=idx,
            label_map=label_map,
            field_map=field_map,
        )
    db.session.flush()
    return new_board
