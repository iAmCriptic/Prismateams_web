from app import create_app, db
from app.models import (
    User, Chat, ChatMessage, ChatMember,
    File, FileVersion, Folder,
    CalendarEvent, EventParticipant,
    EmailMessage, EmailPermission, EmailAttachment,
    Credential, Manual,
    SystemSettings, WhitelistEntry,
    NotificationSettings, ChatNotificationSettings,
    PushSubscription, NotificationLog,
    Product, BorrowTransaction
)
import os

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
    print(f"Starte HTTP-Server auf http://0.0.0.0:5000")
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True
    )



