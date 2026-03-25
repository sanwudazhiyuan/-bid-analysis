"""Celery task: run document generation stage (after human review)."""
import datetime
import os
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


def _get_task(db: Session, task_id: str):
    from server.app.models.task import Task
    return db.get(Task, _uuid.UUID(task_id))


@celery_app.task(bind=True, name="run_generate")
def run_generate(self, task_id: str):
    """生成三份输出文档。"""
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist

    with Session(_sync_engine) as db:
        task = _get_task(db, task_id)
        if not task or not task.extracted_data:
            return {"error": "Task or extracted data not found"}
        extracted = task.extracted_data
        filename = task.filename
        task.status = "generating"
        db.commit()

    output_dir = os.path.join(settings.DATA_DIR, "output", task_id)
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(filename)[0]

    try:
        self.update_state(state="PROGRESS", meta={"step": "generating", "detail": "生成分析报告...", "progress": 92})
        report_path = os.path.join(output_dir, f"{stem}_分析报告.docx")
        render_report(extracted, report_path)

        self.update_state(state="PROGRESS", meta={"step": "generating", "detail": "生成投标文件格式...", "progress": 95})
        format_path = os.path.join(output_dir, f"{stem}_投标文件格式.docx")
        render_format(extracted, format_path)

        self.update_state(state="PROGRESS", meta={"step": "generating", "detail": "生成资料清单...", "progress": 98})
        checklist_path = os.path.join(output_dir, f"{stem}_资料清单.docx")
        render_checklist(extracted, checklist_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.datetime.now()

            from server.app.models.generated_file import GeneratedFile
            for ftype, fpath in [
                ("report", report_path), ("format", format_path), ("checklist", checklist_path),
            ]:
                size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
                db.add(GeneratedFile(task_id=_uuid.UUID(task_id), file_type=ftype, file_path=fpath, file_size=size))
            db.commit()

        return {"status": "completed", "task_id": task_id}

    except Exception as e:
        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
        raise
