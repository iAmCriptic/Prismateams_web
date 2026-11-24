"""Tests for portal-wide Nextcloud integration in the Files module."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app import db
from app.models.file import File, Folder
from app.models.settings import SystemSettings
from app.models.team import Team, TeamMember
from app.models.user import User
from app.utils.cloud_import.base import RemoteEntry
from app.utils.cloud_import.nextcloud import NextcloudLockError
from app.utils.integrations import get_nextcloud_credentials, nextcloud_configured
from app.utils.nextcloud_settings import (
    SETTING_NC_ENABLED,
    SETTING_NC_EUROOFFICE,
    SETTING_NC_MD_EDIT,
    SETTING_NC_MODE,
    SETTING_NC_PRIVATE_BASE,
    SETTING_NC_PRIVATE_ENABLED,
    SETTING_NC_PUBLIC_ACCESS,
    SETTING_NC_PUBLIC_ENABLED,
    SETTING_NC_PUBLIC_PATH,
    SETTING_NC_TEAM_MAPPINGS,
    SETTING_NC_WEBDAV_LOCKS,
    can_access_nextcloud_public,
    get_files_storage_mode,
    get_team_nextcloud_mapping,
)
from app.utils.nextcloud_storage import (
    acquire_nextcloud_lock,
    ensure_nextcloud_root_folder,
    invalidate_sync_cache,
    release_nextcloud_lock_if_unused,
    sync_folder_children,
    write_file_bytes,
)
from app.utils.private_files import hard_delete_file_disk_and_db, soft_delete_file
from app.utils.system_settings_cache import invalidate_system_settings_cache


@pytest.fixture(autouse=True)
def _clear_files_caches():
    invalidate_system_settings_cache()
    invalidate_sync_cache()
    yield
    invalidate_system_settings_cache()
    invalidate_sync_cache()


class FakeNextcloudProvider:
    """In-memory WebDAV Nextcloud mock for integration tests."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = {'', 'Public', 'Teams', 'Teams/Alpha', 'Ablage'}
        self.locks: dict[str, tuple[str, str]] = {}  # path -> (token, owner)
        self.deleted_paths: list[str] = []
        self.moved_paths: list[tuple[str, str]] = []
        self.unlocked_tokens: list[str] = []

    def test_connection(self):
        return None

    def list_children(self, path_or_id: str = ''):
        base = (path_or_id or '').strip('/')
        entries = []
        for d in sorted(self.dirs):
            if not d or d == base:
                continue
            parent = d.rsplit('/', 1)[0] if '/' in d else ''
            if parent == base:
                entries.append(RemoteEntry(id=d, name=d.rsplit('/', 1)[-1], is_dir=True, path=d))
        for p, data in sorted(self.files.items()):
            parent = p.rsplit('/', 1)[0] if '/' in p else ''
            if parent == base:
                entries.append(
                    RemoteEntry(
                        id=p,
                        name=p.rsplit('/', 1)[-1],
                        is_dir=False,
                        size=len(data),
                        path=p,
                        etag=f'etag-{len(data)}',
                    )
                )
        return entries

    def download_bytes(self, path: str) -> bytes:
        norm = path.strip('/')
        if norm not in self.files:
            raise ConnectionError('nextcloud_download_failed:404')
        return self.files[norm]

    def upload_bytes(self, path: str, data: bytes, *, content_type=None, lock_token=None) -> str:
        norm = path.strip('/')
        if norm in self.locks and self.locks[norm][0] != lock_token:
            raise NextcloudLockError('locked', owner=self.locks[norm][1])
        self.files[norm] = data
        return f'etag-{len(data)}'

    def create_folder(self, path: str) -> None:
        norm = path.strip('/')
        if norm:
            self.dirs.add(norm)

    def move_entry(self, src_path: str, dst_path: str, *, overwrite=False, lock_token=None) -> None:
        s = src_path.strip('/')
        d = dst_path.strip('/')
        self.moved_paths.append((s, d))
        if s in self.files:
            self.files[d] = self.files.pop(s)
        elif s in self.dirs:
            self.dirs.discard(s)
            self.dirs.add(d)

    def delete_entry(self, path: str, *, lock_token=None) -> None:
        norm = path.strip('/')
        self.deleted_paths.append(norm)
        self.files.pop(norm, None)
        self.dirs.discard(norm)

    def lock_resource(self, path: str, *, owner='PrismaTeams', timeout_seconds=300):
        norm = path.strip('/')
        if norm in self.locks:
            raise NextcloudLockError('locked', owner=self.locks[norm][1])
        token = f'opaquelocktoken:{norm}'
        self.locks[norm] = (token, owner)
        return token, datetime.utcnow() + timedelta(seconds=timeout_seconds)

    def refresh_lock(self, path: str, lock_token: str, *, timeout_seconds=300):
        norm = path.strip('/')
        if norm in self.locks and self.locks[norm][0] != lock_token:
            raise NextcloudLockError('locked', owner=self.locks[norm][1])
        return datetime.utcnow() + timedelta(seconds=timeout_seconds)

    def unlock_resource(self, path: str, lock_token: str) -> None:
        norm = path.strip('/')
        self.unlocked_tokens.append(lock_token)
        if norm in self.locks and self.locks[norm][0] == lock_token:
            self.locks.pop(norm, None)


def _create_user(username='alice', is_admin=False):
    u = User(
        email=f'{username}@example.com',
        first_name=username.title(),
        last_name='Test',
        is_active=True,
        is_admin=is_admin,
        is_guest=False,
        is_email_confirmed=True,
        has_full_access=True,
    )
    u.set_password('Password123!@#')
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, user):
    client.post('/logout', follow_redirects=True)
    client.post('/login', data={
        'email': user.email,
        'password': 'Password123!@#',
    }, follow_redirects=True)


def _set_setting(key: str, value: str):
    row = SystemSettings.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(SystemSettings(key=key, value=value))
    db.session.commit()


def test_portal_wide_nextcloud_credentials_save_and_test(app, client):
    admin = _create_user('admin', is_admin=True)
    _login(client, admin)

    resp = client.post('/settings/admin/integrations', data={
        'nextcloud_url': 'https://cloud.example.com/',
        'nextcloud_username': 'portal_svc',
        'nextcloud_password': 'app-password-123',
    })
    assert resp.status_code in (200, 302)
    assert nextcloud_configured() is True
    creds = get_nextcloud_credentials(include_password=True)
    assert creds['server_url'] == 'https://cloud.example.com'
    assert creds['username'] == 'portal_svc'
    assert creds['app_password'] == 'app-password-123'

    # Saving with blank password keeps existing encrypted password
    client.post('/settings/admin/integrations', data={
        'nextcloud_url': 'https://cloud.example.com',
        'nextcloud_username': 'portal_svc',
        'nextcloud_password': '',
    })
    assert get_nextcloud_credentials(include_password=True)['app_password'] == 'app-password-123'

    with patch('app.utils.cloud_import.nextcloud.NextcloudProvider.test_connection', return_value=None):
        test_resp = client.post('/settings/admin/integrations/nextcloud/test', json={})
        assert test_resp.status_code == 200
        assert test_resp.get_json()['success'] is True


def test_file_settings_modes_team_mapping_and_public_restrictions(app, client):
    admin = _create_user('admin2', is_admin=True)
    member = _create_user('member', is_admin=False)
    team = Team(name='Alpha')
    db.session.add(team)
    db.session.commit()
    db.session.add(TeamMember(team_id=team.id, user_id=member.id))
    db.session.commit()

    _login(client, admin)
    resp = client.post('/settings/admin/file-settings', data={
        'files_max_file_value': '100',
        'files_max_file_unit': 'MB',
        'files_quota_value': '15',
        'files_quota_unit': 'GB',
        'files_trash_retention_days': '30',
        'files_nextcloud_enabled': 'on',
        'files_storage_mode': 'hybrid',
        'files_nextcloud_eurooffice_enabled': 'on',
        'files_nextcloud_markdown_enabled': 'on',
        'files_nextcloud_webdav_locks_enabled': 'on',
        'files_nextcloud_private_enabled': 'on',
        'files_nextcloud_private_base_path': '/Ablage',
        'files_nextcloud_public_enabled': 'on',
        'files_nextcloud_public_path': '/Public',
        'files_nextcloud_public_access': 'read_only',
        f'nc_team_enabled_{team.id}': 'on',
        f'nc_team_path_{team.id}': '/Teams/Alpha',
    })
    assert resp.status_code in (200, 302)
    assert get_files_storage_mode() == 'hybrid'
    assert get_team_nextcloud_mapping(team.id) == {'path': '/Teams/Alpha', 'enabled': True}
    assert can_access_nextcloud_public(member, write=False) is True
    assert can_access_nextcloud_public(member, write=True) is False
    assert can_access_nextcloud_public(admin, write=True) is True

    _set_setting(SETTING_NC_PUBLIC_ACCESS, 'admins_only')
    assert can_access_nextcloud_public(member, write=False) is False
    assert can_access_nextcloud_public(admin, write=False) is True


def test_shadow_sync_trash_and_permanent_delete(app):
    invalidate_sync_cache()
    admin = _create_user('admin3', is_admin=True)
    fake = FakeNextcloudProvider()
    fake.files['Public/notes.md'] = b'# Hello Nextcloud'

    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        root = ensure_nextcloud_root_folder(
            space='public',
            user_id=admin.id,
            remote_path='/Public',
            name='Public',
        )
        sync_folder_children(root, user_id=admin.id, force=True)
        fobj = File.query.filter_by(folder_id=root.id, name='notes.md').first()
        assert fobj is not None
        assert fobj.storage_backend == 'nextcloud'
        assert fobj.remote_path == 'Public/notes.md'

        # Soft-delete stays in portal trash only; Nextcloud still has the file
        soft_delete_file(fobj, admin.id)
        db.session.commit()
        assert 'Public/notes.md' in fake.files
        assert 'Public/notes.md' not in fake.deleted_paths

        # Permanent delete removes from Nextcloud via WebDAV DELETE
        import os
        hard_delete_file_disk_and_db(fobj, os)
        db.session.commit()
        assert 'Public/notes.md' in fake.deleted_paths
        assert 'Public/notes.md' not in fake.files


def test_webdav_locks_and_markdown_eurooffice_roundtrip(app, client):
    invalidate_sync_cache()
    _set_setting(SETTING_NC_ENABLED, 'true')
    _set_setting(SETTING_NC_MODE, 'nextcloud')
    _set_setting(SETTING_NC_EUROOFFICE, 'true')
    _set_setting(SETTING_NC_MD_EDIT, 'true')
    _set_setting(SETTING_NC_WEBDAV_LOCKS, 'true')
    _set_setting(SETTING_NC_PUBLIC_ENABLED, 'true')
    _set_setting(SETTING_NC_PUBLIC_PATH, '/Public')
    _set_setting(SETTING_NC_PUBLIC_ACCESS, 'all')

    alice = _create_user('alice_lock', is_admin=False)
    bob = _create_user('bob_lock', is_admin=False)
    fake = FakeNextcloudProvider()
    fake.files['Public/readme.md'] = b'# Initial'
    fake.files['Public/doc.docx'] = b'PK-DOCX-DATA'

    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        root = ensure_nextcloud_root_folder(space='public', user_id=alice.id, remote_path='/Public', name='Public')
        sync_folder_children(root, user_id=alice.id, force=True)
        md_file = File.query.filter_by(folder_id=root.id, name='readme.md').first()
        docx_file = File.query.filter_by(folder_id=root.id, name='doc.docx').first()

        alice_client = app.test_client()
        bob_client = app.test_client()

        # Alice opens Markdown editor -> acquires portal + Nextcloud WebDAV lock
        _login(alice_client, alice)
        get_resp = alice_client.get(f'/files/edit/{md_file.id}')
        assert get_resp.status_code == 200
        assert b'# Initial' in get_resp.data
        assert 'Public/readme.md' in fake.locks

        # Alice saves -> writes via WebDAV PUT with lock token
        save_resp = alice_client.post(
            f'/files/edit/{md_file.id}',
            data={'content': '# Updated by Alice'},
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        assert save_resp.status_code == 200
        assert fake.files['Public/readme.md'] == b'# Updated by Alice'

        # Bob tries to open in a separate browser session -> blocked by exclusive lock
        _login(bob_client, bob)
        bob_resp = bob_client.get(f'/files/edit/{md_file.id}')
        assert bob_resp.status_code == 200
        assert b'gesperrt' in bob_resp.data

        # Alice releases lock -> Nextcloud UNLOCK called
        _login(alice_client, alice)
        rel_resp = alice_client.post('/files/api/edit-lock', json={'action': 'leave', 'file_id': md_file.id})
        assert rel_resp.status_code == 200
        assert rel_resp.get_json().get('released') is True
        assert 'Public/readme.md' not in fake.locks

        # Euro-Office: acquire lock, write callback bytes, release on leave
        ok, err = acquire_nextcloud_lock(docx_file, 'Alice')
        assert ok is True and err is None
        assert 'Public/doc.docx' in fake.locks
        write_file_bytes(docx_file, b'PK-UPDATED-DOCX')
        assert fake.files['Public/doc.docx'] == b'PK-UPDATED-DOCX'
        release_nextcloud_lock_if_unused(docx_file)
        assert 'Public/doc.docx' not in fake.locks


def test_hybrid_sidebar_and_prefs(app, client):
    invalidate_sync_cache()
    _set_setting(SETTING_NC_ENABLED, 'true')
    _set_setting(SETTING_NC_MODE, 'hybrid')
    _set_setting(SETTING_NC_PRIVATE_ENABLED, 'true')
    _set_setting(SETTING_NC_PRIVATE_BASE, '/Ablage')
    _set_setting(SETTING_NC_PUBLIC_ENABLED, 'true')
    _set_setting(SETTING_NC_PUBLIC_PATH, '/Public')

    user = _create_user('hybrid_user', is_admin=False)
    _login(client, user)

    prefs_resp = client.post('/files/api/sidebar-prefs', json={
        'order': ['nextcloud', 'portal'],
        'collapsed': {'portal': True, 'nextcloud': False},
    })
    assert prefs_resp.status_code == 200

    fake = FakeNextcloudProvider()
    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        page = client.get('/files/?view=nc_public')
        assert page.status_code == 200
        assert b'Nextcloud' in page.data
        assert b'data-files-sidebar-groups' in page.data


def test_nextcloud_root_create_upload_version_zip_move_and_favorites(app, client):
    import io
    import zipfile
    from app.models.file import File, Folder
    from app.utils.nextcloud_storage import ensure_nextcloud_root_folder, upload_nextcloud_file
    from app.utils.private_files import soft_delete_folder, toggle_folder_favorite

    invalidate_sync_cache()
    _set_setting(SETTING_NC_ENABLED, 'true')
    _set_setting(SETTING_NC_MODE, 'nextcloud')
    _set_setting(SETTING_NC_PRIVATE_ENABLED, 'true')
    _set_setting(SETTING_NC_PRIVATE_BASE, '/Ablage')
    _set_setting(SETTING_NC_PUBLIC_ENABLED, 'true')
    _set_setting(SETTING_NC_PUBLIC_PATH, '/Public')
    _set_setting(SETTING_NC_PUBLIC_ACCESS, 'all')

    user = _create_user('nc_ops_user', is_admin=False)
    _login(client, user)

    fake = FakeNextcloudProvider()
    fake.dirs.update({'Ablage/nc_ops_user', 'Public'})

    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        # 1. Create folder at nc_ablage root (no parent_id in form)
        resp = client.post('/files/create-folder', data={
            'folder_name': 'RootSub',
            'view': 'nc_ablage',
        })
        assert resp.status_code in (302, 200)
        assert 'Ablage/nc_ops_user/RootSub' in fake.dirs
        sub_folder = Folder.query.filter_by(name='RootSub', storage_backend='nextcloud').first()
        assert sub_folder is not None

        # 2. Upload file at nc_ablage root, then overwrite with conflict_strategy='version'
        up1 = client.post('/files/upload', data={
            'view': 'nc_ablage',
            'file': (io.BytesIO(b'v1-content'), 'notes.txt'),
        }, content_type='multipart/form-data')
        assert up1.status_code in (302, 200)
        assert fake.files.get('Ablage/nc_ops_user/notes.txt') == b'v1-content'

        up2 = client.post('/files/upload', data={
            'view': 'nc_ablage',
            'conflict_strategy': 'version',
            'file': (io.BytesIO(b'v2-content'), 'notes.txt'),
        }, content_type='multipart/form-data')
        assert up2.status_code in (302, 200)
        assert fake.files.get('Ablage/nc_ops_user/notes.txt') == b'v2-content'
        fobj = File.query.filter_by(name='notes.txt', storage_backend='nextcloud', is_current=True).first()
        assert fobj is not None
        assert fobj.version_number == 2

        # 3. Move destinations include Nextcloud spaces, and move works
        dest_resp = client.get('/files/api/move-destinations')
        assert dest_resp.status_code == 200
        keys = {s['key'] for s in dest_resp.get_json()['spaces']}
        assert 'nc_ablage' in keys
        assert 'nc_public' in keys

        mv_resp = client.post('/files/move', json={
            'item_type': 'file',
            'item_id': fobj.id,
            'target_folder_id': sub_folder.id,
        })
        assert mv_resp.status_code == 200
        assert 'Ablage/nc_ops_user/RootSub/notes.txt' in fake.files

        # 4. ZIP download includes Nextcloud files
        zip_resp = client.post('/files/api/download-zip', json={
            'items': [{'type': 'folder', 'id': sub_folder.id}],
        })
        assert zip_resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(zip_resp.data))
        assert 'RootSub/notes.txt' in zf.namelist()
        assert zf.read('RootSub/notes.txt') == b'v2-content'

        # 5. toggle_folder_favorite on deleted folder returns 4-tuple without TypeError
        soft_delete_folder(sub_folder, user.id)
        db.session.commit()
        ok, is_fav, msg, cnt = toggle_folder_favorite(user, sub_folder.id)
        assert ok is False and is_fav is False and isinstance(msg, str) and cnt == 0


def test_nextcloud_public_file_view_restriction(app, client):
    from app.utils.nextcloud_storage import ensure_nextcloud_root_folder, upload_nextcloud_file
    from app.utils.private_files import can_view_file

    invalidate_sync_cache()
    _set_setting(SETTING_NC_ENABLED, 'true')
    _set_setting(SETTING_NC_MODE, 'nextcloud')
    _set_setting(SETTING_NC_PUBLIC_ENABLED, 'true')
    _set_setting(SETTING_NC_PUBLIC_PATH, '/Public')
    _set_setting(SETTING_NC_PUBLIC_ACCESS, 'admins_only')

    admin = _create_user('nc_pub_admin', is_admin=True)
    user = _create_user('nc_pub_user', is_admin=False)

    fake = FakeNextcloudProvider()
    fake.dirs.add('Public')
    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        pub_root = ensure_nextcloud_root_folder(
            space='public', user_id=admin.id, remote_path='/Public', name='Public'
        )
        fobj = upload_nextcloud_file(pub_root, 'secret.txt', b'admin-only', user_id=admin.id, mime_type='text/plain')
        assert can_view_file(fobj, admin) is True
        assert can_view_file(fobj, user) is False


def test_nextcloud_public_path_root_and_custom_folder_persist(app, client):
    from app.utils.nextcloud_settings import get_nextcloud_public_path, normalize_remote_path

    assert normalize_remote_path('/') == '/'
    assert normalize_remote_path('///') == '/'
    assert normalize_remote_path('') == ''
    assert normalize_remote_path(None) == ''
    assert normalize_remote_path('Shared/Team') == '/Shared/Team'

    admin = _create_user('nc_path_admin', is_admin=True)
    _login(client, admin)

    # Selecting Nextcloud root '/' must persist as '/' and not fall back to '/Public'
    resp = client.post('/settings/admin/file-settings', data={
        'files_max_file_value': '100',
        'files_max_file_unit': 'MB',
        'files_quota_value': '15',
        'files_quota_unit': 'GB',
        'files_trash_retention_days': '30',
        'files_nextcloud_enabled': 'on',
        'files_storage_mode': 'nextcloud',
        'files_nextcloud_private_base_path': '/',
        'files_nextcloud_public_enabled': 'on',
        'files_nextcloud_public_path': '/',
        'files_nextcloud_public_access': 'all',
    })
    assert resp.status_code in (200, 302)
    assert get_nextcloud_public_path() == '/'

    # Selecting a custom folder must persist as that folder
    resp2 = client.post('/settings/admin/file-settings', data={
        'files_max_file_value': '100',
        'files_max_file_unit': 'MB',
        'files_quota_value': '15',
        'files_quota_unit': 'GB',
        'files_trash_retention_days': '30',
        'files_nextcloud_enabled': 'on',
        'files_storage_mode': 'nextcloud',
        'files_nextcloud_private_base_path': '/Privat',
        'files_nextcloud_public_enabled': 'on',
        'files_nextcloud_public_path': '/Gemeinsam/Dokumente',
        'files_nextcloud_public_access': 'all',
    })
    assert resp2.status_code in (200, 302)
    assert get_nextcloud_public_path() == '/Gemeinsam/Dokumente'


def test_nextcloud_propfind_parses_owner_and_timestamps():
    from app.utils.cloud_import.nextcloud import NextcloudProvider

    xml_payload = b'''<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" xmlns:nc="http://nextcloud.org/ns">
      <d:response>
        <d:href>/remote.php/dav/files/svc_user/Public/</d:href>
        <d:propstat>
          <d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
          <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
      </d:response>
      <d:response>
        <d:href>/remote.php/dav/files/svc_user/Public/Unterordner/</d:href>
        <d:propstat>
          <d:prop>
            <d:displayname>Unterordner</d:displayname>
            <d:resourcetype><d:collection/></d:resourcetype>
            <d:getlastmodified>Tue, 10 Nov 2026 12:30:00 GMT</d:getlastmodified>
            <oc:owner-id>erika.muster</oc:owner-id>
            <oc:owner-display-name></oc:owner-display-name>
          </d:prop>
          <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
      </d:response>
      <d:response>
        <d:href>/remote.php/dav/files/svc_user/Public/Bericht.pdf</d:href>
        <d:propstat>
          <d:prop>
            <d:displayname>Bericht.pdf</d:displayname>
            <d:getcontentlength>2048</d:getcontentlength>
            <d:getetag>"abc123"</d:getetag>
            <d:getcontenttype>application/pdf</d:getcontenttype>
            <d:resourcetype/>
            <d:getlastmodified>Wed, 11 Nov 2026 15:45:00 GMT</d:getlastmodified>
            <oc:owner-display-name>Max Mustermann</oc:owner-display-name>
            <oc:owner-id>max.mustermann</oc:owner-id>
            <nc:creation_time>1794300000</nc:creation_time>
          </d:prop>
          <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
      </d:response>
    </d:multistatus>'''

    class _FakeResp:
        status_code = 207
        content = xml_payload

    provider = NextcloudProvider('https://cloud.example.org', 'svc_user', 'secret')
    with patch.object(provider._session, 'request', return_value=_FakeResp()):
        entries = provider.list_children('Public')

    assert len(entries) == 2
    folder_entry, file_entry = entries[0], entries[1]
    assert folder_entry.is_dir is True
    assert folder_entry.owner == 'erika.muster'
    assert folder_entry.modified_at == datetime(2026, 11, 10, 12, 30, 0)
    assert folder_entry.created_at == datetime(2026, 11, 10, 12, 30, 0)

    assert file_entry.is_dir is False
    assert file_entry.owner == 'Max Mustermann'
    assert file_entry.modified_at == datetime(2026, 11, 11, 15, 45, 0)
    assert file_entry.created_at == datetime(2026, 11, 10, 8, 40, 0)


def test_nextcloud_sync_and_ui_show_remote_owner_and_dates(app, client):
    from app.utils.nextcloud_settings import upsert_nextcloud_setting

    admin = _create_user('nc_owner_admin', is_admin=True)
    _login(client, admin)

    upsert_nextcloud_setting(SETTING_NC_ENABLED, 'true')
    upsert_nextcloud_setting(SETTING_NC_MODE, 'nextcloud')
    upsert_nextcloud_setting(SETTING_NC_PUBLIC_ENABLED, 'true')
    upsert_nextcloud_setting(SETTING_NC_PUBLIC_PATH, '/Public')
    upsert_nextcloud_setting(SETTING_NC_PUBLIC_ACCESS, 'all')
    db.session.commit()

    nc_created = datetime(2025, 5, 1, 9, 15, 0)
    nc_modified = datetime(2025, 6, 2, 14, 20, 0)

    class _OwnerAwareProvider(FakeNextcloudProvider):
        def list_children(self, path_or_id: str = ''):
            base = (path_or_id or '').strip('/')
            if base == 'Public':
                return [
                    RemoteEntry(
                        id='Public/TeamDoku',
                        name='TeamDoku',
                        is_dir=True,
                        path='Public/TeamDoku',
                        owner='Erika Musterfrau',
                        created_at=nc_created,
                        modified_at=nc_modified,
                    ),
                    RemoteEntry(
                        id='Public/Protokoll.pdf',
                        name='Protokoll.pdf',
                        is_dir=False,
                        size=4096,
                        path='Public/Protokoll.pdf',
                        etag='etag-v1',
                        content_type='application/pdf',
                        owner='Max Mustermann',
                        created_at=nc_created,
                        modified_at=nc_modified,
                    ),
                ]
            return []

    fake = _OwnerAwareProvider()
    with patch('app.utils.nextcloud_storage.get_portal_nextcloud_provider', return_value=fake):
        pub_root = ensure_nextcloud_root_folder(
            space='public', user_id=admin.id, remote_path='/Public', name='Public'
        )
        # Pre-existing shadow row created earlier with admin as uploader and no remote_owner
        stale_file = File(
            name='Protokoll.pdf',
            original_name='Protokoll.pdf',
            folder_id=pub_root.id,
            uploaded_by=admin.id,
            file_path='nextcloud://Public/Protokoll.pdf',
            file_size=4096,
            mime_type='application/pdf',
            version_number=1,
            is_current=True,
            space='public',
            storage_backend='nextcloud',
            remote_path='Public/Protokoll.pdf',
            remote_etag='etag-v1',
        )
        db.session.add(stale_file)
        db.session.commit()

        sync_folder_children(pub_root, user_id=admin.id, force=True)

        synced_folder = Folder.query.filter_by(parent_id=pub_root.id, name='TeamDoku').first()
        assert synced_folder is not None
        assert synced_folder.remote_owner == 'Erika Musterfrau'
        assert synced_folder.created_at == nc_created
        assert synced_folder.updated_at == nc_modified

        db.session.refresh(stale_file)
        assert stale_file.remote_owner == 'Max Mustermann'
        assert stale_file.created_at == nc_created
        assert stale_file.updated_at == nc_modified

        # Browse page and file-details API must show Nextcloud author instead of admin
        page_resp = client.get(f'/files/folder/{pub_root.id}?view=nc_public')
        assert page_resp.status_code == 200
        html = page_resp.get_data(as_text=True)
        assert 'Max Mustermann' in html
        assert 'Erika Musterfrau' in html

        details_resp = client.get(f'/files/api/file-details/{stale_file.id}')
        assert details_resp.status_code == 200
        payload = details_resp.get_json()
        assert payload['success'] is True
        assert payload['file']['uploader'] == 'Max Mustermann'
        assert '01.05.2025' in payload['file']['created_at']


