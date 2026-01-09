import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration."""
    
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI') or 'sqlite:///teamportal.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,  # Prüft Verbindungen vor Verwendung, verhindert "Connection lost" Fehler
        'pool_timeout': 10,  # Reduziert von 20 auf 10 Sekunden für schnellere Fehlerbehandlung
        'pool_size': 15,  # Erhöht von 10 auf 15 für bessere Parallelität (Musiktool + Dashboard + E-Mail-Sync)
        'max_overflow': 25,  # Erhöht von 20 auf 25 für mehr gleichzeitige Verbindungen
        'connect_args': {
            'connect_timeout': 5,  # Reduziert von 10 auf 5 Sekunden für schnellere Timeouts
            'read_timeout': 30,  # Reduziert von 300 auf 30 Sekunden (ausreichend für normale Abfragen)
            'write_timeout': 30,  # Reduziert von 300 auf 30 Sekunden
        }
    }
    
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ.get('MAIL_USERNAME')
    MAIL_SENDER_NAME = os.environ.get('MAIL_SENDER_NAME', '')
    
    IMAP_SERVER = os.environ.get('IMAP_SERVER')
    IMAP_PORT = int(os.environ.get('IMAP_PORT', 993))
    IMAP_USE_SSL = os.environ.get('IMAP_USE_SSL', 'True').lower() == 'true'
    
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 524288000))
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'md', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar'}
    
    APP_NAME = os.environ.get('APP_NAME', 'Prismateams')
    APP_LOGO = os.environ.get('APP_LOGO', 'static/img/logo.png')
    
    TIMEZONE = os.environ.get('TIMEZONE', 'Europe/Berlin')
    
    MAX_FILE_VERSIONS = 3
    
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    
    EMAIL_HTML_MAX_LENGTH = int(os.environ.get('EMAIL_HTML_MAX_LENGTH', 0))
    EMAIL_TEXT_MAX_LENGTH = int(os.environ.get('EMAIL_TEXT_MAX_LENGTH', 10000))
    EMAIL_HTML_STORAGE_TYPE = os.environ.get('EMAIL_HTML_STORAGE_TYPE', 'TEXT')
    
    ONLYOFFICE_ENABLED = os.environ.get('ONLYOFFICE_ENABLED', 'False').lower() == 'true'
    ONLYOFFICE_DOCUMENT_SERVER_URL = os.environ.get('ONLYOFFICE_DOCUMENT_SERVER_URL', '/onlyoffice')
    ONLYOFFICE_SECRET_KEY = os.environ.get('ONLYOFFICE_SECRET_KEY', '')
    ONLYOFFICE_PUBLIC_URL = os.environ.get('ONLYOFFICE_PUBLIC_URL', '')
    
    EXCALIDRAW_ENABLED = os.environ.get('EXCALIDRAW_ENABLED', 'False').lower() == 'true'
    EXCALIDRAW_URL = os.environ.get('EXCALIDRAW_URL', '/excalidraw')
    EXCALIDRAW_ROOM_URL = os.environ.get('EXCALIDRAW_ROOM_URL', '/excalidraw-room')
    EXCALIDRAW_PUBLIC_URL = os.environ.get('EXCALIDRAW_PUBLIC_URL', '')

    # Redis für SocketIO Message Queue (optional, für Multi-Worker-Setups)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', 'False').lower() == 'true'


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = False


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



