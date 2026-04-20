"""暗标审查引擎：格式规则审查 + 内容规则审查。"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from src.extractor.base import call_qwen, build_messages
from src.models import Paragraph, DocumentFormat
from src.reviewer.anbiao_rule_parser import AnbiaoRule

logger = logging.getLogger(__name__)


@dataclass
class ChapterBatch:
    """单个章节审核批次。

    - text: 段落拼接文本（含 [p.index] 前缀）
    - para_indices: 批次包含的全局段落索引
    - chapter_title: 章节标题；兜底模式为 "段落批次 N"
    - image_map: 批次专属 filename→绝对路径 映射
    """
    text: str
    para_indices: list[int]
    chapter_title: str
    image_map: dict[str, str] = field(default_factory=dict)


_FORMAT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_format_review.txt"
_CONTENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review.txt"
_CONTENT_FINAL_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review_final.txt"
_CONTENT_CONCLUDE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review_conclude.txt"


def review_format_rules(
    rules: list[AnbiaoRule],
    doc_format: DocumentFormat,
    paragraphs: list[Paragraph],
    api_settings: dict,
    is_local_mode: bool = False,
) -> list[dict]:
    """逐条格式规则调 LLM 判断。返回 [{rule_index, rule_text, result, reason, details}]。"""
    prompt_template = _FORMAT_PROMPT_PATH.read_text(encoding="utf-8")
    doc_format_text = doc_format.to_prompt_text()
    results = []

    def _review_one(rule: AnbiaoRule) -> dict:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"
        prompt = (
            prompt_template
            .replace("{rule_text}", rule.rule_text)
            .replace("{severity_level}", severity_level)
            .replace("{document_format_text}", doc_format_text)
        )
        messages = build_messages(system="你是暗标格式审查专家。", user=prompt)
        llm_result = call_qwen(messages, api_settings)

        if not isinstance(llm_result, dict):
            return {
                "rule_index": rule.rule_index,
                "rule_text": rule.rule_text,
                "rule_type": "format",
                "result": "error",
                "reason": "LLM 调用失败",
                "details": [],
                "is_mandatory": rule.is_mandatory,
            }

        result_val = llm_result.get("result", "error")
        # 非强制规则：fail 降级为 warning
        if not rule.is_mandatory and result_val == "fail":
            result_val = "warning"

        return {
            "rule_index": rule.rule_index,
            "rule_text": rule.rule_text,
            "rule_type": "format",
            "result": result_val,
            "reason": llm_result.get("reason", ""),
            "details": llm_result.get("details", []),
            "is_mandatory": rule.is_mandatory,
        }

    if is_local_mode:
        for rule in rules:
            results.append(_review_one(rule))
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_review_one, rule): rule for rule in rules}
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda r: r["rule_index"])
    return results


def review_content_rules(
    rules: list[AnbiaoRule],
    paragraphs: list[Paragraph],
    tender_index: dict,
    extracted_images: list[dict],
    doc_format: DocumentFormat,
    api_settings: dict,
    is_local_mode: bool = False,
    image_map: dict[str, str] | None = None,
    progress_callback=None,
) -> list[dict]:
    """内容规则按批次审查。复用 reviewer.py 的三阶段模式。

    Returns list of dicts, one per rule, each with:
      rule_index, rule_text, result, confidence, reason, tender_locations
    """
    from src.reviewer.tender_indexer import paragraphs_to_text, map_batch_indices_to_global
    from src.reviewer.reviewer import _build_multimodal_content, _IMAGE_MARKER_RE, assemble_multi_batch_result

    content_prompt_template = _CONTENT_PROMPT_PATH.read_text(encoding="utf-8")
    content_final_prompt_template = _CONTENT_FINAL_PROMPT_PATH.read_text(encoding="utf-8")

    # 页眉页脚文字也要审查
    hf_text_parts = []
    for section in doc_format.sections:
        for h in section.headers:
            if h.has_text:
                hf_text_parts.append(f"[页眉 Section{section.section_index} {h.hf_type}] {h.text_content}")
        for f in section.footers:
            if f.has_text:
                hf_text_parts.append(f"[页脚 Section{section.section_index} {f.hf_type}] {f.text_content}")
    hf_context = "\n".join(hf_text_parts) if hf_text_parts else ""

    # 分批逻辑：从 tender_index 的 chapters 提取段落范围
    chapters = tender_index.get("chapters", [])
    if not chapters:
        # 无章节时按段落数分批（每批约 50 段）
        batch_size = 50
        batches = []
        for i in range(0, len(paragraphs), batch_size):
            batch_paras = paragraphs[i:i + batch_size]
            batch_text = "\n".join(f"[{p.index}] {p.text}" for p in batch_paras)
            batches.append({"text": batch_text, "para_indices": [p.index for p in batch_paras]})
    else:
        batches = []
        if is_local_mode:
            # 本地模式：每章节一批
            for ch in chapters:
                start = ch.get("start_para", 0)
                end = ch.get("end_para", len(paragraphs) - 1)
                paras_in_node = [p for p in paragraphs if start <= p.index <= end]
                if paras_in_node:
                    batch_text = paragraphs_to_text(paras_in_node)
                    batches.append({"text": batch_text, "para_indices": [p.index for p in paras_in_node]})
        else:
            # 云端模式：多章节合并为一批（控制 token 量）
            from src.extractor.base import estimate_tokens
            current_batch_text = []
            current_batch_indices = []
            for ch in chapters:
                start = ch.get("start_para", 0)
                end = ch.get("end_para", len(paragraphs) - 1)
                paras_in_node = [p for p in paragraphs if start <= p.index <= end]
                if paras_in_node:
                    text = paragraphs_to_text(paras_in_node)
                    current_batch_text.append(text)
                    current_batch_indices.extend([p.index for p in paras_in_node])
                    if estimate_tokens("\n".join(current_batch_text)) > 15000:
                        batches.append({"text": "\n".join(current_batch_text), "para_indices": current_batch_indices})
                        current_batch_text = []
                        current_batch_indices = []
            if current_batch_text:
                batches.append({"text": "\n".join(current_batch_text), "para_indices": current_batch_indices})

    if not batches:
        batches = [{"text": "\n".join(f"[{p.index}] {p.text}" for p in paragraphs), "para_indices": [p.index for p in paragraphs]}]

    # 对每条内容规则，遍历所有批次
    all_results = []
    total_work = len(rules) * len(batches)
    done_work = 0

    for rule in rules:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"
        accumulated_summary = ""
        all_candidates = []

        for bi, batch in enumerate(batches):
            is_final = (bi == len(batches) - 1)
            tender_text = batch["text"]
            if bi == 0 and hf_context:
                tender_text = f"## 页眉页脚内容\n{hf_context}\n\n## 正文内容\n{tender_text}"

            if is_final and len(batches) > 1:
                # 末批次：综合判定
                if all_candidates:
                    cand_lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
                    candidates_text = "\n".join(cand_lines)
                else:
                    candidates_text = "（无前序候选）"

                prompt = (
                    content_final_prompt_template
                    .replace("{rule_text}", rule.rule_text)
                    .replace("{severity_level}", severity_level)
                    .replace("{accumulated_summary}", accumulated_summary or "（首批次，无前序摘要）")
                    .replace("{candidates_text}", candidates_text)
                    .replace("{tender_text}", tender_text)
                )
            else:
                prev_context = ""
                if accumulated_summary:
                    prev_context = f"## 前序批次审查摘要\n{accumulated_summary}\n"
                if all_candidates:
                    lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
                    prev_context += f"\n## 前序批次候选批注\n" + "\n".join(lines)

                prompt = (
                    content_prompt_template
                    .replace("{rule_text}", rule.rule_text)
                    .replace("{severity_level}", severity_level)
                    .replace("{prev_context}", prev_context)
                    .replace("{tender_text}", tender_text)
                )

            # 多模态图片支持
            has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
            if has_images:
                content = _build_multimodal_content(prompt, image_map)
                messages = [
                    {"role": "system", "content": "你是暗标内容审查专家。"},
                    {"role": "user", "content": content},
                ]
            else:
                messages = build_messages(system="你是暗标内容审查专家。", user=prompt)

            llm_result = call_qwen(messages, api_settings)
            done_work += 1
            if progress_callback:
                progress_callback(done_work, total_work)

            if not isinstance(llm_result, dict):
                continue

            if is_final and len(batches) > 1:
                # 末批次最终判定
                result_val = llm_result.get("result", "error")
                if not rule.is_mandatory and result_val == "fail":
                    result_val = "warning"

                final_result = {
                    "source_module": "anbiao",
                    "clause_index": rule.rule_index,
                    "clause_text": rule.rule_text,
                    "rule_type": "content",
                    "result": result_val,
                    "confidence": int(llm_result.get("confidence", 0)),
                    "reason": llm_result.get("reason", ""),
                    "severity": "critical" if rule.is_mandatory else "minor",
                    "is_mandatory": rule.is_mandatory,
                    "locations": llm_result.get("locations", []),
                    "retained_candidates": llm_result.get("retained_candidates", []),
                }
                assembled = assemble_multi_batch_result(final_result, all_candidates)
                all_results.append(assembled)
            elif not is_final:
                # 中间批次：累积候选
                new_candidates = llm_result.get("candidates", [])
                for c in new_candidates:
                    if isinstance(c, dict) and c.get("para_index") is not None:
                        all_candidates.append(c)
                summary = llm_result.get("summary", "")
                if summary:
                    accumulated_summary = f"{accumulated_summary}\n{summary}" if accumulated_summary else summary
            else:
                # 单批次直接判定
                # LLM 可能返回两种格式：
                #   A) result+confidence+reason+locations（标准最终格式）
                #   B) candidates+summary（中间批次格式，某些模型在单批次时也会返回）
                # 对 B 格式需要从 candidates 推导 result/confidence/reason
                result_val = llm_result.get("result", None)
                confidence = llm_result.get("confidence", None)
                reason = llm_result.get("reason", None)

                locations = llm_result.get("locations", [])
                candidates = llm_result.get("candidates", [])

                # 如果 LLM 返回中间批次格式（无 result），从 candidates 推导
                if result_val is None:
                    if candidates:
                        # 有违规候选 → 判定不合规
                        result_val = "fail" if rule.is_mandatory else "warning"
                        # confidence: 有候选但非最终判定，给中等置信度
                        if confidence is None:
                            confidence = 70
                        # reason: 从 candidates 或 summary 拼接
                        if not reason:
                            summary_text = llm_result.get("summary", "")
                            cand_reasons = [c.get("reason", "") for c in candidates if c.get("reason")]
                            reason = summary_text or "、".join(cand_reasons[:3]) or "发现违规内容"
                    else:
                        # 无违规候选 → 判定通过
                        result_val = "pass"
                        if confidence is None:
                            confidence = 80
                        if not reason:
                            reason = "未发现违规内容"

                if not rule.is_mandatory and result_val == "fail":
                    result_val = "warning"

                if not locations and candidates and result_val != "pass":
                    locations = candidates

                tender_locations = []
                if locations:
                    para_indices = [loc["para_index"] for loc in locations if isinstance(loc, dict) and loc.get("para_index") is not None]
                    per_para_reasons = {loc["para_index"]: loc.get("reason", "") for loc in locations if isinstance(loc, dict) and loc.get("para_index") is not None}
                    if para_indices:
                        tender_locations.append({
                            "batch_id": "single_batch",
                            "path": "single",
                            "global_para_indices": para_indices,
                            "text_snippet": locations[0].get("text_snippet", "") if locations else "",
                            "per_para_reasons": per_para_reasons,
                        })

                all_results.append({
                    "source_module": "anbiao",
                    "clause_index": rule.rule_index,
                    "clause_text": rule.rule_text,
                    "rule_type": "content",
                    "result": result_val,
                    "confidence": int(confidence or 0),
                    "reason": reason or "",
                    "severity": "critical" if rule.is_mandatory else "minor",
                    "is_mandatory": rule.is_mandatory,
                    "tender_locations": tender_locations,
                })

    all_results.sort(key=lambda r: r["clause_index"])
    return all_results


def compute_anbiao_summary(format_results: list[dict], content_results: list[dict]) -> dict:
    """计算暗标审查汇总统计。"""
    all_items = format_results + content_results
    total = len(all_items)
    pass_count = sum(1 for r in all_items if r["result"] == "pass")
    fail_count = sum(1 for r in all_items if r["result"] == "fail")
    warning_count = sum(1 for r in all_items if r["result"] == "warning")
    error_count = sum(1 for r in all_items if r["result"] == "error")
    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warning": warning_count,
        "error": error_count,
        "format_total": len(format_results),
        "content_total": len(content_results),
    }