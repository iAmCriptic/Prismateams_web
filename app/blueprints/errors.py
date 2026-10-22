from flask import Blueprint, abort

errors_bp = Blueprint('errors', __name__)


@errors_bp.route('/404')
def test_404():
    """Test route for 404 error page."""
    abort(404)


@errors_bp.route('/403')
def test_403():
    """Test route for 403 error page."""
    abort(403)


@errors_bp.route('/400')
def test_400():
    """Test route for 400 error page."""
    abort(400)


@errors_bp.route('/429')
def test_429():
    """Test route for 429 error page."""
    abort(429)


@errors_bp.route('/500')
def test_500():
    """Test route for 500 error page."""
    abort(500)


@errors_bp.route('/exception')
def test_exception():
    """Test route for unhandled exception."""
    raise Exception("Test exception for error handling")
