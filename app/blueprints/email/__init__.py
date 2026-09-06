"""Email module package. Public API matches the former email.py."""

from app.blueprints.email._bp import EMAIL_LIST_PER_PAGE, email_bp, logger
from app.blueprints.email.imap_client import (
    _is_placeholder_imap_config,
    connect_imap,
    probe_imap_connection,
)
from app.blueprints.email.scheduler import start_email_sync
from app.blueprints.email.sync import cleanup_old_emails, sync_all_configured_mailboxes, sync_emails_from_folder

# Register routes on email_bp
from app.blueprints.email import actions as _actions  # noqa: F401
from app.blueprints.email import compose as _compose  # noqa: F401
from app.blueprints.email import views as _views  # noqa: F401

__all__ = [
    "EMAIL_LIST_PER_PAGE",
    "_is_placeholder_imap_config",
    "cleanup_old_emails",
    "connect_imap",
    "email_bp",
    "logger",
    "probe_imap_connection",
    "start_email_sync",
    "sync_all_configured_mailboxes",
    "sync_emails_from_folder",
]
