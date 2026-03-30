import os
from datetime import datetime

from flask import current_app, jsonify, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app import db
from app.models.chat import Chat, ChatMember, ChatMessage
from app.models.user import User
from app.utils.access_control import has_module_access
from app.utils.dashboard_events import emit_dashboard_update
from app.utils.i18n import translate
from app.utils.notifications import send_chat_notification


ALLOWED_MEDIA_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "webm", "ogg", "mp3", "wav", "m4a"}


def _allowed_media(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS


def _chat_access_required():
    if not has_module_access(current_user, "module_chat"):
        return jsonify({"success": False, "error": "Kein Zugriff auf Chat-Modul"}), 403
    return None


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
                    ~User.is_guest,
                    User.email != "anonymous@system.local",
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
        if file_obj is not None:
            content = (request.form.get("content") or "").strip()
        else:
            content = (data.get("content") or "").strip()

        message_type = "text"
        media_url = None

        if file_obj and file_obj.filename:
            if not _allowed_media(file_obj.filename):
                return jsonify({"success": False, "error": "Dateityp nicht erlaubt"}), 400
            filename = secure_filename(file_obj.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"

            project_root = os.path.dirname(current_app.root_path)
            upload_dir = os.path.join(project_root, current_app.config["UPLOAD_FOLDER"], "chat")
            os.makedirs(upload_dir, exist_ok=True)
            file_obj.save(os.path.join(upload_dir, filename))
            media_url = filename

            ext = filename.rsplit(".", 1)[1].lower()
            if ext in {"png", "jpg", "jpeg", "gif"}:
                message_type = "image"
            elif ext in {"mp4", "webm", "ogg"}:
                message_type = "video"
            elif ext in {"mp3", "wav", "m4a"}:
                message_type = "voice"

        if not content and not media_url:
            return jsonify({"success": False, "error": translate("chat.errors.message_empty")}), 400

        message = ChatMessage(
            chat_id=actual_chat_id,
            sender_id=current_user.id,
            content=content,
            message_type=message_type,
            media_url=media_url,
        )
        db.session.add(message)
        db.session.commit()

        try:
            send_chat_notification(
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
                ~User.is_guest,
                User.email != "anonymous@system.local",
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
                ~User.is_guest,
                User.email != "anonymous@system.local",
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
                ~User.is_guest,
                User.email != "anonymous@system.local",
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

