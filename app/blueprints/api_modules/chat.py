import os
from datetime import datetime
import json

from flask import current_app, jsonify, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app import db
from app.models.calendar import CalendarEvent, EventParticipant
from app.models.chat import Chat, ChatMember, ChatMessage
from app.models.file import Folder
from app.models.user import User
from app.utils.access_control import has_module_access, get_guest_accessible_items
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.i18n import translate
from app.utils.notifications import enqueue_chat_notification
from app.utils.chat_visibility import visible_chat_user_filters


ALLOWED_MEDIA_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "mov", "avi", "webm",
    "ogg", "mp3", "wav", "m4a", "aac",
    "pdf", "txt", "csv", "json", "zip", "7z", "rar",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
}


def _allowed_media(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS


def _resolve_message_type(filename, mimetype):
    ext = filename.rsplit(".", 1)[1].lower()
    mimetype = (mimetype or "").lower()
    if ext in {"png", "jpg", "jpeg", "gif", "webp"} or mimetype.startswith("image/"):
        return "image"
    if ext in {"mp4", "mov", "avi"} or mimetype.startswith("video/"):
        return "video"
    if ext in {"mp3", "wav", "m4a", "aac", "ogg"} or mimetype.startswith("audio/") or filename.startswith("voice_message"):
        return "voice"
    if ext == "webm":
        return "voice" if mimetype.startswith("audio/") or filename.startswith("voice_message") else "video"
    return "file"


def _has_structured_message_content(message_type, metadata):
    if not isinstance(metadata, dict):
        return False
    if message_type == "folder_link":
        folder_id = metadata.get("folder_id")
        folder_name = (metadata.get("folder_name") or "").strip()
        try:
            has_folder_id = int(folder_id) > 0
        except (TypeError, ValueError):
            has_folder_id = False
        return has_folder_id or bool(folder_name)
    if message_type == "calendar_event":
        return bool((metadata.get("title") or "").strip())
    if message_type == "poll":
        question = (metadata.get("question") or "").strip()
        options = metadata.get("options") if isinstance(metadata.get("options"), list) else []
        valid_options = [
            option for option in options
            if isinstance(option, dict) and (option.get("text") or "").strip()
        ]
        return bool(question and len(valid_options) >= 2)
    return False


def _chat_access_required():
    if not has_module_access(current_user, "module_chat"):
        return jsonify({"success": False, "error": "Kein Zugriff auf Chat-Modul"}), 403
    return None


def _build_calendar_message_metadata(event, current_user_status="pending"):
    is_all_day = False
    if event.start_time and event.end_time:
        starts_midnight = event.start_time.hour == 0 and event.start_time.minute == 0
        ends_same_day_2359 = (
            event.end_time.date() == event.start_time.date()
            and event.end_time.hour == 23
            and event.end_time.minute == 59
        )
        ends_next_day_midnight = (
            event.end_time.date() > event.start_time.date()
            and event.end_time.hour == 0
            and event.end_time.minute == 0
        )
        is_all_day = bool(starts_midnight and (ends_same_day_2359 or ends_next_day_midnight))
    participants = EventParticipant.query.filter_by(event_id=event.id).all()
    accepted_count = sum(1 for participant in participants if participant.status == "accepted")
    declined_count = sum(1 for participant in participants if participant.status == "declined")
    pending_count = sum(1 for participant in participants if participant.status == "pending")
    from app.utils import get_local_time
    return {
        "event_id": event.id,
        "title": event.title,
        "description": event.description or "",
        "location": event.location or "",
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "start_time_label": "Ganztägig" if is_all_day else (get_local_time(event.start_time).strftime("%H:%M") if event.start_time else ""),
        "end_time_label": "" if is_all_day else (get_local_time(event.end_time).strftime("%H:%M") if event.end_time else ""),
        "is_all_day": is_all_day,
        "event_url": url_for("calendar.view_event", event_id=event.id),
        "accepted_count": accepted_count,
        "declined_count": declined_count,
        "pending_count": pending_count,
        "participant_count": len(participants),
        "current_user_status": current_user_status or "pending",
    }


def _normalize_chat_id(chat_id):
    if chat_id == 1:
        main_chat = Chat.query.filter_by(is_main_chat=True).first()
        return main_chat.id if main_chat else None
    return chat_id


def _get_membership_or_403(chat_id):
    membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()
    if not membership:
        return None, (jsonify({"success": False, "error": translate("api.errors.unauthorized")}), 403)
    return membership, None


def _serialize_message(msg):
    from app.utils import get_local_time
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender.full_name if msg.sender else "Unbekannter Benutzer",
        "sender": msg.sender.full_name if msg.sender else "Unbekannter Benutzer",
        "content": msg.content,
        "message_type": msg.message_type,
        "media_url": msg.media_url,
        "media_full_url": url_for("chat.serve_media", filename=msg.media_url, _external=True) if msg.media_url else None,
        "metadata": msg.get_metadata(),
        "created_at": get_local_time(msg.created_at).isoformat(),
    }


def _serialize_chat(chat, unread_count=None):
    last_message = ChatMessage.query.filter_by(
        chat_id=chat.id,
        is_deleted=False,
    ).order_by(ChatMessage.created_at.desc()).first()
    if unread_count is None:
        membership = ChatMember.query.filter_by(chat_id=chat.id, user_id=current_user.id).first()
        unread_count = 0
        if membership:
            unread_count = ChatMessage.query.filter(
                ChatMessage.chat_id == chat.id,
                ChatMessage.created_at > membership.last_read_at,
                ChatMessage.sender_id != current_user.id,
                ChatMessage.is_deleted == False,
            ).count()
    return {
        "id": chat.id,
        "name": chat.name,
        "description": chat.description,
        "group_avatar": chat.group_avatar,
        "group_avatar_url": url_for("chat.serve_media", filename=f"avatars/{chat.group_avatar}", _external=True) if chat.group_avatar else None,
        "is_main_chat": chat.is_main_chat,
        "is_direct_message": chat.is_direct_message,
        "created_by": chat.created_by,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
        "unread_count": unread_count,
        "last_message": {
            "content": last_message.content,
            "created_at": last_message.created_at.isoformat(),
            "sender": last_message.sender.full_name if last_message.sender else "Unbekannter Benutzer",
            "message_type": last_message.message_type,
            "media_url": last_message.media_url,
        } if last_message else None,
    }


def register_chat_routes(api_bp, require_api_auth):
    @api_bp.route("/chats", methods=["GET"])
    @require_api_auth
    def get_chats():
        access_error = _chat_access_required()
        if access_error:
            return access_error

        memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
        chats = []
        for membership in memberships:
            chat = membership.chat
            unread_count = ChatMessage.query.filter(
                ChatMessage.chat_id == chat.id,
                ChatMessage.created_at > membership.last_read_at,
                ChatMessage.sender_id != current_user.id,
            ).count()
            chat_data = _serialize_chat(chat, unread_count=unread_count)
            if chat.is_direct_message and not chat.is_main_chat:
                members = ChatMember.query.filter_by(chat_id=chat.id).join(User).filter(
                    *visible_chat_user_filters(),
                ).all()
                for member in members:
                    if member.user_id != current_user.id:
                        chat_data["name"] = member.user.full_name
                        break
            chats.append(chat_data)
        return jsonify(chats)

    @api_bp.route("/chats/<int:chat_id>", methods=["GET"])
    @require_api_auth
    def get_chat(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        chat = Chat.query.get_or_404(actual_chat_id)
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error
        return jsonify({"success": True, "chat": _serialize_chat(chat)}), 200

    @api_bp.route("/chats/<int:chat_id>/messages", methods=["GET"])
    @require_api_auth
    def get_messages(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        since_id = request.args.get("since", type=int)
        limit = request.args.get("limit", default=200, type=int)
        if limit is None or limit < 1:
            limit = 200
        limit = min(limit, 500)

        query = ChatMessage.query.filter_by(chat_id=actual_chat_id, is_deleted=False)
        if since_id:
            query = query.filter(ChatMessage.id > since_id)
        messages = query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
        messages.reverse()
        return jsonify({"success": True, "messages": [_serialize_message(msg) for msg in messages]}), 200

    @api_bp.route("/chats/<int:chat_id>/send", methods=["POST"])
    @require_api_auth
    def send_message(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        chat = Chat.query.get_or_404(actual_chat_id)
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        data = request.get_json(silent=True) or {}
        content = ""
        file_obj = request.files.get("file")
        requested_type = "text"
        metadata = None
        if file_obj is not None:
            content = (request.form.get("content") or "").strip()
            requested_type = (request.form.get("message_type") or "text").strip().lower()
            metadata_raw = request.form.get("metadata")
            if metadata_raw:
                try:
                    metadata = json.loads(metadata_raw)
                except Exception:
                    metadata = None
        else:
            content = (data.get("content") or "").strip()
            requested_type = (data.get("message_type") or "text").strip().lower()
            metadata = data.get("metadata")

        message_type = requested_type if requested_type in {"text", "folder_link", "calendar_event", "poll"} else "text"
        media_url = None

        if file_obj and file_obj.filename:
            if not _allowed_media(file_obj.filename):
                return jsonify({"success": False, "error": "Dateityp nicht erlaubt"}), 400
            original_filename = secure_filename(file_obj.filename)
            filename = secure_filename(file_obj.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"

            project_root = os.path.dirname(current_app.root_path)
            upload_dir = os.path.join(project_root, current_app.config["UPLOAD_FOLDER"], "chat")
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)
            file_obj.save(filepath)
            media_url = filename

            message_type = _resolve_message_type(filename, file_obj.mimetype)
            if not isinstance(metadata, dict):
                metadata = {}
            metadata.setdefault("original_name", original_filename)
            try:
                metadata.setdefault("size_bytes", os.path.getsize(filepath))
            except Exception:
                pass

        if message_type == "folder_link":
            if not isinstance(metadata, dict):
                metadata = {}
            raw_folder_id = metadata.get("folder_id")
            try:
                folder_id = int(raw_folder_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Bitte einen Ordner auswählen."}), 400

            folder = Folder.query.get(folder_id)
            if not folder:
                return jsonify({"success": False, "error": "Ordner wurde nicht gefunden."}), 404

            if current_user.is_guest:
                _, guest_folders = get_guest_accessible_items(current_user)
                accessible_folder_ids = {item.id for item in guest_folders}
                if folder.id not in accessible_folder_ids:
                    return jsonify({"success": False, "error": "Gast Accounts haben keinen Zugriff auf diese Funktion"}), 403

            metadata = {
                "folder_id": folder.id,
                "folder_name": folder.name,
                "folder_path": folder.path,
                "folder_url": url_for("files.browse_folder", folder_id=folder.id),
            }
        if message_type == "calendar_event":
            if not isinstance(metadata, dict):
                metadata = {}
            raw_event_id = metadata.get("event_id")
            try:
                event_id = int(raw_event_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Bitte einen Termin auswählen."}), 400

            event = CalendarEvent.query.get(event_id)
            if not event:
                return jsonify({"success": False, "error": "Termin wurde nicht gefunden."}), 404

            participation = EventParticipant.query.filter_by(event_id=event.id, user_id=current_user.id).first()
            if participation and participation.status == "removed":
                return jsonify({"success": False, "error": "Sie wurden aus diesem Termin entfernt."}), 403

            metadata = _build_calendar_message_metadata(
                event,
                participation.status if participation else "pending",
            )

        if not content and not media_url and not _has_structured_message_content(message_type, metadata):
            return jsonify({"success": False, "error": translate("chat.errors.message_empty")}), 400

        message = ChatMessage(
            chat_id=actual_chat_id,
            sender_id=current_user.id,
            content=content,
            message_type=message_type,
            media_url=media_url,
        )
        if isinstance(metadata, dict):
            message.set_metadata(metadata)
        db.session.add(message)
        db.session.commit()

        try:
            enqueue_chat_notification(
                chat_id=actual_chat_id,
                sender_id=current_user.id,
                message_content=content or f"[{message_type}]",
                chat_name=chat.name,
                message_id=message.id,
            )
        except Exception:
            pass

        try:
            chat_members = ChatMember.query.filter_by(chat_id=actual_chat_id).all()
            for member in chat_members:
                if member.user_id == current_user.id:
                    continue
                user_memberships = ChatMember.query.filter_by(user_id=member.user_id).all()
                unread_count = 0
                for m in user_memberships:
                    unread_count += ChatMessage.query.filter(
                        ChatMessage.chat_id == m.chat_id,
                        ChatMessage.sender_id != member.user_id,
                        ChatMessage.created_at > m.last_read_at,
                        ChatMessage.is_deleted == False,
                    ).count()
                emit_dashboard_update(member.user_id, "chat_update", {"count": unread_count})
        except Exception:
            pass

        return jsonify({"success": True, "message": _serialize_message(message)}), 200

    @api_bp.route("/chats/<int:chat_id>/messages/<int:message_id>/calendar-rsvp", methods=["POST"])
    @require_api_auth
    def respond_to_calendar_event(chat_id, message_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        data = request.get_json(silent=True) or {}
        status = (data.get("status") or "").strip().lower()
        if status not in {"accepted", "declined"}:
            return jsonify({"success": False, "error": "Ungültiger Status"}), 400

        message = ChatMessage.query.filter_by(id=message_id, chat_id=actual_chat_id, is_deleted=False).first()
        if not message or message.message_type != "calendar_event":
            return jsonify({"success": False, "error": "Kalender-Nachricht nicht gefunden"}), 404

        metadata = message.get_metadata() if isinstance(message.get_metadata(), dict) else {}
        raw_event_id = metadata.get("event_id")
        try:
            event_id = int(raw_event_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Ungültige Event-ID"}), 400

        event = CalendarEvent.query.get(event_id)
        if not event:
            return jsonify({"success": False, "error": "Termin wurde nicht gefunden"}), 404

        participation = EventParticipant.query.filter_by(event_id=event.id, user_id=current_user.id).first()
        if participation and participation.status == "removed":
            return jsonify({"success": False, "error": "Sie wurden aus diesem Termin entfernt."}), 403

        if not participation:
            participation = EventParticipant(
                event_id=event.id,
                user_id=current_user.id,
                status=status,
                responded_at=datetime.utcnow(),
            )
            db.session.add(participation)
        else:
            participation.status = status
            participation.responded_at = datetime.utcnow()

        db.session.commit()

        refreshed_metadata = _build_calendar_message_metadata(event, status)
        refreshed_metadata["updated_at"] = datetime.utcnow().isoformat()
        message.set_metadata(refreshed_metadata)
        db.session.commit()

        return jsonify({"success": True, "message": _serialize_message(message)}), 200

    @api_bp.route("/chats/<int:chat_id>/messages/<int:message_id>/poll-vote", methods=["POST"])
    @require_api_auth
    def vote_on_poll(chat_id, message_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        message = ChatMessage.query.filter_by(id=message_id, chat_id=actual_chat_id, is_deleted=False).first()
        if not message or message.message_type != "poll":
            return jsonify({"success": False, "error": "Abstimmung nicht gefunden"}), 404

        data = request.get_json(silent=True) or {}
        option_id = (data.get("option_id") or "").strip()
        if not option_id:
            return jsonify({"success": False, "error": "option_id fehlt"}), 400

        metadata = message.get_metadata()
        options = metadata.get("options", []) if isinstance(metadata, dict) else []
        if not isinstance(options, list):
            options = []

        allow_multiple = bool(metadata.get("allow_multiple", False))
        if not allow_multiple:
            for option in options:
                votes = option.get("votes", [])
                option["votes"] = [vote for vote in votes if int(vote) != int(current_user.id)]

        selected = next((option for option in options if str(option.get("id")) == option_id), None)
        if not selected:
            return jsonify({"success": False, "error": "Option nicht gefunden"}), 404

        votes = [int(vote) for vote in selected.get("votes", [])]
        current_user_id = int(current_user.id)
        if current_user_id in votes:
            if allow_multiple:
                votes = [vote for vote in votes if vote != current_user_id]
        else:
            votes.append(current_user_id)
        selected["votes"] = votes
        metadata["options"] = options
        metadata["total_votes"] = sum(len(option.get("votes", [])) for option in options)
        metadata["updated_at"] = datetime.utcnow().isoformat()
        message.set_metadata(metadata)
        db.session.commit()

        return jsonify({"success": True, "message": _serialize_message(message)}), 200

    @api_bp.route("/chats/<int:chat_id>/members", methods=["GET"])
    @require_api_auth
    def get_chat_members(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        chat_memberships = ChatMember.query.filter_by(chat_id=actual_chat_id).all()
        member_ids = [cm.user_id for cm in chat_memberships]
        if member_ids:
            members = User.query.filter(
                User.id.in_(member_ids),
                *visible_chat_user_filters(),
            ).all()
        else:
            members = []

        chat = Chat.query.get_or_404(actual_chat_id)
        return jsonify([{
            "id": member.id,
            "full_name": member.full_name,
            "email": member.email,
            "phone": member.phone,
            "profile_picture": url_for("settings.profile_picture", filename=member.profile_picture) if member.profile_picture else None,
            "is_admin": member.is_admin,
            "is_guest": member.is_guest,
            "guest_username": member.guest_username,
            "is_creator": member.id == chat.created_by,
            "is_online": member.is_online(),
        } for member in members])

    @api_bp.route("/chats/create", methods=["POST"])
    @require_api_auth
    def create_chat():
        access_error = _chat_access_required()
        if access_error:
            return access_error

        data = request.get_json(silent=True) or {}
        chat_type = (data.get("chat_type") or "group").strip().lower()
        member_ids = data.get("member_ids") or []
        if not isinstance(member_ids, list):
            return jsonify({"success": False, "error": "member_ids muss eine Liste sein"}), 400

        if chat_type == "private":
            if len(member_ids) != 1:
                return jsonify({"success": False, "error": "Für private Chats genau 1 Zielnutzer angeben"}), 400
            try:
                other_user_id = int(member_ids[0])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Ungültige Nutzer-ID"}), 400
            if other_user_id == current_user.id:
                return jsonify({"success": False, "error": translate("chat.flash.no_self_chat")}), 400

            other_user = User.query.filter(
                User.id == other_user_id,
                *visible_chat_user_filters(),
            ).first_or_404()

            existing_dm = Chat.query.filter_by(is_direct_message=True).join(ChatMember).filter(
                ChatMember.user_id.in_([current_user.id, other_user_id])
            ).group_by(Chat.id).having(db.func.count(ChatMember.id) == 2).first()
            if existing_dm:
                return jsonify({"success": True, "chat": _serialize_chat(existing_dm), "existing": True}), 200

            chat_name = f"{current_user.full_name}, {other_user.full_name}"
            new_chat = Chat(
                name=chat_name,
                is_main_chat=False,
                is_direct_message=True,
                created_by=current_user.id,
            )
            db.session.add(new_chat)
            db.session.flush()
            db.session.add(ChatMember(chat_id=new_chat.id, user_id=current_user.id))
            db.session.add(ChatMember(chat_id=new_chat.id, user_id=other_user_id))
            db.session.commit()
            return jsonify({"success": True, "chat": _serialize_chat(new_chat)}), 201

        # group
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        if not name:
            return jsonify({"success": False, "error": translate("chat.flash.enter_name")}), 400
        if not member_ids:
            return jsonify({"success": False, "error": translate("chat.flash.select_member")}), 400

        new_chat = Chat(
            name=name,
            description=description,
            is_main_chat=False,
            is_direct_message=False,
            created_by=current_user.id,
        )
        db.session.add(new_chat)
        db.session.flush()
        db.session.add(ChatMember(chat_id=new_chat.id, user_id=current_user.id))

        for member_id in member_ids:
            try:
                member_id_int = int(member_id)
            except (TypeError, ValueError):
                continue
            if member_id_int == current_user.id:
                continue
            user = User.query.filter(
                User.id == member_id_int,
                *visible_chat_user_filters(),
            ).first()
            if user:
                db.session.add(ChatMember(chat_id=new_chat.id, user_id=member_id_int))

        db.session.commit()
        return jsonify({"success": True, "chat": _serialize_chat(new_chat)}), 201

    @api_bp.route("/chats/<int:chat_id>/update", methods=["PUT", "POST"])
    @require_api_auth
    def update_chat(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        chat = Chat.query.get_or_404(actual_chat_id)
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        if chat.is_main_chat:
            return jsonify({"success": False, "error": translate("chat.errors.main_chat_cannot_edit")}), 400
        if chat.is_direct_message:
            return jsonify({"success": False, "error": translate("chat.errors.private_chat_cannot_edit")}), 400

        if request.files:
            name = (request.form.get("name") or "").strip()
            description = (request.form.get("description") or "").strip()
            remove_avatar = request.form.get("remove_avatar") == "1"
            avatar_file = request.files.get("avatar")
        else:
            data = request.get_json(silent=True) or {}
            name = (data.get("name") or "").strip()
            description = (data.get("description") or "").strip()
            remove_avatar = bool(data.get("remove_avatar"))
            avatar_file = None

        if name:
            chat.name = name
        chat.description = description

        project_root = os.path.dirname(current_app.root_path)
        avatar_dir = os.path.join(project_root, current_app.config["UPLOAD_FOLDER"], "chat", "avatars")
        os.makedirs(avatar_dir, exist_ok=True)

        if avatar_file and avatar_file.filename:
            if not _allowed_media(avatar_file.filename):
                return jsonify({"success": False, "error": "Avatar-Dateityp nicht erlaubt"}), 400
            if chat.group_avatar:
                old_avatar_path = os.path.join(avatar_dir, chat.group_avatar)
                if os.path.exists(old_avatar_path):
                    try:
                        os.remove(old_avatar_path)
                    except Exception:
                        pass
            filename = secure_filename(avatar_file.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            avatar_file.save(os.path.join(avatar_dir, filename))
            chat.group_avatar = filename

        if remove_avatar and chat.group_avatar:
            avatar_path = os.path.join(avatar_dir, chat.group_avatar)
            if os.path.exists(avatar_path):
                try:
                    os.remove(avatar_path)
                except Exception:
                    pass
            chat.group_avatar = None

        chat.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True, "chat": _serialize_chat(chat)}), 200

    @api_bp.route("/chats/<int:chat_id>", methods=["DELETE"])
    @require_api_auth
    def delete_chat(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        chat = Chat.query.get_or_404(actual_chat_id)
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        if chat.is_main_chat:
            return jsonify({"success": False, "error": translate("chat.errors.main_chat_cannot_delete")}), 400

        db.session.delete(chat)
        db.session.commit()
        return jsonify({"success": True, "message": "Chat erfolgreich gelöscht"}), 200

    @api_bp.route("/chats/<int:chat_id>/mark-read", methods=["POST"])
    @require_api_auth
    def mark_chat_read(chat_id):
        access_error = _chat_access_required()
        if access_error:
            return access_error

        actual_chat_id = _normalize_chat_id(chat_id)
        if not actual_chat_id:
            return jsonify({"success": False, "error": "Haupt-Chat nicht gefunden"}), 404
        membership, error = _get_membership_or_403(actual_chat_id)
        if error:
            return error

        membership.last_read_at = datetime.utcnow()
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True}), 200

    @api_bp.route("/chat/unread-count", methods=["GET"])
    @require_api_auth
    def get_unread_chat_count():
        access_error = _chat_access_required()
        if access_error:
            return access_error
        try:
            user_chat_members = ChatMember.query.filter_by(user_id=current_user.id).all()
            unread_count = 0
            for member in user_chat_members:
                chat_unread = ChatMessage.query.filter(
                    ChatMessage.chat_id == member.chat_id,
                    ChatMessage.sender_id != current_user.id,
                    ChatMessage.created_at > member.last_read_at,
                    ChatMessage.is_deleted == False,
                ).count()
                unread_count += chat_unread
            return jsonify({"count": unread_count})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

