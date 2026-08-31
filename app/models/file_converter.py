from datetime import datetime

from app import db


class ConversionJob(db.Model):
    __tablename__ = 'conversion_jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    source_filename = db.Column(db.String(500), nullable=False)
    source_path = db.Column(db.String(1000), nullable=True)
    source_category = db.Column(db.String(20), nullable=False)
    source_format = db.Column(db.String(20), nullable=True)
    target_format = db.Column(db.String(20), nullable=False)
    options_json = db.Column(db.Text, nullable=True)
    output_filename = db.Column(db.String(500), nullable=True)
    output_path = db.Column(db.String(1000), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    user = db.relationship('User', backref='conversion_jobs')

    def is_downloadable(self):
        return (
            self.status == 'completed'
            and self.output_filename
            and self.expires_at
            and datetime.utcnow() < self.expires_at
        )

    def __repr__(self):
        return f'<ConversionJob {self.id} {self.status}>'
