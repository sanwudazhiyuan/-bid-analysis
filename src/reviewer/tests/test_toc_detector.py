"""Tests for TOC detection in tender documents."""
from src.models import Paragraph
from src.reviewer.toc_detector import detect_toc


def test_detect_toc_with_toc_style():
    """Paragraphs with TOC style are detected as table of contents."""
    paras = [
        Paragraph(index=0, text="目录", style="TOCHeading"),
        Paragraph(index=1, text="第一章 投标函 ........ 1", style="TOC1"),
        Paragraph(index=2, text="第二章 技术方案 ...... 5", style="TOC1"),
        Paragraph(index=3, text="2.1 系统架构 ........ 6", style="TOC2"),
        Paragraph(index=4, text="第三章 商务报价 ...... 10", style="TOC1"),
    ] + [Paragraph(index=i + 5, text=f"正文段落{i}") for i in range(50)]
    result = detect_toc(paras)
    assert result is not None
    assert len(result) >= 3
    assert result[0]["title"] == "第一章 投标函"
    assert result[0]["level"] == 1


def test_detect_toc_with_pattern_matching():
    """Lines matching '第X章 title ... page' pattern are detected."""
    paras = [
        Paragraph(index=0, text="目  录"),
        Paragraph(index=1, text="第一章 投标函 1"),
        Paragraph(index=2, text="第二章 授权委托书 3"),
        Paragraph(index=3, text="第三章 技术方案 5"),
        Paragraph(index=4, text="第四章 商务方案 12"),
        Paragraph(index=5, text="第五章 服务承诺 18"),
    ] + [Paragraph(index=i + 6, text=f"正文{i}") for i in range(50)]
    result = detect_toc(paras)
    assert result is not None
    assert len(result) == 5


def test_detect_toc_none_when_no_toc():
    """Returns None when document has no detectable TOC."""
    paras = [Paragraph(index=i, text=f"这是一段普通文本 {i}") for i in range(60)]
    result = detect_toc(paras)
    assert result is None
