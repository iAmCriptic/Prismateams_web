"""Tests für das ToDos-Modul und das Dashboard-Widget."""

from datetime import date, datetime, timedelta

from app import db
from app.blueprints.todos import collect_dashboard_todos, collect_todos
from app.models import (
    Event,
    EventTodoItem,
    EventTodoList,
    KanbanBoard,
    KanbanCard,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanList,
    SystemSettings,
    Team,
    TeamMember,
    TodoItem,
    User,
)


def _create_user(email: str, label: str, is_admin: bool = False) -> User:
    u = User(
        email=email,
        first_name='Test',
        last_name=label,
        is_active=True,
        is_email_confirmed=True,
        is_admin=is_admin,
        has_full_access=True,
    )
    u.set_password('Secret123!@#')
    db.session.add(u)
    db.session.commit()
    return u


def _enable_modules(*keys: str):
    for key in keys:
        row = SystemSettings.query.filter_by(key=key).first()
        if not row:
            row = SystemSettings(key=key, value='true')
            db.session.add(row)
        else:
            row.value = 'true'
    db.session.commit()


def _login(client, user: User):
    res = client.post('/login', data={'email': user.email, 'password': 'Secret123!@#'}, follow_redirects=False)
    assert res.status_code in (200, 302)


def test_todos_private_today_and_all_views(app, client):
    _enable_modules('module_todos')
    user = _create_user('u1@example.com', 'u1')
    _login(client, user)

    today = date.today()
    yesterday = today - timedelta(days=1)
    next_week = today + timedelta(days=7)

    t_overdue = TodoItem(title='Überfällig', visibility='private', created_by_id=user.id, assignee_id=user.id, due_date=yesterday)
    t_today = TodoItem(title='Heute fällig', visibility='private', created_by_id=user.id, assignee_id=user.id, due_date=today)
    t_future = TodoItem(title='Nächste Woche', visibility='private', created_by_id=user.id, assignee_id=user.id, due_date=next_week)
    t_nodate = TodoItem(title='Ohne Datum', visibility='private', created_by_id=user.id, assignee_id=user.id, due_date=None)
    db.session.add_all([t_overdue, t_today, t_future, t_nodate])
    db.session.commit()

    res_today = client.get('/todos/api/items?section=private&view=today')
    assert res_today.status_code == 200
    titles_today = [it['title'] for it in res_today.get_json()['open_items']]
    assert titles_today == ['Überfällig', 'Heute fällig']

    res_all = client.get('/todos/api/items?section=private&view=all')
    assert res_all.status_code == 200
    titles_all = [it['title'] for it in res_all.get_json()['open_items']]
    assert set(titles_all) == {'Überfällig', 'Heute fällig', 'Nächste Woche', 'Ohne Datum'}


def test_todos_team_pool_and_claim(app, client):
    _enable_modules('module_todos')
    u1 = _create_user('pool1@example.com', 'pool1')
    u2 = _create_user('pool2@example.com', 'pool2')
    team = Team(name='Technik')
    db.session.add(team)
    db.session.flush()
    db.session.add_all([
        TeamMember(team_id=team.id, user_id=u1.id),
        TeamMember(team_id=team.id, user_id=u2.id),
    ])
    db.session.commit()

    _login(client, u1)
    res_create = client.post('/todos/api/items', json={
        'title': 'Kabel aufrollen',
        'visibility': 'team',
        'team_id': team.id,
    })
    assert res_create.status_code == 201
    item_id = res_create.get_json()['item']['id']
    assert res_create.get_json()['item']['can_claim'] is True
    assert res_create.get_json()['item']['due_date'] is None

    # u2 übernimmt aus dem Pool
    client.post('/logout')
    _login(client, u2)
    res_claim = client.post(f'/todos/api/items/todo/{item_id}/claim', json={})
    assert res_claim.status_code == 200
    assert res_claim.get_json()['item']['assignee_id'] == u2.id
    assert res_claim.get_json()['item']['can_claim'] is False

    # Bleibt im Team sichtbar und erscheint bei u2 unter Privat
    team_data = collect_todos(u2, section='team', team_id=team.id, view_mode='all')
    assert any(it['id'] == item_id for it in team_data['open_items'])

    priv_data = collect_todos(u2, section='private', view_mode='all')
    assert any(it['id'] == item_id and it['source'] == 'todo' for it in priv_data['open_items'])


def test_kanban_and_event_checklists_sync_and_dashboard_widget(app, client):
    _enable_modules('module_todos', 'module_kanban', 'module_events', 'module_calendar')
    user = _create_user('sync@example.com', 'sync')
    _login(client, user)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Kanban Checklist Item auf user zugewiesen (heute)
    board = KanbanBoard(title='Orga', visibility='private', created_by=user.id)
    db.session.add(board)
    db.session.flush()
    klist = KanbanList(board_id=board.id, title='ToDo', position=0)
    db.session.add(klist)
    db.session.flush()
    card = KanbanCard(list_id=klist.id, title='Bühne', position=0, created_by=user.id)
    db.session.add(card)
    db.session.flush()
    cl = KanbanChecklist(card_id=card.id, title='Check', position=0)
    db.session.add(cl)
    db.session.flush()
    kb_item = KanbanChecklistItem(
        checklist_id=cl.id,
        text='Mikrofone testen',
        done=False,
        position=0,
        due_date=datetime.combine(today, datetime.min.time()),
        assignee_id=user.id,
    )
    db.session.add(kb_item)

    # Event Todo Item auf user zugewiesen (überfällig)
    ev = Event(name='Sommerfest', owner_id=user.id, created_by=user.id)
    db.session.add(ev)
    db.session.flush()
    ev_list = EventTodoList(event_id=ev.id, title='Aufbau', created_by=user.id)
    db.session.add(ev_list)
    db.session.flush()
    ev_item = EventTodoItem(
        todo_list_id=ev_list.id,
        title='Stromkabel legen',
        is_completed=False,
        assigned_to_user_id=user.id,
        due_date=yesterday,
    )
    db.session.add(ev_item)
    db.session.commit()

    # Dashboard Widget zeigt beide unerledigten Aufgaben
    dash_items = collect_dashboard_todos(user)
    titles = [it['title'] for it in dash_items]
    assert 'Stromkabel legen' in titles
    assert 'Mikrofone testen' in titles

    # Über ToDos API abhaken -> Live-Sync zu Kanban & Event
    res_kb = client.patch(f'/todos/api/items/kanban/{kb_item.id}', json={'is_completed': True})
    assert res_kb.status_code == 200
    db.session.refresh(kb_item)
    assert kb_item.done is True

    res_ev = client.patch(f'/todos/api/items/event/{ev_item.id}', json={'is_completed': True})
    assert res_ev.status_code == 200
    db.session.refresh(ev_item)
    assert ev_item.is_completed is True

    # Nach Abhaken nicht mehr im Dashboard-Widget
    assert collect_dashboard_todos(user) == []


def test_todos_page_renders(app, client):
    _enable_modules('module_todos')
    user = _create_user('page@example.com', 'page')
    _login(client, user)

    res = client.get('/todos/')
    assert res.status_code == 200
