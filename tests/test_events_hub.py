from datetime import date, datetime, time, timedelta
import pytest
from app import db
from app.models.user import User
from app.models.event import (
    Event,
    EventDay,
    EventAppointment,
    EventAssignment,
    EventContact,
    EventTodoList,
    EventTodoItem,
    EventBookingPersonalLink,
    EventCustomField,
    EventCustomFieldValue,
    EventLink,
)
from app.models.file import Folder, File
from app.models.booking_personal import BookingPersonalEvent
from app.models.kanban import KanbanBoard, KanbanList, KanbanCard


@pytest.fixture
def auth_user(app):
    user = User(
        email='eventadmin@example.com',
        first_name='Event',
        last_name='Admin',
        is_active=True,
        is_admin=True,
        is_email_confirmed=True,
        has_full_access=True,
    )
    user.set_password('Password123!@#')
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, email='eventadmin@example.com', password='Password123!@#'):
    return client.post('/login', data={
        'email': email,
        'password': password
    }, follow_redirects=True)


def test_create_single_day_event(client, auth_user):
    _login(client)

    res = client.post('/events/create', data={
        'name': 'Sommerfest 2026',
        'event_mode': 'single',
        'event_date': '2026-08-20',
        'start_time': '12:00',
        'end_time': '20:00',
        'default_location': 'Festwiese',
        'description': 'Tolles Sommerfest',
    }, follow_redirects=True)
    assert res.status_code == 200

    event = Event.query.filter_by(name='Sommerfest 2026').first()
    assert event is not None
    assert event.is_multiday is False
    assert event.start_date == date(2026, 8, 20)
    assert event.end_date == date(2026, 8, 20)
    assert len(event.days) == 1
    day = event.days[0]
    assert day.day_number == 1
    assert day.date == date(2026, 8, 20)
    assert len(event.appointments) == 1
    appt = event.appointments[0]
    assert appt.day_id == day.id
    assert appt.start_time.hour == 12
    assert appt.end_time.hour == 20
    # Check standard todo list Vorbereitung
    assert len(event.todo_lists) == 1
    assert event.todo_lists[0].title == 'Vorbereitung'


def test_create_multiday_event(client, auth_user):
    _login(client)

    res = client.post('/events/create', data={
        'name': '3-Tage-Festival',
        'event_mode': 'multi',
        'start_date': '2026-09-10',
        'end_date': '2026-09-12',
        'start_time_multi': '14:00',
        'end_time_multi': '23:00',
        'default_location': 'Festivalgelände',
    }, follow_redirects=True)
    assert res.status_code == 200

    event = Event.query.filter_by(name='3-Tage-Festival').first()
    assert event is not None
    assert event.is_multiday is True
    assert event.start_date == date(2026, 9, 10)
    assert event.end_date == date(2026, 9, 12)
    assert len(event.days) == 3
    assert [d.day_number for d in event.days] == [1, 2, 3]
    assert [d.date for d in event.days] == [
        date(2026, 9, 10),
        date(2026, 9, 11),
        date(2026, 9, 12),
    ]
    assert len(event.appointments) == 3


def test_todo_lists_and_items(client, auth_user):
    _login(client)

    ev = Event(
        name='Konzert Event',
        is_multiday=True,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        owner_id=auth_user.id,
        created_by=auth_user.id,
    )
    db.session.add(ev)
    db.session.flush()

    day1 = EventDay(event_id=ev.id, day_number=1, date=date(2026, 7, 1), label='Aufbau')
    day2 = EventDay(event_id=ev.id, day_number=2, date=date(2026, 7, 2), label='Konzert')
    db.session.add_all([day1, day2])
    db.session.commit()
    ev_id = ev.id
    day1_id = day1.id

    # 1. ToDo Liste für die gesamte Veranstaltung erstellen
    res = client.post(f'/events/{ev_id}/todos/list/create', data={
        'title': 'Marketing & Promo',
        'day_id': '',
    }, follow_redirects=True)
    assert res.status_code == 200

    # 2. ToDo Liste für Tag 1 erstellen
    res = client.post(f'/events/{ev_id}/todos/list/create', data={
        'title': 'Bühnenaufbau Checkliste',
        'day_id': str(day1_id),
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    general_list = next((l for l in ev.todo_lists if l.day_id is None), None)
    assert general_list is not None
    assert general_list.title == 'Marketing & Promo'

    day1_list = next((l for l in ev.todo_lists if l.day_id == day1_id), None)
    assert day1_list is not None
    assert day1_list.title == 'Bühnenaufbau Checkliste'
    gen_list_id = general_list.id

    # 3. Item hinzufügen
    res = client.post(f'/events/{ev_id}/todos/item/create', data={
        'todo_list_id': str(gen_list_id),
        'title': 'Flyer drucken',
    }, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    item_id = data['id']

    # 4. Item abhaken (Toggle)
    res = client.post(f'/events/todos/item/{item_id}/toggle', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['is_completed'] is True
    assert data['progress'] == 100

    # 5. Item löschen
    res = client.post(f'/events/todos/item/{item_id}/delete', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    assert db.session.get(EventTodoItem, item_id) is None


def test_booking_personal_and_kanban_linking(client, auth_user):
    _login(client)

    ev = Event(
        name='Open Air Gala',
        owner_id=auth_user.id,
        created_by=auth_user.id,
    )
    db.session.add(ev)
    db.session.flush()

    bp1 = BookingPersonalEvent(name='Main Stage Bands', created_by=auth_user.id)
    bp2 = BookingPersonalEvent(name='DJ Lounge', created_by=auth_user.id)
    db.session.add_all([bp1, bp2])

    board = KanbanBoard(title='Festival Orga', created_by=auth_user.id)
    db.session.add(board)
    db.session.flush()

    k_list = KanbanList(board_id=board.id, title='Zu erledigen')
    db.session.add(k_list)
    db.session.flush()

    k_card = KanbanCard(list_id=k_list.id, title='Genehmigung Ordnungsamt', created_by=auth_user.id)
    db.session.add(k_card)
    db.session.commit()

    ev_id = ev.id
    bp1_id = bp1.id
    bp2_id = bp2.id
    board_id = board.id
    card_id = k_card.id

    # 1. Booking Liste 1 verknüpfen
    res = client.post(f'/events/{ev_id}/link/booking', data={
        'action': 'add',
        'booking_personal_event_id': str(bp1_id),
    }, follow_redirects=True)
    assert res.status_code == 200

    # 2. Booking Liste 2 verknüpfen (mehrere Booking-Listen)
    res = client.post(f'/events/{ev_id}/link/booking', data={
        'action': 'add',
        'booking_personal_event_id': str(bp2_id),
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    linked_ids = {l.booking_personal_event_id for l in ev.booking_personal_links}
    assert linked_ids == {bp1_id, bp2_id}

    # 3. Kanban Board verknüpfen
    res = client.post(f'/events/{ev_id}/link/kanban', data={
        'kanban_board_id': str(board_id),
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.kanban_board_id == board_id
    assert ev.kanban_card_id is None

    # 4. Kanban Card verknüpfen
    res = client.post(f'/events/{ev_id}/link/kanban', data={
        'kanban_board_id': str(board_id),
        'kanban_card_id': str(card_id),
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.kanban_card_id == card_id

    # 5. Kanban Unlink
    res = client.post(f'/events/{ev_id}/link/kanban', data={
        'clear': '1',
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.kanban_board_id is None
    assert ev.kanban_card_id is None


def test_link_folder(client, auth_user):
    _login(client)

    ev = Event(name='Festival Ordner Test', owner_id=auth_user.id, created_by=auth_user.id)
    folder = Folder(name='Festival Dokumente', created_by=auth_user.id)
    db.session.add_all([ev, folder])
    db.session.commit()
    ev_id = ev.id
    f_id = folder.id

    # Ordner verknüpfen
    res = client.post(f'/events/{ev_id}/link/folder', data={'folder_id': str(f_id)}, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.folder_id == f_id

    # Ordner trennen
    res = client.post(f'/events/{ev_id}/link/folder', data={'folder_id': ''}, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.folder_id is None


def test_kanban_cards_ajax_endpoint(client, auth_user):
    _login(client)

    board = KanbanBoard(title='Test Board', created_by=auth_user.id)
    db.session.add(board)
    db.session.flush()

    k_list = KanbanList(board_id=board.id, title='Backlog')
    db.session.add(k_list)
    db.session.flush()

    card1 = KanbanCard(list_id=k_list.id, title='Catering anfragen', created_by=auth_user.id)
    card2 = KanbanCard(list_id=k_list.id, title='Plakate aufhängen', created_by=auth_user.id)
    db.session.add_all([card1, card2])
    db.session.commit()

    res = client.get(f'/events/kanban/board/{board.id}/cards')
    assert res.status_code == 200
    cards_data = res.get_json()
    assert len(cards_data) == 2
    titles = [c['title'] for c in cards_data]
    assert 'Catering anfragen' in titles
    assert 'Plakate aufhängen' in titles


def test_multiday_custom_days_create(client, auth_user):
    _login(client)

    # Multi-day event with individual days, gaps/pauses, distinct locations and times
    res = client.post('/events/create', data={
        'name': 'Sommertournee 2026',
        'event_mode': 'multi',
        'default_location': 'Zentrale Bühne',
        'multi_day_date[]': ['2026-07-01', '2026-07-05', '2026-07-10'],
        'multi_day_start[]': ['11:00', '15:00', '18:00'],
        'multi_day_end[]': ['17:00', '22:00', '23:30'],
        'multi_day_location[]': ['Berlin Arena', 'Hamburg Dockland', 'München Halle'],
        'multi_day_label[]': ['Tour-Auftakt', 'Zwischenstopp', 'Finale'],
    }, follow_redirects=True)
    assert res.status_code == 200

    event = Event.query.filter_by(name='Sommertournee 2026').first()
    assert event is not None
    assert event.is_multiday is True
    assert event.start_date == date(2026, 7, 1)
    assert event.end_date == date(2026, 7, 10)
    assert len(event.days) == 3

    days = event.days
    assert days[0].date == date(2026, 7, 1)
    assert days[0].location == 'Berlin Arena'
    assert days[0].label == 'Tour-Auftakt'
    assert days[0].start_time.hour == 11

    assert days[1].date == date(2026, 7, 5)
    assert days[1].location == 'Hamburg Dockland'
    assert days[1].label == 'Zwischenstopp'
    assert days[1].start_time.hour == 15

    assert days[2].date == date(2026, 7, 10)
    assert days[2].location == 'München Halle'
    assert days[2].label == 'Finale'
    assert days[2].end_time.minute == 30


def test_todo_due_time_and_update(client, auth_user):
    _login(client)

    ev = Event(name='ToDo Detail Test', owner_id=auth_user.id, created_by=auth_user.id)
    tl = EventTodoList(event=ev, title='Logistik', created_by=auth_user.id)
    db.session.add_all([ev, tl])
    db.session.commit()

    # 1. Item mit Fälligkeitsdatum und Endzeit erstellen
    res = client.post(f'/events/{ev.id}/todos/item/create', data={
        'todo_list_id': str(tl.id),
        'title': 'Mikrofone einpacken',
        'assigned_to_user_id': str(auth_user.id),
        'due_date': '2026-06-15',
        'due_time': '16:30',
    }, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['due_time'] == '16:30'
    item_id = data['id']

    item = db.session.get(EventTodoItem, item_id)
    assert item.due_time.hour == 16
    assert item.due_time.minute == 30
    assert item.assigned_to_user_id == auth_user.id

    # 2. Item bearbeiten (Update)
    res = client.post(f'/events/todos/item/{item_id}/update', data={
        'title': 'Funkmikrofone testen und einpacken',
        'assigned_to_user_id': '',
        'due_date': '2026-06-16',
        'due_time': '18:00',
    }, follow_redirects=True)
    assert res.status_code == 200

    db.session.refresh(item)
    assert item.title == 'Funkmikrofone testen und einpacken'
    assert item.assigned_to_user_id is None
    assert item.due_date == date(2026, 6, 16)
    assert item.due_time.hour == 18


def test_owner_and_people_management(client, auth_user):
    _login(client)

    other_user = User(
        email='copartner@example.com',
        first_name='Co',
        last_name='Partner',
        is_active=True,
        is_email_confirmed=True,
    )
    other_user.set_password('Password123!@#')
    db.session.add(other_user)
    db.session.flush()

    ev = Event(name='Management Test Event', owner_id=auth_user.id, created_by=auth_user.id)
    db.session.add(ev)
    db.session.commit()
    ev_id = ev.id
    other_user_id = other_user.id

    # 1. Verantwortlichen ändern
    res = client.post(f'/events/{ev_id}/owner', data={
        'owner_id': str(other_user_id),
    }, follow_redirects=True)
    assert res.status_code == 200
    ev = db.session.get(Event, ev_id)
    assert ev.owner_id == other_user_id

    # 2. Personal zuordnen
    res = client.post(f'/events/{ev_id}/assignments/add', data={
        'user_id': str(auth_user.id),
        'role': 'Projektleiter',
    }, follow_redirects=True)
    assert res.status_code == 200
    ev = db.session.get(Event, ev_id)
    assert len(ev.assignments) == 1
    assert ev.assignments[0].user_id == auth_user.id
    assert ev.assignments[0].role == 'Projektleiter'
    assignment_id = ev.assignments[0].id

    # 3. Personal entfernen
    res = client.post(f'/events/{ev_id}/assignments/{assignment_id}/delete', follow_redirects=True)
    assert res.status_code == 200
    ev = db.session.get(Event, ev_id)
    assert len(ev.assignments) == 0

    # 4. Ansprechpartner hinzufügen
    res = client.post(f'/events/{ev_id}/contacts/add', data={
        'name': 'Frau Müller',
        'role': 'Event-Managerin',
        'phone': '+49 123 456789',
        'email': 'mueller@location.de',
    }, follow_redirects=True)
    assert res.status_code == 200
    ev = db.session.get(Event, ev_id)
    assert len(ev.contacts) == 1
    contact = ev.contacts[0]
    assert contact.name == 'Frau Müller'
    assert contact.email == 'mueller@location.de'
    contact_id = contact.id

    # 5. Ansprechpartner löschen
    res = client.post(f'/events/{ev_id}/contacts/{contact_id}/delete', follow_redirects=True)
    assert res.status_code == 200
    ev = db.session.get(Event, ev_id)
    assert len(ev.contacts) == 0


def test_admin_events_custom_fields(client, auth_user):
    _login(client)

    # 1. Standard-Felder laden
    res = client.post('/settings/admin/events', data={
        'action': 'load_defaults'
    }, follow_redirects=True)
    assert res.status_code == 200
    fields = EventCustomField.query.all()
    assert len(fields) >= 15
    assert any(f.label == 'EPISODE' and f.field_type == 'number' for f in fields)
    assert any(f.label == 'ALTERSBESCHRÄNKUNG' and f.field_type == 'select' for f in fields)
    assert any(f.label == 'VA LEITUNG' and f.field_type == 'person' for f in fields)

    # 2. Eigenes Feld anlegen
    res = client.post('/settings/admin/events', data={
        'action': 'add_field',
        'label': 'CATERING FIRMA',
        'field_type': 'text',
        'placeholder': 'Name des Caterers',
    }, follow_redirects=True)
    assert res.status_code == 200
    cat_field = EventCustomField.query.filter_by(label='CATERING FIRMA').first()
    assert cat_field is not None
    assert cat_field.field_type == 'text'
    assert cat_field.placeholder == 'Name des Caterers'

    # 3. Feld bearbeiten
    res = client.post('/settings/admin/events', data={
        'action': 'edit_field',
        'field_id': str(cat_field.id),
        'label': 'CATERING PREMIUM',
        'field_type': 'text',
        'placeholder': 'Premium Caterer',
    }, follow_redirects=True)
    assert res.status_code == 200
    db.session.refresh(cat_field)
    assert cat_field.label == 'CATERING PREMIUM'

    # 4. Feld löschen
    res = client.post('/settings/admin/events', data={
        'action': 'delete_field',
        'field_id': str(cat_field.id),
    }, follow_redirects=True)
    assert res.status_code == 200
    assert EventCustomField.query.filter_by(label='CATERING PREMIUM').first() is None


def test_event_custom_fields_save_and_display(client, auth_user):
    _login(client)

    # Erstelle Custom Fields
    f_episode = EventCustomField(label='EPISODE', field_type='number', position=10)
    f_check = EventCustomField(label='VVK VIA T4G?', field_type='checkbox', position=20)
    f_lead = EventCustomField(label='VA LEITUNG', field_type='person', position=30)
    db.session.add_all([f_episode, f_check, f_lead])
    db.session.commit()

    # Event anlegen
    ev = Event(name='Custom Fields Event', owner_id=auth_user.id, created_by=auth_user.id)
    db.session.add(ev)
    db.session.commit()
    ev_id = ev.id

    # Speichern via Form
    res = client.post(f'/events/{ev_id}/custom-fields/save', data={
        f'field_{f_episode.id}': '42',
        f'field_{f_check.id}': '1',
        f'field_{f_lead.id}': str(auth_user.id),
    }, follow_redirects=True)
    assert res.status_code == 200

    ev = db.session.get(Event, ev_id)
    assert ev.custom_values_dict[f_episode.id] == '42'
    assert ev.custom_values_dict[f_check.id] == '1'
    assert ev.custom_values_dict[f_lead.id] == str(auth_user.id)

    # Prüfe Darstellung in view_event (HTML)
    res_get = client.get(f'/events/{ev_id}')
    assert res_get.status_code == 200
    content = res_get.data.decode('utf-8')
    assert 'Infos zur Veranstaltung' in content
    assert 'EPISODE' in content
    assert '42' in content
    assert 'VVK VIA T4G?' in content
    assert 'VA LEITUNG' in content


def test_hide_day_todos_when_empty(client, auth_user):
    _login(client)

    # Event mit 2 Tagen anlegen
    ev = Event(name='ToDo Visibility Test', owner_id=auth_user.id, created_by=auth_user.id)
    db.session.add(ev)
    db.session.flush()

    day1 = EventDay(event_id=ev.id, day_number=1, date=date(2026, 7, 1))
    day2 = EventDay(event_id=ev.id, day_number=2, date=date(2026, 7, 2))
    # Nur eine Liste für die GESAMTE Veranstaltung (day_id=None)
    todo_general = EventTodoList(event_id=ev.id, title='Allgemeines', created_by=auth_user.id, day_id=None)
    db.session.add_all([day1, day2, todo_general])
    db.session.commit()
    ev_id = ev.id
    day1_id = day1.id

    # 1. Prüfe Ansicht: Da keine Tages-ToDos existieren, darf "ToDos nach Tagen" NICHT angezeigt werden
    res = client.get(f'/events/{ev_id}?tab=todos')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'Gesamte Veranstaltung' in html
    assert 'Allgemeines' in html
    assert 'ToDos nach Tagen' not in html

    # 2. Jetzt eine Tages-ToDo-Liste hinzufügen
    res_add = client.post(f'/events/{ev_id}/todos/list/create', data={
        'title': 'Aufbau Tag 1',
        'day_id': str(day1_id),
    }, follow_redirects=True)
    assert res_add.status_code == 200

    # 3. Nun MUSS "ToDos nach Tagen" gerendert werden
    res2 = client.get(f'/events/{ev_id}?tab=todos')
    assert res2.status_code == 200
    html2 = res2.data.decode('utf-8')
    assert 'ToDos nach Tagen' in html2
    assert 'Aufbau Tag 1' in html2


def test_event_links_and_files_overview(client, auth_user):
    _login(client)

    # 1. Event mit verknüpftem Ordner & Datei anlegen
    folder = Folder(name='Event Folder', created_by=auth_user.id)
    db.session.add(folder)
    db.session.flush()

    file_obj = File(
        name='Ablaufplan.pdf',
        original_name='Ablaufplan.pdf',
        file_path='uploads/Ablaufplan.pdf',
        folder_id=folder.id,
        file_size=10240,
        mime_type='application/pdf',
        uploaded_by=auth_user.id,
        is_current=True,
    )
    db.session.add(file_obj)

    ev = Event(
        name='Links and Files Event',
        owner_id=auth_user.id,
        created_by=auth_user.id,
        folder_id=folder.id,
    )
    db.session.add(ev)
    db.session.commit()
    ev_id = ev.id

    # 2. Externe Links hinzufügen
    res_link = client.post(f'/events/{ev_id}/links/add', data={
        'title': 'Ticketshop',
        'url': 'https://tickets.example.com',
    }, follow_redirects=True)
    assert res_link.status_code == 200

    res_link2 = client.post(f'/events/{ev_id}/links/add', data={
        'title': 'Cloud Drive',
        'url': 'drive.google.com/folder',
    }, follow_redirects=True)
    assert res_link2.status_code == 200

    # 3. Ansicht abrufen: Dateien & Links müssen in der Übersicht gerendert sein
    res_view = client.get(f'/events/{ev_id}')
    assert res_view.status_code == 200
    html = res_view.data.decode('utf-8')

    # Dateien-Karte
    assert 'Dateien' in html
    assert 'Ablaufplan.pdf' in html
    assert '10.0 KB' in html

    # Links-Karte
    assert 'Links' in html
    assert 'Ticketshop' in html
    assert 'https://tickets.example.com' in html
    assert 'Cloud Drive' in html
    assert 'https://drive.google.com/folder' in html

    # 4. Einen Link löschen
    link = EventLink.query.filter_by(event_id=ev_id, title='Ticketshop').first()
    assert link is not None
    res_del = client.post(f'/events/{ev_id}/links/{link.id}/delete', follow_redirects=True)
    assert res_del.status_code == 200

    ev_refreshed = db.session.get(Event, ev_id)
    assert len(ev_refreshed.links) == 1
    assert ev_refreshed.links[0].title == 'Cloud Drive'


def test_event_pdf_export_with_all_details(client, auth_user):
    """Prüft, dass der PDF-Export alle Veranstaltungsdetails, Custom Fields, Tage, Termine, ToDos etc. fehlerfrei generiert."""
    _login(client)

    # 1. Mehrtägige Veranstaltung mit Custom Fields, Tagen, Kontakten und ToDos anlegen
    ev = Event(
        name='Großes Sommerfestival 2026',
        description='Ein dreitägiges Open-Air Event mit Bands und Workshops.',
        default_location='Festwiese Nord',
        is_multiday=True,
        owner_id=auth_user.id,
        created_by=auth_user.id,
    )
    db.session.add(ev)
    db.session.flush()

    board = KanbanBoard(title='PDF Board', created_by=auth_user.id)
    db.session.add(board)
    db.session.flush()
    k_list = KanbanList(board_id=board.id, title='Backlog')
    db.session.add(k_list)
    db.session.flush()
    k_card = KanbanCard(list_id=k_list.id, title='PDF Karte', created_by=auth_user.id)
    db.session.add(k_card)
    db.session.flush()
    pdf_folder = Folder(name='PDF Ordner', created_by=auth_user.id)
    db.session.add(pdf_folder)
    db.session.flush()
    ev.kanban_board_id = board.id
    ev.kanban_card_id = k_card.id
    ev.folder_id = pdf_folder.id
    db.session.add(EventLink(event_id=ev.id, title='Ticketshop', url='https://tickets.example.com'))

    day1 = EventDay(
        event_id=ev.id,
        day_number=1,
        date=date(2026, 7, 10),
        start_time=time(14, 0),
        end_time=time(23, 0),
        location='Main Stage Area',
        label='Festival Tag 1',
        notes='Einlass ab 13:00 Uhr',
    )
    db.session.add(day1)
    db.session.flush()

    appt1 = EventAppointment(
        event_id=ev.id,
        day_id=day1.id,
        label='Headliner Act',
        start_time=datetime(2026, 7, 10, 20, 0),
        end_time=datetime(2026, 7, 10, 22, 30),
        location='Main Stage Area',
        description='Große Show mit Pyrotechnik',
    )
    db.session.add(appt1)

    contact1 = EventContact(
        event_id=ev.id,
        name='Max Mustermann',
        role='Produktionsleiter',
        phone='+49 170 1234567',
        email='max@festival.example',
    )
    db.session.add(contact1)

    assign1 = EventAssignment(
        event_id=ev.id,
        user_id=auth_user.id,
        role='Stage Manager',
    )
    db.session.add(assign1)

    tl = EventTodoList(
        event_id=ev.id,
        title='Produktions-Checkliste',
        created_by=auth_user.id,
    )
    db.session.add(tl)
    db.session.flush()

    item1 = EventTodoItem(
        todo_list_id=tl.id,
        title='Notstromaggregat prüfen',
        is_completed=True,
        assigned_to_user_id=auth_user.id,
        due_date=date(2026, 7, 10),
    )
    db.session.add(item1)

    # Custom Field Wert
    field = EventCustomField.query.first()
    if field:
        cv = EventCustomFieldValue(
            event_id=ev.id,
            field_id=field.id,
            value='Custom Test Wert',
        )
        db.session.add(cv)

    db.session.commit()

    # PDF abrufen
    resp = client.get(f'/events/{ev.id}/pdf')
    assert resp.status_code == 200
    assert resp.content_type == 'application/pdf'
    assert resp.data.startswith(b'%PDF-')
    assert len(resp.data) > 1000


