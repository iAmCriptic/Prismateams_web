import json
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.kanban import KanbanAttachment, KanbanBoard, KanbanCard, KanbanChecklist
from app.models.user import User
from app.utils.kanban_import import import_board_from_bytes


@pytest.fixture
def import_user(app):
    user = User(
        email='kanban_import_user@example.com',
        first_name='Import',
        last_name='User',
        is_active=True,
        is_admin=False,
        has_full_access=True,
        is_email_confirmed=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email, password='Password123!@#'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_trello_json_checklists_all_variants(import_user):
    payload = {
        'id': 'board1',
        'name': 'Trello Checklist Board',
        'lists': [{'id': 'list1', 'name': 'To Do', 'pos': 16384, 'closed': False}],
        'checklists': [
            {
                'id': 'cl_by_card',
                'idCard': 'card1',
                'name': 'Top-Level via idCard',
                'pos': 'top',
                'checkItems': [
                    {'id': 'i1', 'name': 'Item A', 'state': 'complete', 'pos': 1},
                    {'id': 'i2', 'name': 'Item B', 'state': 'incomplete', 'pos': 'bottom'},
                ],
            },
            {
                'id': 'cl_by_ref',
                'name': 'Referenced via idChecklists',
                'pos': 200,
                'checkItems': [
                    {'id': 'i3', 'text': 'Item C', 'checked': True, 'pos': None},
                ],
            },
        ],
        'cards': [
            {
                'id': 'card1',
                'idList': 'list1',
                'name': 'ZIELE JUKU TEAM',
                'desc': '### Ziel\n\n**Wichtig**',
                'pos': 65536,
                'idChecklists': ['cl_by_card', 'cl_by_ref'],
                'checklists': [
                    {
                        'id': 'cl_embedded',
                        'name': 'Embedded Checklist',
                        'pos': 300,
                        'checkItems': [
                            {'id': 'i4', 'name': 'Item D', 'state': 'complete', 'pos': 1},
                        ],
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode('utf-8')
    board = import_board_from_bytes(
        raw=raw,
        filename='board.json',
        user=import_user,
        visibility='private',
    )
    db.session.commit()

    assert board.title == 'Trello Checklist Board'
    cards = KanbanCard.query.join(KanbanCard.list).filter_by(board_id=board.id).all()
    assert len(cards) == 1
    checklists = KanbanChecklist.query.filter_by(card_id=cards[0].id).order_by(KanbanChecklist.position).all()
    assert [c.title for c in checklists] == [
        'Top-Level via idCard',
        'Referenced via idChecklists',
        'Embedded Checklist',
    ]
    assert [(it.text, it.done) for it in checklists[0].items] == [('Item A', True), ('Item B', False)]
    assert [(it.text, it.done) for it in checklists[1].items] == [('Item C', True)]
    assert [(it.text, it.done) for it in checklists[2].items] == [('Item D', True)]


def test_csv_import_semicolon_cp1252_and_checklists(import_user):
    csv_text = (
        'Karte;Beschreibung;Etiketten;Liste;Erledigt;Checkliste\n'
        'Prüfung Größe;**Dauer:** 2h;Dringend, Team;Offen;false;"[x] Schritt 1; [ ] Schritt 2"\n'
    )
    raw = csv_text.encode('cp1252')
    board = import_board_from_bytes(
        raw=raw,
        filename='export.csv',
        user=import_user,
        visibility='private',
        title_override='CSV Board',
    )
    db.session.commit()

    assert board.title == 'CSV Board'
    cards = KanbanCard.query.join(KanbanCard.list).filter_by(board_id=board.id).all()
    assert len(cards) == 1
    assert cards[0].title == 'Prüfung Größe'
    assert cards[0].description == '**Dauer:** 2h'
    assert [lb.label.name for lb in cards[0].card_labels] == ['Dringend', 'Team']
    checklists = KanbanChecklist.query.filter_by(card_id=cards[0].id).all()
    assert len(checklists) == 1
    assert [(it.text, it.done) for it in checklists[0].items] == [('Schritt 1', True), ('Schritt 2', False)]


def test_trello_auth_downloads_private_attachments(import_user):
    payload = {
        'id': 'b1',
        'name': 'Media Board',
        'lists': [{'id': 'l1', 'name': 'To Do', 'pos': 1}],
        'cards': [
            {
                'id': 'c1',
                'idList': 'l1',
                'name': 'Card with Image',
                'pos': 1,
                'idAttachmentCover': 'att1',
                'attachments': [
                    {
                        'id': 'att1',
                        'name': 'photo.png',
                        'url': 'https://trello.com/1/cards/c1/attachments/att1/download/photo.png',
                        'mimeType': 'image/png',
                    }
                ],
            }
        ],
    }
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {'Content-Type': 'image/png'}
    fake_resp.iter_content.return_value = [b'\x89PNG\r\n\x1a\nFAKEPNG']
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = False

    with patch('app.utils.kanban_import.requests.get', return_value=fake_resp) as mock_get:
        board = import_board_from_bytes(
            raw=json.dumps(payload).encode('utf-8'),
            filename='media.json',
            user=import_user,
            visibility='private',
            trello_auth=('key123', 'tok456'),
        )
        db.session.commit()

    assert mock_get.called
    sent_headers = mock_get.call_args.kwargs.get('headers') or {}
    assert sent_headers.get('Authorization') == 'OAuth oauth_consumer_key="key123", oauth_token="tok456"'

    cards = KanbanCard.query.join(KanbanCard.list).filter_by(board_id=board.id).all()
    atts = KanbanAttachment.query.filter_by(card_id=cards[0].id).all()
    assert len(atts) == 1
    assert atts[0].url is None
    assert atts[0].storage_path
    assert cards[0].cover_attachment_id == atts[0].id


def test_card_description_markdown_html_and_xss_sanitized(client, import_user):
    board = KanbanBoard(title='MD Board', created_by=import_user.id, visibility='private')
    db.session.add(board)
    db.session.flush()
    from app.models.kanban import KanbanBoardMember, KanbanList
    db.session.add(KanbanBoardMember(board_id=board.id, user_id=import_user.id, role='owner'))
    lst = KanbanList(board_id=board.id, title='Todo', position=0)
    db.session.add(lst)
    db.session.flush()
    card = KanbanCard(
        list_id=lst.id,
        title='MD Card',
        description='### Ziel\n\n**Fett** <script>alert(1)</script>',
        position=0,
        created_by=import_user.id,
    )
    db.session.add(card)
    db.session.commit()

    _login(client, import_user.email)
    resp = client.get(f'/kanban/api/cards/{card.id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert '<h3' in data['description_html']
    assert '<strong>Fett</strong>' in data['description_html']
    assert '<script' not in data['description_html']

    patch_resp = client.patch(
        f'/kanban/api/cards/{card.id}',
        json={'description': '- Punkt 1\n- Punkt 2'},
    )
    assert patch_resp.status_code == 200
    pdata = patch_resp.get_json()
    assert '<li>Punkt 1</li>' in pdata['card']['description_html']


def test_settings_trello_api_connect_boards_and_import(client, import_user):
    _login(client, import_user.email)

    with patch('app.utils.trello_client.validate_trello_credentials', return_value={'id': 'u1', 'username': 'max', 'full_name': 'Max Mustermann'}):
        r = client.post('/settings/kanban-import/trello/connect', json={'api_key': 'k1', 'token': 't1'})
        assert r.status_code == 200
        assert r.get_json()['profile']['username'] == 'max'

    with patch('app.utils.trello_client.list_trello_boards', return_value=[{'id': 'tb1', 'name': 'Remote Board', 'desc': ''}]):
        r = client.get('/settings/kanban-import/trello/boards')
        assert r.status_code == 200
        assert r.get_json()['boards'][0]['id'] == 'tb1'

    remote_board = {
        'id': 'tb1',
        'name': 'Remote Board',
        'lists': [{'id': 'l1', 'name': 'Backlog', 'pos': 1}],
        'cards': [{'id': 'c1', 'idList': 'l1', 'name': 'Remote Card', 'pos': 1}],
        'checklists': [{'id': 'cl1', 'idCard': 'c1', 'name': 'Steps', 'pos': 1, 'checkItems': [{'id': 'i1', 'name': 'Do it', 'state': 'complete', 'pos': 1}]}],
    }
    with patch('app.utils.trello_client.fetch_trello_board_json', return_value=remote_board):
        r = client.post('/settings/kanban-import/trello/import', json={'board_ids': ['tb1'], 'visibility': 'private'})
        assert r.status_code == 201
        j = r.get_json()
        assert j['success'] is True
        assert j['boards'][0]['title'] == 'Remote Board'

    r = client.post('/settings/kanban-import/trello/disconnect')
    assert r.status_code == 200


def test_board_cover_url_prefers_local_file_over_posix_slash_prefix(app, import_user, tmp_path):
    from app.blueprints.kanban.helpers import _board_cover_url

    img_file = tmp_path / 'board-bg.jpg'
    img_file.write_bytes(b'\xff\xd8\xff\xe0FAKEJPEG')
    posix_like_path = '/' + str(img_file).lstrip('/').replace('\\', '/')

    board = KanbanBoard(
        title='Cover Test',
        created_by=import_user.id,
        visibility='private',
        cover_path=str(img_file),
    )
    db.session.add(board)
    db.session.commit()

    with app.test_request_context():
        with patch('app.blueprints.kanban.helpers._board_cover_file_path', return_value=str(img_file)):
            board.cover_path = '/var/www/teamportal/uploads/kanban/boards/abc_bg.jpg'
            url = _board_cover_url(board)
            assert url is not None
            assert not url.startswith('/var/www/')
            assert f'/boards/{board.id}/background' in url or 'background' in url

        with patch('app.blueprints.kanban.helpers._board_cover_file_path', return_value=None):
            board.cover_path = '/static/img/bg.jpg'
            assert _board_cover_url(board) == '/static/img/bg.jpg'
            assert posix_like_path.startswith('/')


def test_trello_async_import_job_persists_across_page_reload(app, client, import_user):
    from app.models.cloud_import import KanbanImportJob
    from app.utils.kanban_import_worker import process_trello_import_job

    _login(client, import_user.email)

    with patch('app.utils.trello_client.validate_trello_credentials', return_value={'id': 'u1', 'username': 'max', 'full_name': 'Max Mustermann'}):
        r = client.post('/settings/kanban-import/trello/connect', json={'api_key': 'k1', 'token': 't1'})
        assert r.status_code == 200

    # Non-admin cannot import into public visibility
    r_forbidden = client.post('/settings/kanban-import/trello/jobs', json={
        'board_ids': ['tb1'],
        'visibility': 'public',
    })
    assert r_forbidden.status_code == 403

    # Start async job without running background thread yet (simulate in-progress state)
    with patch('app.utils.kanban_import_worker.start_trello_import_job') as mock_start:
        r_start = client.post('/settings/kanban-import/trello/jobs', json={
            'board_ids': ['tb1'],
            'board_names': ['Async Board'],
            'visibility': 'private',
            'target_label': 'Private',
        })
        assert r_start.status_code == 202
        job_data = r_start.get_json()['job']
        job_id = job_data['id']
        assert job_data['status'] == 'pending'
        assert job_data['display_name'] == 'Async Board'
        assert mock_start.called

    # Leaving and returning to /settings/imports still shows the active job with timer
    r_page = client.get('/settings/imports?source=kanban')
    assert r_page.status_code == 200
    html = r_page.get_data(as_text=True)
    assert f'data-kanban-job-id="{job_id}"' in html
    assert 'Async Board' in html
    assert 'kanban-import-job-timer' in html

    # Polling before completion reports pending/running and no boards yet
    r_poll_before = client.get(f'/settings/kanban-import/jobs/{job_id}')
    assert r_poll_before.status_code == 200
    assert r_poll_before.get_json()['job']['status'] == 'pending'
    assert r_poll_before.get_json()['job']['boards'] == []

    # Now execute the worker synchronously
    remote_board = {
        'id': 'tb1',
        'name': 'Async Board',
        'lists': [{'id': 'l1', 'name': 'To Do', 'pos': 1}],
        'cards': [{'id': 'c1', 'idList': 'l1', 'name': 'Card 1', 'pos': 1}],
    }
    with patch('app.utils.trello_client.fetch_trello_board_json', return_value=remote_board):
        process_trello_import_job(app, job_id, ['tb1'], 'k1', 't1')

    # Polling after worker finishes reports completed + imported board URL
    r_poll_after = client.get(f'/settings/kanban-import/jobs/{job_id}')
    assert r_poll_after.status_code == 200
    done_job = r_poll_after.get_json()['job']
    assert done_job['status'] == 'completed'
    assert done_job['boards_done'] == 1
    assert len(done_job['boards']) == 1
    assert done_job['boards'][0]['title'] == 'Async Board'
    assert done_job['boards'][0]['url']

    persisted = db.session.get(KanbanImportJob, job_id)
    assert persisted is not None
    assert persisted.completed_at is not None
