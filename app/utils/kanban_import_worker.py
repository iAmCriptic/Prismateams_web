"""Background worker for asynchronous Trello Kanban import jobs."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from app import db
from app.models.cloud_import import KanbanImportJob
from app.models.user import User

logger = logging.getLogger(__name__)


def process_trello_import_job(
    app,
    job_id: int,
    board_ids: list[str],
    api_key: str,
    token: str,
) -> None:
    """Import selected Trello boards in the background and update KanbanImportJob."""
    from app.blueprints.kanban.helpers import _log_activity
    from app.utils.kanban_access import KanbanImportPermissionError
    from app.utils.kanban_import import KanbanImportError, import_trello_board_dict
    from app.utils.trello_client import TrelloApiError, fetch_trello_board_json

    with app.app_context():
        job = db.session.get(KanbanImportJob, job_id)
        if not job:
            return
        if job.status not in ('pending', 'running'):
            return

        user = db.session.get(User, job.user_id)
        if not user:
            job.status = 'failed'
            job.error_message = 'user_not_found'
            job.completed_at = datetime.utcnow()
            db.session.commit()
            return

        job.status = 'running'
        if not job.started_at:
            job.started_at = datetime.utcnow()
        job.error_message = None
        db.session.commit()

        imported_boards: list[dict] = []
        errors: list[str] = []

        for bid in board_ids:
            try:
                board_json = fetch_trello_board_json(api_key, token, bid)
                board = import_trello_board_dict(
                    board_json,
                    user=user,
                    visibility=job.visibility,
                    team_id=job.team_id,
                    trello_auth=(api_key, token),
                )
                _log_activity(board.id, 'board_imported', board.title, user_id=user.id)
                db.session.commit()

                imported_boards.append({
                    'id': board.id,
                    'public_id': board.public_id,
                    'title': board.title,
                })
                job = db.session.get(KanbanImportJob, job_id)
                if job:
                    job.boards_done = len(imported_boards)
                    job.result_boards_json = json.dumps(imported_boards, ensure_ascii=False)
                    db.session.commit()
            except KanbanImportPermissionError as exc:
                db.session.rollback()
                errors.append(str(exc) or 'forbidden')
            except (TrelloApiError, KanbanImportError) as exc:
                db.session.rollback()
                errors.append(getattr(exc, 'code', None) or str(exc) or 'failed')
            except Exception:
                db.session.rollback()
                logger.exception('Background Trello board import failed for %s (job %s)', bid, job_id)
                errors.append('failed')

        job = db.session.get(KanbanImportJob, job_id)
        if not job:
            return

        if imported_boards:
            job.status = 'completed'
            job.boards_done = len(imported_boards)
            job.result_boards_json = json.dumps(imported_boards, ensure_ascii=False)
            if errors:
                job.error_message = ', '.join(errors)[:2000]
        else:
            job.status = 'failed'
            job.error_message = (', '.join(errors) or 'failed')[:2000]
        job.completed_at = datetime.utcnow()
        db.session.commit()


def start_trello_import_job(
    app,
    job_id: int,
    board_ids: list[str],
    api_key: str,
    token: str,
) -> None:
    """Spawn a daemon thread to run a Trello Kanban import job."""
    thread = threading.Thread(
        target=process_trello_import_job,
        args=(app, job_id, list(board_ids), api_key, token),
        daemon=True,
        name=f'trello-import-{job_id}',
    )
    thread.start()
