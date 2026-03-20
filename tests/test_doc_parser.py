import pytest
from src.parser.doc_parser import parse_doc, check_libreoffice
from src.models import Paragraph


@pytest.fixture
def doc_file():
    return "（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc"


def test_libreoffice_available():
    """检查 LibreOffice 是否已安装"""
    available = check_libreoffice()
    if not available:
        pytest.skip("LibreOffice not installed")


def test_parse_doc_returns_paragraphs(doc_file):
    result = parse_doc(doc_file)
    assert isinstance(result, list)
    assert len(result) > 50  # 招标文件应有大量段落


def test_parse_doc_has_chinese_text(doc_file):
    result = parse_doc(doc_file)
    texts = [p.text for p in result if p.text.strip()]
    assert any("采购" in t for t in texts)
    assert any("投标" in t for t in texts)


def test_parse_doc_has_tables(doc_file):
    result = parse_doc(doc_file)
    tables = [p for p in result if p.is_table]
    assert len(tables) > 0  # 招标文件一定有表格
