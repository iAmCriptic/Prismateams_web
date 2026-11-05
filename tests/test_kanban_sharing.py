import pytest
from app import db
from app.models.kanban import KanbanBoard, KanbanBoardMember
from app.models.user import User
from app.models.team import Team, TeamMember


@pytest.fixture
def kanban_users_and_boards(app):
    user1 = User(
        email='owner@example.com',
        first_name='Owner',
        last_name='User',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user1.set_password('Password123!@#')

    user2 = User(
        email='collaborator@example.com',
        first_name='Collab',
        last_name='User',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user2.set_password('Password123!@#')

    db.session.add_all([user1, user2])
    db.session.commit()

    private_board = KanbanBoard(
        title='Private Project Board',
        created_by=user1.id,
        visibility='private',
    )
    db.session.add(private_board)
    db.session.flush()

    db.session.add(KanbanBoardMember(board_id=private_board.id, user_id=user1.id, role='owner'))

    team = Team(name='Test Team', leader_id=user1.id)
    db.session.add(team)
    db.session.flush()

    team_board = KanbanBoard(
        title='Team Project Board',
        created_by=user1.id,
        visibility='team',
        team_id=team.id,
    )
    db.session.add(team_board)
    db.session.flush()

    db.session.add(KanbanBoardMember(board_id=team_board.id, user_id=user1.id, role='owner'))
    db.session.commit()

    return user1, user2, private_board, team_board, team


def _login(client, email, password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_candidate_users_and_sharing_private_board(client, kanban_users_and_boards):
    user1, user2, private_board, team_board, team = kanban_users_and_boards

    # Log in as board owner
    _login(client, user1.email)

    # 1. Fetch candidate users - previously crashed with AttributeError: 'User' object has no attribute 'username'
    resp = client.get(f'/kanban/api/boards/{private_board.id}/candidate_users')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'users' in data
    user_ids = [u['id'] for u in data['users']]
    assert user2.id in user_ids

    # 2. Share private board with user2
    share_resp = client.post(
        f'/kanban/api/boards/{private_board.id}/members',
        json={'user_id': user2.id, 'role': 'member'},
    )
    assert share_resp.status_code == 200
    share_data = share_resp.get_json()
    assert share_data.get('success') is True
    member_ids = [m['id'] for m in share_data.get('members', [])]
    assert user2.id in member_ids

    # 3. Log out and log in as user2
    client.get('/logout', follow_redirects=True)
    _login(client, user2.email)

    # User2 should now be able to view the private board
    view_resp = client.get(f'/kanban/board/{private_board.id}')
    assert view_resp.status_code == 200

    # User2 should see members
    members_resp = client.get(f'/kanban/api/boards/{private_board.id}/members')
    assert members_resp.status_code == 200


def test_sharing_team_board(client, kanban_users_and_boards):
    user1, user2, private_board, team_board, team = kanban_users_and_boards

    _login(client, user1.email)

    # Candidate users for team board
    resp = client.get(f'/kanban/api/boards/{team_board.id}/candidate_users')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(u['id'] == user2.id for u in data['users'])

    # Share team board with user2 (who is not in team)
    share_resp = client.post(
        f'/kanban/api/boards/{team_board.id}/members',
        json={'user_id': user2.id, 'role': 'member'},
    )
    assert share_resp.status_code == 200

    # Log out and log in as user2
    client.get('/logout', follow_redirects=True)
    _login(client, user2.email)

    # User2 should now be able to view the team board
    view_resp = client.get(f'/kanban/board/{team_board.id}')
    assert view_resp.status_code == 200
