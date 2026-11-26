import os
from unittest.mock import patch

import pytest

from app import db
from app.models.canvas import CanvasDocument
from app.models.role import UserModuleRole
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils.canvas import sign_canvas_avatar_token


@pytest.fixture
def canvas_user(app):
    user = User(
        email='canvas@example.com',
        first_name='Canvas',
        last_name='Tester',
        is_admin=False,
        is_active=True,
        is_email_confirmed=True,
    )
    user.set_password('StrongPass!12345')
    db.session.add(user)
    db.session.flush()

    db.session.add(SystemSettings(key='module_canvas_enabled', value='true'))
    db.session.add(
        UserModuleRole(
            user_id=user.id,
            module_key='module_canvas',
            has_access=True,
        )
    )
    db.session.commit()
    return user


def _login(client, user):
    resp = client.post(
        '/login',
        data={'email': user.email, 'password': 'StrongPass!12345'},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_canvas_requires_login(client):
    resp = client.get('/canvas/', follow_redirects=False)
    assert resp.status_code in (302, 401)


def test_canvas_index_renders_hycanvas_embed(client, canvas_user, app):
    _login(client, canvas_user)
    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'
    resp = client.get('/canvas/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'hycanvasFrame' in html
    assert '/hycanvas/' in html
    set_cookie = resp.headers.getlist('Set-Cookie')
    assert any('hycanvas_token=' in c for c in set_cookie)


def test_canvas_create_preset_and_custom(client, canvas_user, app):
    _login(client, canvas_user)
    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'

    with patch('app.blueprints.canvas.hycanvas_create_design', return_value='hy-design-1') as mock_create:
        resp = client.post(
            '/canvas/create',
            data={
                'name': 'Quartals-Deck',
                'preset': 'presentation',
                'visibility': 'private',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert '/canvas/' in resp.location and '/edit' in resp.location
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs['design_type'] == 'presentation'
        assert kwargs['width'] == 1920
        assert kwargs['height'] == 1080

    doc = CanvasDocument.query.filter_by(name='Quartals-Deck').first()
    assert doc is not None
    assert doc.hycanvas_design_id == 'hy-design-1'

    with patch('app.blueprints.canvas.hycanvas_create_design', return_value='hy-design-2'):
        resp2 = client.post(
            '/canvas/create',
            data={
                'name': 'Custom Board',
                'preset': 'custom',
                'custom_width': '1200',
                'custom_height': '900',
                'visibility': 'private',
            },
            follow_redirects=False,
        )
        assert resp2.status_code == 302

    doc2 = CanvasDocument.query.filter_by(name='Custom Board').first()
    assert doc2 is not None
    assert doc2.width == 1200
    assert doc2.height == 900


def test_canvas_edit_sets_sso_cookie_and_renders_header(client, canvas_user, app):
    _login(client, canvas_user)
    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'

    doc = CanvasDocument(
        name='Team Whiteboard',
        design_type='whiteboard',
        preset_key='whiteboard',
        width=1920,
        height=1080,
        hycanvas_design_id='hy-wb-42',
        created_by=canvas_user.id,
        visibility='private',
    )
    db.session.add(doc)
    db.session.commit()

    resp = client.get(f'/canvas/{doc.id}/edit')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'canvasSaveBtn' in html
    assert '/hycanvas/design/hy-wb-42' in html
    set_cookie = resp.headers.getlist('Set-Cookie')
    assert any('hycanvas_token=' in c for c in set_cookie)


def test_canvas_save_snapshot_and_delete(client, canvas_user, app, tmp_path):
    _login(client, canvas_user)
    app.config['UPLOAD_FOLDER'] = str(tmp_path)

    doc = CanvasDocument(
        name='Snapshot Doc',
        design_type='whiteboard',
        preset_key='whiteboard',
        width=1920,
        height=1080,
        hycanvas_design_id='hy-snap-1',
        created_by=canvas_user.id,
        visibility='private',
    )
    db.session.add(doc)
    db.session.commit()

    with (
        patch('app.blueprints.canvas.hycanvas_export_hyc', return_value=b'{"version":1}'),
        patch('app.blueprints.canvas.hycanvas_export_thumbnail', return_value=b'\x89PNG\r\n\x1a\n'),
    ):
        resp = client.post(f'/canvas/{doc.id}/save', json={'name': 'Snapshot Doc v2'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['snapshot_saved'] is True

    db.session.refresh(doc)
    assert doc.name == 'Snapshot Doc v2'
    assert doc.file_path and os.path.exists(doc.file_path)
    assert doc.thumbnail_path and os.path.exists(doc.thumbnail_path)

    thumb_resp = client.get(f'/canvas/{doc.id}/thumbnail')
    assert thumb_resp.status_code == 200

    with patch('app.blueprints.canvas.hycanvas_delete_design') as mock_del:
        del_resp = client.post(f'/canvas/{doc.id}/delete', follow_redirects=False)
        assert del_resp.status_code == 302
        mock_del.assert_called_once()
        assert mock_del.call_args.args == ('hy-snap-1',)

    assert CanvasDocument.query.get(doc.id) is None


def test_canvas_signed_avatar_endpoint(client, canvas_user, app, tmp_path):
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    profiles_dir = tmp_path / 'profile_pics'
    profiles_dir.mkdir(parents=True, exist_ok=True)
    avatar_file = profiles_dir / 'tester.png'
    avatar_file.write_bytes(b'\x89PNG\r\n\x1a\nfake')

    canvas_user.profile_picture = 'tester.png'
    db.session.commit()

    token = sign_canvas_avatar_token(canvas_user.id)
    resp = client.get(f'/canvas/avatar/{token}')
    assert resp.status_code == 200
    assert resp.data.startswith(b'\x89PNG')


def test_canvas_auth_cookie_cache_skips_redundant_login(client, canvas_user, app):
    _login(client, canvas_user)
    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'

    with patch('app.blueprints.canvas.authenticate_hycanvas_session', return_value=None) as mock_auth:
        resp1 = client.get('/canvas/')
        assert resp1.status_code == 200
        assert mock_auth.call_count == 1

        # Second request within TTL with hycanvas_token cookie present skips re-auth
        resp2 = client.get('/canvas/')
        assert resp2.status_code == 200
        assert mock_auth.call_count == 1


def _create_admin(app):
    admin = User(
        email='canvas-admin@example.com',
        first_name='Admin',
        last_name='Tester',
        is_admin=True,
        is_active=True,
        is_email_confirmed=True,
    )
    admin.set_password('StrongPass!12345')
    db.session.add(admin)
    db.session.commit()
    return admin


def test_admin_modules_lists_hycanvas_only_when_installed(client, app):
    admin = _create_admin(app)
    _login(client, admin)

    with patch('app.utils.canvas.is_hycanvas_installed', return_value=False):
        resp = client.get('/settings/admin/modules')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="module_canvas"' not in html

    with patch('app.utils.canvas.is_hycanvas_installed', return_value=True):
        resp = client.get('/settings/admin/modules')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="module_canvas"' in html


def test_admin_modules_post_forces_canvas_off_when_not_installed(client, app):
    admin = _create_admin(app)
    _login(client, admin)

    with patch('app.utils.canvas.is_hycanvas_installed', return_value=False):
        resp = client.post(
            '/settings/admin/modules',
            data={'module_canvas': 'on'},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302)

    setting = SystemSettings.query.filter_by(key='module_canvas').first()
    assert setting is not None
    assert setting.value == 'False'


def test_is_hycanvas_installed_reflects_status(app):
    from app.utils.canvas import is_hycanvas_installed

    with app.app_context():
        with patch('app.utils.canvas.get_hycanvas_status', return_value=(False, None)):
            assert is_hycanvas_installed() is False
        with patch('app.utils.canvas.get_hycanvas_status', return_value=(True, '1.2.3')):
            assert is_hycanvas_installed() is True


def test_canvas_syncs_theme_and_language_across_cache_and_html(client, canvas_user, app):
    canvas_user.dark_mode = True
    canvas_user.language = 'en'
    db.session.commit()

    _login(client, canvas_user)
    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'

    with patch('app.blueprints.canvas.authenticate_hycanvas_session', return_value=None) as mock_auth:
        resp1 = client.get('/canvas/')
        assert resp1.status_code == 200
        html1 = resp1.get_data(as_text=True)
        assert '"dark"' in html1
        assert '"en"' in html1
        assert mock_auth.call_count == 1

        # Changing language invalidates the HyCanvas auth cache even within TTL
        canvas_user.language = 'de'
        db.session.commit()
        resp2 = client.get('/canvas/')
        assert resp2.status_code == 200
        html2 = resp2.get_data(as_text=True)
        assert '"de"' in html2
        assert mock_auth.call_count == 2


def test_build_hycanvas_sso_jwt_includes_theme_and_language(app, canvas_user):
    import jwt as pyjwt
    from app.utils.canvas import build_hycanvas_sso_jwt

    canvas_user.dark_mode = True
    canvas_user.language = 'pt'
    db.session.commit()

    app.config['HYCANVAS_JWT_SECRET'] = 'test-hycanvas-secret-1234567890'
    token = build_hycanvas_sso_jwt(canvas_user)
    assert token is not None
    claims = pyjwt.decode(token, 'test-hycanvas-secret-1234567890', algorithms=['HS256'])
    assert claims['theme'] == 'dark'
    assert claims['locale'] == 'pt'
    assert claims['language'] == 'pt'
