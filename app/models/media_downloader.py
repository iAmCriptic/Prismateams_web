from datetime import datetime

from app import db


class MediaDownloadJob(db.Model):
    __tablename__ = 'media_download_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    source_url = db.Column(db.String(2048), nullable=False)
    format = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.String(20), nullable=True)
    end_time = db.Column(db.String(20), nullable=True)
    title = db.Column(db.String(500), nullable=True)
    filename = db.Column(db.String(500), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    user = db.relationship('User', backref='media_download_jobs')

    def is_downloadable(self):
        return (
            self.status == 'completed'
            and self.filename
            and self.expires_at
            and datetime.utcnow() < self.expires_at
        )

    def __repr__(self):
        return f'<MediaDownloadJob {self.id} {self.status}>'
