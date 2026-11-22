import os
import pytest

from app import db
from app.models.kanban import KanbanAttachment, KanbanBoard, KanbanCard, KanbanList
from app.models.user import User


@pytest.fixture
def kanban_cleanup_user(app):
    user = User(
        email='kanbancleanup@example.com',
        first_name='Cleanup',
        last_name='Tester',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email='kanbancleanup@example.com', password='Password123!@#'):
    resp = client.post(
        '/login',
        data={'email': email, 'password': password},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def _kanban_dirs(app):
    upload_root = os.path.join(app.config['UPLOAD_FOLDER'], 'kanban')
    boards_root = os.path.join(upload_root, 'boards')
    os.makedirs(upload_root, exist_ok=True)
    os.makedirs(boards_root, exist_ok=True)
    return upload_root, boards_root


def test_delete_board_removes_only_unreferenced_files(app, client, kanban_cleanup_user):
    _login(client)
    upload_root, boards_root = _kanban_dirs(app)

    exclusive_att_path = os.path.join(upload_root, 'exclusive_att.txt')
    shared_att_path = os.path.join(upload_root, 'shared_att.txt')
    exclusive_cover_path = os.path.join(boards_root, 'exclusive_cover.png')
    shared_cover_path = os.path.join(boards_root, 'shared_cover.png')
    outside_path = os.path.join(app.config['UPLOAD_FOLDER'], 'outside_keep.txt')

    for p in (exclusive_att_path, shared_att_path, exclusive_cover_path, shared_cover_path, outside_path):
        with open(p, 'wb') as fh:
            fh.write(b'test-content')

    board_to_delete = KanbanBoard(
        title='Delete Me',
        created_by=kanban_cleanup_user.id,
        visibility='public',
        cover_path=exclusive_cover_path,
    )
    other_board = KanbanBoard(
        title='Keep Me',
        created_by=kanban_cleanup_user.id,
        visibility='public',
        cover_path=shared_cover_path,
    )
    db.session.add_all([board_to_delete, other_board])
    db.session.flush()

    lst1 = KanbanList(board_id=board_to_delete.id, title='L1', position=0)
    lst2 = KanbanList(board_id=other_board.id, title='L2', position=0)
    db.session.add_all([lst1, lst2])
    db.session.flush()

    card1 = KanbanCard(list_id=lst1.id, title='C1', created_by=kanban_cleanup_user.id, position=0)
    card2 = KanbanCard(list_id=lst2.id, title='C2', created_by=kanban_cleanup_user.id, position=0)
    db.session.add_all([card1, card2])
    db.session.flush()

    db.session.add_all([
        KanbanAttachment(
            card_id=card1.id,
            filename='exclusive_att.txt',
            original_filename='exclusive_att.txt',
            storage_path=exclusive_att_path,
            uploaded_by=kanban_cleanup_user.id,
        ),
        KanbanAttachment(
            card_id=card1.id,
            filename='shared_att.txt',
            original_filename='shared_att.txt',
            storage_path=shared_att_path,
            uploaded_by=kanban_cleanup_user.id,
        ),
        KanbanAttachment(
            card_id=card1.id,
            filename='shared_cover.png',
            original_filename='shared_cover.png',
            storage_path=shared_cover_path,
            uploaded_by=kanban_cleanup_user.id,
        ),
        KanbanAttachment(
            card_id=card1.id,
            filename='outside_keep.txt',
            original_filename='outside_keep.txt',
            storage_path=outside_path,
            uploaded_by=kanban_cleanup_user.id,
        ),
        KanbanAttachment(
            card_id=card2.id,
            filename='shared_att.txt',
            original_filename='shared_att.txt',
            storage_path=shared_att_path,
            uploaded_by=kanban_cleanup_user.id,
        ),
    ])
    db.session.commit()

    resp = client.delete(f'/kanban/api/boards/{board_to_delete.id}')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    assert not os.path.exists(exclusive_att_path)
    assert not os.path.exists(exclusive_cover_path)
    assert os.path.exists(shared_att_path)
    assert os.path.exists(shared_cover_path)
    assert os.path.exists(outside_path)


def test_delete_list_card_and_attachment_cleanup_unreferenced_files(app, client, kanban_cleanup_user):
    _login(client)
    upload_root, _ = _kanban_dirs(app)

    list_file = os.path.join(upload_root, 'list_att.txt')
    card_file = os.path.join(upload_root, 'card_att.txt')
    single_file = os.path.join(upload_root, 'single_att.txt')
    shared_file = os.path.join(upload_root, 'still_linked.txt')

    for p in (list_file, card_file, single_file, shared_file):
        with open(p, 'wb') as fh:
            fh.write(b'data')

    board = KanbanBoard(title='Cleanup Board', created_by=kanban_cleanup_user.id, visibility='public')
    db.session.add(board)
    db.session.flush()

    lst_del = KanbanList(board_id=board.id, title='Delete List', position=0)
    lst_keep = KanbanList(board_id=board.id, title='Keep List', position=1)
    db.session.add_all([lst_del, lst_keep])
    db.session.flush()

    c_in_del_list = KanbanCard(list_id=lst_del.id, title='In Del List', created_by=kanban_cleanup_user.id, position=0)
    c_del = KanbanCard(list_id=lst_keep.id, title='Del Card', created_by=kanban_cleanup_user.id, position=0)
    c_keep = KanbanCard(list_id=lst_keep.id, title='Keep Card', created_by=kanban_cleanup_user.id, position=1)
    db.session.add_all([c_in_del_list, c_del, c_keep])
    db.session.flush()

    att_single = KanbanAttachment(
        card_id=c_keep.id,
        filename='single_att.txt',
        original_filename='single_att.txt',
        storage_path=single_file,
        uploaded_by=kanban_cleanup_user.id,
    )
    att_shared_1 = KanbanAttachment(
        card_id=c_del.id,
        filename='still_linked.txt',
        original_filename='still_linked.txt',
        storage_path=shared_file,
        uploaded_by=kanban_cleanup_user.id,
    )
    att_shared_2 = KanbanAttachment(
        card_id=c_keep.id,
        filename='still_linked.txt',
        original_filename='still_linked.txt',
        storage_path=shared_file,
        uploaded_by=kanban_cleanup_user.id,
    )
    db.session.add_all([
        KanbanAttachment(
            card_id=c_in_del_list.id,
            filename='list_att.txt',
            original_filename='list_att.txt',
            storage_path=list_file,
            uploaded_by=kanban_cleanup_user.id,
        ),
        KanbanAttachment(
            card_id=c_del.id,
            filename='card_att.txt',
            original_filename='card_att.txt',
            storage_path=card_file,
            uploaded_by=kanban_cleanup_user.id,
        ),
        att_single,
        att_shared_1,
        att_shared_2,
    ])
    db.session.commit()

    assert client.delete(f'/kanban/api/lists/{lst_del.id}').status_code == 200
    assert not os.path.exists(list_file)

    assert client.delete(f'/kanban/api/cards/{c_del.id}').status_code == 200
    assert not os.path.exists(card_file)
    assert os.path.exists(shared_file)

    assert client.delete(f'/kanban/api/attachments/{att_single.id}').status_code == 200
    assert not os.path.exists(single_file)
    assert os.path.exists(shared_file)
