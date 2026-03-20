"""checklist (投标所需资料清单) 提取测试"""
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
        from src.extractor.checklist import extract_checklist
        _cached_results[cache_key] = extract_checklist(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_checklist_prompt_exists():
    from pathlib import Path
    prompt_path = Path("config/prompts/checklist.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    assert "资料" in content or "清单" in content
    assert "JSON" in content


def test_checklist_filter_paragraphs(indexed_doc):
    from src.extractor.checklist import _filter_paragraphs
    filtered = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_checklist_json_schema(indexed_doc):
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    assert "sections" in result
    for section in result["sections"]:
        assert "id" in section
        assert "type" in section
        assert section["type"] in ("standard_table", "key_value_table", "text", "parent")


@requires_api
def test_checklist_has_categories(indexed_doc):
    """至少应有2个资料分类"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert len(result["sections"]) >= 2, f"应至少有2个资料类别，实际: {len(result['sections'])}"


@requires_api
def test_checklist_has_common_materials(indexed_doc):
    """应包含常见的资质材料"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    all_text = str(result)
    assert "营业执照" in all_text, "应包含营业执照"


@requires_api
def test_checklist_minimum_items(indexed_doc):
    """总材料项数应 >= 5"""
    result = _get_result(indexed_doc["tagged_paragraphs"], "ccb")
    total_rows = sum(len(s.get("rows", [])) for s in result["sections"])
    assert total_rows >= 5, f"资料清单应至少有5项，实际: {total_rows}"
