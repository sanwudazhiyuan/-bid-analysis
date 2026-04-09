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
    from src.reviewer.reviewer import (
        llm_review_clause, llm_review_clause_intermediate,
        llm_review_clause_final, assemble_multi_batch_result, compute_summary,
    )
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

            review_mode = review.review_mode or "fixed"

            # Step 1: Parse tender file (0-5%)
            review.status = "indexing"
            review.progress = 0
            review.current_step = "解析投标文件"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 0, "detail": "解析投标文件"})

            paragraphs = parse_document(review.tender_file_path)

            # Step 1b: Extract images (2-3%)
            review.progress = 2
            review.current_step = "提取图片"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 2, "detail": "提取图片"})

            import os
            images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
            extracted_images = extract_images(review.tender_file_path, images_dir)
            logger.info("Extracted %d images from tender document", len(extracted_images))

            # Step 2: Build index on CLEAN paragraphs (5-10%)
            # 必须在脱敏和图片标记注入之前建索引，避免标题文本被污染
            review.progress = 5
            review.current_step = "构建索引"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 5, "detail": "构建索引"})

            tender_index = build_tender_index(paragraphs, api_settings)

            # Step 2b: Desensitize PII AFTER index is built
            review.current_step = "信息脱敏"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 7, "detail": "信息脱敏"})

            paragraphs, pii_mapping = desensitize_paragraphs(paragraphs)
            logger.info("PII desensitization: %d items masked", len(pii_mapping))

            # Inject image markers AFTER index is built
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

            bid_tagged_paragraphs = _load_bid_tagged_paragraphs(bid_task)
            clauses = extract_review_clauses(extracted_data, tagged_paragraphs=bid_tagged_paragraphs)
            project_context = extract_project_context(extracted_data)

            if not clauses:
                review.status = "completed"
                review.progress = 100
                review.review_summary = {"total": 0, "pass": 0, "fail": 0, "warning": 0, "critical_fails": 0}
                review.review_items = []
                db.commit()
                return {"status": "completed", "review_id": review_id, "clauses": 0}

            all_clauses = sorted(clauses, key=lambda c: {"critical": 0, "major": 1, "minor": 2}.get(c["severity"], 9))
            clause_progress_start = 15
            clause_progress_end = 95

            from concurrent.futures import ThreadPoolExecutor, as_completed

            if review_mode == "smart":
                # ── 智能审核模式：构建文件夹 → haha-code 逐条审查 ──
                from src.reviewer.folder_builder import build_tender_folder
                from src.reviewer.smart_reviewer import call_smart_review

                # Step 4s: 构建投标文件文件夹结构 (12-15%)
                self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 12, "detail": "构建文件夹"})
                review.progress = 12
                review.current_step = "构建文件夹结构"
                db.commit()

                import os
                folder_dir = os.path.join(os.path.dirname(review.tender_file_path), "tender_folder")
                build_tender_folder(paragraphs, tender_index, extracted_images, folder_dir)
                logger.info("Tender folder built at %s", folder_dir)

                # Step 5s-7s: 并发智能审查 (15-95%)
                SMART_MAX_WORKERS = 4
                results_by_index: dict[int, dict] = {}
                futures = {}

                with ThreadPoolExecutor(max_workers=SMART_MAX_WORKERS) as executor:
                    for clause in all_clauses:
                        future = executor.submit(call_smart_review, clause, folder_dir, project_context)
                        futures[future] = clause

                    completed = 0
                    for future in as_completed(futures):
                        clause = futures[future]
                        completed += 1
                        progress = clause_progress_start + int(
                            (clause_progress_end - clause_progress_start) * completed / max(len(all_clauses), 1)
                        )
                        review.progress = progress
                        review.current_step = f"智能审查 [{completed}/{len(all_clauses)}]"
                        db.commit()
                        self.update_state(state="PROGRESS", meta={
                            "step": "reviewing", "progress": progress,
                            "detail": review.current_step,
                        })

                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error("Smart review error for clause %d: %s", clause["clause_index"], e)
                            result = {
                                "source_module": clause["source_module"],
                                "clause_index": clause["clause_index"],
                                "clause_text": clause["clause_text"],
                                "result": "error", "confidence": 0,
                                "reason": f"智能审查异常: {e}",
                                "severity": clause["severity"], "tender_locations": [],
                            }
                        results_by_index[clause["clause_index"]] = result

                review_items = []
                for item_id, clause in enumerate(all_clauses):
                    result = results_by_index.get(clause["clause_index"], {
                        "source_module": clause["source_module"],
                        "clause_index": clause["clause_index"],
                        "clause_text": clause["clause_text"],
                        "result": "error", "confidence": 0,
                        "reason": "智能审查未返回结果",
                        "severity": clause["severity"], "tender_locations": [],
                    })
                    result["id"] = item_id
                    review_items.append(result)

                # 智能审核完成后清理 tender_folder 释放磁盘空间
                _cleanup_tender_folder(folder_dir)

            else:
                # ── 固定审核模式（原有逻辑）──
                # Step 4: Chapter mapping (12-15%)
                self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 12, "detail": "条款映射"})
                clause_mapping = llm_map_clauses_to_leaf_nodes(clauses, tender_index, api_settings)

                # 构建 image_map: filename → file_path，用于多模态审查
                image_map = {}
                for img in extracted_images:
                    if img.get("path") and img.get("filename"):
                        image_map[img["filename"]] = img["path"]
                if image_map:
                    logger.info("Image map built: %d images available for multimodal review", len(image_map))

                # Step 5-7: 并发审查 (15-95%)
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

                def _review_single_clause(clause: dict) -> dict:
                    """审查单个条款（在线程池中执行）。"""
                    paths = clause_mapping.get(clause["clause_index"], [])
                    if not paths:
                        return _no_match_item(clause)

                    batches = get_text_for_clause(
                        clause["clause_index"], paths, tender_index, paragraphs
                    )
                    if not batches:
                        return _no_match_item(clause)

                    if len(batches) == 1:
                        batch = batches[0]
                        tender_text = paragraphs_to_text(batch.paragraphs)
                        try:
                            result = llm_review_clause(clause, tender_text, project_context, api_settings, image_map=image_map)
                            return map_batch_indices_to_global(result, batch)
                        except Exception as e:
                            logger.error("Clause review failed for %d: %s", clause["clause_index"], e)
                            return {
                                "source_module": clause["source_module"],
                                "clause_index": clause["clause_index"],
                                "clause_text": clause["clause_text"],
                                "result": "error", "confidence": 0,
                                "reason": f"LLM 调用失败: {e}",
                                "severity": clause["severity"], "tender_locations": [],
                            }
                    else:
                        # 顺序累积审查：逐批次传递摘要，末批次综合判定
                        accumulated_summary = ""
                        all_candidates = []

                        for i, batch in enumerate(batches):
                            tender_text = paragraphs_to_text(batch.paragraphs)
                            is_last = (i == len(batches) - 1)

                            if is_last:
                                try:
                                    result = llm_review_clause_final(
                                        clause, tender_text, project_context,
                                        accumulated_summary, all_candidates,
                                        api_settings, image_map=image_map,
                                    )
                                    # 校验末批次 locations 的索引
                                    batch_indices = {p.index for p in batch.paragraphs}
                                    validated_locations = []
                                    for loc in result.get("locations", []):
                                        pi = loc.get("para_index")
                                        if pi is not None and int(pi) in batch_indices:
                                            validated_locations.append(loc)
                                    result["locations"] = validated_locations
                                    return assemble_multi_batch_result(result, all_candidates)
                                except Exception as e:
                                    logger.error("Clause final review failed for %d: %s", clause["clause_index"], e)
                                    return {
                                        "source_module": clause["source_module"],
                                        "clause_index": clause["clause_index"],
                                        "clause_text": clause["clause_text"],
                                        "result": "error", "confidence": 0,
                                        "reason": f"LLM 调用失败: {e}",
                                        "severity": clause["severity"], "tender_locations": [],
                                    }
                            else:
                                try:
                                    intermediate = llm_review_clause_intermediate(
                                        clause, tender_text, project_context,
                                        prev_summary=accumulated_summary,
                                        prev_candidates=all_candidates if all_candidates else None,
                                        api_settings=api_settings,
                                        image_map=image_map,
                                    )
                                    # 校验候选索引是否在当前批次范围内
                                    batch_indices = {p.index for p in batch.paragraphs}
                                    valid_candidates = [
                                        c for c in intermediate.get("candidates", [])
                                        if c.get("para_index") is not None and int(c["para_index"]) in batch_indices
                                    ]
                                    all_candidates.extend(valid_candidates)
                                    accumulated_summary = intermediate.get("summary", accumulated_summary)
                                except Exception as e:
                                    logger.error("Clause intermediate review failed for batch %s: %s", batch.batch_id, e)
                                    # 中间批次失败不致命，继续下一批次
                                    accumulated_summary += f"\n批次{batch.batch_id}审查失败: {e}"

                MAX_WORKERS = 8
                results_by_index: dict[int, dict] = {}
                futures = {}

                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    for clause in all_clauses:
                        future = executor.submit(_review_single_clause, clause)
                        futures[future] = clause

                    completed = 0
                    for future in as_completed(futures):
                        clause = futures[future]
                        completed += 1
                        progress = clause_progress_start + int(
                            (clause_progress_end - clause_progress_start) * completed / max(len(all_clauses), 1)
                        )
                        review.progress = progress
                        review.current_step = f"审查 [{completed}/{len(all_clauses)}]"
                        db.commit()
                        self.update_state(state="PROGRESS", meta={
                            "step": "reviewing", "progress": progress,
                            "detail": review.current_step,
                        })

                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error("Unexpected error reviewing clause %d: %s", clause["clause_index"], e)
                            result = {
                                "source_module": clause["source_module"],
                                "clause_index": clause["clause_index"],
                                "clause_text": clause["clause_text"],
                                "result": "error", "confidence": 0,
                                "reason": f"审查异常: {e}",
                                "severity": clause["severity"], "tender_locations": [],
                            }
                        results_by_index[clause["clause_index"]] = result

                # 按原始顺序组装结果
                review_items = []
                for item_id, clause in enumerate(all_clauses):
                    result = results_by_index.get(clause["clause_index"], _no_match_item(clause))
                    result["id"] = item_id
                    review_items.append(result)

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


def _load_bid_tagged_paragraphs(bid_task) -> list:
    """从招标解读的索引结果中加载 tagged_paragraphs。"""
    import json
    from src.models import TaggedParagraph

    indexed_path = bid_task.indexed_path
    if not indexed_path:
        return []
    try:
        with open(indexed_path, "r", encoding="utf-8") as f:
            indexed_data = json.load(f)
        raw_paragraphs = indexed_data.get("tagged_paragraphs", [])
        return [
            TaggedParagraph(
                index=p["index"],
                text=p["text"],
                section_title=p.get("section_title"),
                section_level=p.get("section_level", 0),
                tags=p.get("tags", []),
                table_data=p.get("table_data"),
            )
            for p in raw_paragraphs
        ]
    except Exception:
        logger.warning("Failed to load bid tagged_paragraphs from %s", indexed_path, exc_info=True)
        return []


def _cleanup_tender_folder(folder_dir: str):
    """审核完成后清理 tender_folder 释放磁盘空间。"""
    import os
    import shutil
    if os.path.isdir(folder_dir):
        try:
            shutil.rmtree(folder_dir)
            logger.info("Cleaned up tender_folder: %s", folder_dir)
        except Exception:
            logger.warning("Failed to clean up tender_folder: %s", folder_dir, exc_info=True)
