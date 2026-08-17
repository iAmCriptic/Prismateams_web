"""Ensure and sync a group chat for each Team."""

from app import db
from app.models.chat import Chat, ChatMember
from app.models.team import Team, TeamMember


def _team_user_ids(team):
    ids = {m.user_id for m in TeamMember.query.filter_by(team_id=team.id).all()}
    if team.leader_id:
        ids.add(team.leader_id)
    return ids


def get_team_chat(team_or_id):
    team_id = team_or_id.id if hasattr(team_or_id, 'id') else team_or_id
    if not team_id:
        return None
    return Chat.query.filter_by(team_id=team_id).first()


def ensure_team_chat(team, created_by=None):
    """Create or return the team's bound group chat and sync membership."""
    if not team or not getattr(team, 'id', None):
        return None

    chat = Chat.query.filter_by(team_id=team.id).first()
    if not chat:
        chat = Chat(
            name=(team.name or 'Team').strip() or 'Team',
            description=team.description,
            is_main_chat=False,
            is_direct_message=False,
            team_id=team.id,
            created_by=created_by or team.leader_id,
        )
        db.session.add(chat)
        db.session.flush()

    sync_team_chat_name(team, chat=chat)
    sync_team_chat_members(team, chat=chat)
    return chat


def sync_team_chat_name(team, chat=None):
    if not team:
        return
    chat = chat or Chat.query.filter_by(team_id=team.id).first()
    if not chat:
        return
    name = (team.name or '').strip()
    if name and chat.name != name:
        chat.name = name
    if team.description is not None and chat.description != team.description:
        chat.description = team.description


def sync_team_chat_members(team, chat=None):
    """Membership follows the team. Messages are kept when someone is removed."""
    if not team:
        return
    chat = chat or Chat.query.filter_by(team_id=team.id).first()
    if not chat:
        return

    wanted = _team_user_ids(team)
    existing = {
        m.user_id: m
        for m in ChatMember.query.filter_by(chat_id=chat.id).all()
    }

    for user_id in wanted - set(existing):
        db.session.add(ChatMember(chat_id=chat.id, user_id=user_id))

    for user_id, membership in existing.items():
        if user_id not in wanted:
            db.session.delete(membership)


def unlink_team_chat(team_id):
    """Keep the group chat after the team is deleted; drop the team binding."""
    if not team_id:
        return
    chat = Chat.query.filter_by(team_id=team_id).first()
    if chat:
        chat.team_id = None


def ensure_all_team_chats():
    """Backfill team chats for existing teams (idempotent)."""
    teams = Team.query.all()
    for team in teams:
        ensure_team_chat(team)
    return len(teams)
