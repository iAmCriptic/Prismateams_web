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
    client.post('/logout', follow_redirects=True)
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
    client.post('/logout', follow_redirects=True)
    _login(client, user2.email)

    # User2 should now be able to view the team board
    view_resp = client.get(f'/kanban/board/{team_board.id}')
    assert view_resp.status_code == 200

    # User2 is an invited member (not in team), so user2 CANNOT manage the board
    patch_resp = client.patch(
        f'/kanban/api/boards/{team_board.id}',
        json={'background': 'coral'},
    )
    assert patch_resp.status_code == 403


def test_team_member_can_manage_team_board(client, app, kanban_users_and_boards):
    user1, user2, private_board, team_board, team = kanban_users_and_boards

    # Add user3 to the team
    with app.app_context():
        user3 = User(
            email='team_member@example.com',
            first_name='Team',
            last_name='Member',
            is_active=True,
            is_admin=False,
            has_full_access=True,
            is_email_confirmed=True,
        )
        user3.set_password('Password123!@#')
        db.session.add(user3)
        db.session.flush()

        db.session.add(TeamMember(team_id=team.id, user_id=user3.id))
        db.session.commit()
        user3_id = user3.id
        user3_email = user3.email

    _login(client, user3_email)

    # Team member CAN view team board
    view_resp = client.get(f'/kanban/board/{team_board.id}')
    assert view_resp.status_code == 200

    # Team member CAN manage team board (e.g. change background)
    patch_resp = client.patch(
        f'/kanban/api/boards/{team_board.id}',
        json={'background': 'slate'},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.get_json().get('board', {}).get('background') == 'slate'


def test_public_board_permissions(client, app, kanban_users_and_boards):
    user1, user2, private_board, team_board, team = kanban_users_and_boards

    with app.app_context():
        public_board = KanbanBoard(
            title='Public Company Board',
            created_by=user1.id,
            visibility='public',
        )
        db.session.add(public_board)
        db.session.flush()

        user4 = User(
            email='random_user@example.com',
            first_name='Random',
            last_name='PortalUser',
            is_active=True,
            is_admin=False,
            has_full_access=True,
            is_email_confirmed=True,
        )
        user4.set_password('Password123!@#')
        db.session.add(user4)
        db.session.commit()
        pub_id = public_board.id
        u4_id = user4.id
        u4_email = user4.email

    # User2 is not invited to public board: as a portal user, user2 CAN manage (change color, invite)
    _login(client, user2.email)
    view_resp = client.get(f'/kanban/board/{pub_id}')
    assert view_resp.status_code == 200

    patch_resp = client.patch(
        f'/kanban/api/boards/{pub_id}',
        json={'background': 'emerald'},
    )
    assert patch_resp.status_code == 200

    # User2 invites user4 as a restricted 'member'
    share_resp = client.post(
        f'/kanban/api/boards/{pub_id}/members',
        json={'user_id': u4_id, 'role': 'member'},
    )
    assert share_resp.status_code == 200

    # Log in as user4 (who was explicitly invited with role 'member')
    client.post('/logout', follow_redirects=True)
    _login(client, u4_email)

    # user4 can view public board
    v4 = client.get(f'/kanban/board/{pub_id}')
    assert v4.status_code == 200

    # user4 is an invited member and CANNOT manage (cannot change background)
    p4 = client.patch(
        f'/kanban/api/boards/{pub_id}',
        json={'background': 'ocean'},
    )
    assert p4.status_code == 403


def test_board_security_enumeration_protection(client, app, kanban_users_and_boards):
    user1, user2, private_board, team, team_board = kanban_users_and_boards

    # Verify private_board has a non-sequential public_id
    assert private_board.public_id is not None
    assert len(private_board.public_id) >= 12

    # User2 logs in (has no access to private_board)
    _login(client, user2.email)

    # 1. Accessing private board by numeric id or public_id gives 404 (no existence disclosure, no 403, no 302)
    resp = client.get(f'/kanban/board/{private_board.id}')
    assert resp.status_code == 404

    resp_public = client.get(f'/kanban/board/{private_board.public_id}')
    assert resp_public.status_code == 404

    resp_api = client.get(f'/kanban/api/boards/{private_board.id}')
    assert resp_api.status_code == 404

    resp_api_pub = client.get(f'/kanban/api/boards/{private_board.public_id}')
    assert resp_api_pub.status_code == 404

    # 2. Non-existent board gives 404 (indistinguishable from unauthorized board)
    resp_fake = client.get('/kanban/board/nonexistent999999')
    assert resp_fake.status_code == 404

    # 3. User1 (authorized owner) logs in
    client.post('/logout', follow_redirects=True)
    _login(client, user1.email)

    # Authorized user can access by public_id
    resp_owner_pub = client.get(f'/kanban/board/{private_board.public_id}')
    assert resp_owner_pub.status_code == 200

    # Authorized user can also access by legacy numeric id
    resp_owner_num = client.get(f'/kanban/board/{private_board.id}')
    assert resp_owner_num.status_code == 200


