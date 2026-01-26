"""
Files API namespace.
"""
from flask import request
from flask_restx import Namespace, Resource, fields
from flask_login import login_required, current_user

from app.models.file import File, Folder

api = Namespace('files', description='Dateiverwaltung')

# Models
file_model = api.model('File', {
    'id': fields.Integer(description='Datei-ID'),
    'name': fields.String(description='Dateiname'),
    'original_name': fields.String(description='Originalname'),
    'size': fields.Integer(description='Dateigröße in Bytes'),
    'mime_type': fields.String(description='MIME-Typ'),
    'version': fields.Integer(description='Versionsnummer'),
    'folder_id': fields.Integer(description='Ordner-ID'),
    'uploaded_by': fields.String(description='Hochgeladen von'),
    'uploaded_at': fields.DateTime(description='Hochladezeitpunkt')
})

folder_model = api.model('Folder', {
    'id': fields.Integer(description='Ordner-ID'),
    'name': fields.String(description='Ordnername'),
    'parent_id': fields.Integer(description='Übergeordneter Ordner'),
    'created_at': fields.DateTime(description='Erstellungszeitpunkt')
})

files_list_response = api.model('FilesListResponse', {
    'items': fields.List(fields.Nested(file_model)),
    'total': fields.Integer(description='Gesamtanzahl'),
    'limit': fields.Integer(),
    'offset': fields.Integer()
})


@api.route('/')
class FileList(Resource):
    @api.doc('list_files', security='Bearer')
    @api.marshal_with(files_list_response)
    @api.param('folder_id', 'Ordner-ID (null für Root)', type=int)
    @api.param('limit', 'Maximale Anzahl', type=int, default=50)
    @api.param('offset', 'Offset für Pagination', type=int, default=0)
    @login_required
    def get(self):
        """
        Dateien in einem Ordner auflisten.
        
        Gibt alle Dateien in einem bestimmten Ordner zurück.
        Ohne `folder_id` werden Dateien im Root-Ordner zurückgegeben.
        """
        folder_id = request.args.get('folder_id', type=int)
        limit = min(request.args.get('limit', 50, type=int), 200)
        offset = request.args.get('offset', 0, type=int)
        
        query = File.query.filter_by(
            folder_id=folder_id,
            is_current=True
        )
        
        total = query.count()
        files = query.order_by(File.updated_at.desc()).offset(offset).limit(limit).all()
        
        return {
            'items': [{
                'id': f.id,
                'name': f.name,
                'original_name': f.original_name,
                'size': f.file_size,
                'mime_type': f.mime_type,
                'version': f.version_number,
                'folder_id': f.folder_id,
                'uploaded_by': f.uploader.full_name if f.uploader else 'Unbekannt',
                'uploaded_at': f.created_at
            } for f in files],
            'total': total,
            'limit': limit,
            'offset': offset
        }


@api.route('/<int:file_id>')
@api.param('file_id', 'Datei-ID')
class FileResource(Resource):
    @api.doc('get_file', security='Bearer')
    @api.marshal_with(file_model)
    @api.response(404, 'Datei nicht gefunden')
    @login_required
    def get(self, file_id):
        """
        Datei-Details abrufen.
        
        Gibt detaillierte Informationen zu einer Datei zurück.
        """
        file = File.query.filter_by(id=file_id, is_current=True).first_or_404()
        
        return {
            'id': file.id,
            'name': file.name,
            'original_name': file.original_name,
            'size': file.file_size,
            'mime_type': file.mime_type,
            'version': file.version_number,
            'folder_id': file.folder_id,
            'uploaded_by': file.uploader.full_name if file.uploader else 'Unbekannt',
            'uploaded_at': file.created_at
        }


@api.route('/folders')
class FolderList(Resource):
    @api.doc('list_folders', security='Bearer')
    @api.marshal_list_with(folder_model)
    @api.param('parent_id', 'Übergeordneter Ordner-ID', type=int)
    @login_required
    def get(self):
        """
        Unterordner auflisten.
        
        Gibt alle Unterordner eines bestimmten Ordners zurück.
        """
        parent_id = request.args.get('parent_id', type=int)
        
        folders = Folder.query.filter_by(parent_id=parent_id).order_by(Folder.name).all()
        
        return [{
            'id': f.id,
            'name': f.name,
            'parent_id': f.parent_id,
            'created_at': f.created_at
        } for f in folders]
