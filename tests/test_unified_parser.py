import glob
import pytest
from src.parser.unified import parse_document

TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))


def test_parse_docx():
    result = parse_document("测试文档/招标公告.docx")
    assert len(result) > 0


def test_parse_doc():
    result = parse_document(
        "（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc"
    )
    assert len(result) > 0


def test_parse_unsupported_format():
    with pytest.raises(ValueError, match="不支持的文件格式"):
        parse_document("test.txt")


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.split("/")[-1].split("\\")[-1],
)
def test_unified_parse_all_test_documents(docx_path):
    """统一接口对 测试文档/ 下每个文件均能成功解析"""
    result = parse_document(docx_path)
    assert len(result) > 0, f"{docx_path} 解析后段落数为0"
