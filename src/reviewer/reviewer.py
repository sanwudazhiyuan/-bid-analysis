"""LLM-based clause review: single and batch modes."""
import json
import logging
from pathlib import Path

from src.extractor.base import call_qwen, build_messages

logger = logging.getLogger(__name__)

_CLAUSE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause.txt"
_BATCH_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_batch.txt"


def llm_review_clause(
    clause: dict,
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> dict:
    """Review a single clause against tender text. Returns review item dict."""
    prompt_template = _CLAUSE_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{tender_text}", tender_text)
    )

    messages = build_messages(system="你是招标文件审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not result:
        return _error_item(clause)

    # Normalize locations format
    locations = result.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict):
            normalized_locations.append({
                "para_index": loc.get("para_index"),
                "text_snippet": loc.get("text_snippet", ""),
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


def llm_review_batch(
    clauses: list[dict],
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> list[dict]:
    """Review multiple clauses in one LLM call. Returns list of review items."""
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
    """Build tender_locations from LLM response locations."""
    if not locations:
        return []
    return [{
        "chapter": "",
        "para_indices": [loc["para_index"] for loc in locations if loc.get("para_index") is not None],
        "text_snippet": locations[0].get("text_snippet", "") if locations else "",
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
