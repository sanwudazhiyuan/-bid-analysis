"""Tests for bid document context extraction for smart review."""
from src.models import TaggedParagraph
from src.reviewer.bid_context import (
    build_bid_chapter_index,
    extract_bid_context_for_clauses,
)


def _make_indexed_data():
    """模拟招标解读 indexed.json 的内容。"""
    return {
        "confidence": 0.85,
        "sections": [
            {"title": "第一章 招标公告", "start": 0, "level": 1},
            {"title": "第二章 投标人须知", "start": 20, "level": 1},
            {"title": "一、投标人资格条件", "start": 21, "level": 2},
            {"title": "二、投标文件编制要求", "start": 40, "level": 2},
            {"title": "第三章 评标办法", "start": 60, "level": 1},
        ],
        "tagged_paragraphs": [
            {"index": i, "text": f"段落{i}的内容", "section_title": None, "section_level": 0, "tags": []}
            for i in range(80)
        ],
    }


def _make_tagged_paragraphs(indexed_data):
    """从 indexed_data 构建 TaggedParagraph 列表。"""
    return [
        TaggedParagraph(
            index=p["index"],
            text=p["text"],
            section_title=p.get("section_title"),
            section_level=p.get("section_level", 0),
            tags=p.get("tags", []),
        )
        for p in indexed_data["tagged_paragraphs"]
    ]


class TestBuildBidChapterIndex:
    """测试从 indexed.json sections 构建 chapters 树。"""

    def test_returns_chapters_tree(self):
        indexed_data = _make_indexed_data()
        result = build_bid_chapter_index(indexed_data)

        assert "chapters" in result
        assert "all_paths" in result
        assert "toc_source" in result
        assert result["toc_source"] == "bid_indexed"

    def test_top_level_chapters(self):
        indexed_data = _make_indexed_data()
        result = build_bid_chapter_index(indexed_data)

        top_titles = [ch["title"] for ch in result["chapters"]]
        assert "第一章 招标公告" in top_titles
        assert "第二章 投标人须知" in top_titles
        assert "第三章 评标办法" in top_titles

    def test_children_nested(self):
        indexed_data = _make_indexed_data()
        result = build_bid_chapter_index(indexed_data)

        ch2 = [ch for ch in result["chapters"] if "投标人须知" in ch["title"]][0]
        child_titles = [c["title"] for c in ch2["children"]]
        assert "一、投标人资格条件" in child_titles
        assert "二、投标文件编制要求" in child_titles

    def test_has_para_ranges(self):
        indexed_data = _make_indexed_data()
        result = build_bid_chapter_index(indexed_data)

        ch1 = result["chapters"][0]
        assert "start_para" in ch1
        assert "end_para" in ch1
        assert ch1["start_para"] == 0

    def test_all_paths_populated(self):
        indexed_data = _make_indexed_data()
        result = build_bid_chapter_index(indexed_data)

        assert len(result["all_paths"]) >= 5  # 3 top + 2 children

    def test_empty_sections(self):
        result = build_bid_chapter_index({"sections": [], "tagged_paragraphs": []})
        assert result["chapters"] == []
        assert result["all_paths"] == []

    def test_no_sections_key(self):
        result = build_bid_chapter_index({"tagged_paragraphs": []})
        assert result["chapters"] == []


class TestExtractBidContextForClauses:
    """测试从招标文件中提取条款相关原文上下文。"""

    def test_extracts_text_for_mapped_clause(self):
        indexed_data = _make_indexed_data()
        tagged_paragraphs = _make_tagged_paragraphs(indexed_data)
        bid_index = build_bid_chapter_index(indexed_data)

        # 模拟条款映射结果：条款 0 映射到第一章
        clause_mapping = {0: [bid_index["chapters"][0]["path"]]}

        contexts = extract_bid_context_for_clauses(
            clause_mapping, bid_index, tagged_paragraphs
        )

        assert 0 in contexts
        assert "段落0的内容" in contexts[0]

    def test_empty_mapping_returns_empty(self):
        indexed_data = _make_indexed_data()
        tagged_paragraphs = _make_tagged_paragraphs(indexed_data)
        bid_index = build_bid_chapter_index(indexed_data)

        contexts = extract_bid_context_for_clauses({}, bid_index, tagged_paragraphs)
        assert contexts == {}

    def test_unmapped_clause_not_in_result(self):
        indexed_data = _make_indexed_data()
        tagged_paragraphs = _make_tagged_paragraphs(indexed_data)
        bid_index = build_bid_chapter_index(indexed_data)

        clause_mapping = {0: [bid_index["chapters"][0]["path"]]}
        contexts = extract_bid_context_for_clauses(
            clause_mapping, bid_index, tagged_paragraphs
        )

        assert 1 not in contexts  # clause 1 was not mapped

    def test_text_contains_paragraph_indices(self):
        """提取的原文应包含 [N] 段落编号标记。"""
        indexed_data = _make_indexed_data()
        tagged_paragraphs = _make_tagged_paragraphs(indexed_data)
        bid_index = build_bid_chapter_index(indexed_data)

        clause_mapping = {0: [bid_index["chapters"][0]["path"]]}
        contexts = extract_bid_context_for_clauses(
            clause_mapping, bid_index, tagged_paragraphs
        )

        assert "[0]" in contexts[0]  # 应包含段落编号
