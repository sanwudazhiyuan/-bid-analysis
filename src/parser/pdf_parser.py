"""PDF 文件解析器：使用 pdfplumber 提取文本和表格，返回 List[Paragraph]"""

import logging
from src.models import Paragraph

logger = logging.getLogger(__name__)


def parse_pdf(file_path: str) -> list[Paragraph]:
    """解析 PDF 文件，逐页提取文本和表格。

    对于图片型 PDF，提取结果可能为空（不报错）。
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber 未安装，请运行: pip install pdfplumber")

    paragraphs = []
    idx = 0

    with pdfplumber.open(file_path) as pdf:
        logger.info("PDF 共 %d 页: %s", len(pdf.pages), file_path)

        for page_num, page in enumerate(pdf.pages, 1):
            # 提取表格
            tables = page.extract_tables() or []
            for table in tables:
                if not table:
                    continue
                rows_data = []
                for row in table:
                    cells = [cell.strip() if cell else "" for cell in row]
                    rows_data.append(cells)
                if rows_data:
                    summary = " | ".join(rows_data[0])
                    paragraphs.append(Paragraph(
                        index=idx,
                        text=summary,
                        style=None,
                        is_table=True,
                        table_data=rows_data,
                    ))
                    idx += 1

            # 提取文本（排除已被表格覆盖的区域）
            text = page.extract_text() or ""
            if text.strip():
                # 按行分割
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    paragraphs.append(Paragraph(
                        index=idx,
                        text=line,
                        style=None,
                        is_table=False,
                        table_data=None,
                    ))
                    idx += 1

    logger.info("PDF 解析完成，提取 %d 个段落/表格", len(paragraphs))
    return paragraphs
