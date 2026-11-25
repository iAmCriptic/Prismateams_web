from app import db
from app.models.kanban import KanbanBoard
from app.models.user import User


def _create_user():
    user = User(
        email='share_user@example.com',
        first_name='Share',
        last_name='User',
        is_admin=True,
        is_active=True,
        is_email_confirmed=True,
    )
    user.set_password('Secret123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client):
    return client.post(
        '/login',
        data={'email': 'share_user@example.com', 'password': 'Secret123!@#'},
        follow_redirects=False,
    )


def test_share_target_renders_styles_and_script(client, app):
    with app.app_context():
        _create_user()

    _login(client)
    res = client.get('/share-target?url=https://example.com&title=TestLink')
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # base.html uses extra_css / extra_js; both must be rendered
    assert '.share-target-dest-btn' in html
    assert 'js/share-target.js' in html
    assert 'data-fallback-url="https://example.com"' in html
    assert 'data-fallback-title="TestLink"' in html


def test_share_target_kanban_boards_api(client, app):
    with app.app_context():
        user = _create_user()
        board = KanbanBoard(title='Share Board', created_by=user.id, visibility='private')
        db.session.add(board)
        db.session.commit()

    _login(client)
    res = client.get('/share-target/api/kanban-boards')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert any(b['title'] == 'Share Board' for b in data['boards'])
