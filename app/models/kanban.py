"""Kanban board models (Trello-like boards, lists, cards)."""

from datetime import datetime

from app import db


class KanbanBoard(db.Model):
    __tablename__ = 'kanban_boards'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    cover_path = db.Column(db.String(500), nullable=True)
    background = db.Column(db.String(100), nullable=True)  # Phase 2: color/gradient key
    visibility = db.Column(db.String(20), nullable=False, default='private')  # private|team|public
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    archived_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    last_viewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team = db.relationship('Team', backref='kanban_boards')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_kanban_boards')
    members = db.relationship('KanbanBoardMember', back_populates='board', cascade='all, delete-orphan')
    lists = db.relationship(
        'KanbanList',
        back_populates='board',
        cascade='all, delete-orphan',
        order_by='KanbanList.position',
    )
    labels = db.relationship('KanbanLabel', back_populates='board', cascade='all, delete-orphan')
    custom_fields = db.relationship(
        'KanbanCustomField',
        primaryjoin='and_(KanbanBoard.id==KanbanCustomField.board_id, KanbanCustomField.card_id.is_(None))',
        back_populates='board',
        cascade='all, delete-orphan',
        order_by='KanbanCustomField.position',
        overlaps='local_fields,board',
    )
    custom_field_categories = db.relationship(
        'KanbanCustomFieldCategory',
        back_populates='board',
        cascade='all, delete-orphan',
        order_by='KanbanCustomFieldCategory.position',
    )
    activities = db.relationship(
        'KanbanActivity',
        back_populates='board',
        cascade='all, delete-orphan',
        order_by='KanbanActivity.created_at.desc()',
    )

    @property
    def is_archived(self):
        return self.archived_at is not None or self.closed_at is not None

    def __repr__(self):
        return f'<KanbanBoard {self.id} {self.title}>'


class KanbanBoardMember(db.Model):
    __tablename__ = 'kanban_board_members'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='member')  # owner|admin|member
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    board = db.relationship('KanbanBoard', back_populates='members')
    user = db.relationship('User', backref='kanban_board_memberships')

    __table_args__ = (
        db.UniqueConstraint('board_id', 'user_id', name='unique_kanban_board_member'),
    )


class KanbanList(db.Model):
    __tablename__ = 'kanban_lists'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    board = db.relationship('KanbanBoard', back_populates='lists')
    cards = db.relationship(
        'KanbanCard',
        back_populates='list',
        cascade='all, delete-orphan',
        order_by='KanbanCard.position',
    )

    @property
    def is_archived(self):
        return self.archived_at is not None


class KanbanCard(db.Model):
    __tablename__ = 'kanban_cards'

    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('kanban_lists.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    poll_text = db.Column(db.Text, nullable=True)  # Freitext-Abstimmung unter der Beschreibung
    due_date = db.Column(db.DateTime, nullable=True)
    cover_attachment_id = db.Column(db.Integer, nullable=True)  # logical FK to kanban_attachments.id
    position = db.Column(db.Integer, nullable=False, default=0)
    completed_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    list = db.relationship('KanbanList', back_populates='cards')
    creator = db.relationship('User', foreign_keys=[created_by])
    assignees = db.relationship('KanbanCardAssignee', back_populates='card', cascade='all, delete-orphan')
    card_labels = db.relationship('KanbanCardLabel', back_populates='card', cascade='all, delete-orphan')
    checklists = db.relationship(
        'KanbanChecklist',
        back_populates='card',
        cascade='all, delete-orphan',
        order_by='KanbanChecklist.position',
    )
    attachments = db.relationship(
        'KanbanAttachment',
        back_populates='card',
        cascade='all, delete-orphan',
        foreign_keys='KanbanAttachment.card_id',
        order_by='KanbanAttachment.created_at.desc()',
    )
    votes = db.relationship('KanbanCardVote', back_populates='card', cascade='all, delete-orphan')
    field_values = db.relationship(
        'KanbanCardFieldValue',
        back_populates='card',
        cascade='all, delete-orphan',
    )
    enabled_fields = db.relationship(
        'KanbanCardFieldEnabled',
        back_populates='card',
        cascade='all, delete-orphan',
    )
    local_fields = db.relationship(
        'KanbanCustomField',
        primaryjoin='KanbanCard.id==KanbanCustomField.card_id',
        back_populates='card',
        cascade='all, delete-orphan',
        overlaps='custom_fields,board',
    )

    @property
    def is_archived(self):
        return self.archived_at is not None

    @property
    def is_completed(self):
        return self.completed_at is not None

    @property
    def board(self):
        return self.list.board if self.list else None


class KanbanLabel(db.Model):
    __tablename__ = 'kanban_labels'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(20), nullable=False, default='#0d6efd')
    position = db.Column(db.Integer, nullable=False, default=0)

    board = db.relationship('KanbanBoard', back_populates='labels')
    card_labels = db.relationship('KanbanCardLabel', back_populates='label', cascade='all, delete-orphan')


class KanbanCardLabel(db.Model):
    __tablename__ = 'kanban_card_labels'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    label_id = db.Column(db.Integer, db.ForeignKey('kanban_labels.id', ondelete='CASCADE'), nullable=False)

    card = db.relationship('KanbanCard', back_populates='card_labels')
    label = db.relationship('KanbanLabel', back_populates='card_labels')

    __table_args__ = (
        db.UniqueConstraint('card_id', 'label_id', name='unique_kanban_card_label'),
    )


class KanbanCardAssignee(db.Model):
    __tablename__ = 'kanban_card_assignees'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    card = db.relationship('KanbanCard', back_populates='assignees')
    user = db.relationship('User', backref='kanban_card_assignments')

    __table_args__ = (
        db.UniqueConstraint('card_id', 'user_id', name='unique_kanban_card_assignee'),
    )


class KanbanChecklist(db.Model):
    __tablename__ = 'kanban_checklists'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False, default='Checkliste')
    position = db.Column(db.Integer, nullable=False, default=0)

    card = db.relationship('KanbanCard', back_populates='checklists')
    items = db.relationship(
        'KanbanChecklistItem',
        back_populates='checklist',
        cascade='all, delete-orphan',
        order_by='KanbanChecklistItem.position',
    )


class KanbanChecklistItem(db.Model):
    __tablename__ = 'kanban_checklist_items'

    id = db.Column(db.Integer, primary_key=True)
    checklist_id = db.Column(db.Integer, db.ForeignKey('kanban_checklists.id', ondelete='CASCADE'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    due_date = db.Column(db.DateTime, nullable=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    checklist = db.relationship('KanbanChecklist', back_populates='items')
    assignee = db.relationship('User', foreign_keys=[assignee_id])


class KanbanAttachment(db.Model):
    __tablename__ = 'kanban_attachments'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    filename = db.Column(db.String(255), nullable=True)
    original_filename = db.Column(db.String(255), nullable=True)
    mime_type = db.Column(db.String(120), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    storage_path = db.Column(db.String(500), nullable=True)
    url = db.Column(db.String(1000), nullable=True)  # external link attachment
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    card = db.relationship('KanbanCard', back_populates='attachments', foreign_keys=[card_id])
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    @property
    def is_link(self):
        return bool(self.url)


class KanbanCardVote(db.Model):
    """Phase 2: voting on cards."""
    __tablename__ = 'kanban_card_votes'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    card = db.relationship('KanbanCard', back_populates='votes')
    user = db.relationship('User', backref='kanban_card_votes')

    __table_args__ = (
        db.UniqueConstraint('card_id', 'user_id', name='unique_kanban_card_vote'),
    )


class KanbanActivity(db.Model):
    """Phase 2: activity feed entries."""
    __tablename__ = 'kanban_activities'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='SET NULL'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    board = db.relationship('KanbanBoard', back_populates='activities')
    card = db.relationship('KanbanCard', backref='activities')
    user = db.relationship('User', backref='kanban_activities')


class KanbanBoardTemplate(db.Model):
    """Phase 2: board templates (JSON snapshot of lists/labels)."""
    __tablename__ = 'kanban_board_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=False, default='{}')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_global = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship('User', backref='kanban_templates')


class KanbanBoardView(db.Model):
    """Track recently viewed boards per user."""
    __tablename__ = 'kanban_board_views'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    board = db.relationship('KanbanBoard', backref='views')
    user = db.relationship('User', backref='kanban_board_views')

    __table_args__ = (
        db.UniqueConstraint('board_id', 'user_id', name='unique_kanban_board_view'),
    )


class KanbanCustomFieldCategory(db.Model):
    """Board-level category/group for custom field templates."""
    __tablename__ = 'kanban_custom_field_categories'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    board = db.relationship('KanbanBoard', back_populates='custom_field_categories')
    fields = db.relationship(
        'KanbanCustomField',
        back_populates='category',
        foreign_keys='KanbanCustomField.category_id',
    )


class KanbanCustomField(db.Model):
    """Custom field definition: board template (card_id null) or card-local (card_id set)."""
    __tablename__ = 'kanban_custom_fields'

    id = db.Column(db.Integer, primary_key=True)
    board_id = db.Column(db.Integer, db.ForeignKey('kanban_boards.id', ondelete='CASCADE'), nullable=False)
    category_id = db.Column(
        db.Integer, db.ForeignKey('kanban_custom_field_categories.id', ondelete='SET NULL'), nullable=True
    )
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=True)
    field_type = db.Column(db.String(20), nullable=False, default='text')
    label = db.Column(db.String(200), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    options = db.Column(db.Text, nullable=True)  # JSON list for select
    placeholder = db.Column(db.String(255), nullable=True)

    board = db.relationship(
        'KanbanBoard',
        back_populates='custom_fields',
        foreign_keys=[board_id],
        overlaps='local_fields,board',
    )
    category = db.relationship('KanbanCustomFieldCategory', back_populates='fields')
    card = db.relationship(
        'KanbanCard',
        back_populates='local_fields',
        foreign_keys=[card_id],
        overlaps='custom_fields,board',
    )
    values = db.relationship(
        'KanbanCardFieldValue',
        back_populates='field',
        cascade='all, delete-orphan',
    )
    enabled_on_cards = db.relationship(
        'KanbanCardFieldEnabled',
        back_populates='field',
        cascade='all, delete-orphan',
    )


class KanbanCardFieldEnabled(db.Model):
    """Which board template fields are inserted/shown on a card."""
    __tablename__ = 'kanban_card_field_enabled'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey('kanban_custom_fields.id', ondelete='CASCADE'), nullable=False)

    card = db.relationship('KanbanCard', back_populates='enabled_fields')
    field = db.relationship('KanbanCustomField', back_populates='enabled_on_cards')

    __table_args__ = (
        db.UniqueConstraint('card_id', 'field_id', name='unique_kanban_card_field_enabled'),
    )


class KanbanCardFieldValue(db.Model):
    """Per-card value for a custom field."""
    __tablename__ = 'kanban_card_field_values'

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('kanban_cards.id', ondelete='CASCADE'), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey('kanban_custom_fields.id', ondelete='CASCADE'), nullable=False)
    value = db.Column(db.Text, nullable=True)

    card = db.relationship('KanbanCard', back_populates='field_values')
    field = db.relationship('KanbanCustomField', back_populates='values')

    __table_args__ = (
        db.UniqueConstraint('card_id', 'field_id', name='unique_kanban_card_field_value'),
    )
