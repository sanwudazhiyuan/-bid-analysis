"""Test docx format extraction."""
import os
from src.parser.docx_parser import parse_docx, extract_document_format

# 使用项目中已有的投标文件做集成测试
_SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..")
_SAMPLE_CANDIDATES = [
    os.path.join(_SAMPLE_DIR, "投标文档",
                 "响应文件-2025-2026年华师校园卡卡片采购项目-整合版20250311.docx"),
]

def _find_sample():
    for path in _SAMPLE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def test_parse_docx_without_format():
    """extract_format=False 时行为不变，format_info 为 None。"""
    sample = _find_sample()
    if not sample:
        return  # CI 中无样本文件时跳过
    paras = parse_docx(sample, extract_format=False)
    assert len(paras) > 0
    assert all(p.format_info is None for p in paras)


def test_parse_docx_with_format():
    """extract_format=True 时非表格段落都有 format_info。"""
    sample = _find_sample()
    if not sample:
        return
    paras = parse_docx(sample, extract_format=True)
    assert len(paras) > 0
    # 非表格段落应该有 format_info
    text_paras = [p for p in paras if not p.is_table]
    assert len(text_paras) > 0
    assert all(p.format_info is not None for p in text_paras)
    # 至少应该有一些段落检测到了字号
    has_size = any(p.format_info.dominant_size_pt is not None for p in text_paras)
    assert has_size


def test_extract_document_format():
    """提取文档级格式信息。"""
    sample = _find_sample()
    if not sample:
        return
    doc_fmt = extract_document_format(sample)
    assert len(doc_fmt.sections) >= 1
    s0 = doc_fmt.sections[0]
    assert s0.margin_top_cm is not None