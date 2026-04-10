"""将投标文件章节树 + 段落生成为磁盘文件夹结构，供 haha-code 智能体读取。"""
import os
import re
import shutil
import logging
from PIL import Image

from src.models import Paragraph

logger = logging.getLogger(__name__)

# 图片压缩配置：限制单图尺寸，避免 agent 读取多张图片时累积超过 6MB
COMPRESSED_MAX_DIM = 800  # 最大宽高
COMPRESSED_JPEG_QUALITY = 70  # JPEG 质量


def _compress_image_for_folder(src_path: str, dst_path: str):
    """复制图片时预压缩，限制尺寸和质量。

    确保单张图片压缩后 < 200KB，即使 agent 读取多张也不会累积超限。
    """
    try:
        with Image.open(src_path) as img:
            # 限制尺寸
            img.thumbnail((COMPRESSED_MAX_DIM, COMPRESSED_MAX_DIM), Image.LANCZOS)
            # 统一转为 JPEG 以减小体积
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(dst_path, "JPEG", quality=COMPRESSED_JPEG_QUALITY, optimize=True)
    except Exception:
        # 压缩失败时直接复制原图
        logger.warning("Failed to compress image %s, copying as-is", src_path)
        shutil.copy2(src_path, dst_path)

_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name: str) -> str:
    """清理文件/文件夹名称中的不安全字符。"""
    if not name:
        return "_"
    return _UNSAFE_RE.sub("_", name)


def _build_leaf_md(
    title: str,
    paragraphs: list[Paragraph],
    image_descriptions: dict[int, list[str]],
    image_filenames: dict[int, list[str]],
    images_rel_prefix: str = "images",
) -> str:
    """为叶子节点生成 Markdown 内容。

    每个段落以 [Pxxx] 标记，图片包含：
    1. AI 预描述文本（优先阅读，纯文本无需 API 调用）
    2. 图片文件引用（描述不足时 agent 读取压缩版图片）

    表格段落额外渲染为 Markdown 表格格式。
    """
    lines = [f"# {title}", ""]

    for p in paragraphs:
        if p.is_table and p.table_data:
            # 渲染为 Markdown 表格
            lines.append(f"[P{p.index}] **表格**")
            # 表头
            header = p.table_data[0] if p.table_data else []
            sep = ["---"] * len(header)
            lines.append("| " + " | ".join(str(c) for c in header) + " |")
            lines.append("| " + " | ".join(sep) + " |")
            # 数据行
            for row in p.table_data[1:]:
                padded = row + [""] * (len(header) - len(row))
                lines.append("| " + " | ".join(str(c) for c in padded[:len(header)]) + " |")
        else:
            lines.append(f"[P{p.index}] {p.text}")

        # 先插入 AI 图片描述
        for desc in image_descriptions.get(p.index, []):
            lines.append(f"> [图片描述] {desc}")

        # 再插入图片文件引用（fallback，图片已预压缩）
        for fn in image_filenames.get(p.index, []):
            lines.append(f"![图片]({images_rel_prefix}/{fn})")

        lines.append("")

    return "\n".join(lines)


def _build_toc_md(chapters: list[dict]) -> str:
    """生成目录文件内容。"""
    lines = ["# 投标文件目录", ""]

    def _walk(nodes: list[dict], depth: int = 0):
        indent = "  " * depth
        for node in nodes:
            title = node["title"]
            children = node.get("children", [])
            start = node.get("start_para", 0)
            end = node.get("end_para", 0)
            if children:
                lines.append(f"{indent}- {_sanitize_filename(title)}/")
                _walk(children, depth + 1)
            else:
                lines.append(f"{indent}- {_sanitize_filename(title)}.md (P{start}-P{end})")

    _walk(chapters)
    return "\n".join(lines)


def build_tender_folder(
    paragraphs: list[Paragraph],
    tender_index: dict,
    image_descriptions: dict[str, str],
    image_para_map: dict[int, list[str]],
    image_para_files: dict[int, list[str]],
    extracted_images: list[dict],
    output_dir: str,
) -> str:
    """将投标文件按章节树生成文件夹结构。

    图片包含两种形式：
    1. AI 预描述文本：嵌入 MD 文件，智能体优先阅读
    2. 图片文件：保留原图，描述不足时可 fallback 读取

    Args:
        paragraphs: 投标文件段落列表
        tender_index: 章节树（含 chapters）
        image_descriptions: {filename: description} 映射
        image_para_map: {para_index: [description, ...]} 按段落分组的图片描述
        image_para_files: {para_index: [filename, ...]} 按段落分组的图片文件名
        extracted_images: 原始图片信息 [{filename, path, near_para_index}]
        output_dir: 输出根目录

    Returns:
        输出目录路径
    """
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    chapters = tender_index.get("chapters", [])

    # 构建原始文件名 → 压缩后文件名 的映射
    filename_map: dict[str, str] = {}

    # 复制所有图片到 output_dir/images/（预压缩作为 fallback）
    if extracted_images:
        img_root = os.path.join(output_dir, "images")
        os.makedirs(img_root, exist_ok=True)
        for img in extracted_images:
            src = img.get("path", "")
            if src and os.path.isfile(src):
                orig_name = img["filename"]
                base_name = os.path.splitext(orig_name)[0]
                compressed_name = base_name + ".jpg"
                dst = os.path.join(img_root, compressed_name)
                _compress_image_for_folder(src, dst)
                filename_map[orig_name] = compressed_name

    def _map_filenames(orig_files: dict[int, list[str]]) -> dict[int, list[str]]:
        """将原始文件名映射为压缩后的 .jpg 文件名。"""
        return {
            pi: [filename_map.get(fn, fn) for fn in fns]
            for pi, fns in orig_files.items()
        }

    compressed_file_map = _map_filenames(image_para_files)

    def _images_rel_prefix(depth: int) -> str:
        if depth == 0:
            return "images"
        return "/".join([".."] * depth) + "/images"

    def _write_node(node: dict, parent_dir: str, depth: int = 0):
        title = node["title"]
        safe_title = _sanitize_filename(title)
        children = node.get("children", [])
        start = node.get("start_para", 0)
        end = node.get("end_para", 0)

        if children:
            node_dir = os.path.join(parent_dir, safe_title)
            os.makedirs(node_dir, exist_ok=True)

            children_start = min(c.get("start_para", 0) for c in children)
            if start < children_start:
                intro_paras = [p for p in paragraphs if start <= p.index < children_start]
                if intro_paras:
                    intro_desc = {p.index: image_para_map[p.index] for p in intro_paras if p.index in image_para_map}
                    intro_files = {p.index: compressed_file_map[p.index] for p in intro_paras if p.index in compressed_file_map}
                    prefix = _images_rel_prefix(depth + 1)
                    md = _build_leaf_md(f"{title} 概述", intro_paras, intro_desc, intro_files, prefix)
                    with open(os.path.join(node_dir, "_概述.md"), "w", encoding="utf-8") as f:
                        f.write(md)

            for child in children:
                _write_node(child, node_dir, depth + 1)
        else:
            node_paras = [p for p in paragraphs if start <= p.index <= end]
            node_desc = {p.index: image_para_map[p.index] for p in node_paras if p.index in image_para_map}
            node_files = {p.index: compressed_file_map[p.index] for p in node_paras if p.index in compressed_file_map}

            prefix = _images_rel_prefix(depth)
            md_content = _build_leaf_md(title, node_paras, node_desc, node_files, prefix)
            md_path = os.path.join(parent_dir, f"{safe_title}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

    for chapter in chapters:
        _write_node(chapter, output_dir, depth=0)

    # 生成目录文件
    toc_content = _build_toc_md(chapters)
    with open(os.path.join(output_dir, "_目录.md"), "w", encoding="utf-8") as f:
        f.write(toc_content)

    # 生成图片索引文件
    if image_descriptions:
        image_index_content = _build_image_index_md(image_descriptions)
        with open(os.path.join(output_dir, "_图片索引.md"), "w", encoding="utf-8") as f:
            f.write(image_index_content)

    logger.info(
        "Tender folder built at %s with %d chapters, %d images, %d descriptions",
        output_dir, len(chapters), len(extracted_images), len(image_descriptions),
    )
    return output_dir


def _build_image_index_md(
    image_descriptions: dict[str, str],
) -> str:
    """生成全局图片索引文件，列出所有图片及其 AI 描述。"""
    lines = ["# 图片索引", ""]
    lines.append(f"共 {len(image_descriptions)} 张图片。")
    lines.append("图片已预先描述为文字并嵌入对应章节的 MD 文件中。")
    lines.append("如 AI 描述不够详细，可使用 Read 工具读取原始图片。")
    lines.append("")

    for i, (fn, desc) in enumerate(image_descriptions.items(), 1):
        lines.append(f"## {i}. `{fn}`")
        lines.append(f"{desc}")
        lines.append("")

    lines.append("---")
    lines.append("**重要**: 审查签字盖章、营业执照、资质证书等条款时，请优先阅读嵌入在 MD 文件中的图片描述。")
    lines.append("如描述信息不足以判定，再使用 Read 工具查看原始图片。")
    return "\n".join(lines)
