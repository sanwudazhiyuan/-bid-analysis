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


# ========== 新增：精确段落提取 ==========

class TestFindNodeByPath:
    def test_find_root(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": [
            {"path": "/第一章", "title": "第一章", "children": []},
        ]}
        node = find_node_by_path(index, "/第一章")
        assert node is not None
        assert node["title"] == "第一章"

    def test_find_nested(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": [
            {"path": "/第一章", "title": "第一章", "children": [
                {"path": "/第一章/1.1", "title": "1.1", "children": [
                    {"path": "/第一章/1.1/1.1.1", "title": "1.1.1", "children": []},
                ]},
            ]},
        ]}
        node = find_node_by_path(index, "/第一章/1.1/1.1.1")
        assert node is not None
        assert node["title"] == "1.1.1"

    def test_not_found(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": []}
        assert find_node_by_path(index, "/不存在") is None


class TestGetTextForClause:
    def test_single_batch(self):
        from src.reviewer.tender_indexer import get_text_for_clause
        from src.models import Paragraph

        paras = [Paragraph(index=i, text=f"段落{i}") for i in range(10)]
        index = {"chapters": [
            {"path": "/ch1", "title": "ch1", "start_para": 0, "end_para": 9,
             "is_leaf": True, "para_count": 10, "children": []},
        ]}
        batches = get_text_for_clause(0, ["/ch1"], index, paras)
        assert len(batches) == 1
        assert batches[0].batch_id == "/ch1#0"
        assert len(batches[0].paragraphs) == 10

    def test_split_large_leaf(self):
        """超大叶子节点按字符数拆分为多批次。"""
        from src.reviewer.tender_indexer import get_text_for_clause
        from src.models import Paragraph

        # 创建 1500 个段落（超过 LEAF_SPLIT_THRESHOLD=1200），每个 50 字符
        paras = [Paragraph(index=i, text="X" * 50) for i in range(1500)]
        index = {"chapters": [
            {"path": "/big", "title": "big", "start_para": 0, "end_para": 1499,
             "is_leaf": True, "para_count": 1500, "children": []},
        ]}
        batches = get_text_for_clause(0, ["/big"], index, paras)
        assert len(batches) > 1
        assert all(b.batch_id.startswith("/big#") for b in batches)


class TestMapReviewLocation:
    def test_global_index_mapping(self):
        from src.reviewer.tender_indexer import map_review_location, ClauseBatch
        from src.models import Paragraph

        paras = [Paragraph(index=100 + i, text=f"p{i}") for i in range(5)]
        batch = ClauseBatch(clause_index=0, path="/ch1", batch_id="/ch1#0", paragraphs=paras)

        result = map_review_location(batch, {"para_index": 2, "text_snippet": "p2"})
        assert result["global_para_index"] == 102  # 100 + 2
