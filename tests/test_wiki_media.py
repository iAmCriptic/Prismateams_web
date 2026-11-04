import io
import os
import pytest
from app import db
from app.models.user import User
from app.models.settings import SystemSettings
from app.utils.markdown import process_markdown, extract_youtube_id, extract_vimeo_id


def test_youtube_id_extraction():
    assert extract_youtube_id('dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert extract_youtube_id('https://www.youtube.com/watch?v=dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert extract_youtube_id('https://youtu.be/dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert extract_youtube_id('https://www.youtube.com/embed/dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert extract_youtube_id('https://www.youtube.com/shorts/dQw4w9WgXcQ') == 'dQw4w9WgXcQ'
    assert extract_youtube_id('invalid_link') is None


def test_vimeo_id_extraction():
    assert extract_vimeo_id('76979871') == '76979871'
    assert extract_vimeo_id('https://vimeo.com/76979871') == '76979871'
    assert extract_vimeo_id('https://player.vimeo.com/video/76979871') == '76979871'


def test_process_markdown_video_image_syntax(app):
    with app.app_context():
        content = "![Demo Video](/wiki/media/demo.mp4)"
        html = process_markdown(content, wiki_mode=True)
        assert '<video' in html
        assert 'src="/wiki/media/demo.mp4"' in html
        assert 'controls' in html
        assert '<figcaption class="wiki-video-caption">Demo Video</figcaption>' in html


def test_process_markdown_youtube_embed(app):
    with app.app_context():
        content = "Hier ist ein Video:\nhttps://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        html = process_markdown(content, wiki_mode=True)
        assert '<iframe' in html
        assert 'youtube-nocookie.com/embed/dQw4w9WgXcQ' in html
        assert 'wiki-video-responsive' in html


def test_process_markdown_directives(app):
    with app.app_context():
        content = "@[youtube](dQw4w9WgXcQ)\n\n@[video](/wiki/media/local.mp4)"
        html = process_markdown(content, wiki_mode=True)
        assert 'youtube-nocookie.com/embed/dQw4w9WgXcQ' in html
        assert 'src="/wiki/media/local.mp4"' in html


def test_process_markdown_bleach_sanitizes_unsafe_iframe(app):
    with app.app_context():
        unsafe_content = '<iframe src="http://evil.com/malicious"></iframe>'
        html = process_markdown(unsafe_content, wiki_mode=True)
        assert 'evil.com' not in html


def test_process_markdown_allows_safe_html5_video(app):
    with app.app_context():
        safe_video = '<video controls src="/wiki/media/test.mp4"><source src="/wiki/media/test.mp4" type="video/mp4"></video>'
        html = process_markdown(safe_video, wiki_mode=True)
        assert '<video' in html
        assert 'src="/wiki/media/test.mp4"' in html


def _login_test_user(client):
    user = User.query.filter_by(email='wiki_admin@example.com').first()
    if not user:
        user = User(
            email='wiki_admin@example.com',
            first_name='Wiki',
            last_name='Admin',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True
        )
        user.set_password('AdminPassword123!')
        db.session.add(user)

    s = SystemSettings.query.filter_by(key='module_wiki').first()
    if not s:
        db.session.add(SystemSettings(key='module_wiki', value='True'))
    else:
        s.value = 'True'

    db.session.commit()

    resp = client.post('/login', data={
        'email': 'wiki_admin@example.com',
        'password': 'AdminPassword123!'
    }, follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_wiki_upload_media_api(client, app):
    with app.app_context():
        _login_test_user(client)

        # Test valid image upload
        img_data = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01')
        resp = client.post(
            '/wiki/api/upload-media',
            data={'file': (img_data, 'test_image.png')},
            content_type='multipart/form-data'
        )
        print('RESP STATUS:', resp.status_code, 'LOC:', resp.headers.get('Location'))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['is_image'] is True
        assert data['is_video'] is False
        assert '/wiki/media/' in data['url']
        assert '![' in data['markdown']

        # Test valid video upload
        vid_data = io.BytesIO(b'\x00\x00\x00\x18ftypmp42')
        resp_vid = client.post(
            '/wiki/api/upload-media',
            data={'file': (vid_data, 'sample_clip.mp4')},
            content_type='multipart/form-data'
        )
        assert resp_vid.status_code == 200
        vid_json = resp_vid.get_json()
        assert vid_json['success'] is True
        assert vid_json['is_video'] is True
        assert '/wiki/media/' in vid_json['url']
        uploaded_video_filename = vid_json['filename']

        # Test serving the uploaded video
        serve_resp = client.get(f'/wiki/media/{uploaded_video_filename}')
        assert serve_resp.status_code in (200, 206)

        # Test invalid file extension
        bad_data = io.BytesIO(b'MZ executable')
        bad_resp = client.post(
            '/wiki/api/upload-media',
            data={'file': (bad_data, 'malicious.exe')},
            content_type='multipart/form-data'
        )
        assert bad_resp.status_code == 400


def test_wiki_preview_api(client, app):
    with app.app_context():
        _login_test_user(client)

        resp = client.post(
            '/wiki/api/preview',
            json={'content': '### Vorschau Titel\n![Clip](/wiki/media/clip.mp4)'}
        )
        print('RESP STATUS:', resp.status_code, 'LOC:', resp.headers.get('Location'))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert '<h3' in data['html']
        assert '<video' in data['html']
