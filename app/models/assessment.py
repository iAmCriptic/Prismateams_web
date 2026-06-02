import json
import re
from datetime import datetime

from argon2 import PasswordHasher
from flask_login import UserMixin

from app import db


password_hasher = PasswordHasher()


def _slugify(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "liste"


class AssessmentUser(UserMixin, db.Model):
    __tablename__ = "ass_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    theme_mode = db.Column(db.String(16), default="light", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    roles = db.relationship(
        "AssessmentRole",
        secondary="ass_user_roles",
        back_populates="users",
        lazy="joined",
    )

    def set_password(self, password):
        self.password_hash = password_hasher.hash(password)

    def check_password(self, password):
        try:
            password_hasher.verify(self.password_hash, password)
            if password_hasher.check_needs_rehash(self.password_hash):
                self.password_hash = password_hasher.hash(password)
                db.session.commit()
            return True
        except Exception:
            return False

    @property
    def role_names(self):
        return [role.name for role in self.roles]

    def has_role(self, role_name):
        return role_name in self.role_names

    @property
    def full_name(self):
        return self.display_name

    @property
    def accent_color(self):
        return "#0d6efd"

    @property
    def accent_style(self):
        return "linear-gradient(45deg, #0d6efd, #0d6efd)"

    @property
    def dark_mode(self):
        return self.theme_mode in ("dark", "oled")

    @property
    def oled_mode(self):
        return self.theme_mode == "oled"

    @property
    def is_guest(self):
        return False

    @property
    def is_email_confirmed(self):
        return True

    @property
    def profile_picture(self):
        return None

    def get_id(self):
        return f"ass:{self.id}"

    def __repr__(self):
        return f"<AssessmentUser {self.username}>"


class AssessmentRole(db.Model):
    __tablename__ = "ass_roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    users = db.relationship(
        "AssessmentUser",
        secondary="ass_user_roles",
        back_populates="roles",
    )

    def __repr__(self):
        return f"<AssessmentRole {self.name}>"


class AssessmentUserRole(db.Model):
    __tablename__ = "ass_user_roles"

    user_id = db.Column(db.Integer, db.ForeignKey("ass_users.id", ondelete="CASCADE"), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("ass_roles.id", ondelete="CASCADE"), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AssessmentStandType(db.Model):
    __tablename__ = "ass_stand_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    color = db.Column(db.String(32), nullable=True)

    stands = db.relationship("AssessmentStand", back_populates="stand_type")

    def __repr__(self):
        return f"<AssessmentStandType {self.name}>"


class AssessmentList(db.Model):
    __tablename__ = "ass_lists"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    subject_mode = db.Column(db.String(16), nullable=False, default="stand")
    stand_type_ids = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    enable_visitor_rating = db.Column(db.Boolean, default=False, nullable=False)
    ranking_mode = db.Column(db.String(32), default="standard", nullable=False)
    ranking_sort = db.Column(db.String(32), default="total", nullable=False)
    welcome_label = db.Column(db.String(120), nullable=True)

    criteria = db.relationship("AssessmentCriterion", back_populates="evaluation_list", cascade="all, delete-orphan")
    subjects = db.relationship("AssessmentListSubject", back_populates="evaluation_list", cascade="all, delete-orphan")

    def get_stand_type_id_list(self):
        if not self.stand_type_ids:
            return []
        try:
            parsed = json.loads(self.stand_type_ids)
            return [int(x) for x in parsed if str(x).isdigit() or isinstance(x, int)]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def set_stand_type_id_list(self, ids):
        if not ids:
            self.stand_type_ids = None
        else:
            self.stand_type_ids = json.dumps([int(i) for i in ids])

    @staticmethod
    def make_slug(name, exclude_id=None):
        base = _slugify(name)
        slug = base
        counter = 2
        while True:
            query = AssessmentList.query.filter_by(slug=slug)
            if exclude_id:
                query = query.filter(AssessmentList.id != exclude_id)
            if not query.first():
                return slug
            slug = f"{base}-{counter}"
            counter += 1

    def __repr__(self):
        return f"<AssessmentList {self.name}>"


class AssessmentListSubject(db.Model):
    __tablename__ = "ass_list_subjects"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("ass_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    evaluation_list = db.relationship("AssessmentList", back_populates="subjects")
    evaluations = db.relationship("AssessmentEvaluation", back_populates="subject", cascade="all, delete-orphan")
    visitor_evaluations = db.relationship(
        "AssessmentVisitorEvaluation", back_populates="subject", cascade="all, delete-orphan"
    )
    warnings = db.relationship("AssessmentWarning", back_populates="subject", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("list_id", "name", name="uq_ass_list_subject_name"),)

    def __repr__(self):
        return f"<AssessmentListSubject {self.name}>"


class AssessmentRoom(db.Model):
    __tablename__ = "ass_rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

    stands = db.relationship("AssessmentStand", back_populates="room", cascade="all, delete-orphan")
    inspections = db.relationship("AssessmentRoomInspection", back_populates="room", cascade="all, delete-orphan")


class AssessmentStand(db.Model):
    __tablename__ = "ass_stands"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey("ass_rooms.id", ondelete="SET NULL"), nullable=True)
    stand_type_id = db.Column(db.Integer, db.ForeignKey("ass_stand_types.id", ondelete="SET NULL"), nullable=True)

    room = db.relationship("AssessmentRoom", back_populates="stands")
    stand_type = db.relationship("AssessmentStandType", back_populates="stands")
    evaluations = db.relationship("AssessmentEvaluation", back_populates="stand", cascade="all, delete-orphan")
    visitor_evaluations = db.relationship(
        "AssessmentVisitorEvaluation", back_populates="stand", cascade="all, delete-orphan"
    )
    warnings = db.relationship("AssessmentWarning", back_populates="stand", cascade="all, delete-orphan")


class AssessmentCriterion(db.Model):
    __tablename__ = "ass_criteria"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("ass_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    max_score = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)

    evaluation_list = db.relationship("AssessmentList", back_populates="criteria")
    scores = db.relationship("AssessmentEvaluationScore", back_populates="criterion", cascade="all, delete-orphan")
    visitor_scores = db.relationship(
        "AssessmentVisitorEvaluationScore", back_populates="criterion", cascade="all, delete-orphan"
    )

    __table_args__ = (db.UniqueConstraint("list_id", "name", name="uq_ass_criterion_list_name"),)


class AssessmentEvaluation(db.Model):
    __tablename__ = "ass_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("ass_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    user_type = db.Column(db.String(16), nullable=False, default="ass")
    user_id = db.Column(db.Integer, nullable=False, index=True)
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("ass_list_subjects.id", ondelete="CASCADE"), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    evaluation_list = db.relationship("AssessmentList")
    stand = db.relationship("AssessmentStand", back_populates="evaluations")
    subject = db.relationship("AssessmentListSubject", back_populates="evaluations")
    scores = db.relationship("AssessmentEvaluationScore", back_populates="evaluation", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("user_type", "user_id", "list_id", "stand_id", name="uq_ass_eval_user_list_stand"),
        db.UniqueConstraint("user_type", "user_id", "list_id", "subject_id", name="uq_ass_eval_user_list_subject"),
    )


class AssessmentEvaluationScore(db.Model):
    __tablename__ = "ass_evaluation_scores"

    evaluation_id = db.Column(
        db.Integer, db.ForeignKey("ass_evaluations.id", ondelete="CASCADE"), primary_key=True
    )
    criterion_id = db.Column(db.Integer, db.ForeignKey("ass_criteria.id", ondelete="CASCADE"), primary_key=True)
    score = db.Column(db.Integer, nullable=False)

    evaluation = db.relationship("AssessmentEvaluation", back_populates="scores")
    criterion = db.relationship("AssessmentCriterion", back_populates="scores")


class AssessmentVisitorEvaluation(db.Model):
    __tablename__ = "ass_visitor_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("ass_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("ass_list_subjects.id", ondelete="CASCADE"), nullable=True)
    visitor_token_hash = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ip_hash = db.Column(db.String(255), nullable=True)
    ua_hash = db.Column(db.String(255), nullable=True)

    stand = db.relationship("AssessmentStand", back_populates="visitor_evaluations")
    subject = db.relationship("AssessmentListSubject", back_populates="visitor_evaluations")
    scores = db.relationship(
        "AssessmentVisitorEvaluationScore", back_populates="visitor_evaluation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("list_id", "stand_id", "visitor_token_hash", name="uq_ass_visitor_list_stand"),
        db.UniqueConstraint("list_id", "subject_id", "visitor_token_hash", name="uq_ass_visitor_list_subject"),
    )


class AssessmentVisitorEvaluationScore(db.Model):
    __tablename__ = "ass_visitor_evaluation_scores"

    visitor_evaluation_id = db.Column(
        db.Integer, db.ForeignKey("ass_visitor_evaluations.id", ondelete="CASCADE"), primary_key=True
    )
    criterion_id = db.Column(db.Integer, db.ForeignKey("ass_criteria.id", ondelete="CASCADE"), primary_key=True)
    score = db.Column(db.Integer, nullable=False)

    visitor_evaluation = db.relationship("AssessmentVisitorEvaluation", back_populates="scores")
    criterion = db.relationship("AssessmentCriterion", back_populates="visitor_scores")


class AssessmentWarning(db.Model):
    __tablename__ = "ass_warnings"

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("ass_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("ass_list_subjects.id", ondelete="CASCADE"), nullable=True)
    user_type = db.Column(db.String(16), nullable=False, default="ass")
    user_id = db.Column(db.Integer, nullable=False, index=True)
    comment = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_invalidated = db.Column(db.Boolean, default=False, nullable=False)
    invalidated_by_user_id = db.Column(db.Integer, nullable=True)
    invalidation_comment = db.Column(db.Text, nullable=True)
    invalidation_timestamp = db.Column(db.DateTime, nullable=True)

    stand = db.relationship("AssessmentStand", back_populates="warnings")
    subject = db.relationship("AssessmentListSubject", back_populates="warnings")


class AssessmentRoomInspection(db.Model):
    __tablename__ = "ass_room_inspections"

    room_id = db.Column(db.Integer, db.ForeignKey("ass_rooms.id", ondelete="CASCADE"), primary_key=True)
    inspector_user_type = db.Column(db.String(16), nullable=False, default="ass")
    inspector_user_id = db.Column(db.Integer, nullable=False, index=True)
    inspection_timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_clean = db.Column(db.Boolean, nullable=False, default=False)
    comment = db.Column(db.Text, nullable=True)

    room = db.relationship("AssessmentRoom", back_populates="inspections")


class AssessmentAppSetting(db.Model):
    __tablename__ = "ass_app_settings"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(120), unique=True, nullable=False)
    setting_value = db.Column(db.Text, nullable=True)
