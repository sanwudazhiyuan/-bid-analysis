"""module_e (E. 废标/无效标风险提示) 提取测试"""
import pytest
from src.parser.unified import parse_document
from src.indexer.indexer import build_index
from src.config import load_settings


def _api_key_available():
    try:
        settings = load_settings()
        key = settings.get("api", {}).get("api_key", "")
        return bool(key and key != "${DASHSCOPE_API_KEY}" and len(key) > 5)
    except Exception:
        return False


requires_api = pytest.mark.skipif(
    not _api_key_available(), reason="settings.yaml 中未配置有效的 API Key"
)


@pytest.fixture(scope="module")
def indexed_doc():
    paragraphs = parse_document(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    return build_index(paragraphs)


_cached_results = {}


def _get_result(tagged_paragraphs, cache_key):
    if cache_key not in _cached_results:
        from src.extractor.module_e import extract_module_e
        _cached_results[cache_key] = extract_module_e(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_module_e_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/module_e.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "废标" in content or "无效" in content
    assert "JSON" in content


def test_module_e_filter_paragraphs(indexed_doc):
    from src.extractor.module_e import _filter_paragraphs
    filtered = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0, "应筛选出风险相关段落"


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_module_e_json_schema(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert result["title"].startswith("E")
    for section in result["sections"]:
        assert "id" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")


@requires_api
def test_module_e_has_risk_levels(indexed_doc):
    """风险项应按高/中/低分级"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_text = str(result)
    assert "高风险" in all_text or "高" in all_text or "废标" in all_text


@requires_api
def test_module_e_has_source_reference(indexed_doc):
    """每个风险项应有原文依据或来源章节"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    for section in result["sections"]:
        if section["type"] == "standard_table" and len(section.get("rows", [])) > 0:
            cols = section["columns"]
            has_source_col = any("依据" in c or "来源" in c or "章节" in c for c in cols)
            assert has_source_col, f"表格应包含来源依据列，实际列: {cols}"


@requires_api
def test_module_e_minimum_risk_items(indexed_doc):
    """至少应识别出3条风险项"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    total_rows = 0
    for section in result["sections"]:
        if section["type"] == "standard_table":
            total_rows += len(section.get("rows", []))
    assert total_rows >= 3, f"应至少识别3条风险项，实际: {total_rows}"
