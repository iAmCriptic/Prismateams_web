from __future__ import annotations

from app import db
from app.models.settings import SystemSettings
from app.models.user import User
from app.utils import system_settings_cache as cache_mod


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}

    def get(self, key: str):
        val = self.store.get(key)
        return str(val) if val is not None else None

    def incr(self, key: str):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]


def _create_admin() -> User:
    admin = User(
        email='admin_mod_test@example.com',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_email_confirmed=True,
        is_admin=True,
    )
    admin.set_password('SecretPass123!')
    db.session.add(admin)
    db.session.commit()
    return admin


def test_cross_worker_cache_invalidation_via_redis_version(app, monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, '_get_redis_client', lambda: fake_redis)
    cache_mod.invalidate_system_settings_cache(bump_remote=False)

    db.session.add(SystemSettings(key='module_chat', value='True', description='test'))
    db.session.commit()
    assert fake_redis.get(cache_mod._REDIS_VERSION_KEY) == '1'

    # Worker A loads and caches 'True' under remote version '1'
    assert cache_mod.get_setting('module_chat') == 'True'

    # Simulate Worker B updating DB and bumping Redis version (without touching Worker A's _process_map)
    row = SystemSettings.query.filter_by(key='module_chat').first()
    row.value = 'False'
    # Flush without commit: remote version must NOT be bumped yet
    db.session.flush()
    assert fake_redis.get(cache_mod._REDIS_VERSION_KEY) == '1'

    # Now commit: after_commit bumps Redis version to '2'
    db.session.commit()
    assert fake_redis.get(cache_mod._REDIS_VERSION_KEY) == '2'

    # Simulate another worker having stale _process_map from before commit
    with cache_mod._process_lock:
        cache_mod._process_map = {'module_chat': 'True'}
        cache_mod._process_loaded_at = 1e18  # far in the future so TTL would not expire
        cache_mod._process_version = '1'

    # Next read must detect version mismatch ('1' != '2') and reload 'False' from DB
    assert cache_mod.get_setting('module_chat') == 'False'


def test_rollback_does_not_bump_remote_version(app, monkeypatch):
    fake_redis = _FakeRedis()
    monkeypatch.setattr(cache_mod, '_get_redis_client', lambda: fake_redis)
    cache_mod.invalidate_system_settings_cache(bump_remote=False)

    db.session.add(SystemSettings(key='module_wiki', value='True', description='test'))
    db.session.commit()
    ver_after_commit = fake_redis.get(cache_mod._REDIS_VERSION_KEY)

    row = SystemSettings.query.filter_by(key='module_wiki').first()
    row.value = 'False'
    db.session.flush()
    db.session.rollback()

    assert fake_redis.get(cache_mod._REDIS_VERSION_KEY) == ver_after_commit
    assert cache_mod.get_setting('module_wiki') == 'True'


def test_admin_modules_get_ignores_stale_process_cache(app, client):
    _create_admin()
    db.session.add(SystemSettings(key='module_chat', value='True', description='test'))
    db.session.commit()

    login_resp = client.post('/login', data={
        'email': 'admin_mod_test@example.com',
        'password': 'SecretPass123!',
    }, follow_redirects=False)
    assert login_resp.status_code in (302, 303)

    # Simulate POST on Worker A: disable module_chat
    resp = client.post(
        '/settings/admin/modules',
        data={'module_files': 'on'},
        headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    # Simulate Worker B still having stale _process_map (even without Redis)
    with cache_mod._process_lock:
        cache_mod._process_map = {'module_chat': 'True'}
        cache_mod._process_loaded_at = 1e18

    page = client.get('/settings/admin/modules')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    # module_chat checkbox must NOT be checked
    assert 'id="module_chat" name="module_chat"\n                       checked' not in html
    assert 'id="module_chat" name="module_chat" checked' not in html
