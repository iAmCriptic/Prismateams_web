"""
Webhooks API namespace.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user
import secrets

from app import db
from app.models.webhook import Webhook, WebhookDelivery
from app.utils.webhook_dispatcher import get_webhook_dispatcher

api = Namespace('webhooks', description='Webhook-Verwaltung')


def admin_required(f):
    """Decorator to require admin privileges."""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            api.abort(401, 'Nicht authentifiziert')
        if not current_user.is_admin:
            api.abort(403, 'Admin-Berechtigung erforderlich')
        return f(*args, **kwargs)
    
    return decorated_function


# Models
webhook_model = api.model('Webhook', {
    'id': fields.Integer(description='Webhook-ID'),
    'name': fields.String(description='Name'),
    'url': fields.String(description='Webhook-URL'),
    'events': fields.List(fields.String, description='Abonnierte Events'),
    'is_active': fields.Boolean(description='Aktiv'),
    'max_retries': fields.Integer(description='Max. Wiederholungen'),
    'timeout': fields.Integer(description='Timeout in Sekunden'),
    'total_deliveries': fields.Integer(description='Gesamte Zustellungen'),
    'successful_deliveries': fields.Integer(description='Erfolgreiche Zustellungen'),
    'failed_deliveries': fields.Integer(description='Fehlgeschlagene Zustellungen'),
    'created_at': fields.DateTime(description='Erstellt am'),
    'last_triggered_at': fields.DateTime(description='Zuletzt ausgelöst')
})

webhook_create_model = api.model('WebhookCreate', {
    'name': fields.String(required=True, description='Name'),
    'url': fields.String(required=True, description='Webhook-URL'),
    'events': fields.List(fields.String, required=True, description='Events'),
    'secret': fields.String(description='Secret für Signatur'),
    'headers': fields.Raw(description='Custom Headers'),
    'is_active': fields.Boolean(default=True),
    'max_retries': fields.Integer(default=5),
    'timeout': fields.Integer(default=10)
})

delivery_model = api.model('WebhookDelivery', {
    'id': fields.Integer(description='Delivery-ID'),
    'webhook_id': fields.Integer(description='Webhook-ID'),
    'event_type': fields.String(description='Event-Typ'),
    'status': fields.String(description='Status'),
    'response_code': fields.Integer(description='Response-Code'),
    'error_message': fields.String(description='Fehlermeldung'),
    'retry_count': fields.Integer(description='Wiederholungen'),
    'created_at': fields.DateTime(description='Erstellt am'),
    'delivered_at': fields.DateTime(description='Zugestellt am'),
    'duration_ms': fields.Integer(description='Dauer in ms')
})


@api.route('/')
class WebhookList(Resource):
    @api.doc('list_webhooks', security='Bearer')
    @api.marshal_list_with(webhook_model)
    @login_required
    @admin_required
    def get(self):
        """
        Alle Webhooks auflisten.
        
        Gibt alle konfigurierten Webhooks zurück.
        Nur für Administratoren.
        """
        webhooks = Webhook.query.order_by(Webhook.created_at.desc()).all()
        return [w.to_dict() for w in webhooks]
    
    @api.doc('create_webhook', security='Bearer')
    @api.expect(webhook_create_model)
    @api.marshal_with(webhook_model, code=201)
    @api.response(400, 'Ungültige Anfrage')
    @login_required
    @admin_required
    def post(self):
        """
        Neuen Webhook erstellen.
        
        Erstellt einen neuen Webhook für externe Event-Benachrichtigungen.
        Das Secret wird automatisch generiert, wenn nicht angegeben.
        """
        data = request.get_json()
        
        if not data:
            api.abort(400, 'Keine Daten übermittelt')
        
        name = data.get('name', '').strip()
        url = data.get('url', '').strip()
        events = data.get('events', [])
        
        if not name:
            api.abort(400, 'Name ist erforderlich')
        
        if not url:
            api.abort(400, 'URL ist erforderlich')
        
        if not url.startswith(('http://', 'https://')):
            api.abort(400, 'URL muss mit http:// oder https:// beginnen')
        
        if not events:
            api.abort(400, 'Mindestens ein Event ist erforderlich')
        
        invalid_events = [e for e in events if e not in Webhook.EVENTS]
        if invalid_events:
            api.abort(400, f'Ungültige Events: {", ".join(invalid_events)}')
        
        secret = data.get('secret') or secrets.token_hex(32)
        
        webhook = Webhook(
            name=name,
            url=url,
            secret=secret,
            events=events,
            headers=data.get('headers', {}),
            is_active=data.get('is_active', True),
            max_retries=data.get('max_retries', 5),
            timeout=data.get('timeout', 10),
            created_by=current_user.id
        )
        
        db.session.add(webhook)
        db.session.commit()
        
        result = webhook.to_dict()
        result['secret'] = secret  # Only shown on creation
        
        return result, 201


@api.route('/<int:webhook_id>')
@api.param('webhook_id', 'Webhook-ID')
class WebhookResource(Resource):
    @api.doc('get_webhook', security='Bearer')
    @api.marshal_with(webhook_model)
    @api.response(404, 'Webhook nicht gefunden')
    @login_required
    @admin_required
    def get(self, webhook_id):
        """
        Webhook-Details abrufen.
        """
        webhook = db.session.get(Webhook, webhook_id)
        if not webhook:
            api.abort(404, 'Webhook nicht gefunden')
        return webhook.to_dict()
    
    @api.doc('delete_webhook', security='Bearer')
    @api.response(204, 'Gelöscht')
    @api.response(404, 'Webhook nicht gefunden')
    @login_required
    @admin_required
    def delete(self, webhook_id):
        """
        Webhook löschen.
        """
        webhook = db.session.get(Webhook, webhook_id)
        if not webhook:
            api.abort(404, 'Webhook nicht gefunden')
        
        db.session.delete(webhook)
        db.session.commit()
        
        return '', 204


@api.route('/<int:webhook_id>/test')
@api.param('webhook_id', 'Webhook-ID')
class WebhookTest(Resource):
    @api.doc('test_webhook', security='Bearer')
    @api.response(200, 'Test-Ergebnis')
    @api.response(404, 'Webhook nicht gefunden')
    @login_required
    @admin_required
    def post(self, webhook_id):
        """
        Test-Event an Webhook senden.
        
        Sendet ein Test-Event, um die Webhook-Konfiguration zu überprüfen.
        """
        webhook = db.session.get(Webhook, webhook_id)
        if not webhook:
            api.abort(404, 'Webhook nicht gefunden')
        
        dispatcher = get_webhook_dispatcher()
        result = dispatcher.send_test_event(webhook_id)
        
        return result


@api.route('/<int:webhook_id>/deliveries')
@api.param('webhook_id', 'Webhook-ID')
class WebhookDeliveries(Resource):
    @api.doc('list_deliveries', security='Bearer')
    @api.marshal_list_with(delivery_model)
    @api.param('page', 'Seitennummer', type=int, default=1)
    @api.param('per_page', 'Einträge pro Seite', type=int, default=50)
    @login_required
    @admin_required
    def get(self, webhook_id):
        """
        Zustellungshistorie abrufen.
        
        Gibt die Historie aller Webhook-Zustellungen zurück.
        """
        webhook = db.session.get(Webhook, webhook_id)
        if not webhook:
            api.abort(404, 'Webhook nicht gefunden')
        
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        
        pagination = WebhookDelivery.query.filter_by(
            webhook_id=webhook_id
        ).order_by(
            WebhookDelivery.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        return [d.to_dict() for d in pagination.items]


@api.route('/events')
class WebhookEvents(Resource):
    @api.doc('list_events', security='Bearer')
    @login_required
    @admin_required
    def get(self):
        """
        Verfügbare Webhook-Events auflisten.
        
        Gibt alle Events zurück, die für Webhooks abonniert werden können.
        """
        return {'events': Webhook.EVENTS}
