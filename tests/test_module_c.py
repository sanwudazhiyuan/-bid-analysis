"""module_c (C. 评标办法与评分标准) 提取测试"""
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
        from src.extractor.module_c import extract_module_c
        _cached_results[cache_key] = extract_module_c(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_module_c_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/module_c.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "评分" in content or "评标" in content
    assert "JSON" in content


def test_module_c_filter_paragraphs(indexed_doc):
    from src.extractor.module_c import _filter_paragraphs
    filtered = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0, "应筛选出评分标准相关段落"


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_module_c_json_schema(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert result["title"].startswith("C")
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")


@requires_api
def test_module_c_has_scoring_breakdown(indexed_doc):
    """评分标准必须包含评分大类"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_text = str(result)
    has_scoring = (
        "报价" in all_text or "价格" in all_text or
        "商务" in all_text or "技术" in all_text or
        "评分" in all_text
    )
    assert has_scoring, f"应包含评分大类信息，实际: {all_text[:300]}"


@requires_api
def test_module_c_has_detail_items(indexed_doc):
    """应提取出多条评分细则，不只是大类"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    total_rows = 0
    for section in result["sections"]:
        if section["type"] in ("standard_table", "key_value_table"):
            total_rows += len(section.get("rows", []))
    assert total_rows >= 5, f"评分细则应至少有5条，实际: {total_rows}"


@requires_api
def test_module_c_price_formula(indexed_doc):
    """如果存在价格评分公式，应完整提取"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_text = str(result)
    has_formula = (
        "基准价" in all_text or "投标报价" in all_text or
        "价格得分" in all_text or "报价得分" in all_text or
        "最低价" in all_text or "公式" in all_text
    )
    assert has_formula, "应提取价格评分公式"
