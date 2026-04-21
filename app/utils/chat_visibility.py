from app.models.user import User


SYSTEM_ANONYMOUS_EMAIL = "anonymous@system.local"


def visible_chat_user_filters():
    """Return SQLAlchemy filters for users visible in chats."""
    return [User.email != SYSTEM_ANONYMOUS_EMAIL]


def selectable_chat_user_filters(include_guests=True):
    """Return SQLAlchemy filters for users that can be selected for chats."""
    filters = [User.is_active.is_(True), User.email != SYSTEM_ANONYMOUS_EMAIL]
    if not include_guests:
        filters.append(~User.is_guest)
    return filters
