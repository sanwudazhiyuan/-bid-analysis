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
# Explicitly include task modules (autodiscover only finds 'tasks.py')
celery_app.conf.include = [
    "server.app.tasks.pipeline_task",
    "server.app.tasks.reextract_task",
    "server.app.tasks.generate_task",
    "server.app.tasks.bulk_reextract_task",
    "server.app.tasks.review_task",
    "server.app.tasks.anbiao_review_task",
]
