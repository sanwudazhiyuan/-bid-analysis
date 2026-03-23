"""分析报告生成器：将校对后的 JSON 渲染为 .docx 分析报告。

输出包含 A-G 全部模块标题、子标题和动态表格。
失败模块渲染红色占位文本。
"""

import os

from docx import Document
from docx.shared import RGBColor, Pt

from src.generator.style_manager import StyleManager
from src.generator.table_builder import TableBuilder


def render_report(data: dict, output_path: str) -> None:
    """将提取/校对结果渲染为分析报告 .docx。

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

    # 报告大标题
    title_para = doc.add_paragraph()
    title_run = title_para.add_run("招标文件分析报告")
    style_mgr.apply_run_style(title_run, "heading1")
    title_para.alignment = 1  # 居中

    modules = data.get("modules", {})

    for module_key, module_data in modules.items():
        # None 模块
        if module_data is None:
            para = doc.add_paragraph()
            run = para.add_run(f"[{module_key}] 无数据（跳过）")
            run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            continue

        # 失败模块
        if module_data.get("status") == "failed":
            error = module_data.get("error", "未知错误")
            para = doc.add_paragraph()
            run = para.add_run(
                f"[{module_key} 提取失败: {error}]"
            )
            run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
            continue

        # 正常模块 — 渲染标题
        title = module_data.get("title", module_key)
        heading_para = doc.add_paragraph()
        heading_run = heading_para.add_run(title)
        style_mgr.apply_run_style(heading_run, "heading2")

        # 渲染 sections
        sections = module_data.get("sections", [])
        _render_sections(doc, sections, table_builder, style_mgr)

    doc.save(output_path)


def _render_sections(
    doc: Document,
    sections: list,
    table_builder: TableBuilder,
    style_mgr: StyleManager,
) -> None:
    """递归渲染 sections 列表。"""
    for section in sections:
        section_type = section.get("type", "")
        section_title = section.get("title", "")

        # 子标题
        if section_title:
            sub_para = doc.add_paragraph()
            sub_run = sub_para.add_run(section_title)
            style_mgr.apply_run_style(sub_run, "heading3")

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

        # 递归处理子 sections
        sub_sections = section.get("sections", [])
        if sub_sections:
            _render_sections(doc, sub_sections, table_builder, style_mgr)
