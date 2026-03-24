"""Celery task: re-extract a section with user annotations."""
import json
import os
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.tasks.celery_app import celery_app
from server.app.config import settings

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="reextract_section")
def reextract_section(self, task_id: str, module_key: str, section_id: str, annotation_ids: list[int]):
    """根据用户标注重新提取指定 section。"""
    from src.extractor.base import reextract_with_annotations, ExtractError
    from src.config import load_settings
    from src.persistence import load_indexed
    from server.app.models.task import Task
    from server.app.models.annotation import Annotation

    self.update_state(state="PROGRESS", meta={"step": "reextracting", "detail": f"重提取 {section_id}...", "progress": 10})

    with Session(_sync_engine) as db:
        task = db.get(Task, _uuid.UUID(task_id))
        if not task or not task.extracted_data:
            return {"error": "Task or data not found"}

        modules = task.extracted_data.get("modules", {})
        module_data = modules.get(module_key, {})
        original_section = None
        for sec in (module_data or {}).get("sections", []):
            if sec.get("id") == section_id:
                original_section = sec
                break
        if not original_section:
            return {"error": f"Section {section_id} not found"}

        annotations = []
        for ann_id in annotation_ids:
            ann = db.get(Annotation, ann_id)
            if ann:
                annotations.append({
                    "row_index": ann.row_index,
                    "content": ann.content,
                    "annotation_type": ann.annotation_type,
                })
                ann.status = "submitted"
        db.commit()
        indexed_path = task.indexed_path

    relevant_paragraphs = []
    if indexed_path and os.path.exists(indexed_path):
        indexed = load_indexed(indexed_path)
        relevant_paragraphs = indexed.get("tagged_paragraphs", [])

    try:
        api_settings = load_settings()
        new_section = reextract_with_annotations(
            module_key, section_id, original_section, relevant_paragraphs, annotations, api_settings
        )

        self.update_state(state="PROGRESS", meta={"step": "reextracting", "detail": f"合并 {section_id}...", "progress": 80})

        with Session(_sync_engine) as db:
            task = db.get(Task, _uuid.UUID(task_id))
            extracted = dict(task.extracted_data)
            mod = extracted["modules"][module_key]
            for i, sec in enumerate(mod["sections"]):
                if sec.get("id") == section_id:
                    mod["sections"][i] = new_section
                    break
            task.extracted_data = extracted

            for ann_id in annotation_ids:
                ann = db.get(Annotation, ann_id)
                if ann:
                    ann.status = "resolved"
                    ann.llm_response = json.dumps(new_section, ensure_ascii=False)
            db.commit()

        return {"status": "ok", "section_id": section_id}

    except ExtractError as e:
        with Session(_sync_engine) as db:
            for ann_id in annotation_ids:
                ann = db.get(Annotation, ann_id)
                if ann:
                    ann.status = "failed"
            db.commit()
        raise
