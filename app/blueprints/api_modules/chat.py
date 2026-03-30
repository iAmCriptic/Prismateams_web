from flask import jsonify, request, url_for
from flask_login import current_user, login_required

from app.models.chat import Chat, ChatMember, ChatMessage
from app.models.user import User
from app.utils.i18n import translate


def register_chat_routes(api_bp, require_api_auth):
    @api_bp.route("/chats", methods=["GET"])
    @login_required
    def get_chats():
        memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
        chats = []
        for membership in memberships:
            chat = membership.chat
            unread_count = ChatMessage.query.filter(
                ChatMessage.chat_id == chat.id,
                ChatMessage.created_at > membership.last_read_at,
                ChatMessage.sender_id != current_user.id,
            ).count()

            last_message = ChatMessage.query.filter_by(
                chat_id=chat.id,
                is_deleted=False,
            ).order_by(ChatMessage.created_at.desc()).first()

            display_name = chat.name
            if chat.is_direct_message and not chat.is_main_chat:
                members = ChatMember.query.filter_by(chat_id=chat.id).join(User).filter(
                    ~User.is_guest,
                    User.email != "anonymous@system.local",
                ).all()
                for member in members:
                    if member.user_id != current_user.id:
                        display_name = member.user.full_name
                        break

            chats.append({
                "id": chat.id,
                "name": display_name,
                "is_main_chat": chat.is_main_chat,
                "is_direct_message": chat.is_direct_message,
                "unread_count": unread_count,
                "last_message": {
                    "content": last_message.content,
                    "created_at": last_message.created_at.isoformat(),
                    "sender": last_message.sender.full_name,
                } if last_message else None,
            })
        return jsonify(chats)

    @api_bp.route("/chats/<int:chat_id>/messages", methods=["GET"])
    @login_required
    def get_messages(chat_id):
        membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()
        if not membership:
            return jsonify({"error": translate("api.errors.unauthorized")}), 403

        since_id = request.args.get("since", type=int)
        query = ChatMessage.query.filter_by(chat_id=chat_id, is_deleted=False)
        if since_id:
            query = query.filter(ChatMessage.id > since_id)
        messages = query.order_by(ChatMessage.created_at).all()

        from app.utils import get_local_time
        return jsonify([{
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.full_name if msg.sender else "Unbekannter Benutzer",
            "sender": msg.sender.full_name if msg.sender else "Unbekannter Benutzer",
            "content": msg.content,
            "message_type": msg.message_type,
            "media_url": msg.media_url,
            "created_at": get_local_time(msg.created_at).isoformat(),
        } for msg in messages])

    @api_bp.route("/chats/<int:chat_id>/members", methods=["GET"])
    @login_required
    def get_chat_members(chat_id):
        membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()
        if not membership:
            return jsonify({"error": translate("api.errors.unauthorized")}), 403

        chat_memberships = ChatMember.query.filter_by(chat_id=chat_id).all()
        member_ids = [cm.user_id for cm in chat_memberships]
        if member_ids:
            members = User.query.filter(
                User.id.in_(member_ids),
                ~User.is_guest,
                User.email != "anonymous@system.local",
            ).all()
        else:
            members = []

        chat = Chat.query.get_or_404(chat_id)
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

    @api_bp.route("/chat/unread-count", methods=["GET"])
    @require_api_auth
    def get_unread_chat_count():
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

