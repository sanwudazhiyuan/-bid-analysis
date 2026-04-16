"""module_a (A. 项目基本信息) 提取测试"""
import pytest
from src.parser.unified import parse_document
from src.indexer.indexer import build_index
from src.config import load_settings


def _api_key_available():
    """检查 settings.yaml 中是否配置了有效的 API Key"""
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
    """使用真实招标文件构建索引"""
    paragraphs = parse_document(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    return build_index(paragraphs)


@pytest.fixture(scope="module")
def indexed_announcement():
    """使用招标公告构建索引"""
    paragraphs = parse_document("测试文档/招标公告.docx")
    return build_index(paragraphs)


# 缓存 LLM 调用结果，避免同一 fixture 多次调用 API
_cached_results = {}


def _get_module_a_result(tagged_paragraphs, cache_key):
    """缓存 LLM 结果，同一测试 session 只调用一次"""
    if cache_key not in _cached_results:
        from src.extractor.module_a import extract_module_a

        _cached_results[cache_key] = extract_module_a(tagged_paragraphs)
    return _cached_results[cache_key]


# ========== 不需要 API Key 的测试 ==========


def test_module_a_prompt_exists():
    """module_a prompt 模板文件应存在"""
    from src.extractor.base import load_prompt_template
    from pathlib import Path

    prompt_path = Path("config/prompts/module_a.txt")
    assert prompt_path.exists(), "config/prompts/module_a.txt 不存在"
    content = load_prompt_template(str(prompt_path))
    assert "项目基本信息" in content
    assert "JSON" in content


def test_module_a_filter_paragraphs(indexed_doc):
    """module_a 应能从索引结果中筛选出相关段落"""
    from src.extractor.module_a import _filter_paragraphs

    filtered, score_map = _filter_paragraphs(indexed_doc["tagged_paragraphs"])
    assert len(filtered) > 0, "应筛选出项目信息相关段落"


# ========== 需要 API Key 的测试 ==========


@requires_api
def test_extract_module_a_returns_valid_json(indexed_doc):
    """module_a 应返回合法的结构化 JSON"""
    result = _get_module_a_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None, "extract_module_a 返回 None"
    assert "title" in result
    assert result["title"].startswith("A")
    assert "sections" in result
    assert len(result["sections"]) > 0


@requires_api
def test_module_a_sections_have_required_fields(indexed_doc):
    """每个 section 应包含 id, title, type 字段"""
    result = _get_module_a_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    for section in result["sections"]:
        assert "id" in section, f"section 缺少 id: {section}"
        assert "title" in section, f"section 缺少 title: {section}"
        assert "type" in section, f"section 缺少 type: {section}"
        assert section["type"] in (
            "key_value_table",
            "standard_table",
            "text",
            "parent",
        ), f"未知 type: {section['type']}"


@requires_api
def test_module_a_has_project_name(indexed_doc):
    """应提取到项目名称"""
    result = _get_module_a_result(indexed_doc["tagged_paragraphs"], "ccb")
    assert result is not None
    all_text = str(result)
    assert "建设银行" in all_text or "社保卡" in all_text or "制卡机" in all_text, (
        f"应提取到项目名称相关信息，实际内容: {all_text[:200]}"
    )


@requires_api
def test_module_a_on_announcement(indexed_announcement):
    """对招标公告也应能提取项目信息"""
    result = _get_module_a_result(indexed_announcement["tagged_paragraphs"], "announcement")
    assert result is not None
    assert len(result["sections"]) > 0
    all_text = str(result)
    assert "采购" in all_text, f"招标公告应包含采购相关信息"
