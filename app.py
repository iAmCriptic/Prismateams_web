from app import create_app, db
from app.models import *
import os

# Create the Flask application
app = create_app(os.getenv('FLASK_ENV', 'development'))


@app.shell_context_processor
def make_shell_context():
    """Make database and models available in Flask shell."""
    return {
        'db': db,
        'User': User,
        'Chat': Chat,
        'ChatMessage': ChatMessage,
        'ChatMember': ChatMember,
        'File': File,
        'FileVersion': FileVersion,
        'Folder': Folder,
        'CalendarEvent': CalendarEvent,
        'EventParticipant': EventParticipant,
        'EmailMessage': EmailMessage,
        'EmailPermission': EmailPermission,
        'EmailAttachment': EmailAttachment,
        'Credential': Credential,
        'Manual': Manual,
        'Canvas': Canvas,
        'CanvasTextField': CanvasTextField,
        'SystemSettings': SystemSettings,
        'WhitelistEntry': WhitelistEntry,
        'NotificationSettings': NotificationSettings,
        'ChatNotificationSettings': ChatNotificationSettings,
        'PushSubscription': PushSubscription,
        'NotificationLog': NotificationLog,
        'Product': Product,
        'BorrowTransaction': BorrowTransaction,
    }


if __name__ == '__main__':
    from app import socketio
    import os
    
    # SSL-Zertifikate für HTTPS
    cert_file = os.path.join(os.path.expanduser('~'), '127.0.0.1.pem')
    key_file = os.path.join(os.path.expanduser('~'), '127.0.0.1-key.pem')
    
    # Prüfe ob Zertifikate existieren
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print(f"Starte HTTPS-Server auf https://0.0.0.0:5000")
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=True,
            allow_unsafe_werkzeug=True,
            certfile=cert_file,
            keyfile=key_file
        )
    else:
        print(f"SSL-Zertifikate nicht gefunden. Starte HTTP-Server auf http://0.0.0.0:5000")
        print(f"Erwartete Dateien: {cert_file} und {key_file}")
        socketio.run(
            app,
            host='0.0.0.0',
            port=5000,
            debug=True,
            allow_unsafe_werkzeug=True
        )



