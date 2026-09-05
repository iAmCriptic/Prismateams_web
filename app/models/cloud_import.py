from datetime import datetime

from app import db


class CloudImportConnection(db.Model):
    __tablename__ = 'cloud_import_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    provider = db.Column(db.String(32), nullable=False)  # nextcloud | google_drive
    display_name = db.Column(db.String(255), nullable=True)
    credentials_enc = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='cloud_import_connections')

    def __repr__(self):
        return f'<CloudImportConnection {self.id} {self.provider}>'


class CloudImportJob(db.Model):
    __tablename__ = 'cloud_import_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    connection_id = db.Column(
        db.Integer,
        db.ForeignKey('cloud_import_connections.id'),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    source_paths = db.Column(db.Text, nullable=False, default='[]')  # JSON list
    target_space = db.Column(db.String(20), nullable=False)  # public | team | personal
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True, index=True)
    target_folder_id = db.Column(db.Integer, db.ForeignKey('folders.id'), nullable=True)
    files_done = db.Column(db.Integer, nullable=False, default=0)
    files_total = db.Column(db.Integer, nullable=False, default=0)
    bytes_done = db.Column(db.BigInteger, nullable=False, default=0)
    files_skipped = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='cloud_import_jobs')
    connection = db.relationship('CloudImportConnection', backref='jobs')
    team = db.relationship('Team', backref='cloud_import_jobs')
    target_folder = db.relationship('Folder', backref='cloud_import_jobs')

    def __repr__(self):
        return f'<CloudImportJob {self.id} {self.status}>'
