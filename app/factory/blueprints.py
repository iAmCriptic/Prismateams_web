"""Blueprint registration."""


from app import csrf

def register_blueprints(app):
    """Register application blueprints and CSRF exemptions."""
    from app.blueprints.setup import setup_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.dashboard import dashboard_bp
    from app.blueprints.chat import chat_bp
    from app.blueprints.files import files_bp
    from app.blueprints.calendar import calendar_bp
    from app.blueprints.email import email_bp
    from app.blueprints.contacts import contacts_bp
    from app.blueprints.credentials import credentials_bp
    from app.blueprints.manuals import manuals_bp
    from app.blueprints.settings import settings_bp
    from app.blueprints.api import api_bp
    from app.blueprints.errors import errors_bp
    from app.blueprints.inventory import inventory_bp
    from app.blueprints.inventory_vnext import inventory_vnext_bp
    from app.blueprints.wiki import wiki_bp
    from app.blueprints.comments import comments_bp
    from app.blueprints.booking import booking_bp
    from app.blueprints.music import music_bp
    from app.blueprints.sse import sse_bp
    from app.blueprints.assessment import assessment_bp
    from app.blueprints.shortlinks import shortlinks_bp
    from app.blueprints.events import events_bp
    from app.blueprints.media_downloader import media_downloader_bp
    from app.blueprints.file_converter import file_converter_bp
    from app.blueprints.kanban import kanban_bp
    from app.blueprints.excalidraw import excalidraw_bp
    from app.blueprints.surveys import surveys_bp
    from app.blueprints.protocols import protocols_bp
    from app.blueprints.meetings import meetings_bp
    
    app.register_blueprint(setup_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(files_bp, url_prefix='/files')
    app.register_blueprint(calendar_bp, url_prefix='/calendar')
    app.register_blueprint(email_bp, url_prefix='/email')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(credentials_bp, url_prefix='/credentials')
    app.register_blueprint(manuals_bp, url_prefix='/manuals')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')
    if app.config.get('ENABLE_ERROR_TEST_ROUTES'):
        app.register_blueprint(errors_bp, url_prefix='/test')
        app.logger.info('Error-Testrouten aktiv unter /test/… (ENABLE_ERROR_TEST_ROUTES)')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(inventory_vnext_bp)
    app.register_blueprint(wiki_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(booking_bp, url_prefix='/booking')
    app.register_blueprint(music_bp)
    app.register_blueprint(sse_bp, url_prefix='/sse')
    app.register_blueprint(assessment_bp)
    app.register_blueprint(shortlinks_bp)
    app.register_blueprint(events_bp, url_prefix='/events')
    app.register_blueprint(media_downloader_bp)
    app.register_blueprint(file_converter_bp)
    app.register_blueprint(kanban_bp, url_prefix='/kanban')
    app.register_blueprint(excalidraw_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(protocols_bp)
    app.register_blueprint(meetings_bp)

    # Server-to-server callbacks ohne Browser-CSRF-Token.
    # Euro-Office: CSRF-Exempt nötig; kompensierendes Control ist JWT
    # (verify_onlyoffice_callback_token). Unsigned nur Dev/Test oder
    # ONLYOFFICE_ALLOW_UNSIGNED_CALLBACKS=true.
    for endpoint in (
        'files.onlyoffice_callback',
        'files.share_onlyoffice_callback',
        'kanban.onlyoffice_callback',
        'api.api_login',  # credential login (mobile/API clients)
        # Inventory Mobile API (Bearer): keine Browser-CSRF-Tokens
        'inventory.api_mobile_borrow',
        'inventory.api_mobile_return',
        'inventory.api_mobile_scan',
    ):
        view = app.view_functions.get(endpoint)
        if view is not None:
            csrf.exempt(view)
