from src.parser.pdf_parser import parse_pdf
from src.models import Paragraph


def test_parse_pdf_returns_list():
    """基本功能测试 — 即使是图片PDF也不应抛异常"""
    result = parse_pdf("示例文档/DeepAnalysis_Analysis_20260319.pdf")
    assert isinstance(result, list)


def test_parse_pdf_table_extraction():
    """如果 PDF 有可提取的表格，检查不抛异常"""
    result = parse_pdf("示例文档/DeepAnalysis_Analysis_20260319.pdf")
    assert isinstance(result, list)
