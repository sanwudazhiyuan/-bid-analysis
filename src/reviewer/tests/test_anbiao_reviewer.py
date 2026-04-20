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


def test_filter_images_for_batch_matches_by_near_para_indices():
    from src.reviewer.anbiao_reviewer import _filter_images_for_batch
    images = [
        {"filename": "a.png", "path": "/tmp/a.png", "near_para_indices": [2, 3]},
        {"filename": "b.png", "path": "/tmp/b.png", "near_para_indices": [10]},
    ]
    result = _filter_images_for_batch([0, 1, 2, 3, 4, 5], images)
    assert result == {"a.png": "/tmp/a.png"}


def test_filter_images_for_batch_falls_back_to_near_para_index():
    """near_para_indices 缺失时使用 near_para_index。"""
    from src.reviewer.anbiao_reviewer import _filter_images_for_batch
    images = [{"filename": "c.png", "path": "/tmp/c.png", "near_para_index": 7}]
    assert _filter_images_for_batch([5, 6, 7], images) == {"c.png": "/tmp/c.png"}
    assert _filter_images_for_batch([0, 1], images) == {}


def test_filter_images_for_batch_skips_images_with_no_indices():
    from src.reviewer.anbiao_reviewer import _filter_images_for_batch
    images = [{"filename": "d.png", "path": "/tmp/d.png"}]
    assert _filter_images_for_batch([0, 1, 2], images) == {}


def test_build_batch_from_node_basic():
    from src.reviewer.anbiao_reviewer import _build_batch_from_node
    paras = _make_paras(["p0", "p1", "p2", "p3"])
    node = {"title": "T", "start_para": 1, "end_para": 2, "children": []}
    images = [{"filename": "x.png", "path": "/tmp/x.png", "near_para_indices": [2]}]
    batch = _build_batch_from_node(node, paras, images, title="章节T")
    assert batch.para_indices == [1, 2]
    assert "[1] p1" in batch.text and "[2] p2" in batch.text
    assert batch.chapter_title == "章节T"
    assert batch.image_map == {"x.png": "/tmp/x.png"}


def test_build_batch_from_node_missing_start_end_uses_all():
    """节点无 start_para/end_para 字段时，fallback 为全量段落。"""
    from src.reviewer.anbiao_reviewer import _build_batch_from_node
    paras = _make_paras(["a", "b"])
    node = {"title": "T", "children": []}
    batch = _build_batch_from_node(node, paras, [], title="T")
    assert batch.para_indices == [0, 1]
