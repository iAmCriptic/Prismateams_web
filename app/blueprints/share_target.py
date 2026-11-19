"""PWA Web Share Target blueprint (files, links, text -> Files, Kanban, Events, Chat)."""

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from app import db
from app.models.event import Event, EventLink, EventTodoItem, EventTodoList
from app.models.file import Folder
from app.models.kanban import KanbanBoard
from app.utils.access_control import check_module_access, has_module_access
from app.utils.chat_nav import build_chat_nav_items
from app.utils.kanban_access import accessible_boards_query, can_edit_board

share_target_bp = Blueprint('share_target', __name__)


def _can_edit_event(user, event_obj: Event) -> bool:
    return bool(
        getattr(user, 'is_admin', False)
        or getattr(user, 'has_full_access', False)
        or event_obj.owner_id == user.id
        or event_obj.created_by == user.id
    )


@share_target_bp.route('/share-target', methods=['GET', 'POST'])
@login_required
def index():
    """Landing page for PWA Web Share Target payloads."""
    is_guest = bool(getattr(current_user, 'is_guest', False))
    can_files = bool(has_module_access(current_user, 'module_files') and not is_guest)
    can_kanban = bool(has_module_access(current_user, 'module_kanban'))
    can_events = bool(has_module_access(current_user, 'module_events') and not is_guest)
    can_chat = bool(has_module_access(current_user, 'module_chat'))

    source = request.form if request.method == 'POST' else request.args
    fallback_title = (source.get('title') or '').strip()
    fallback_text = (source.get('text') or '').strip()
    fallback_url = (source.get('url') or '').strip()

    return render_template(
        'share_target/index.html',
        can_files=can_files,
        can_kanban=can_kanban,
        can_events=can_events,
        can_chat=can_chat,
        share_id=(request.args.get('id') or '').strip(),
        has_error=bool(request.args.get('error')),
        fallback_title=fallback_title,
        fallback_text=fallback_text,
        fallback_url=fallback_url,
    )


@share_target_bp.route('/share-target/api/kanban-boards', methods=['GET'])
@login_required
@check_module_access('module_kanban')
def api_kanban_boards():
    """Return editable Kanban boards for the share-target destination picker."""
    boards = (
        accessible_boards_query(current_user, include_closed=False)
        .options(joinedload(KanbanBoard.team))
        .order_by(KanbanBoard.updated_at.desc())
        .all()
    )
    items = []
    for board in boards:
        if not can_edit_board(current_user, board):
            continue
        items.append({
            'id': board.id,
            'public_id': board.public_id,
            'title': board.title,
            'visibility': board.visibility,
            'team_name': board.team.name if board.team else None,
        })
    return jsonify({'success': True, 'boards': items})


@share_target_bp.route('/share-target/api/events', methods=['GET'])
@login_required
@check_module_access('module_events')
def api_events():
    """Return editable non-archived events for the share-target destination picker."""
    events = (
        Event.query
        .filter(Event.is_archived.is_(False))
        .options(joinedload(Event.folder), joinedload(Event.todo_lists))
        .order_by(Event.start_date.desc(), Event.id.desc())
        .all()
    )
    items = []
    for ev in events:
        if not _can_edit_event(current_user, ev):
            continue
        items.append({
            'id': ev.id,
            'title': ev.title,
            'start_date': ev.start_date.isoformat() if ev.start_date else None,
            'folder_id': ev.folder_id,
            'folder_name': ev.folder.name if ev.folder else None,
            'todo_lists': [
                {'id': tl.id, 'title': tl.title}
                for tl in (ev.todo_lists or [])
            ],
        })
    return jsonify({'success': True, 'events': items})


@share_target_bp.route('/share-target/api/events/<int:event_id>/ensure-folder', methods=['POST'])
@login_required
@check_module_access('module_events')
def api_event_ensure_folder(event_id):
    """Ensure the event has a linked folder (creating one if needed) for file uploads."""
    if not has_module_access(current_user, 'module_files') or getattr(current_user, 'is_guest', False):
        return jsonify({'success': False, 'error': 'Kein Zugriff auf das Dateien-Modul.'}), 403

    event_obj = Event.query.get_or_404(event_id)
    if not _can_edit_event(current_user, event_obj):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    if event_obj.folder_id and event_obj.folder:
        return jsonify({
            'success': True,
            'folder_id': event_obj.folder_id,
            'folder_name': event_obj.folder.name,
            'view': 'public' if not event_obj.folder.is_private else 'ablage',
        })

    folder_name = (event_obj.title or f'Veranstaltung #{event_obj.id}')[:100].strip()
    folder = Folder(
        name=folder_name,
        owner_id=current_user.id,
        is_private=False,
    )
    db.session.add(folder)
    db.session.flush()
    event_obj.folder_id = folder.id
    db.session.commit()

    return jsonify({
        'success': True,
        'folder_id': folder.id,
        'folder_name': folder.name,
        'view': 'public',
    })


@share_target_bp.route('/share-target/api/events/<int:event_id>/add', methods=['POST'])
@login_required
@check_module_access('module_events')
def api_event_add(event_id):
    """Add a shared link and/or text (as todo item) to an event."""
    event_obj = Event.query.get_or_404(event_id)
    if not _can_edit_event(current_user, event_obj):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    link_url = (data.get('link_url') or '').strip()
    link_title = (data.get('link_title') or '').strip()
    todo_text = (data.get('todo_text') or '').strip()
    raw_list_id = data.get('todo_list_id')

    if link_url:
        if not (link_url.startswith('http://') or link_url.startswith('https://') or link_url.startswith('mailto:')):
            link_url = 'https://' + link_url
        db.session.add(EventLink(
            event_id=event_obj.id,
            title=(link_title or link_url)[:200],
            url=link_url[:500],
        ))

    if todo_text:
        target_list = None
        if raw_list_id:
            try:
                target_list = EventTodoList.query.filter_by(
                    id=int(raw_list_id),
                    event_id=event_obj.id,
                ).first()
            except (TypeError, ValueError):
                target_list = None
        if not target_list:
            target_list = EventTodoList.query.filter_by(event_id=event_obj.id).first()
        if not target_list:
            target_list = EventTodoList(
                event_id=event_obj.id,
                title='Aufgaben',
                created_by=current_user.id,
            )
            db.session.add(target_list)
            db.session.flush()

        max_pos = (
            db.session.query(db.func.max(EventTodoItem.position))
            .filter_by(todo_list_id=target_list.id)
            .scalar()
            or 0
        )
        db.session.add(EventTodoItem(
            todo_list_id=target_list.id,
            title=todo_text[:300],
            position=max_pos + 1,
        ))

    db.session.commit()
    return jsonify({
        'success': True,
        'event_url': url_for('events.view_event', event_id=event_obj.id),
    })


@share_target_bp.route('/share-target/api/chats', methods=['GET'])
@login_required
@check_module_access('module_chat')
def api_chats():
    """Return chats/channels the current user can send messages/files to."""
    nav_items = build_chat_nav_items(current_user)
    chats = []
    for item in nav_items:
        chat = item['chat']
        chats.append({
            'id': chat.id,
            'nav_id': item['nav_id'],
            'name': item['display_name'],
            'is_direct': bool(chat.is_direct),
            'is_team_chat': bool(item.get('is_team_chat')),
        })
    return jsonify({'success': True, 'chats': chats})
