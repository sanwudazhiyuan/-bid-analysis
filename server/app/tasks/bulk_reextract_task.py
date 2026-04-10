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
    import json as _json
    from sqlalchemy import select
    from server.app.models.annotation import Annotation
    from src.extractor.base import reextract_with_annotations, call_qwen, build_messages
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

            # Build annotation dicts
            ann_dicts = []
            module_level = False
            ann_by_section: dict[str, list] = {}
            for ann in module_annotations:
                ann_dict = {
                    "row_index": ann.row_index,
                    "content": ann.content,
                    "annotation_type": ann.annotation_type,
                }
                # If section_id matches module_key, it's a module-level annotation
                if ann.section_id == module_key or ann.section_id is None:
                    module_level = True
                    ann_dicts.append(ann_dict)
                else:
                    ann_by_section.setdefault(ann.section_id, []).append(ann_dict)

            module_data = modules_result.get(module_key, {})
            sections = module_data.get("sections", []) if isinstance(module_data, dict) else []

            try:
                updated_sections = []
                if module_level and sections:
                    # Module-level annotation: one LLM call for the whole module
                    ann_text = "\n".join(f"- {a['content']}" for a in ann_dicts)
                    prompt = (
                        "你是招标文件分析专家。请根据用户的修改意见，对照原始提取结果重新提取。\n\n"
                        f"## 原始提取结果\n{_json.dumps({'sections': sections}, ensure_ascii=False, indent=2)}\n\n"
                        f"## 用户修改意见\n{ann_text}\n\n"
                        "## 要求\n"
                        "1. 仔细分析用户指出的问题，修正或补充内容\n"
                        "2. 返回完整的 JSON，格式为 {\"sections\": [...]}\n"
                        "3. 保持与原始结果相同的结构，section 的 id/type/title/columns 不变\n"
                        "4. 只修改用户指出的问题，其他内容保持不变"
                    )
                    messages = build_messages("你是招标文件分析专家。", prompt)
                    result = call_qwen(messages, api_settings)
                    if result and "sections" in result:
                        updated_sections = result["sections"]
                    else:
                        updated_sections = list(sections)
                else:
                    # Section-level annotations: per-section LLM calls
                    for section in sections:
                        section_id = section.get("id", "")
                        section_anns = ann_by_section.get(section_id, [])
                        if section_anns:
                            updated = reextract_with_annotations(
                                module_key,
                                section_id,
                                section,
                                [],
                                section_anns,
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

        # Auto-proceed to generation
        from server.app.tasks.generate_task import run_generate
        celery_result = run_generate.delay(task_id)
        task.celery_task_id = celery_result.id
        task.status = "generating"
        db.commit()

    return {"status": "generating", "task_id": task_id, "modules_processed": modules_processed}
