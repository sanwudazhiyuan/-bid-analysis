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


def test_build_chapter_batches_cloud_mode_50_paras():
    """云端模式：50段落一批次。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras([f"p{i}" for i in range(120)])
    batches = _build_chapter_batches(
        paras, is_local_mode=False, extracted_images=[], image_map=None,
    )
    assert len(batches) == 3  # 120 / 50 = 3 batches (50+50+20)
    assert batches[0].chapter_title == "段落批次 1"
    assert len(batches[0].para_indices) == 50
    assert len(batches[2].para_indices) == 20


def test_build_chapter_batches_local_mode_30_paras():
    """本地模式：30段落一批次。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras([f"p{i}" for i in range(65)])
    batches = _build_chapter_batches(
        paras, is_local_mode=True, extracted_images=[], image_map=None,
    )
    assert len(batches) == 3  # 65 / 30 = 3 batches (30+30+5)
    assert batches[0].chapter_title == "段落批次 1"
    assert len(batches[0].para_indices) == 30
    assert len(batches[2].para_indices) == 5


def test_build_chapter_batches_with_images():
    """图片按段落范围精确分配到对应批次。"""
    from src.reviewer.anbiao_reviewer import _build_chapter_batches
    paras = _make_paras([f"p{i}" for i in range(100)])
    images = [
        {"filename": "a.png", "path": "/tmp/a.png", "near_para_indices": [25]},
        {"filename": "b.png", "path": "/tmp/b.png", "near_para_indices": [75]},
    ]
    batches = _build_chapter_batches(
        paras, is_local_mode=False, extracted_images=images, image_map=None,
    )
    # 段落25在批次1 (0-49), 段落75在批次2 (50-99)
    assert "a.png" in batches[0].image_map
    assert "a.png" not in batches[1].image_map
    assert "b.png" in batches[1].image_map


def test_format_chapter_results_includes_candidates_and_summary():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    chapter_results = [
        {
            "chapter_title": "技术方案",
            "candidates": [
                {"para_index": 3, "text_snippet": "XX公司", "reason": "泄露公司名"},
            ],
            "summary": "发现1处泄露",
        },
        {"chapter_title": "报价", "candidates": [], "summary": ""},
    ]
    text = _format_chapter_results(chapter_results)
    assert "### 章节：技术方案" in text
    assert "段落3" in text and "泄露公司名" in text
    assert "摘要: 发现1处泄露" in text
    assert "### 章节：报价" in text
    assert "（无违规内容）" in text


def test_format_chapter_results_empty():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    assert _format_chapter_results([]) == ""


# ========== 集成测试：review_content_rules 主流程 ==========

from src.models import DocumentFormat
from src.reviewer.anbiao_rule_parser import AnbiaoRule


def _make_rule(idx=1, text="不得出现公司名称", is_mandatory=True):
    return AnbiaoRule(
        rule_index=idx,
        rule_text=text,
        rule_type="content",
        is_mandatory=is_mandatory,
    )


def _empty_doc_format():
    return DocumentFormat(sections=[])


def test_review_content_rules_conclude_does_not_filter_candidates(monkeypatch):
    """conclude 只给总体判定，不再筛选 candidates；所有批次 candidates 全部采纳为 tender_locations。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras(["p0", "p1", "p2"])
    rule = _make_rule()

    call_counter = {"n": 0}

    def fake_call_qwen(messages, api_settings):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            # 批次审核：发现 2 个候选
            return {
                "candidates": [
                    {"para_index": 0, "text_snippet": "Goldpac", "reason": "公司名"},
                    {"para_index": 2, "text_snippet": "logo", "reason": "Logo暴露"},
                ],
                "summary": "2处违规",
            }
        # 综合判定：只返回 result/confidence/reason，不再返回 locations/retained_candidates
        return {"result": "fail", "confidence": 85, "reason": "多处泄露公司信息"}

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule],
        paragraphs=paras,
        tender_index={},
        extracted_images=[],
        doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=True,
    )
    assert results[0]["result"] == "fail"
    assert results[0]["confidence"] == 85
    assert "泄露" in results[0]["reason"]
    # 关键：所有 candidates 全部采纳，不被 conclude 筛选
    locs = results[0]["tender_locations"]
    assert len(locs) == 1
    assert locs[0]["batch_id"] == "all_candidates"
    assert 0 in locs[0]["global_para_indices"]
    assert 2 in locs[0]["global_para_indices"]
    assert locs[0]["per_para_reasons"][0] == "公司名"
    assert locs[0]["per_para_reasons"][2] == "Logo暴露"


def test_review_content_rules_pass_result_empty_tender_locations(monkeypatch):
    """conclude 判定 pass → tender_locations 为空（即使批次有候选）。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras(["p0", "p1"])
    rule = _make_rule()

    call_counter = {"n": 0}

    def fake_call_qwen(messages, api_settings):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return {"candidates": [{"para_index": 0, "text_snippet": "xx", "reason": "疑似"}], "summary": ""}
        return {"result": "pass", "confidence": 90, "reason": "经综合判定无违规"}

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule],
        paragraphs=paras,
        tender_index={},
        extracted_images=[],
        doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=True,
    )
    assert results[0]["result"] == "pass"
    assert results[0]["tender_locations"] == []


def test_review_content_rules_multi_chapter_conclude(monkeypatch):
    """4个段落本地模式只有1个批次，+1次综合判定 = 2次调用。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras(["p0", "p1", "p2", "p3"])
    rule = _make_rule()

    call_log = []

    def fake_call_qwen(messages, api_settings):
        call_log.append(messages)
        call_idx = len(call_log)
        if call_idx == 1:
            return {"candidates": [{"para_index": 0, "text_snippet": "X公司", "reason": "公司名"}], "summary": "1处违规"}
        return {
            "result": "fail",
            "confidence": 90,
            "reason": "段落 0 泄露公司名",
        }

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule],
        paragraphs=paras,
        tender_index={},
        extracted_images=[],
        doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=True,
    )
    assert len(call_log) == 2
    assert len(results) == 1
    assert results[0]["result"] == "fail"
    assert results[0]["tender_locations"]
    assert 0 in results[0]["tender_locations"][0]["global_para_indices"]


def test_review_content_rules_advisory_downgrade(monkeypatch):
    """advisory 规则：综合判定返回 fail 自动降级为 warning。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras(["p0", "p1"])
    tender_index = {"chapters": [
        {"title": "C1", "level": 1, "start_para": 0, "end_para": 1, "children": []},
    ]}
    rule = _make_rule(idx=2, text="不应附图", is_mandatory=False)

    call_counter = {"n": 0}

    def fake_call_qwen(messages, api_settings):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return {"candidates": [], "summary": ""}
        return {"result": "fail", "confidence": 70, "reason": "有图"}

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule],
        paragraphs=paras,
        tender_index=tender_index,
        extracted_images=[],
        doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=True,
    )
    assert results[0]["result"] == "warning"


def test_review_content_rules_conclude_llm_failure_fallback(monkeypatch):
    """综合判定 LLM 失败 + 有候选 → 降级为 fail，置信度 60。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras(["p0"])
    tender_index = {"chapters": [
        {"title": "C1", "level": 1, "start_para": 0, "end_para": 0, "children": []},
    ]}
    rule = _make_rule()

    call_counter = {"n": 0}

    def fake_call_qwen(messages, api_settings):
        call_counter["n"] += 1
        if call_counter["n"] == 1:
            return {"candidates": [{"para_index": 0, "text_snippet": "X", "reason": "r"}], "summary": ""}
        return None

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule], paragraphs=paras, tender_index=tender_index,
        extracted_images=[], doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=True,
    )
    assert results[0]["result"] == "fail"
    assert results[0]["confidence"] == 60
    assert "综合判定 LLM 调用失败" in results[0]["reason"]


def test_review_content_rules_no_chapters_fallback(monkeypatch):
    """无章节索引时走兜底分批。"""
    from src.reviewer import anbiao_reviewer as mod

    paras = _make_paras([f"p{i}" for i in range(10)])
    tender_index = {"chapters": []}
    rule = _make_rule()

    call_log = []

    def fake_call_qwen(messages, api_settings):
        call_log.append(1)
        if len(call_log) == 2:
            return {"result": "pass", "confidence": 90, "reason": "无"}
        return {"candidates": [], "summary": ""}

    monkeypatch.setattr(mod, "call_qwen", fake_call_qwen)

    results = mod.review_content_rules(
        rules=[rule], paragraphs=paras, tender_index=tender_index,
        extracted_images=[], doc_format=_empty_doc_format(),
        api_settings={"api": {"context_length": 32000, "max_output_tokens": 8000}},
        is_local_mode=False,
    )
    assert len(call_log) == 2
    assert results[0]["result"] == "pass"


# ========== 表格内容格式化测试 ==========


def test_paragraphs_to_text_with_table():
    """表格段落展开为完整表格内容。"""
    from src.reviewer.tender_indexer import paragraphs_to_text
    paras = [
        Paragraph(index=0, text="普通段落"),
        Paragraph(index=1, text="表头A | 表头B", is_table=True, table_data=[
            ["表头A", "表头B"],
            ["数据1", "数据2"],
        ]),
        Paragraph(index=2, text="后续段落"),
    ]
    text = paragraphs_to_text(paras)
    assert "[0] 普通段落" in text
    assert "[1] 【表格】" in text
    assert "行0: 表头A | 表头B" in text
    assert "行1: 数据1 | 数据2" in text
    assert "[/1]" in text
    assert "[2] 后续段落" in text


def test_paragraphs_to_text_plain_only():
    """纯文本段落（无表格）正常输出。"""
    from src.reviewer.tender_indexer import paragraphs_to_text
    paras = _make_paras(["a", "b", "c"])
    text = paragraphs_to_text(paras)
    assert text == "[0] a\n[1] b\n[2] c"


def test_paragraphs_to_text_table_without_data():
    """is_table=True 但 table_data=None 时按普通段落输出。"""
    from src.reviewer.tender_indexer import paragraphs_to_text
    paras = [Paragraph(index=0, text="摘要", is_table=True, table_data=None)]
    text = paragraphs_to_text(paras)
    assert text == "[0] 摘要"


# ========== 图片分批次拆分测试 ==========


def test_split_batch_by_image_limit_no_split_needed():
    """图片不超过6张时不拆分。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch, _split_batch_by_image_limit
    img_map = {f"img{i}.png": f"/tmp/img{i}.png" for i in range(4)}
    batch = ChapterBatch(
        text="[0] text\n[1] [图片: img0.png] [图片: img1.png]\n[2] [图片: img2.png]\n[3] [图片: img3.png]",
        para_indices=[0, 1, 2, 3],
        chapter_title="T",
        image_map=img_map,
    )
    result = _split_batch_by_image_limit(batch)
    assert len(result) == 1
    assert result[0] == batch


def test_split_batch_by_image_limit_splits_at_6():
    """8张图片拆为2个子批次：前6 + 后2。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch, _split_batch_by_image_limit
    img_map = {f"img{i}.png": f"/tmp/img{i}.png" for i in range(8)}
    text_lines = [
        "[0] 无图前导",
        "[1] [图片: img0.png] [图片: img1.png] [图片: img2.png]",
        "[2] [图片: img3.png]",
        "[3] [图片: img4.png] [图片: img5.png]",
        "[4] [图片: img6.png]",
        "[5] [图片: img7.png]",
        "[6] 尾部无图",
    ]
    batch = ChapterBatch(
        text="\n".join(text_lines),
        para_indices=[0, 1, 2, 3, 4, 5, 6],
        chapter_title="T",
        image_map=img_map,
    )
    result = _split_batch_by_image_limit(batch)
    assert len(result) == 2
    # 第一个子批次包含 [0]-[3]，有 img0-img5（6张）
    sub1 = result[0]
    assert 0 in sub1.para_indices
    assert 3 in sub1.para_indices
    assert len(sub1.image_map) == 6
    assert "img0.png" in sub1.image_map
    assert "img5.png" in sub1.image_map
    # 第二个子批次包含 [4]-[6]，有 img6-img7（2张）
    sub2 = result[1]
    assert 4 in sub2.para_indices
    assert 6 in sub2.para_indices
    assert len(sub2.image_map) == 2
    assert "img6.png" in sub2.image_map


def test_split_batch_by_image_limit_12_images_3_batches():
    """12张图片拆为3个子批次：6+6。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch, _split_batch_by_image_limit
    img_map = {f"img{i}.png": f"/tmp/img{i}.png" for i in range(12)}
    text_lines = [f"[{i}] [图片: img{i}.png]" for i in range(12)]
    batch = ChapterBatch(
        text="\n".join(text_lines),
        para_indices=list(range(12)),
        chapter_title="T",
        image_map=img_map,
    )
    result = _split_batch_by_image_limit(batch)
    assert len(result) == 2
    assert len(result[0].image_map) == 6
    assert len(result[1].image_map) == 6


def test_split_batch_by_image_limit_preserves_text_order():
    """拆分后每个子批次的文本保持段落顺序。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch, _split_batch_by_image_limit
    img_map = {f"img{i}.png": f"/tmp/img{i}.png" for i in range(8)}
    text_lines = [
        "[0] 前导段落A",
        "[1] 前导段落B",
        "[2] [图片: img0.png]",
        "[3] [图片: img1.png]",
        "[4] [图片: img2.png]",
        "[5] [图片: img3.png]",
        "[6] [图片: img4.png]",
        "[7] [图片: img5.png]",
        "[8] [图片: img6.png]",
        "[9] [图片: img7.png]",
        "[10] 尾部段落",
    ]
    batch = ChapterBatch(
        text="\n".join(text_lines),
        para_indices=list(range(11)),
        chapter_title="T",
        image_map=img_map,
    )
    result = _split_batch_by_image_limit(batch)
    assert len(result) == 2
    # 子批次1：[0]-[7]，含 img0-img5
    assert result[0].text.startswith("[0] 前导段落A")
    assert "[7]" in result[0].text
    assert "[8]" not in result[0].text
    # 子批次2：[8]-[10]，含 img6-img7
    assert result[1].text.startswith("[8]")
    assert "[10] 尾部段落" in result[1].text


def test_format_chapter_results_passes_severity_and_path():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    chapter_results = [{
        "chapter_title": "第一章",
        "candidates": [{
            "para_index": 5,
            "severity": "suspect",
            "identification_path": "从证书编号可反查到公司",
            "reason": "证书编号可识别",
        }],
        "summary": "发现1处可疑",
    }]
    text = _format_chapter_results(chapter_results)
    assert "[suspect]" in text
    assert "从证书编号可反查到公司" in text
    assert "段落5" in text
    assert "证书编号可识别" in text


def test_format_chapter_results_omits_missing_fields_gracefully():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    chapter_results = [{
        "chapter_title": "第二章",
        "candidates": [{"para_index": 3, "reason": "历史记录无新字段"}],
        "summary": "",
    }]
    text = _format_chapter_results(chapter_results)
    assert "段落3" in text
    assert "历史记录无新字段" in text


def test_compute_rule_severity_fail_candidate_is_critical():
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "fail"}, {"severity": "suspect"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "critical"


def test_compute_rule_severity_all_suspect_is_minor():
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "suspect"}, {"severity": "suspect"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "minor"


def test_compute_rule_severity_advisory_capped_at_minor():
    """advisory 规则即使收到 fail 候选也封顶 minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "fail"}]
    assert _compute_rule_severity(candidates, is_mandatory=False) == "minor"


def test_compute_rule_severity_no_candidates_falls_back_to_rule_default():
    """无候选项时按规则默认：mandatory→critical，advisory→minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    assert _compute_rule_severity([], is_mandatory=True) == "critical"
    assert _compute_rule_severity([], is_mandatory=False) == "minor"


def test_compute_rule_severity_legacy_candidates_without_severity_field():
    """历史候选无 severity 字段 → 回退按 is_mandatory。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"para_index": 1, "reason": "old"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "critical"
    assert _compute_rule_severity(candidates, is_mandatory=False) == "minor"
