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


def parse_documents(file_paths: list[str]) -> list[Paragraph]:
    """依次解析多个文件，合并段落列表。

    每个段落增加 source_file 标记，后续管线无需修改。
    不支持的格式在对应文件上抛出 ValueError。
    """
    all_paragraphs: list[Paragraph] = []
    global_idx = 0

    for file_path in file_paths:
        filename = Path(file_path).name
        paragraphs = parse_document(file_path)
        for p in paragraphs:
            p.source_file = filename
            p.index = global_idx
            global_idx += 1
            all_paragraphs.append(p)

    return all_paragraphs
