from datetime import datetime
from app import db


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(7), nullable=True)
    leader_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = db.relationship('TeamMember', back_populates='team', cascade='all, delete-orphan')
    leader = db.relationship('User', foreign_keys=[leader_id], back_populates='led_teams')

    def __repr__(self):
        return f'<Team {self.name}>'

    @property
    def member_count(self):
        return len(self.members) if self.members is not None else 0


class TeamMember(db.Model):
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    team = db.relationship('Team', back_populates='members')
    user = db.relationship('User', back_populates='team_memberships')

    __table_args__ = (
        db.UniqueConstraint('team_id', 'user_id', name='unique_team_member'),
    )

    def __repr__(self):
        return f'<TeamMember team={self.team_id} user={self.user_id}>'
