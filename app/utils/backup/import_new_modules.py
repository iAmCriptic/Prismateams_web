"""Backup importers for newer modules: teams, surveys, protocols, meetings, duty_roster, booking_personal."""

from __future__ import annotations

import base64
import os
from typing import Dict, Optional

from app import db
from app.models.booking_personal import (
    BookingPersonalEntry,
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalFile,
    BookingPersonalTemplate,
)
from app.models.canvas import CanvasDocument
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
from app.models.email import Mailbox
from app.models.helpers import (
    Helper,
    HelperArea,
    HelperAreaWish,
    HelperEvent,
    HelperFieldConfig,
    HelperShift,
    HelperVoucherRule,
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
from app.models.todo import TodoItem
from app.models.user import User
from app.utils.backup.file_io import (
    parse_date,
    parse_dt,
    parse_time,
    resolve_team_id,
    resolve_user_id,
    write_base64_file,
)


def import_teams_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
) -> Dict[str, int]:
    team_map: Dict[str, int] = {t.name: t.id for t in Team.query.all()}

    for row in backup_data.get("teams") or []:
        name = row.get("name")
        if not name:
            continue
        team = Team.query.filter_by(name=name).first()
        if not team:
            saved_img = None
            if row.get("image_content_base64"):
                saved = write_base64_file(
                    row["image_content_base64"],
                    "teams",
                    row.get("image_original_name") or "team.png",
                )
                saved_img = os.path.basename(saved) if saved else row.get("image")
            team = Team(
                name=name,
                description=row.get("description"),
                image=saved_img or row.get("image"),
                color=row.get("color"),
                leader_id=resolve_user_id(row.get("leader_email"), user_map),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(team)
            db.session.flush()
        else:
            if row.get("description") is not None:
                team.description = row.get("description")
            if row.get("color") is not None:
                team.color = row.get("color")
            if not team.leader_id and row.get("leader_email"):
                team.leader_id = resolve_user_id(row.get("leader_email"), user_map)
        team_map[name] = team.id

    if backup_data.get("teams"):
        results["imported"].append("teams")

    for row in backup_data.get("team_members") or []:
        tid = team_map.get(row.get("team_name"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if not tid or not uid:
            continue
        if not TeamMember.query.filter_by(team_id=tid, user_id=uid).first():
            db.session.add(TeamMember(
                team_id=tid,
                user_id=uid,
                joined_at=parse_dt(row.get("joined_at")),
            ))

    for row in backup_data.get("team_module_settings") or []:
        tid = team_map.get(row.get("team_name"))
        mkey = row.get("module_key")
        if not tid or not mkey:
            continue
        existing = TeamModuleSetting.query.filter_by(team_id=tid, module_key=mkey).first()
        if existing:
            existing.team_section_enabled = bool(row.get("team_section_enabled", True))
        else:
            db.session.add(TeamModuleSetting(
                team_id=tid,
                module_key=mkey,
                team_section_enabled=bool(row.get("team_section_enabled", True)),
            ))

    for row in backup_data.get("team_invite_codes") or []:
        tid = team_map.get(row.get("team_name"))
        code = row.get("code")
        if not tid or not code:
            continue
        if not TeamInviteCode.query.filter_by(code=code).first():
            aau_dt = parse_dt(row.get("account_active_until"))
            db.session.add(TeamInviteCode(
                code=code,
                team_id=tid,
                created_by_id=resolve_user_id(row.get("created_by_email"), user_map, current_user_id),
                max_uses=row.get("max_uses"),
                uses_count=row.get("uses_count", 0),
                expires_at=parse_dt(row.get("expires_at")),
                account_active_until=aau_dt.date() if aau_dt else None,
                is_active=bool(row.get("is_active", True)),
                role=row.get("role") or "team_only",
                created_at=parse_dt(row.get("created_at")),
            ))

    return team_map


def import_surveys_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
):
    survey_map: Dict[int, int] = {}
    page_map: Dict[int, int] = {}
    question_map: Dict[int, int] = {}
    response_map: Dict[int, int] = {}

    for row in backup_data.get("surveys") or []:
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not creator_id:
            continue
        old_id = row.get("old_id")
        pub_token = row.get("public_token")
        survey = Survey.query.filter_by(public_token=pub_token).first() if pub_token else None
        if not survey:
            survey = Survey(
                title=row.get("title") or "Umfrage",
                description=row.get("description"),
                created_by=creator_id,
                visibility=row.get("visibility") or "private",
                team_id=resolve_team_id(row.get("team_name"), team_map),
                is_active=bool(row.get("is_active", True)),
                is_publicly_fillable=bool(row.get("is_publicly_fillable", False)),
                public_token=pub_token,
                layout_mode=row.get("layout_mode") or "scroll",
                settings_json=row.get("settings_json"),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(survey)
            db.session.flush()
            if row.get("header_image_base64"):
                saved = write_base64_file(
                    row["header_image_base64"],
                    os.path.join("surveys", str(survey.id)),
                    row.get("header_image_name") or "header.png",
                )
                if saved:
                    survey.header_image_path = f"surveys/{survey.id}/{os.path.basename(saved)}"
        if old_id is not None:
            survey_map[old_id] = survey.id

    if backup_data.get("surveys"):
        results["imported"].append("surveys")

    for row in backup_data.get("survey_pages") or []:
        sid = survey_map.get(row.get("old_survey_id"))
        if not sid:
            continue
        old_id = row.get("old_id")
        page = SurveyPage(
            survey_id=sid,
            title=row.get("title"),
            description=row.get("description"),
            page_order=row.get("page_order", 0),
        )
        db.session.add(page)
        db.session.flush()
        if old_id is not None:
            page_map[old_id] = page.id

    for row in backup_data.get("survey_questions") or []:
        pid = page_map.get(row.get("old_page_id"))
        if not pid:
            continue
        old_id = row.get("old_id")
        q = SurveyQuestion(
            page_id=pid,
            question_type=row.get("question_type") or "short_text",
            label=row.get("label") or "Frage",
            description=row.get("description"),
            is_required=bool(row.get("is_required", False)),
            question_order=row.get("question_order", 0),
            config_json=row.get("config_json"),
        )
        db.session.add(q)
        db.session.flush()
        if old_id is not None:
            question_map[old_id] = q.id

    for row in backup_data.get("survey_logic_rules") or []:
        sid = survey_map.get(row.get("old_survey_id"))
        src_qid = question_map.get(row.get("old_source_question_id"))
        if not sid or not src_qid:
            continue
        db.session.add(SurveyLogicRule(
            survey_id=sid,
            source_question_id=src_qid,
            operator=row.get("operator") or "equals",
            value_json=row.get("value_json"),
            action=row.get("action") or "show_question",
            target_page_id=page_map.get(row.get("old_target_page_id")) if row.get("old_target_page_id") else None,
            target_question_id=question_map.get(row.get("old_target_question_id")) if row.get("old_target_question_id") else None,
            rule_order=row.get("rule_order", 0),
        ))

    for row in backup_data.get("survey_responses") or []:
        sid = survey_map.get(row.get("old_survey_id"))
        if not sid:
            continue
        old_id = row.get("old_id")
        pub_token = row.get("public_token")
        resp = SurveyResponse.query.filter_by(public_token=pub_token).first() if pub_token else None
        if not resp:
            resp = SurveyResponse(
                survey_id=sid,
                public_token=pub_token,
                respondent_email=row.get("respondent_email"),
                email_verified_at=parse_dt(row.get("email_verified_at")),
                status=row.get("status") or "draft",
                submitted_at=parse_dt(row.get("submitted_at")),
                user_id=resolve_user_id(row.get("user_email"), user_map),
                ip_hash=row.get("ip_hash"),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(resp)
            db.session.flush()
        if old_id is not None:
            response_map[old_id] = resp.id

    for row in backup_data.get("survey_answers") or []:
        rid = response_map.get(row.get("old_response_id"))
        qid = question_map.get(row.get("old_question_id"))
        if not rid or not qid:
            continue
        if SurveyAnswer.query.filter_by(response_id=rid, question_id=qid).first():
            continue
        file_path = row.get("file_path")
        if row.get("file_content_base64"):
            resp_obj = SurveyResponse.query.get(rid)
            sid = resp_obj.survey_id if resp_obj else 0
            saved = write_base64_file(
                row["file_content_base64"],
                os.path.join("surveys", str(sid), str(rid)),
                row.get("file_original_name") or "upload.bin",
            )
            if saved:
                file_path = f"surveys/{sid}/{rid}/{os.path.basename(saved)}"
        db.session.add(SurveyAnswer(
            response_id=rid,
            question_id=qid,
            value_text=row.get("value_text"),
            value_json=row.get("value_json"),
            file_path=file_path,
        ))


def import_protocols_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
):
    protocol_map: Dict[int, int] = {}
    for row in backup_data.get("protocols") or []:
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not creator_id:
            continue
        old_id = row.get("old_id")
        mdate = parse_date(row.get("meeting_date"))
        stime = parse_time(row.get("start_time"))
        if not mdate or not stime:
            continue
        p = Protocol(
            title=row.get("title") or "Protokoll",
            meeting_date=mdate,
            start_time=stime,
            end_time=parse_time(row.get("end_time")),
            participants_text=row.get("participants_text"),
            excused_text=row.get("excused_text"),
            absent_text=row.get("absent_text"),
            status=row.get("status") or "draft",
            visibility=row.get("visibility") or "public",
            team_id=resolve_team_id(row.get("team_name"), team_map),
            created_by=creator_id,
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
            finalized_at=parse_dt(row.get("finalized_at")),
        )
        db.session.add(p)
        db.session.flush()
        if old_id is not None:
            protocol_map[old_id] = p.id

    if backup_data.get("protocols"):
        results["imported"].append("protocols")

    for row in backup_data.get("protocol_agenda_items") or []:
        pid = protocol_map.get(row.get("old_protocol_id"))
        if not pid:
            continue
        db.session.add(ProtocolAgendaItem(
            protocol_id=pid,
            position=row.get("position", 0),
            title=row.get("title") or "",
            content_html=row.get("content_html"),
        ))


def import_meetings_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
):
    from app.models.chat import Chat

    chat_by_name = {c.name: c.id for c in Chat.query.all() if c.name}
    meeting_map: Dict[int, int] = {}

    for row in backup_data.get("meetings") or []:
        room_id = row.get("room_id")
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, current_user_id)
        if not room_id or not creator_id:
            continue
        old_id = row.get("old_id")
        m = Meeting.query.filter_by(room_id=room_id).first()
        if not m:
            m = Meeting(
                title=row.get("title") or "Meeting",
                room_id=room_id,
                access_mode=row.get("access_mode") or "public",
                status=row.get("status") or "active",
                created_by=creator_id,
                chat_id=chat_by_name.get(row.get("chat_name")) if row.get("chat_name") else None,
                guest_join_token=row.get("guest_join_token") or room_id,
                created_at=parse_dt(row.get("created_at")),
                ended_at=parse_dt(row.get("ended_at")),
                ended_by=resolve_user_id(row.get("ended_by_email"), user_map),
            )
            db.session.add(m)
            db.session.flush()
        if old_id is not None:
            meeting_map[old_id] = m.id

    if backup_data.get("meetings"):
        results["imported"].append("meetings")

    for row in backup_data.get("meeting_invites") or []:
        mid = meeting_map.get(row.get("old_meeting_id"))
        uid = resolve_user_id(row.get("user_email"), user_map)
        if mid and uid and not MeetingInvite.query.filter_by(meeting_id=mid, user_id=uid).first():
            db.session.add(MeetingInvite(
                meeting_id=mid,
                user_id=uid,
                invited_at=parse_dt(row.get("invited_at")),
            ))


def import_duty_roster_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
):
    ext_map: Dict[int, int] = {}
    roster_map: Dict[int, int] = {}
    day_map: Dict[int, int] = {}
    col_map: Dict[int, int] = {}

    for row in backup_data.get("duty_external_persons") or []:
        tid = resolve_team_id(row.get("team_name"), team_map)
        if not tid:
            continue
        old_id = row.get("old_id")
        ext = DutyExternalPerson(
            team_id=tid,
            name=row.get("name") or "Extern",
            valid_from=parse_date(row.get("valid_from")),
            valid_until=parse_date(row.get("valid_until")),
            sort_order=row.get("sort_order", 0),
            is_active=bool(row.get("is_active", True)),
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(ext)
        db.session.flush()
        if old_id is not None:
            ext_map[old_id] = ext.id

    for row in backup_data.get("duty_person_configs") or []:
        tid = resolve_team_id(row.get("team_name"), team_map)
        uid = resolve_user_id(row.get("user_email"), user_map)
        if not tid or not uid:
            continue
        if not DutyPersonConfig.query.filter_by(team_id=tid, user_id=uid).first():
            db.session.add(DutyPersonConfig(
                team_id=tid,
                user_id=uid,
                weekly_hours_soll=row.get("weekly_hours_soll"),
                vacation_days_total=row.get("vacation_days_total"),
                vacation_days_used=row.get("vacation_days_used", 0.0),
                available_for_roster=bool(row.get("available_for_roster", True)),
                valid_from=parse_date(row.get("valid_from")),
                valid_until=parse_date(row.get("valid_until")),
            ))

    for row in backup_data.get("duty_roster_planners") or []:
        tid = resolve_team_id(row.get("team_name"), team_map)
        uid = resolve_user_id(row.get("user_email"), user_map)
        if tid and uid and not DutyRosterPlanner.query.filter_by(team_id=tid, user_id=uid).first():
            db.session.add(DutyRosterPlanner(
                team_id=tid,
                user_id=uid,
                created_at=parse_dt(row.get("created_at")),
            ))

    for row in backup_data.get("duty_rosters") or []:
        tid = resolve_team_id(row.get("team_name"), team_map)
        if not tid:
            continue
        old_id = row.get("old_id")
        roster = DutyRoster.query.filter_by(team_id=tid, year=row.get("year"), month=row.get("month")).first()
        if not roster:
            roster = DutyRoster(
                team_id=tid,
                year=row.get("year"),
                month=row.get("month"),
                title=row.get("title"),
                is_published=bool(row.get("is_published", False)),
                created_by_id=resolve_user_id(row.get("created_by_email"), user_map, current_user_id),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(roster)
            db.session.flush()
        if old_id is not None:
            roster_map[old_id] = roster.id

    if backup_data.get("duty_rosters"):
        results["imported"].append("duty_rosters")

    for row in backup_data.get("duty_roster_days") or []:
        rid = roster_map.get(row.get("old_roster_id"))
        dval = parse_date(row.get("date"))
        if not rid or not dval:
            continue
        old_id = row.get("old_id")
        day = DutyRosterDay.query.filter_by(roster_id=rid, date=dval).first()
        if not day:
            day = DutyRosterDay(
                roster_id=rid,
                date=dval,
                weekday=row.get("weekday"),
                whats_happening=row.get("whats_happening"),
                row_color=row.get("row_color"),
            )
            db.session.add(day)
            db.session.flush()
        if old_id is not None:
            day_map[old_id] = day.id

    for row in backup_data.get("duty_roster_columns") or []:
        rid = roster_map.get(row.get("old_roster_id"))
        if not rid:
            continue
        old_id = row.get("old_id")
        col = DutyRosterColumn(
            roster_id=rid,
            user_id=resolve_user_id(row.get("user_email"), user_map),
            external_person_id=ext_map.get(row.get("old_external_person_id")) if row.get("old_external_person_id") else None,
            external_name=row.get("external_name"),
            sort_order=row.get("sort_order", 0),
            show_in_plan=bool(row.get("show_in_plan", True)),
        )
        db.session.add(col)
        db.session.flush()
        if old_id is not None:
            col_map[old_id] = col.id

    for row in backup_data.get("duty_roster_entries") or []:
        did = day_map.get(row.get("old_day_id"))
        cid = col_map.get(row.get("old_column_id"))
        if not did or not cid:
            continue
        if not DutyRosterEntry.query.filter_by(day_id=did, column_id=cid).first():
            db.session.add(DutyRosterEntry(
                day_id=did,
                column_id=cid,
                start_time=parse_time(row.get("start_time")),
                end_time=parse_time(row.get("end_time")),
                ends_next_day=bool(row.get("ends_next_day", False)),
                entry_type=row.get("entry_type") or "shift",
                label=row.get("label"),
            ))

    for row in backup_data.get("duty_time_entries") or []:
        uid = resolve_user_id(row.get("user_email"), user_map)
        dval = parse_date(row.get("date"))
        if not uid or not dval:
            continue
        db.session.add(DutyTimeEntry(
            user_id=uid,
            team_id=resolve_team_id(row.get("team_name"), team_map),
            date=dval,
            start_time=parse_time(row.get("start_time")),
            end_time=parse_time(row.get("end_time")),
            ends_next_day=bool(row.get("ends_next_day", False)),
            entry_type=row.get("entry_type") or "work",
            note=row.get("note"),
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        ))


def import_booking_personal_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
) -> Dict[int, int]:
    from app.models.email import Mailbox

    mailbox_by_name = {m.name: m.id for m in Mailbox.query.all()}
    event_map: Dict[int, int] = {}
    entry_map: Dict[int, int] = {}

    for row in backup_data.get("booking_personal_templates") or []:
        name = row.get("name")
        if not name or BookingPersonalTemplate.query.filter_by(name=name).first():
            continue
        db.session.add(BookingPersonalTemplate(
            name=name,
            description=row.get("description"),
            is_system_default=bool(row.get("is_system_default", False)),
            fields_schema_json=row.get("fields_schema_json") or "[]",
            created_by=resolve_user_id(row.get("created_by_email"), user_map, current_user_id),
            created_at=parse_dt(row.get("created_at")),
        ))

    for row in backup_data.get("booking_personal_events") or []:
        old_id = row.get("old_id")
        apply_token = row.get("apply_token")
        ev = BookingPersonalEvent.query.filter_by(apply_token=apply_token).first() if apply_token else None
        if not ev:
            ev = BookingPersonalEvent(
                name=row.get("name") or "Event",
                slug=row.get("slug"),
                description=row.get("description"),
                start_date=parse_date(row.get("start_date")),
                end_date=parse_date(row.get("end_date")),
                is_active=bool(row.get("is_active", True)),
                mailbox_id=mailbox_by_name.get(row.get("mailbox_name")) if row.get("mailbox_name") else None,
                apply_token=apply_token,
                apply_enabled=bool(row.get("apply_enabled", True)),
                accept_template_subject=row.get("accept_template_subject") or "",
                accept_template_body=row.get("accept_template_body") or "",
                reject_template_subject=row.get("reject_template_subject") or "",
                reject_template_body=row.get("reject_template_body") or "",
                invite_template_subject=row.get("invite_template_subject") or "",
                invite_template_body=row.get("invite_template_body") or "",
                accept_template_subject_en=row.get("accept_template_subject_en"),
                accept_template_body_en=row.get("accept_template_body_en"),
                reject_template_subject_en=row.get("reject_template_subject_en"),
                reject_template_body_en=row.get("reject_template_body_en"),
                invite_template_subject_en=row.get("invite_template_subject_en"),
                invite_template_body_en=row.get("invite_template_body_en"),
                apply_intro_text=row.get("apply_intro_text"),
                apply_intro_text_en=row.get("apply_intro_text_en"),
                form_intro_text=row.get("form_intro_text"),
                form_intro_text_en=row.get("form_intro_text_en"),
                overview_intro_text=row.get("overview_intro_text"),
                overview_intro_text_en=row.get("overview_intro_text_en"),
                created_by=resolve_user_id(row.get("created_by_email"), user_map, current_user_id),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(ev)
            db.session.flush()
            if row.get("header_image_base64"):
                saved = write_base64_file(
                    row["header_image_base64"],
                    os.path.join("booking_personal", str(ev.id)),
                    row.get("header_image_name") or "header.png",
                )
                if saved:
                    ev.header_image_path = f"/uploads/booking_personal/{ev.id}/{os.path.basename(saved)}"
        if old_id is not None:
            event_map[old_id] = ev.id

    if backup_data.get("booking_personal_events"):
        results["imported"].append("booking_personal_events")

    for row in backup_data.get("booking_personal_fields") or []:
        ev_id = event_map.get(row.get("old_event_id"))
        if not ev_id:
            continue
        db.session.add(BookingPersonalField(
            event_id=ev_id,
            field_key=row.get("field_key") or "field",
            label=row.get("label") or "Feld",
            label_en=row.get("label_en"),
            field_type=row.get("field_type") or "text",
            field_order=row.get("field_order", 0),
            width=row.get("width", 160),
            category=row.get("category"),
            is_required=bool(row.get("is_required", False)),
            is_external=bool(row.get("is_external", False)),
            is_internal=bool(row.get("is_internal", True)),
            visible_in_overview=bool(row.get("visible_in_overview", True)),
            options_json=row.get("options_json"),
            formula_definition=row.get("formula_definition"),
            help_text=row.get("help_text"),
        ))

    for row in backup_data.get("booking_personal_entries") or []:
        ev_id = event_map.get(row.get("old_event_id"))
        if not ev_id:
            continue
        old_id = row.get("old_id")
        form_token = row.get("form_token")
        entry = BookingPersonalEntry.query.filter_by(form_token=form_token).first() if form_token else None
        if not entry:
            entry = BookingPersonalEntry(
                event_id=ev_id,
                order_index=row.get("order_index", 0),
                name=row.get("name"),
                email=row.get("email"),
                phone=row.get("phone"),
                status=row.get("status") or "Angefragt",
                form_token=form_token,
                form_submitted_at=parse_dt(row.get("form_submitted_at")),
                overview_token=row.get("overview_token"),
                acceptance_sent_at=parse_dt(row.get("acceptance_sent_at")),
                rejection_sent_at=parse_dt(row.get("rejection_sent_at")),
                invite_sent_at=parse_dt(row.get("invite_sent_at")),
                custom_data_json=row.get("custom_data_json"),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(entry)
            db.session.flush()
        if old_id is not None:
            entry_map[old_id] = entry.id

    for row in backup_data.get("booking_personal_files") or []:
        eid = entry_map.get(row.get("old_entry_id"))
        if not eid:
            continue
        entry_obj = BookingPersonalEntry.query.get(eid)
        ev_id = entry_obj.event_id if entry_obj else 0
        file_path = row.get("file_path") or ""
        if row.get("file_content_base64"):
            saved = write_base64_file(
                row["file_content_base64"],
                os.path.join("booking_personal", str(ev_id)),
                row.get("file_name") or "file.bin",
            )
            if saved:
                file_path = f"/uploads/booking_personal/{ev_id}/{os.path.basename(saved)}"
        db.session.add(BookingPersonalFile(
            entry_id=eid,
            field_key=row.get("field_key") or "file",
            file_path=file_path,
            file_name=row.get("file_name") or "file",
            mime_type=row.get("mime_type"),
            file_size=row.get("file_size"),
            is_image=bool(row.get("is_image", False)),
            uploaded_at=parse_dt(row.get("uploaded_at")),
        ))

    return event_map


def _fallback_user_id(user_map: Dict[str, int], current_user_id: Optional[int]) -> Optional[int]:
    if current_user_id:
        return current_user_id
    if user_map:
        return next(iter(user_map.values()))
    first_user = User.query.order_by(User.id).first()
    return first_user.id if first_user else None


def import_canvas_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
) -> None:
    docs_data = backup_data.get("canvas_documents")
    if docs_data is None:
        return

    from app.utils.canvas import save_canvas_hyc_file, save_canvas_thumbnail

    fallback_uid = _fallback_user_id(user_map, current_user_id)
    for row in docs_data:
        hyc_id = row.get("hycanvas_design_id")
        if hyc_id and CanvasDocument.query.filter_by(hycanvas_design_id=hyc_id).first():
            continue
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, fallback_uid)
        if not creator_id:
            continue
        doc = CanvasDocument(
            name=row.get("name") or "Canvas",
            design_type=row.get("design_type") or "whiteboard",
            preset_key=row.get("preset_key") or "whiteboard",
            width=int(row.get("width") or 1920),
            height=int(row.get("height") or 1080),
            hycanvas_design_id=hyc_id,
            created_by=creator_id,
            visibility=row.get("visibility") or "private",
            team_id=resolve_team_id(row.get("team_name"), team_map),
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        )
        db.session.add(doc)
        db.session.flush()

        if row.get("file_content_base64"):
            try:
                raw_bytes = base64.b64decode(row["file_content_base64"])
                doc.file_path = save_canvas_hyc_file(doc.id, doc.name, raw_bytes)
            except Exception:
                pass
        if row.get("thumbnail_content_base64"):
            try:
                thumb_bytes = base64.b64decode(row["thumbnail_content_base64"])
                doc.thumbnail_path = save_canvas_thumbnail(doc.id, thumb_bytes)
            except Exception:
                pass

    results["imported"].append("canvas")


def import_todos_bundle(
    backup_data: Dict,
    user_map: Dict[str, int],
    current_user_id: Optional[int],
    results: Dict,
    team_map: Optional[Dict[str, int]] = None,
) -> None:
    todos_data = backup_data.get("todo_items")
    if todos_data is None:
        return

    fallback_uid = _fallback_user_id(user_map, current_user_id)
    for row in todos_data:
        creator_id = resolve_user_id(row.get("created_by_email"), user_map, fallback_uid)
        if not creator_id:
            continue
        db.session.add(TodoItem(
            title=row.get("title") or "",
            visibility=row.get("visibility") or "private",
            team_id=resolve_team_id(row.get("team_name"), team_map),
            created_by_id=creator_id,
            assignee_id=resolve_user_id(row.get("assignee_email"), user_map),
            due_date=parse_date(row.get("due_date")),
            due_time=parse_time(row.get("due_time")),
            is_completed=bool(row.get("is_completed", False)),
            completed_at=parse_dt(row.get("completed_at")),
            completed_by_id=resolve_user_id(row.get("completed_by_email"), user_map),
            position=int(row.get("position") or 0),
            created_at=parse_dt(row.get("created_at")),
            updated_at=parse_dt(row.get("updated_at")),
        ))

    results["imported"].append("todos")


def import_helpers_bundle(
    backup_data: Dict,
    results: Dict,
) -> Dict[int, int]:
    event_map: Dict[int, int] = {}
    area_map: Dict[int, int] = {}
    helper_map: Dict[int, int] = {}

    if not any(k in backup_data for k in ("helper_events", "helper_areas", "helpers")):
        return event_map

    mb_by_name = {m.name: m.id for m in Mailbox.query.all()}

    for row in backup_data.get("helper_events") or []:
        old_id = row.get("old_id")
        apply_token = row.get("apply_token")
        ev = HelperEvent.query.filter_by(apply_token=apply_token).first() if apply_token else None
        if not ev:
            ev = HelperEvent(
                name=row.get("name") or "Helfer-Event",
                slug=row.get("slug"),
                description=row.get("description"),
                start_date=parse_date(row.get("start_date")),
                end_date=parse_date(row.get("end_date")),
                is_active=bool(row.get("is_active", True)),
                apply_token=apply_token,
                apply_enabled=bool(row.get("apply_enabled", True)),
                voucher_calc_mode=row.get("voucher_calc_mode") or "per_shift",
                mailbox_id=mb_by_name.get(row.get("mailbox_name")) if row.get("mailbox_name") else None,
                mail_template_subject=row.get("mail_template_subject") or "Dein Schichtplan für {{ event_name }}",
                mail_template_body=row.get("mail_template_body") or "",
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(ev)
            db.session.flush()
        if old_id is not None:
            event_map[old_id] = ev.id

    for row in backup_data.get("helper_areas") or []:
        old_id = row.get("old_id")
        ev_id = event_map.get(row.get("old_event_id"))
        if not ev_id:
            continue
        name = row.get("name") or "Bereich"
        area = HelperArea.query.filter_by(event_id=ev_id, name=name).first()
        if not area:
            area = HelperArea(
                event_id=ev_id,
                name=name,
                description=row.get("description"),
                is_public_selectable=bool(row.get("is_public_selectable", True)),
                sort_order=int(row.get("sort_order") or 0),
            )
            db.session.add(area)
            db.session.flush()
        if old_id is not None:
            area_map[old_id] = area.id

    for row in backup_data.get("helpers") or []:
        old_id = row.get("old_id")
        ev_id = event_map.get(row.get("old_event_id"))
        if not ev_id:
            continue
        email = row.get("email") or ""
        helper = Helper.query.filter_by(event_id=ev_id, email=email).first() if email else None
        if not helper:
            helper = Helper(
                event_id=ev_id,
                first_name=row.get("first_name") or "",
                last_name=row.get("last_name") or "",
                email=email,
                phone=row.get("phone"),
                tshirt_size=row.get("tshirt_size"),
                allergies=row.get("allergies"),
                status=row.get("status") or "registered",
                custom_fields=row.get("custom_fields") if row.get("custom_fields") is not None else {},
                dsgvo_accepted=bool(row.get("dsgvo_accepted", False)),
                dsgvo_accepted_at=parse_dt(row.get("dsgvo_accepted_at")),
                vouchers_issued=bool(row.get("vouchers_issued", False)),
                vouchers_issued_at=parse_dt(row.get("vouchers_issued_at")),
                created_at=parse_dt(row.get("created_at")),
                updated_at=parse_dt(row.get("updated_at")),
            )
            db.session.add(helper)
            db.session.flush()
        if old_id is not None:
            helper_map[old_id] = helper.id

    for row in backup_data.get("helper_area_wishes") or []:
        h_id = helper_map.get(row.get("old_helper_id"))
        a_id = area_map.get(row.get("old_area_id"))
        if not (h_id and a_id):
            continue
        if not HelperAreaWish.query.filter_by(helper_id=h_id, area_id=a_id).first():
            db.session.add(HelperAreaWish(
                helper_id=h_id,
                area_id=a_id,
                priority=int(row.get("priority") or 1),
                available_days=row.get("available_days") if row.get("available_days") is not None else [],
                notes=row.get("notes"),
            ))

    for row in backup_data.get("helper_shifts") or []:
        ev_id = event_map.get(row.get("old_event_id"))
        a_id = area_map.get(row.get("old_area_id"))
        if not (ev_id and a_id):
            continue
        db.session.add(HelperShift(
            event_id=ev_id,
            area_id=a_id,
            helper_id=helper_map.get(row.get("old_helper_id")) if row.get("old_helper_id") else None,
            group_count=int(row.get("group_count") or 1),
            role_label=row.get("role_label"),
            day_label=row.get("day_label") or "Freitag",
            date=parse_date(row.get("date")),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
            hours=float(row.get("hours") or 0.0),
            is_head=bool(row.get("is_head", False)),
            food_override=row.get("food_override"),
            drinks_override=row.get("drinks_override"),
            notes=row.get("notes"),
            created_at=parse_dt(row.get("created_at")),
        ))

    for row in backup_data.get("helper_field_configs") or []:
        ev_id = event_map.get(row.get("old_event_id"))
        field_key = row.get("field_key")
        if not (ev_id and field_key):
            continue
        if not HelperFieldConfig.query.filter_by(event_id=ev_id, field_key=field_key).first():
            db.session.add(HelperFieldConfig(
                event_id=ev_id,
                field_key=field_key,
                label=row.get("label") or field_key,
                field_type=row.get("field_type") or "text",
                options=row.get("options") if row.get("options") is not None else [],
                is_public=bool(row.get("is_public", True)),
                is_required=bool(row.get("is_required", False)),
                admin_only=bool(row.get("admin_only", False)),
                show_in_overview=bool(row.get("show_in_overview", False)),
                is_active=bool(row.get("is_active", True)),
                is_core=bool(row.get("is_core", False)),
                sort_order=int(row.get("sort_order") or 0),
            ))

    for row in backup_data.get("helper_voucher_rules") or []:
        ev_id = event_map.get(row.get("old_event_id"))
        if not ev_id:
            continue
        db.session.add(HelperVoucherRule(
            event_id=ev_id,
            area_id=area_map.get(row.get("old_area_id")) if row.get("old_area_id") else None,
            name=row.get("name") or "Regel",
            min_hours=float(row.get("min_hours") or 0.0),
            max_hours=row.get("max_hours"),
            food_count=int(row.get("food_count") or 0),
            drinks_count=int(row.get("drinks_count") or 0),
            head_bonus_drinks=int(row.get("head_bonus_drinks") or 0),
        ))

    results["imported"].append("helpers")
    return event_map
