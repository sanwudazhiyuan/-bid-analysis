"""Test format-related data models."""
from src.models import (
    RunFormat, ParagraphFormat, HeaderFooterInfo,
    SectionFormat, FormatSummary, DocumentFormat, Paragraph,
)


def test_paragraph_format_info_default_none():
    p = Paragraph(index=0, text="hello")
    assert p.format_info is None


def test_paragraph_with_format_info():
    fmt = ParagraphFormat(
        heading_level=1,
        alignment="center",
        runs=[RunFormat(text="标题", font_name_east_asia="宋体", font_size_pt=16.0, bold=True)],
        dominant_font="宋体",
        dominant_size_pt=16.0,
    )
    p = Paragraph(index=0, text="标题", format_info=fmt)
    assert p.format_info.heading_level == 1
    assert p.format_info.runs[0].font_size_pt == 16.0


def test_document_format_to_prompt_text():
    doc_fmt = DocumentFormat(
        sections=[SectionFormat(
            section_index=0,
            margin_top_cm=2.54, margin_bottom_cm=2.54,
            margin_left_cm=3.17, margin_right_cm=3.17,
            para_range=(0, 45),
            section_heading="施工方案",
            page_number_start=1,
            headers=[HeaderFooterInfo(hf_type="default", has_image=True, image_count=1)],
            footers=[HeaderFooterInfo(hf_type="default", has_page_number=True)],
        )],
        total_pages=23,
        format_summary=FormatSummary(
            heading_stats={1: {"count": 5, "font": "宋体", "size_pt": 16, "bold": True}},
            non_black_paragraphs=[{"para_index": 23, "color": "FF0000", "text_snippet": "重要"}],
        ),
    )
    text = doc_fmt.to_prompt_text()
    assert "Section 0" in text
    assert "有图片1张" in text
    assert "有页码" in text
    assert "段落23" in text


def test_format_summary_to_prompt_text_empty():
    fs = FormatSummary()
    assert fs.to_prompt_text() == ""