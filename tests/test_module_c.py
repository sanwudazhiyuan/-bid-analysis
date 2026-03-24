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


def test_filter_paragraphs_includes_commercial_content():
    """扩展后的筛选应包含报价要求、后评价、分配规则相关段落"""
    from src.extractor.module_c import _filter_paragraphs
    from src.models import TaggedParagraph

    paragraphs = [
        TaggedParagraph(index=0, text="评分分值构成表", section_title="评标办法"),
        TaggedParagraph(index=1, text="报价方式：含税包干价格"),
        TaggedParagraph(index=2, text="单价最高限价：3.32元/张"),
        TaggedParagraph(index=3, text="后评价管理：季度评价指标"),
        TaggedParagraph(index=4, text="分配规则：首次分配50%：50%"),
        TaggedParagraph(index=5, text="履约保证金金额为20万元"),
        TaggedParagraph(index=6, text="这是一段无关内容"),
    ]
    filtered = _filter_paragraphs(paragraphs)
    filtered_indices = {tp.index for tp in filtered}
    assert 0 in filtered_indices, "评分相关段落应被选中"
    assert 1 in filtered_indices, "报价方式段落应被选中"
    assert 2 in filtered_indices, "限价段落应被选中"
    assert 3 in filtered_indices, "后评价段落应被选中"
    assert 4 in filtered_indices, "分配规则段落应被选中"
    assert 6 not in filtered_indices, "无关段落不应被选中"


def test_resolve_references_appends_referenced_paragraphs():
    """当筛选段落中有'详见XX'引用时，应从全文档追加被引用段落"""
    from src.extractor.module_c import _resolve_references
    from src.models import TaggedParagraph

    all_paragraphs = [
        TaggedParagraph(index=0, text="评分标准详见评标办法前附表"),
        TaggedParagraph(index=1, text="这是无关段落"),
        TaggedParagraph(index=2, text="这是无关段落2"),
        TaggedParagraph(index=3, text="评标办法前附表：评分项与分值", section_title="评标办法前附表"),
        TaggedParagraph(index=4, text="技术评分30分，商务评分20分"),
        TaggedParagraph(index=5, text="据第2.1款规定的标准执行"),
        TaggedParagraph(index=6, text="第2.1款 卡片质量标准", section_title="2.1 卡片质量标准"),
    ]
    selected = [all_paragraphs[0], all_paragraphs[5]]
    selected_indices = {0, 5}

    resolved = _resolve_references(selected, all_paragraphs, selected_indices)
    resolved_indices = {tp.index for tp in resolved}

    assert 3 in resolved_indices, "应追加'评标办法前附表'段落"
    assert 6 in resolved_indices, "应追加'第2.1款'段落"
    assert 1 not in resolved_indices, "不应追加无关段落"


def test_resolve_references_no_duplicates():
    """已选中的段落不应被重复追加"""
    from src.extractor.module_c import _resolve_references
    from src.models import TaggedParagraph

    all_paragraphs = [
        TaggedParagraph(index=0, text="详见评标办法前附表", section_title="评标办法"),
        TaggedParagraph(index=1, text="评标办法前附表内容", section_title="评标办法前附表"),
    ]
    selected = [all_paragraphs[0], all_paragraphs[1]]
    selected_indices = {0, 1}

    resolved = _resolve_references(selected, all_paragraphs, selected_indices)
    assert len(resolved) == 0, "已选中的段落不应被重复追加"


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
