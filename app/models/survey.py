from datetime import datetime
import json
import secrets

from app import db


SURVEY_QUESTION_TYPES = (
    'short_text',
    'long_text',
    'number',
    'slider',
    'single_choice',
    'multiple_choice',
    'rating_stars',
    'file_upload',
    'date',
    'time',
    'url',
    'email',
)

SURVEY_LOGIC_OPERATORS = (
    'equals',
    'not_equals',
    'contains',
    'greater_than',
    'less_than',
    'is_empty',
    'is_not_empty',
    'one_of',
)

SURVEY_LOGIC_ACTIONS = (
    'goto_page',
    'skip_page',
    'show_question',
    'hide_question',
)

DEFAULT_SURVEY_SETTINGS = {
    'require_email_verification': False,
    'one_response_per_email': False,
    'show_progress_bar': True,
    'shuffle_questions': False,
    'confirmation_message': 'Ihre Antwort wurde gespeichert.',
    'allow_edit_response': False,
    'show_submit_another_link': True,
    'disable_autosave': False,
}


class Survey(db.Model):
    __tablename__ = 'surveys'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False, default='Neue Umfrage')
    description = db.Column(db.Text, nullable=True)
    header_image_path = db.Column(db.String(500), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visibility = db.Column(db.String(20), nullable=False, default='private')
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_publicly_fillable = db.Column(db.Boolean, default=False, nullable=False)
    public_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    layout_mode = db.Column(db.String(20), nullable=False, default='scroll')
    settings_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', backref='created_surveys')
    team = db.relationship('Team', backref='surveys')
    pages = db.relationship(
        'SurveyPage',
        back_populates='survey',
        cascade='all, delete-orphan',
        order_by='SurveyPage.page_order',
    )
    logic_rules = db.relationship(
        'SurveyLogicRule',
        back_populates='survey',
        cascade='all, delete-orphan',
    )
    responses = db.relationship(
        'SurveyResponse',
        back_populates='survey',
        cascade='all, delete-orphan',
    )

    def get_settings(self):
        if not self.settings_json:
            return dict(DEFAULT_SURVEY_SETTINGS)
        try:
            data = json.loads(self.settings_json)
            merged = dict(DEFAULT_SURVEY_SETTINGS)
            merged.update(data)
            return merged
        except (TypeError, ValueError):
            return dict(DEFAULT_SURVEY_SETTINGS)

    def set_settings(self, data):
        merged = dict(DEFAULT_SURVEY_SETTINGS)
        if data:
            merged.update(data)
        self.settings_json = json.dumps(merged)

    def ensure_public_token(self):
        if not self.public_token:
            self.public_token = secrets.token_urlsafe(32)
        return self.public_token

    def all_questions(self):
        questions = []
        for page in self.pages:
            questions.extend(page.questions)
        return questions

    def __repr__(self):
        return f'<Survey {self.title}>'


class SurveyPage(db.Model):
    __tablename__ = 'survey_pages'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    page_order = db.Column(db.Integer, default=0, nullable=False)

    survey = db.relationship('Survey', back_populates='pages')
    questions = db.relationship(
        'SurveyQuestion',
        back_populates='page',
        cascade='all, delete-orphan',
        order_by='SurveyQuestion.question_order',
    )

    def __repr__(self):
        return f'<SurveyPage {self.id} survey={self.survey_id}>'


class SurveyQuestion(db.Model):
    __tablename__ = 'survey_questions'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('survey_pages.id', ondelete='CASCADE'), nullable=False, index=True)
    question_type = db.Column(db.String(30), nullable=False)
    label = db.Column(db.String(500), nullable=False, default='Neue Frage')
    description = db.Column(db.Text, nullable=True)
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    question_order = db.Column(db.Integer, default=0, nullable=False)
    config_json = db.Column(db.Text, nullable=True)

    page = db.relationship('SurveyPage', back_populates='questions')
    answers = db.relationship(
        'SurveyAnswer',
        back_populates='question',
        cascade='all, delete-orphan',
    )

    def get_config(self):
        if not self.config_json:
            return {}
        try:
            return json.loads(self.config_json)
        except (TypeError, ValueError):
            return {}

    def set_config(self, data):
        self.config_json = json.dumps(data or {})

    @property
    def survey_id(self):
        if self.page:
            return self.page.survey_id
        return None

    def __repr__(self):
        return f'<SurveyQuestion {self.label} ({self.question_type})>'


class SurveyLogicRule(db.Model):
    __tablename__ = 'survey_logic_rules'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False, index=True)
    source_question_id = db.Column(db.Integer, db.ForeignKey('survey_questions.id', ondelete='CASCADE'), nullable=False)
    operator = db.Column(db.String(30), nullable=False)
    value_json = db.Column(db.Text, nullable=True)
    action = db.Column(db.String(30), nullable=False)
    target_page_id = db.Column(db.Integer, db.ForeignKey('survey_pages.id', ondelete='SET NULL'), nullable=True)
    target_question_id = db.Column(db.Integer, db.ForeignKey('survey_questions.id', ondelete='SET NULL'), nullable=True)
    rule_order = db.Column(db.Integer, default=0, nullable=False)

    survey = db.relationship('Survey', back_populates='logic_rules')
    source_question = db.relationship('SurveyQuestion', foreign_keys=[source_question_id])
    target_page = db.relationship('SurveyPage', foreign_keys=[target_page_id])
    target_question = db.relationship('SurveyQuestion', foreign_keys=[target_question_id])

    def get_value(self):
        if not self.value_json:
            return None
        try:
            return json.loads(self.value_json)
        except (TypeError, ValueError):
            return self.value_json

    def set_value(self, value):
        if value is None:
            self.value_json = None
        else:
            self.value_json = json.dumps(value)

    def __repr__(self):
        return f'<SurveyLogicRule {self.id} action={self.action}>'


class SurveyResponse(db.Model):
    __tablename__ = 'survey_responses'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False, index=True)
    public_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    respondent_email = db.Column(db.String(255), nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='draft', nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_hash = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    survey = db.relationship('Survey', back_populates='responses')
    user = db.relationship('User', backref='survey_responses')
    answers = db.relationship(
        'SurveyAnswer',
        back_populates='response',
        cascade='all, delete-orphan',
    )

    def ensure_public_token(self):
        if not self.public_token:
            self.public_token = secrets.token_urlsafe(32)
        return self.public_token

    def __repr__(self):
        return f'<SurveyResponse {self.id} survey={self.survey_id} status={self.status}>'


class SurveyAnswer(db.Model):
    __tablename__ = 'survey_answers'

    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('survey_responses.id', ondelete='CASCADE'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_questions.id', ondelete='CASCADE'), nullable=False, index=True)
    value_text = db.Column(db.Text, nullable=True)
    value_json = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(500), nullable=True)

    response = db.relationship('SurveyResponse', back_populates='answers')
    question = db.relationship('SurveyQuestion', back_populates='answers')

    def get_value_json(self):
        if not self.value_json:
            return None
        try:
            return json.loads(self.value_json)
        except (TypeError, ValueError):
            return self.value_json

    def set_value_json(self, value):
        if value is None:
            self.value_json = None
        else:
            self.value_json = json.dumps(value)

    __table_args__ = (
        db.UniqueConstraint('response_id', 'question_id', name='uq_survey_answer_response_question'),
    )

    def __repr__(self):
        return f'<SurveyAnswer response={self.response_id} question={self.question_id}>'


class SurveyEmailVerification(db.Model):
    __tablename__ = 'survey_email_verifications'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    code = db.Column(db.String(10), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    survey = db.relationship('Survey', backref='email_verifications')

    __table_args__ = (
        db.Index('ix_survey_email_verification_survey_email', 'survey_id', 'email'),
    )

    def __repr__(self):
        return f'<SurveyEmailVerification survey={self.survey_id} email={self.email}>'


class SurveyResponseLock(db.Model):
    __tablename__ = 'survey_response_locks'

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('surveys.id', ondelete='CASCADE'), nullable=False, index=True)
    email_normalized = db.Column(db.String(255), nullable=False)
    response_id = db.Column(db.Integer, db.ForeignKey('survey_responses.id', ondelete='SET NULL'), nullable=True)
    locked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    survey = db.relationship('Survey', backref='response_locks')
    response = db.relationship('SurveyResponse', backref='lock_entry')

    __table_args__ = (
        db.UniqueConstraint('survey_id', 'email_normalized', name='uq_survey_response_lock_email'),
    )

    def __repr__(self):
        return f'<SurveyResponseLock survey={self.survey_id} email={self.email_normalized}>'
