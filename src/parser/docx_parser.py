"""docx 文件解析器：提取段落和表格，返回 List[Paragraph]"""

from docx import Document
from src.models import Paragraph


def parse_docx(file_path: str) -> list[Paragraph]:
    """解析 .docx 文件，提取段落和表格。

    段落和表格按在文档中的出现顺序（body 元素顺序）交错排列，
    而非先列所有段落再列所有表格。
    """
    doc = Document(file_path)
    paragraphs = []
    idx = 0

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

            # 获取样式
            style_name = None
            pPr = element.find(qn("w:pPr"))
            if pPr is not None:
                pStyle = pPr.find(qn("w:pStyle"))
                if pStyle is not None:
                    style_name = pStyle.get(qn("w:val"))

            paragraphs.append(Paragraph(
                index=idx,
                text=text,
                style=style_name,
                is_table=False,
                table_data=None,
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
