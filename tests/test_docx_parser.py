import glob
import pytest
from src.parser.docx_parser import parse_docx
from src.models import Paragraph

# 测试文档目录下的全部 .docx 文件
TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))


def test_parse_docx_returns_paragraphs():
    """使用测试文档测试 .docx 解析"""
    result = parse_docx("测试文档/招标公告.docx")
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(p, Paragraph) for p in result)


def test_parse_docx_has_tables():
    result = parse_docx(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    tables = [p for p in result if p.is_table]
    assert len(tables) > 0


def test_parse_docx_preserves_style_info():
    """验证样式字段被正确填充（即使值为 None，字段应存在）"""
    result = parse_docx("测试文档/招标公告.docx")
    for p in result:
        assert hasattr(p, "style")  # 字段必须存在


def test_parse_docx_table_data():
    result = parse_docx(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    tables = [p for p in result if p.is_table and p.table_data]
    if tables:
        first_table = tables[0]
        assert isinstance(first_table.table_data, list)
        assert isinstance(first_table.table_data[0], list)


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.split("/")[-1].split("\\")[-1],
)
def test_parse_all_test_documents(docx_path):
    """对 测试文档/ 下每个 .docx 验证：可解析、有段落、有中文"""
    result = parse_docx(docx_path)
    assert isinstance(result, list), f"{docx_path} 返回类型错误"
    assert len(result) > 0, f"{docx_path} 解析后段落数为0"
    texts = [p.text for p in result if p.text.strip()]
    assert len(texts) > 0, f"{docx_path} 无有效文本"
    # 招标文件必定包含中文
    has_chinese = any(any("\u4e00" <= c <= "\u9fff" for c in t) for t in texts)
    assert has_chinese, f"{docx_path} 未检测到中文内容"
