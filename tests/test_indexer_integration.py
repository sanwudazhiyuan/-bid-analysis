"""索引层集成测试 — build_index 端到端验证"""
import glob
import pytest
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))


def test_index_returns_required_structure():
    paragraphs = parse_document("测试文档/招标公告.docx")
    result = build_index(paragraphs)
    assert "confidence" in result
    assert "sections" in result
    assert "tagged_paragraphs" in result
    assert result["confidence"] >= 0


def test_index_tags_coverage():
    """对较大的招标文件，检查主要标签类型都有段落命中"""
    paragraphs = parse_document(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    result = build_index(paragraphs)
    all_tags = set()
    for tp in result["tagged_paragraphs"]:
        all_tags.update(tp.tags)

    # 建行的完整招标文件应覆盖多种标签
    expected_tags = {"评分", "资格", "报价", "风险"}
    missing = expected_tags - all_tags
    assert len(missing) <= 1, f"缺少标签: {missing}, 实际标签: {all_tags}"


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.replace("\\", "/").split("/")[-1],
)
def test_index_all_test_documents(docx_path):
    """每个测试文档: build_index 不崩溃，有章节，有标签"""
    paragraphs = parse_document(docx_path)
    result = build_index(paragraphs)

    assert result["confidence"] >= 0
    assert len(result["sections"]) >= 1
    assert len(result["tagged_paragraphs"]) == len(paragraphs)

    # 至少部分段落应被打标
    tagged_with_tags = [tp for tp in result["tagged_paragraphs"] if tp.tags]
    assert len(tagged_with_tags) > 0, f"{docx_path} 无任何段落被打标"
