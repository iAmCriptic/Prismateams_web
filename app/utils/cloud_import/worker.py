"""Background worker for cloud import jobs."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any

from app import db
from app.models.cloud_import import CloudImportConnection, CloudImportJob
from app.utils.cloud_import.base import decrypt_credentials, encrypt_credentials
from app.utils.cloud_import.google_drive import build_google_drive_provider
from app.utils.cloud_import.ingest import (
    file_exists_in_folder,
    find_or_create_folder_path,
    ingest_file_bytes,
)
from app.utils.cloud_import.nextcloud import build_nextcloud_provider
from app.utils.file_storage_limits import check_upload_allowed

logger = logging.getLogger(__name__)


def _parse_source_paths(job: CloudImportJob) -> list[dict[str, Any]]:
    try:
        data = json.loads(job.source_paths or '[]')
        return data if isinstance(data, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _read_all(stream) -> bytes:
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)
    if hasattr(stream, 'read'):
        data = stream.read()
        if isinstance(data, str):
            return data.encode('utf-8')
        return data or b''
    return b''


def _build_provider(connection: CloudImportConnection):
    creds = decrypt_credentials(connection.credentials_enc)
    if connection.provider == 'nextcloud':
        return build_nextcloud_provider(creds)

    if connection.provider == 'google_drive':
        conn_id = connection.id

        def on_refresh(access_token, expires_at):
            c = CloudImportConnection.query.get(conn_id)
            if not c:
                return
            payload = decrypt_credentials(c.credentials_enc)
            payload['access_token'] = access_token
            payload['expires_at'] = expires_at.isoformat() if expires_at else None
            c.credentials_enc = encrypt_credentials(payload)
            db.session.commit()

        return build_google_drive_provider(creds, on_token_refresh=on_refresh)

    raise ValueError(f'unknown_provider:{connection.provider}')


def _job_cancelled(job_id: int) -> bool:
    job = CloudImportJob.query.get(job_id)
    if not job:
        return True
    return job.status in ('cancelled', 'cancelling', 'failed')


def _fail_job(job: CloudImportJob, message: str) -> None:
    job.status = 'failed'
    job.error_message = (message or 'error')[:2000]
    job.completed_at = datetime.utcnow()
    db.session.commit()


def _process_one_file(job, provider, connection, rel_path, download_fn, user_id, space, team_id, target_folder_id, pending_bytes):
    parts = [p for p in (rel_path or '').replace('\\', '/').split('/') if p]
    if not parts:
        return pending_bytes, True
    filename = parts[-1]
    folder_parts = parts[:-1]

    dest_folder_id = find_or_create_folder_path(
        target_folder_id,
        folder_parts,
        user_id,
        space,
        team_id,
    )

    if file_exists_in_folder(dest_folder_id, filename):
        job.files_skipped = (job.files_skipped or 0) + 1
        job.files_done = (job.files_done or 0) + 1
        db.session.commit()
        return pending_bytes, True

    stream = download_fn()
    data = _read_all(stream)
    actual_size = len(data)

    ok, code, msg = check_upload_allowed(
        user_id,
        actual_size,
        pending_bytes=pending_bytes,
    )
    if not ok:
        _fail_job(job, msg or code or 'quota_exceeded')
        return pending_bytes, False

    ingest_file_bytes(
        data,
        filename,
        dest_folder_id,
        user_id,
        space=space,
        team_id=team_id,
    )
    pending_bytes += actual_size
    job.files_done = (job.files_done or 0) + 1
    job.bytes_done = (job.bytes_done or 0) + actual_size
    db.session.commit()
    return pending_bytes, True


def process_cloud_import_job(app, job_id: int) -> None:
    with app.app_context():
        job = CloudImportJob.query.get(job_id)
        if not job:
            return
        if job.status not in ('pending', 'running'):
            return

        job.status = 'running'
        job.started_at = datetime.utcnow()
        job.error_message = None
        db.session.commit()

        connection = CloudImportConnection.query.get(job.connection_id)
        if not connection:
            _fail_job(job, 'connection_missing')
            return

        try:
            provider = _build_provider(connection)
        except Exception as exc:
            logger.exception('cloud import provider build failed')
            _fail_job(job, str(exc))
            return

        selected = _parse_source_paths(job)
        if not selected:
            _fail_job(job, 'no_sources')
            return

        target_folder_id = job.target_folder_id
        space = job.target_space or 'personal'
        team_id = job.team_id
        user_id = job.user_id
        pending_bytes = 0

        try:
            if connection.provider == 'nextcloud':
                entries = provider.collect_selected_entries(selected)
                job.files_total = len(entries)
                db.session.commit()
                for entry in entries:
                    if _job_cancelled(job_id):
                        job = CloudImportJob.query.get(job_id)
                        if job and job.status == 'cancelling':
                            job.status = 'cancelled'
                            job.completed_at = datetime.utcnow()
                            db.session.commit()
                        return
                    pending_bytes, ok = _process_one_file(
                        job,
                        provider,
                        connection,
                        entry.path or entry.id,
                        lambda e=entry: provider.download_stream(e.id),
                        user_id,
                        space,
                        team_id,
                        target_folder_id,
                        pending_bytes,
                    )
                    if not ok:
                        return
            else:
                entries = provider.collect_selected_entries(selected)
                job.files_total = len(entries)
                db.session.commit()
                for rel, file_id, _size in entries:
                    if _job_cancelled(job_id):
                        job = CloudImportJob.query.get(job_id)
                        if job and job.status == 'cancelling':
                            job.status = 'cancelled'
                            job.completed_at = datetime.utcnow()
                            db.session.commit()
                        return

                    def _dl(fid=file_id, rpath=rel):
                        content, final_name = provider.download_bytes(fid)
                        if '/' in rpath:
                            parent, _ = rpath.rsplit('/', 1)
                            out_rel = f'{parent}/{final_name}'
                        else:
                            out_rel = final_name
                        return out_rel, content

                    out_rel, content = _dl()
                    pending_bytes, ok = _process_one_file(
                        job,
                        provider,
                        connection,
                        out_rel,
                        lambda c=content: c,
                        user_id,
                        space,
                        team_id,
                        target_folder_id,
                        pending_bytes,
                    )
                    if not ok:
                        return

            job = CloudImportJob.query.get(job_id)
            if job and job.status == 'running':
                job.status = 'completed'
                job.completed_at = datetime.utcnow()
                db.session.commit()
        except Exception as exc:
            logger.exception('cloud import job %s failed', job_id)
            job = CloudImportJob.query.get(job_id)
            if job:
                _fail_job(job, str(exc))


def start_cloud_import_job(app, job_id: int) -> None:
    thread = threading.Thread(
        target=process_cloud_import_job,
        args=(app, job_id),
        daemon=True,
        name=f'cloud-import-{job_id}',
    )
    thread.start()
