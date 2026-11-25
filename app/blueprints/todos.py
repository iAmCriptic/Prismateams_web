"""ToDos-Modul: Einheitliche Checklisten-Ansicht (Privat, Teams, Public) & Aufgabenpool."""

from datetime import datetime, date, time as dt_time
import pytz
from flask import Blueprint, abort, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.models import (
    Event,
    EventTodoItem,
    EventTodoList,
    KanbanBoard,
    KanbanCard,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanList,
    Team,
    TeamMember,
    TodoItem,
    User,
)
from app.utils.access_control import check_module_access, has_module_access
from app.utils.common import get_system_timezone, is_module_enabled
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.kanban_access import can_edit_board, can_view_board
from app.utils.module_visibility import (
    get_allowed_visibilities,
    user_visibility_teams,
    visibility_allowed,
)

todos_bp = Blueprint('todos', __name__, url_prefix='/todos')


def _local_today() -> date:
    """Heutiges Datum in der konfigurierten Portal-Zeitzone."""
    tz_name = get_system_timezone()
    try:
        tz = pytz.timezone(tz_name)
        return datetime.now(tz).date()
    except Exception:
        return datetime.utcnow().date()


def _serialize_user(user: User | None) -> dict | None:
    if not user:
        return None
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    full_name = f'{first} {last}'.strip() or (user.username or user.email or f'#{user.id}')
    initials = ((first[:1] + last[:1]) or full_name[:2]).upper()
    avatar_url = None
    if getattr(user, 'profile_picture', None):
        try:
            avatar_url = url_for('settings.profile_picture', filename=user.profile_picture)
        except Exception:
            avatar_url = None
    return {
        'id': user.id,
        'name': full_name,
        'initials': initials,
        'avatar_url': avatar_url,
    }


def _due_state(due_date_val: date | None, due_time_val: dt_time | None, is_done: bool, today: date) -> str:
    if is_done:
        return 'done'
    if not due_date_val:
        return 'none'
    if due_date_val < today:
        return 'overdue'
    if due_date_val == today:
        return 'soon'
    return 'future'


def _format_due_label(due_date_val: date | None, due_time_val: dt_time | None, today: date) -> str:
    if not due_date_val:
        return ''
    date_part = due_date_val.strftime('%d.%m.%Y') if due_date_val.year != today.year else due_date_val.strftime('%d.%m.')
    if due_time_val:
        return f"{date_part} {due_time_val.strftime('%H:%M')}"
    return date_part


def _user_team_ids(user: User) -> set[int]:
    if getattr(user, 'is_admin', False):
        return {t.id for t in Team.query.all()}
    return {
        row.team_id
        for row in TeamMember.query.filter_by(user_id=user.id).all()
    }


def _can_access_todo(todo: TodoItem, user: User, user_team_ids: set[int] | None = None) -> bool:
    if getattr(user, 'is_admin', False):
        return True
    if todo.visibility == 'private':
        return todo.created_by_id == user.id or todo.assignee_id == user.id
    if todo.visibility == 'team':
        if user_team_ids is None:
            user_team_ids = _user_team_ids(user)
        return todo.team_id in user_team_ids
    if todo.visibility == 'public':
        return visibility_allowed('todos', 'public')
    return False


def _serialize_todo_item(todo: TodoItem, today: date, can_edit: bool = True) -> dict:
    due_d = todo.due_date
    due_t = todo.due_time
    return {
        'id': todo.id,
        'source': 'todo',
        'title': todo.title,
        'is_completed': bool(todo.is_completed),
        'due_date': due_d.isoformat() if due_d else None,
        'due_time': due_t.strftime('%H:%M') if due_t else None,
        'due_label': _format_due_label(due_d, due_t, today),
        'due_state': _due_state(due_d, due_t, bool(todo.is_completed), today),
        'is_overdue': bool(not todo.is_completed and due_d and due_d < today),
        'is_today': bool(due_d and due_d == today),
        'visibility': todo.visibility,
        'team_id': todo.team_id,
        'team_name': todo.team.name if todo.team else None,
        'assignee': _serialize_user(todo.assignee),
        'assignee_id': todo.assignee_id,
        'created_by_id': todo.created_by_id,
        'can_edit': can_edit,
        'can_delete': can_edit,
        'can_claim': bool(todo.visibility in ('team', 'public') and todo.assignee_id is None and not todo.is_completed),
        'source_label': todo.team.name if todo.visibility == 'team' and todo.team else None,
        'source_url': None,
        'created_at': todo.created_at.isoformat() if todo.created_at else None,
    }


def _safe_url_for(endpoint: str, **values) -> str | None:
    try:
        return url_for(endpoint, **values)
    except RuntimeError:
        return None


def _serialize_kanban_item(item: KanbanChecklistItem, checklist: KanbanChecklist, card: KanbanCard, board: KanbanBoard, today: date, can_edit: bool) -> dict:
    due_dt = item.due_date
    due_d = due_dt.date() if due_dt else None
    due_t = due_dt.time() if (due_dt and (due_dt.hour != 0 or due_dt.minute != 0)) else None
    return {
        'id': item.id,
        'source': 'kanban',
        'title': item.text,
        'is_completed': bool(item.done),
        'due_date': due_d.isoformat() if due_d else None,
        'due_time': due_t.strftime('%H:%M') if due_t else None,
        'due_label': _format_due_label(due_d, due_t, today),
        'due_state': _due_state(due_d, due_t, bool(item.done), today),
        'is_overdue': bool(not item.done and due_d and due_d < today),
        'is_today': bool(due_d and due_d == today),
        'visibility': 'private',
        'team_id': board.team_id,
        'team_name': None,
        'assignee': _serialize_user(item.assignee),
        'assignee_id': item.assignee_id,
        'created_by_id': None,
        'can_edit': can_edit,
        'can_delete': False,
        'can_claim': False,
        'source_label': f'{board.title} · {card.title}',
        'source_url': _safe_url_for('kanban.board', board_id=board.id, card=card.id),
        'created_at': None,
    }


def _serialize_event_item(item: EventTodoItem, todo_list: EventTodoList, event: Event, today: date) -> dict:
    due_d = item.due_date
    due_t = item.due_time
    return {
        'id': item.id,
        'source': 'event',
        'title': item.title,
        'is_completed': bool(item.is_completed),
        'due_date': due_d.isoformat() if due_d else None,
        'due_time': due_t.strftime('%H:%M') if due_t else None,
        'due_label': _format_due_label(due_d, due_t, today),
        'due_state': _due_state(due_d, due_t, bool(item.is_completed), today),
        'is_overdue': bool(not item.is_completed and due_d and due_d < today),
        'is_today': bool(due_d and due_d == today),
        'visibility': 'private',
        'team_id': None,
        'team_name': None,
        'assignee': _serialize_user(item.assigned_to),
        'assignee_id': item.assigned_to_user_id,
        'created_by_id': None,
        'can_edit': True,
        'can_delete': False,
        'can_claim': False,
        'source_label': f'{event.name} · {todo_list.title}',
        'source_url': _safe_url_for('events.view_event', event_id=event.id),
        'created_at': item.created_at.isoformat() if item.created_at else None,
    }


def _sort_key(item: dict):
    """Überfällig zuerst, dann Heute/nächstes Datum, dann ohne Datum."""
    due_d = item.get('due_date') or '9999-12-31'
    due_t = item.get('due_time') or '23:59'
    return (
        1 if item.get('is_completed') else 0,
        due_d,
        due_t,
        (item.get('title') or '').lower(),
    )


def collect_todos(
    user: User,
    section: str = 'private',
    team_id: int | None = None,
    view_mode: str = 'today',
    search_query: str = '',
) -> dict:
    """Sammelt alle ToDos (inkl. Kanban & Events unter Privat) für den gewählten Bereich."""
    today = _local_today()
    user_team_ids = _user_team_ids(user)
    items: list[dict] = []

    if section == 'private':
        # 1) Eigenständige ToDos: Privat selbst erstellt oder mir zugewiesen
        todo_q = (
            TodoItem.query.options(
                joinedload(TodoItem.assignee),
                joinedload(TodoItem.team),
            )
            .filter(
                or_(
                    db.and_(TodoItem.visibility == 'private', TodoItem.created_by_id == user.id),
                    TodoItem.assignee_id == user.id,
                )
            )
        )
        for todo in todo_q.all():
            if todo.visibility == 'team' and todo.team_id not in user_team_ids and not getattr(user, 'is_admin', False):
                continue
            items.append(_serialize_todo_item(todo, today, can_edit=True))

        # 2) Kanban Checklisten-Items auf meine Person
        if is_module_enabled('module_kanban') and has_module_access(user, 'module_kanban'):
            kb_rows = (
                db.session.query(KanbanChecklistItem, KanbanChecklist, KanbanCard, KanbanBoard)
                .join(KanbanChecklist, KanbanChecklistItem.checklist_id == KanbanChecklist.id)
                .join(KanbanCard, KanbanChecklist.card_id == KanbanCard.id)
                .join(KanbanList, KanbanCard.list_id == KanbanList.id)
                .join(KanbanBoard, KanbanList.board_id == KanbanBoard.id)
                .options(joinedload(KanbanChecklistItem.assignee))
                .filter(
                    KanbanChecklistItem.assignee_id == user.id,
                    KanbanBoard.closed_at.is_(None),
                )
                .all()
            )
            for cl_item, checklist, card, board in kb_rows:
                if can_view_board(user, board):
                    items.append(
                        _serialize_kanban_item(
                            cl_item,
                            checklist,
                            card,
                            board,
                            today,
                            can_edit=can_edit_board(user, board),
                        )
                    )

        # 3) Event Checklisten-Items auf meine Person
        if (is_module_enabled('module_events') and has_module_access(user, 'module_events')) or (
            is_module_enabled('module_calendar') and has_module_access(user, 'module_calendar')
        ):
            ev_rows = (
                db.session.query(EventTodoItem, EventTodoList, Event)
                .join(EventTodoList, EventTodoItem.todo_list_id == EventTodoList.id)
                .join(Event, EventTodoList.event_id == Event.id)
                .options(joinedload(EventTodoItem.assigned_to))
                .filter(
                    EventTodoItem.assigned_to_user_id == user.id,
                    Event.is_archived.is_(False),
                )
                .all()
            )
            for ev_item, todo_list, event in ev_rows:
                items.append(_serialize_event_item(ev_item, todo_list, event, today))

    elif section == 'team' and team_id:
        if team_id not in user_team_ids and not getattr(user, 'is_admin', False):
            abort(403)
        todo_q = (
            TodoItem.query.options(
                joinedload(TodoItem.assignee),
                joinedload(TodoItem.team),
            )
            .filter(TodoItem.visibility == 'team', TodoItem.team_id == team_id)
        )
        for todo in todo_q.all():
            items.append(_serialize_todo_item(todo, today, can_edit=True))

    elif section == 'public':
        if not visibility_allowed('todos', 'public'):
            abort(403)
        todo_q = (
            TodoItem.query.options(
                joinedload(TodoItem.assignee),
                joinedload(TodoItem.team),
            )
            .filter(TodoItem.visibility == 'public')
        )
        for todo in todo_q.all():
            can_edit = bool(
                getattr(user, 'is_admin', False)
                or todo.created_by_id == user.id
                or todo.assignee_id == user.id
                or todo.assignee_id is None
            )
            items.append(_serialize_todo_item(todo, today, can_edit=can_edit))

    # Suchfilter anwenden
    q_norm = (search_query or '').strip().lower()
    if q_norm:
        items = [
            it
            for it in items
            if q_norm in (it.get('title') or '').lower()
            or q_norm in (it.get('source_label') or '').lower()
            or q_norm in ((it.get('assignee') or {}).get('name') or '').lower()
        ]

    # Tagesansicht: nur Überfällig + Heute fällig (bzw. heute erledigt)
    if view_mode == 'today':
        today_iso = today.isoformat()
        filtered = []
        for it in items:
            d = it.get('due_date')
            if d and d <= today_iso:
                filtered.append(it)
        items = filtered

    open_items = sorted([it for it in items if not it['is_completed']], key=_sort_key)
    completed_items = sorted([it for it in items if it['is_completed']], key=_sort_key)

    return {
        'open_items': open_items,
        'completed_items': completed_items,
        'today': today.isoformat(),
    }


def collect_dashboard_todos(user: User, limit: int = 12) -> list[dict]:
    """Liefert unerledigte, mir zugewiesene ToDos (Überfällig + Heute) fürs Dashboard-Widget."""
    if not is_module_enabled('module_todos') or not has_module_access(user, 'module_todos'):
        return []
    data = collect_todos(user, section='private', view_mode='today', search_query='')
    return data['open_items'][:limit]


def _assignable_users_for_scope(user: User, section: str, team_id: int | None) -> list[dict]:
    if section == 'team' and team_id:
        members = (
            User.query.join(TeamMember, TeamMember.user_id == User.id)
            .filter(TeamMember.team_id == team_id, User.is_active.is_(True), ~User.is_guest)
            .order_by(User.first_name, User.last_name)
            .all()
        )
        return [_serialize_user(u) for u in members]
    if section == 'public':
        users = (
            User.query.filter(
                User.is_active.is_(True),
                ~User.is_guest,
                User.email != 'anonymous@system.local',
            )
            .order_by(User.first_name, User.last_name)
            .all()
        )
        return [_serialize_user(u) for u in users]
    return [_serialize_user(user)]


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return datetime.strptime(val.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_time(val: str | None) -> dt_time | None:
    if not val:
        return None
    try:
        return datetime.strptime(val.strip(), '%H:%M').time()
    except ValueError:
        return None


@todos_bp.route('/')
@login_required
@check_module_access('module_todos')
def index():
    if not is_module_enabled('module_todos'):
        abort(404)

    allowed_vis = get_allowed_visibilities('todos')
    teams = user_visibility_teams(current_user, 'todos') if 'team' in allowed_vis else []

    section = (request.args.get('section') or 'private').strip()
    team_id = request.args.get('team_id', type=int)
    view_mode = (request.args.get('view') or 'today').strip()
    if view_mode not in ('today', 'all'):
        view_mode = 'today'
    search_query = (request.args.get('q') or '').strip()

    if section == 'team':
        if 'team' not in allowed_vis or not teams:
            section = 'private'
            team_id = None
        elif not team_id:
            team_id = teams[0].id
    elif section == 'public':
        if 'public' not in allowed_vis:
            section = 'private'
            team_id = None
    else:
        section = 'private'
        team_id = None

    data = collect_todos(
        current_user,
        section=section,
        team_id=team_id,
        view_mode=view_mode,
        search_query=search_query,
    )
    assignable = _assignable_users_for_scope(current_user, section, team_id)

    active_team = next((t for t in teams if t.id == team_id), None) if team_id else None
    active_nav = f'team-{team_id}' if section == 'team' and team_id else section

    return render_template(
        'todos/index.html',
        section=section,
        team_id=team_id,
        active_team=active_team,
        active_nav=active_nav,
        view_mode=view_mode,
        search_query=search_query,
        teams=teams,
        allowed_visibilities=allowed_vis,
        open_items=data['open_items'],
        completed_items=data['completed_items'],
        assignable_users=assignable,
        today_iso=data['today'],
    )


@todos_bp.route('/api/items', methods=['GET'])
@login_required
@check_module_access('module_todos')
def api_list_items():
    section = (request.args.get('section') or 'private').strip()
    team_id = request.args.get('team_id', type=int)
    view_mode = (request.args.get('view') or 'today').strip()
    if view_mode not in ('today', 'all'):
        view_mode = 'today'
    search_query = (request.args.get('q') or '').strip()

    data = collect_todos(
        current_user,
        section=section,
        team_id=team_id,
        view_mode=view_mode,
        search_query=search_query,
    )
    return jsonify(data)


@todos_bp.route('/api/items', methods=['POST'])
@login_required
@check_module_access('module_todos')
def api_create_item():
    payload = request.get_json(silent=True) or {}
    title = (payload.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400

    visibility = (payload.get('visibility') or 'private').strip()
    if visibility not in ('private', 'team', 'public'):
        visibility = 'private'
    if not visibility_allowed('todos', visibility):
        return jsonify({'error': 'Visibility not allowed'}), 403

    team_id = payload.get('team_id')
    if visibility == 'team':
        try:
            team_id = int(team_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Team is required'}), 400
        if team_id not in _user_team_ids(current_user) and not getattr(current_user, 'is_admin', False):
            return jsonify({'error': 'Forbidden'}), 403
    else:
        team_id = None

    assignee_id = payload.get('assignee_id')
    if visibility == 'private':
        assignee_id = current_user.id
    elif assignee_id:
        try:
            assignee_id = int(assignee_id)
        except (TypeError, ValueError):
            assignee_id = None
    else:
        assignee_id = None

    due_date_val = _parse_date(payload.get('due_date'))
    due_time_val = _parse_time(payload.get('due_time')) if due_date_val else None

    todo = TodoItem(
        title=title[:500],
        visibility=visibility,
        team_id=team_id,
        created_by_id=current_user.id,
        assignee_id=assignee_id,
        due_date=due_date_val,
        due_time=due_time_val,
    )
    db.session.add(todo)
    db.session.commit()

    if todo.assignee_id:
        emit_dashboard_update(todo.assignee_id, 'todos', {})
    emit_dashboard_update(current_user.id, 'todos', {})

    today = _local_today()
    return jsonify({'item': _serialize_todo_item(todo, today, can_edit=True)}), 201


@todos_bp.route('/api/items/<string:source>/<int:item_id>', methods=['PATCH'])
@login_required
@check_module_access('module_todos')
def api_update_item(source: str, item_id: int):
    payload = request.get_json(silent=True) or {}
    today = _local_today()

    if source == 'todo':
        todo = db.session.get(TodoItem, item_id)
        if not todo:
            abort(404)
        if not _can_access_todo(todo, current_user):
            abort(403)

        prev_assignee_id = todo.assignee_id

        if 'is_completed' in payload:
            done = bool(payload['is_completed'])
            todo.is_completed = done
            todo.completed_at = datetime.utcnow() if done else None
            todo.completed_by_id = current_user.id if done else None

        if 'title' in payload:
            new_title = (payload.get('title') or '').strip()
            if not new_title:
                return jsonify({'error': 'Title cannot be empty'}), 400
            todo.title = new_title[:500]

        if 'due_date' in payload:
            todo.due_date = _parse_date(payload.get('due_date'))
            if not todo.due_date:
                todo.due_time = None

        if 'due_time' in payload:
            todo.due_time = _parse_time(payload.get('due_time')) if todo.due_date else None

        if 'assignee_id' in payload and todo.visibility != 'private':
            raw_aid = payload.get('assignee_id')
            if raw_aid in (None, '', 0):
                todo.assignee_id = None
            else:
                try:
                    todo.assignee_id = int(raw_aid)
                except (TypeError, ValueError):
                    pass

        db.session.commit()
        for uid in {current_user.id, todo.created_by_id, todo.assignee_id, prev_assignee_id}:
            if uid:
                emit_dashboard_update(uid, 'todos', {})

        return jsonify({'item': _serialize_todo_item(todo, today, can_edit=True)})

    if source == 'kanban':
        if not is_module_enabled('module_kanban') or not has_module_access(current_user, 'module_kanban'):
            abort(403)
        cl_item = db.session.get(KanbanChecklistItem, item_id)
        if not cl_item:
            abort(404)
        checklist = cl_item.checklist
        card = checklist.card
        board = card.list.board
        if not can_edit_board(current_user, board):
            abort(403)
        if 'is_completed' in payload:
            cl_item.done = bool(payload['is_completed'])
        db.session.commit()
        try:
            from app.blueprints.sse import emit_kanban_update
            emit_kanban_update(board.id, {'type': 'card_updated', 'card_id': card.id})
        except Exception:
            pass
        if cl_item.assignee_id:
            emit_dashboard_update(cl_item.assignee_id, 'todos', {})
        return jsonify({
            'item': _serialize_kanban_item(cl_item, checklist, card, board, today, can_edit=True)
        })

    if source == 'event':
        ev_item = db.session.get(EventTodoItem, item_id)
        if not ev_item:
            abort(404)
        todo_list = ev_item.todo_list
        event = todo_list.event
        if 'is_completed' in payload:
            done = bool(payload['is_completed'])
            ev_item.is_completed = done
            ev_item.completed_at = datetime.utcnow() if done else None
            ev_item.completed_by_id = current_user.id if done else None
        db.session.commit()
        if ev_item.assigned_to_user_id:
            emit_dashboard_update(ev_item.assigned_to_user_id, 'todos', {})
        return jsonify({'item': _serialize_event_item(ev_item, todo_list, event, today)})

    abort(404)


@todos_bp.route('/api/items/todo/<int:item_id>/claim', methods=['POST'])
@login_required
@check_module_access('module_todos')
def api_claim_item(item_id: int):
    todo = db.session.get(TodoItem, item_id)
    if not todo:
        abort(404)
    if todo.visibility not in ('team', 'public') or not _can_access_todo(todo, current_user):
        abort(403)

    todo.assignee_id = current_user.id
    db.session.commit()
    emit_dashboard_update(current_user.id, 'todos', {})

    today = _local_today()
    return jsonify({'item': _serialize_todo_item(todo, today, can_edit=True)})


@todos_bp.route('/api/items/todo/<int:item_id>', methods=['DELETE'])
@login_required
@check_module_access('module_todos')
def api_delete_item(item_id: int):
    todo = db.session.get(TodoItem, item_id)
    if not todo:
        abort(404)
    if not _can_access_todo(todo, current_user):
        abort(403)

    affected_users = {current_user.id, todo.created_by_id, todo.assignee_id}
    db.session.delete(todo)
    db.session.commit()
    for uid in affected_users:
        if uid:
            emit_dashboard_update(uid, 'todos', {})

    return jsonify({'deleted': True})
