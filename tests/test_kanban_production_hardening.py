import io
import json
import pytest

from app import db
from app.models.kanban import (
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardTemplate,
    KanbanCard,
    KanbanList,
)
from app.models.public_share import PublicShare
from app.models.user import User


def _login(client, email, password='Password123!@#'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


@pytest.fixture
def hardening_ctx(app):
    owner = User(
        email='hardening-owner@example.com',
        first_name='Hardening',
        last_name='Owner',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    owner.set_password('Password123!@#')

    other = User(
        email='hardening-other@example.com',
        first_name='Other',
        last_name='User',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    other.set_password('Password123!@#')

    db.session.add_all([owner, other])
    db.session.commit()

    board = KanbanBoard(
        title='Hardening Board',
        created_by=owner.id,
        visibility='private',
    )
    db.session.add(board)
    db.session.flush()
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=owner.id, role='owner'))

    lst = KanbanList(board_id=board.id, title='To Do', position=0)
    db.session.add(lst)
    db.session.flush()

    card = KanbanCard(list_id=lst.id, title='Test Card', created_by=owner.id, position=0)
    db.session.add(card)
    db.session.commit()

    return {'owner': owner, 'other': other, 'board': board, 'list': lst, 'card': card}


def test_svg_attachment_never_served_inline(client, hardening_ctx):
    _login(client, hardening_ctx['owner'].email)
    card = hardening_ctx['card']

    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    res = client.post(
        f'/kanban/api/cards/{card.id}/attachments',
        data={'file': (io.BytesIO(svg_bytes), 'xss.svg', 'image/svg+xml')},
        content_type='multipart/form-data',
    )
    assert res.status_code == 201
    att_id = res.get_json()['attachment']['id']

    preview_res = client.get(f'/kanban/attachments/{att_id}/preview')
    assert preview_res.status_code == 200
    assert preview_res.headers.get('X-Content-Type-Options') == 'nosniff'
    assert 'attachment' in (preview_res.headers.get('Content-Disposition') or '').lower()


def test_png_attachment_served_inline_with_nosniff(client, hardening_ctx):
    _login(client, hardening_ctx['owner'].email)
    card = hardening_ctx['card']

    png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
    res = client.post(
        f'/kanban/api/cards/{card.id}/attachments',
        data={'file': (io.BytesIO(png_bytes), 'pixel.png', 'image/png')},
        content_type='multipart/form-data',
    )
    assert res.status_code == 201
    att_id = res.get_json()['attachment']['id']

    preview_res = client.get(f'/kanban/attachments/{att_id}/preview')
    assert preview_res.status_code == 200
    assert preview_res.headers.get('X-Content-Type-Options') == 'nosniff'
    assert 'attachment' not in (preview_res.headers.get('Content-Disposition') or '').lower()


def test_fetch_url_title_rejects_fake_share_token(client, hardening_ctx):
    res = client.get('/kanban/api/fetch-url-title?url=https://example.com&share_token=forged-token')
    assert res.status_code == 401


def test_create_board_rejects_invalid_or_private_foreign_template(client, hardening_ctx):
    owner = hardening_ctx['owner']
    other = hardening_ctx['other']
    private_tmpl = KanbanBoardTemplate(
        name='Secret Template',
        payload_json=json.dumps({'lists': [{'title': 'Secret List'}]}),
        created_by=owner.id,
        is_global=False,
    )
    db.session.add(private_tmpl)
    db.session.commit()

    _login(client, other.email)

    bad_res = client.post('/kanban/api/boards', json={'title': 'Bad', 'template_id': 'not-an-int'})
    assert bad_res.status_code == 400

    idor_res = client.post('/kanban/api/boards', json={'title': 'Stolen', 'template_id': private_tmpl.id})
    assert idor_res.status_code == 403


def test_board_get_supports_etag_304(client, hardening_ctx):
    _login(client, hardening_ctx['owner'].email)
    board = hardening_ctx['board']

    res1 = client.get(f'/kanban/api/boards/{board.id}')
    assert res1.status_code == 200
    etag = res1.headers.get('ETag')
    assert etag

    res2 = client.get(f'/kanban/api/boards/{board.id}', headers={'If-None-Match': etag})
    assert res2.status_code == 304


def test_portal_file_attachment_redirect_and_share_block(client, hardening_ctx):
    owner = hardening_ctx['owner']
    board = hardening_ctx['board']
    card = hardening_ctx['card']

    att = KanbanAttachment(
        card_id=card.id,
        filename='portal-file',
        original_filename='doc.pdf',
        mime_type='text/uri-list',
        storage_path='',
        url='portal-file://42',
        uploaded_by=owner.id,
    )
    share = PublicShare(
        token='hardening-share-token-123',
        resource_type='kanban_board',
        resource_id=str(board.id),
        mode='view',
        created_by=owner.id,
    )
    db.session.add_all([att, share])
    db.session.commit()

    _login(client, owner.email)
    dl = client.get(f'/kanban/attachments/{att.id}/download')
    assert dl.status_code == 302
    assert '/files/download/42' in dl.headers['Location']

    share_dl = client.get(f'/kanban/share/{share.token}/attachments/{att.id}/download')
    assert share_dl.status_code == 403


def test_board_background_rejects_svg_and_sets_nosniff(client, hardening_ctx):
    _login(client, hardening_ctx['owner'].email)
    board = hardening_ctx['board']

    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    bad = client.post(
        f'/kanban/api/boards/{board.id}/background',
        data={'file': (io.BytesIO(svg_bytes), 'bg.svg', 'image/svg+xml')},
        content_type='multipart/form-data',
    )
    assert bad.status_code == 400

    png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
    ok = client.post(
        f'/kanban/api/boards/{board.id}/background',
        data={'file': (io.BytesIO(png_bytes), 'bg.png', 'image/png')},
        content_type='multipart/form-data',
    )
    assert ok.status_code == 201
    bg_res = client.get(f'/kanban/boards/{board.id}/background')
    assert bg_res.status_code == 200
    assert bg_res.headers.get('X-Content-Type-Options') == 'nosniff'


def test_move_board_validates_team_membership(client, hardening_ctx):
    from app.models.team import Team
    owner = hardening_ctx['owner']
    other = hardening_ctx['other']
    board = hardening_ctx['board']

    foreign_team = Team(name='Foreign Team')
    db.session.add(foreign_team)
    db.session.commit()

    _login(client, owner.email)
    res_404 = client.post(
        f'/kanban/api/boards/{board.id}/move',
        json={'visibility': 'team', 'team_id': 999999},
    )
    assert res_404.status_code == 404

    res_403 = client.post(
        f'/kanban/api/boards/{board.id}/move',
        json={'visibility': 'team', 'team_id': foreign_team.id},
    )
    assert res_403.status_code == 403


def test_move_card_ignores_archived_cards_in_position(client, hardening_ctx):
    from datetime import datetime, timezone
    _login(client, hardening_ctx['owner'].email)
    owner = hardening_ctx['owner']
    board = hardening_ctx['board']
    lst = hardening_ctx['list']
    c1 = hardening_ctx['card']

    archived_card = KanbanCard(
        list_id=lst.id,
        title='Archived',
        created_by=owner.id,
        position=0,
        archived_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    c2 = KanbanCard(list_id=lst.id, title='Second Active', created_by=owner.id, position=2)
    c1.position = 1
    db.session.add_all([archived_card, c2])
    db.session.commit()

    res = client.post(
        f'/kanban/api/boards/{board.id}/cards/move',
        json={'card_id': c2.id, 'list_id': lst.id, 'position': 0},
    )
    assert res.status_code == 200
    db.session.refresh(c2)
    db.session.refresh(c1)
    assert c2.position == 0
    assert c1.position == 1


def test_reorder_lists_batch(client, hardening_ctx):
    _login(client, hardening_ctx['owner'].email)
    board = hardening_ctx['board']
    l1 = hardening_ctx['list']
    l2 = KanbanList(board_id=board.id, title='Doing', position=1)
    db.session.add(l2)
    db.session.commit()

    res = client.post(
        f'/kanban/api/boards/{board.id}/lists/reorder',
        json={'order': [l2.id, l1.id]},
    )
    assert res.status_code == 200
    db.session.refresh(l1)
    db.session.refresh(l2)
    assert l2.position == 0
    assert l1.position == 1
