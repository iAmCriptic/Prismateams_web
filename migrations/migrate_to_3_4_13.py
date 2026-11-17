"""
Portal 3.4.13: Ensure each team has exactly one calendar; deduplicate team calendars and duplicate teams.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def run(db=None, report=None):
    from sqlalchemy import inspect, text

    if db is None:
        from app import create_app, db as _db
        app = create_app()
        ctx = app.app_context()
        ctx.push()
        db = _db
    else:
        ctx = None

    class _Nop:
        def note_ok(self, *a, **k): pass
        def note_warn(self, *a, **k): pass
        def note_skip(self, *a, **k): pass
        def note_error(self, *a, **k): pass

    report = report or _Nop()

    try:
        from app.models.team import Team, TeamMember, TeamInviteCode, TeamModuleSetting
        from app.models.calendar import Calendar, CalendarEvent
        from app.models.chat import Chat, ChatMessage, ChatMember
        from app.utils.multi_calendars import get_public_calendar, DEFAULT_TEAM_COLOR

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        dialect = db.engine.dialect.name

        # -------------------------------------------------------------
        # 1. Merge duplicate teams (same normalized name)
        # -------------------------------------------------------------
        if 'teams' in tables:
            all_teams = Team.query.order_by(Team.id.asc()).all()
            by_name = defaultdict(list)
            for t in all_teams:
                key = (t.name or '').strip().lower()
                by_name[key].append(t)

            merged_teams_count = 0
            for key, team_list in by_name.items():
                if len(team_list) <= 1:
                    continue

                # Pick canonical team: prefer one with leader or members, else lowest id
                def _score_team(t):
                    score = 0
                    if t.leader_id is not None:
                        score += 10
                    score += len(t.members or [])
                    return score

                sorted_teams = sorted(team_list, key=_score_team, reverse=True)
                canonical = sorted_teams[0]
                duplicates = sorted_teams[1:]

                canonical_member_ids = {m.user_id for m in canonical.members}

                for dup in duplicates:
                    # Move memberships
                    for m in list(dup.members):
                        if m.user_id not in canonical_member_ids:
                            canonical_member_ids.add(m.user_id)
                            db.session.add(TeamMember(team_id=canonical.id, user_id=m.user_id))
                        db.session.delete(m)

                    # Move invite codes
                    TeamInviteCode.query.filter_by(team_id=dup.id).update(
                        {TeamInviteCode.team_id: canonical.id},
                        synchronize_session=False,
                    )

                    # Move module settings
                    existing_mod_keys = {
                        s.module_key for s in TeamModuleSetting.query.filter_by(team_id=canonical.id).all()
                    }
                    for ms in list(dup.module_settings):
                        if ms.module_key not in existing_mod_keys:
                            ms.team_id = canonical.id
                            existing_mod_keys.add(ms.module_key)
                        else:
                            db.session.delete(ms)

                    # Move Team Chats
                    dup_chat = Chat.query.filter_by(team_id=dup.id).first()
                    canonical_chat = Chat.query.filter_by(team_id=canonical.id).first()
                    if dup_chat:
                        if canonical_chat:
                            ChatMessage.query.filter_by(chat_id=dup_chat.id).update(
                                {ChatMessage.chat_id: canonical_chat.id},
                                synchronize_session=False,
                            )
                            ChatMember.query.filter_by(chat_id=dup_chat.id).delete(synchronize_session=False)
                            db.session.delete(dup_chat)
                        else:
                            dup_chat.team_id = canonical.id

                    # Reassign all other known foreign keys to teams.id
                    table_col_pairs = [
                        ('cloud_imports', 'team_id'),
                        ('contacts', 'team_id'),
                        ('credentials', 'team_id'),
                        ('credential_shares', 'team_id'),
                        ('duty_rosters', 'team_id'),
                        ('duty_roster_shifts', 'team_id'),
                        ('duty_roster_assignments', 'team_id'),
                        ('duty_roster_columns', 'team_id'),
                        ('duty_roster_notifications', 'team_id'),
                        ('email_permissions', 'team_id'),
                        ('excalidraw_rooms', 'team_id'),
                        ('files', 'team_id'),
                        ('folders', 'team_id'),
                        ('file_shares', 'grantee_team_id'),
                        ('kanban_boards', 'team_id'),
                        ('manual_categories', 'team_id'),
                        ('manual_articles', 'team_id'),
                        ('protocols', 'team_id'),
                        ('shortlinks', 'team_id'),
                        ('surveys', 'team_id'),
                        ('wiki_articles', 'team_id'),
                    ]
                    for tbl, col in table_col_pairs:
                        if tbl in tables:
                            try:
                                with db.engine.begin() as conn:
                                    conn.execute(text(
                                        f"UPDATE {tbl} SET {col} = :canonical_id WHERE {col} = :dup_id"
                                    ), {'canonical_id': canonical.id, 'dup_id': dup.id})
                            except Exception:
                                pass

                    # Move calendars of duplicate team to canonical team
                    Calendar.query.filter_by(calendar_type='team', team_id=dup.id).update(
                        {Calendar.team_id: canonical.id},
                        synchronize_session=False,
                    )

                    db.session.delete(dup)
                    merged_teams_count += 1

            if merged_teams_count:
                db.session.commit()
                report.note_ok(f'{merged_teams_count} doppelte(s) Team(s) zusammengeführt')
            else:
                report.note_skip('keine doppelten Teams vorhanden')

        # -------------------------------------------------------------
        # 2. Deduplicate team calendars: exactly one calendar per team
        # -------------------------------------------------------------
        if 'calendars' in tables:
            public_cal = get_public_calendar()
            # Clean up orphaned team calendars (team_id is null or invalid)
            valid_team_ids = {t.id for t in Team.query.all()} if 'teams' in tables else set()
            orphans = Calendar.query.filter(
                Calendar.calendar_type == 'team',
                (~Calendar.team_id.in_(list(valid_team_ids) or [-1])) | (Calendar.team_id.is_(None)),
            ).all()
            for orphan in orphans:
                if public_cal and public_cal.id != orphan.id:
                    CalendarEvent.query.filter_by(calendar_id=orphan.id).update(
                        {CalendarEvent.calendar_id: public_cal.id},
                        synchronize_session=False,
                    )
                db.session.delete(orphan)

            # Consolidate calendars per existing team
            merged_cals_count = 0
            if 'teams' in tables:
                for team in Team.query.all():
                    team_cals = (
                        Calendar.query.filter_by(calendar_type='team', team_id=team.id)
                        .order_by(Calendar.is_default.desc(), Calendar.id.asc())
                        .all()
                    )
                    if not team_cals:
                        # Create missing team calendar
                        cal = Calendar(
                            name=team.name or 'Team-Kalender',
                            calendar_type='team',
                            team_id=team.id,
                            owner_id=team.leader_id,
                            color=team.color or DEFAULT_TEAM_COLOR,
                            is_default=True,
                        )
                        db.session.add(cal)
                    else:
                        primary = team_cals[0]
                        primary.is_default = True
                        primary.name = team.name
                        if team.color:
                            primary.color = team.color
                        if len(team_cals) > 1:
                            for extra in team_cals[1:]:
                                CalendarEvent.query.filter_by(calendar_id=extra.id).update(
                                    {CalendarEvent.calendar_id: primary.id},
                                    synchronize_session=False,
                                )
                                db.session.delete(extra)
                                merged_cals_count += 1

            db.session.commit()
            if merged_cals_count:
                report.note_ok(f'{merged_cals_count} überzählige Team-Kalender bereinigt')
            else:
                report.note_skip('keine überzähligen Team-Kalender vorhanden')

        # -------------------------------------------------------------
        # 3. Best-effort Unique-Index on teams(name) and calendars(team_id)
        # -------------------------------------------------------------
        try:
            if 'teams' in tables:
                indexes = {idx['name'] for idx in inspector.get_indexes('teams')}
                if 'uq_teams_name' not in indexes:
                    with db.engine.begin() as conn:
                        if dialect in ('sqlite', 'postgresql'):
                            conn.execute(text(
                                'CREATE UNIQUE INDEX IF NOT EXISTS uq_teams_name ON teams (name)'
                            ))
                        else:
                            conn.execute(text(
                                'CREATE UNIQUE INDEX uq_teams_name ON teams (name)'
                            ))
                    report.note_ok('uq_teams_name angelegt')
        except Exception as exc:
            report.note_warn(f'uq_teams_name: {exc}')

        try:
            if 'calendars' in tables:
                indexes = {idx['name'] for idx in inspector.get_indexes('calendars')}
                if 'uq_calendars_team_id' not in indexes:
                    with db.engine.begin() as conn:
                        if dialect in ('sqlite', 'postgresql'):
                            conn.execute(text(
                                'CREATE UNIQUE INDEX IF NOT EXISTS uq_calendars_team_id ON calendars (team_id)'
                            ))
                        else:
                            conn.execute(text(
                                'CREATE UNIQUE INDEX uq_calendars_team_id ON calendars (team_id)'
                            ))
                    report.note_ok('uq_calendars_team_id angelegt')
        except Exception as exc:
            report.note_warn(f'uq_calendars_team_id: {exc}')

    except Exception as exc:
        report.note_error(f'migrate_to_3_4_13 failed: {exc}')
        raise
    finally:
        if ctx is not None:
            ctx.pop()


if __name__ == '__main__':
    run()
