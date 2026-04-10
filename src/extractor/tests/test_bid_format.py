"""Tests for bid_format two-pass logic and module summarization."""
from unittest.mock import patch

from src.extractor.bid_format import _summarize_modules
from src.models import TaggedParagraph


def _make_tagged(index, text, section_title="投标文件格式"):
    return TaggedParagraph(index=index, text=text, section_title=section_title, tags=["格式"])


# ========== _summarize_modules Tests ==========

def test_summarize_modules_basic():
    """正常模块结果应提取标题和 section 列表。"""
    modules = {
        "module_a": {
            "title": "基本信息",
            "sections": [
                {"title": "项目概述", "content": "xxx"},
                {"title": "采购需求", "content": "yyy"},
            ],
        },
        "module_b": {
            "title": "资质要求",
            "sections": [
                {"title": "营业执照", "items": ["xxx"]},
            ],
        },
    }
    result = _summarize_modules(modules)
    assert "基本信息" in result
    assert "项目概述" in result
    assert "采购需求" in result
    assert "资质要求" in result
    assert "营业执照" in result


def test_summarize_modules_skips_none():
    """None 的模块应被跳过。"""
    modules = {
        "module_a": None,
        "module_b": {"title": "资质要求", "sections": []},
    }
    result = _summarize_modules(modules)
    assert "module_a" not in result
    assert "资质要求" in result


def test_summarize_modules_skips_bid_format_and_checklist():
    """bid_format 和 checklist 应被排除。"""
    modules = {
        "bid_format": {"title": "投标文件格式", "sections": []},
        "checklist": {"title": "检查清单", "sections": []},
        "module_a": {"title": "基本信息", "sections": []},
    }
    result = _summarize_modules(modules)
    assert "投标文件格式" not in result
    assert "检查清单" not in result
    assert "基本信息" in result


def test_summarize_modules_empty():
    """所有模块为 None 时返回空字符串。"""
    modules = {"module_a": None, "module_b": None}
    result = _summarize_modules(modules)
    assert result == ""


# ========== Two-pass extract_bid_format Tests ==========

@patch("src.extractor.bid_format.call_qwen")
def test_first_pass_has_template(mock_call):
    """第一次调用发现有格式样例 → 直接返回结果，不调用第二次。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.return_value = {
        "title": "投标文件格式",
        "sections": [{"id": "BF1", "title": "投标函", "type": "text", "content": "致：..."}],
    }
    paras = [_make_tagged(0, "投标函格式：致：采购人")]
    result = extract_bid_format(paras, modules_context={"module_a": {"title": "基本信息", "sections": []}})
    assert result is not None
    assert result["title"] == "投标文件格式"
    assert len(result["sections"]) == 1
    assert mock_call.call_count == 1


@patch("src.extractor.bid_format.call_qwen")
def test_first_pass_no_template_triggers_fallback(mock_call):
    """第一次调用无格式样例 → 触发第二次调用。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},
        {
            "title": "投标文件格式",
            "sections": [{"id": "BF1", "title": "法定代表人身份证明书", "type": "text", "content": "兹证明..."}],
        },
    ]
    paras = [_make_tagged(0, "投标文件应包含投标函")]
    modules = {
        "module_a": {"title": "基本信息", "sections": [{"title": "项目概述"}]},
        "module_b": {"title": "资质要求", "sections": [{"title": "营业执照"}]},
    }
    result = extract_bid_format(paras, modules_context=modules)
    assert result is not None
    assert result["sections"][0]["title"] == "法定代表人身份证明书"
    assert mock_call.call_count == 2


@patch("src.extractor.bid_format.call_qwen")
def test_fallback_without_modules_context(mock_call):
    """无 modules_context 且无模板 → fallback 仍然调用但 modules_summary 为空。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},
        {"title": "投标文件格式", "sections": [{"id": "BF1", "title": "投标函", "type": "text", "content": "..."}]},
    ]
    paras = [_make_tagged(0, "投标文件应包含投标函")]
    result = extract_bid_format(paras, modules_context=None)
    assert result is not None
    assert mock_call.call_count == 2


@patch("src.extractor.bid_format.call_qwen")
def test_both_passes_fail(mock_call):
    """两次 LLM 都失败 → 返回 None。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},
        None,
    ]
    paras = [_make_tagged(0, "投标文件格式")]
    result = extract_bid_format(paras, modules_context={})
    assert result is None
