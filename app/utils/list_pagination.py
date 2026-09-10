"""Shared SQLAlchemy list pagination for module index pages."""

from flask import request

DEFAULT_LIST_PER_PAGE = 24


def request_list_page(arg: str = 'page') -> int:
    return max(1, request.args.get(arg, 1, type=int) or 1)


def paginate_list(query, per_page: int = DEFAULT_LIST_PER_PAGE, *, page=None, page_arg: str = 'page'):
    """Return ``(items, pagination)`` with ``error_out=False``."""
    if page is None:
        page = request_list_page(page_arg)
    else:
        page = max(1, int(page) or 1)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return pagination.items, pagination
