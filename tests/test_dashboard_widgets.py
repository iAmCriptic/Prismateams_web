from datetime import date, datetime, time, timedelta

from app import db
from app.models.booking import BookingRequest, BookingRoom
from app.models.booking_personal import BookingPersonalEvent
from app.models.duty_roster import DutyRoster, DutyRosterColumn, DutyRosterDay, DutyRosterEntry
from app.models.event import Event
from app.models.excalidraw import ExcalidrawDrawing
from app.models.kanban import KanbanBoard, KanbanCard, KanbanCardAssignee, KanbanList
from app.models.protocol import Protocol
from app.models.settings import SystemSettings
from app.models.survey import Survey
from app.models.team import Team
from app.models.user import User


def _create_admin():
    user = User(
        email='dash_admin@example.com',
        first_name='Dash',
        last_name='Admin',
        is_admin=True,
        is_active=True,
        is_email_confirmed=True,
    )
    user.set_password('Secret123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email='dash_admin@example.com', password='Secret123!@#'):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=False)


def test_dashboard_renders_all_widgets_empty_and_populated(client, app):
    with app.app_context():
        user = _create_admin()
        today = date.today()

        # Booking Personal
        bp_event = BookingPersonalEvent(name='Festival Lineup', start_date=today, is_active=True)
        db.session.add(bp_event)

        # Raumbuchung
        room = BookingRoom(name='Saal 1', is_active=True)
        db.session.add(room)
        db.session.flush()
        req_pending = BookingRequest(event_name='Offene Anfrage', email='a@example.com', status='pending', room_id=room.id)
        req_accepted = BookingRequest(
            event_name='Bestätigtes Meeting',
            email='b@example.com',
            status='accepted',
            room_id=room.id,
            event_date=today + timedelta(days=1),
            event_start_time=time(10, 0),
            event_end_time=time(12, 0),
        )
        db.session.add_all([req_pending, req_accepted])

        # Kanban
        board = KanbanBoard(title='Roadmap', visibility='public', created_by=user.id)
        db.session.add(board)
        db.session.flush()
        klist = KanbanList(board_id=board.id, title='Todo', position=0)
        db.session.add(klist)
        db.session.flush()
        card = KanbanCard(
            list_id=klist.id,
            title='Widget bauen',
            created_by=user.id,
            due_date=datetime.utcnow() + timedelta(days=2),
        )
        db.session.add(card)
        db.session.flush()
        db.session.add(KanbanCardAssignee(card_id=card.id, user_id=user.id))

        # Veranstaltungen
        ev = Event(name='Sommerfest', start_date=today + timedelta(days=3), owner_id=user.id, created_by=user.id)
        db.session.add(ev)

        # Umfragen
        survey = Survey(title='Team-Umfrage', created_by=user.id, visibility='public', is_active=True)
        db.session.add(survey)

        # Protokolle
        proto = Protocol(
            title='Wochenmeeting',
            meeting_date=today,
            start_time=time(9, 0),
            visibility='public',
            created_by=user.id,
        )
        db.session.add(proto)

        # Dienstplan
        team = Team(name='Technik')
        db.session.add(team)
        db.session.flush()
        roster = DutyRoster(team_id=team.id, year=today.year, month=today.month, is_published=True)
        db.session.add(roster)
        db.session.flush()
        rday = DutyRosterDay(roster_id=roster.id, date=today + timedelta(days=1))
        rcol = DutyRosterColumn(roster_id=roster.id, user_id=user.id, sort_order=0)
        db.session.add_all([rday, rcol])
        db.session.flush()
        db.session.add(DutyRosterEntry(day_id=rday.id, column_id=rcol.id, start_time=time(8, 0), end_time=time(16, 0), label='Frühschicht'))

        # Excalidraw
        drawing = ExcalidrawDrawing(
            name='Architektur',
            file_path='arch.excalidraw',
            created_by=user.id,
            visibility='public',
            room_id=ExcalidrawDrawing.generate_room_id(),
            room_key=ExcalidrawDrawing.generate_room_key(),
        )
        db.session.add(drawing)
        db.session.commit()

        # Enable all widget types for user
        all_types = [
            'termine', 'veranstaltungen', 'dienstplan',
            'buchungen', 'raumbuchung_kommende', 'booking_personal',
            'nachrichten', 'emails', 'kontakte',
            'kanban_meine_karten', 'kanban_aenderungen',
            'neue_wikieintraege', 'meine_wikis', 'protokolle', 'excalidraw',
            'dateien', 'passwoerter', 'meine_ausleihen', 'umfragen',
        ]
        user.set_dashboard_config({
            'widgets': [{'id': f'w_{i}', 'type': wt, 'w': 1, 'h': 2, 'grid_v': 2} for i, wt in enumerate(all_types)]
        })

    _login(client)
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for expected in [
        'Festival Lineup',
        'Bestätigtes Meeting',
        'Widget bauen',
        'Sommerfest',
        'Team-Umfrage',
        'Wochenmeeting',
        'Frühschicht',
        'Architektur',
        'dashboardWidgetModalDialog',
    ]:
        assert expected in html


def test_dashboard_options_and_size_config_api(client, app):
    with app.app_context():
        _create_admin()
        db.session.add(SystemSettings(key='module_surveys', value='true'))
        db.session.add(SystemSettings(key='module_excalidraw', value='false'))
        db.session.commit()

    _login(client)
    opt_resp = client.get('/api/dashboard/options')
    assert opt_resp.status_code == 200
    opts = opt_resp.get_json()
    assert 'categories' in opts
    types_map = {wt['type']: wt for wt in opts['widget_types']}
    assert 'booking_personal' in types_map
    assert 'raumbuchung_kommende' in types_map
    assert 'kanban_meine_karten' in types_map
    assert types_map['kanban_meine_karten']['configurable'] is True
    assert 'icon' in types_map['booking_personal']
    assert 'category' in types_map['booking_personal']
    # Disabled module must not appear
    assert 'excalidraw' not in types_map

    # Size management persists via /api/dashboard/config
    save_resp = client.post('/api/dashboard/config', json={
        'widgets': [
            {'id': 'w1', 'type': 'booking_personal', 'w': 2, 'h': 4, 'x': 1, 'y': 1, 'grid_v': 2},
            {'id': 'w2', 'type': 'kanban_meine_karten', 'w': 2, 'h': 3, 'x': 3, 'y': 1, 'grid_v': 2, 'board_ids': []},
        ]
    })
    assert save_resp.status_code == 200
    cfg = save_resp.get_json()['config']
    assert len(cfg['widgets']) == 2
    assert cfg['widgets'][0]['w'] == 2
    assert cfg['widgets'][0]['h'] == 4
    assert cfg['widgets'][1]['x'] == 3


def test_dashboard_guest_renders_cleanly(client, app):
    with app.app_context():
        guest = User(
            email='dash_guest@example.com',
            first_name='Gast',
            last_name='User',
            is_guest=True,
            is_active=True,
            is_email_confirmed=True,
        )
        guest.set_password('Secret123!@#')
        db.session.add(guest)
        db.session.commit()

    _login(client, email='dash_guest@example.com')
    resp = client.get('/dashboard')
    assert resp.status_code == 200


def test_dashboard_mobile_and_pc_sizes_are_independent(client, app):
    with app.app_context():
        _create_admin()

    _login(client)
    save_resp = client.post('/api/dashboard/config', json={
        'widgets': [
            {
                'id': 'wm1', 'type': 'termine',
                'w': 3, 'h': 4, 'x': 1, 'y': 1,
                'mobile_w': 1, 'mobile_h': 3, 'mobile_x': 1, 'mobile_y': 1,
                'grid_v': 2,
            },
            {
                'id': 'wm2', 'type': 'nachrichten',
                'w': 1, 'h': 2, 'x': 4, 'y': 1,
                'mobile_w': 1, 'mobile_h': 2, 'mobile_x': 2, 'mobile_y': 1,
                'grid_v': 2,
            },
        ]
    })
    assert save_resp.status_code == 200
    widgets = {w['id']: w for w in save_resp.get_json()['config']['widgets']}
    assert widgets['wm1']['w'] == 3 and widgets['wm1']['h'] == 4 and widgets['wm1']['x'] == 1
    assert widgets['wm1']['mobile_w'] == 1 and widgets['wm1']['mobile_h'] == 3 and widgets['wm1']['mobile_x'] == 1
    assert widgets['wm2']['w'] == 1 and widgets['wm2']['h'] == 2 and widgets['wm2']['x'] == 4
    assert widgets['wm2']['mobile_w'] == 1 and widgets['wm2']['mobile_h'] == 2 and widgets['wm2']['mobile_x'] == 2

    # Update only mobile size of wm1 to full width (2) -> wm2 mobile_x/y should repack, PC sizes untouched
    update_resp = client.post('/api/dashboard/config', json={
        'widgets': [
            {**widgets['wm1'], 'mobile_w': 2, 'mobile_h': 5},
            widgets['wm2'],
        ]
    })
    assert update_resp.status_code == 200
    updated = {w['id']: w for w in update_resp.get_json()['config']['widgets']}
    assert updated['wm1']['w'] == 3 and updated['wm1']['h'] == 4 and updated['wm1']['x'] == 1
    assert updated['wm2']['w'] == 1 and updated['wm2']['h'] == 2 and updated['wm2']['x'] == 4
    assert updated['wm1']['mobile_w'] == 2 and updated['wm1']['mobile_h'] == 5
    assert updated['wm2']['mobile_y'] >= 6  # repacked below wm1 (y=1..5)

    dash_resp = client.get('/dashboard')
    assert dash_resp.status_code == 200
    html = dash_resp.get_data(as_text=True)
    assert 'data-mobile-col-span="2"' in html
    assert 'data-mobile-row-span="5"' in html
    assert '--dash-mw: 2;' in html
    assert '--dash-mh: 5;' in html


def test_default_dashboard_widgets_start_with_todos(app):
    with app.app_context():
        user = _create_admin()
        config = user.get_dashboard_config()
        widget_types = [w['type'] for w in config['widgets']]
        assert widget_types == ['todos', 'nachrichten', 'emails', 'passwoerter']
