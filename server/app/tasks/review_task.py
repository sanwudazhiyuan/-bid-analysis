"""Celery task: run bid document review pipeline."""
import logging
import time
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="run_review")
def run_review(self, review_id: str):
    """Main review pipeline: parse -> desensitize -> extract images -> index -> map -> review -> generate docx."""
    from server.app.models.review_task import ReviewTask
    from server.app.models.task import Task
    from src.parser.unified import parse_document
    from src.reviewer.desensitizer import desensitize_paragraphs
    from src.reviewer.image_extractor import extract_images
    from src.reviewer.tender_rule_splitter import build_tender_index
    from src.reviewer.clause_extractor import extract_review_clauses, extract_project_context
    from src.reviewer.clause_mapper import llm_map_clauses_to_leaf_nodes
    from src.reviewer.tender_indexer import (
        get_text_for_clause, paragraphs_to_text, map_batch_indices_to_global,
    )
    from src.reviewer.reviewer import llm_review_clause, compute_summary
    from src.reviewer.docx_annotator import generate_review_docx
    from src.config import load_settings

    api_settings = load_settings()

    with Session(_sync_engine) as db:
        review = db.get(ReviewTask, _uuid.UUID(review_id))
        if not review:
            return {"error": "Review task not found"}

        bid_task = db.get(Task, review.bid_task_id)
        if not bid_task:
            review.status = "failed"
            review.error_message = "关联的招标任务不存在"
            db.commit()
            return {"error": "Bid task not found"}

        try:
            # Ensure bid analysis is complete
            _ensure_bid_complete(bid_task, db)
            extracted_data = bid_task.extracted_data
            if not extracted_data:
                raise ValueError("招标文件尚未完成解析")

            # Step 1: Parse tender file (0-5%)
            review.status = "indexing"
            review.progress = 0
            review.current_step = "解析投标文件"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 0, "detail": "解析投标文件"})

            paragraphs = parse_document(review.tender_file_path)

            # Step 1b: Desensitize PII (2-3%)
            review.progress = 2
            review.current_step = "信息脱敏"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 2, "detail": "信息脱敏"})

            paragraphs, pii_mapping = desensitize_paragraphs(paragraphs)
            logger.info("PII desensitization: %d items masked", len(pii_mapping))

            # Step 1c: Extract images (3-5%)
            review.progress = 3
            review.current_step = "提取图片"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 3, "detail": "提取图片"})

            import os
            images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
            extracted_images = extract_images(review.tender_file_path, images_dir)
            logger.info("Extracted %d images from tender document", len(extracted_images))

            # Inject image markers into paragraphs for LLM awareness
            index_to_pos = {p.index: pos for pos, p in enumerate(paragraphs)}

            image_by_para = {}
            for img in extracted_images:
                pi = img.get("near_para_index")
                if pi is not None:
                    image_by_para.setdefault(pi, []).append(img["filename"])

            from dataclasses import replace as dc_replace
            for pi, filenames in image_by_para.items():
                pos = index_to_pos.get(pi)
                if pos is not None:
                    marker = " ".join(f"[图片: {fn}]" for fn in filenames)
                    paragraphs[pos] = dc_replace(
                        paragraphs[pos],
                        text=paragraphs[pos].text + f" {marker}",
                    )

            # Step 2: Build index (5-10%)
            review.progress = 5
            review.current_step = "构建索引"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 5, "detail": "构建索引"})

            tender_index = build_tender_index(paragraphs, api_settings)
            logger.info(
                "Tender index built: source=%s, confidence=%.2f, chapters=%d",
                tender_index.get("toc_source"), tender_index.get("confidence", 0),
                len(tender_index.get("chapters", [])),
            )
            review.tender_index = tender_index

            # Step 3: Extract clauses (10-15%)
            review.status = "reviewing"
            review.progress = 10
            review.current_step = "提取审查条款"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 10, "detail": "提取条款"})

            clauses = extract_review_clauses(extracted_data)
            project_context = extract_project_context(extracted_data)

            if not clauses:
                review.status = "completed"
                review.progress = 100
                review.review_summary = {"total": 0, "pass": 0, "fail": 0, "warning": 0, "critical_fails": 0}
                review.review_items = []
                db.commit()
                return {"status": "completed", "review_id": review_id, "clauses": 0}

            # Step 4: Chapter mapping (12-15%)
            self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 12, "detail": "条款映射"})
            clause_mapping = llm_map_clauses_to_leaf_nodes(clauses, tender_index, api_settings)

            # Step 5-7: 逐条独立审查 (15-95%)
            _SEVERITY_ORDER = {"fail": 0, "error": 1, "warning": 2, "pass": 3}

            def _is_worse(a: dict, b: dict) -> bool:
                return _SEVERITY_ORDER.get(a.get("result", ""), 99) < _SEVERITY_ORDER.get(b.get("result", ""), 99)

            def _no_match_item(clause: dict) -> dict:
                return {
                    "source_module": clause["source_module"],
                    "clause_index": clause["clause_index"],
                    "clause_text": clause["clause_text"],
                    "result": "warning",
                    "confidence": 0,
                    "reason": "条款未能映射到投标文件任何章节节点",
                    "severity": clause["severity"],
                    "tender_locations": [],
                }

            review_items = []
            item_id = 0
            all_clauses = sorted(clauses, key=lambda c: {"critical": 0, "major": 1, "minor": 2}.get(c["severity"], 9))
            clause_progress_start = 15
            clause_progress_end = 95

            for i, clause in enumerate(all_clauses):
                progress = clause_progress_start + int(
                    (clause_progress_end - clause_progress_start) * i / max(len(all_clauses), 1)
                )
                step_key = (
                    "p0_review" if clause["severity"] == "critical" else
                    "p1_review" if clause["severity"] == "major" else "p2_review"
                )
                review.progress = progress
                review.current_step = f"审查 [{i+1}/{len(all_clauses)}] {clause['clause_text'][:20]}..."
                db.commit()
                self.update_state(state="PROGRESS", meta={
                    "step": step_key, "progress": progress,
                    "detail": review.current_step,
                })

                paths = clause_mapping.get(clause["clause_index"], [])
                if not paths:
                    item = _no_match_item(clause)
                    item["id"] = item_id
                    review_items.append(item)
                    item_id += 1
                    continue

                batches = get_text_for_clause(
                    clause["clause_index"], paths, tender_index, paragraphs
                )

                if not batches:
                    item = _no_match_item(clause)
                    item["id"] = item_id
                    review_items.append(item)
                    item_id += 1
                    continue

                if len(batches) == 1:
                    batch = batches[0]
                    tender_text = paragraphs_to_text(batch.paragraphs)
                    try:
                        result = llm_review_clause(clause, tender_text, project_context, api_settings)
                        result = map_batch_indices_to_global(result, batch)
                        result["id"] = item_id
                        review_items.append(result)
                    except Exception as e:
                        logger.error("Clause review failed for %d: %s", clause["clause_index"], e)
                        review_items.append({
                            "id": item_id, "source_module": clause["source_module"],
                            "clause_index": clause["clause_index"], "clause_text": clause["clause_text"],
                            "result": "error", "confidence": 0, "reason": f"LLM 调用失败: {e}",
                            "severity": clause["severity"], "tender_locations": [],
                        })
                else:
                    # 多批次：各批次独立审查，取最严格结果但合并所有位置信息
                    best_result = None
                    all_locations = []
                    for batch in batches:
                        tender_text = paragraphs_to_text(batch.paragraphs)
                        try:
                            r = llm_review_clause(clause, tender_text, project_context, api_settings)
                            r = map_batch_indices_to_global(r, batch)
                            all_locations.extend(r.get("tender_locations", []))
                            if best_result is None or _is_worse(r, best_result):
                                best_result = r
                        except Exception as e:
                            logger.error("Clause batch review failed for %s: %s", batch.batch_id, e)
                    if best_result is None:
                        best_result = {
                            "source_module": clause["source_module"],
                            "clause_index": clause["clause_index"],
                            "clause_text": clause["clause_text"],
                            "result": "error", "confidence": 0,
                            "reason": "所有批次 LLM 调用失败",
                            "severity": clause["severity"], "tender_locations": [],
                        }
                    else:
                        # 合并所有批次的位置信息
                        best_result["tender_locations"] = all_locations
                    best_result["id"] = item_id
                    review_items.append(best_result)

                item_id += 1

            # Step 8: Generate docx (95-100%)
            review.progress = 95
            review.current_step = "生成审查报告"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "generating", "progress": 95, "detail": "生成报告"})

            summary = compute_summary(review_items)
            import os
            output_dir = os.path.dirname(review.tender_file_path)
            annotated_path = generate_review_docx(
                review.tender_file_path, review_items, summary,
                bid_filename=bid_task.filename, output_dir=output_dir,
            )

            # Store images metadata in summary for preview API
            summary["extracted_images"] = [
                {"filename": img["filename"], "near_para_index": img.get("near_para_index"),
                 "content_type": img.get("content_type", "")}
                for img in extracted_images
            ]
            summary["pii_masked_count"] = len(pii_mapping)

            review.review_summary = summary
            review.review_items = review_items
            review.annotated_file_path = annotated_path
            review.status = "completed"
            review.progress = 100
            review.current_step = None
            db.commit()

            return {"status": "completed", "review_id": review_id}

        except Exception as e:
            logger.error("Review task failed: %s", e, exc_info=True)
            review.status = "failed"
            review.error_message = str(e)
            db.commit()
            return {"error": str(e)}


def _ensure_bid_complete(bid_task, db: Session):
    """Ensure bid analysis is complete. Wait or trigger generation if needed."""
    if bid_task.status == "completed":
        return

    if bid_task.status == "failed":
        raise ValueError("招标文件解析失败，请重新上传")

    if bid_task.status == "review":
        from server.app.tasks.generate_task import run_generate
        result = run_generate.delay(str(bid_task.id))
        bid_task.celery_task_id = result.id
        bid_task.status = "generating"
        db.commit()

    # Wait for completion (max 30 minutes)
    max_wait = 1800
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        db.refresh(bid_task)
        if bid_task.status == "completed":
            return
        if bid_task.status == "failed":
            raise ValueError("招标文件解析失败")
        if bid_task.status == "review":
            from server.app.tasks.generate_task import run_generate
            result = run_generate.delay(str(bid_task.id))
            bid_task.celery_task_id = result.id
            bid_task.status = "generating"
            db.commit()

    raise TimeoutError("等待招标文件解析超时（30分钟）")
