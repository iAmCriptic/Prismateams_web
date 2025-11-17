import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration."""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI') or 'sqlite:///teamportal.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
        'pool_timeout': 20,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'connect_timeout': 10,
            'read_timeout': 300,  # 5 minutes for large attachments
            'write_timeout': 300,  # 5 minutes for large attachments
        }
    }
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_SECURE = False  # HTTP für Entwicklung im Netzwerk
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME')
    MAIL_SENDER_NAME = os.environ.get('MAIL_SENDER_NAME', '')  # Optional: Anzeigename für Absender
    
    # IMAP
    IMAP_SERVER = os.environ.get('IMAP_SERVER')
    IMAP_PORT = int(os.environ.get('IMAP_PORT', 993))
    IMAP_USE_SSL = os.environ.get('IMAP_USE_SSL', 'True').lower() == 'true'
    
    # Uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 524288000))  # 500MB (erhöht für Backup-Imports)
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'md', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar'}
    
    # Application
    APP_NAME = os.environ.get('APP_NAME', 'Prismateams')
    APP_LOGO = os.environ.get('APP_LOGO', 'static/img/logo.png')
    
    # Timezone
    TIMEZONE = os.environ.get('TIMEZONE', 'Europe/Berlin')
    
    # File Versioning
    MAX_FILE_VERSIONS = 3
    
    # VAPID Keys for Push Notifications (base64url format)
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    
    # Email HTML Storage Configuration
    EMAIL_HTML_MAX_LENGTH = int(os.environ.get('EMAIL_HTML_MAX_LENGTH', 0))  # 0 = unlimited
    EMAIL_TEXT_MAX_LENGTH = int(os.environ.get('EMAIL_TEXT_MAX_LENGTH', 10000))  # 10KB for text
    EMAIL_HTML_STORAGE_TYPE = os.environ.get('EMAIL_HTML_STORAGE_TYPE', 'TEXT')  # TEXT, MEDIUMTEXT, LONGTEXT
    
    # ONLYOFFICE Configuration
    ONLYOFFICE_ENABLED = os.environ.get('ONLYOFFICE_ENABLED', 'False').lower() == 'true'
    ONLYOFFICE_DOCUMENT_SERVER_URL = os.environ.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    ONLYOFFICE_SECRET_KEY = os.environ.get('ONLYOFFICE_SECRET_KEY', '')
    # Public URL for Flask app (required when OnlyOffice runs on different server)
    # OnlyOffice needs to access document_url and callback_url from its server
    # Example: http://192.168.188.115:5000 or https://yourdomain.com
    ONLYOFFICE_PUBLIC_URL = os.environ.get('ONLYOFFICE_PUBLIC_URL', '')
    
    # Excalidraw Configuration
    EXCALIDRAW_ENABLED = os.environ.get('EXCALIDRAW_ENABLED', 'False').lower() == 'true'
    EXCALIDRAW_URL = os.environ.get('EXCALIDRAW_URL', '/excalidraw')
    EXCALIDRAW_ROOM_URL = os.environ.get('EXCALIDRAW_ROOM_URL', '/excalidraw-room')
    # Public URL for Flask app (required when Excalidraw runs on different server)
    # Excalidraw needs to access document_url and callback_url from its server
    # Example: http://192.168.188.115:5000 or https://yourdomain.com
    EXCALIDRAW_PUBLIC_URL = os.environ.get('EXCALIDRAW_PUBLIC_URL', '')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = False  # HTTP für Netzwerkzugriff


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///test.db'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_formatted_sender():
    """Gibt den formatierten Absender zurück: 'Name <email@example.com>' oder nur 'email@example.com'."""
    sender_name = os.environ.get('MAIL_SENDER_NAME', '').strip()
    sender_email = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME')
    
    if not sender_email:
        return None
    
    if sender_name:
        return f"{sender_name} <{sender_email}>"
    else:
        return sender_email



