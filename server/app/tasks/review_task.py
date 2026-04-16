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
    from src.config import load_settings, load_settings_from_db

    api_settings = load_settings_from_db() or load_settings()
    is_local_mode = "/v1" in (api_settings.get("api", {}).get("base_url", "").lower()) and "dashscope" not in api_settings.get("api", {}).get("base_url", "").lower()

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
            # 按图片在文档中实际出现顺序排列，而非 docx 内部 media 文件名排序
            # 每张图片的 near_para_index 反映其首次出现的段落位置，
            # 同一段落内多张图片按 near_para_index + 在 para_image_map 中的插入顺序排列。
            index_to_pos = {p.index: pos for pos, p in enumerate(paragraphs)}

            # 构建段落→图片有序映射，确保同一段落内图片按文档出现顺序排列
            # 先按 near_para_index（首次出现段落）排序图片，再按 near_para_indices
            # 中的段落索引顺序构建 para→images 映射
            # near_para_index 可能显式为 None（无法定位到段落的图片），排序时用 -1 兜底
            def _sort_key(img):
                indices = img.get("near_para_indices") or []
                first_pi = indices[0] if indices else (img.get("near_para_index") or -1)
                return (first_pi, first_pi)

            sorted_images = sorted(extracted_images, key=_sort_key)

            image_by_para: dict[int, list[str]] = {}
            # image_order_in_para: 记录每张图片在其所属段落内的出现次序，
            # 用于同一段落多图时保持文档原始顺序
            image_para_order: dict[str, int] = {}  # filename → insertion_order
            for order, img in enumerate(sorted_images):
                indices = img.get("near_para_indices")
                if not indices:
                    pi = img.get("near_para_index")
                    indices = [pi] if pi is not None else []
                for pi in indices:
                    image_by_para.setdefault(pi, []).append(img["filename"])
                image_para_order[img["filename"]] = order

            from dataclasses import replace as dc_replace
            for pi, filenames in image_by_para.items():
                # 按 image_para_order 排序，确保同一段落内多图按文档出现顺序排列
                sorted_fns = sorted(filenames, key=lambda fn: image_para_order.get(fn, 0))
                pos = index_to_pos.get(pi)
                if pos is not None:
                    marker = " ".join(f"[图片: {fn}]" for fn in sorted_fns)
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

            # 预提取每个条款对应的招标原文上下文
            # - 智能审核：作为 tender_context 传给 agent 辅助理解条款
            # - 固定审核：作为 bid_reference 追加进 LLM 审查 prompt
            # 两种模式共用 build_clause_bid_contexts helper。
            from src.reviewer.bid_context import build_clause_bid_contexts
            self.update_state(state="PROGRESS", meta={"step": "mapping", "progress": 11, "detail": "条款映射（招标原文）"})
            review.progress = 11
            review.current_step = "条款映射（招标原文）"
            db.commit()

            bid_indexed_data = _load_bid_indexed_data(bid_task)
            # 条款映射使用当前配置的 LLM 模型
            # 云模式: DashScope qwen3.5-flash（快速低成本）
            # 本地模式: 使用 Ollama 当前配置的模型（gemma4:31b 等）
            mapping_settings = api_settings
            clause_bid_contexts = build_clause_bid_contexts(
                all_clauses, bid_indexed_data, bid_tagged_paragraphs, mapping_settings,
            )
            logger.info(
                "条款→招标原文映射: %d/%d 条款获得上下文",
                sum(1 for v in clause_bid_contexts.values() if v), len(all_clauses),
            )

            from concurrent.futures import ThreadPoolExecutor, as_completed

            if review_mode == "smart":
                # ── 智能审核模式：图片预描述 → 构建文件夹 → haha-code 逐条审查 ──
                # 条款→招标原文映射已在上面统一完成（clause_bid_contexts）。
                from src.reviewer.folder_builder import build_tender_folder
                from src.reviewer.image_describer import describe_images
                from src.reviewer.smart_reviewer import call_smart_review

                # Step 4s-1: 图片预描述
                self.update_state(state="PROGRESS", meta={"step": "describing", "progress": 12, "detail": "图片预描述"})
                review.progress = 12
                review.current_step = "图片预描述"
                db.commit()

                import os
                api_key = os.environ.get("DASHSCOPE_API_KEY", "")
                # 本地模式: 用 Ollama 视觉模型; 云模式: 用 DashScope qwen3.5-flash
                vision_base_url = api_settings.get("api", {}).get("base_url") if api_settings.get("api", {}).get("base_url") else None
                vision_model = api_settings.get("api", {}).get("model") if api_settings.get("api", {}).get("model") else None
                image_descriptions = describe_images(
                    api_key, extracted_images,
                    base_url=vision_base_url, model=vision_model,
                ) if extracted_images else {}

                # 按段落分组图片描述和图片文件名
                # 同一张物理图片可能被多个段落引用（如证书同时出现在资格证明和技术部分），
                # 需要将描述/文件名挂到所有引用段落，否则部分章节 MD 会缺失图片。
                # 与固定审核模式一样，先按文档出现顺序排序图片，确保同一段落内多图顺序正确
                sorted_images_smart = sorted(
                    extracted_images, key=_sort_key
                )
                smart_image_order: dict[str, int] = {}  # filename → insertion_order
                # 同时维护 filename→desc 映射，用于按 filename order 排序 desc 列表
                filename_to_desc: dict[str, str] = {}
                for fn, desc in image_descriptions.items():
                    filename_to_desc[fn] = desc

                image_para_map: dict[int, list[str]] = {}
                image_para_files: dict[int, list[str]] = {}
                for order, img in enumerate(sorted_images_smart):
                    indices = img.get("near_para_indices")
                    if not indices:
                        pi = img.get("near_para_index")
                        indices = [pi] if pi is not None else []
                    smart_image_order[img["filename"]] = order
                    desc = image_descriptions.get(img["filename"], "")
                    for pi in indices:
                        if desc:
                            image_para_map.setdefault(pi, []).append(img["filename"])  # 先存 filename 用于排序
                        image_para_files.setdefault(pi, []).append(img["filename"])
                # 同一段落内多图按文档出现顺序排列，然后把 filename 替换为对应的 description
                for pi in image_para_map:
                    image_para_map[pi] = sorted(image_para_map[pi], key=lambda fn: smart_image_order.get(fn, 0))
                    image_para_map[pi] = [filename_to_desc.get(fn, fn) for fn in image_para_map[pi]]
                for pi in image_para_files:
                    image_para_files[pi] = sorted(image_para_files[pi], key=lambda fn: smart_image_order.get(fn, 0))

                logger.info(
                    "图片映射分组: %d 张图片映射到 %d 个段落, image_para_map: %s, image_para_files: %s",
                    len(extracted_images),
                    len(image_para_map),
                    {pi: len(descs) for pi, descs in image_para_map.items()},
                    {pi: len(fns) for pi, fns in image_para_files.items()},
                )

                # Step 4s-3: 构建文件夹结构
                self.update_state(state="PROGRESS", meta={"step": "building", "progress": 13, "detail": "构建文件夹"})
                review.progress = 13
                review.current_step = "构建文件夹结构"
                db.commit()

                folder_dir = os.path.join(os.path.dirname(review.tender_file_path), "tender_folder")
                build_tender_folder(
                    paragraphs, tender_index,
                    image_descriptions, image_para_map, image_para_files,
                    extracted_images, folder_dir,
                )
                logger.info("Tender folder built at %s", folder_dir)

                # Step 5s-7s: 并发智能审查 (15-95%)
                # 首条条款完成前进度不会前进，先显式推一次 reviewing 状态，避免 UI 卡在"构建文件夹"
                self.update_state(state="PROGRESS", meta={
                    "step": "reviewing", "progress": clause_progress_start,
                    "detail": f"智能审查 [0/{len(all_clauses)}]",
                })
                review.progress = clause_progress_start
                review.current_step = f"智能审查 [0/{len(all_clauses)}]"
                db.commit()

                SMART_MAX_WORKERS = 2 if is_local_mode else 4
                results_by_index: dict[int, dict] = {}
                futures = {}

                with ThreadPoolExecutor(max_workers=SMART_MAX_WORKERS) as executor:
                    for clause in all_clauses:
                        tender_context = clause_bid_contexts.get(clause["clause_index"], "")
                        future = executor.submit(call_smart_review, clause, folder_dir, project_context, tender_context)
                        futures[future] = clause

                    completed = 0
                    for future in as_completed(futures):
                        clause = futures[future]
                        completed += 1
                        progress = clause_progress_start + int(
                            (clause_progress_end - clause_progress_start) * completed / max(len(all_clauses), 1)
                        )
                        # 同步更新 Celery 和数据库进度（前端刷新时从 DB 读取）
                        self.update_state(state="PROGRESS", meta={
                            "step": "reviewing", "progress": progress,
                            "detail": f"智能审查 [{completed}/{len(all_clauses)}]",
                        })
                        review.progress = progress
                        review.current_step = f"智能审查 [{completed}/{len(all_clauses)}]"
                        try:
                            db.commit()
                        except Exception as e:
                            logger.warning("Progress commit failed (smart): %s", e)
                            db.rollback()

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

                # 构建全局 image_map: filename → file_path
                global_image_map = {}
                # 构建段落→图片文件名映射（用于条款级别的图片过滤）
                para_to_image_files: dict[int, list[str]] = {}
                for img in extracted_images:
                    if img.get("path") and img.get("filename"):
                        global_image_map[img["filename"]] = img["path"]
                    indices = img.get("near_para_indices")
                    if not indices:
                        pi = img.get("near_para_index")
                        indices = [pi] if pi is not None else []
                    for pi in indices:
                        para_to_image_files.setdefault(pi, []).append(img["filename"])
                if global_image_map:
                    logger.info("Image map built: %d images available for multimodal review", len(global_image_map))

                def _build_clause_image_map(batch_paragraphs: list) -> dict[str, str]:
                    """根据条款映射到的段落，构建只包含相关图片的 image_map。

                    避免将全局所有图片传给 LLM，防止图片顺序混淆（如银联证书图
                    被误判为 EAL4+证书）。只传入条款映射段落中实际出现的图片。
                    """
                    clause_image_map = {}
                    relevant_para_indices = {p.index for p in batch_paragraphs}
                    for pi in relevant_para_indices:
                        for fn in para_to_image_files.get(pi, []):
                            if fn in global_image_map and fn not in clause_image_map:
                                clause_image_map[fn] = global_image_map[fn]
                    # 如果通过段落过滤没有找到任何图片，退回全局 image_map
                    # （可能是因为图片段落索引与条款段落不精确对应）
                    if not clause_image_map and global_image_map:
                        logger.debug(
                            "No images found for clause paragraphs %s, falling back to global image_map",
                            sorted(relevant_para_indices),
                        )
                        clause_image_map = global_image_map
                    return clause_image_map

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

                    bid_reference = clause_bid_contexts.get(clause["clause_index"], "")

                    if len(batches) == 1:
                        batch = batches[0]
                        tender_text = paragraphs_to_text(batch.paragraphs)
                        clause_image_map = _build_clause_image_map(batch.paragraphs)
                        try:
                            result = llm_review_clause(
                                clause, tender_text, project_context, api_settings,
                                image_map=clause_image_map, bid_reference=bid_reference,
                            )
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
                            clause_image_map = _build_clause_image_map(batch.paragraphs)
                            is_last = (i == len(batches) - 1)

                            if is_last:
                                try:
                                    result = llm_review_clause_final(
                                        clause, tender_text, project_context,
                                        accumulated_summary, all_candidates,
                                        api_settings, image_map=clause_image_map,
                                        bid_reference=bid_reference,
                                    )
                                    # 校验末批次 locations 的索引
                                    # LLM 可能返回非整数 para_index（如 '未提供'），需 try/except
                                    batch_indices = {p.index for p in batch.paragraphs}
                                    validated_locations = []
                                    for loc in result.get("locations", []):
                                        pi = loc.get("para_index")
                                        if pi is not None:
                                            try:
                                                pi = int(pi)
                                            except (TypeError, ValueError):
                                                pi = None
                                        if pi is not None and pi in batch_indices:
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
                                        image_map=clause_image_map,
                                        bid_reference=bid_reference,
                                    )
                                    # 校验候选索引是否在当前批次范围内
                                    # LLM 可能返回非整数 para_index，需 try/except
                                    batch_indices = {p.index for p in batch.paragraphs}
                                    valid_candidates = []
                                    for c in intermediate.get("candidates", []):
                                        pi = c.get("para_index")
                                        if pi is not None:
                                            try:
                                                pi = int(pi)
                                            except (TypeError, ValueError):
                                                pi = None
                                        if pi is not None and pi in batch_indices:
                                            valid_candidates.append(c)
                                    all_candidates.extend(valid_candidates)
                                    accumulated_summary = intermediate.get("summary", accumulated_summary)
                                except Exception as e:
                                    logger.error("Clause intermediate review failed for batch %s: %s", batch.batch_id, e)
                                    # 中间批次失败不致命，继续下一批次
                                    accumulated_summary += f"\n批次{batch.batch_id}审查失败: {e}"

                MAX_WORKERS = 2 if is_local_mode else 8
                results_by_index: dict[int, dict] = {}
                futures = {}

                # 首条条款完成前先显式推一次 reviewing 状态
                self.update_state(state="PROGRESS", meta={
                    "step": "reviewing", "progress": clause_progress_start,
                    "detail": f"审查 [0/{len(all_clauses)}]",
                })
                review.progress = clause_progress_start
                review.current_step = f"审查 [0/{len(all_clauses)}]"
                db.commit()

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
                        # 同步更新 Celery 和数据库进度
                        self.update_state(state="PROGRESS", meta={
                            "step": "reviewing", "progress": progress,
                            "detail": f"审查 [{completed}/{len(all_clauses)}]",
                        })
                        review.progress = progress
                        review.current_step = f"审查 [{completed}/{len(all_clauses)}]"
                        try:
                            db.commit()
                        except Exception as e:
                            logger.warning("Progress commit failed: %s", e)
                            db.rollback()

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
                {"filename": img["filename"],
                 "near_para_index": img.get("near_para_index"),
                 "near_para_indices": img.get("near_para_indices") or [],
                 "content_type": img.get("content_type", "")}
                for img in extracted_images
            ]
            summary["pii_masked_count"] = len(pii_mapping)

            # Pre-render preview HTML once to avoid per-request python-docx cost
            try:
                from server.app.services.review_preview import build_preview_html
                tender_html = build_preview_html(
                    review.tender_file_path,
                    review_items,
                    summary["extracted_images"],
                    review_id,
                )
                preview_path = os.path.join(output_dir, "preview.html")
                with open(preview_path, "w", encoding="utf-8") as f:
                    f.write(tender_html)
                summary["preview_html_path"] = preview_path
            except Exception as e:
                logger.warning("Pre-render preview HTML failed: %s", e, exc_info=True)

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
            try:
                db.rollback()
            except Exception:
                pass
            # 重新加载 review 对象，避免 StaleDataError
            db.expire_all()
            try:
                review = db.get(ReviewTask, _uuid.UUID(review_id))
                if review:
                    review.status = "failed"
                    review.error_message = str(e)
                    db.commit()
            except Exception:
                pass
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


def _load_bid_indexed_data(bid_task) -> dict:
    """从招标解读的索引结果中加载完整 indexed.json 数据（含 sections）。"""
    import json

    indexed_path = bid_task.indexed_path
    if not indexed_path:
        return {}
    try:
        with open(indexed_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to load bid indexed data from %s", indexed_path, exc_info=True)
        return {}


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
