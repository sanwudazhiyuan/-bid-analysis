"""bid_format (投标文件格式模板) 提取测试"""
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
        from src.extractor.bid_format import extract_bid_format
        _cached_results[cache_key] = extract_bid_format(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_bid_format_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/bid_format.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "投标" in content
    assert "JSON" in content


def test_bid_format_filter_paragraphs(indexed_doc):
    from src.extractor.bid_format import _filter_paragraphs
    filtered, score_map = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_bid_format_json_schema(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert "sections" in result
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section


@requires_api
def test_bid_format_has_key_templates(indexed_doc):
    """应包含投标函、报价表等关键模板"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_titles = [s["title"] for s in result["sections"]]
    all_text = " ".join(all_titles)
    assert "投标函" in all_text or "投标" in all_text, f"应包含投标函模板，实际: {all_titles}"


@requires_api
def test_bid_format_minimum_sections(indexed_doc):
    """至少应提取3个模板部分"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert len(result["sections"]) >= 3, f"应至少有3个模板，实际: {len(result['sections'])}"
