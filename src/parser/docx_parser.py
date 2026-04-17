"""docx 文件解析器：提取段落和表格，返回 List[Paragraph]

当 extract_format=True 时额外提取段落级格式信息。
同时提供 extract_document_format() 提取文档级格式（节、页眉页脚等）。
"""

from collections import Counter
from docx import Document
from src.models import (
    Paragraph, RunFormat, ParagraphFormat, HeaderFooterInfo,
    SectionFormat, DocumentFormat,
)


# ── Unit conversion helpers ──────────────────────────────────────────────

def _twips_to_cm(twips: str | None) -> float | None:
    """Convert twips (1/20 point, 1440 twips = 1 inch = 2.54 cm) to cm."""
    if twips is None:
        return None
    try:
        return round(int(twips) / 1440 * 2.54, 2)
    except (ValueError, TypeError):
        return None


def _half_points_to_pt(val: str | None) -> float | None:
    """Convert half-points (w:sz value) to pt. sz=24 means 12pt."""
    if val is None:
        return None
    try:
        return int(val) / 2
    except (ValueError, TypeError):
        return None


# ── Run & Paragraph format extraction ────────────────────────────────────

def _extract_run_format(run_element, qn_func) -> RunFormat:
    """Extract format info from a w:r element."""
    text_parts = []
    for t in run_element.findall(qn_func("w:t")):
        if t.text:
            text_parts.append(t.text)
    text = "".join(text_parts)

    rf = RunFormat(text=text)
    rPr = run_element.find(qn_func("w:rPr"))
    if rPr is None:
        return rf

    # Font
    rFonts = rPr.find(qn_func("w:rFonts"))
    if rFonts is not None:
        rf.font_name_ascii = rFonts.get(qn_func("w:ascii"))
        rf.font_name_east_asia = rFonts.get(qn_func("w:eastAsia"))

    # Size
    sz = rPr.find(qn_func("w:sz"))
    if sz is not None:
        rf.font_size_pt = _half_points_to_pt(sz.get(qn_func("w:val")))

    # Color
    color = rPr.find(qn_func("w:color"))
    if color is not None:
        rf.font_color_rgb = color.get(qn_func("w:val"))

    # Bold
    b = rPr.find(qn_func("w:b"))
    if b is not None:
        val = b.get(qn_func("w:val"))
        rf.bold = val != "0" if val else True

    # Italic
    i = rPr.find(qn_func("w:i"))
    if i is not None:
        val = i.get(qn_func("w:val"))
        rf.italic = val != "0" if val else True

    # Underline
    u = rPr.find(qn_func("w:u"))
    if u is not None:
        rf.underline = u.get(qn_func("w:val"))

    return rf


def _extract_para_format(element, style_id_to_name: dict, qn_func) -> ParagraphFormat:
    """Extract format info from a w:p element."""
    pf = ParagraphFormat()
    pPr = element.find(qn_func("w:pPr"))

    if pPr is not None:
        # Style → heading level
        pStyle = pPr.find(qn_func("w:pStyle"))
        if pStyle is not None:
            style_id = pStyle.get(qn_func("w:val"))
            style_name = style_id_to_name.get(style_id, style_id or "")
            if style_name.lower().startswith("heading"):
                try:
                    pf.heading_level = int(style_name.split()[-1])
                except (ValueError, IndexError):
                    pf.heading_level = 0

        # Outline level
        outlineLvl = pPr.find(qn_func("w:outlineLvl"))
        if outlineLvl is not None:
            try:
                pf.outline_level = int(outlineLvl.get(qn_func("w:val"), "0"))
            except ValueError:
                pass

        # Spacing
        spacing = pPr.find(qn_func("w:spacing"))
        if spacing is not None:
            line = spacing.get(qn_func("w:line"))
            line_rule = spacing.get(qn_func("w:lineRule"))
            pf.line_spacing_rule = line_rule
            if line:
                try:
                    line_val = int(line)
                    if line_rule == "auto" or line_rule is None:
                        pf.line_spacing = round(line_val / 240, 2)
                    else:
                        pf.line_spacing = round(line_val / 20, 2)
                except ValueError:
                    pass
            before = spacing.get(qn_func("w:before"))
            if before:
                pf.space_before_pt = _half_points_to_pt(before)
            after = spacing.get(qn_func("w:after"))
            if after:
                pf.space_after_pt = _half_points_to_pt(after)

        # Alignment
        jc = pPr.find(qn_func("w:jc"))
        if jc is not None:
            pf.alignment = jc.get(qn_func("w:val"))

        # Indent
        ind = pPr.find(qn_func("w:ind"))
        if ind is not None:
            pf.indent_left_cm = _twips_to_cm(ind.get(qn_func("w:left")))
            pf.indent_right_cm = _twips_to_cm(ind.get(qn_func("w:right")))
            first_line = ind.get(qn_func("w:firstLine"))
            if first_line:
                pf.indent_first_line_cm = _twips_to_cm(first_line)

    # Runs
    runs = []
    for r in element.findall(qn_func("w:r")):
        runs.append(_extract_run_format(r, qn_func))
    pf.runs = runs

    # Dominant calculations
    if runs:
        fonts = [r.font_name_east_asia or r.font_name_ascii for r in runs if r.font_name_east_asia or r.font_name_ascii]
        sizes = [r.font_size_pt for r in runs if r.font_size_pt is not None]
        colors = [r.font_color_rgb for r in runs if r.font_color_rgb is not None]
        if fonts:
            pf.dominant_font = Counter(fonts).most_common(1)[0][0]
        if sizes:
            pf.dominant_size_pt = Counter(sizes).most_common(1)[0][0]
        if colors:
            pf.dominant_color = Counter(colors).most_common(1)[0][0]
        pf.has_non_black_text = any(
            c and c.upper() not in ("000000", "AUTO", "FFFFFF")
            for c in colors
        )

    return pf


# ── Document-level format extraction ─────────────────────────────────────

def extract_document_format(file_path: str) -> DocumentFormat:
    """提取文档级格式信息（sections/headers/footers/page setup）。"""
    from docx.oxml.ns import qn
    doc = Document(file_path)

    sections = []
    for si, section in enumerate(doc.sections):
        sf = SectionFormat(section_index=si)
        sectPr = section._sectPr

        # Page margins
        pgMar = sectPr.find(qn("w:pgMar"))
        if pgMar is not None:
            sf.margin_top_cm = _twips_to_cm(pgMar.get(qn("w:top")))
            sf.margin_bottom_cm = _twips_to_cm(pgMar.get(qn("w:bottom")))
            sf.margin_left_cm = _twips_to_cm(pgMar.get(qn("w:left")))
            sf.margin_right_cm = _twips_to_cm(pgMar.get(qn("w:right")))

        # Page size
        pgSz = sectPr.find(qn("w:pgSz"))
        if pgSz is not None:
            sf.page_width_cm = _twips_to_cm(pgSz.get(qn("w:w")))
            sf.page_height_cm = _twips_to_cm(pgSz.get(qn("w:h")))

        # Section break type
        sec_type = sectPr.find(qn("w:type"))
        if sec_type is not None:
            sf.section_break_type = sec_type.get(qn("w:val"))

        # Page number type
        pgNumType = sectPr.find(qn("w:pgNumType"))
        if pgNumType is not None:
            start = pgNumType.get(qn("w:start"))
            if start is not None:
                try:
                    sf.page_number_start = int(start)
                except ValueError:
                    pass
            sf.page_number_format = pgNumType.get(qn("w:fmt"))

        # Title page (different first page header/footer)
        titlePg = sectPr.find(qn("w:titlePg"))
        sf.has_different_first_page = titlePg is not None

        # Headers
        for hdr_ref in sectPr.findall(qn("w:headerReference")):
            hf_type = hdr_ref.get(qn("w:type")) or "default"
            rid = hdr_ref.get(qn("r:id"))
            hfi = HeaderFooterInfo(hf_type=hf_type)
            if rid and rid in doc.part.rels:
                _parse_hf_content(doc.part.rels[rid].target_part._element, hfi, qn)
            sf.headers.append(hfi)

        # Footers
        for ftr_ref in sectPr.findall(qn("w:footerReference")):
            hf_type = ftr_ref.get(qn("w:type")) or "default"
            rid = ftr_ref.get(qn("r:id"))
            hfi = HeaderFooterInfo(hf_type=hf_type)
            if rid and rid in doc.part.rels:
                _parse_hf_content(doc.part.rels[rid].target_part._element, hfi, qn)
            sf.footers.append(hfi)

        sections.append(sf)

    # Map sections to paragraph ranges
    _assign_section_para_ranges(doc, sections)

    return DocumentFormat(sections=sections)


def _parse_hf_content(hf_element, hfi: HeaderFooterInfo, qn_func):
    """解析页眉/页脚 XML 内容，检测文字、图片、页码域。"""
    text_parts = []
    for p in hf_element.findall(f".//{qn_func('w:t')}"):
        if p.text and p.text.strip():
            text_parts.append(p.text.strip())
    if text_parts:
        hfi.has_text = True
        hfi.text_content = " ".join(text_parts)

    # Images (w:drawing)
    drawings = hf_element.findall(f".//{qn_func('w:drawing')}")
    if drawings:
        hfi.has_image = True
        hfi.image_count = len(drawings)

    # Page number fields: w:fldSimple containing PAGE, or w:fldChar sequence
    for fld in hf_element.findall(f".//{qn_func('w:fldSimple')}"):
        instr = fld.get(qn_func("w:instr")) or ""
        if "PAGE" in instr.upper():
            hfi.has_page_number = True
            break
    # Also check fldChar-based page numbering
    for instrText in hf_element.findall(f".//{qn_func('w:instrText')}"):
        if instrText.text and "PAGE" in instrText.text.upper():
            hfi.has_page_number = True
            break


def _assign_section_para_ranges(doc, sections: list[SectionFormat]):
    """Assign paragraph index ranges to each section."""
    from docx.oxml.ns import qn
    body = doc.element.body

    para_idx = 0
    section_para_starts: list[int] = []
    current_section = 0

    for element in body:
        if element.tag == qn("w:p"):
            runs_text = []
            for r in element.findall(qn("w:r")):
                t = r.find(qn("w:t"))
                if t is not None and t.text:
                    runs_text.append(t.text)
            text = "".join(runs_text).strip()
            if not text:
                continue

            if current_section >= len(section_para_starts):
                section_para_starts.append(para_idx)

            # Check if this paragraph contains a section break
            pPr = element.find(qn("w:pPr"))
            if pPr is not None:
                sectPr = pPr.find(qn("w:sectPr"))
                if sectPr is not None:
                    current_section += 1

            para_idx += 1
        elif element.tag == qn("w:tbl"):
            if current_section >= len(section_para_starts):
                section_para_starts.append(para_idx)
            para_idx += 1

    # Also handle the final section (body-level sectPr)
    if current_section >= len(section_para_starts):
        section_para_starts.append(para_idx if para_idx > 0 else 0)

    # Assign ranges
    total_paras = para_idx
    for i, sf in enumerate(sections):
        start = section_para_starts[i] if i < len(section_para_starts) else 0
        end = section_para_starts[i + 1] - 1 if i + 1 < len(section_para_starts) else total_paras - 1
        sf.para_range = (start, end)


# ── Main parser ──────────────────────────────────────────────────────────

def parse_docx(file_path: str, extract_format: bool = False) -> list[Paragraph]:
    """解析 .docx 文件，提取段落和表格。

    段落和表格按在文档中的出现顺序（body 元素顺序）交错排列，
    而非先列所有段落再列所有表格。

    当 extract_format=True 时，额外提取每个段落的 ParagraphFormat。
    """
    doc = Document(file_path)
    paragraphs = []
    idx = 0

    # 构建 style ID → style name 映射表
    style_id_to_name: dict[str, str] = {}
    for style in doc.styles:
        if style.style_id and style.name:
            style_id_to_name[style.style_id] = style.name

    # 按 body 中元素顺序遍历，保持段落和表格的原始位置关系
    from docx.oxml.ns import qn

    for element in doc.element.body:
        tag = element.tag

        if tag == qn("w:p"):
            # 段落元素
            text = element.text or ""
            # 需要拼接所有 run 的文本
            runs_text = []
            for r in element.findall(qn("w:r")):
                t = r.find(qn("w:t"))
                if t is not None and t.text:
                    runs_text.append(t.text)
            text = "".join(runs_text).strip()
            if not text:
                continue

            # 获取样式（将 style ID 转换为可读的 style name）
            style_name = None
            pPr = element.find(qn("w:pPr"))
            if pPr is not None:
                pStyle = pPr.find(qn("w:pStyle"))
                if pStyle is not None:
                    style_id = pStyle.get(qn("w:val"))
                    style_name = style_id_to_name.get(style_id, style_id)

            # Format extraction (only when requested)
            fmt = None
            if extract_format:
                fmt = _extract_para_format(element, style_id_to_name, qn)

            paragraphs.append(Paragraph(
                index=idx,
                text=text,
                style=style_name,
                is_table=False,
                table_data=None,
                format_info=fmt,
            ))
            idx += 1

        elif tag == qn("w:tbl"):
            # 表格元素
            rows_data = []
            for tr in element.findall(qn("w:tr")):
                cells = []
                for tc in tr.findall(qn("w:tc")):
                    # 拼接单元格内所有段落的文本
                    cell_texts = []
                    for p in tc.findall(qn("w:p")):
                        runs_text = []
                        for r in p.findall(qn("w:r")):
                            t = r.find(qn("w:t"))
                            if t is not None and t.text:
                                runs_text.append(t.text)
                        cell_texts.append("".join(runs_text))
                    cells.append("\n".join(cell_texts).strip())
                rows_data.append(cells)

            if rows_data:
                summary = " | ".join(rows_data[0]) if rows_data[0] else ""
                paragraphs.append(Paragraph(
                    index=idx,
                    text=summary,
                    style=None,
                    is_table=True,
                    table_data=rows_data,
                ))
                idx += 1

    return paragraphs