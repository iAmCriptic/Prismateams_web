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
    }


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)



