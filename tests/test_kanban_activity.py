import pytest
from app import db
from app.models.kanban import KanbanBoard, KanbanActivity
from app.models.user import User


@pytest.fixture
def kanban_user_and_board(app):
    user = User(
        email='kanbantest@example.com',
        first_name='Kanban',
        last_name='Tester',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()

    board = KanbanBoard(
        title='Activity Test Board',
        created_by=user.id,
        visibility='organization',
    )
    db.session.add(board)
    db.session.commit()

    act = KanbanActivity(
        board_id=board.id,
        user_id=user.id,
        action='board_created',
        detail='Activity Test Board',
    )
    db.session.add(act)
    db.session.commit()

    return user, board


def _login(client, email='kanbantest@example.com', password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_kanban_board_activity_api(client, kanban_user_and_board):
    user, board = kanban_user_and_board
    login_resp = _login(client)
    assert login_resp.status_code == 200

    resp = client.get(f'/kanban/api/boards/{board.id}/activity')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'activities' in data
    assert len(data['activities']) >= 1
    item = data['activities'][0]
    assert item['action'] == 'board_created'
    assert item['action_label'] == 'Board erstellt'
    assert item['detail'] == 'Activity Test Board'
    assert item['user']['id'] == user.id

