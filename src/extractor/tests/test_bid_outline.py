"""测试 bid_outline 四层流水线：合并/合成/绑定/编号/渲染/主入口。"""
from unittest.mock import patch

from src.extractor.bid_outline import _merge_skeleton_batches


# ========== Layer 2 合并 ==========

def test_merge_skeleton_batches_concatenates_lists():
    b1 = {
        "composition_clause": {"found": True,
                                "items": [{"order": 1, "title": "商务文件"}]},
        "scoring_factors": [{"category": "技术", "title": "能力A", "sub_items": []}],
        "material_enumerations": [{"parent": "资质", "items": ["A"]}],
        "format_templates": [{"title": "投标函", "has_sample": True}],
        "dynamic_nodes": [],
    }
    b2 = {
        "composition_clause": {"found": False, "items": []},
        "scoring_factors": [{"category": "商务", "title": "能力B", "sub_items": []}],
        "material_enumerations": [{"parent": "证明", "items": ["B"]}],
        "format_templates": [{"title": "授权书", "has_sample": False}],
        "dynamic_nodes": [{"anchor": "业绩", "expansion_type": "customer_list",
                            "expansion_hint": "按客户展开"}],
    }
    merged = _merge_skeleton_batches([b1, b2])
    assert merged["composition_clause"]["found"] is True
    assert merged["composition_clause"]["items"][0]["title"] == "商务文件"
    assert len(merged["scoring_factors"]) == 2
    assert len(merged["material_enumerations"]) == 2
    assert len(merged["format_templates"]) == 2
    assert len(merged["dynamic_nodes"]) == 1


def test_merge_skeleton_batches_all_empty():
    merged = _merge_skeleton_batches([])
    assert merged["composition_clause"]["found"] is False
    assert merged["composition_clause"]["items"] == []
    assert merged["scoring_factors"] == []
    assert merged["material_enumerations"] == []
    assert merged["format_templates"] == []
    assert merged["dynamic_nodes"] == []


def test_merge_skeleton_batches_ignores_none_entries():
    b1 = {
        "composition_clause": {"found": True, "items": [{"order": 1, "title": "X"}]},
        "scoring_factors": [], "material_enumerations": [],
        "format_templates": [], "dynamic_nodes": [],
    }
    merged = _merge_skeleton_batches([None, b1, None])
    assert merged["composition_clause"]["found"] is True


def test_merge_skeleton_batches_preserves_first_composition_clause_wins():
    """多个批次都说 found=true 时保留第一个批次的 items（幂等，不累加）。"""
    b1 = {
        "composition_clause": {"found": True, "items": [{"order": 1, "title": "A"}]},
        "scoring_factors": [], "material_enumerations": [],
        "format_templates": [], "dynamic_nodes": [],
    }
    b2 = {
        "composition_clause": {"found": True, "items": [{"order": 1, "title": "B"}]},
        "scoring_factors": [], "material_enumerations": [],
        "format_templates": [], "dynamic_nodes": [],
    }
    merged = _merge_skeleton_batches([b1, b2])
    assert merged["composition_clause"]["found"] is True
    assert len(merged["composition_clause"]["items"]) == 1
    assert merged["composition_clause"]["items"][0]["title"] == "A"
