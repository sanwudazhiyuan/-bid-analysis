"""Tests for clause extraction from extracted_data."""
from dataclasses import dataclass

from src.reviewer.clause_extractor import (
    extract_review_clauses,
    extract_project_context,
    _parse_para_indices,
    _build_enriched_basis,
)


@dataclass
class FakeParagraph:
    index: int
    text: str


class TestParseParaIndices:
    def test_single_index(self):
        assert _parse_para_indices("[57]") == [57]

    def test_multiple_indices(self):
        assert _parse_para_indices("三、采购需求 [57][68]") == [57, 68]

    def test_mixed_text_and_indices(self):
        assert _parse_para_indices("二、资格条件 [30] / 三、采购需求 [83]") == [30, 83]

    def test_no_indices(self):
        assert _parse_para_indices("第三章 评审程序") == []

    def test_empty_string(self):
        assert _parse_para_indices("") == []


class TestBuildEnrichedBasis:
    def test_with_paragraphs(self):
        paragraphs = [
            FakeParagraph(index=56, text="前一段"),
            FakeParagraph(index=57, text="投标时针对提供的样本卡片通过测试要求后为有效标"),
            FakeParagraph(index=68, text="否则视为废标"),
        ]
        result = _build_enriched_basis(
            basis_text="样卡测试需通过",
            source_text="三、采购需求 [57][68]",
            tagged_paragraphs=paragraphs,
        )
        assert "样卡测试需通过" in result
        assert "[57]" in result
        assert "投标时针对提供的样本卡片" in result
        assert "[68]" in result
        assert "否则视为废标" in result

    def test_no_indices_returns_basis_only(self):
        result = _build_enriched_basis("原文依据", "第三章", [])
        assert result == "原文依据"

    def test_missing_paragraph_skipped(self):
        result = _build_enriched_basis("依据", "[999]", [])
        assert result == "依据"


def _make_extracted_data():
    return {
        "schema_version": "1.0",
        "modules": {
            "module_a": {
                "sections": [{
                    "id": "info", "type": "table", "title": "项目基本信息",
                    "columns": ["字段", "内容"],
                    "rows": [
                        ["项目名称", "某银行IC卡采购"],
                        ["预算金额", "100万元"],
                    ],
                }]
            },
            "module_e": {
                "sections": [{
                    "id": "risks", "type": "table", "title": "废标风险",
                    "columns": ["序号", "风险项", "原文依据", "来源章节"],
                    "rows": [
                        ["1", "未按要求密封", "投标文件未密封的作废标处理", "投标须知"],
                        ["2", "未缴纳保证金", "未按时缴纳保证金", "投标须知"],
                    ],
                }]
            },
            "module_b": {
                "sections": [{
                    "id": "quals", "type": "table", "title": "资格条件",
                    "columns": ["序号", "条件", "依据"],
                    "rows": [["1", "具有独立法人资格", "资格要求"]],
                }]
            },
            "module_f": {
                "sections": [{
                    "id": "format", "type": "table", "title": "编制要求",
                    "columns": ["序号", "要求内容", "依据"],
                    "rows": [["1", "投标文件须双面打印", "投标须知"]],
                }]
            },
            "module_c": {
                "sections": [{
                    "id": "scoring", "type": "table", "title": "评分标准",
                    "columns": ["序号", "评分项", "分值"],
                    "rows": [["1", "技术方案", "30"]],
                }]
            },
        },
    }


def test_extract_clauses_module_e():
    """P0 clauses from module_e are extracted with severity=critical."""
    clauses = extract_review_clauses(_make_extracted_data())
    critical = [c for c in clauses if c["severity"] == "critical"]
    assert len(critical) == 2
    assert "未按要求密封" in critical[0]["clause_text"]
    assert critical[0]["source_module"] == "module_e"


def test_extract_clauses_module_b():
    """P1 clauses from module_b are extracted with severity=major."""
    clauses = extract_review_clauses(_make_extracted_data())
    major = [c for c in clauses if c["severity"] == "major"]
    assert len(major) >= 2  # module_b + module_f
    assert any(c["source_module"] == "module_b" for c in major)
    assert any(c["source_module"] == "module_f" for c in major)


def test_extract_clauses_module_c():
    """P2 clauses from module_c are extracted with severity=minor."""
    clauses = extract_review_clauses(_make_extracted_data())
    minor = [c for c in clauses if c["severity"] == "minor"]
    assert len(minor) >= 1
    assert minor[0]["source_module"] == "module_c"


def test_extract_clauses_ordering():
    """Clauses are ordered by priority: critical → major → minor."""
    clauses = extract_review_clauses(_make_extracted_data())
    severities = [c["severity"] for c in clauses]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s])


def test_extract_project_context():
    """Project context is extracted from module_a."""
    ctx = extract_project_context(_make_extracted_data())
    assert "某银行IC卡采购" in ctx
    assert "100万元" in ctx
