"""Fast approximate size estimation for backup categories."""

from __future__ import annotations

import os
from typing import Callable, Dict, Iterable, Optional, Sequence

from sqlalchemy import func

from app import db
from app.models import (
    AssessmentAppSetting,
    AssessmentCriterion,
    AssessmentEvaluation,
    AssessmentEvaluationScore,
    AssessmentList,
    AssessmentListSubject,
    AssessmentRole,
    AssessmentRoom,
    AssessmentRoomInspection,
    AssessmentStand,
    AssessmentStandType,
    AssessmentUser,
    AssessmentUserRole,
    AssessmentVisitorEvaluation,
    AssessmentVisitorEvaluationScore,
    AssessmentWarning,
    BorrowTransaction,
    Calendar,
    CalendarEvent,
    CalendarSyncSource,
    Chat,
    ChatMember,
    ChatMessage,
    ChatPin,
    Comment,
    CommentMention,
    Contact,
    Credential,
    EmailAttachment,
    EmailMessage,
    EmailPermission,
    Event,
    EventAppointment,
    EventAssignment,
    EventContact,
    EventInventoryNeed,
    EventTimelineItem,
    EventParticipant,
    ExcalidrawDrawing,
    ExcalidrawDrawingVersion,
    File,
    FileVersion,
    Folder,
    FolderFavorite,
    Inventory,
    InventoryItem,
    Manual,
    MediaDownloadJob,
    MusicProviderToken,
    MusicQueue,
    MusicSettings,
    MusicWish,
    NotificationSettings,
    Product,
    ProductDocument,
    ProductFavorite,
    ProductFolder,
    ProductSet,
    ProductSetItem,
    PublicCalendarFeed,
    ResourceACL,
    SavedFilter,
    ShortLink,
    SystemSettings,
    User,
    WhitelistEntry,
    WikiCategory,
    WikiPage,
    WikiPageVersion,
    WikiTag,
)
from app.models.booking import (
    BookingForm,
    BookingFormField,
    BookingFormImage,
    BookingFormRole,
    BookingFormRoleUser,
    BookingRequest,
    BookingRequestApproval,
    BookingRequestField,
    BookingRequestFile,
)
from app.models.booking_personal import (
    BookingPersonalEntry,
    BookingPersonalEvent,
    BookingPersonalField,
    BookingPersonalFile,
    BookingPersonalTemplate,
)
from app.models.duty_roster import (
    DutyExternalPerson,
    DutyPersonConfig,
    DutyRoster,
    DutyRosterColumn,
    DutyRosterDay,
    DutyRosterEntry,
    DutyRosterPlanner,
    DutyTimeEntry,
)
from app.models.kanban import (
    KanbanActivity,
    KanbanActivityRead,
    KanbanAttachment,
    KanbanBoard,
    KanbanBoardMember,
    KanbanBoardTemplate,
    KanbanBoardView,
    KanbanCard,
    KanbanCardAssignee,
    KanbanCardFieldEnabled,
    KanbanCardFieldValue,
    KanbanCardLabel,
    KanbanCardVote,
    KanbanChecklist,
    KanbanChecklistItem,
    KanbanCustomField,
    KanbanCustomFieldCategory,
    KanbanLabel,
    KanbanList,
)
from app.models.canvas import CanvasDocument
from app.models.helpers import (
    Helper,
    HelperArea,
    HelperAreaWish,
    HelperEvent,
    HelperFieldConfig,
    HelperShift,
    HelperVoucherRule,
)
from app.models.meetings import Meeting, MeetingInvite
from app.models.protocol import Protocol, ProtocolAgendaItem
from app.models.public_share import PublicShare
from app.models.role import UserModuleRole
from app.models.survey import (
    Survey,
    SurveyAnswer,
    SurveyLogicRule,
    SurveyPage,
    SurveyQuestion,
    SurveyResponse,
)
from app.models.team import Team, TeamInviteCode, TeamMember, TeamModuleSetting
from app.models.todo import TodoItem
from app.utils.backup.constants import CATEGORY_DEFINITIONS
from app.utils.backup.file_io import resolve_existing_file, upload_root


def _b64_bytes(raw_bytes: int) -> int:
    """Return the approximate JSON byte length of base64-encoded binary data."""
    if raw_bytes <= 0:
        return 0
    return (int(raw_bytes) * 4 + 2) // 3


def _table_bytes(model, text_cols: Sequence = (), row_overhead: int = 320) -> int:
    """Estimate JSON bytes for all rows of ``model`` via a single SQL aggregate."""
    try:
        cols = [func.count(model.id)]
        for col in text_cols:
            cols.append(func.coalesce(func.sum(func.length(col)), 0))
        row = db.session.query(*cols).one()
        count = int(row[0] or 0)
        text_total = sum(int(v or 0) for v in row[1:])
        return count * row_overhead + text_total
    except Exception:
        return 0


def _tables_bytes(specs: Iterable[tuple]) -> int:
    """Sum ``_table_bytes`` for multiple ``(model, text_cols, row_overhead)`` specs."""
    total = 0
    for spec in specs:
        model = spec[0]
        text_cols = spec[1] if len(spec) > 1 else ()
        row_overhead = spec[2] if len(spec) > 2 else 320
        total += _table_bytes(model, text_cols=text_cols, row_overhead=row_overhead)
    return total


def _sum_size_col(model, size_col) -> int:
    """Return ``SUM(size_col)`` for ``model`` without loading ORM rows."""
    try:
        val = db.session.query(func.coalesce(func.sum(size_col), 0)).scalar()
        return int(val or 0)
    except Exception:
        return 0


def _sum_file_paths(
    model,
    path_col,
    candidates_fn: Optional[Callable[[str], Iterable[Optional[str]]]] = None,
) -> int:
    """Stat non-null file paths for ``model`` without reading file contents."""
    try:
        rows = db.session.query(path_col).filter(path_col.isnot(None)).all()
    except Exception:
        return 0

    total = 0
    for (raw_path,) in rows:
        if not raw_path:
            continue
        candidates = candidates_fn(raw_path) if candidates_fn else (raw_path,)
        resolved = resolve_existing_file(candidates)
        if resolved:
            try:
                total += os.path.getsize(resolved)
            except OSError:
                pass
    return total


def _estimate_settings() -> int:
    total = _tables_bytes([
        (SystemSettings, (), 900),
        (WhitelistEntry, (), 180),
    ])
    total += _b64_bytes(_sum_file_paths(SystemSettings, SystemSettings.logo_path))
    return total


def _estimate_users() -> int:
    total = _tables_bytes([
        (User, (), 550),
        (NotificationSettings, (), 300),
        (UserModuleRole, (), 180),
    ])
    total += _b64_bytes(
        _sum_file_paths(
            User,
            User.profile_picture,
            lambda p: (
                p,
                os.path.join(upload_root(), "avatars", p),
                os.path.join(upload_root(), "profile_pictures", p),
                os.path.join(upload_root(), p),
            ),
        )
    )
    return total


def _estimate_emails() -> int:
    total = _tables_bytes([
        (EmailMessage, (EmailMessage.subject, EmailMessage.body_text, EmailMessage.body_html), 500),
        (EmailPermission, (), 180),
        (EmailAttachment, (), 220),
    ])
    total += _b64_bytes(_sum_size_col(EmailAttachment, EmailAttachment.size))
    return total


def _estimate_appointments() -> int:
    return _tables_bytes([
        (Calendar, (Calendar.description,), 320),
        (CalendarSyncSource, (), 350),
        (PublicCalendarFeed, (), 280),
        (CalendarEvent, (CalendarEvent.description,), 420),
        (EventParticipant, (), 200),
    ])


def _estimate_credentials() -> int:
    return _tables_bytes([
        (Credential, (Credential.notes,), 420),
    ])


def _estimate_files() -> int:
    total = _tables_bytes([
        (Folder, (), 260),
        (File, (), 380),
        (FileVersion, (), 240),
        (PublicShare, (), 240),
        (ResourceACL, (), 200),
        (FolderFavorite, (), 150),
    ])
    total += _b64_bytes(
        _sum_size_col(File, File.file_size) + _sum_size_col(FileVersion, FileVersion.file_size)
    )
    return total


def _estimate_wiki() -> int:
    return _tables_bytes([
        (WikiCategory, (WikiCategory.description,), 260),
        (WikiTag, (), 140),
        (WikiPage, (WikiPage.content,), 450),
        (WikiPageVersion, (WikiPageVersion.content,), 320),
    ])


def _estimate_comments() -> int:
    return _tables_bytes([
        (Comment, (Comment.content,), 300),
        (CommentMention, (), 160),
    ])


def _estimate_inventory() -> int:
    total = _tables_bytes([
        (ProductFolder, (ProductFolder.description,), 260),
        (Product, (Product.description, Product.notes), 500),
        (BorrowTransaction, (BorrowTransaction.notes,), 320),
        (ProductSet, (ProductSet.description,), 280),
        (ProductSetItem, (), 160),
        (ProductDocument, (), 240),
        (SavedFilter, (), 300),
        (ProductFavorite, (), 140),
        (Inventory, (Inventory.description,), 280),
        (InventoryItem, (InventoryItem.notes,), 240),
    ])
    total += _b64_bytes(
        _sum_size_col(ProductDocument, ProductDocument.file_size)
        + _sum_file_paths(Product, Product.image_path)
    )
    return total


def _estimate_manuals() -> int:
    total = _tables_bytes([(Manual, (), 320)])
    total += _b64_bytes(_sum_size_col(Manual, Manual.file_size))
    return total


def _estimate_chats() -> int:
    total = _tables_bytes([
        (Chat, (Chat.description,), 300),
        (ChatMember, (), 180),
        (ChatMessage, (ChatMessage.content,), 280),
        (ChatPin, (), 180),
    ])
    chat_media_bytes = _sum_file_paths(
        ChatMessage,
        ChatMessage.media_url,
        lambda p: (
            os.path.join(upload_root(), "chat", p),
            os.path.join(upload_root(), "chat_media", p),
            p,
        ),
    )
    chat_avatar_bytes = _sum_file_paths(
        Chat,
        Chat.group_avatar,
        lambda p: (
            os.path.join(upload_root(), "chat", "avatars", p),
            os.path.join(upload_root(), "chat_avatars", p),
        ),
    )
    total += _b64_bytes(chat_media_bytes + chat_avatar_bytes)
    return total


def _estimate_contacts() -> int:
    return _tables_bytes([(Contact, (Contact.notes,), 380)])


def _estimate_events() -> int:
    return _tables_bytes([
        (Event, (Event.description,), 420),
        (EventAppointment, (), 240),
        (EventAssignment, (), 220),
        (EventInventoryNeed, (), 200),
        (EventContact, (), 200),
        (EventTimelineItem, (EventTimelineItem.description,), 260),
    ])


def _estimate_booking() -> int:
    total = _tables_bytes([
        (BookingForm, (BookingForm.description,), 400),
        (BookingFormField, (), 260),
        (BookingFormImage, (), 220),
        (BookingFormRole, (), 180),
        (BookingFormRoleUser, (), 160),
        (BookingRequest, (BookingRequest.notes,), 380),
        (BookingRequestField, (BookingRequestField.value,), 200),
        (BookingRequestApproval, (BookingRequestApproval.comment,), 240),
        (BookingRequestFile, (), 240),
    ])
    total += _b64_bytes(
        _sum_file_paths(BookingFormImage, BookingFormImage.image_path)
        + _sum_file_paths(BookingRequestFile, BookingRequestFile.file_path)
    )
    return total


def _estimate_music() -> int:
    return _tables_bytes([
        (MusicSettings, (), 300),
        (MusicProviderToken, (), 350),
        (MusicWish, (), 280),
        (MusicQueue, (), 280),
    ])


def _estimate_media_downloader() -> int:
    return _tables_bytes([(MediaDownloadJob, (), 350)])


def _estimate_assessment() -> int:
    return _tables_bytes([
        (AssessmentAppSetting, (), 200),
        (AssessmentUser, (), 260),
        (AssessmentRole, (), 200),
        (AssessmentUserRole, (), 160),
        (AssessmentStandType, (), 220),
        (AssessmentList, (), 260),
        (AssessmentListSubject, (), 200),
        (AssessmentRoom, (), 220),
        (AssessmentStand, (), 240),
        (AssessmentCriterion, (), 260),
        (AssessmentEvaluation, (), 280),
        (AssessmentEvaluationScore, (), 180),
        (AssessmentVisitorEvaluation, (), 260),
        (AssessmentVisitorEvaluationScore, (), 180),
        (AssessmentWarning, (), 240),
        (AssessmentRoomInspection, (), 240),
    ])


def _estimate_shortlinks() -> int:
    return _tables_bytes([(ShortLink, (), 260)])


def _estimate_excalidraw() -> int:
    return _tables_bytes([
        (ExcalidrawDrawing, (ExcalidrawDrawing.scene_data,), 450),
        (ExcalidrawDrawingVersion, (ExcalidrawDrawingVersion.scene_data,), 380),
    ])


def _estimate_teams() -> int:
    total = _tables_bytes([
        (Team, (Team.description,), 320),
        (TeamMember, (), 180),
        (TeamModuleSetting, (), 200),
        (TeamInviteCode, (), 220),
    ])
    total += _b64_bytes(
        _sum_file_paths(
            Team,
            Team.avatar_path,
            lambda p: (
                os.path.join(upload_root(), "teams", p),
                p,
            ),
        )
    )
    return total


def _estimate_kanban() -> int:
    total = _tables_bytes([
        (KanbanBoard, (KanbanBoard.description,), 360),
        (KanbanBoardMember, (), 180),
        (KanbanBoardView, (), 220),
        (KanbanList, (), 220),
        (KanbanLabel, (), 180),
        (KanbanCard, (KanbanCard.description,), 420),
        (KanbanCardAssignee, (), 160),
        (KanbanCardLabel, (), 160),
        (KanbanCardVote, (), 150),
        (KanbanChecklist, (), 200),
        (KanbanChecklistItem, (), 200),
        (KanbanCustomFieldCategory, (), 200),
        (KanbanCustomField, (), 240),
        (KanbanCardFieldEnabled, (), 160),
        (KanbanCardFieldValue, (KanbanCardFieldValue.value,), 200),
        (KanbanAttachment, (), 260),
        (KanbanBoardTemplate, (), 380),
        (KanbanActivity, (), 240),
        (KanbanActivityRead, (), 160),
    ])
    cover_bytes = _sum_file_paths(
        KanbanBoard,
        KanbanBoard.cover_path,
        lambda p: (
            os.path.join(upload_root(), "kanban", "boards", p),
            os.path.join(upload_root(), "kanban", p),
            p,
        ),
    )
    att_bytes = _sum_size_col(KanbanAttachment, KanbanAttachment.file_size)
    total += _b64_bytes(cover_bytes + att_bytes)
    return total


def _estimate_surveys() -> int:
    return _tables_bytes([
        (Survey, (Survey.description,), 360),
        (SurveyPage, (SurveyPage.description,), 260),
        (SurveyQuestion, (SurveyQuestion.options_json,), 320),
        (SurveyLogicRule, (), 240),
        (SurveyResponse, (), 280),
        (SurveyAnswer, (SurveyAnswer.answer_text,), 220),
    ])


def _estimate_protocols() -> int:
    return _tables_bytes([
        (Protocol, (Protocol.content,), 450),
        (ProtocolAgendaItem, (ProtocolAgendaItem.notes,), 280),
    ])


def _estimate_meetings() -> int:
    return _tables_bytes([
        (Meeting, (Meeting.description,), 340),
        (MeetingInvite, (), 200),
    ])


def _estimate_duty_roster() -> int:
    return _tables_bytes([
        (DutyRoster, (DutyRoster.description,), 320),
        (DutyRosterColumn, (), 200),
        (DutyRosterDay, (), 200),
        (DutyRosterEntry, (DutyRosterEntry.notes,), 240),
        (DutyRosterPlanner, (), 180),
        (DutyPersonConfig, (), 220),
        (DutyExternalPerson, (), 220),
        (DutyTimeEntry, (DutyTimeEntry.notes,), 240),
    ])


def _estimate_booking_personal() -> int:
    total = _tables_bytes([
        (BookingPersonalEvent, (BookingPersonalEvent.description,), 360),
        (BookingPersonalField, (), 240),
        (BookingPersonalEntry, (), 300),
        (BookingPersonalFile, (), 240),
        (BookingPersonalTemplate, (), 320),
    ])
    total += _b64_bytes(_sum_size_col(BookingPersonalFile, BookingPersonalFile.file_size))
    return total


def _estimate_canvas() -> int:
    total = _tables_bytes([
        (CanvasDocument, (), 320),
    ])
    canvas_dir = os.path.join(upload_root(), "canvas")
    file_bytes = _sum_file_paths(
        CanvasDocument,
        CanvasDocument.file_path,
        lambda p: (p, os.path.join(canvas_dir, os.path.basename(p))),
    )
    thumb_bytes = _sum_file_paths(
        CanvasDocument,
        CanvasDocument.thumbnail_path,
        lambda p: (p, os.path.join(canvas_dir, os.path.basename(p))),
    )
    total += _b64_bytes(file_bytes + thumb_bytes)
    return total


def _estimate_todos() -> int:
    return _tables_bytes([
        (TodoItem, (TodoItem.title,), 220),
    ])


def _estimate_helpers() -> int:
    return _tables_bytes([
        (HelperEvent, (HelperEvent.description, HelperEvent.mail_template_body), 420),
        (HelperArea, (HelperArea.description,), 240),
        (Helper, (Helper.allergies,), 320),
        (HelperAreaWish, (HelperAreaWish.notes,), 200),
        (HelperShift, (HelperShift.notes,), 240),
        (HelperFieldConfig, (), 220),
        (HelperVoucherRule, (), 200),
    ])


_ESTIMATORS: Dict[str, Callable[[], int]] = {
    "settings": _estimate_settings,
    "users": _estimate_users,
    "emails": _estimate_emails,
    "appointments": _estimate_appointments,
    "credentials": _estimate_credentials,
    "files": _estimate_files,
    "wiki": _estimate_wiki,
    "comments": _estimate_comments,
    "inventory": _estimate_inventory,
    "manuals": _estimate_manuals,
    "chats": _estimate_chats,
    "contacts": _estimate_contacts,
    "events": _estimate_events,
    "booking": _estimate_booking,
    "music": _estimate_music,
    "media_downloader": _estimate_media_downloader,
    "assessment": _estimate_assessment,
    "shortlinks": _estimate_shortlinks,
    "excalidraw": _estimate_excalidraw,
    "teams": _estimate_teams,
    "kanban": _estimate_kanban,
    "surveys": _estimate_surveys,
    "protocols": _estimate_protocols,
    "meetings": _estimate_meetings,
    "duty_roster": _estimate_duty_roster,
    "booking_personal": _estimate_booking_personal,
    "canvas": _estimate_canvas,
    "todos": _estimate_todos,
    "helpers": _estimate_helpers,
}


def estimate_backup_sizes() -> Dict[str, int]:
    """Return estimated export size in bytes for every backup category."""
    sizes: Dict[str, int] = {}
    for cat in CATEGORY_DEFINITIONS:
        key = cat["key"]
        fn = _ESTIMATORS.get(key)
        try:
            sizes[key] = max(0, int(fn())) if fn else 0
        except Exception:
            sizes[key] = 0
    return sizes
