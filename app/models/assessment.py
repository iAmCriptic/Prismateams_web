from datetime import datetime

from argon2 import PasswordHasher
from flask_login import UserMixin

from app import db


password_hasher = PasswordHasher()


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

    room = db.relationship("AssessmentRoom", back_populates="stands")
    evaluations = db.relationship("AssessmentEvaluation", back_populates="stand", cascade="all, delete-orphan")
    visitor_evaluations = db.relationship(
        "AssessmentVisitorEvaluation", back_populates="stand", cascade="all, delete-orphan"
    )
    warnings = db.relationship("AssessmentWarning", back_populates="stand", cascade="all, delete-orphan")


class AssessmentCriterion(db.Model):
    __tablename__ = "ass_criteria"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    max_score = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)

    scores = db.relationship("AssessmentEvaluationScore", back_populates="criterion", cascade="all, delete-orphan")
    visitor_scores = db.relationship(
        "AssessmentVisitorEvaluationScore", back_populates="criterion", cascade="all, delete-orphan"
    )


class AssessmentEvaluation(db.Model):
    __tablename__ = "ass_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(16), nullable=False, default="ass")
    user_id = db.Column(db.Integer, nullable=False, index=True)
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    stand = db.relationship("AssessmentStand", back_populates="evaluations")
    scores = db.relationship("AssessmentEvaluationScore", back_populates="evaluation", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("user_type", "user_id", "stand_id", name="uq_ass_eval_user_stand"),
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
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=False)
    visitor_token_hash = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ip_hash = db.Column(db.String(255), nullable=True)
    ua_hash = db.Column(db.String(255), nullable=True)

    stand = db.relationship("AssessmentStand", back_populates="visitor_evaluations")
    scores = db.relationship(
        "AssessmentVisitorEvaluationScore", back_populates="visitor_evaluation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("stand_id", "visitor_token_hash", name="uq_ass_visitor_stand"),
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
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="CASCADE"), nullable=False)
    user_type = db.Column(db.String(16), nullable=False, default="ass")
    user_id = db.Column(db.Integer, nullable=False, index=True)
    comment = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_invalidated = db.Column(db.Boolean, default=False, nullable=False)
    invalidated_by_user_id = db.Column(db.Integer, nullable=True)
    invalidation_comment = db.Column(db.Text, nullable=True)
    invalidation_timestamp = db.Column(db.DateTime, nullable=True)

    stand = db.relationship("AssessmentStand", back_populates="warnings")


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


class AssessmentFloorPlan(db.Model):
    __tablename__ = "ass_floor_plans"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    image_path = db.Column(db.String(512), nullable=False)
    width_px = db.Column(db.Float, nullable=True)
    height_px = db.Column(db.Float, nullable=True)
    scale_point1_x = db.Column(db.Float, nullable=True)
    scale_point1_y = db.Column(db.Float, nullable=True)
    scale_point2_x = db.Column(db.Float, nullable=True)
    scale_point2_y = db.Column(db.Float, nullable=True)
    scale_distance_meters = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    objects = db.relationship("AssessmentFloorPlanObject", back_populates="plan", cascade="all, delete-orphan")


class AssessmentFloorPlanObject(db.Model):
    __tablename__ = "ass_floor_plan_objects"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("ass_floor_plans.id", ondelete="CASCADE"), nullable=False)
    type = db.Column(db.String(40), nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=True)
    height = db.Column(db.Float, nullable=True)
    color = db.Column(db.String(32), nullable=True)
    trash_can_color = db.Column(db.String(32), nullable=True)
    wc_label = db.Column(db.String(32), nullable=True)
    power_outlet_label = db.Column(db.String(32), nullable=True)
    stand_id = db.Column(db.Integer, db.ForeignKey("ass_stands.id", ondelete="SET NULL"), nullable=True)
    custom_stand_name = db.Column(db.String(255), nullable=True)

    plan = db.relationship("AssessmentFloorPlan", back_populates="objects")
    stand = db.relationship("AssessmentStand")

