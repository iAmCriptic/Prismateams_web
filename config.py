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
            'read_timeout': 30,
            'write_timeout': 30,
        }
    }
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    
    # IMAP
    IMAP_SERVER = os.environ.get('IMAP_SERVER')
    IMAP_PORT = int(os.environ.get('IMAP_PORT', 993))
    IMAP_USE_SSL = os.environ.get('IMAP_USE_SSL', 'True').lower() == 'true'
    
    # Uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 104857600))  # 100MB
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'ogg', 'mp3', 'wav', 'md', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'rar'}
    
    # Application
    APP_NAME = os.environ.get('APP_NAME', 'Team Portal')
    APP_LOGO = os.environ.get('APP_LOGO', 'static/img/logo.png')
    
    # Timezone
    TIMEZONE = os.environ.get('TIMEZONE', 'Europe/Berlin')
    
    # File Versioning
    MAX_FILE_VERSIONS = 3
    
    # VAPID Keys for Push Notifications
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    
    # Email HTML Storage Configuration
    EMAIL_HTML_MAX_LENGTH = int(os.environ.get('EMAIL_HTML_MAX_LENGTH', 0))  # 0 = unlimited
    EMAIL_TEXT_MAX_LENGTH = int(os.environ.get('EMAIL_TEXT_MAX_LENGTH', 10000))  # 10KB for text
    EMAIL_HTML_STORAGE_TYPE = os.environ.get('EMAIL_HTML_STORAGE_TYPE', 'TEXT')  # TEXT, MEDIUMTEXT, LONGTEXT


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


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



