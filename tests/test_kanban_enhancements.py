import os
import tempfile

from app import db
from app.models.comment import Comment
from app.models.kanban import (
    KanbanActivity,
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardNotificationPreference,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardLabel,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanLabel,
    KanbanList,
)
from app.models.notification import NotificationLog
from app.models.user import User
from app.utils.notifications import send_comment_notification, send_kanban_notification


def _make_user(email: str, first: str, last: str) -> User:
    u = User(
        email=email,
        first_name=first,
        last_name=last,
        is_active=True,
        is_admin=False,
        has_full_access=True,
        can_access_public=True,
        can_access_team=True,
        can_access_private=True,
        is_email_confirmed=True,
        notifications_enabled=True,
    )
    u.set_password('Password123!@#')
    db.session.add(u)
    db.session.flush()
    return u


def _login(client, email: str):
    resp = client.post(
        '/login',
        data={'email': email, 'password': 'Password123!@#'},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)


def test_board_notification_filter_modes(app, client):
    alice = _make_user('alice_nf@example.com', 'Alice', 'Admin')
    bob = _make_user('bob_nf@example.com', 'Bob', 'Member')
    board = KanbanBoard(title='Filter Board', created_by=alice.id, visibility='private')
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=alice.id, role='owner'))
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=bob.id, role='member'))
    lst = KanbanList(board_id=board.id, title='To Do', position=0)
    db.session.add(lst)
    db.session.flush()

    card_unassigned = KanbanCard(list_id=lst.id, title='Other Card', position=0, created_by=alice.id)
    card_assigned = KanbanCard(list_id=lst.id, title='Bob Card', position=1, created_by=alice.id)
    db.session.add_all([card_unassigned, card_assigned])
    db.session.flush()
    db.session.add(KanbanCardAssignee(card_id=card_assigned.id, user_id=bob.id))
    cl = KanbanChecklist(card_id=card_unassigned.id, title='CL', position=0)
    db.session.add(cl)
    db.session.flush()
    cl_item = KanbanChecklistItem(checklist_id=cl.id, text='Check item', position=0)
    db.session.add(cl_item)
    db.session.commit()

    # Bob sets mode = 'mentions_checklist' via API
    _login(client, 'bob_nf@example.com')
    r = client.patch(
        f'/kanban/api/boards/{board.id}/notification-preference',
        json={'mode': 'mentions_checklist'},
    )
    assert r.status_code == 200
    assert r.get_json()['mode'] == 'mentions_checklist'

    # Unassigned card change -> suppressed for Bob
    sent = send_kanban_notification(board.id, alice.id, 'change', card_unassigned.id)
    assert sent == 0
    # Assigned card change -> also suppressed in mentions_checklist
    sent = send_kanban_notification(board.id, alice.id, 'change', card_assigned.id)
    assert sent == 0
    # Checklist assignment to Bob -> allowed!
    sent = send_kanban_notification(
        board.id,
        alice.id,
        'checklist',
        card_unassigned.id,
        detail=cl_item.text,
        target_user_ids={bob.id},
        is_checklist_assignment=True,
    )
    assert sent == 1

    # Comment mention on unassigned card -> allowed!
    c_mention = Comment(
        content_type='kanban_card',
        content_id=card_unassigned.id,
        author_id=alice.id,
        content='Hi @Bob Member',
    )
    db.session.add(c_mention)
    db.session.flush()
    assert send_comment_notification(c_mention, event_kind='mention', target_user_id=bob.id, actor=alice) is True

    # Switch Bob to 'assigned' mode
    r = client.patch(
        f'/kanban/api/boards/{board.id}/notification-preference',
        json={'mode': 'assigned'},
    )
    assert r.status_code == 200
    # Unassigned card change -> suppressed
    assert send_kanban_notification(board.id, alice.id, 'change', card_unassigned.id) == 0
    # Assigned card change -> allowed!
    assert send_kanban_notification(board.id, alice.id, 'change', card_assigned.id) == 1

    # Verify NotificationLog entries exist only for allowed notifications
    logs = NotificationLog.query.filter_by(user_id=bob.id).all()
    assert len(logs) == 3

    # Verify board-internal bell (KanbanActivity) still logs everything when Alice edits
    _login(client, 'alice_nf@example.com')
    r_upd = client.patch(
        f'/kanban/api/cards/{card_unassigned.id}',
        json={'title': 'Updated Other Card'},
    )
    assert r_upd.status_code == 200
    assert KanbanActivity.query.filter_by(board_id=board.id, card_id=card_unassigned.id).count() >= 1


def test_empty_checklist_title_defaults_to_checkliste(app, client):
    alice = _make_user('alice_cl@example.com', 'Alice', 'CL')
    board = KanbanBoard(title='CL Board', created_by=alice.id, visibility='private')
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=alice.id, role='owner'))
    lst = KanbanList(board_id=board.id, title='L1', position=0)
    db.session.add(lst)
    db.session.flush()
    card = KanbanCard(list_id=lst.id, title='Card 1', position=0, created_by=alice.id)
    db.session.add(card)
    db.session.commit()

    _login(client, 'alice_cl@example.com')
    r1 = client.post(f'/kanban/api/cards/{card.id}/checklists', json={'title': ''})
    assert r1.status_code == 201
    assert r1.get_json()['card']['checklists'][0]['title'] == 'Checkliste'

    r2 = client.post(f'/kanban/api/cards/{card.id}/checklists', json={'title': '   '})
    assert r2.status_code == 201
    assert r2.get_json()['card']['checklists'][1]['title'] == 'Checkliste'


def test_copy_and_move_checklist_card_list_board(app, client, tmp_path):
    alice = _make_user('alice_tr@example.com', 'Alice', 'Transfer')
    board1 = KanbanBoard(title='Board 1', created_by=alice.id, visibility='private')
    board2 = KanbanBoard(title='Board 2', created_by=alice.id, visibility='private')
    db.session.add_all([board1, board2])
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board1.id, user_id=alice.id, role='owner'))
    db.session.add(KanbanBoardMember(board_id=board2.id, user_id=alice.id, role='owner'))

    l1 = KanbanList(board_id=board1.id, title='List A', position=0)
    l2 = KanbanList(board_id=board2.id, title='List B', position=0)
    db.session.add_all([l1, l2])
    db.session.flush()

    lbl = KanbanLabel(board_id=board1.id, name='Urgent', color='#dc3545', position=0)
    db.session.add(lbl)
    db.session.flush()

    card1 = KanbanCard(list_id=l1.id, title='Original Card', description='Desc', position=0, created_by=alice.id)
    card2 = KanbanCard(list_id=l2.id, title='Target Card', position=0, created_by=alice.id)
    db.session.add_all([card1, card2])
    db.session.flush()
    db.session.add(KanbanCardLabel(card_id=card1.id, label_id=lbl.id))
    db.session.add(KanbanCardAssignee(card_id=card1.id, user_id=alice.id))

    cl = KanbanChecklist(card_id=card1.id, title='Steps', position=0)
    db.session.add(cl)
    db.session.flush()
    db.session.add(KanbanChecklistItem(checklist_id=cl.id, text='Step 1', done=True, position=0))

    src_file = tmp_path / 'spec.docx'
    src_file.write_bytes(b'PK-dummy-docx')
    att = KanbanAttachment(
        card_id=card1.id,
        filename='spec.docx',
        original_filename='spec.docx',
        mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        file_size=13,
        storage_path=str(src_file),
        uploaded_by=alice.id,
    )
    db.session.add(att)
    db.session.add(Comment(content_type='kanban_card', content_id=card1.id, author_id=alice.id, content='Nice card'))
    db.session.commit()

    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    _login(client, 'alice_tr@example.com')

    # 1. Copy checklist to card2 on board2
    r_cl_copy = client.post(f'/kanban/api/checklists/{cl.id}/copy', json={'target_card_id': card2.id})
    assert r_cl_copy.status_code == 201
    assert len(r_cl_copy.get_json()['card']['checklists']) == 1

    # 2. Copy card1 to list l2 on board2
    r_card_copy = client.post(
        f'/kanban/api/cards/{card1.id}/copy',
        json={'target_list_id': l2.id, 'title': 'Copied Card'},
    )
    assert r_card_copy.status_code == 201
    copied_card_id = r_card_copy.get_json()['card']['id']
    copied_card = db.session.get(KanbanCard, copied_card_id)
    assert copied_card.title == 'Copied Card'
    assert copied_card.description == 'Desc'
    assert len(copied_card.checklists) == 1
    assert len(copied_card.attachments) == 1
    assert copied_card.attachments[0].storage_path != str(src_file)
    assert os.path.isfile(copied_card.attachments[0].storage_path)
    assert Comment.query.filter_by(content_type='kanban_card', content_id=copied_card.id).count() == 1

    # 3. Move checklist from card1 to card2
    r_cl_move = client.post(f'/kanban/api/checklists/{cl.id}/move', json={'target_card_id': card2.id})
    assert r_cl_move.status_code == 200
    assert len(r_cl_move.get_json()['card']['checklists']) == 2

    # 4. Copy list l1 to board2
    r_list_copy = client.post(
        f'/kanban/api/lists/{l1.id}/copy',
        json={'target_board_id': board2.id, 'title': 'List A Copy'},
    )
    assert r_list_copy.status_code == 201
    assert len(r_list_copy.get_json()['list']['cards']) == 1

    # 5. Move list l1 to board2
    r_list_move = client.post(f'/kanban/api/lists/{l1.id}/move', json={'target_board_id': board2.id})
    assert r_list_move.status_code == 200
    assert db.session.get(KanbanList, l1.id).board_id == board2.id

    # 6. Copy board2
    r_board_copy = client.post(f'/kanban/api/boards/{board2.id}/copy', json={'title': 'Board 2 Clone'})
    assert r_board_copy.status_code == 201
    cloned_board_id = r_board_copy.get_json()['board']['id']
    cloned_board = db.session.get(KanbanBoard, cloned_board_id)
    assert cloned_board.title == 'Board 2 Clone'
    assert len(cloned_board.lists) == 3

    # 7. Move board2 visibility
    r_board_move = client.post(f'/kanban/api/boards/{board2.id}/move', json={'visibility': 'public'})
    assert r_board_move.status_code == 200
    assert db.session.get(KanbanBoard, board2.id).visibility == 'public'


def test_eurooffice_kanban_attachments_docx_pptx_pdf(app, client, tmp_path):
    alice = _make_user('alice_oo@example.com', 'Alice', 'OO')
    board = KanbanBoard(title='OO Board', created_by=alice.id, visibility='private')
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=alice.id, role='owner'))
    lst = KanbanList(board_id=board.id, title='Docs', position=0)
    db.session.add(lst)
    db.session.flush()
    card = KanbanCard(list_id=lst.id, title='Office Card', position=0, created_by=alice.id)
    db.session.add(card)
    db.session.flush()

    created_atts = []
    for fname, mime in [
        ('report.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
        ('deck.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
        ('manual.pdf', 'application/pdf'),
    ]:
        p = tmp_path / fname
        p.write_bytes(b'dummy-content')
        att = KanbanAttachment(
            card_id=card.id,
            filename=fname,
            original_filename=fname,
            mime_type=mime,
            file_size=13,
            storage_path=str(p),
            uploaded_by=alice.id,
        )
        db.session.add(att)
        created_atts.append(att)
    db.session.commit()

    app.config['ONLYOFFICE_ENABLED'] = True
    _login(client, 'alice_oo@example.com')

    r_card = client.get(f'/kanban/api/cards/{card.id}')
    assert r_card.status_code == 200
    card_json = r_card.get_json()
    atts = card_json.get('attachments') if 'attachments' in card_json else card_json['card']['attachments']
    assert len(atts) == 3
    for a in atts:
        assert a['onlyoffice_enabled'] is True
        assert a['is_office'] is True
        assert a['onlyoffice_url'] and ('/edit-eurooffice' in a['onlyoffice_url'] or '/edit-onlyoffice' in a['onlyoffice_url'])

    for att in created_atts:
        r_oo = client.get(f'/kanban/attachments/{att.id}/edit-onlyoffice')
        assert r_oo.status_code == 200


def test_card_template_mark_and_copy_resets_template_flag(app, client):
    alice = _make_user('alice_tpl@example.com', 'Alice', 'Tpl')
    board = KanbanBoard(title='Tpl Board', created_by=alice.id, visibility='private')
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=alice.id, role='owner'))
    lst = KanbanList(board_id=board.id, title='Vorlagen', position=0)
    db.session.add(lst)
    db.session.flush()
    card = KanbanCard(list_id=lst.id, title='MEETING', position=0, created_by=alice.id)
    db.session.add(card)
    db.session.commit()

    _login(client, 'alice_tpl@example.com')

    # Mark card as template
    r_patch = client.patch(f'/kanban/api/cards/{card.id}', json={'is_template': True})
    assert r_patch.status_code == 200
    assert r_patch.get_json()['card']['is_template'] is True

    # Create card from template -> copied card must NOT be a template
    r_copy = client.post(
        f'/kanban/api/cards/{card.id}/copy',
        json={'target_list_id': lst.id, 'title': 'MEETING'},
    )
    assert r_copy.status_code == 201
    new_card_data = r_copy.get_json()['card']
    assert new_card_data['is_template'] is False
