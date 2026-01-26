"""
Webhook management blueprint.

Provides API endpoints for managing webhooks and viewing delivery history.
"""
import secrets
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.models.webhook import Webhook, WebhookDelivery
from app.utils.webhook_dispatcher import get_webhook_dispatcher


webhooks_bp = Blueprint('webhooks', __name__)


def admin_required(f):
    """Decorator to require admin privileges."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'Nicht authentifiziert'}), 401
        if not current_user.is_admin:
            return jsonify({'error': 'Admin-Berechtigung erforderlich'}), 403
        return f(*args, **kwargs)
    
    return decorated_function


@webhooks_bp.route('/api/webhooks', methods=['GET'])
@login_required
@admin_required
def list_webhooks():
    """List all webhooks."""
    webhooks = Webhook.query.order_by(Webhook.created_at.desc()).all()
    
    return jsonify({
        'webhooks': [w.to_dict() for w in webhooks],
        'available_events': Webhook.EVENTS
    })


@webhooks_bp.route('/api/webhooks', methods=['POST'])
@login_required
@admin_required
def create_webhook():
    """Create a new webhook."""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt'}), 400
    
    # Validate required fields
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    
    if not name:
        return jsonify({'error': 'Name ist erforderlich'}), 400
    
    if not url:
        return jsonify({'error': 'URL ist erforderlich'}), 400
    
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': 'URL muss mit http:// oder https:// beginnen'}), 400
    
    # Validate events
    events = data.get('events', [])
    if not events:
        return jsonify({'error': 'Mindestens ein Event ist erforderlich'}), 400
    
    invalid_events = [e for e in events if e not in Webhook.EVENTS]
    if invalid_events:
        return jsonify({
            'error': f'Ungültige Events: {", ".join(invalid_events)}'
        }), 400
    
    # Generate secret if not provided
    secret = data.get('secret')
    if secret is None:
        secret = secrets.token_hex(32)
    
    # Create webhook
    webhook = Webhook(
        name=name,
        url=url,
        secret=secret if secret else None,
        events=events,
        headers=data.get('headers', {}),
        is_active=data.get('is_active', True),
        max_retries=data.get('max_retries', 5),
        retry_delay=data.get('retry_delay', 60),
        timeout=data.get('timeout', 10),
        created_by=current_user.id
    )
    
    db.session.add(webhook)
    
    try:
        db.session.commit()
        
        response_data = webhook.to_dict()
        # Include secret only on creation
        if secret:
            response_data['secret'] = secret
        
        return jsonify({
            'success': True,
            'webhook': response_data,
            'message': 'Webhook erfolgreich erstellt'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Erstellen: {str(e)}'}), 500


@webhooks_bp.route('/api/webhooks/<int:webhook_id>', methods=['GET'])
@login_required
@admin_required
def get_webhook(webhook_id):
    """Get webhook details."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    return jsonify({
        'webhook': webhook.to_dict()
    })


@webhooks_bp.route('/api/webhooks/<int:webhook_id>', methods=['PUT'])
@login_required
@admin_required
def update_webhook(webhook_id):
    """Update a webhook."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Keine Daten übermittelt'}), 400
    
    # Update fields
    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return jsonify({'error': 'Name darf nicht leer sein'}), 400
        webhook.name = name
    
    if 'url' in data:
        url = data['url'].strip()
        if not url:
            return jsonify({'error': 'URL darf nicht leer sein'}), 400
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'URL muss mit http:// oder https:// beginnen'}), 400
        webhook.url = url
    
    if 'events' in data:
        events = data['events']
        if not events:
            return jsonify({'error': 'Mindestens ein Event ist erforderlich'}), 400
        invalid_events = [e for e in events if e not in Webhook.EVENTS]
        if invalid_events:
            return jsonify({
                'error': f'Ungültige Events: {", ".join(invalid_events)}'
            }), 400
        webhook.events = events
    
    if 'headers' in data:
        webhook.headers = data['headers']
    
    if 'is_active' in data:
        webhook.is_active = bool(data['is_active'])
    
    if 'max_retries' in data:
        webhook.max_retries = max(0, min(10, int(data['max_retries'])))
    
    if 'retry_delay' in data:
        webhook.retry_delay = max(10, min(3600, int(data['retry_delay'])))
    
    if 'timeout' in data:
        webhook.timeout = max(1, min(60, int(data['timeout'])))
    
    try:
        db.session.commit()
        
        return jsonify({
            'success': True,
            'webhook': webhook.to_dict(),
            'message': 'Webhook erfolgreich aktualisiert'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Aktualisieren: {str(e)}'}), 500


@webhooks_bp.route('/api/webhooks/<int:webhook_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_webhook(webhook_id):
    """Delete a webhook."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    try:
        db.session.delete(webhook)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Webhook erfolgreich gelöscht'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Löschen: {str(e)}'}), 500


@webhooks_bp.route('/api/webhooks/<int:webhook_id>/regenerate-secret', methods=['POST'])
@login_required
@admin_required
def regenerate_webhook_secret(webhook_id):
    """Regenerate the secret for a webhook."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    new_secret = secrets.token_hex(32)
    webhook.secret = new_secret
    
    try:
        db.session.commit()
        
        return jsonify({
            'success': True,
            'secret': new_secret,
            'message': 'Secret erfolgreich neu generiert'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Fehler beim Regenerieren: {str(e)}'}), 500


@webhooks_bp.route('/api/webhooks/<int:webhook_id>/deliveries', methods=['GET'])
@login_required
@admin_required
def list_webhook_deliveries(webhook_id):
    """List delivery history for a webhook."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 100)  # Max 100 per page
    
    # Filter by status
    status = request.args.get('status')
    
    query = WebhookDelivery.query.filter_by(webhook_id=webhook_id)
    
    if status:
        query = query.filter_by(status=status)
    
    query = query.order_by(WebhookDelivery.created_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'deliveries': [d.to_dict() for d in pagination.items],
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    })


@webhooks_bp.route('/api/webhooks/<int:webhook_id>/deliveries/<int:delivery_id>', methods=['GET'])
@login_required
@admin_required
def get_webhook_delivery(webhook_id, delivery_id):
    """Get details of a specific delivery."""
    delivery = WebhookDelivery.query.filter_by(
        id=delivery_id,
        webhook_id=webhook_id
    ).first()
    
    if not delivery:
        return jsonify({'error': 'Zustellung nicht gefunden'}), 404
    
    # Include full payload and response for detail view
    data = delivery.to_dict()
    data['request_headers'] = delivery.request_headers
    data['response_headers'] = delivery.response_headers
    data['response_body'] = delivery.response_body
    
    return jsonify({
        'delivery': data
    })


@webhooks_bp.route('/api/webhooks/<int:webhook_id>/test', methods=['POST'])
@login_required
@admin_required
def test_webhook(webhook_id):
    """Send a test event to a webhook."""
    webhook = db.session.get(Webhook, webhook_id)
    
    if not webhook:
        return jsonify({'error': 'Webhook nicht gefunden'}), 404
    
    dispatcher = get_webhook_dispatcher()
    result = dispatcher.send_test_event(webhook_id)
    
    return jsonify(result)


@webhooks_bp.route('/api/webhooks/events', methods=['GET'])
@login_required
@admin_required
def list_webhook_events():
    """List all available webhook events."""
    return jsonify({
        'events': Webhook.EVENTS
    })


@webhooks_bp.route('/api/webhooks/stats', methods=['GET'])
@login_required
@admin_required
def webhook_stats():
    """Get webhook statistics."""
    total_webhooks = Webhook.query.count()
    active_webhooks = Webhook.query.filter_by(is_active=True).count()
    
    total_deliveries = db.session.query(db.func.sum(Webhook.total_deliveries)).scalar() or 0
    successful_deliveries = db.session.query(db.func.sum(Webhook.successful_deliveries)).scalar() or 0
    failed_deliveries = db.session.query(db.func.sum(Webhook.failed_deliveries)).scalar() or 0
    
    # Recent deliveries (last 24 hours)
    from datetime import datetime, timedelta
    yesterday = datetime.utcnow() - timedelta(days=1)
    
    recent_deliveries = WebhookDelivery.query.filter(
        WebhookDelivery.created_at >= yesterday
    ).count()
    
    recent_failures = WebhookDelivery.query.filter(
        WebhookDelivery.created_at >= yesterday,
        WebhookDelivery.status == WebhookDelivery.STATUS_FAILED
    ).count()
    
    return jsonify({
        'total_webhooks': total_webhooks,
        'active_webhooks': active_webhooks,
        'total_deliveries': total_deliveries,
        'successful_deliveries': successful_deliveries,
        'failed_deliveries': failed_deliveries,
        'success_rate': round(successful_deliveries / total_deliveries * 100, 1) if total_deliveries > 0 else 0,
        'recent_deliveries_24h': recent_deliveries,
        'recent_failures_24h': recent_failures
    })
