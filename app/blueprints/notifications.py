from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models.notification import NotificationLog
from sqlalchemy import desc
from datetime import datetime

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications')
@login_required
def index():
    """Vollständige Benachrichtigungsübersicht."""
    category = request.args.get('category', None)
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = NotificationLog.query.filter_by(user_id=current_user.id)
    
    if category:
        query = query.filter_by(category=category)
    
    if unread_only:
        query = query.filter_by(is_read=False)
    
    notifications = query.order_by(desc(NotificationLog.sent_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Statistiken
    stats = db.session.query(
        NotificationLog.category,
        db.func.count(NotificationLog.id).label('count')
    ).filter_by(
        user_id=current_user.id,
        is_read=False
    ).group_by(NotificationLog.category).all()
    
    stats_dict = {category: count for category, count in stats}
    total_unread = sum(count for _, count in stats)
    
    return render_template(
        'notifications/index.html',
        notifications=notifications,
        category=category,
        unread_only=unread_only,
        stats=stats_dict,
        total_unread=total_unread
    )


@notifications_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def notifications_mark_read(notification_id):
    """Markiere eine Benachrichtigung als gelesen."""
    notification = NotificationLog.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()
    
    if not notification:
        return jsonify({'error': 'Benachrichtigung nicht gefunden'}), 404
    
    notification.mark_as_read()
    
    return jsonify({'success': True})


@notifications_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_mark_all_read():
    """Markiere alle Benachrichtigungen als gelesen."""
    category = request.json.get('category', None) if request.json else None
    
    query = NotificationLog.query.filter_by(
        user_id=current_user.id,
        is_read=False
    )
    
    if category:
        query = query.filter_by(category=category)
    
    notifications = query.all()
    
    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'marked_count': len(notifications)
    })
