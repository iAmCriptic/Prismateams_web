"""Files module package. Public API matches the former files.py."""

from app.blueprints.files._bp import (
    FILES_BROWSE_PAGE_SIZE,
    MAX_FILE_PREVIEW_CHARS,
    MAX_FILE_VERSIONS,
    files_bp,
)
from app.blueprints.files.helpers import _is_guest_user, _paginate_browse_items

# Register routes on files_bp
from app.blueprints.files import crud as _crud  # noqa: F401
from app.blueprints.files import dropbox as _dropbox  # noqa: F401
from app.blueprints.files import media as _media  # noqa: F401
from app.blueprints.files import onlyoffice as _onlyoffice  # noqa: F401
from app.blueprints.files import onlyoffice_io as _onlyoffice_io  # noqa: F401
from app.blueprints.files import share as _share  # noqa: F401
from app.blueprints.files import trash as _trash  # noqa: F401
from app.blueprints.files import upload as _upload  # noqa: F401

from app.blueprints.files_browse import register_browse_routes

register_browse_routes(files_bp)

__all__ = [
    "FILES_BROWSE_PAGE_SIZE",
    "MAX_FILE_PREVIEW_CHARS",
    "MAX_FILE_VERSIONS",
    "_is_guest_user",
    "_paginate_browse_items",
    "files_bp",
]
