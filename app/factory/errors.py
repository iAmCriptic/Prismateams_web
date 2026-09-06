"""Error handlers."""


from flask import jsonify, render_template, request

from app import db

def register_error_handlers(app):
    """HTTP and unhandled-exception error pages."""
    def _error_detail(error):
        """Human-readable detail for error pages (server log / exception text)."""
        if error is None:
            return None
        detail = getattr(error, 'description', None) or str(error)
        detail = (detail or '').strip()
        return detail or None

    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Bad request', 'message': str(error)}), 400
        return render_template('errors/400.html', error_detail=_error_detail(error)), 400
    
    @app.errorhandler(403)
    def forbidden(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Forbidden', 'message': str(error)}), 403
        return render_template('errors/403.html', error_detail=_error_detail(error)), 403
    
    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f"404 Not Found: {request.url}")
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Not found', 'path': request.path}), 404
        return render_template('errors/404.html', error_detail=_error_detail(error)), 404
    
    @app.errorhandler(429)
    def too_many_requests(error):
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Too many requests', 'message': str(error)}), 429
        return render_template('errors/429.html', error_detail=_error_detail(error)), 429
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        app.logger.warning(f"413 Request Entity Too Large: {request.url}")
        wants_json = (
            request.path.startswith('/api/')
            or request.path.startswith('/files/api/')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in (request.headers.get('Accept') or '')
        )
        msg = 'Die hochgeladene Datei überschreitet das maximale Größenlimit.'
        if wants_json:
            return jsonify({
                'success': False,
                'error': 'File too large',
                'message': msg,
                'messages': [{'category': 'danger', 'text': msg}],
            }), 413
        try:
            from app.utils.file_storage_limits import format_bytes_de, get_max_configured_file_size
            max_label = format_bytes_de(get_max_configured_file_size())
            msg = f'Die hochgeladene Datei überschreitet das maximale Größenlimit (max. {max_label} pro Datei).'
        except Exception:
            pass
        max_size_mb = (app.config.get('MAX_CONTENT_LENGTH') or (100 * 1024 * 1024)) / (1024 * 1024)
        return render_template(
            'errors/413.html',
            max_size_mb=max_size_mb,
            error_detail=_error_detail(error),
        ), 413
    
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}", exc_info=True)
        db.session.rollback()
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(error)}), 500
        return render_template('errors/500.html', error_detail=_error_detail(error)), 500
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        from werkzeug.exceptions import RequestEntityTooLarge
        if isinstance(e, RequestEntityTooLarge):
            raise
        
        app.logger.error(f"Unhandled exception: {e}", exc_info=True)
        
        db.session.rollback()
        
        if request.path.startswith('/api/') or request.path.startswith('/files/api/'):
            return jsonify({'error': 'Internal server error', 'message': str(e)}), 500
        return render_template('errors/500.html', error_detail=_error_detail(e)), 500
    
    @app.errorhandler(ValueError)
    def handle_value_error(e):
        app.logger.warning(f"Value error: {e}")
        return render_template('errors/generic.html', 
                             error_code='400',
                             error_title='Ungültige Eingabe',
                             error_message=str(e),
                             error_detail=_error_detail(e)), 400
    
    @app.errorhandler(PermissionError)
    def handle_permission_error(e):
        app.logger.warning(f"Permission error: {e}")
        return render_template('errors/403.html', error_detail=_error_detail(e)), 403
