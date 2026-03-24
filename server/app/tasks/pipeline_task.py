"""Celery task: run the full analysis pipeline."""
import datetime
import os
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

# Sync DB engine for Celery worker (no asyncpg)
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)

_MODULE_KEYS = [
    "module_a", "module_b", "module_c", "module_d", "module_e",
    "module_f", "module_g", "bid_format", "checklist",
]


def _get_task(db: Session, task_id: str):
    from server.app.models.task import Task
    return db.get(Task, _uuid.UUID(task_id))


@celery_app.task(bind=True, name="run_pipeline")
def run_pipeline(self, task_id: str):
    """执行完整分析管线，逐模块上报进度。"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index
    from src.extractor.extractor import extract_single_module
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from src.persistence import save_parsed, save_indexed, save_extracted
    from src.config import load_settings

    with Session(_sync_engine) as db:
        task = _get_task(db, task_id)
        if not task:
            return {"error": "Task not found"}
        task.status = "parsing"
        task.started_at = datetime.datetime.now(datetime.timezone.utc)
        file_path = task.file_path
        filename = task.filename
        db.commit()

    data_dir = os.path.join(settings.DATA_DIR, "intermediate", task_id)
    output_dir = os.path.join(settings.DATA_DIR, "output", task_id)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Layer 1: Parse (0-10%)
        self.update_state(
            state="PROGRESS",
            meta={"step": "parsing", "detail": "解析文档中...", "progress": 5},
        )
        paragraphs = parse_document(file_path)
        parsed_path = os.path.join(data_dir, "parsed.json")
        save_parsed(paragraphs, parsed_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "indexing"
            task.parsed_path = parsed_path
            db.commit()

        # Layer 2: Index (10-20%)
        self.update_state(
            state="PROGRESS",
            meta={"step": "indexing", "detail": "构建索引中...", "progress": 15},
        )
        index_result = build_index(paragraphs)
        indexed_path = os.path.join(data_dir, "indexed.json")
        save_indexed(index_result, indexed_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "extracting"
            task.indexed_path = indexed_path
            db.commit()

        # Layer 3: Extract (20-90%)
        api_settings = load_settings()
        tagged = index_result.get("tagged_paragraphs", [])
        modules_result = {}
        for i, module_key in enumerate(_MODULE_KEYS):
            progress = 20 + int(70 * i / len(_MODULE_KEYS))
            self.update_state(
                state="PROGRESS",
                meta={
                    "step": "extracting",
                    "detail": f"提取 {module_key} [{i + 1}/{len(_MODULE_KEYS)}]",
                    "progress": progress,
                    "current_module": module_key,
                    "modules_done": i,
                    "modules_total": len(_MODULE_KEYS),
                },
            )
            try:
                modules_result[module_key] = extract_single_module(module_key, tagged, api_settings)
            except Exception as e:
                modules_result[module_key] = {"status": "failed", "error": str(e)}

        extracted = {"schema_version": "1.0", "modules": modules_result}
        extracted_path = os.path.join(data_dir, "extracted.json")
        save_extracted(extracted, extracted_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "generating"
            task.extracted_path = extracted_path
            task.extracted_data = extracted
            db.commit()

        # Layer 4: Generate (90-100%)
        self.update_state(
            state="PROGRESS",
            meta={"step": "generating", "detail": "生成文档中...", "progress": 95},
        )
        stem = os.path.splitext(filename)[0]
        report_path = os.path.join(output_dir, f"{stem}_分析报告.docx")
        format_path = os.path.join(output_dir, f"{stem}_投标文件格式.docx")
        checklist_path = os.path.join(output_dir, f"{stem}_资料清单.docx")

        render_report(extracted, report_path)
        render_format(extracted, format_path)
        render_checklist(extracted, checklist_path)

        # Complete
        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.datetime.now(datetime.timezone.utc)

            from server.app.models.generated_file import GeneratedFile
            for ftype, fpath in [
                ("report", report_path),
                ("format", format_path),
                ("checklist", checklist_path),
            ]:
                size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
                db.add(GeneratedFile(
                    task_id=_uuid.UUID(task_id),
                    file_type=ftype,
                    file_path=fpath,
                    file_size=size,
                ))
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
