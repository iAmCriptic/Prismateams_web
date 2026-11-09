import pytest
from app import db
from app.models.kanban import KanbanBoard, KanbanBoardMember, KanbanList, KanbanCard
from app.models.user import User


@pytest.fixture
def kanban_search_data(app):
    user = User(
        email='search_user@example.com',
        first_name='Search',
        last_name='User',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()

    board_alpha = KanbanBoard(
        title='Alpha Roadmap Board',
        created_by=user.id,
        visibility='private',
    )
    board_beta = KanbanBoard(
        title='Beta Testing Board',
        created_by=user.id,
        visibility='private',
    )
    db.session.add_all([board_alpha, board_beta])
    db.session.flush()

    db.session.add_all([
        KanbanBoardMember(board_id=board_alpha.id, user_id=user.id, role='owner'),
        KanbanBoardMember(board_id=board_beta.id, user_id=user.id, role='owner'),
    ])

    # Lists and cards on board_alpha
    list_todo = KanbanList(board_id=board_alpha.id, title='To Do List', position=0)
    list_done = KanbanList(board_id=board_alpha.id, title='Done Sprint 4', position=1)
    db.session.add_all([list_todo, list_done])
    db.session.flush()

    card1 = KanbanCard(list_id=list_todo.id, title='Design Homepage Layout', position=0, created_by=user.id)
    card2 = KanbanCard(list_id=list_done.id, title='Setup Database Schema', position=0, created_by=user.id)
    db.session.add_all([card1, card2])
    db.session.commit()

    return {
        'user': user,
        'board_alpha': board_alpha,
        'board_beta': board_beta,
        'list_todo': list_todo,
        'list_done': list_done,
        'card1': card1,
        'card2': card2,
    }


def _login(client, email, password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_kanban_index_search(client, kanban_search_data):
    user = kanban_search_data['user']
    _login(client, user.email)

    # Search for Alpha
    resp = client.get('/kanban/?q=Alpha')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Alpha Roadmap Board' in html
    assert 'Beta Testing Board' not in html

    # Search for Beta
    resp = client.get('/kanban/?q=Beta')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Beta Testing Board' in html
    assert 'Alpha Roadmap Board' not in html


def test_kanban_board_filter_cards_and_lists(client, kanban_search_data):
    user = kanban_search_data['user']
    board = kanban_search_data['board_alpha']
    card1 = kanban_search_data['card1']
    card2 = kanban_search_data['card2']
    list_done = kanban_search_data['list_done']
    list_todo = kanban_search_data['list_todo']

    _login(client, user.email)

    # Search by card title "Homepage"
    resp = client.post(f'/kanban/api/boards/{board.id}/filter', json={'q': 'Homepage'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert card1.id in data['card_ids']
    assert card2.id not in data['card_ids']
    assert list_todo.id in data['list_ids']

    # Search by list title "Sprint 4"
    resp = client.post(f'/kanban/api/boards/{board.id}/filter', json={'q': 'Sprint 4'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert list_done.id in data['list_ids']
    assert card2.id in data['card_ids']
    assert card1.id not in data['card_ids']
