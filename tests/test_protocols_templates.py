"""Tests for protocol templates and attendance checklist start flow."""

from datetime import date, time

from app import db
from app.models import (
    Protocol,
    ProtocolAgendaItem,
    ProtocolTemplate,
    ProtocolTemplateAgendaItem,
    SystemSettings,
    Team,
    TeamMember,
    User,
)


def _create_user(email: str, label: str, is_admin: bool = False) -> User:
    u = User(
        email=email,
        first_name='Test',
        last_name=label,
        is_active=True,
        is_email_confirmed=True,
        is_admin=is_admin,
        has_full_access=True,
    )
    u.set_password('Secret123!@#')
    db.session.add(u)
    db.session.commit()
    return u


def _enable_protocols_module():
    row = SystemSettings.query.filter_by(key='module_protocols').first()
    if not row:
        row = SystemSettings(key='module_protocols', value='true')
        db.session.add(row)
    else:
        row.value = 'true'
    db.session.commit()


def _login(client, user: User):
    res = client.post('/login', data={'email': user.email, 'password': 'Secret123!@#'}, follow_redirects=False)
    assert res.status_code in (200, 302)


def test_template_create_edit_and_delete(app, client):
    _enable_protocols_module()
    user = _create_user('tpl1@example.com', 'Tpl1', is_admin=True)
    _login(client, user)

    res = client.post(
        '/protocols/templates/create',
        data={
            'title': 'Vorstandssitzung',
            'members_text': 'Anna, Ben, Clara',
            'visibility': 'public',
            'titles': ['Begrüßung', 'Finanzen', 'Sonstiges'],
            'item_ids': ['', '', ''],
        },
        follow_redirects=False,
    )
    assert res.status_code == 302
    tpl = ProtocolTemplate.query.filter_by(title='Vorstandssitzung').first()
    assert tpl is not None
    assert tpl.members_list() == ['Anna', 'Ben', 'Clara']
    assert [it.title for it in tpl.agenda_items] == ['Begrüßung', 'Finanzen', 'Sonstiges']

    # Edit template: update title, members, reorder/update TOPs
    res_edit = client.post(
        f'/protocols/templates/{tpl.id}/edit',
        data={
            'title': 'Vorstandssitzung (NEU)',
            'members_text': 'Anna, Ben, Clara, David',
            'visibility': 'public',
            'titles': ['Finanzen', 'Begrüßung'],
            'item_ids': [str(tpl.agenda_items[1].id), str(tpl.agenda_items[0].id)],
        },
        follow_redirects=False,
    )
    assert res_edit.status_code == 302
    db.session.refresh(tpl)
    assert tpl.title == 'Vorstandssitzung (NEU)'
    assert tpl.members_list() == ['Anna', 'Ben', 'Clara', 'David']
    assert [it.title for it in tpl.agenda_items] == ['Finanzen', 'Begrüßung']

    # Delete template
    res_del = client.post(f'/protocols/templates/{tpl.id}/delete', follow_redirects=False)
    assert res_del.status_code == 302
    assert db.session.get(ProtocolTemplate, tpl.id) is None


def test_start_protocol_from_template_with_attendance(app, client):
    _enable_protocols_module()
    user = _create_user('tpl2@example.com', 'Tpl2', is_admin=True)
    _login(client, user)

    tpl = ProtocolTemplate(
        title='Gesamtteamsitzung',
        members_text='Alice, Bob, Charlie',
        visibility='public',
        created_by=user.id,
    )
    db.session.add(tpl)
    db.session.flush()
    db.session.add_all([
        ProtocolTemplateAgendaItem(template_id=tpl.id, position=0, title='TOP 1: Rückblick'),
        ProtocolTemplateAgendaItem(template_id=tpl.id, position=1, title='TOP 2: Planung'),
    ])
    db.session.commit()

    # GET start page renders checklist
    res_get = client.get(f'/protocols/templates/{tpl.id}/start')
    assert res_get.status_code == 200
    html = res_get.get_data(as_text=True)
    assert 'Alice' in html
    assert 'Bob' in html
    assert 'Charlie' in html
    assert 'TOP 1: Rückblick' in html

    # POST start with attendance choices + extra guest -> redirects straight to TOP 1
    res_post = client.post(
        f'/protocols/templates/{tpl.id}/start',
        data={
            'title': 'Gesamtteamsitzung KW 48',
            'meeting_date': '2026-11-25',
            'start_time': '19:00',
            'visibility': 'public',
            'member_count': '3',
            'member_name_0': 'Alice',
            'member_status_0': 'present',
            'member_name_1': 'Bob',
            'member_status_1': 'excused',
            'member_name_2': 'Charlie',
            'member_status_2': 'absent',
            'extra_participants_text': 'Gast Dana',
            'titles': ['TOP 1: Rückblick', 'TOP 2: Planung'],
            'action': 'start',
        },
        follow_redirects=False,
    )
    assert res_post.status_code == 302

    protocol = Protocol.query.filter_by(title='Gesamtteamsitzung KW 48').first()
    assert protocol is not None
    assert protocol.participants_text == 'Alice, Gast Dana'
    assert protocol.excused_text == 'Bob'
    assert protocol.absent_text == 'Charlie'
    assert [it.title for it in protocol.agenda_items] == ['TOP 1: Rückblick', 'TOP 2: Planung']
    assert f'/protocols/{protocol.id}/item/{protocol.agenda_items[0].id}' in res_post.headers['Location']


def test_save_existing_protocol_as_template(app, client):
    _enable_protocols_module()
    user = _create_user('tpl3@example.com', 'Tpl3', is_admin=True)
    _login(client, user)

    protocol = Protocol(
        title='Technik-Runde',
        meeting_date=date(2026, 11, 20),
        start_time=time(18, 30),
        participants_text='Max, Moritz',
        excused_text='Lea',
        absent_text='Tom',
        visibility='public',
        created_by=user.id,
    )
    db.session.add(protocol)
    db.session.flush()
    db.session.add_all([
        ProtocolAgendaItem(protocol_id=protocol.id, position=0, title='Server-Update'),
        ProtocolAgendaItem(protocol_id=protocol.id, position=1, title='Backup-Test'),
    ])
    db.session.commit()

    res = client.post(f'/protocols/{protocol.id}/save-as-template', follow_redirects=False)
    assert res.status_code == 302
    tpl = ProtocolTemplate.query.filter_by(title='Technik-Runde').first()
    assert tpl is not None
    assert tpl.members_list() == ['Max', 'Moritz', 'Lea', 'Tom']
    assert [it.title for it in tpl.agenda_items] == ['Server-Update', 'Backup-Test']
    assert f'/protocols/templates/{tpl.id}/edit' in res.headers['Location']


def test_team_template_visibility_isolation(app, client):
    _enable_protocols_module()
    owner = _create_user('owner@example.com', 'Owner')
    outsider = _create_user('outsider@example.com', 'Outsider')

    team = Team(name='Geheimteam')
    db.session.add(team)
    db.session.flush()
    db.session.add(TeamMember(team_id=team.id, user_id=owner.id))

    tpl = ProtocolTemplate(
        title='Interne Teamsitzung',
        members_text='Owner',
        visibility='team',
        team_id=team.id,
        created_by=owner.id,
    )
    db.session.add(tpl)
    db.session.commit()

    _login(client, outsider)
    res_list = client.get('/protocols/templates')
    assert res_list.status_code == 200
    assert 'Interne Teamsitzung' not in res_list.get_data(as_text=True)

    res_start = client.get(f'/protocols/templates/{tpl.id}/start', follow_redirects=False)
    assert res_start.status_code == 302
    assert '/protocols' in res_start.headers['Location']
