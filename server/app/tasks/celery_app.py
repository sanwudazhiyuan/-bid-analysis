"""Celery application instance."""

from celery import Celery
from server.app.config import settings

celery_app = Celery("bid_analyzer", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_track_started=True,
)
# Auto-discover task modules in this package
celery_app.autodiscover_tasks(["server.app.tasks"])
