"""Import Kanban boards from Trello-compatible JSON / CSV exports."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app import db
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
    KanbanLabel,
    KanbanList,
)
from app.models.user import User
from app.utils.kanban_access import (
    VISIBILITY_PRIVATE,
    VISIBILITY_TEAM,
    assert_can_import_board_visibility,
    visibility_allowed,
)

_KNOWN_BACKGROUNDS = frozenset({'teal', 'slate', 'ocean', 'forest', 'sunset', 'berry'})

TRELLO_COLOR_HEX = {
    'green': '#22c55e',
    'yellow': '#eab308',
    'orange': '#f97316',
    'red': '#ef4444',
    'purple': '#a855f7',
    'blue': '#3b82f6',
    'sky': '#0ea5e9',
    'lime': '#84cc16',
    'pink': '#ec4899',
    'black': '#334155',
    'green_dark': '#166534',
    'yellow_dark': '#a16207',
    'orange_dark': '#c2410c',
    'red_dark': '#b91c1c',
    'purple_dark': '#7e22ce',
    'blue_dark': '#1d4ed8',
    'sky_dark': '#0369a1',
    'lime_dark': '#4d7c0f',
    'pink_dark': '#be185d',
    'black_dark': '#0f172a',
    'green_light': '#86efac',
    'yellow_light': '#fde047',
    'orange_light': '#fdba74',
    'red_light': '#fca5a5',
    'purple_light': '#d8b4fe',
    'blue_light': '#93c5fd',
    'sky_light': '#7dd3fc',
    'lime_light': '#bef264',
    'pink_light': '#f9a8d4',
    'black_light': '#94a3b8',
}

_CF_FROM_TRELLO = {
    'text': 'text',
    'number': 'text',
    'date': 'date',
    'checkbox': 'checkbox',
    'list': 'select',
}


class KanbanImportError(ValueError):
    """Invalid or unsupported import payload."""


def _parse_dt(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    text = str(raw).strip()
    if not text:
        return None
    # Trello: 2024-07-26T11:42:00.000Z
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d.%m.%Y %H:%M', '%d.%m.%Y'):
            try:
                return datetime.strptime(text[:19], fmt)
            except Exception:
                continue
    return None


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or '').strip().lower() in ('1', 'true', 'yes', 'on', 'complete', 'checked')


def _looks_like_trello_json(data: dict) -> bool:
    return isinstance(data, dict) and (
        'lists' in data and 'cards' in data and ('name' in data or 'id' in data)
    )


def detect_import_format(filename: str, raw: bytes) -> str:
    name = (filename or '').lower()
    if name.endswith('.csv'):
        return 'csv'
    if name.endswith('.json'):
        return 'json'
    head = raw.lstrip()[:1]
    if head in (b'{', b'['):
        return 'json'
    return 'csv'


def _resolve_users_by_email(emails: set[str]) -> dict[str, User]:
    cleaned = {e.strip().lower() for e in emails if e and str(e).strip()}
    if not cleaned:
        return {}
    users = User.query.filter(User.email.in_(cleaned), User.is_active.is_(True)).all()
    return {(u.email or '').strip().lower(): u for u in users}


def _color_hex(color: str | None) -> str:
    if not color:
        return '#3b82f6'
    c = color.strip().lower()
    if c.startswith('#') and len(c) >= 4:
        return c[:7]
    base = c.replace('_dark', '').replace('_light', '')
    return TRELLO_COLOR_HEX.get(c) or TRELLO_COLOR_HEX.get(base) or '#3b82f6'


def import_board_from_bytes(
    *,
    raw: bytes,
    filename: str,
    user: User,
    visibility: str,
    team_id: int | None = None,
    title_override: str | None = None,
) -> KanbanBoard:
    assert_can_import_board_visibility(user, visibility, team_id)
    visibility = (visibility or VISIBILITY_PRIVATE).strip().lower()
    if not visibility_allowed(visibility):
        raise KanbanImportError('visibility_not_allowed')
    if visibility != VISIBILITY_TEAM:
        team_id = None

    fmt = detect_import_format(filename, raw)
    if fmt == 'json':
        try:
            data = json.loads(raw.decode('utf-8-sig'))
        except Exception as exc:
            raise KanbanImportError('invalid_json') from exc
        if not _looks_like_trello_json(data):
            raise KanbanImportError('not_trello_json')
        return _import_trello_json(
            data,
            user=user,
            visibility=visibility,
            team_id=team_id,
            title_override=title_override,
        )

    try:
        text = raw.decode('utf-8-sig')
    except Exception as exc:
        raise KanbanImportError('invalid_csv') from exc
    return _import_trello_csv(
        text,
        user=user,
        visibility=visibility,
        team_id=team_id,
        title_override=title_override,
    )


def _import_trello_json(
    data: dict,
    *,
    user: User,
    visibility: str,
    team_id: int | None,
    title_override: str | None,
) -> KanbanBoard:
    title = (title_override or data.get('name') or 'Imported Board').strip()[:200] or 'Imported Board'
    desc = (data.get('desc') or '').strip() or None
    prefs = data.get('prefs') or {}
    bg = prefs.get('background')
    # Trello often uses opaque bg ids; keep only our known keys
    background = bg if isinstance(bg, str) and bg in _KNOWN_BACKGROUNDS else 'teal'

    board = KanbanBoard(
        title=title,
        description=desc,
        visibility=visibility,
        team_id=team_id,
        created_by=user.id,
        background=background,
        closed_at=_parse_dt(data.get('dateClosed')) if data.get('closed') else None,
    )
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=user.id, role='owner'))

    # Members from export → best-effort by email / username match
    trello_member_to_user: dict[str, int] = {}
    emails: set[str] = set()
    for m in data.get('members') or []:
        if m.get('email'):
            emails.add(str(m['email']).strip().lower())
    email_map = _resolve_users_by_email(emails)
    for m in data.get('members') or []:
        mid = m.get('id')
        if not mid:
            continue
        email = (m.get('email') or '').strip().lower()
        u = email_map.get(email) if email else None
        if u and u.id != user.id:
            trello_member_to_user[mid] = u.id
            existing = KanbanBoardMember.query.filter_by(board_id=board.id, user_id=u.id).first()
            if not existing:
                role = 'admin' if m.get('memberType') == 'admin' else 'member'
                # check memberships for admin
                for ms in data.get('memberships') or []:
                    if ms.get('idMember') == mid and ms.get('memberType') in ('admin', 'owner'):
                        role = 'admin'
                        break
                db.session.add(KanbanBoardMember(board_id=board.id, user_id=u.id, role=role))

    # Labels
    label_map: dict[str, KanbanLabel] = {}
    for i, lb in enumerate(data.get('labels') or []):
        lid = lb.get('id')
        name = (lb.get('name') or '').strip()
        color_name = lb.get('color')
        if not name and color_name:
            # fall back to labelNames map
            name = (data.get('labelNames') or {}).get(color_name) or color_name
        if not name:
            name = color_name or f'Label {i + 1}'
        label = KanbanLabel(
            board_id=board.id,
            name=str(name)[:100],
            color=_color_hex(color_name),
            position=i,
        )
        db.session.add(label)
        db.session.flush()
        if lid:
            label_map[lid] = label

    # Lists (open first, preserve pos)
    lists_sorted = sorted(
        data.get('lists') or [],
        key=lambda x: (bool(x.get('closed')), float(x.get('pos') or 0)),
    )
    list_map: dict[str, KanbanList] = {}
    list_pos = 0
    for lst in lists_sorted:
        lid = lst.get('id')
        kl = KanbanList(
            board_id=board.id,
            title=(lst.get('name') or 'Liste')[:200],
            position=list_pos,
            archived_at=datetime.utcnow() if lst.get('closed') else None,
        )
        db.session.add(kl)
        db.session.flush()
        list_pos += 1
        if lid:
            list_map[lid] = kl

    if not list_map:
        # ensure at least one list
        kl = KanbanList(board_id=board.id, title='To Do', position=0)
        db.session.add(kl)
        db.session.flush()
        list_map['__default__'] = kl

    # Custom fields (board-level)
    field_map: dict[str, KanbanCustomField] = {}
    option_value_map: dict[str, str] = {}  # trello option id -> text
    for i, cf in enumerate(data.get('customFields') or []):
        fid = cf.get('id')
        ftype = _CF_FROM_TRELLO.get(cf.get('type') or 'text', 'text')
        options_json = None
        if ftype == 'select':
            opts = []
            for opt in cf.get('options') or []:
                text = ((opt.get('value') or {}).get('text') or '').strip()
                if text:
                    opts.append(text)
                    if opt.get('id'):
                        option_value_map[opt['id']] = text
            options_json = json.dumps(opts)
        field = KanbanCustomField(
            board_id=board.id,
            field_type=ftype,
            label=(cf.get('name') or 'Field')[:200],
            position=i,
            options=options_json,
        )
        db.session.add(field)
        db.session.flush()
        if fid:
            field_map[fid] = field

    # Index checklists by card
    checklists_by_card: dict[str, list] = {}
    for cl in data.get('checklists') or []:
        cid = cl.get('idCard')
        if not cid:
            continue
        checklists_by_card.setdefault(cid, []).append(cl)

    default_list = next(iter(list_map.values()))
    cards_sorted = sorted(
        data.get('cards') or [],
        key=lambda x: (bool(x.get('closed')), float(x.get('pos') or 0)),
    )

    for card_data in cards_sorted:
        id_list = card_data.get('idList')
        kl = list_map.get(id_list) or default_list
        card = KanbanCard(
            list_id=kl.id,
            title=(card_data.get('name') or 'Karte')[:300],
            description=card_data.get('desc') or None,
            poll_text=card_data.get('pollText') or None,
            due_date=_parse_dt(card_data.get('due')),
            position=int(float(card_data.get('pos') or 0) // 65536) if card_data.get('pos') is not None else 0,
            completed_at=_parse_dt(card_data.get('dateCompleted')) if _truthy(card_data.get('dueComplete')) else None,
            archived_at=datetime.utcnow() if card_data.get('closed') else None,
            created_by=user.id,
        )
        # better position: use index within list later — keep pos scaled down
        if card_data.get('pos') is not None:
            try:
                card.position = max(0, int(float(card_data['pos']) / 65536.0))
            except Exception:
                card.position = 0
        db.session.add(card)
        db.session.flush()

        # labels
        for lid in card_data.get('idLabels') or []:
            label = label_map.get(lid)
            if label:
                db.session.add(KanbanCardLabel(card_id=card.id, label_id=label.id))
        # also from embedded labels array
        for lb in card_data.get('labels') or []:
            lid = lb.get('id')
            if lid and lid in label_map:
                exists = KanbanCardLabel.query.filter_by(card_id=card.id, label_id=label_map[lid].id).first()
                if not exists:
                    db.session.add(KanbanCardLabel(card_id=card.id, label_id=label_map[lid].id))

        # assignees
        for mid in card_data.get('idMembers') or []:
            uid = trello_member_to_user.get(mid)
            if uid:
                db.session.add(KanbanCardAssignee(card_id=card.id, user_id=uid))

        # checklists
        for i, cl in enumerate(sorted(checklists_by_card.get(card_data.get('id'), []), key=lambda x: float(x.get('pos') or 0))):
            checklist = KanbanChecklist(
                card_id=card.id,
                title=(cl.get('name') or 'Checkliste')[:200],
                position=i,
            )
            db.session.add(checklist)
            db.session.flush()
            for j, item in enumerate(sorted(cl.get('checkItems') or [], key=lambda x: float(x.get('pos') or 0))):
                assignee_id = None
                mid = item.get('idMember')
                if mid:
                    assignee_id = trello_member_to_user.get(mid)
                db.session.add(KanbanChecklistItem(
                    checklist_id=checklist.id,
                    text=(item.get('name') or '')[:500] or '…',
                    done=item.get('state') == 'complete',
                    position=j,
                    due_date=_parse_dt(item.get('due')),
                    assignee_id=assignee_id,
                ))

        # attachments — store as link URLs (Trello export has no binaries)
        cover_tid = card_data.get('idAttachmentCover')
        cover_new_id = None
        for att in card_data.get('attachments') or []:
            url = (att.get('url') or '').strip()
            name = (att.get('name') or att.get('fileName') or url or 'Attachment')[:255]
            if not url:
                continue
            # Prefer link attachment; optionally try local download later
            ka = KanbanAttachment(
                card_id=card.id,
                filename='link',
                original_filename=name,
                mime_type=att.get('mimeType') or 'text/uri-list',
                file_size=att.get('bytes'),
                storage_path='',
                url=url,
                uploaded_by=user.id,
            )
            db.session.add(ka)
            db.session.flush()
            if cover_tid and att.get('id') == cover_tid:
                cover_new_id = ka.id
        if cover_new_id:
            card.cover_attachment_id = cover_new_id

        # custom field values
        for item in card_data.get('customFieldItems') or []:
            fid = item.get('idCustomField')
            field = field_map.get(fid)
            if not field:
                continue
            value = None
            if item.get('idValue') and item['idValue'] in option_value_map:
                value = option_value_map[item['idValue']]
            else:
                val = item.get('value') or {}
                if isinstance(val, dict):
                    if 'text' in val:
                        value = str(val.get('text') or '')
                    elif 'number' in val:
                        value = str(val.get('number') or '')
                    elif 'date' in val:
                        value = str(val.get('date') or '')
                    elif 'checked' in val:
                        value = 'true' if _truthy(val.get('checked')) else 'false'
                elif val is not None:
                    value = str(val)
            db.session.add(KanbanCardFieldEnabled(card_id=card.id, field_id=field.id))
            db.session.add(KanbanCardFieldValue(card_id=card.id, field_id=field.id, value=value))

    db.session.flush()
    return board


def _import_trello_csv(
    text: str,
    *,
    user: User,
    visibility: str,
    team_id: int | None,
    title_override: str | None,
) -> KanbanBoard:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise KanbanImportError('invalid_csv')

    # Normalize headers
    def col(*names):
        lower = { (h or '').strip().lower(): h for h in reader.fieldnames }
        for n in names:
            if n.lower() in lower:
                return lower[n.lower()]
        return None

    c_name = col('Card Name', 'Name', 'Title', 'Kartentitel')
    c_desc = col('Card Description', 'Description', 'Desc', 'Beschreibung')
    c_labels = col('Labels', 'Label')
    c_members = col('Members', 'Member', 'Mitglieder')
    c_due = col('Due Date', 'Due', 'Fälligkeitsdatum')
    c_due_done = col('Due Complete', 'Completed')
    c_list = col('List Name', 'List', 'Liste')
    c_board = col('Board Name', 'Board')
    c_att = col('Attachment Links', 'Attachments', 'Attachment URLs')
    c_archived = col('Archived', 'Closed')

    if not c_name:
        raise KanbanImportError('invalid_csv')

    rows = list(reader)
    if not rows:
        raise KanbanImportError('empty_csv')

    board_title = (title_override or '').strip()
    if not board_title and c_board:
        board_title = (rows[0].get(c_board) or '').strip()
    board_title = (board_title or 'Imported Board')[:200]

    board = KanbanBoard(
        title=board_title,
        visibility=visibility,
        team_id=team_id,
        created_by=user.id,
        background='teal',
    )
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=user.id, role='owner'))

    list_map: dict[str, KanbanList] = {}
    label_map: dict[str, KanbanLabel] = {}
    label_pos = 0

    member_emails: set[str] = set()
    if c_members:
        for row in rows:
            for part in (row.get(c_members) or '').split(','):
                part = part.strip()
                if '@' in part:
                    member_emails.add(part.lower())
    email_users = _resolve_users_by_email(member_emails)

    for row in rows:
        list_name = ((row.get(c_list) if c_list else None) or 'To Do').strip() or 'To Do'
        if list_name not in list_map:
            kl = KanbanList(board_id=board.id, title=list_name[:200], position=len(list_map))
            db.session.add(kl)
            db.session.flush()
            list_map[list_name] = kl

        title = (row.get(c_name) or 'Karte').strip()[:300] or 'Karte'
        card = KanbanCard(
            list_id=list_map[list_name].id,
            title=title,
            description=(row.get(c_desc) if c_desc else None) or None,
            due_date=_parse_dt(row.get(c_due)) if c_due else None,
            completed_at=datetime.utcnow() if c_due_done and _truthy(row.get(c_due_done)) else None,
            archived_at=datetime.utcnow() if c_archived and _truthy(row.get(c_archived)) else None,
            position=KanbanCard.query.filter_by(list_id=list_map[list_name].id).count(),
            created_by=user.id,
        )
        db.session.add(card)
        db.session.flush()

        if c_labels:
            for part in (row.get(c_labels) or '').split(','):
                name = part.strip()
                if not name:
                    continue
                if name not in label_map:
                    label = KanbanLabel(
                        board_id=board.id,
                        name=name[:100],
                        color='#3b82f6',
                        position=label_pos,
                    )
                    label_pos += 1
                    db.session.add(label)
                    db.session.flush()
                    label_map[name] = label
                db.session.add(KanbanCardLabel(card_id=card.id, label_id=label_map[name].id))

        if c_members:
            for part in (row.get(c_members) or '').split(','):
                part = part.strip()
                u = None
                if '@' in part:
                    u = email_users.get(part.lower())
                if u:
                    db.session.add(KanbanCardAssignee(card_id=card.id, user_id=u.id))

        if c_att:
            for url in (row.get(c_att) or '').split():
                url = url.strip()
                if not url.startswith(('http://', 'https://')):
                    continue
                name = os.path.basename(urlparse(url).path) or url
                db.session.add(KanbanAttachment(
                    card_id=card.id,
                    filename='link',
                    original_filename=name[:255],
                    mime_type='text/uri-list',
                    storage_path='',
                    url=url,
                    uploaded_by=user.id,
                ))

    if not list_map:
        db.session.add(KanbanList(board_id=board.id, title='To Do', position=0))

    db.session.flush()
    return board
