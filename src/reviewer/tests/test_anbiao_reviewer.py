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


def test_build_fallback_batches_splits_by_50():
    from src.reviewer.anbiao_reviewer import _build_fallback_batches
    paras = _make_paras([f"p{i}" for i in range(120)])
    batches = _build_fallback_batches(paras, image_map={"img.png": "/tmp/img.png"}, batch_size=50)
    assert len(batches) == 3
    assert batches[0].chapter_title == "段落批次 1"
    assert batches[1].chapter_title == "段落批次 2"
    assert batches[2].chapter_title == "段落批次 3"
    assert len(batches[0].para_indices) == 50
    assert len(batches[2].para_indices) == 20
    assert batches[0].image_map == {"img.png": "/tmp/img.png"}
    assert batches[2].image_map == {"img.png": "/tmp/img.png"}


def test_build_fallback_batches_none_image_map():
    from src.reviewer.anbiao_reviewer import _build_fallback_batches
    paras = _make_paras(["a", "b"])
    batches = _build_fallback_batches(paras, image_map=None, batch_size=50)
    assert batches[0].image_map == {}


def test_split_chapter_no_children_returns_whole():
    from src.reviewer.anbiao_reviewer import _split_chapter_at_sub_sections
    paras = _make_paras(["p0", "p1"])
    chapter = {"title": "C", "start_para": 0, "end_para": 1, "children": []}
    batches = _split_chapter_at_sub_sections(chapter, paras, [], max_chars=10)
    assert len(batches) == 1
    assert batches[0].chapter_title == "C"


def test_split_chapter_packs_subs_under_max_chars():
    """三个小子章节合并到一批（总字符 < max_chars）。"""
    from src.reviewer.anbiao_reviewer import _split_chapter_at_sub_sections
    paras = _make_paras(["aa", "bb", "cc"])
    chapter = {
        "title": "C", "start_para": 0, "end_para": 2,
        "children": [
            {"title": "S1", "start_para": 0, "end_para": 0},
            {"title": "S2", "start_para": 1, "end_para": 1},
            {"title": "S3", "start_para": 2, "end_para": 2},
        ],
    }
    batches = _split_chapter_at_sub_sections(chapter, paras, [], max_chars=10000)
    assert len(batches) == 1
    assert set(batches[0].para_indices) == {0, 1, 2}
    assert batches[0].chapter_title == "C"


def test_split_chapter_breaks_when_accumulated_exceeds_max():
    """前两个子章节合并后超限 → 先提交前一个，新批次从第二个开始。"""
    from src.reviewer.anbiao_reviewer import _split_chapter_at_sub_sections
    long_text = "x" * 60
    paras = [Paragraph(index=0, text=long_text), Paragraph(index=1, text=long_text)]
    chapter = {
        "title": "C", "start_para": 0, "end_para": 1,
        "children": [
            {"title": "S1", "start_para": 0, "end_para": 0},
            {"title": "S2", "start_para": 1, "end_para": 1},
        ],
    }
    batches = _split_chapter_at_sub_sections(chapter, paras, [], max_chars=100)
    assert len(batches) == 2
    assert batches[0].para_indices == [0]
    assert batches[1].para_indices == [1]


def test_split_chapter_oversized_single_sub_sends_whole():
    """单个子章节超 max_chars → 整体发送（不拆分内部）。"""
    from src.reviewer.anbiao_reviewer import _split_chapter_at_sub_sections
    huge = "y" * 500
    paras = [Paragraph(index=0, text=huge)]
    chapter = {
        "title": "C", "start_para": 0, "end_para": 0,
        "children": [{"title": "Huge", "start_para": 0, "end_para": 0}],
    }
    batches = _split_chapter_at_sub_sections(chapter, paras, [], max_chars=100)
    assert len(batches) == 1
    assert batches[0].para_indices == [0]
    assert batches[0].chapter_title == "C/Huge"


def test_build_chapter_batches_no_chapters_fallback():
    """无 chapters → 走兜底，chapter_title 为 "段落批次 N"。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras([f"p{i}" for i in range(60)])
    tender_index = {"chapters": []}
    api_settings = {"api": {"context_length": 32000, "max_output_tokens": 8000}}
    batches = _build_chapter_batches(
        paras, tender_index, is_local_mode=False,
        api_settings=api_settings, extracted_images=[],
        image_map={"k.png": "/tmp/k.png"},
    )
    assert len(batches) == 2
    assert batches[0].chapter_title.startswith("段落批次")
    assert batches[0].image_map == {"k.png": "/tmp/k.png"}


def test_build_chapter_batches_local_mode_uses_leaves():
    """本地模式：每个叶子节点一批。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras(["p0", "p1", "p2", "p3"])
    tender_index = {"chapters": [
        {"title": "C1", "level": 1, "start_para": 0, "end_para": 3, "children": [
            {"title": "C1.1", "level": 2, "start_para": 0, "end_para": 1, "children": []},
            {"title": "C1.2", "level": 2, "start_para": 2, "end_para": 3, "children": []},
        ]},
    ]}
    api_settings = {"api": {"context_length": 16000, "max_output_tokens": 4000}}
    batches = _build_chapter_batches(
        paras, tender_index, is_local_mode=True,
        api_settings=api_settings, extracted_images=[], image_map=None,
    )
    assert [b.chapter_title for b in batches] == ["C1.1", "C1.2"]
    assert batches[0].para_indices == [0, 1]
    assert batches[1].para_indices == [2, 3]


def test_build_chapter_batches_cloud_mode_one_batch_per_l1():
    """云端模式：未超限时每个一级标题一批（含所有子章节）。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras(["a", "b", "c", "d"])
    tender_index = {"chapters": [
        {"title": "C1", "level": 1, "start_para": 0, "end_para": 1, "children": [
            {"title": "C1.1", "level": 2, "start_para": 0, "end_para": 1, "children": []},
        ]},
        {"title": "C2", "level": 1, "start_para": 2, "end_para": 3, "children": []},
    ]}
    api_settings = {"api": {"context_length": 200000, "max_output_tokens": 4000}}
    batches = _build_chapter_batches(
        paras, tender_index, is_local_mode=False,
        api_settings=api_settings, extracted_images=[], image_map=None,
    )
    assert [b.chapter_title for b in batches] == ["C1", "C2"]


def test_build_chapter_batches_local_skips_empty_leaves():
    """start_para > end_para 或无段落命中的叶子不产出批次。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras(["p0"])
    tender_index = {"chapters": [
        {"title": "Empty", "level": 1, "start_para": 5, "end_para": 10, "children": []},
        {"title": "C", "level": 1, "start_para": 0, "end_para": 0, "children": []},
    ]}
    api_settings = {"api": {"context_length": 16000, "max_output_tokens": 4000}}
    batches = _build_chapter_batches(
        paras, tender_index, is_local_mode=True,
        api_settings=api_settings, extracted_images=[], image_map=None,
    )
    assert [b.chapter_title for b in batches] == ["C"]
