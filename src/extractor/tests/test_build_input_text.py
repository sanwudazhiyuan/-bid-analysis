"""测试 build_input_text 正确渲染表格数据为 markdown 格式。"""
import pytest
from src.models import TaggedParagraph
from src.extractor.base import build_input_text


class TestBuildInputTextTableData:
    """build_input_text 应将 table_data 渲染为 markdown 表格。"""

    def test_plain_paragraph(self):
        """普通段落只输出 [index] text。"""
        paragraphs = [
            TaggedParagraph(index=0, text="普通文本段落"),
        ]
        result = build_input_text(paragraphs)
        assert result == "[0] 普通文本段落"

    def test_paragraph_with_section_title(self):
        """带 section_title 的段落输出 [index] [section] text。"""
        paragraphs = [
            TaggedParagraph(index=5, text="内容", section_title="第一章"),
        ]
        result = build_input_text(paragraphs)
        assert result == "[5] [第一章] 内容"

    def test_table_paragraph_renders_markdown(self):
        """表格段落应渲染为 markdown 表格格式，而非仅第一行 summary。"""
        paragraphs = [
            TaggedParagraph(
                index=10,
                text="评审因素 | 评分项 | 评分细则",
                table_data=[
                    ["评审因素", "评分项", "评分细则"],
                    ["报价部分（30分）", "投标报价（30分）", "基础分25分"],
                    ["商务部分（30分）", "企业业绩（16分）", "每增加一个案例得2分"],
                ],
            ),
        ]
        result = build_input_text(paragraphs)
        # 应包含所有行的数据，不仅是表头
        assert "报价部分（30分）" in result
        assert "投标报价（30分）" in result
        assert "基础分25分" in result
        assert "商务部分（30分）" in result
        assert "企业业绩（16分）" in result

    def test_table_has_markdown_format(self):
        """表格应使用 markdown 表格语法（| 分隔符和 --- 分隔行）。"""
        paragraphs = [
            TaggedParagraph(
                index=3,
                text="列A | 列B",
                table_data=[
                    ["列A", "列B"],
                    ["值1", "值2"],
                ],
            ),
        ]
        result = build_input_text(paragraphs)
        lines = result.strip().split("\n")
        # 应有表头行、分隔行、数据行
        header_lines = [l for l in lines if "列A" in l and "列B" in l and "|" in l]
        sep_lines = [l for l in lines if "---" in l]
        data_lines = [l for l in lines if "值1" in l and "值2" in l]
        assert len(header_lines) >= 1, "应有 markdown 表头行"
        assert len(sep_lines) >= 1, "应有 markdown 分隔行"
        assert len(data_lines) >= 1, "应有 markdown 数据行"

    def test_table_with_uneven_rows(self):
        """列数不一致的行应补齐空列。"""
        paragraphs = [
            TaggedParagraph(
                index=7,
                text="A | B | C",
                table_data=[
                    ["A", "B", "C"],
                    ["值1", "值2"],  # 少一列
                ],
            ),
        ]
        result = build_input_text(paragraphs)
        assert "值1" in result
        assert "值2" in result

    def test_mixed_paragraphs_and_tables(self):
        """混合段落和表格应按顺序正确渲染。"""
        paragraphs = [
            TaggedParagraph(index=0, text="普通段落"),
            TaggedParagraph(
                index=1, text="A | B",
                table_data=[["A", "B"], ["1", "2"]],
            ),
            TaggedParagraph(index=2, text="另一个普通段落"),
        ]
        result = build_input_text(paragraphs)
        assert "普通段落" in result
        assert "另一个普通段落" in result
        # 表格数据行也应在输出中
        lines = result.split("\n")
        # 第一行是普通段落
        assert lines[0] == "[0] 普通段落"
        # 最后一行是另一个普通段落
        assert lines[-1] == "[2] 另一个普通段落"

    def test_empty_table_data_falls_back_to_text(self):
        """table_data 为空列表时应回退到普通文本渲染。"""
        paragraphs = [
            TaggedParagraph(index=0, text="只有表头", table_data=[]),
        ]
        result = build_input_text(paragraphs)
        assert result == "[0] 只有表头"

    def test_single_row_table(self):
        """只有表头没有数据行的表格应正常渲染。"""
        paragraphs = [
            TaggedParagraph(
                index=0, text="A | B",
                table_data=[["A", "B"]],
            ),
        ]
        result = build_input_text(paragraphs)
        assert "| A | B |" in result
