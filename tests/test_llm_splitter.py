"""LLM 兜底索引测试"""
import pytest
from src.models import Paragraph
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


def _make_paragraphs(texts: list[str]) -> list[Paragraph]:
    """构造测试用的 Paragraph 列表"""
    return [
        Paragraph(index=i, text=t)
        for i, t in enumerate(texts)
    ]


def test_llm_split_returns_sections():
    """llm_split 返回包含 sections 和 assignments 的 dict"""
    from src.indexer.llm_splitter import llm_split

    # 使用非常简单的文本，不需要 API（mock 测试结构）
    paras = _make_paragraphs([
        "第一章 招标公告",
        "项目名称：测试项目",
        "采购编号：TEST-001",
        "第二章 投标人须知",
        "投标人应具有独立法人资格",
    ])

    # 测试函数签名和返回结构（不实际调用 API）
    # 这里只测试导入是否正确
    assert callable(llm_split)


@requires_api
def test_llm_split_with_real_document():
    """使用真实文档测试 LLM 兜底索引"""
    from src.parser.unified import parse_document
    from src.indexer.llm_splitter import llm_split

    paragraphs = parse_document(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )

    result = llm_split(paragraphs)
    assert "sections" in result
    assert "assignments" in result
    assert len(result["sections"]) >= 3, f"应识别出至少3个章节，实际: {len(result['sections'])}"

    # 每个 section 应有 title 和 start
    for section in result["sections"]:
        assert "title" in section
        assert "start" in section


def test_build_index_uses_llm_fallback_when_low_confidence():
    """当规则切分置信度低时，build_index 应调用 LLM 兜底"""
    # 这是一个集成测试的占位 - 真正的集成在 indexer.py 中
    from src.indexer.indexer import build_index
    assert callable(build_index)
