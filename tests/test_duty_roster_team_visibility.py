from app import db
from app.models.team import Team, TeamMember
from app.models.user import User


def _create_user(email: str, *, is_admin: bool = False) -> User:
    user = User(
        email=email,
        first_name='Test',
        last_name='User',
        is_admin=is_admin,
        is_active=True,
        is_email_confirmed=True,
    )
    user.set_password('Secret123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email: str, password: str = 'Secret123!@#'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=False)


def test_admin_only_sees_own_teams_in_duty_roster(client, app):
    with app.app_context():
        admin = _create_user('roster_admin@example.com', is_admin=True)
        team_member_of = Team(name='Alpha Roster Team')
        team_not_member_of = Team(name='Beta Hidden Team')
        db.session.add_all([team_member_of, team_not_member_of])
        db.session.flush()
        db.session.add(TeamMember(team_id=team_member_of.id, user_id=admin.id))
        db.session.commit()
        other_team_id = team_not_member_of.id

    _login(client, 'roster_admin@example.com')

    resp = client.get('/duty-roster/team')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Alpha Roster Team' in body
    assert 'Beta Hidden Team' not in body

    resp_other = client.get(f'/duty-roster/team?team_id={other_team_id}')
    assert resp_other.status_code == 200
    body_other = resp_other.get_data(as_text=True)
    assert 'Alpha Roster Team' in body_other
    assert 'Beta Hidden Team' not in body_other


def test_admin_without_teams_sees_no_teams_in_duty_roster(client, app):
    with app.app_context():
        _create_user('roster_admin_empty@example.com', is_admin=True)
        team_other = Team(name='Gamma Unassigned Team')
        db.session.add(team_other)
        db.session.commit()

    _login(client, 'roster_admin_empty@example.com')

    resp = client.get('/duty-roster/team')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Gamma Unassigned Team' not in body
