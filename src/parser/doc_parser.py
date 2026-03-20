"""doc 文件解析器：通过 LibreOffice 转换为 docx 后解析，降级为 olefile 纯文本提取"""

import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

from src.models import Paragraph
from src.parser.docx_parser import parse_docx

logger = logging.getLogger(__name__)

# LibreOffice 可执行文件路径（Windows 默认安装位置）
_SOFFICE_PATHS = [
    "soffice",  # 在 PATH 中
    "C:/Program Files/LibreOffice/program/soffice.exe",
    "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
]


def _find_soffice() -> str | None:
    """查找 soffice 可执行文件"""
    for path in _SOFFICE_PATHS:
        if shutil.which(path):
            return path
        if Path(path).is_file():
            return path
    return None


def check_libreoffice() -> bool:
    """检查 LibreOffice 是否可用"""
    return _find_soffice() is not None


def _convert_doc_to_docx(doc_path: str, output_dir: str) -> str:
    """调用 LibreOffice headless 将 .doc 转换为 .docx"""
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            "LibreOffice 未安装或不在 PATH 中。"
            "请安装 LibreOffice: https://www.libreoffice.org/download/"
        )

    doc_abs = str(Path(doc_path).resolve())
    cmd = [
        soffice,
        "--headless",
        "--convert-to", "docx",
        "--outdir", output_dir,
        doc_abs,
    ]

    logger.info("LibreOffice 转换: %s", doc_abs)
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=120,
    )

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"LibreOffice 转换失败: {stderr}")

    # 查找转换后的文件
    stem = Path(doc_path).stem
    docx_path = Path(output_dir) / f"{stem}.docx"
    if not docx_path.exists():
        raise RuntimeError(f"转换后文件不存在: {docx_path}")

    logger.info("转换成功: %s", docx_path)
    return str(docx_path)


def _parse_doc_with_olefile(doc_path: str) -> list[Paragraph]:
    """降级方案：用 olefile 提取 .doc 中的纯文本"""
    try:
        import olefile
        import charset_normalizer
    except ImportError:
        raise RuntimeError(
            "olefile 或 charset_normalizer 未安装，无法降级解析 .doc 文件"
        )

    logger.warning("使用 olefile 降级解析（无表格/样式信息）: %s", doc_path)

    ole = olefile.OleFileIO(doc_path)
    if not ole.exists("WordDocument"):
        raise ValueError(f"不是有效的 Word .doc 文件: {doc_path}")

    # 尝试从 1Table 或 0Table 读取文本流
    text = ""
    for stream_name in ["WordDocument"]:
        if ole.exists(stream_name):
            raw = ole.openstream(stream_name).read()
            # 检测编码
            detection = charset_normalizer.detect(raw)
            encoding = detection.get("encoding") or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")
            break

    ole.close()

    # 按换行切分段落，过滤不可读字符
    paragraphs = []
    idx = 0
    for line in text.split("\n"):
        # 只保留含有可读中文或英文字符的行
        cleaned = "".join(c for c in line if c.isprintable())
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        # 至少含有1个中文或英文字母才保留
        has_readable = any(
            ("\u4e00" <= c <= "\u9fff") or c.isalpha() for c in cleaned
        )
        if not has_readable:
            continue
        paragraphs.append(Paragraph(
            index=idx,
            text=cleaned,
            style=None,
            is_table=False,
            table_data=None,
        ))
        idx += 1

    return paragraphs


def parse_doc(file_path: str) -> list[Paragraph]:
    """解析 .doc 文件。优先使用 LibreOffice 转换，失败则降级为 olefile。"""
    soffice = _find_soffice()

    if soffice:
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                docx_path = _convert_doc_to_docx(file_path, tmp_dir)
                return parse_docx(docx_path)
        except Exception as e:
            logger.warning("LibreOffice 转换失败，尝试 olefile 降级: %s", e)

    # 降级到 olefile
    return _parse_doc_with_olefile(file_path)
