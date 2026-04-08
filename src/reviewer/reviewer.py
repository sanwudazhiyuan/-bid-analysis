"""LLM-based clause review: single and batch modes."""
import base64
import json
import logging
import re
from pathlib import Path

from src.extractor.base import call_qwen, build_messages

logger = logging.getLogger(__name__)

_CLAUSE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause.txt"
_BATCH_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_batch.txt"
_INTERMEDIATE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause_intermediate.txt"
_FINAL_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause_final.txt"

_IMAGE_MARKER_RE = re.compile(r"\[图片:\s*(.+?)\]")

_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp",
}


def _encode_image_base64(file_path: str) -> str | None:
    """读取图片文件并返回 data URI base64 编码。"""
    try:
        ext = Path(file_path).suffix.lower()
        mime = _MIME_MAP.get(ext, "image/png")
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning("Failed to encode image %s: %s", file_path, e)
        return None


def _build_multimodal_content(prompt: str, image_map: dict[str, str]) -> list[dict]:
    """将 prompt 中的 [图片: filename] 替换为实际的 image_url 内容块。

    返回 OpenAI 多模态 content 数组。
    """
    parts = []
    last_end = 0

    for match in _IMAGE_MARKER_RE.finditer(prompt):
        # 添加标记前的文本
        if match.start() > last_end:
            parts.append({"type": "text", "text": prompt[last_end:match.start()]})

        filename = match.group(1).strip()
        file_path = image_map.get(filename)
        if file_path:
            data_uri = _encode_image_base64(file_path)
            if data_uri:
                parts.append({"type": "image_url", "image_url": {"url": data_uri}})
                last_end = match.end()
                continue

        # 无法加载图片时保留原始标记
        last_end = match.start()

    # 添加剩余文本
    if last_end < len(prompt):
        parts.append({"type": "text", "text": prompt[last_end:]})

    return parts


def llm_review_clause(
    clause: dict,
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    """Review a single clause against tender text. Returns review item dict.

    Args:
        image_map: filename → file_path 映射，用于将 [图片: xxx] 标记
                   替换为实际图片内容发送给多模态 LLM。
    """
    prompt_template = _CLAUSE_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{tender_text}", tender_text)
    )

    # 检测是否有图片需要发送
    has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
    if has_images:
        content = _build_multimodal_content(prompt, image_map)
        messages = [
            {"role": "system", "content": "你是招标文件审查专家。"},
            {"role": "user", "content": content},
        ]
    else:
        messages = build_messages(system="你是招标文件审查专家。", user=prompt)

    result = call_qwen(messages, api_settings)

    if not result:
        return _error_item(clause)

    # call_qwen may return a list (e.g. [{"result": ...}]) — unwrap it
    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], dict) else None
    if not isinstance(result, dict):
        return _error_item(clause)

    # Normalize locations format
    locations = result.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict):
            normalized_locations.append({
                "para_index": loc.get("para_index"),
                "text_snippet": loc.get("text_snippet", ""),
                "reason": loc.get("reason", ""),
            })

    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": result.get("result", "error"),
        "confidence": int(result.get("confidence", 0)),
        "reason": result.get("reason", ""),
        "severity": clause["severity"],
        "tender_locations": _build_tender_locations(normalized_locations, clause),
    }


def llm_review_clause_intermediate(
    clause: dict,
    tender_text: str,
    project_context: str,
    prev_summary: str = "",
    prev_candidates: list[dict] | None = None,
    api_settings: dict | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    """非末批次审查：返回 candidates + summary，不做最终判定。"""
    prompt_template = _INTERMEDIATE_PROMPT_PATH.read_text(encoding="utf-8")

    # 构建前序上下文
    prev_context = ""
    if prev_summary:
        prev_context += f"## 前序批次审查摘要\n{prev_summary}\n"
    if prev_candidates:
        lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in prev_candidates]
        prev_context += f"\n## 前序批次候选批注\n" + "\n".join(lines)

    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{prev_context}", prev_context)
        .replace("{tender_text}", tender_text)
    )

    has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
    if has_images:
        content = _build_multimodal_content(prompt, image_map)
        messages = [
            {"role": "system", "content": "你是招标文件审查专家。"},
            {"role": "user", "content": content},
        ]
    else:
        messages = build_messages(system="你是招标文件审查专家。", user=prompt)

    result = call_qwen(messages, api_settings)

    if not result or not isinstance(result, dict):
        return {"candidates": [], "summary": "LLM 调用失败，无法获取本批次审查结果。"}

    # 规范化 candidates
    raw_candidates = result.get("candidates", [])
    candidates = []
    for c in raw_candidates:
        if isinstance(c, dict) and c.get("para_index") is not None:
            candidates.append({
                "para_index": c["para_index"],
                "text_snippet": c.get("text_snippet", ""),
                "reason": c.get("reason", ""),
            })

    return {
        "candidates": candidates,
        "summary": result.get("summary", ""),
    }


def llm_review_clause_final(
    clause: dict,
    tender_text: str,
    project_context: str,
    accumulated_summary: str,
    all_candidates: list[dict],
    api_settings: dict | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    """末批次审查：综合所有前序发现，做最终判定。

    返回 dict 包含 result/confidence/reason/locations/retained_candidates。
    """
    prompt_template = _FINAL_PROMPT_PATH.read_text(encoding="utf-8")

    # 构建前序候选文本
    if all_candidates:
        lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
        candidates_text = "\n".join(lines)
    else:
        candidates_text = "（无前序候选）"

    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{accumulated_summary}", accumulated_summary or "（首批次，无前序摘要）")
        .replace("{candidates_text}", candidates_text)
        .replace("{tender_text}", tender_text)
    )

    has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
    if has_images:
        content = _build_multimodal_content(prompt, image_map)
        messages = [
            {"role": "system", "content": "你是招标文件审查专家。"},
            {"role": "user", "content": content},
        ]
    else:
        messages = build_messages(system="你是招标文件审查专家。", user=prompt)

    result = call_qwen(messages, api_settings)

    if not result:
        return _error_item(clause)

    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], dict) else None
    if not isinstance(result, dict):
        return _error_item(clause)

    # Normalize locations
    locations = result.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict):
            normalized_locations.append({
                "para_index": loc.get("para_index"),
                "text_snippet": loc.get("text_snippet", ""),
                "reason": loc.get("reason", ""),
            })

    # Normalize retained_candidates to list[int]
    raw_retained = result.get("retained_candidates", [])
    retained = []
    for r in raw_retained:
        try:
            retained.append(int(r))
        except (TypeError, ValueError):
            pass

    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": result.get("result", "error"),
        "confidence": int(result.get("confidence", 0)),
        "reason": result.get("reason", ""),
        "severity": clause["severity"],
        "locations": normalized_locations,
        "retained_candidates": retained,
    }


def assemble_multi_batch_result(
    final_result: dict,
    all_candidates: list[dict],
) -> dict:
    """根据最终 result 组装 tender_locations。

    - pass → tender_locations 清空
    - fail/warning → 保留 retained_candidates 中的前序候选 + 末批次自身 locations
    """
    retained_indices = set(final_result.pop("retained_candidates", []))
    final_locations_raw = final_result.pop("locations", [])

    if final_result["result"] == "pass":
        final_result["tender_locations"] = []
        return final_result

    # 构建候选索引集合（用于过滤无效 retained）
    candidate_index_set = {c["para_index"] for c in all_candidates}

    tender_locations = []

    # 保留的前序候选
    retained_candidates = [
        c for c in all_candidates
        if c["para_index"] in retained_indices and c["para_index"] in candidate_index_set
    ]
    if retained_candidates:
        retained_para_indices = [c["para_index"] for c in retained_candidates]
        retained_reasons = {c["para_index"]: c["reason"] for c in retained_candidates}
        tender_locations.append({
            "batch_id": "retained_candidates",
            "path": "accumulated",
            "global_para_indices": retained_para_indices,
            "text_snippet": retained_candidates[0].get("text_snippet", ""),
            "per_para_reasons": retained_reasons,
        })

    # 末批次自身 locations
    if final_locations_raw:
        final_para_indices = [loc["para_index"] for loc in final_locations_raw if loc.get("para_index") is not None]
        final_reasons = {loc["para_index"]: loc.get("reason", "") for loc in final_locations_raw if loc.get("para_index") is not None}
        if final_para_indices:
            tender_locations.append({
                "batch_id": "final_batch",
                "path": "final",
                "global_para_indices": final_para_indices,
                "text_snippet": final_locations_raw[0].get("text_snippet", ""),
                "per_para_reasons": final_reasons,
            })

    final_result["tender_locations"] = tender_locations
    return final_result


def llm_review_batch(
    clauses: list[dict],
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> list[dict]:
    """[DEPRECATED] Use per-clause llm_review_clause instead.

    Review multiple clauses in one LLM call. Returns list of review items.
    """
    prompt_template = _BATCH_PROMPT_PATH.read_text(encoding="utf-8")
    clauses_json = json.dumps(
        [{"clause_index": c["clause_index"], "clause_text": c["clause_text"],
          "basis_text": c.get("basis_text", ""), "severity": c["severity"]}
         for c in clauses],
        ensure_ascii=False, indent=2,
    )
    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clauses_json}", clauses_json)
        .replace("{tender_text}", tender_text)
    )

    messages = build_messages(system="你是招标文件审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not isinstance(result, list):
        # Fallback: mark all as error
        return [_error_item(c) for c in clauses]

    # Map results by clause_index
    result_map = {r.get("clause_index"): r for r in result if isinstance(r, dict)}
    items = []
    for clause in clauses:
        r = result_map.get(clause["clause_index"])
        if r:
            # Normalize locations (same validation as single-clause path)
            raw_locations = r.get("locations", [])
            locations = [
                {"para_index": loc.get("para_index"), "text_snippet": loc.get("text_snippet", "")}
                for loc in raw_locations if isinstance(loc, dict)
            ]
            items.append({
                "source_module": clause["source_module"],
                "clause_index": clause["clause_index"],
                "clause_text": clause["clause_text"],
                "result": r.get("result", "error"),
                "confidence": int(r.get("confidence", 0)),
                "reason": r.get("reason", ""),
                "severity": clause["severity"],
                "tender_locations": _build_tender_locations(locations, clause),
            })
        else:
            items.append(_error_item(clause))
    return items


def _error_item(clause: dict) -> dict:
    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": "error",
        "confidence": 0,
        "reason": "LLM 调用失败",
        "severity": clause["severity"],
        "tender_locations": [],
    }


def _build_tender_locations(locations: list[dict], clause: dict) -> list[dict]:
    """Build tender_locations from LLM response locations.

    保留每个 para_index 对应的独立 reason，用于逐段批注。
    """
    if not locations:
        return []
    # 构建 para_index → reason 映射
    per_para_reasons = {}
    for loc in locations:
        pi = loc.get("para_index")
        if pi is not None:
            per_para_reasons[pi] = loc.get("reason", "")
    return [{
        "chapter": "",
        "para_indices": [loc["para_index"] for loc in locations if loc.get("para_index") is not None],
        "text_snippet": locations[0].get("text_snippet", "") if locations else "",
        "per_para_reasons": per_para_reasons,
    }]


def compute_summary(review_items: list[dict]) -> dict:
    """Compute review summary statistics."""
    total = len(review_items)
    pass_count = sum(1 for r in review_items if r["result"] == "pass")
    fail_count = sum(1 for r in review_items if r["result"] == "fail")
    warning_count = sum(1 for r in review_items if r["result"] == "warning")
    error_count = sum(1 for r in review_items if r["result"] == "error")
    critical_fails = sum(1 for r in review_items if r["result"] == "fail" and r["severity"] == "critical")
    confidences = [r["confidence"] for r in review_items if r["confidence"] > 0]
    avg_confidence = round(sum(confidences) / len(confidences) / 100, 2) if confidences else 0

    by_severity = {}
    for sev in ("critical", "major", "minor"):
        items = [r for r in review_items if r["severity"] == sev]
        by_severity[sev] = {
            "total": len(items),
            "pass": sum(1 for r in items if r["result"] == "pass"),
            "fail": sum(1 for r in items if r["result"] == "fail"),
            "warning": sum(1 for r in items if r["result"] == "warning"),
        }

    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warning": warning_count,
        "error": error_count,
        "critical_fails": critical_fails,
        "avg_confidence": avg_confidence,
        "by_severity": by_severity,
    }
