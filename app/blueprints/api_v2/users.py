"""
Users API namespace.
"""
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user

from app.models.user import User

api = Namespace('users', description='Benutzerverwaltung')

# Models
user_model = api.model('User', {
    'id': fields.Integer(description='Benutzer-ID'),
    'email': fields.String(description='E-Mail-Adresse'),
    'full_name': fields.String(description='Vollständiger Name'),
    'first_name': fields.String(description='Vorname'),
    'last_name': fields.String(description='Nachname'),
    'is_admin': fields.Boolean(description='Admin-Status'),
    'profile_picture': fields.String(description='Profilbild-URL')
})

user_detail_model = api.inherit('UserDetail', user_model, {
    'phone': fields.String(description='Telefonnummer'),
    'accent_color': fields.String(description='Akzentfarbe'),
    'dark_mode': fields.Boolean(description='Dark Mode aktiviert'),
    'is_active': fields.Boolean(description='Account aktiv')
})


@api.route('/')
class UserList(Resource):
    @api.doc('list_users', security='Bearer')
    @api.marshal_list_with(user_model)
    @api.response(401, 'Nicht authentifiziert')
    @login_required
    def get(self):
        """
        Alle Benutzer auflisten.
        
        Gibt eine Liste aller aktiven Benutzer zurück.
        Gast-Accounts werden ausgeschlossen.
        """
        users = User.query.filter(
            User.is_active == True,
            User.email != 'anonymous@system.local'
        ).all()
        
        return [{
            'id': u.id,
            'email': u.email,
            'full_name': u.full_name,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'is_admin': u.is_admin,
            'profile_picture': f'/settings/profile-picture/{u.profile_picture_filename}' if u.profile_picture_filename else None
        } for u in users if not getattr(u, 'is_guest', False)]


@api.route('/<int:user_id>')
@api.param('user_id', 'Benutzer-ID')
class UserResource(Resource):
    @api.doc('get_user', security='Bearer')
    @api.marshal_with(user_detail_model)
    @api.response(404, 'Benutzer nicht gefunden')
    @login_required
    def get(self, user_id):
        """
        Einzelnen Benutzer abrufen.
        
        Gibt detaillierte Informationen zu einem Benutzer zurück.
        """
        user = User.query.get_or_404(user_id)
        
        return {
            'id': user.id,
            'email': user.email,
            'full_name': user.full_name,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone,
            'is_admin': user.is_admin,
            'profile_picture': f'/settings/profile-picture/{user.profile_picture_filename}' if user.profile_picture_filename else None,
            'accent_color': user.accent_color,
            'dark_mode': user.dark_mode,
            'is_active': user.is_active
        }
