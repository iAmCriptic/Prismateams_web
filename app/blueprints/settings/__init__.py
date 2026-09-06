"""Settings module package. Public API matches the former settings.py."""

from app.blueprints.settings._bp import settings_bp

# Register routes on settings_bp
from app.blueprints.settings import account as _account  # noqa: F401
from app.blueprints.settings import users as _users  # noqa: F401
from app.blueprints.settings import teams as _teams  # noqa: F401
from app.blueprints.settings import admin_core as _admin_core  # noqa: F401
from app.blueprints.settings import mailboxes as _mailboxes  # noqa: F401
from app.blueprints.settings import admin_extra as _admin_extra  # noqa: F401
from app.blueprints.settings import security as _security  # noqa: F401

from app.blueprints.settings_cloud_import import register_cloud_import_routes

register_cloud_import_routes(settings_bp)

__all__ = ["settings_bp"]
