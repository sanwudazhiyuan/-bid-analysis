"""Tests for anbiao chapter-based content review."""
from dataclasses import fields
from src.models import Paragraph


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t) for i, t in enumerate(texts)]


def test_chapter_batch_dataclass_fields():
    """ChapterBatch 应有 text/para_indices/chapter_title/image_map 四个字段。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch
    field_names = {f.name for f in fields(ChapterBatch)}
    assert field_names == {"text", "para_indices", "chapter_title", "image_map"}


def test_collect_leaf_chapters_no_children_is_leaf():
    from src.reviewer.anbiao_reviewer import _collect_leaf_chapters
    chapters = [{"title": "A", "level": 1, "children": []}]
    leaves = _collect_leaf_chapters(chapters, max_level=3)
    assert len(leaves) == 1
    assert leaves[0]["title"] == "A"


def test_collect_leaf_chapters_recurses_to_level_3():
    from src.reviewer.anbiao_reviewer import _collect_leaf_chapters
    chapters = [{
        "title": "L1", "level": 1,
        "children": [{
            "title": "L2", "level": 2,
            "children": [{"title": "L3", "level": 3, "children": []}],
        }],
    }]
    leaves = _collect_leaf_chapters(chapters, max_level=3)
    assert [l["title"] for l in leaves] == ["L3"]


def test_collect_leaf_chapters_stops_at_max_level():
    """level 3 且有 children 时，自身即为叶子（children 不再展开）。"""
    from src.reviewer.anbiao_reviewer import _collect_leaf_chapters
    chapters = [{
        "title": "L3", "level": 3,
        "children": [{"title": "L4", "level": 4, "children": []}],
    }]
    leaves = _collect_leaf_chapters(chapters, max_level=3)
    assert [l["title"] for l in leaves] == ["L3"]
