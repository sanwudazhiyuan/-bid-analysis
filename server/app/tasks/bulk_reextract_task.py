"""Celery task: bulk re-extraction for modules with pending annotations."""
import datetime
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


@celery_app.task(bind=True, name="run_bulk_reextract")
def run_bulk_reextract(self, task_id: str):
    """Re-extract all modules that have pending annotations, then set task back to review."""
    from sqlalchemy import select
    from server.app.models.annotation import Annotation
    from src.extractor.extractor import extract_single_module
    from src.extractor.base import reextract_with_annotations
    from src.config import load_settings

    api_settings = load_settings()

    with Session(_sync_engine) as db:
        task = _get_task(db, task_id)
        if not task:
            return {"error": "Task not found"}

        annotations = db.execute(
            select(Annotation).where(
                Annotation.task_id == _uuid.UUID(task_id),
                Annotation.status == "pending",
            )
        ).scalars().all()

        if not annotations:
            task.status = "review"
            db.commit()
            return {"status": "review", "task_id": task_id, "modules_processed": []}

        # Group annotations by module_key
        modules_map: dict[str, list] = {}
        for ann in annotations:
            modules_map.setdefault(ann.module_key, []).append(ann)

        extracted_data = task.extracted_data or {"schema_version": "1.0", "modules": {}}
        modules_result = dict(extracted_data.get("modules", {}))

        modules_processed = []
        total = len(modules_map)
        for i, (module_key, module_annotations) in enumerate(modules_map.items()):
            progress = 10 + int(70 * i / total)
            self.update_state(
                state="PROGRESS",
                meta={
                    "step": "reprocessing",
                    "detail": f"重提取 {module_key} [{i + 1}/{total}]",
                    "progress": progress,
                    "current_module": module_key,
                },
            )

            # Build annotation dicts for each section
            ann_by_section: dict[str, list] = {}
            for ann in module_annotations:
                ann_by_section.setdefault(ann.section_id, []).append({
                    "row_index": ann.row_index,
                    "content": ann.content,
                    "annotation_type": ann.annotation_type,
                })

            module_data = modules_result.get(module_key, {})
            sections = module_data.get("sections", []) if isinstance(module_data, dict) else []

            try:
                updated_sections = []
                for section in sections:
                    section_id = section.get("id", "")
                    if section_id in ann_by_section:
                        updated = reextract_with_annotations(
                            module_key,
                            section_id,
                            section,
                            [],
                            ann_by_section[section_id],
                            api_settings,
                        )
                        updated_sections.append(updated)
                    else:
                        updated_sections.append(section)

                if isinstance(module_data, dict):
                    new_module_data = dict(module_data)
                    new_module_data["sections"] = updated_sections
                else:
                    new_module_data = {"sections": updated_sections}

                modules_result[module_key] = new_module_data

                # Mark annotations as resolved
                now = datetime.datetime.now()
                for ann in module_annotations:
                    ann.status = "resolved"
                    ann.resolved_at = now

                modules_processed.append(module_key)
            except Exception as e:
                # If re-extraction fails for a module, leave it and continue
                for ann in module_annotations:
                    ann.llm_response = str(e)

        updated_extracted = dict(extracted_data)
        updated_extracted["modules"] = modules_result
        task.extracted_data = updated_extracted
        task.status = "review"
        db.commit()

    return {"status": "review", "task_id": task_id, "modules_processed": modules_processed}
