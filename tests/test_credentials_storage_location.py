import pytest
from cryptography.fernet import Fernet

from app import db
from app.models.credential import Credential, CredentialFolder
from app.models.team import Team, TeamMember
from app.models.user import User


@pytest.fixture
def cred_setup(app, monkeypatch):
    monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    with app.app_context():
        user = User(
            email='cred_tester@example.com',
            first_name='Cred',
            last_name='Tester',
            is_admin=True,
            is_active=True,
            is_email_confirmed=True,
            has_full_access=True,
        )
        user.set_password('TestPass123!')
        db.session.add(user)
        db.session.flush()

        team = Team(name='Team Alpha')
        db.session.add(team)
        db.session.flush()
        db.session.add(TeamMember(team_id=team.id, user_id=user.id))
        db.session.commit()
        return {'user_id': user.id, 'team_id': team.id}


def _login(client, email='cred_tester@example.com', password='TestPass123!'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def test_folder_linked_to_bereich_on_create_and_update(app, client, cred_setup):
    _login(client)
    team_id = cred_setup['team_id']

    # Create folder explicitly in team Bereich
    resp = client.post(
        '/credentials/folders/create',
        data={'name': 'Server', 'color': '#123456', 'visibility': f'team:{team_id}'},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        folder = CredentialFolder.query.filter_by(name='Server').first()
        assert folder is not None
        assert folder.visibility == 'team'
        assert folder.team_id == team_id

        cred = Credential(
            website_url='https://example.com',
            website_name='Example',
            username='admin',
            folder_id=folder.id,
            visibility='team',
            team_id=team_id,
            created_by=cred_setup['user_id'],
        )
        cred.set_password('secret', Fernet.generate_key())
        db.session.add(cred)
        db.session.commit()
        folder_id = folder.id
        cred_id = cred.id

    # Update folder to private -> contained credential moves to private too
    resp = client.post(
        f'/credentials/folders/{folder_id}/update',
        data={'name': 'Server Privat', 'color': '#654321', 'visibility': 'private'},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        folder = db.session.get(CredentialFolder, folder_id)
        cred = db.session.get(Credential, cred_id)
        assert folder.name == 'Server Privat'
        assert folder.visibility == 'private'
        assert folder.team_id is None
        assert cred.visibility == 'private'
        assert cred.team_id is None


def test_create_form_shows_speicherort_and_saves_bereich_and_folder(app, client, cred_setup):
    _login(client)
    team_id = cred_setup['team_id']

    with app.app_context():
        priv_folder = CredentialFolder(
            name='Banking',
            visibility='private',
            created_by=cred_setup['user_id'],
        )
        team_folder = CredentialFolder(
            name='DevOps',
            visibility='team',
            team_id=team_id,
            created_by=cred_setup['user_id'],
        )
        db.session.add_all([priv_folder, team_folder])
        db.session.commit()
        team_folder_id = team_folder.id

    # GET /credentials/create shows Speicherort with "Bereich / Ordner"
    resp = client.get('/credentials/create')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="storage_location"' in html
    assert 'Speicherort' in html
    assert 'Privat / Banking' in html
    assert 'Team Alpha / DevOps' in html
    assert 'name="folder_id"' not in html

    # POST with storage_location = folder:<team_folder_id>
    resp = client.post(
        '/credentials/create',
        data={
            'website_name': 'GitLab',
            'website_url': 'https://gitlab.example.com',
            'username': 'devops',
            'password': 'super-secret-password',
            'storage_location': f'folder:{team_folder_id}',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        cred = Credential.query.filter_by(website_name='GitLab').first()
        assert cred is not None
        assert cred.folder_id == team_folder_id
        assert cred.visibility == 'team'
        assert cred.team_id == team_id
        cred_id = cred.id

    # POST edit with storage_location = scope:private
    resp = client.post(
        f'/credentials/edit/{cred_id}',
        data={
            'website_name': 'GitLab',
            'website_url': 'https://gitlab.example.com',
            'username': 'devops',
            'password': '',
            'storage_location': 'scope:private',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        cred = db.session.get(Credential, cred_id)
        assert cred.folder_id is None
        assert cred.visibility == 'private'
        assert cred.team_id is None
