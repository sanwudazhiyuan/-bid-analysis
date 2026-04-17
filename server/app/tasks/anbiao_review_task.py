"""Celery task: run anbiao (anonymous bid) review pipeline."""
import logging
import os
import uuid as _uuid
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="run_anbiao_review")
def run_anbiao_review(self, review_id: str):
    """Anbiao review pipeline: parse rules -> parse tender -> format review -> content review -> generate report."""
    from server.app.models.anbiao_review import AnbiaoReview
    from src.parser.unified import parse_document
    from src.parser.docx_parser import parse_docx, extract_document_format
    from src.reviewer.image_extractor import extract_images
    from src.reviewer.tender_rule_splitter import build_tender_index
    from src.reviewer.anbiao_rule_parser import parse_anbiao_rules, load_default_rules, merge_rules, AnbiaoRule
    from src.reviewer.anbiao_reviewer import review_format_rules, review_content_rules, compute_anbiao_summary
    from src.reviewer.docx_annotator import generate_anbiao_review_docx
    from src.config import load_settings_from_db, load_settings
    from src.reviewer.reviewer import _IMAGE_MARKER_RE
    from src.models import DocumentFormat

    api_settings = load_settings_from_db() or load_settings()
    is_local_mode = "/v1" in (api_settings.get("api", {}).get("base_url", "").lower()) and "dashscope" not in api_settings.get("api", {}).get("base_url", "").lower()

    with Session(_sync_engine) as db:
        review = db.get(AnbiaoReview, _uuid.UUID(review_id))
        if not review:
            return {"error": "Anbiao review task not found"}

        try:
            # Step 1: Parse rules (0-5%)
            review.status = "indexing"
            review.progress = 0
            review.current_step = "解析暗标规则"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_rules", "progress": 0, "detail": "解析暗标规则"})

            project_rules = []
            if review.rule_file_path and os.path.exists(review.rule_file_path):
                project_rules = parse_anbiao_rules(review.rule_file_path, api_settings)

            default_rules = load_default_rules() if review.use_default_rules else []
            if project_rules:
                all_rules = merge_rules(project_rules, default_rules)
            else:
                # 无项目规则时，将通用规则直接转为 AnbiaoRule 列表
                all_rules = [
                    AnbiaoRule(
                        rule_index=i, rule_text=r["rule_text"], rule_type=r["rule_type"],
                        source_section="通用规则", is_mandatory=r.get("is_mandatory", True),
                        category=r.get("category", ""),
                    ) for i, r in enumerate(default_rules)
                ]

            review.parsed_rules = [r.to_dict() for r in all_rules]
            review.progress = 5
            db.commit()
            logger.info("暗标规则解析完成: %d 条规则", len(all_rules))

            format_rules = [r for r in all_rules if r.rule_type == "format"]
            content_rules = [r for r in all_rules if r.rule_type == "content"]

            # Step 2: Parse tender document (5-15%)
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 5, "detail": "解析标书文档"})
            review.current_step = "解析标书文档"
            db.commit()

            file_ext = os.path.splitext(review.tender_file_path)[1].lower()
            if file_ext in (".docx",):
                paragraphs = parse_docx(review.tender_file_path, extract_format=True)
                doc_format = extract_document_format(review.tender_file_path)
            else:
                paragraphs = parse_document(review.tender_file_path)
                doc_format = DocumentFormat()

            # Extract images
            review.progress = 8
            review.current_step = "提取图片"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 8, "detail": "提取图片"})

            images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
            extracted_images = extract_images(review.tender_file_path, images_dir)

            # Build index
            review.progress = 10
            review.current_step = "构建索引"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 10, "detail": "构建索引"})

            tender_index = build_tender_index(paragraphs, api_settings)

            # Inject image markers
            from dataclasses import replace as dc_replace
            index_to_pos = {p.index: pos for pos, p in enumerate(paragraphs)}
            image_by_para = {}
            for img in extracted_images:
                indices = img.get("near_para_indices") or ([img.get("near_para_index")] if img.get("near_para_index") is not None else [])
                for pi in indices:
                    image_by_para.setdefault(pi, []).append(img["filename"])

            for pi, filenames in image_by_para.items():
                pos = index_to_pos.get(pi)
                if pos is not None:
                    marker = " ".join(f"[图片: {fn}]" for fn in filenames)
                    paragraphs[pos] = dc_replace(paragraphs[pos], text=paragraphs[pos].text + f" {marker}")

            # Build image map for multimodal
            image_map = {}
            for img in extracted_images:
                image_map[img["filename"]] = os.path.join(images_dir, img["filename"])

            # Build format summary
            if paragraphs and paragraphs[0].format_info is not None:
                from src.models import FormatSummary
                from collections import Counter

                heading_stats = {}
                body_fonts = []
                body_sizes = []
                non_black = []

                for p in paragraphs:
                    fi = p.format_info
                    if fi is None:
                        continue
                    if fi.heading_level is not None:
                        lvl = fi.heading_level
                        if lvl not in heading_stats:
                            heading_stats[lvl] = {"count": 0, "font": fi.dominant_font, "size_pt": fi.dominant_size_pt, "bold": any(r.bold for r in fi.runs if r.bold), "anomalies": []}
                        heading_stats[lvl]["count"] += 1
                    else:
                        if fi.dominant_font:
                            body_fonts.append(fi.dominant_font)
                        if fi.dominant_size_pt:
                            body_sizes.append(fi.dominant_size_pt)
                    if fi.has_non_black_text:
                        non_black.append({"para_index": p.index, "color": fi.dominant_color, "text_snippet": p.text[:30]})

                font_dist = {}
                if body_fonts:
                    total_f = len(body_fonts)
                    for font, count in Counter(body_fonts).most_common():
                        font_dist[font] = round(count / total_f * 100)
                size_dist = {}
                if body_sizes:
                    total_s = len(body_sizes)
                    for size, count in Counter(body_sizes).most_common():
                        size_dist[str(size)] = round(count / total_s * 100)

                doc_format.format_summary = FormatSummary(
                    heading_stats=heading_stats,
                    body_stats={"font_distribution": font_dist, "size_distribution": size_dist},
                    non_black_paragraphs=non_black,
                )

            review.progress = 15
            db.commit()

            # Step 3: Format review (15-40%)
            self.update_state(state="PROGRESS", meta={"step": "format_review", "progress": 15, "detail": f"格式审查（{len(format_rules)}条规则）"})
            review.status = "reviewing"
            review.current_step = "格式审查"
            db.commit()

            format_results = review_format_rules(format_rules, doc_format, paragraphs, api_settings, is_local_mode) if format_rules else []

            review.format_results = format_results
            review.progress = 40
            db.commit()

            # Step 4: Content review (40-90%)
            self.update_state(state="PROGRESS", meta={"step": "content_review", "progress": 40, "detail": f"内容审查（{len(content_rules)}条规则）"})
            review.current_step = "内容审查"
            db.commit()

            def _content_progress(done, total):
                p = 40 + int(50 * done / max(total, 1))
                review.progress = min(p, 90)
                db.commit()
                self.update_state(state="PROGRESS", meta={"step": "content_review", "progress": review.progress, "detail": f"内容审查 ({done}/{total})"})

            content_results = review_content_rules(
                content_rules, paragraphs, tender_index, extracted_images,
                doc_format, api_settings, is_local_mode, image_map, _content_progress,
            ) if content_rules else []

            review.content_results = content_results
            review.progress = 90
            db.commit()

            # Step 5: Generate report (90-100%)
            self.update_state(state="PROGRESS", meta={"step": "generating", "progress": 90, "detail": "生成审查报告"})
            review.current_step = "生成报告"
            db.commit()

            summary = compute_anbiao_summary(format_results, content_results)
            summary["extracted_images"] = extracted_images

            # Generate annotated docx
            output_dir = os.path.dirname(review.tender_file_path)
            annotated_path = generate_anbiao_review_docx(
                review.tender_file_path,
                format_results, content_results, summary,
                rule_filename=review.rule_file_name or "通用规则",
                tender_filename=review.tender_file_name,
                output_dir=output_dir,
            )
            review.annotated_file_path = annotated_path

            # Generate preview HTML
            from server.app.services.review_preview import build_preview_html
            preview_html = build_preview_html(
                review.tender_file_path, content_results, extracted_images, review_id,
            )
            preview_path = os.path.join(output_dir, "preview.html")
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(preview_html)
            summary["preview_html_path"] = preview_path

            review.review_summary = summary
            review.status = "completed"
            review.progress = 100
            review.completed_at = datetime.datetime.now()
            db.commit()

            self.update_state(state="PROGRESS", meta={"step": "completed", "progress": 100})
            logger.info("暗标审查完成: %s", review_id)
            return {"status": "completed", "review_id": review_id}

        except Exception as e:
            logger.exception("暗标审查失败: %s", review_id)
            review.status = "failed"
            review.error_message = str(e)[:2000]
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "failed", "progress": 0, "error": str(e)[:500]})
            return {"error": str(e)}