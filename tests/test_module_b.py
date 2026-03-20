"""module_b (B. 投标人资格条件) 提取测试"""
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
        from src.extractor.module_b import extract_module_b
        _cached_results[cache_key] = extract_module_b(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_module_b_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/module_b.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "资格" in content
    assert "JSON" in content


def test_module_b_filter_paragraphs(indexed_doc):
    from src.extractor.module_b import _filter_paragraphs
    filtered = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0, "应筛选出资格条件相关段落"


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_module_b_returns_valid_json(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert "title" in result
    assert result["title"].startswith("B")
    assert "sections" in result
    assert len(result["sections"]) > 0


@requires_api
def test_module_b_sections_have_required_fields(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")


@requires_api
def test_module_b_has_qualification_content(indexed_doc):
    """应包含资格要求相关内容（如营业执照、禁止情形等）"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    all_text = str(result)
    has_qualification = (
        "营业执照" in all_text or "资格" in all_text or
        "法人" in all_text or "资质" in all_text
    )
    assert has_qualification, f"应包含资格相关内容，实际: {all_text[:300]}"


@requires_api
def test_module_b_has_prohibition(indexed_doc):
    """应包含禁止情形相关内容"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    all_text = str(result)
    has_prohibition = (
        "禁止" in all_text or "失信" in all_text or
        "不得" in all_text or "不允许" in all_text or
        "排除" in all_text or "无效" in all_text
    )
    assert has_prohibition, f"应包含禁止情形内容，实际: {all_text[:300]}"
