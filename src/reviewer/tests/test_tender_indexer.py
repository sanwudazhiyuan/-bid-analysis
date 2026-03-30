"""Tests for tender document indexing."""
from src.models import Paragraph
from src.reviewer.tender_indexer import build_index_from_toc, get_chapter_text


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t) for i, t in enumerate(texts)]


def test_build_index_basic():
    """TOC entries are matched to paragraphs by fuzzy title matching."""
    paras = _make_paras([
        "第一章 投标函",
        "致采购人：...",
        "我方承诺...",
        "第二章 技术方案",
        "2.1 系统架构",
        "本系统采用...",
        "2.2 实施计划",
        "按照以下步骤...",
        "第三章 商务报价",
        "报价明细如下...",
    ])
    toc = [
        {"title": "第一章 投标函", "level": 1, "page_hint": None},
        {"title": "第二章 技术方案", "level": 1, "page_hint": None},
        {"title": "第三章 商务报价", "level": 1, "page_hint": None},
    ]
    index = build_index_from_toc(toc, paras)
    assert len(index["chapters"]) == 3
    assert index["chapters"][0]["start_para"] == 0
    assert index["chapters"][0]["end_para"] == 2
    assert index["chapters"][1]["start_para"] == 3
    assert index["chapters"][2]["start_para"] == 8


def test_get_chapter_text():
    """get_chapter_text returns text for specified chapters."""
    paras = _make_paras(["章节标题", "段落A", "段落B", "另一章", "段落C"])
    index = {
        "chapters": [
            {"title": "第一章", "level": 1, "start_para": 0, "end_para": 2, "children": []},
            {"title": "第二章", "level": 1, "start_para": 3, "end_para": 4, "children": []},
        ]
    }
    text = get_chapter_text(paras, index, ["第一章"])
    assert "段落A" in text
    assert "段落B" in text
    assert "段落C" not in text
