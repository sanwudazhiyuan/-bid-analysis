"""Tests for reviewer: compute_summary, intermediate/final review, assembly."""
from unittest.mock import patch

from src.reviewer.reviewer import compute_summary


def _make_clause(clause_index=1, severity="critical"):
    """Helper to build a test clause dict."""
    return {
        "source_module": "module_a",
        "clause_index": clause_index,
        "clause_text": "同时提供供应商版与芯片厂商版证书",
        "basis_text": "招标文件第3章",
        "severity": severity,
    }


def test_compute_summary():
    items = [
        {"result": "pass", "confidence": 90, "severity": "critical"},
        {"result": "fail", "confidence": 85, "severity": "critical"},
        {"result": "warning", "confidence": 60, "severity": "major"},
        {"result": "pass", "confidence": 95, "severity": "minor"},
    ]
    summary = compute_summary(items)
    assert summary["total"] == 4
    assert summary["pass"] == 2
    assert summary["fail"] == 1
    assert summary["warning"] == 1
    assert summary["critical_fails"] == 1
    assert summary["by_severity"]["critical"]["total"] == 2
    assert summary["by_severity"]["major"]["warning"] == 1
    # avg_confidence is 0-1 scale: (90+85+60+95)/4/100 = 0.825 → round to 0.82
    assert summary["avg_confidence"] == 0.82


# ========== Intermediate Review Tests ==========

@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_review_basic(mock_call):
    """中间批次应返回 candidates + summary，不做最终判定。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版证书"}
        ],
        "summary": "本批次发现供应商版证书（段落42），未见芯片厂商版证书。"
    }
    clause = _make_clause()
    result = llm_review_clause_intermediate(clause, "[42] 供应商版证书...", "某项目")
    assert "candidates" in result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["para_index"] == 42
    assert "summary" in result
    assert "供应商版" in result["summary"]


# ========== Final Review Tests ==========

@patch("src.reviewer.reviewer.call_qwen")
def test_final_review_pass(mock_call):
    """末批次综合判定 pass 时，retained_candidates 为空。"""
    from src.reviewer.reviewer import llm_review_clause_final
    mock_call.return_value = {
        "result": "pass",
        "confidence": 90,
        "reason": "供应商版和芯片厂商版证书均已提供",
        "locations": [],
        "retained_candidates": [],
    }
    clause = _make_clause()
    accumulated_summary = "批次1发现供应商版证书（段落42）。批次2发现芯片厂商版证书（段落1105）。"
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
        {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"},
    ]
    result = llm_review_clause_final(
        clause, "[1200] 其他内容", "某项目",
        accumulated_summary, all_candidates,
    )
    assert result["result"] == "pass"
    assert result["confidence"] == 90
    assert result["retained_candidates"] == []


@patch("src.reviewer.reviewer.call_qwen")
def test_final_review_fail_with_retained(mock_call):
    """末批次综合判定 fail 时，retained_candidates 保留相关前序候选。"""
    from src.reviewer.reviewer import llm_review_clause_final
    mock_call.return_value = {
        "result": "fail",
        "confidence": 85,
        "reason": "仅提供供应商版证书，未见芯片厂商版",
        "locations": [
            {"para_index": 1250, "text_snippet": "此处缺失", "reason": "应包含芯片厂商版证书"}
        ],
        "retained_candidates": [42],
    }
    clause = _make_clause()
    result = llm_review_clause_final(
        clause, "[1200] 其他内容", "某项目",
        "批次1发现供应商版证书（段落42）",
        [{"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}],
    )
    assert result["result"] == "fail"
    assert result["retained_candidates"] == [42]
    assert len(result["locations"]) == 1
    assert result["locations"][0]["para_index"] == 1250


# ========== Assembly Tests ==========

def test_assemble_pass_clears_locations():
    """最终 pass → 清空所有 locations。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "pass",
        "confidence": 90,
        "reason": "全部符合",
        "severity": "critical",
        "locations": [],
        "retained_candidates": [],
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "pass"
    assert result["tender_locations"] == []
    assert "retained_candidates" not in result
    assert "locations" not in result


def test_assemble_fail_retains_candidates():
    """最终 fail → retained_candidates 中的前序候选 + 末批次 locations 保留。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "fail",
        "confidence": 85,
        "reason": "缺失芯片厂商版",
        "severity": "critical",
        "locations": [
            {"para_index": 1250, "text_snippet": "此处缺失", "reason": "缺失证书"}
        ],
        "retained_candidates": [42],
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
        {"para_index": 55, "text_snippet": "无关内容", "reason": "不相关"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "fail"
    all_indices = []
    all_reasons = {}
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
        all_reasons.update(loc.get("per_para_reasons", {}))
    assert 42 in all_indices
    assert 1250 in all_indices
    assert 55 not in all_indices
    assert 42 in all_reasons
    assert 1250 in all_reasons
    assert "retained_candidates" not in result
    assert "locations" not in result


def test_assemble_warning_retains_candidates():
    """最终 warning → 同 fail 逻辑保留 locations。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "warning",
        "confidence": 60,
        "reason": "表述模糊",
        "severity": "major",
        "locations": [
            {"para_index": 80, "text_snippet": "模糊表述", "reason": "表述不清"}
        ],
        "retained_candidates": [30],
    }
    all_candidates = [
        {"para_index": 30, "text_snippet": "相关内容", "reason": "部分符合"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "warning"
    all_indices = []
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 30 in all_indices
    assert 80 in all_indices


def test_assemble_invalid_retained_filtered():
    """retained_candidates 引用不存在的候选索引 → 被过滤。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "fail",
        "confidence": 80,
        "reason": "缺失",
        "severity": "critical",
        "locations": [],
        "retained_candidates": [42, 9999],
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "证书", "reason": "提供了证书"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    all_indices = []
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 42 in all_indices
    assert 9999 not in all_indices


# ========== Intermediate Edge Case Tests ==========

@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_with_prev_context(mock_call):
    """中间批次传入前序摘要和候选时，prompt 中应包含前序信息。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"}
        ],
        "summary": "前序已确认供应商版证书；本批次发现芯片厂商版证书（段落1105）。"
    }
    clause = _make_clause()
    prev_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
    ]
    result = llm_review_clause_intermediate(
        clause, "[1105] 芯片厂商版证书...", "某项目",
        prev_summary="批次1发现供应商版证书（段落42）",
        prev_candidates=prev_candidates,
    )
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["para_index"] == 1105
    # 验证 call_qwen 收到的 prompt 包含前序摘要
    call_args = mock_call.call_args[0][0]  # messages list
    user_content = call_args[1]["content"]
    assert "批次1发现供应商版证书" in user_content
    assert "段落42" in user_content


@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_llm_failure(mock_call):
    """中间批次 LLM 调用失败 → 返回空 candidates 和失败摘要。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = None
    clause = _make_clause()
    result = llm_review_clause_intermediate(clause, "[42] text", "某项目")
    assert result["candidates"] == []
    assert "失败" in result["summary"]


# ========== End-to-End Multi-Batch Tests ==========

@patch("src.reviewer.reviewer.call_qwen")
def test_multi_batch_e2e_pass(mock_call):
    """端到端：3批次累积审查，最终 pass → locations 清空。"""
    from src.reviewer.reviewer import (
        llm_review_clause_intermediate,
        llm_review_clause_final,
        assemble_multi_batch_result,
    )
    clause = _make_clause()

    # Batch 1: intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}
        ],
        "summary": "发现供应商版证书（段落42），未见芯片厂商版。"
    }
    r1 = llm_review_clause_intermediate(clause, "[42] 供应商版证书", "项目A")
    all_candidates = r1["candidates"]
    accumulated_summary = r1["summary"]

    # Batch 2: intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"}
        ],
        "summary": "前序已确认供应商版（段落42）；本批次发现芯片厂商版（段落1105）。"
    }
    r2 = llm_review_clause_intermediate(
        clause, "[1105] 芯片厂商版证书", "项目A",
        prev_summary=accumulated_summary,
        prev_candidates=all_candidates,
    )
    all_candidates.extend(r2["candidates"])
    accumulated_summary = r2["summary"]

    # Batch 3: final
    mock_call.return_value = {
        "result": "pass",
        "confidence": 92,
        "reason": "供应商版和芯片厂商版证书均已在前序批次中确认提供",
        "locations": [],
        "retained_candidates": [],
    }
    r3 = llm_review_clause_final(
        clause, "[1300] 其他内容", "项目A",
        accumulated_summary, all_candidates,
    )

    # Assemble
    final = assemble_multi_batch_result(r3, all_candidates)
    assert final["result"] == "pass"
    assert final["tender_locations"] == []
    assert final["confidence"] == 92


@patch("src.reviewer.reviewer.call_qwen")
def test_multi_batch_e2e_fail(mock_call):
    """端到端：2批次累积审查，最终 fail → 保留相关 locations。"""
    from src.reviewer.reviewer import (
        llm_review_clause_intermediate,
        llm_review_clause_final,
        assemble_multi_batch_result,
    )
    clause = _make_clause()

    # Batch 1: intermediate - 只找到供应商版
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}
        ],
        "summary": "发现供应商版证书（段落42），未见芯片厂商版。"
    }
    r1 = llm_review_clause_intermediate(clause, "[42] 供应商版证书", "项目A")
    all_candidates = r1["candidates"]

    # Batch 2: final - 仍未找到芯片厂商版
    mock_call.return_value = {
        "result": "fail",
        "confidence": 88,
        "reason": "仅提供供应商版证书，未见芯片厂商版证书",
        "locations": [
            {"para_index": 500, "text_snippet": "缺失区域", "reason": "此处应包含芯片厂商版证书"}
        ],
        "retained_candidates": [42],
    }
    r2 = llm_review_clause_final(
        clause, "[500] 其他内容", "项目A",
        r1["summary"], all_candidates,
    )

    # Assemble
    final = assemble_multi_batch_result(r2, all_candidates)
    assert final["result"] == "fail"
    assert final["confidence"] == 88
    all_indices = []
    for loc in final["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 42 in all_indices
    assert 500 in all_indices
