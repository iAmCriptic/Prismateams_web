"""Backup exporters for newer modules: teams, surveys, protocols, meetings, duty_roster, booking_personal."""

from __future__ import annotations

import os
from typing import Dict

from app.models.booking_personal import (
    BookingPersonalEntry,
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalFile,
    BookingPersonalTemplate,
)
from app.models.duty_roster import (
    DutyExternalPerson,
    DutyPersonConfig,
    DutyRoster,
    DutyRosterColumn,
    DutyRosterDay,
    DutyRosterEntry,
    DutyRosterPlanner,
    DutyTimeEntry,
)
from app.models.meetings import Meeting, MeetingInvite
from app.models.protocol import Protocol, ProtocolAgendaItem
from app.models.survey import (
    Survey,
    SurveyAnswer,
    SurveyLogicRule,
    SurveyPage,
    SurveyQuestion,
    SurveyResponse,
)
from app.models.team import Team, TeamInviteCode, TeamMember, TeamModuleSetting
from app.utils.backup.file_io import read_file_base64, upload_root
from app.utils.backup_lookups import lookup_team_name, lookup_user_email


def export_teams_bundle() -> Dict:
    teams_dir = os.path.join(upload_root(), "teams")
    teams_out = []
    for t in Team.query.order_by(Team.id).all():
        entry = {
            "old_id": t.id,
            "name": t.name,
            "description": t.description,
            "image": t.image,
            "color": t.color,
            "leader_email": lookup_user_email(t.leader_id) if t.leader_id else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        if t.image:
            b64 = read_file_base64([t.image, os.path.join(teams_dir, t.image)])
            if b64:
                entry["image_content_base64"] = b64
                entry["image_original_name"] = os.path.basename(t.image)
        teams_out.append(entry)

    members_out = [{
        "team_name": lookup_team_name(m.team_id),
        "user_email": lookup_user_email(m.user_id),
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    } for m in TeamMember.query.all()]

    module_settings_out = [{
        "team_name": lookup_team_name(ms.team_id),
        "module_key": ms.module_key,
        "team_section_enabled": ms.team_section_enabled,
        "updated_at": ms.updated_at.isoformat() if ms.updated_at else None,
    } for ms in TeamModuleSetting.query.all()]

    invite_codes_out = [{
        "code": c.code,
        "team_name": lookup_team_name(c.team_id),
        "created_by_email": lookup_user_email(c.created_by_id) if c.created_by_id else None,
        "max_uses": c.max_uses,
        "uses_count": c.uses_count,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "is_active": c.is_active,
        "role": c.role,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in TeamInviteCode.query.all()]

    return {
        "teams": teams_out,
        "team_members": members_out,
        "team_module_settings": module_settings_out,
        "team_invite_codes": invite_codes_out,
    }


def export_surveys_bundle() -> Dict:
    surveys_out = []
    for s in Survey.query.order_by(Survey.id).all():
        entry = {
            "old_id": s.id,
            "title": s.title,
            "description": s.description,
            "header_image_path": s.header_image_path,
            "created_by_email": lookup_user_email(s.created_by),
            "visibility": s.visibility,
            "team_name": lookup_team_name(s.team_id) if s.team_id else None,
            "is_active": s.is_active,
            "is_publicly_fillable": s.is_publicly_fillable,
            "public_token": s.public_token,
            "layout_mode": s.layout_mode,
            "settings_json": s.settings_json,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        if s.header_image_path:
            b64 = read_file_base64([s.header_image_path])
            if b64:
                entry["header_image_base64"] = b64
                entry["header_image_name"] = os.path.basename(s.header_image_path)
        surveys_out.append(entry)

    pages_out = [{
        "old_id": p.id,
        "old_survey_id": p.survey_id,
        "title": p.title,
        "description": p.description,
        "page_order": p.page_order,
    } for p in SurveyPage.query.order_by(SurveyPage.id).all()]

    questions_out = [{
        "old_id": q.id,
        "old_page_id": q.page_id,
        "question_type": q.question_type,
        "label": q.label,
        "description": q.description,
        "is_required": q.is_required,
        "question_order": q.question_order,
        "config_json": q.config_json,
    } for q in SurveyQuestion.query.order_by(SurveyQuestion.id).all()]

    logic_out = [{
        "old_survey_id": r.survey_id,
        "old_source_question_id": r.source_question_id,
        "operator": r.operator,
        "value_json": r.value_json,
        "action": r.action,
        "old_target_page_id": r.target_page_id,
        "old_target_question_id": r.target_question_id,
        "rule_order": r.rule_order,
    } for r in SurveyLogicRule.query.order_by(SurveyLogicRule.id).all()]

    responses_out = [{
        "old_id": resp.id,
        "old_survey_id": resp.survey_id,
        "public_token": resp.public_token,
        "respondent_email": resp.respondent_email,
        "email_verified_at": resp.email_verified_at.isoformat() if resp.email_verified_at else None,
        "status": resp.status,
        "submitted_at": resp.submitted_at.isoformat() if resp.submitted_at else None,
        "user_email": lookup_user_email(resp.user_id) if resp.user_id else None,
        "ip_hash": resp.ip_hash,
        "created_at": resp.created_at.isoformat() if resp.created_at else None,
        "updated_at": resp.updated_at.isoformat() if resp.updated_at else None,
    } for resp in SurveyResponse.query.order_by(SurveyResponse.id).all()]

    answers_out = []
    for a in SurveyAnswer.query.order_by(SurveyAnswer.id).all():
        item = {
            "old_response_id": a.response_id,
            "old_question_id": a.question_id,
            "value_text": a.value_text,
            "value_json": a.value_json,
            "file_path": a.file_path,
        }
        if a.file_path:
            b64 = read_file_base64([a.file_path])
            if b64:
                item["file_content_base64"] = b64
                item["file_original_name"] = os.path.basename(a.file_path)
        answers_out.append(item)

    return {
        "surveys": surveys_out,
        "survey_pages": pages_out,
        "survey_questions": questions_out,
        "survey_logic_rules": logic_out,
        "survey_responses": responses_out,
        "survey_answers": answers_out,
    }


def export_protocols_bundle() -> Dict:
    protocols_out = [{
        "old_id": p.id,
        "title": p.title,
        "meeting_date": p.meeting_date.isoformat() if p.meeting_date else None,
        "start_time": p.start_time.isoformat() if p.start_time else None,
        "end_time": p.end_time.isoformat() if p.end_time else None,
        "participants_text": p.participants_text,
        "excused_text": p.excused_text,
        "absent_text": p.absent_text,
        "status": p.status,
        "visibility": p.visibility,
        "team_name": lookup_team_name(p.team_id) if p.team_id else None,
        "created_by_email": lookup_user_email(p.created_by),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "finalized_at": p.finalized_at.isoformat() if p.finalized_at else None,
    } for p in Protocol.query.order_by(Protocol.id).all()]

    items_out = [{
        "old_protocol_id": it.protocol_id,
        "position": it.position,
        "title": it.title,
        "content_html": it.content_html,
    } for it in ProtocolAgendaItem.query.order_by(ProtocolAgendaItem.id).all()]

    return {
        "protocols": protocols_out,
        "protocol_agenda_items": items_out,
    }


def export_meetings_bundle() -> Dict:
    from app.utils.backup_lookups import lookup_entity_name

    meetings_out = [{
        "old_id": m.id,
        "title": m.title,
        "room_id": m.room_id,
        "access_mode": m.access_mode,
        "status": m.status,
        "created_by_email": lookup_user_email(m.created_by),
        "chat_name": lookup_entity_name("chat", m.chat_id) if m.chat_id else None,
        "guest_join_token": m.guest_join_token,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "ended_at": m.ended_at.isoformat() if m.ended_at else None,
        "ended_by_email": lookup_user_email(m.ended_by) if m.ended_by else None,
    } for m in Meeting.query.order_by(Meeting.id).all()]

    invites_out = [{
        "old_meeting_id": inv.meeting_id,
        "user_email": lookup_user_email(inv.user_id),
        "invited_at": inv.invited_at.isoformat() if inv.invited_at else None,
    } for inv in MeetingInvite.query.all()]

    return {
        "meetings": meetings_out,
        "meeting_invites": invites_out,
    }


def export_duty_roster_bundle() -> Dict:
    ext_out = [{
        "old_id": p.id,
        "team_name": lookup_team_name(p.team_id),
        "name": p.name,
        "valid_from": p.valid_from.isoformat() if p.valid_from else None,
        "valid_until": p.valid_until.isoformat() if p.valid_until else None,
        "sort_order": p.sort_order,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    } for p in DutyExternalPerson.query.order_by(DutyExternalPerson.id).all()]

    person_cfg_out = [{
        "team_name": lookup_team_name(c.team_id),
        "user_email": lookup_user_email(c.user_id),
        "weekly_hours_soll": c.weekly_hours_soll,
        "vacation_days_total": c.vacation_days_total,
        "vacation_days_used": c.vacation_days_used,
        "available_for_roster": c.available_for_roster,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    } for c in DutyPersonConfig.query.all()]

    planners_out = [{
        "team_name": lookup_team_name(pl.team_id),
        "user_email": lookup_user_email(pl.user_id),
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
    } for pl in DutyRosterPlanner.query.all()]

    rosters_out = [{
        "old_id": r.id,
        "team_name": lookup_team_name(r.team_id),
        "year": r.year,
        "month": r.month,
        "title": r.title,
        "is_published": r.is_published,
        "created_by_email": lookup_user_email(r.created_by_id) if r.created_by_id else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in DutyRoster.query.order_by(DutyRoster.id).all()]

    days_out = [{
        "old_id": d.id,
        "old_roster_id": d.roster_id,
        "date": d.date.isoformat() if d.date else None,
        "weekday": d.weekday,
        "whats_happening": d.whats_happening,
        "row_color": d.row_color,
    } for d in DutyRosterDay.query.order_by(DutyRosterDay.id).all()]

    cols_out = [{
        "old_id": c.id,
        "old_roster_id": c.roster_id,
        "user_email": lookup_user_email(c.user_id) if c.user_id else None,
        "old_external_person_id": c.external_person_id,
        "external_name": c.external_name,
        "sort_order": c.sort_order,
        "show_in_plan": c.show_in_plan,
    } for c in DutyRosterColumn.query.order_by(DutyRosterColumn.id).all()]

    entries_out = [{
        "old_day_id": e.day_id,
        "old_column_id": e.column_id,
        "start_time": e.start_time.isoformat() if e.start_time else None,
        "end_time": e.end_time.isoformat() if e.end_time else None,
        "ends_next_day": e.ends_next_day,
        "entry_type": e.entry_type,
        "label": e.label,
    } for e in DutyRosterEntry.query.order_by(DutyRosterEntry.id).all()]

    time_entries_out = [{
        "user_email": lookup_user_email(t.user_id),
        "team_name": lookup_team_name(t.team_id) if t.team_id else None,
        "date": t.date.isoformat() if t.date else None,
        "start_time": t.start_time.isoformat() if t.start_time else None,
        "end_time": t.end_time.isoformat() if t.end_time else None,
        "ends_next_day": t.ends_next_day,
        "entry_type": t.entry_type,
        "note": t.note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    } for t in DutyTimeEntry.query.order_by(DutyTimeEntry.id).all()]

    return {
        "duty_external_persons": ext_out,
        "duty_person_configs": person_cfg_out,
        "duty_roster_planners": planners_out,
        "duty_rosters": rosters_out,
        "duty_roster_days": days_out,
        "duty_roster_columns": cols_out,
        "duty_roster_entries": entries_out,
        "duty_time_entries": time_entries_out,
    }


def export_booking_personal_bundle() -> Dict:
    from app.models.email import Mailbox

    mailbox_names = {m.id: m.name for m in Mailbox.query.all()}

    templates_out = [{
        "name": t.name,
        "description": t.description,
        "is_system_default": t.is_system_default,
        "fields_schema_json": t.fields_schema_json,
        "created_by_email": lookup_user_email(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in BookingPersonalTemplate.query.order_by(BookingPersonalTemplate.id).all()]

    events_out = []
    for ev in BookingPersonalEvent.query.order_by(BookingPersonalEvent.id).all():
        item = {
            "old_id": ev.id,
            "name": ev.name,
            "slug": ev.slug,
            "description": ev.description,
            "start_date": ev.start_date.isoformat() if ev.start_date else None,
            "end_date": ev.end_date.isoformat() if ev.end_date else None,
            "is_active": ev.is_active,
            "mailbox_name": mailbox_names.get(ev.mailbox_id) if ev.mailbox_id else None,
            "apply_token": ev.apply_token,
            "apply_enabled": ev.apply_enabled,
            "accept_template_subject": ev.accept_template_subject,
            "accept_template_body": ev.accept_template_body,
            "reject_template_subject": ev.reject_template_subject,
            "reject_template_body": ev.reject_template_body,
            "invite_template_subject": ev.invite_template_subject,
            "invite_template_body": ev.invite_template_body,
            "accept_template_subject_en": ev.accept_template_subject_en,
            "accept_template_body_en": ev.accept_template_body_en,
            "reject_template_subject_en": ev.reject_template_subject_en,
            "reject_template_body_en": ev.reject_template_body_en,
            "invite_template_subject_en": ev.invite_template_subject_en,
            "invite_template_body_en": ev.invite_template_body_en,
            "header_image_path": ev.header_image_path,
            "apply_intro_text": ev.apply_intro_text,
            "apply_intro_text_en": ev.apply_intro_text_en,
            "form_intro_text": ev.form_intro_text,
            "form_intro_text_en": ev.form_intro_text_en,
            "overview_intro_text": ev.overview_intro_text,
            "overview_intro_text_en": ev.overview_intro_text_en,
            "created_by_email": lookup_user_email(ev.created_by) if ev.created_by else None,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
            "updated_at": ev.updated_at.isoformat() if ev.updated_at else None,
        }
        if ev.header_image_path:
            b64 = read_file_base64([ev.header_image_path])
            if b64:
                item["header_image_base64"] = b64
                item["header_image_name"] = os.path.basename(ev.header_image_path)
        events_out.append(item)

    fields_out = [{
        "old_event_id": f.event_id,
        "field_key": f.field_key,
        "label": f.label,
        "label_en": f.label_en,
        "field_type": f.field_type,
        "field_order": f.field_order,
        "width": f.width,
        "category": f.category,
        "is_required": f.is_required,
        "is_external": f.is_external,
        "is_internal": f.is_internal,
        "visible_in_overview": f.visible_in_overview,
        "options_json": f.options_json,
        "formula_definition": f.formula_definition,
        "help_text": f.help_text,
    } for f in BookingPersonalField.query.order_by(BookingPersonalField.id).all()]

    entries_out = [{
        "old_id": en.id,
        "old_event_id": en.event_id,
        "order_index": en.order_index,
        "name": en.name,
        "email": en.email,
        "phone": en.phone,
        "status": en.status,
        "form_token": en.form_token,
        "form_submitted_at": en.form_submitted_at.isoformat() if en.form_submitted_at else None,
        "overview_token": en.overview_token,
        "acceptance_sent_at": en.acceptance_sent_at.isoformat() if en.acceptance_sent_at else None,
        "rejection_sent_at": en.rejection_sent_at.isoformat() if en.rejection_sent_at else None,
        "invite_sent_at": en.invite_sent_at.isoformat() if en.invite_sent_at else None,
        "custom_data_json": en.custom_data_json,
        "created_at": en.created_at.isoformat() if en.created_at else None,
        "updated_at": en.updated_at.isoformat() if en.updated_at else None,
    } for en in BookingPersonalEntry.query.order_by(BookingPersonalEntry.id).all()]

    files_out = []
    for bf in BookingPersonalFile.query.order_by(BookingPersonalFile.id).all():
        item = {
            "old_entry_id": bf.entry_id,
            "field_key": bf.field_key,
            "file_path": bf.file_path,
            "file_name": bf.file_name,
            "mime_type": bf.mime_type,
            "file_size": bf.file_size,
            "is_image": bf.is_image,
            "uploaded_at": bf.uploaded_at.isoformat() if bf.uploaded_at else None,
        }
        if bf.file_path:
            b64 = read_file_base64([bf.file_path])
            if b64:
                item["file_content_base64"] = b64
        files_out.append(item)

    return {
        "booking_personal_templates": templates_out,
        "booking_personal_events": events_out,
        "booking_personal_fields": fields_out,
        "booking_personal_entries": entries_out,
        "booking_personal_files": files_out,
    }
