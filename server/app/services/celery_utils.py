"""Celery task management utilities — revoke active tasks for a specific user."""

import logging

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from server.app.config import settings as server_settings
from server.app.models.task import Task
from server.app.models.review_task import ReviewTask

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("pending", "parsing", "extracting", "embedding", "indexing",
                    "reviewing", "review", "generating", "reprocessing",
                    "describing", "mapping", "smart_reviewing")


def revoke_user_active_tasks(user_id: int) -> int:
    """Revoke all active Celery tasks for a given user.

    Only terminates tasks owned by this user — other users' tasks are untouched.
    Returns the number of tasks revoked.
    """
    from server.app.tasks.celery_app import celery_app

    sync_url = server_settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    celery_ids: list[str] = []
    with Session(engine) as db:
        # Collect celery_task_ids from tasks table
        rows = db.execute(
            select(Task.celery_task_id)
            .where(Task.user_id == user_id, Task.status.in_(_ACTIVE_STATUSES))
        ).scalars().all()
        celery_ids.extend(r for r in rows if r)

        # Collect celery_task_ids from review_tasks table
        rows = db.execute(
            select(ReviewTask.celery_task_id)
            .where(ReviewTask.user_id == user_id, ReviewTask.status.in_(_ACTIVE_STATUSES))
        ).scalars().all()
        celery_ids.extend(r for r in rows if r)

    if not celery_ids:
        return 0

    # Revoke each task (terminate=True kills the worker process running it)
    for task_id in celery_ids:
        try:
            celery_app.control.revoke(task_id, terminate=True)
        except Exception as e:
            logger.warning("Failed to revoke task %s for user %d: %s", task_id, user_id, e)

    logger.info("Revoked %d Celery tasks for user %d: %s", len(celery_ids), user_id, celery_ids)
    return len(celery_ids)