"""module_f (F. 投标文件编制要求) 提取测试"""
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
        from src.extractor.module_f import extract_module_f
        _cached_results[cache_key] = extract_module_f(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_module_f_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/module_f.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "投标文件" in content
    assert "JSON" in content


def test_module_f_filter_paragraphs(indexed_doc):
    from src.extractor.module_f import _filter_paragraphs
    filtered = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_module_f_returns_valid_json(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert result["title"].startswith("F")
    assert "sections" in result
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section


@requires_api
def test_module_f_has_file_composition(indexed_doc):
    """应包含文件组成、份数、密封等要求"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_text = str(result)
    has_content = (
        "份" in all_text or "密封" in all_text or
        "装订" in all_text or "正本" in all_text or
        "投标文件" in all_text or "组成" in all_text
    )
    assert has_content, f"应包含投标文件编制要求，实际: {all_text[:300]}"
