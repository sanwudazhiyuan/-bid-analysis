"""HTTP 客户端：调用 haha-code 智能审核服务。"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

HAHA_CODE_URL = os.environ.get("HAHA_CODE_URL", "http://haha-code:3000")
REVIEW_TIMEOUT = int(os.environ.get("SMART_REVIEW_TIMEOUT", "900"))  # 15 min
SMART_REVIEW_RETRIES = int(os.environ.get("SMART_REVIEW_RETRIES", "2"))


def call_smart_review(
    clause: dict,
    folder_path: str,
    project_context: str,
    tender_context: str = "",
) -> dict:
    """调用 haha-code 智能审核服务审查单个条款。

    Args:
        clause: 条款信息
        folder_path: 投标文件文件夹路径
        project_context: 项目背景
        tender_context: 预提取的相关原文（可为空，为空时 agent 自行搜索）

    返回格式与 llm_review_clause 一致的 review item dict。
    失败时自动重试，指数退避。
    """
    url = f"{HAHA_CODE_URL}/review"
    payload = {
        "clause": {
            "clause_index": clause["clause_index"],
            "clause_text": clause.get("clause_text", ""),
            "basis_text": clause.get("basis_text", ""),
            "severity": clause.get("severity", "minor"),
            "source_module": clause.get("source_module", ""),
        },
        "folder_path": folder_path,
        "project_context": project_context,
        "tender_context": tender_context,
    }

    last_error = None
    for attempt in range(SMART_REVIEW_RETRIES + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=REVIEW_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # 如果是 error 结果，检查是否可恢复（recoverable），不可恢复的直接返回
            if data.get("result") != "error" or attempt == SMART_REVIEW_RETRIES:
                return _normalize_result(data, clause)
            # 如果明确标记为不可恢复，不再重试
            if data.get("recoverable") is False:
                reason = data.get("reason", "未知错误")
                logger.warning("Smart review error (non-recoverable) for clause %d: %s", clause["clause_index"], reason)
                return _error_item(clause, reason)
            last_error = data.get("reason", "未知错误")
        except httpx.TimeoutException:
            last_error = "智能审核超时"
            logger.warning("Smart review timeout for clause %d (attempt %d)", clause["clause_index"], attempt + 1)
        except httpx.ConnectError:
            last_error = f"无法连接到智能审核服务 ({HAHA_CODE_URL})"
            logger.error("Smart review connection failed: %s", HAHA_CODE_URL)
            # 连接错误不重试，直接返回
            return _error_item(clause, last_error)
        except Exception as e:
            last_error = f"智能审核调用失败: {e}"
            logger.warning("Smart review error (attempt %d): %s", attempt + 1, e)

        if attempt < SMART_REVIEW_RETRIES:
            wait = 5 * (2 ** attempt)  # 5s, 10s
            logger.info("Retrying smart review for clause %d in %ds... reason: %s", clause["clause_index"], wait, last_error)
            time.sleep(wait)

    return _error_item(clause, f"智能审核失败（已重试{SMART_REVIEW_RETRIES}次）: {last_error}")


def _normalize_result(data: dict, clause: dict) -> dict:
    """将 haha-code 返回的结果规范化为 review item 格式。"""
    locations = data.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict) and loc.get("para_index") is not None:
            normalized_locations.append({
                "para_index": loc["para_index"],
                "text_snippet": loc.get("text_snippet", ""),
                "reason": loc.get("reason", ""),
            })

    tender_locations = []
    if normalized_locations:
        per_para_reasons = {loc["para_index"]: loc.get("reason", "") for loc in normalized_locations}
        tender_locations.append({
            "chapter": "",
            "para_indices": [loc["para_index"] for loc in normalized_locations],
            "text_snippet": normalized_locations[0].get("text_snippet", ""),
            "per_para_reasons": per_para_reasons,
        })

    return {
        "source_module": clause.get("source_module", ""),
        "clause_index": clause["clause_index"],
        "clause_text": clause.get("clause_text", ""),
        "result": data.get("result", "error"),
        "confidence": int(data.get("confidence", 0)),
        "reason": data.get("reason", ""),
        "severity": clause.get("severity", "minor"),
        "tender_locations": tender_locations,
    }


def _error_item(clause: dict, reason: str) -> dict:
    return {
        "source_module": clause.get("source_module", ""),
        "clause_index": clause["clause_index"],
        "clause_text": clause.get("clause_text", ""),
        "result": "error",
        "confidence": 0,
        "reason": reason,
        "severity": clause.get("severity", "minor"),
        "tender_locations": [],
    }
