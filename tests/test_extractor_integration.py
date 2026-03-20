"""提取层集成测试 — extract_all 统一入口"""
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


# 缓存 extract_all 结果，避免重复调用 9 个模块
_cached_extract_all = {}


def _get_extract_all(tagged_paragraphs, cache_key="ccb"):
    if cache_key not in _cached_extract_all:
        from src.extractor.extractor import extract_all
        _cached_extract_all[cache_key] = extract_all(tagged_paragraphs)
    return _cached_extract_all[cache_key]


# ========== 不需要 API 的测试 ==========


def test_extract_all_importable():
    """extract_all 应可导入"""
    from src.extractor.extractor import extract_all
    assert callable(extract_all)


def test_extract_all_returns_schema():
    """extract_all 返回结构应包含 schema_version 和 modules"""
    from src.extractor.extractor import extract_all
    import inspect
    sig = inspect.signature(extract_all)
    assert "tagged_paragraphs" in sig.parameters


# ========== 需要 API 的集成测试 ==========


@requires_api
def test_extract_all_modules(indexed_doc):
    """全模块提取应返回所有 9 个模块结果"""
    result = _get_extract_all(indexed_doc["tagged_paragraphs"])

    assert "schema_version" in result
    assert "modules" in result

    expected_keys = [
        "module_a", "module_b", "module_c", "module_d",
        "module_e", "module_f", "module_g", "bid_format", "checklist",
    ]
    for key in expected_keys:
        assert key in result["modules"], f"缺少模块: {key}"


@requires_api
def test_extract_all_no_crash_on_failure(indexed_doc):
    """单个模块失败不应导致整体崩溃，至少半数成功"""
    result = _get_extract_all(indexed_doc["tagged_paragraphs"])

    assert len(result["modules"]) == 9

    success_count = sum(1 for v in result["modules"].values() if v is not None)
    assert success_count >= 5, f"应至少有5个模块成功，实际: {success_count}"
