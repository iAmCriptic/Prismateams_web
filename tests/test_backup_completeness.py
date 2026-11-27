"""Round-trip tests for complete backup export & import across all modules, settings, and files."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time

from app import db
from app.models import (
    ApiToken,
    AppPassword,
    BookingPersonalEntry,
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalFile,
    BookingPersonalTemplate,
    Chat,
    Checkout,
    CheckoutItem,
    Comment,
    Credential,
    CredentialFavorite,
    CredentialFolder,
    DutyExternalPerson,
    DutyPersonConfig,
    DutyRoster,
    DutyRosterColumn,
    DutyRosterDay,
    DutyRosterEntry,
    DutyRosterPlanner,
    DutyTimeEntry,
    EmailFolder,
    EmailMessage,
    KanbanActivity,
    KanbanActivityRead,
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardTemplate,
    KanbanBoardView,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardFieldEnabled,
    KanbanCardFieldValue,
    KanbanCardLabel,
    KanbanCardVote,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanCustomField,
    KanbanCustomFieldCategory,
    KanbanLabel,
    KanbanList,
    Mailbox,
    MailboxAutoReply,
    MailboxMembership,
    Manual,
    ManualFolder,
    Meeting,
    MeetingInvite,
    Product,
    ProductLot,
    ProductStatusHistory,
    Protocol,
    ProtocolAgendaItem,
    PublicShare,
    StockMovement,
    Survey,
    SurveyAnswer,
    SurveyLogicRule,
    SurveyPage,
    SurveyQuestion,
    SurveyResponse,
    SystemSettings,
    Team,
    TeamInviteCode,
    TeamMember,
    TeamModuleSetting,
    User,
    WhitelistEntry,
)
from app.models.inventory import LengthColorMapping
from app.utils.backup import CATEGORY_DEFINITIONS, SUPPORTED_CATEGORIES, export_backup, import_backup


def test_backup_categories_and_translations_in_sync():
    def_keys = {c['key'] for c in CATEGORY_DEFINITIONS}
    assert def_keys == set(SUPPORTED_CATEGORIES.keys())
    for required in ('teams', 'kanban', 'surveys', 'protocols', 'meetings', 'duty_roster', 'booking_personal', 'canvas', 'todos', 'helpers'):
        assert required in def_keys

    for lang in ('de', 'en'):
        with open(f'app/translations/{lang}.json', encoding='utf-8') as f:
            tr = json.load(f)['settings']['admin']['backup']
        for key in def_keys:
            assert key in tr['categories'], f"{key} missing in {lang}.json categories"
            assert key in tr['helps'], f"{key} missing in {lang}.json helps"


def test_full_backup_roundtrip_all_modules_and_kanban(app, tmp_path):
    with app.app_context():
        upload_dir = str(tmp_path / 'uploads')
        app.config['UPLOAD_FOLDER'] = upload_dir
        os.makedirs(upload_dir, exist_ok=True)

        # 1. Users & Settings
        admin = User(
            email='admin@example.com',
            first_name='Admin',
            last_name='User',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
            totp_enabled=True,
            totp_secret='JBSWY3DPEHPK3PXP',
            can_access_public=True,
            can_access_team=True,
            can_access_private=False,
            dashboard_config='{"widgets":["kanban"]}',
            portal_onboarding_completed=True,
        )
        admin.set_password('Secret123!')
        db.session.add(admin)
        db.session.flush()

        db.session.add(SystemSettings(key='portal_name', value='PrismaTest', description='Name'))
        db.session.add(WhitelistEntry(entry='@example.com', entry_type='domain', is_active=True))
        db.session.add(ApiToken(user_id=admin.id, token='tok_hash_123', token_prefix='tok_hash', name='CI'))
        db.session.add(AppPassword(user_id=admin.id, username='admin_dav', name='DAV', password_hash='hash_dav'))

        # 2. Teams
        team = Team(name='Technik', description='AV Team', color='#ff5500', leader_id=admin.id)
        db.session.add(team)
        db.session.flush()
        db.session.add(TeamMember(team_id=team.id, user_id=admin.id))
        db.session.add(TeamModuleSetting(team_id=team.id, module_key='kanban', team_section_enabled=True))
        db.session.add(TeamInviteCode(code='TECH2026', team_id=team.id, created_by_id=admin.id, role='team_only'))

        # 3. Chat with avatar in uploads/chat/avatars/
        chat_av_dir = os.path.join(upload_dir, 'chat', 'avatars')
        os.makedirs(chat_av_dir, exist_ok=True)
        with open(os.path.join(chat_av_dir, 'group.png'), 'wb') as f:
            f.write(b'PNGDATA')
        chat = Chat(name='Technik-Chat', is_main_chat=False, team_id=team.id, created_by=admin.id, group_avatar='group.png')
        db.session.add(chat)
        db.session.flush()

        # 4. Credentials & Manuals with folders & team
        cf = CredentialFolder(name='Server', color='#123456', visibility='team', team_id=team.id, created_by=admin.id)
        db.session.add(cf)
        db.session.flush()
        cred = Credential(
            website_url='https://example.org',
            website_name='Example',
            username='root',
            visibility='team',
            team_id=team.id,
            folder_id=cf.id,
            created_by=admin.id,
        )
        from app.blueprints.credentials import get_encryption_key
        cred.set_password('pa$$word', get_encryption_key())
        db.session.add(cred)
        db.session.flush()
        db.session.add(CredentialFavorite(user_id=admin.id, credential_id=cred.id))

        mf = ManualFolder(name='Audio', color='#654321', visibility='team', team_id=team.id, created_by=admin.id)
        db.session.add(mf)
        db.session.flush()
        manuals_dir = os.path.join(upload_dir, 'manuals')
        os.makedirs(manuals_dir, exist_ok=True)
        manual_pdf = os.path.join(manuals_dir, 'mixer.pdf')
        with open(manual_pdf, 'wb') as f:
            f.write(b'%PDF-1.4\nTEST')
        manual = Manual(title='Mixer Guide', filename='mixer.pdf', file_path=manual_pdf, file_size=13, visibility='team', team_id=team.id, folder_id=mf.id, uploaded_by=admin.id)
        db.session.add(manual)

        # 5. Email Mailbox & Message
        mb = Mailbox(name='info@example.com', display_name='Info', mailbox_type='shared', team_id=team.id)
        db.session.add(mb)
        db.session.flush()
        db.session.add(MailboxMembership(mailbox_id=mb.id, user_id=admin.id, can_read=True, can_send=True))
        db.session.add(MailboxAutoReply(mailbox_key='info', mailbox_id=mb.id, enabled=True, subject='OOO', body_html='<p>Away</p>'))
        db.session.add(EmailFolder(name='INBOX', display_name='Posteingang', folder_type='inbox', mailbox_id=mb.id))
        db.session.add(EmailMessage(
            message_id='<m1@example.com>',
            subject='Hallo',
            sender='a@example.com',
            recipients='info@example.com',
            mailbox_id=mb.id,
            color_dot='blue',
            is_flagged=True,
        ))

        # 6. Kanban (all 19 models + files + PublicShare + Comment)
        kb_dir = os.path.join(upload_dir, 'kanban', 'boards')
        os.makedirs(kb_dir, exist_ok=True)
        cover_file = os.path.join(kb_dir, 'cover.png')
        with open(cover_file, 'wb') as f:
            f.write(b'COVERPNG')
        att_file = os.path.join(upload_dir, 'kanban', 'spec.txt')
        with open(att_file, 'wb') as f:
            f.write(b'KANBAN_ATTACHMENT_BYTES')

        board = KanbanBoard(
            public_id='board_pub_1',
            title='Sprint Board',
            description='Roadmap',
            cover_path=cover_file,
            background='ocean',
            visibility='team',
            team_id=team.id,
            created_by=admin.id,
        )
        db.session.add(board)
        db.session.flush()
        db.session.add(KanbanBoardMember(board_id=board.id, user_id=admin.id, role='owner'))
        lbl = KanbanLabel(board_id=board.id, name='Dringend', color='#dc3545', position=0)
        db.session.add(lbl)
        cf_cat = KanbanCustomFieldCategory(board_id=board.id, name='Meta', position=0)
        db.session.add(cf_cat)
        db.session.flush()
        kcf = KanbanCustomField(board_id=board.id, category_id=cf_cat.id, field_type='text', label='Budget', position=0)
        db.session.add(kcf)
        db.session.flush()
        klst = KanbanList(board_id=board.id, title='To Do', position=0)
        klst.set_default_custom_field_ids([kcf.id])
        db.session.add(klst)
        db.session.flush()
        card = KanbanCard(list_id=klst.id, title='Backup prüfen', description='Alles testen', poll_text='OK?', created_by=admin.id)
        db.session.add(card)
        db.session.flush()
        att = KanbanAttachment(
            card_id=card.id,
            filename='spec.txt',
            original_filename='spec.txt',
            mime_type='text/plain',
            file_size=23,
            storage_path=att_file,
            uploaded_by=admin.id,
        )
        db.session.add(att)
        db.session.flush()
        card.cover_attachment_id = att.id
        db.session.add(KanbanCardLabel(card_id=card.id, label_id=lbl.id))
        db.session.add(KanbanCardAssignee(card_id=card.id, user_id=admin.id))
        db.session.add(KanbanCardFieldEnabled(card_id=card.id, field_id=kcf.id))
        db.session.add(KanbanCardFieldValue(card_id=card.id, field_id=kcf.id, value='500€'))
        db.session.add(KanbanCardVote(card_id=card.id, user_id=admin.id))
        chk = KanbanChecklist(card_id=card.id, title='Checks', position=0)
        db.session.add(chk)
        db.session.flush()
        db.session.add(KanbanChecklistItem(checklist_id=chk.id, text='Kanban OK', done=True, assignee_id=admin.id))
        act = KanbanActivity(board_id=board.id, card_id=card.id, user_id=admin.id, action='create', detail='created')
        db.session.add(act)
        db.session.flush()
        db.session.add(KanbanActivityRead(activity_id=act.id, user_id=admin.id))
        db.session.add(KanbanBoardTemplate(name='Standard', payload_json='{"lists":["To Do"]}', created_by=admin.id, is_global=True))
        db.session.add(KanbanBoardView(board_id=board.id, user_id=admin.id))
        db.session.add(PublicShare(resource_type='kanban_board', resource_id=board.id, mode='view', token='kb_tok_1', enabled=True, created_by=admin.id))
        db.session.add(Comment(content_type='kanban_card', content_id=card.id, content='Sieht gut aus', author_id=admin.id))

        # 7. Surveys, Protocols, Meetings, Duty Roster, Booking Personal, Inventory submodels
        surv = Survey(title='Feedback', created_by=admin.id, visibility='team', team_id=team.id, public_token='surv_tok_1')
        db.session.add(surv)
        db.session.flush()
        sp = SurveyPage(survey_id=surv.id, title='Seite 1', page_order=0)
        db.session.add(sp)
        db.session.flush()
        sq = SurveyQuestion(page_id=sp.id, question_type='short_text', label='Wie wars?', is_required=True)
        db.session.add(sq)
        db.session.flush()
        db.session.add(SurveyLogicRule(survey_id=surv.id, source_question_id=sq.id, operator='is_not_empty', action='show_question', target_question_id=sq.id))
        sresp = SurveyResponse(survey_id=surv.id, public_token='resp_tok_1', status='submitted', user_id=admin.id)
        db.session.add(sresp)
        db.session.flush()
        db.session.add(SurveyAnswer(response_id=sresp.id, question_id=sq.id, value_text='Super'))

        prot = Protocol(title='Wochenmeeting', meeting_date=date(2026, 11, 18), start_time=time(10, 0), team_id=team.id, created_by=admin.id)
        db.session.add(prot)
        db.session.flush()
        db.session.add(ProtocolAgendaItem(protocol_id=prot.id, position=0, title='TOP 1', content_html='<p>Backup</p>'))

        mtg = Meeting(title='Sync', room_id='room-sync-1', guest_join_token='gj-1', created_by=admin.id, chat_id=chat.id)
        db.session.add(mtg)
        db.session.flush()
        db.session.add(MeetingInvite(meeting_id=mtg.id, user_id=admin.id))

        ext_p = DutyExternalPerson(team_id=team.id, name='Gast-Tech')
        db.session.add(ext_p)
        db.session.flush()
        db.session.add(DutyPersonConfig(team_id=team.id, user_id=admin.id, weekly_hours_soll=40.0))
        db.session.add(DutyRosterPlanner(team_id=team.id, user_id=admin.id))
        roster = DutyRoster(team_id=team.id, year=2026, month=11, is_published=True, created_by_id=admin.id)
        db.session.add(roster)
        db.session.flush()
        rday = DutyRosterDay(roster_id=roster.id, date=date(2026, 11, 18), whats_happening='Show')
        rcol = DutyRosterColumn(roster_id=roster.id, external_person_id=ext_p.id, sort_order=0)
        db.session.add_all([rday, rcol])
        db.session.flush()
        db.session.add(DutyRosterEntry(day_id=rday.id, column_id=rcol.id, start_time=time(9, 0), end_time=time(17, 0), entry_type='shift'))
        db.session.add(DutyTimeEntry(user_id=admin.id, team_id=team.id, date=date(2026, 11, 18), start_time=time(9, 0), end_time=time(17, 0)))

        db.session.add(BookingPersonalTemplate(name='Band Template', fields_schema_json='[]', created_by=admin.id))
        bpe = BookingPersonalEvent(name='Festival 2026', mailbox_id=mb.id, apply_token='bp_apply_1', created_by=admin.id)
        db.session.add(bpe)
        db.session.flush()
        db.session.add(BookingPersonalField(event_id=bpe.id, field_key='gage', label='Gage', field_type='currency'))
        bp_entry = BookingPersonalEntry(event_id=bpe.id, name='The Band', email='band@example.com', form_token='bp_f1', overview_token='bp_o1')
        db.session.add(bp_entry)
        db.session.flush()
        bp_dir = os.path.join(upload_dir, 'booking_personal', str(bpe.id))
        os.makedirs(bp_dir, exist_ok=True)
        bp_file_path = os.path.join(bp_dir, 'rider.pdf')
        with open(bp_file_path, 'wb') as f:
            f.write(b'RIDER_PDF')
        db.session.add(BookingPersonalFile(entry_id=bp_entry.id, field_key='rider', file_path=f'/uploads/booking_personal/{bpe.id}/rider.pdf', file_name='rider.pdf'))

        prod = Product(name='XLR 10m', length='10m', created_by=admin.id)
        db.session.add(prod)
        db.session.flush()
        db.session.add(LengthColorMapping(length_meters=10.0, color_hex='#00ff00'))
        ch = Checkout(checkout_number='CHK-001', event_name='Show', borrower_name='Admin User', start_date=datetime(2026, 11, 18), end_date=datetime(2026, 11, 20), created_by=admin.id)
        db.session.add(ch)
        db.session.flush()
        db.session.add(CheckoutItem(checkout_id=ch.id, product_id=prod.id))
        lot = ProductLot(product_id=prod.id, lot_code='LOT-1', quantity_on_hand=5, created_by=admin.id)
        db.session.add(lot)
        db.session.flush()
        db.session.add(StockMovement(product_id=prod.id, lot_id=lot.id, movement_type='in', quantity_delta=5, quantity_after=5, performed_by=admin.id))
        db.session.add(ProductStatusHistory(product_id=prod.id, old_status='available', new_status='borrowed', changed_by=admin.id))

        db.session.commit()

        # Export ALL
        backup_file = str(tmp_path / 'full_backup.prismateams')
        exp_res = export_backup(['all'], backup_file)
        assert exp_res['success'] is True

        # Wipe database and uploads completely
        import shutil
        shutil.rmtree(upload_dir, ignore_errors=True)
        os.makedirs(upload_dir, exist_ok=True)
        db.session.remove()
        db.drop_all()
        db.create_all()

        # Import ALL
        imp_res = import_backup(backup_file, ['all'])
        assert imp_res['success'] is True, imp_res

        # Verify restored data
        restored_admin = User.query.filter_by(email='admin@example.com').first()
        assert restored_admin is not None
        assert restored_admin.totp_secret == 'JBSWY3DPEHPK3PXP'
        assert restored_admin.can_access_private is False
        assert restored_admin.dashboard_config == '{"widgets":["kanban"]}'
        assert SystemSettings.query.filter_by(key='portal_name').first().value == 'PrismaTest'
        assert ApiToken.query.filter_by(name='CI').first() is not None
        assert AppPassword.query.filter_by(username='admin_dav').first() is not None

        restored_team = Team.query.filter_by(name='Technik').first()
        assert restored_team is not None
        assert TeamMember.query.filter_by(team_id=restored_team.id, user_id=restored_admin.id).first() is not None
        assert TeamModuleSetting.query.filter_by(team_id=restored_team.id, module_key='kanban').first().team_section_enabled is True
        assert TeamInviteCode.query.filter_by(code='TECH2026').first() is not None

        restored_chat = Chat.query.filter_by(name='Technik-Chat').first()
        assert restored_chat is not None and restored_chat.team_id == restored_team.id
        assert restored_chat.group_avatar is not None
        assert os.path.isfile(os.path.join(upload_dir, 'chat', 'avatars', restored_chat.group_avatar))

        restored_cred = Credential.query.filter_by(website_name='Example').first()
        assert restored_cred is not None and restored_cred.team_id == restored_team.id and restored_cred.folder_id is not None
        assert CredentialFavorite.query.filter_by(user_id=restored_admin.id, credential_id=restored_cred.id).first() is not None
        restored_manual = Manual.query.filter_by(title='Mixer Guide').first()
        assert restored_manual is not None and restored_manual.team_id == restored_team.id and restored_manual.folder_id is not None

        restored_mb = Mailbox.query.filter_by(name='info@example.com').first()
        assert restored_mb is not None
        restored_email = EmailMessage.query.filter_by(message_id='<m1@example.com>').first()
        assert restored_email.mailbox_id == restored_mb.id and restored_email.color_dot == 'blue' and restored_email.is_flagged is True

        # Verify Kanban + remapped IDs + binary files
        r_board = KanbanBoard.query.filter_by(public_id='board_pub_1').first()
        assert r_board is not None and r_board.team_id == restored_team.id
        assert r_board.cover_path and os.path.isfile(r_board.cover_path)
        assert KanbanBoardMember.query.filter_by(board_id=r_board.id, user_id=restored_admin.id).first() is not None
        r_list = KanbanList.query.filter_by(board_id=r_board.id, title='To Do').first()
        assert r_list is not None and len(r_list.get_default_custom_field_ids()) == 1
        r_card = KanbanCard.query.filter_by(list_id=r_list.id, title='Backup prüfen').first()
        assert r_card is not None and r_card.cover_attachment_id is not None
        r_att = KanbanAttachment.query.get(r_card.cover_attachment_id)
        assert r_att is not None and r_att.storage_path and os.path.isfile(r_att.storage_path)
        with open(r_att.storage_path, 'rb') as f:
            assert f.read() == b'KANBAN_ATTACHMENT_BYTES'
        assert KanbanCardFieldValue.query.filter_by(card_id=r_card.id).first().value == '500€'
        assert KanbanChecklistItem.query.filter_by(text='Kanban OK').first().done is True
        assert KanbanBoardTemplate.query.filter_by(name='Standard').first() is not None
        assert PublicShare.query.filter_by(resource_type='kanban_board', resource_id=r_board.id).first() is not None
        assert Comment.query.filter_by(content_type='kanban_card', content_id=r_card.id).first().content == 'Sieht gut aus'

        # Verify Surveys, Protocols, Meetings, Duty Roster, Booking Personal, Inventory submodels
        assert SurveyAnswer.query.filter_by(value_text='Super').first() is not None
        assert ProtocolAgendaItem.query.filter_by(title='TOP 1').first() is not None
        assert Meeting.query.filter_by(room_id='room-sync-1').first() is not None
        assert DutyRosterEntry.query.count() == 1
        assert DutyTimeEntry.query.count() == 1
        r_bp_file = BookingPersonalFile.query.filter_by(file_name='rider.pdf').first()
        assert r_bp_file is not None
        assert os.path.isfile(os.path.join(upload_dir, r_bp_file.file_path.replace('/uploads/', '', 1)))
        assert CheckoutItem.query.count() == 1
        assert StockMovement.query.count() == 1
        assert ProductStatusHistory.query.count() == 1
        assert LengthColorMapping.query.filter_by(length_meters=10.0).first() is not None


def test_backup_upload_allows_large_request_body(app):
    from flask import request

    orig_limit = app.config.get('MAX_CONTENT_LENGTH')
    app.config['MAX_CONTENT_LENGTH'] = 1024
    try:
        with app.test_request_context('/settings/admin/backup', method='POST'):
            assert request.max_content_length == 10 * 1024 * 1024 * 1024
        with app.test_request_context('/setup/import-backup', method='POST'):
            assert request.max_content_length == 10 * 1024 * 1024 * 1024
        with app.test_request_context('/files/upload', method='POST'):
            assert request.max_content_length == 1024
    finally:
        app.config['MAX_CONTENT_LENGTH'] = orig_limit


def test_estimate_backup_sizes_and_admin_backup_ui(app, client):
    from app import db
    from app.models import File, User
    from app.utils.backup import CATEGORY_DEFINITIONS, estimate_backup_sizes

    with app.app_context():
        admin = User(
            email='backup_size_admin@example.com',
            first_name='Backup',
            last_name='Admin',
            is_admin=True,
            is_super_admin=True,
            is_active=True,
            is_email_confirmed=True,
        )
        admin.set_password('Secret123!')
        db.session.add(admin)
        db.session.flush()

        sample_file = File(
            name='demo.bin',
            original_name='demo.bin',
            file_path='/tmp/demo.bin',
            file_size=12000,
            mime_type='application/octet-stream',
            uploaded_by=admin.id,
        )
        db.session.add(sample_file)
        db.session.commit()

        sizes = estimate_backup_sizes()
        expected_keys = {c['key'] for c in CATEGORY_DEFINITIONS}
        assert set(sizes.keys()) == expected_keys
        assert all(isinstance(v, int) and v >= 0 for v in sizes.values())
        assert sizes['files'] >= 16000
        assert sizes['users'] > 0

        client.post('/login', data={
            'email': 'backup_size_admin@example.com',
            'password': 'Secret123!',
        }, follow_redirects=False)

        from flask import url_for
        with app.test_request_context():
            backup_url = url_for('settings.admin_backup')
        resp = client.get(backup_url)
        assert resp.status_code == 200, f"Unexpected status {resp.status_code}, Location={resp.headers.get('Location')}"
        html = resp.get_data(as_text=True)
        assert 'id="backupSizeEstimate"' in html
        assert 'id="backupImportOverlay"' in html
        assert 'data-backup-size="' in html


def test_bot_protection_excluded_from_backup_export_and_import(app, tmp_path):
    from app.utils.bot_protection import SETTING_KEYS as BOT_KEYS

    with app.app_context():
        db.session.add(SystemSettings(key='portal_name', value='KeepMe', description='Portal'))
        db.session.add(SystemSettings(key=BOT_KEYS['provider'], value='turnstile', description='Bot'))
        db.session.add(SystemSettings(key=BOT_KEYS['login_enabled'], value='true', description='Login'))
        db.session.add(SystemSettings(key=BOT_KEYS['turnstile_site_key'], value='site-123', description='Site'))
        db.session.add(SystemSettings(key=BOT_KEYS['turnstile_secret_key'], value='secret-456', description='Secret'))
        db.session.commit()

        backup_file = str(tmp_path / 'settings.prismateams')
        res = export_backup(['settings'], backup_file)
        assert res['success'] is True

        with open(backup_file, encoding='utf-8') as f:
            payload = json.load(f)

        exported_keys = {s['key'] for s in payload['data'].get('settings', [])}
        assert 'portal_name' in exported_keys
        for bot_key in BOT_KEYS.values():
            assert bot_key not in exported_keys

        # Simulate an older backup file that still contains bot-protection settings
        payload['data']['settings'].append({
            'key': BOT_KEYS['provider'],
            'value': 'recaptcha',
            'description': 'Legacy bot protection',
        })
        payload['data']['settings'].append({
            'key': BOT_KEYS['login_enabled'],
            'value': 'true',
            'description': 'Legacy login bot protection',
        })
        payload['data']['settings'].append({
            'key': BOT_KEYS['recaptcha_secret_key'],
            'value': 'legacy-secret',
            'description': 'Legacy secret',
        })
        legacy_file = str(tmp_path / 'legacy_with_bot.prismateams')
        with open(legacy_file, 'w', encoding='utf-8') as f:
            json.dump(payload, f)

        SystemSettings.query.delete()
        db.session.commit()

        imp = import_backup(legacy_file, ['settings'])
        assert imp['success'] is True

        restored_keys = {s.key: s.value for s in SystemSettings.query.all()}
        assert restored_keys.get('portal_name') == 'KeepMe'
        for bot_key in BOT_KEYS.values():
            assert bot_key not in restored_keys


def test_canvas_todos_helpers_selective_backup_roundtrip(app, tmp_path):
    from app.models import (
        CanvasDocument,
        Event,
        EventHelperLink,
        Helper,
        HelperArea,
        HelperAreaWish,
        HelperEvent,
        HelperFieldConfig,
        HelperShift,
        HelperVoucherRule,
        TodoItem,
    )

    with app.app_context():
        upload_dir = str(tmp_path / 'uploads')
        app.config['UPLOAD_FOLDER'] = upload_dir
        os.makedirs(upload_dir, exist_ok=True)

        admin = User(
            email='mod_admin@example.com',
            first_name='Mod',
            last_name='Admin',
            is_active=True,
            is_admin=True,
            is_email_confirmed=True,
        )
        admin.set_password('Secret123!')
        db.session.add(admin)
        db.session.flush()

        team = Team(name='Orga', description='Orga Team', color='#112233', leader_id=admin.id)
        db.session.add(team)
        db.session.flush()

        # Canvas with .hyc & thumbnail
        canvas_dir = os.path.join(upload_dir, 'canvas')
        os.makedirs(canvas_dir, exist_ok=True)
        hyc_path = os.path.join(canvas_dir, 'design.hyc')
        thumb_path = os.path.join(canvas_dir, 'thumb.png')
        with open(hyc_path, 'wb') as f:
            f.write(b'HYCDATA')
        with open(thumb_path, 'wb') as f:
            f.write(b'THUMBPNG')
        doc = CanvasDocument(
            name='Bühnenplan',
            design_type='whiteboard',
            preset_key='whiteboard',
            width=1920,
            height=1080,
            hycanvas_design_id='hyc-abc-1',
            file_path=hyc_path,
            thumbnail_path=thumb_path,
            created_by=admin.id,
            visibility='team',
            team_id=team.id,
        )
        db.session.add(doc)

        # TodoItem
        todo = TodoItem(
            title='Mikrofone testen',
            visibility='team',
            team_id=team.id,
            created_by_id=admin.id,
            assignee_id=admin.id,
            due_date=date(2026, 7, 10),
            due_time=time(14, 30),
            is_completed=False,
            position=1,
        )
        db.session.add(todo)

        # Helpers + EventHelperLink
        he = HelperEvent(
            name='Sommerfest 2026',
            slug='sommerfest-2026',
            apply_token='tok-helper-1',
            voucher_calc_mode='per_shift',
        )
        db.session.add(he)
        db.session.flush()
        ha = HelperArea(event_id=he.id, name='Technik', sort_order=1)
        db.session.add(ha)
        db.session.flush()
        hlp = Helper(event_id=he.id, first_name='Max', last_name='Muster', email='max@example.com', tshirt_size='L')
        db.session.add(hlp)
        db.session.flush()
        db.session.add(HelperAreaWish(helper_id=hlp.id, area_id=ha.id, priority=1, available_days=['Freitag']))
        db.session.add(HelperShift(event_id=he.id, area_id=ha.id, helper_id=hlp.id, day_label='Freitag', hours=4.5))
        db.session.add(HelperFieldConfig(event_id=he.id, field_key='driver_license', label='Führerschein', field_type='checkbox'))
        db.session.add(HelperVoucherRule(event_id=he.id, area_id=ha.id, name='Standard', min_hours=2.0, food_count=1, drinks_count=2))

        ev = Event(name='Sommerfest', owner_id=admin.id, created_by=admin.id)
        db.session.add(ev)
        db.session.flush()
        db.session.add(EventHelperLink(event_id=ev.id, helper_event_id=he.id))
        db.session.commit()

        backup_file = str(tmp_path / 'modules.prismateams')
        res = export_backup(['users', 'teams', 'canvas', 'todos', 'helpers', 'events'], backup_file)
        assert res['success'] is True

        # Wipe database
        for model in (
            EventHelperLink, Event,
            HelperVoucherRule, HelperFieldConfig, HelperShift, HelperAreaWish, Helper, HelperArea, HelperEvent,
            TodoItem, CanvasDocument, Team, User,
        ):
            model.query.delete()
        db.session.commit()

        # Selective import: only canvas + todos first (without helpers/events)
        imp1 = import_backup(backup_file, ['users', 'teams', 'canvas', 'todos'])
        assert imp1['success'] is True
        assert CanvasDocument.query.count() == 1
        assert TodoItem.query.count() == 1
        assert HelperEvent.query.count() == 0

        r_doc = CanvasDocument.query.first()
        assert r_doc.name == 'Bühnenplan'
        assert r_doc.hycanvas_design_id == 'hyc-abc-1'
        assert r_doc.file_path and os.path.exists(r_doc.file_path)
        assert r_doc.thumbnail_path and os.path.exists(r_doc.thumbnail_path)

        r_todo = TodoItem.query.first()
        assert r_todo.title == 'Mikrofone testen'
        assert r_todo.due_date == date(2026, 7, 10)
        assert r_todo.due_time == time(14, 30)

        # Now import helpers + events
        imp2 = import_backup(backup_file, ['helpers', 'events'])
        assert imp2['success'] is True
        assert HelperEvent.query.count() == 1
        assert HelperArea.query.count() == 1
        assert Helper.query.count() == 1
        assert HelperAreaWish.query.count() == 1
        assert HelperShift.query.count() == 1
        assert HelperFieldConfig.query.count() == 1
        assert HelperVoucherRule.query.count() == 1
        assert EventHelperLink.query.count() == 1
