"""统一文档解析接口：根据文件扩展名分发到对应解析器"""

from pathlib import Path
from src.models import Paragraph
from src.parser.docx_parser import parse_docx
from src.parser.doc_parser import parse_doc
from src.parser.pdf_parser import parse_pdf


def parse_document(file_path: str) -> list[Paragraph]:
    """根据文件扩展名选择解析器，返回 List[Paragraph]。

    支持格式: .docx, .doc, .pdf
    不支持的格式抛出 ValueError。
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".docx":
        return parse_docx(file_path)
    elif ext == ".doc":
        return parse_doc(file_path)
    elif ext == ".pdf":
        return parse_pdf(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")
