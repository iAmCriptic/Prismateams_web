"""Cloud-import routes mounted on the settings blueprint."""

from typing import Optional

import json

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from app.models.cloud_import import CloudImportConnection, CloudImportJob
from app.models.file import Folder
from app.utils.cloud_import.base import decrypt_credentials, encrypt_credentials
from app.utils.cloud_import.google_drive import build_google_drive_provider
from app.utils.cloud_import.nextcloud import build_nextcloud_provider
from app.utils.cloud_import.oauth import get_google_drive_oauth_url
from app.utils.cloud_import.permissions import (
    CloudImportPermissionError,
    allowed_import_spaces_for_user,
    assert_can_import_to_space,
    resolve_import_target_folder,
)
from app.utils.cloud_import.worker import start_cloud_import_job
from app.utils.common import is_module_enabled
from app.utils.i18n import translate
from app.utils.integrations import google_oauth_configured
from app.utils.private_files import (
    ensure_personal_root,
    ensure_team_root,
    is_private_folders_enabled,
    is_team_folders_enabled,
)


def _require_files_module():
    if not is_module_enabled('module_files'):
        flash(translate('settings.cloud_import.flash.module_disabled'), 'warning')
        return False
    return True


def _serialize_connection(conn: CloudImportConnection) -> dict:
    return {
        'id': conn.id,
        'provider': conn.provider,
        'display_name': conn.display_name or conn.provider,
        'created_at': conn.created_at.isoformat() + 'Z' if conn.created_at else None,
    }


def _serialize_job(job: CloudImportJob) -> dict:
    progress = 0
    if job.files_total and job.files_total > 0:
        progress = int(round(100.0 * (job.files_done or 0) / job.files_total))
    elif job.status == 'completed':
        progress = 100
    return {
        'id': job.id,
        'status': job.status,
        'provider': job.connection.provider if job.connection else None,
        'display_name': job.connection.display_name if job.connection else None,
        'target_space': job.target_space,
        'team_id': job.team_id,
        'files_done': job.files_done or 0,
        'files_total': job.files_total or 0,
        'files_skipped': job.files_skipped or 0,
        'bytes_done': job.bytes_done or 0,
        'progress': progress,
        'error_message': job.error_message,
        'created_at': job.created_at.isoformat() + 'Z' if job.created_at else None,
        'completed_at': job.completed_at.isoformat() + 'Z' if job.completed_at else None,
    }


def _provider_for_connection(conn: CloudImportConnection):
    creds = decrypt_credentials(conn.credentials_enc)
    if conn.provider == 'nextcloud':
        return build_nextcloud_provider(creds)
    if conn.provider == 'google_drive':
        return build_google_drive_provider(creds)
    raise ValueError('unknown_provider')


def _user_owns_connection(conn_id: int) -> Optional[CloudImportConnection]:
    return CloudImportConnection.query.filter_by(
        id=conn_id,
        user_id=current_user.id,
    ).first()


def _list_dest_folders(space: str, team_id=None, parent_id=None) -> list:
    space = (space or '').strip().lower()
    if parent_id:
        q = Folder.query.filter(
            Folder.deleted_at.is_(None),
            Folder.space == space,
            Folder.parent_id == int(parent_id),
        )
    elif space == 'personal':
        root = ensure_personal_root(current_user.id)
        q = Folder.query.filter(
            Folder.deleted_at.is_(None),
            Folder.space == space,
            Folder.parent_id == root.id,
        )
    elif space == 'team' and team_id:
        root = ensure_team_root(int(team_id), current_user.id)
        q = Folder.query.filter(
            Folder.deleted_at.is_(None),
            Folder.space == space,
            Folder.team_id == int(team_id),
            Folder.parent_id == (root.id if root else None),
        )
    else:
        q = Folder.query.filter(
            Folder.deleted_at.is_(None),
            Folder.space == 'public',
            Folder.parent_id.is_(None),
            Folder.is_personal_root.is_(False),
            Folder.is_team_root.is_(False),
        )

    folders = q.order_by(Folder.name).limit(200).all()
    return [{'id': f.id, 'name': f.name, 'is_dir': True} for f in folders]


def register_cloud_import_routes(bp):
    @bp.route('/cloud-import')
    @login_required
    def cloud_import():
        if not _require_files_module():
            return redirect(url_for('settings.index'))

        connections = (
            CloudImportConnection.query.filter_by(user_id=current_user.id)
            .order_by(CloudImportConnection.created_at.desc())
            .all()
        )
        jobs = (
            CloudImportJob.query.filter_by(user_id=current_user.id)
            .order_by(CloudImportJob.created_at.desc())
            .limit(30)
            .all()
        )
        spaces = allowed_import_spaces_for_user(current_user)

        return render_template(
            'settings/cloud_import.html',
            connections=connections,
            jobs=jobs,
            spaces=spaces,
            google_configured=google_oauth_configured(),
            private_folders_enabled=is_private_folders_enabled(),
            team_folders_enabled=is_team_folders_enabled(),
        )

    @bp.route('/cloud-import/connect/nextcloud', methods=['POST'])
    @login_required
    def cloud_import_connect_nextcloud():
        if not _require_files_module():
            return jsonify({'ok': False, 'error': 'module_disabled'}), 403

        data = request.get_json(silent=True) or request.form
        server_url = (data.get('server_url') or '').strip().rstrip('/')
        username = (data.get('username') or '').strip()
        app_password = (data.get('app_password') or '').strip()
        if not server_url or not username or not app_password:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.credentials_incomplete'),
            }), 400

        try:
            provider = build_nextcloud_provider({
                'server_url': server_url,
                'username': username,
                'app_password': app_password,
            })
            provider.test_connection()
        except Exception:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.nextcloud_connect_failed'),
            }), 400

        display = f'Nextcloud ({username}@{server_url.replace("https://", "").replace("http://", "")})'
        payload = {
            'server_url': server_url,
            'username': username,
            'app_password': app_password,
        }
        conn = CloudImportConnection(
            user_id=current_user.id,
            provider='nextcloud',
            display_name=display[:255],
            credentials_enc=encrypt_credentials(payload),
        )
        db.session.add(conn)
        db.session.commit()
        return jsonify({'ok': True, 'connection': _serialize_connection(conn)})

    @bp.route('/cloud-import/connect/google')
    @login_required
    def cloud_import_connect_google():
        if not _require_files_module():
            return redirect(url_for('settings.index'))
        if not google_oauth_configured():
            flash(translate('settings.cloud_import.flash.google_not_configured'), 'warning')
            return redirect(url_for('settings.cloud_import'))
        try:
            return redirect(get_google_drive_oauth_url())
        except Exception as exc:
            flash(translate('settings.cloud_import.flash.google_oauth_error', error=str(exc)), 'danger')
            return redirect(url_for('settings.cloud_import'))

    @bp.route('/cloud-import/connections/<int:connection_id>', methods=['DELETE'])
    @login_required
    def cloud_import_delete_connection(connection_id):
        conn = _user_owns_connection(connection_id)
        if not conn:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        active = CloudImportJob.query.filter(
            CloudImportJob.connection_id == conn.id,
            CloudImportJob.status.in_(('pending', 'running', 'cancelling')),
        ).count()
        if active:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.connection_in_use'),
            }), 400
        db.session.delete(conn)
        db.session.commit()
        return jsonify({'ok': True})

    @bp.route('/cloud-import/browse/<int:connection_id>')
    @login_required
    def cloud_import_browse(connection_id):
        conn = _user_owns_connection(connection_id)
        if not conn:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        path = (request.args.get('path') or '').strip()
        try:
            provider = _provider_for_connection(conn)
            entries = provider.list_children(path)
        except Exception:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.browse_failed'),
            }), 400
        return jsonify({
            'ok': True,
            'path': path,
            'entries': [
                {
                    'id': e.id,
                    'name': e.name,
                    'is_dir': e.is_dir,
                    'size': e.size,
                    'path': e.path,
                }
                for e in entries
            ],
        })

    @bp.route('/cloud-import/dest-folders')
    @login_required
    def cloud_import_dest_folders():
        space = (request.args.get('space') or 'personal').strip().lower()
        team_id = request.args.get('team_id', type=int)
        parent_id = request.args.get('parent_id', type=int)
        try:
            assert_can_import_to_space(current_user, space, team_id)
        except CloudImportPermissionError:
            return jsonify({'ok': False, 'error': 'forbidden'}), 403
        try:
            folders = _list_dest_folders(space, team_id, parent_id)
        except Exception:
            folders = []
        root = resolve_import_target_folder(current_user, space, team_id, None)
        return jsonify({
            'ok': True,
            'root_id': getattr(root, 'id', None),
            'folders': folders,
        })

    @bp.route('/cloud-import/jobs', methods=['POST'])
    @login_required
    def cloud_import_start_job():
        if not _require_files_module():
            return jsonify({'ok': False, 'error': 'module_disabled'}), 403

        data = request.get_json(silent=True) or {}
        connection_id = data.get('connection_id')
        selected = data.get('selected') or []
        target_space = (data.get('target_space') or 'personal').strip().lower()
        team_id = data.get('team_id')
        target_folder_id = data.get('target_folder_id')

        conn = _user_owns_connection(int(connection_id)) if connection_id else None
        if not conn:
            return jsonify({'ok': False, 'error': 'connection_not_found'}), 404
        if not isinstance(selected, list) or not selected:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.no_selection'),
            }), 400

        try:
            team_id_int = int(team_id) if team_id else None
            folder_id_int = int(target_folder_id) if target_folder_id else None
            dest = resolve_import_target_folder(
                current_user,
                target_space,
                team_id_int,
                folder_id_int,
            )
        except CloudImportPermissionError:
            return jsonify({
                'ok': False,
                'error': translate('settings.cloud_import.flash.space_forbidden'),
            }), 403
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'invalid_target'}), 400

        job = CloudImportJob(
            user_id=current_user.id,
            connection_id=conn.id,
            status='pending',
            source_paths=json.dumps(selected, ensure_ascii=False),
            target_space=target_space,
            team_id=team_id_int if target_space == 'team' else None,
            target_folder_id=getattr(dest, 'id', None),
        )
        db.session.add(job)
        db.session.commit()
        start_cloud_import_job(current_app._get_current_object(), job.id)
        return jsonify({'ok': True, 'job': _serialize_job(job)})

    @bp.route('/cloud-import/jobs/<int:job_id>')
    @login_required
    def cloud_import_job_status(job_id):
        job = CloudImportJob.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, 'job': _serialize_job(job)})

    @bp.route('/cloud-import/jobs/<int:job_id>/cancel', methods=['POST'])
    @login_required
    def cloud_import_cancel_job(job_id):
        job = CloudImportJob.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if job.status in ('pending', 'running'):
            job.status = 'cancelling'
            db.session.commit()
        return jsonify({'ok': True, 'job': _serialize_job(job)})

    @bp.route('/cloud-import/jobs')
    @login_required
    def cloud_import_list_jobs():
        jobs = (
            CloudImportJob.query.filter_by(user_id=current_user.id)
            .order_by(CloudImportJob.created_at.desc())
            .limit(30)
            .all()
        )
        return jsonify({'ok': True, 'jobs': [_serialize_job(j) for j in jobs]})
