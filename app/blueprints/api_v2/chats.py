"""
Chats API namespace.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user

from app import db
from app.models.chat import Chat, ChatMessage, ChatMember

api = Namespace('chats', description='Chat-System')

# Models
chat_model = api.model('Chat', {
    'id': fields.Integer(description='Chat-ID'),
    'name': fields.String(description='Chat-Name'),
    'is_main_chat': fields.Boolean(description='Haupt-Chat'),
    'is_direct_message': fields.Boolean(description='Direktnachricht'),
    'unread_count': fields.Integer(description='Ungelesene Nachrichten'),
    'last_message': fields.Raw(description='Letzte Nachricht')
})

message_model = api.model('ChatMessage', {
    'id': fields.Integer(description='Nachrichten-ID'),
    'sender_id': fields.Integer(description='Absender-ID'),
    'sender_name': fields.String(description='Absendername'),
    'content': fields.String(description='Nachrichteninhalt'),
    'message_type': fields.String(description='Nachrichtentyp (text, image, video, audio)'),
    'media_url': fields.String(description='Medien-URL'),
    'created_at': fields.DateTime(description='Erstellungszeitpunkt')
})


@api.route('/')
class ChatList(Resource):
    @api.doc('list_chats', security='Bearer')
    @api.marshal_list_with(chat_model)
    @login_required
    def get(self):
        """
        Alle Chats des Benutzers auflisten.
        
        Gibt alle Chats zurück, in denen der aktuelle Benutzer Mitglied ist.
        """
        memberships = ChatMember.query.filter_by(user_id=current_user.id).all()
        chat_ids = [m.chat_id for m in memberships]
        
        chats = Chat.query.filter(Chat.id.in_(chat_ids)).order_by(Chat.updated_at.desc()).all()
        
        result = []
        for chat in chats:
            membership = next((m for m in memberships if m.chat_id == chat.id), None)
            
            # Calculate unread count
            unread_count = 0
            if membership and membership.last_read_at:
                unread_count = ChatMessage.query.filter(
                    ChatMessage.chat_id == chat.id,
                    ChatMessage.sender_id != current_user.id,
                    ChatMessage.created_at > membership.last_read_at,
                    ChatMessage.is_deleted == False
                ).count()
            
            # Get last message
            last_msg = ChatMessage.query.filter_by(
                chat_id=chat.id,
                is_deleted=False
            ).order_by(ChatMessage.created_at.desc()).first()
            
            result.append({
                'id': chat.id,
                'name': chat.name,
                'is_main_chat': chat.is_main_chat,
                'is_direct_message': chat.is_direct_message,
                'unread_count': unread_count,
                'last_message': {
                    'content': last_msg.content[:100] if last_msg else None,
                    'created_at': last_msg.created_at.isoformat() if last_msg else None,
                    'sender': last_msg.sender.full_name if last_msg else None
                } if last_msg else None
            })
        
        return result


@api.route('/<int:chat_id>/messages')
@api.param('chat_id', 'Chat-ID')
class ChatMessages(Resource):
    @api.doc('get_messages', security='Bearer')
    @api.marshal_list_with(message_model)
    @api.param('since', 'Nachrichten seit dieser ID', type=int)
    @api.param('limit', 'Maximale Anzahl', type=int, default=50)
    @login_required
    def get(self, chat_id):
        """
        Nachrichten eines Chats abrufen.
        
        Gibt die Nachrichten eines Chats zurück.
        Mit `since` können nur neue Nachrichten abgerufen werden.
        """
        # Check membership
        membership = ChatMember.query.filter_by(
            chat_id=chat_id,
            user_id=current_user.id
        ).first()
        
        if not membership:
            api.abort(403, 'Kein Zugriff auf diesen Chat')
        
        since = request.args.get('since', type=int)
        limit = min(request.args.get('limit', 50, type=int), 200)
        
        query = ChatMessage.query.filter_by(
            chat_id=chat_id,
            is_deleted=False
        )
        
        if since:
            query = query.filter(ChatMessage.id > since)
        
        messages = query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
        
        return [{
            'id': m.id,
            'sender_id': m.sender_id,
            'sender_name': m.sender.full_name if m.sender else 'Unbekannt',
            'content': m.content,
            'message_type': m.message_type,
            'media_url': m.media_url,
            'created_at': m.created_at
        } for m in reversed(messages)]
