"""投标文件格式生成器：将提取的投标文件格式渲染为 .docx。

支持层级编号结构（一、1.1、1.1.1），自动生成目录。
"""

import os

from docx import Document
from docx.shared import RGBColor

from src.generator.style_manager import StyleManager
from src.generator.table_builder import TableBuilder


def _render_section(section: dict, doc: "Document", style_mgr: StyleManager,
                    table_builder: TableBuilder, level: int = 1) -> None:
    """递归渲染一个 section 节点。

    level: 1=一级标题(heading2), 2=二级(heading3), 3+=正文加粗
    """
    number = section.get("number", "")
    title = section.get("title", "")
    section_type = section.get("type", "")

    # 渲染标题
    if title:
        heading_text = f"{number}、{title}" if level == 1 and number else f"{number} {title}" if number else title
        heading_para = doc.add_paragraph()
        if level == 1:
            heading_run = heading_para.add_run(heading_text)
            style_mgr.apply_run_style(heading_run, "heading2")
        elif level == 2:
            heading_run = heading_para.add_run(heading_text)
            style_mgr.apply_run_style(heading_run, "heading3")
        else:
            heading_run = heading_para.add_run(heading_text)
            style_mgr.apply_run_style(heading_run, "body")
            heading_run.bold = True

    # group 类型：递归渲染子项
    if section_type == "group":
        for child in section.get("children", []):
            _render_section(child, doc, style_mgr, table_builder, level + 1)
        return

    # 表格类型
    if section_type in ("key_value_table", "standard_table"):
        table_builder.build(section, doc)
    elif section_type in ("text", "template"):
        content = section.get("content", "")
        if content:
            para = doc.add_paragraph()
            run = para.add_run(content)
            style_mgr.apply_run_style(run, "body")


def _render_toc(sections: list[dict], doc: "Document", style_mgr: StyleManager) -> None:
    """在正文前渲染一个简单的文本目录。"""
    toc_title = doc.add_paragraph()
    toc_run = toc_title.add_run("目  录")
    style_mgr.apply_run_style(toc_run, "heading2")
    toc_title.alignment = 1  # center

    def _walk(items: list[dict], depth: int = 0):
        for item in items:
            number = item.get("number", "")
            title = item.get("title", "")
            indent = "    " * depth
            if depth == 0:
                line = f"{indent}{number}、{title}" if number else f"{indent}{title}"
            else:
                line = f"{indent}{number} {title}" if number else f"{indent}{title}"
            para = doc.add_paragraph()
            run = para.add_run(line)
            style_mgr.apply_run_style(run, "body")
            if depth == 0:
                run.bold = True
            if item.get("type") == "group":
                _walk(item.get("children", []), depth + 1)

    _walk(sections)

    # 目录与正文之间加空行
    doc.add_paragraph()


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

    # 渲染目录
    if sections:
        _render_toc(sections, doc, style_mgr)

    # 渲染正文
    for section in sections:
        _render_section(section, doc, style_mgr, table_builder, level=1)

    doc.save(output_path)
