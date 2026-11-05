import pytest
from app import db
from app.models.kanban import (
    KanbanBoard,
    KanbanBoardMember,
    KanbanList,
    KanbanCard,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanActivity,
    KanbanActivityRead,
)
from app.models.user import User


@pytest.fixture
def kanban_notification_setup(app):
    user1 = User(
        email='alice@example.com',
        first_name='Alice',
        last_name='Tester',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user1.set_password('Password123!@#')

    user2 = User(
        email='bob@example.com',
        first_name='Bob',
        last_name='Collaborator',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user2.set_password('Password123!@#')

    db.session.add_all([user1, user2])
    db.session.commit()

    board = KanbanBoard(
        title='Notification Board',
        created_by=user1.id,
        visibility='private',
    )
    db.session.add(board)
    db.session.flush()

    db.session.add(KanbanBoardMember(board_id=board.id, user_id=user1.id, role='owner'))
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=user2.id, role='member'))

    list1 = KanbanList(board_id=board.id, title='To Do', position=0)
    list2 = KanbanList(board_id=board.id, title='Done', position=1)
    db.session.add_all([list1, list2])
    db.session.flush()

    card = KanbanCard(list_id=list1.id, title='Fix Kanban Bugs', position=0, created_by=user1.id)
    db.session.add(card)
    db.session.flush()

    cl = KanbanChecklist(card_id=card.id, title='Quality Checklist', position=0)
    db.session.add(cl)
    db.session.flush()

    item = KanbanChecklistItem(checklist_id=cl.id, text='Verify Notifications', position=0)
    db.session.add(item)
    db.session.commit()

    return user1, user2, board, list1, list2, card, cl, item


def _login(client, email, password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_kanban_notifications_feed_and_mark_read(client, kanban_notification_setup):
    user1, user2, board, list1, list2, card, cl, item = kanban_notification_setup

    # Log in as Alice (user1)
    _login(client, user1.email)

    # 1. Alice moves card from To Do to Done
    move_resp = client.post(
        f'/kanban/api/boards/{board.id}/cards/move',
        json={'card_id': card.id, 'list_id': list2.id, 'position': 0},
    )
    assert move_resp.status_code == 200

    # 2. Alice assigns Bob (user2) to the checklist item
    cl_resp = client.patch(
        f'/kanban/api/checklist-items/{item.id}',
        json={'assignee_id': user2.id},
    )
    assert cl_resp.status_code == 200

    # 3. Alice adds a file link attachment
    att_resp = client.post(
        f'/kanban/api/cards/{card.id}/attachments',
        json={'url': 'https://example.com/spec.pdf', 'title': 'Design Spec.pdf'},
    )
    assert att_resp.status_code == 201

    # Log out Alice, log in as Bob (user2)
    client.post('/logout', follow_redirects=True)
    _login(client, user2.email)

    # 4. Bob fetches notifications
    notif_resp = client.get(f'/kanban/api/boards/{board.id}/notifications')
    assert notif_resp.status_code == 200
    data = notif_resp.get_json()
    assert 'notifications' in data
    assert 'unread_count' in data
    assert data['unread_count'] >= 3

    # Check unread counts API across all boards for Bob
    all_counts_resp = client.get('/kanban/api/boards/unread_counts')
    assert all_counts_resp.status_code == 200
    all_counts = all_counts_resp.get_json()['unread_counts']
    assert str(board.id) in all_counts
    assert all_counts[str(board.id)] >= 3

    # Check Kanban index / dashboard renders unread badge
    index_resp = client.get('/kanban/')
    assert index_resp.status_code == 200
    index_html = index_resp.get_data(as_text=True)
    assert f'data-board-unread-badge="{board.id}"' in index_html
    assert 'kanban-board-unread-badge' in index_html

    # Check Kanban board view contains the dropdown notification panel under the bell
    board_view_resp = client.get(f'/kanban/board/{board.id}')
    assert board_view_resp.status_code == 200
    board_html = board_view_resp.get_data(as_text=True)
    assert 'kanban-notifications-dropdown' in board_html
    assert 'id="kanbanNotificationsPanel"' in board_html
    assert 'id="kanbanNotificationsCloseBtn"' in board_html

    # Check notification contents
    notifs = data['notifications']
    actions = [n['action'] for n in notifs]
    assert 'card_moved' in actions
    assert 'checklist_assignee_added' in actions
    assert 'attachment_added' in actions

    # Check customized natural language text for Bob
    cl_notif = next(n for n in notifs if n['action'] == 'checklist_assignee_added')
    assert 'Ihnen' in cl_notif['action_text']
    assert cl_notif['is_for_me'] is True

    att_notif = next(n for n in notifs if n['action'] == 'attachment_added')
    assert 'Design Spec.pdf' in att_notif['action_text']

    move_notif = next(n for n in notifs if n['action'] == 'card_moved')
    assert 'nach \'Done\'' in move_notif['action_text']

    # 5. Bob marks one notification as read
    first_notif_id = notifs[0]['id']
    mark_resp = client.post(
        f'/kanban/api/boards/{board.id}/notifications/mark_read',
        json={'activity_id': first_notif_id},
    )
    assert mark_resp.status_code == 200
    assert mark_resp.get_json()['unread_count'] == data['unread_count'] - 1

    # 6. Bob marks all notifications as read
    mark_all_resp = client.post(
        f'/kanban/api/boards/{board.id}/notifications/mark_read',
        json={'all': True},
    )
    assert mark_all_resp.status_code == 200
    assert mark_all_resp.get_json()['unread_count'] == 0

    # 7. Unread count endpoint returns 0
    count_resp = client.get(f'/kanban/api/boards/{board.id}/notifications/count')
    assert count_resp.status_code == 200
    assert count_resp.get_json()['unread_count'] == 0
