from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.comment import Comment, CommentMention
from app.models.user import User
from app.utils.notifications import send_push_notification
from datetime import datetime

comments_bp = Blueprint('comments', __name__, url_prefix='/api/comments')


def process_mentions(comment_text, comment_id):
    """Verarbeitet @-Mentions im Kommentar-Text und erstellt CommentMention-Einträge."""
    # Extrahiere Mentions aus dem Text
    mentions = Comment.extract_mentions(comment_text)
    
    if not mentions:
        return []
    
    created_mentions = []
    
    for mention_text in mentions:
        # Versuche Benutzer zu finden
        # Zuerst nach vollem Namen suchen (z.B. "Max Mustermann")
        if ' ' in mention_text:
            parts = mention_text.split(' ', 1)
            user = User.query.filter(
                db.and_(
                    User.is_active == True,
                    User.first_name.ilike(f"%{parts[0]}%"),
                    User.last_name.ilike(f"%{parts[1]}%")
                )
            ).first()
        else:
            # Suche nach E-Mail oder Vor-/Nachname
            user = User.query.filter(
                db.and_(
                    User.is_active == True,
                    db.or_(
                        User.email.ilike(f"%{mention_text}%"),
                        User.first_name.ilike(f"%{mention_text}%"),
                        User.last_name.ilike(f"%{mention_text}%")
                    )
                )
            ).first()
        
        if user and user.id != current_user.id:
            # Prüfe ob Mention bereits existiert
            existing_mention = CommentMention.query.filter_by(
                comment_id=comment_id,
                user_id=user.id
            ).first()
            
            if not existing_mention:
                mention = CommentMention(
                    comment_id=comment_id,
                    user_id=user.id
                )
                db.session.add(mention)
                created_mentions.append((user, mention))
    
    db.session.commit()
    return created_mentions


def send_mention_notifications(comment, mentions):
    """Sendet Benachrichtigungen für @-Mentions."""
    comment_obj = comment.get_content_object()
    content_name = ""
    
    if comment.content_type == 'file':
        content_name = comment_obj.name if comment_obj else "Datei"
    elif comment.content_type == 'wiki':
        content_name = comment_obj.title if comment_obj else "Wiki-Seite"
    
    for user, mention in mentions:
        # Sende Push-Benachrichtigung
        if send_push_notification(
            user_id=user.id,
            title=f"Du wurdest in einem Kommentar erwähnt",
            body=f"{current_user.full_name} hat dich in einem Kommentar zu \"{content_name}\" erwähnt",
            url=comment.get_content_url(),
            data={
                'comment_id': comment.id,
                'content_type': comment.content_type,
                'content_id': comment.content_id,
                'type': 'comment_mention'
            }
        ):
            mention.notification_sent = True
            mention.notification_sent_at = datetime.utcnow()
            db.session.commit()


@comments_bp.route('/<content_type>/<int:content_id>', methods=['GET'])
@login_required
def get_comments(content_type, content_id):
    """Holt alle Kommentare für ein Objekt."""
    if content_type not in ['file', 'wiki']:
        return jsonify({'error': 'Ungültiger content_type'}), 400
    
    # Lade alle Kommentare (nur Top-Level, ohne Replies)
    comments = Comment.query.filter_by(
        content_type=content_type,
        content_id=content_id,
        parent_id=None,
        is_deleted=False
    ).order_by(Comment.created_at.asc()).all()
    
    result = []
    for comment in comments:
        result.append({
            'id': comment.id,
            'content': comment.content,
            'author': {
                'id': comment.author.id,
                'name': comment.author.full_name,
                'email': comment.author.email,
                'profile_picture': comment.author.profile_picture or None
            },
            'created_at': comment.created_at.isoformat(),
            'updated_at': comment.updated_at.isoformat(),
            'replies': get_replies(comment.id)
        })
    
    return jsonify({'comments': result})


def get_replies(parent_id):
    """Hilfsfunktion zum Laden von Antworten."""
    replies = Comment.query.filter_by(
        parent_id=parent_id,
        is_deleted=False
    ).order_by(Comment.created_at.asc()).all()
    
    result = []
    for reply in replies:
        result.append({
            'id': reply.id,
            'content': reply.content,
            'author': {
                'id': reply.author.id,
                'name': reply.author.full_name,
                'email': reply.author.email,
                'profile_picture': reply.author.profile_picture or None
            },
            'created_at': reply.created_at.isoformat(),
            'updated_at': reply.updated_at.isoformat(),
            'replies': get_replies(reply.id)  # Rekursiv für verschachtelte Threads
        })
    
    return result


@comments_bp.route('/<content_type>/<int:content_id>', methods=['POST'])
@login_required
def create_comment(content_type, content_id):
    """Erstellt einen neuen Kommentar."""
    if content_type not in ['file', 'wiki']:
        return jsonify({'error': 'Ungültiger content_type'}), 400
    
    # Prüfe ob Kommentare für .md Dateien deaktiviert sind
    if content_type == 'file':
        from app.models.file import File
        file = File.query.get(content_id)
        if file and file.name.endswith('.md'):
            return jsonify({'error': 'Kommentare sind für Markdown-Dateien deaktiviert'}), 403
    
    data = request.get_json()
    content = data.get('content', '').strip()
    parent_id = data.get('parent_id', None)
    
    if not content:
        return jsonify({'error': 'Kommentar-Inhalt darf nicht leer sein'}), 400
    
    # Prüfe ob parent_id gültig ist (falls vorhanden)
    if parent_id:
        parent_comment = Comment.query.get(parent_id)
        if not parent_comment or parent_comment.is_deleted:
            return jsonify({'error': 'Ungültiger parent-Kommentar'}), 400
        if parent_comment.content_type != content_type or parent_comment.content_id != content_id:
            return jsonify({'error': 'Parent-Kommentar gehört nicht zu diesem Objekt'}), 400
    
    # Erstelle Kommentar
    comment = Comment(
        content_type=content_type,
        content_id=content_id,
        content=content,
        author_id=current_user.id,
        parent_id=parent_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Verarbeite Mentions
    mentions = process_mentions(content, comment.id)
    
    # Sende Benachrichtigungen für Mentions
    if mentions:
        send_mention_notifications(comment, mentions)
    
    return jsonify({
        'success': True,
        'comment': {
            'id': comment.id,
            'content': comment.content,
            'author': {
                'id': comment.author.id,
                'name': comment.author.full_name,
                'email': comment.author.email,
                'profile_picture': comment.author.profile_picture or None
            },
            'created_at': comment.created_at.isoformat(),
            'updated_at': comment.updated_at.isoformat(),
            'replies': []
        }
    }), 201


@comments_bp.route('/<int:comment_id>', methods=['PUT'])
@login_required
def update_comment(comment_id):
    """Aktualisiert einen Kommentar."""
    comment = Comment.query.get_or_404(comment_id)
    
    # Prüfe Berechtigung
    if comment.author_id != current_user.id:
        return jsonify({'error': 'Keine Berechtigung'}), 403
    
    if comment.is_deleted:
        return jsonify({'error': 'Kommentar wurde gelöscht'}), 400
    
    data = request.get_json()
    content = data.get('content', '').strip()
    
    if not content:
        return jsonify({'error': 'Kommentar-Inhalt darf nicht leer sein'}), 400
    
    comment.content = content
    comment.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'comment': {
            'id': comment.id,
            'content': comment.content,
            'updated_at': comment.updated_at.isoformat()
        }
    })


@comments_bp.route('/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Löscht einen Kommentar (Soft Delete)."""
    comment = Comment.query.get_or_404(comment_id)
    
    # Prüfe Berechtigung
    if comment.author_id != current_user.id:
        return jsonify({'error': 'Keine Berechtigung'}), 403
    
    comment.soft_delete()
    
    return jsonify({'success': True})


@comments_bp.route('/users/search', methods=['GET'])
@login_required
def search_users():
    """Sucht Benutzer für @-Mention-Autovervollständigung."""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify({'users': []})
    
    # Suche nach Benutzern
    users = User.query.filter(
        db.and_(
            User.is_active == True,
            db.or_(
                User.first_name.ilike(f"%{query}%"),
                User.last_name.ilike(f"%{query}%"),
                User.email.ilike(f"%{query}%")
            )
        )
    ).limit(10).all()
    
    result = []
    for user in users:
        result.append({
            'id': user.id,
            'name': user.full_name,
            'email': user.email,
            'mention': f"@{user.first_name} {user.last_name}"
        })
    
    return jsonify({'users': result})

