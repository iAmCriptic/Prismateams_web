"""Export Kanban boards in Trello-compatible JSON / CSV formats."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from flask import has_request_context, url_for

from app.models.kanban import KanbanBoard
from app.models.user import User
from app.utils.kanban_access import get_board_member_roles

EXPORT_VERSION = 'trello-compat-1.0'

# Nearest Trello named colors for our hex labels
_HEX_TO_TRELLO = {
    '#22c55e': 'green',
    '#16a34a': 'green',
    '#eab308': 'yellow',
    '#ca8a04': 'yellow',
    '#f97316': 'orange',
    '#ea580c': 'orange',
    '#ef4444': 'red',
    '#dc2626': 'red',
    '#a855f7': 'purple',
    '#9333ea': 'purple',
    '#3b82f6': 'blue',
    '#2563eb': 'blue',
    '#0d6efd': 'blue',
    '#0ea5e9': 'sky',
    '#0284c7': 'sky',
    '#84cc16': 'lime',
    '#65a30d': 'lime',
    '#ec4899': 'pink',
    '#db2777': 'pink',
    '#334155': 'black',
    '#1e293b': 'black',
    '#000000': 'black',
}

TRELLO_LABEL_NAMES = {
    'green': '', 'yellow': '', 'orange': '', 'red': '', 'purple': '', 'blue': '',
    'sky': '', 'lime': '', 'pink': '', 'black': '',
    'green_dark': '', 'yellow_dark': '', 'orange_dark': '', 'red_dark': '',
    'purple_dark': '', 'blue_dark': '', 'sky_dark': '', 'lime_dark': '',
    'pink_dark': '', 'black_dark': '',
    'green_light': '', 'yellow_light': '', 'orange_light': '', 'red_light': '',
    'purple_light': '', 'blue_light': '', 'sky_light': '', 'lime_light': '',
    'pink_light': '', 'black_light': '',
}

_CF_TYPE_MAP = {
    'text': 'text',
    'select': 'list',
    'date': 'date',
    'time': 'text',
    'checkbox': 'checkbox',
}


def _tid(prefix: str = '') -> str:
    return f'{prefix}{uuid.uuid4().hex[:24]}'[:24] if prefix else uuid.uuid4().hex[:24]


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + '.000Z'
    return dt.isoformat()


def _hex_to_trello_color(hex_color: str | None) -> str:
    raw = (hex_color or '#3b82f6').strip().lower()
    if not raw.startswith('#'):
        raw = '#' + raw
    if raw in _HEX_TO_TRELLO:
        return _HEX_TO_TRELLO[raw]
    # nearest by simple channel distance among known hexes
    try:
        r, g, b = int(raw[1:3], 16), int(raw[3:5], 16), int(raw[5:7], 16)
    except Exception:
        return 'blue'
    best, best_d = 'blue', 1e9
    for hx, name in _HEX_TO_TRELLO.items():
        try:
            rr, gg, bb = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
        except Exception:
            continue
        d = (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
        if d < best_d:
            best, best_d = name, d
    return best


def _parse_options(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _attachment_public_url(att) -> str | None:
    if att.url:
        return att.url
    if not att.storage_path:
        return None
    if not has_request_context():
        return None
    try:
        return url_for('kanban.download_attachment', attachment_id=att.id, _external=True)
    except Exception:
        return None


def _user_email(user: User | None) -> str | None:
    if not user:
        return None
    return (user.email or '').strip().lower() or None


def build_trello_board_dict(board: KanbanBoard) -> dict[str, Any]:
    """Build a Trello board JSON export object (single file, no binaries)."""
    board_tid = _tid()
    list_id_map: dict[int, str] = {}
    label_id_map: dict[int, str] = {}
    card_id_map: dict[int, str] = {}
    member_id_map: dict[int, str] = {}
    field_id_map: dict[int, str] = {}
    attach_id_map: dict[int, str] = {}

    roles = get_board_member_roles(board)
    users = {
        u.id: u
        for u in User.query.filter(User.id.in_(roles.keys())).all()
    } if roles else {}

    members = []
    memberships = []
    for uid, role in roles.items():
        user = users.get(uid)
        if not user:
            continue
        mid = _tid()
        member_id_map[uid] = mid
        members.append({
            'id': mid,
            'fullName': user.full_name or user.email or '',
            'username': (user.email or f'user{uid}').split('@')[0],
            'initials': ((user.first_name or '')[:1] + (user.last_name or '')[:1]).upper()
            or (user.email or 'U')[:2].upper(),
            'email': user.email,
        })
        member_type = 'admin' if role in ('owner', 'admin') else 'normal'
        memberships.append({
            'id': _tid(),
            'idMember': mid,
            'memberType': member_type,
            'unconfirmed': False,
            'deactivated': False,
        })

    labels_out = []
    label_names = dict(TRELLO_LABEL_NAMES)
    for lb in sorted(board.labels, key=lambda x: x.position):
        lid = _tid()
        label_id_map[lb.id] = lid
        color = _hex_to_trello_color(lb.color)
        labels_out.append({
            'id': lid,
            'idBoard': board_tid,
            'name': lb.name or '',
            'color': color,
            'uses': 0,
        })
        if color in label_names and lb.name:
            label_names[color] = lb.name

    lists_out = []
    for lst in sorted(board.lists, key=lambda x: x.position):
        lid = _tid()
        list_id_map[lst.id] = lid
        lists_out.append({
            'id': lid,
            'name': lst.title,
            'closed': bool(lst.archived_at),
            'idBoard': board_tid,
            'pos': float(lst.position) * 65536.0,
            'subscribed': False,
        })

    custom_fields_out = []
    for field in board.custom_fields:
        fid = _tid()
        field_id_map[field.id] = fid
        trello_type = _CF_TYPE_MAP.get(field.field_type, 'text')
        entry: dict[str, Any] = {
            'id': fid,
            'idModel': board_tid,
            'modelType': 'board',
            'name': field.label,
            'pos': float(field.position) * 65536.0,
            'type': trello_type,
            'display': {'cardFront': False},
            'isSuggestedField': False,
        }
        if trello_type == 'list':
            opts = _parse_options(field.options)
            entry['options'] = [
                {'id': _tid(), 'idCustomField': fid, 'value': {'text': opt}, 'pos': float(i) * 16384.0}
                for i, opt in enumerate(opts)
            ]
        custom_fields_out.append(entry)

    checklists_out: list[dict] = []
    cards_out: list[dict] = []

    for lst in sorted(board.lists, key=lambda x: x.position):
        for card in sorted(lst.cards, key=lambda x: x.position):
            cid = _tid()
            card_id_map[card.id] = cid

            # attachments
            attachments = []
            cover_att_tid = None
            for att in card.attachments:
                aid = _tid()
                attach_id_map[att.id] = aid
                url = _attachment_public_url(att)
                is_upload = bool(att.storage_path) and not att.url
                attachments.append({
                    'id': aid,
                    'bytes': att.file_size,
                    'date': _iso(att.created_at),
                    'edgeColor': None,
                    'idMember': member_id_map.get(att.uploaded_by),
                    'isMalicious': False,
                    'isUpload': is_upload,
                    'mimeType': att.mime_type,
                    'name': att.original_filename or att.filename or (att.url or 'Link'),
                    'url': url or att.url or '',
                    'pos': 0,
                    'fileName': att.original_filename or att.filename,
                })
                if card.cover_attachment_id == att.id:
                    cover_att_tid = aid

            # checklists (top-level + idChecklists on card)
            id_checklists = []
            check_item_total = 0
            check_item_done = 0
            for cl in card.checklists:
                clid = _tid()
                id_checklists.append(clid)
                items = []
                for it in cl.items:
                    check_item_total += 1
                    state = 'complete' if it.done else 'incomplete'
                    if it.done:
                        check_item_done += 1
                    items.append({
                        'id': _tid(),
                        'name': it.text,
                        'nameData': {'emoji': {}},
                        'pos': float(it.position) * 16384.0,
                        'state': state,
                        'due': _iso(it.due_date),
                        'dueReminder': None,
                        'idMember': member_id_map.get(it.assignee_id) if it.assignee_id else None,
                        'idChecklist': clid,
                    })
                checklists_out.append({
                    'id': clid,
                    'name': cl.title,
                    'idBoard': board_tid,
                    'idCard': cid,
                    'pos': float(cl.position) * 16384.0,
                    'checkItems': items,
                })

            id_labels = [
                label_id_map[cl.label_id]
                for cl in card.card_labels
                if cl.label_id in label_id_map
            ]
            id_members = [
                member_id_map[a.user_id]
                for a in card.assignees
                if a.user_id in member_id_map
            ]

            # custom field items
            cf_items = []
            for fv in card.field_values:
                fid = field_id_map.get(fv.field_id)
                if not fid:
                    continue
                field = next((f for f in board.custom_fields if f.id == fv.field_id), None)
                if not field:
                    continue
                value: dict[str, Any] = {}
                raw = fv.value
                ft = field.field_type
                if ft == 'checkbox':
                    value = {'checked': 'true' if str(raw).lower() in ('1', 'true', 'yes', 'on') else 'false'}
                elif ft == 'date':
                    value = {'date': str(raw or '')}
                elif ft == 'select':
                    # match option by text
                    matched = None
                    for cf in custom_fields_out:
                        if cf['id'] != fid:
                            continue
                        for opt in cf.get('options') or []:
                            if (opt.get('value') or {}).get('text') == str(raw or ''):
                                matched = opt['id']
                                break
                    cf_items.append({
                        'id': _tid(),
                        'idValue': matched,
                        'idCustomField': fid,
                        'idModel': cid,
                        'modelType': 'card',
                        'value': None if matched else {'text': str(raw or '')},
                    })
                    continue
                else:
                    value = {'text': str(raw or '')}
                cf_items.append({
                    'id': _tid(),
                    'value': value,
                    'idValue': None,
                    'idCustomField': fid,
                    'idModel': cid,
                    'modelType': 'card',
                })

            # also include local card fields as text customFieldItems under ephemeral defs? skip — board templates only

            cards_out.append({
                'id': cid,
                'name': card.title,
                'desc': card.description or '',
                'closed': bool(card.archived_at),
                'due': _iso(card.due_date),
                'dueComplete': bool(card.completed_at),
                'dateCompleted': _iso(card.completed_at),
                'idBoard': board_tid,
                'idList': list_id_map.get(card.list_id),
                'idLabels': id_labels,
                'idMembers': id_members,
                'idChecklists': id_checklists,
                'idAttachmentCover': cover_att_tid,
                'pos': float(card.position) * 65536.0,
                'subscribed': False,
                'attachments': attachments,
                'customFieldItems': cf_items,
                'labels': [
                    next(lb for lb in labels_out if lb['id'] == lid)
                    for lid in id_labels
                    if any(lb['id'] == lid for lb in labels_out)
                ],
                'badges': {
                    'attachments': len(attachments),
                    'checkItems': check_item_total,
                    'checkItemsChecked': check_item_done,
                    'comments': 0,
                    'description': bool(card.description),
                    'due': _iso(card.due_date),
                    'dueComplete': bool(card.completed_at),
                    'votes': len(card.votes),
                },
                # Prismateams extension (ignored by Trello, used by us on re-import)
                'pollText': card.poll_text,
            })

    bg = board.background or 'teal'
    return {
        'id': board_tid,
        'name': board.title,
        'desc': board.description or '',
        'closed': bool(board.closed_at),
        'dateClosed': _iso(board.closed_at),
        'dateLastActivity': _iso(board.updated_at),
        'idOrganization': None,
        'prefs': {
            'permissionLevel': board.visibility or 'private',
            'voting': 'disabled',
            'comments': 'members',
            'invitations': 'members',
            'selfJoin': False,
            'cardCovers': True,
            'background': bg,
            'backgroundColor': None,
            'backgroundImage': None,
        },
        'labelNames': label_names,
        'labels': labels_out,
        'lists': lists_out,
        'cards': cards_out,
        'checklists': checklists_out,
        'members': members,
        'memberships': memberships,
        'customFields': custom_fields_out,
        'actions': [],
        'pluginData': [],
        # Prismateams metadata (harmless for Trello consumers)
        'prismateams': {
            'export_version': EXPORT_VERSION,
            'source_board_id': board.id,
            'visibility': board.visibility,
            'team_name': board.team.name if board.team else None,
            'exported_at': datetime.utcnow().isoformat() + 'Z',
        },
    }


def export_board_json_bytes(board: KanbanBoard) -> tuple[bytes, str]:
    payload = build_trello_board_dict(board)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    safe = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in (board.title or 'board'))[:60]
    return raw, f'{safe or "board"}.json'


def export_board_csv_bytes(board: KanbanBoard) -> tuple[bytes, str]:
    """Trello-style flat CSV (one row per card)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'Card Name',
        'Card Description',
        'Labels',
        'Members',
        'Due Date',
        'Due Complete',
        'List Name',
        'Board Name',
        'Attachment Count',
        'Attachment Links',
        'Checklist Items',
        'Checklist Items Checked',
        'Archived',
    ])
    for lst in sorted(board.lists, key=lambda x: x.position):
        if lst.archived_at:
            continue
        for card in sorted(lst.cards, key=lambda x: x.position):
            if card.archived_at:
                continue
            labels = ', '.join(
                f"{cl.label.name}" if cl.label and cl.label.name else (cl.label.color if cl.label else '')
                for cl in card.card_labels if cl.label
            )
            members = ', '.join(
                (a.user.full_name or a.user.email or '')
                for a in card.assignees if a.user
            )
            att_links = ' '.join(
                filter(None, (_attachment_public_url(a) or a.url or '' for a in card.attachments))
            )
            total = done = 0
            for cl in card.checklists:
                for it in cl.items:
                    total += 1
                    if it.done:
                        done += 1
            writer.writerow([
                card.title,
                card.description or '',
                labels,
                members,
                _iso(card.due_date) or '',
                'true' if card.completed_at else 'false',
                lst.title,
                board.title,
                len(card.attachments),
                att_links,
                total,
                done,
                'true' if card.archived_at else 'false',
            ])
    raw = buf.getvalue().encode('utf-8-sig')
    safe = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in (board.title or 'board'))[:60]
    return raw, f'{safe or "board"}.csv'
