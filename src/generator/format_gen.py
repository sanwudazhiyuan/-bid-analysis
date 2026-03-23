"""投标文件格式生成器：将提取的投标文件格式渲染为 .docx。

输出包含投标函、报价表、服务承诺书等模板结构。
"""

import os

from docx import Document
from docx.shared import RGBColor

from src.generator.style_manager import StyleManager
from src.generator.table_builder import TableBuilder


def render_format(data: dict, output_path: str) -> None:
    """将提取结果中的投标文件格式渲染为 .docx。

    Args:
        data: 包含 modules 的提取结果 dict
        output_path: 输出 .docx 文件路径
    """
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    doc = Document()
    style_mgr = StyleManager()
    table_builder = TableBuilder(style_manager=style_mgr)

    # 大标题
    title_para = doc.add_paragraph()
    title_run = title_para.add_run("投标文件格式")
    style_mgr.apply_run_style(title_run, "heading1")
    title_para.alignment = 1

    modules = data.get("modules", {})
    bid_format = modules.get("bid_format")

    if bid_format is None:
        para = doc.add_paragraph()
        run = para.add_run("[投标文件格式模块无数据]")
        run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        doc.save(output_path)
        return

    if bid_format.get("status") == "failed":
        error = bid_format.get("error", "未知错误")
        para = doc.add_paragraph()
        run = para.add_run(f"[投标文件格式提取失败: {error}]")
        run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        doc.save(output_path)
        return

    sections = bid_format.get("sections", [])
    for section in sections:
        section_type = section.get("type", "")
        section_title = section.get("title", "")

        # 渲染子标题
        if section_title:
            heading_para = doc.add_paragraph()
            heading_run = heading_para.add_run(section_title)
            style_mgr.apply_run_style(heading_run, "heading2")

        # 根据类型渲染
        if section_type in ("key_value_table", "standard_table"):
            table_builder.build(section, doc)
        elif section_type == "template":
            content = section.get("content", "")
            if content:
                para = doc.add_paragraph()
                run = para.add_run(content)
                style_mgr.apply_run_style(run, "body")
        elif section_type == "text":
            content = section.get("content", "")
            if content:
                para = doc.add_paragraph()
                run = para.add_run(content)
                style_mgr.apply_run_style(run, "body")

    doc.save(output_path)
