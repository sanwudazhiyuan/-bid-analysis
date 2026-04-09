"""将投标文件章节树 + 段落生成为磁盘文件夹结构，供 haha-code 智能体读取。"""
import os
import re
import shutil
import logging

from src.models import Paragraph

logger = logging.getLogger(__name__)

_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name: str) -> str:
    """清理文件/文件夹名称中的不安全字符。"""
    if not name:
        return "_"
    return _UNSAFE_RE.sub("_", name)


def _build_leaf_md(
    title: str,
    paragraphs: list[Paragraph],
    images: list[dict],
    images_rel_prefix: str = "images",
) -> str:
    """为叶子节点生成 Markdown 内容。

    每个段落以 [Pxxx] 标记，图片以 ![图片](<prefix>/xxx.png) 引用。
    images_rel_prefix 是从当前 MD 文件到根目录 images/ 的相对路径。
    """
    lines = [f"# {title}", ""]

    # 图片按 near_para_index 分组
    image_by_para: dict[int, list[str]] = {}
    for img in images:
        pi = img.get("near_para_index")
        if pi is not None:
            image_by_para.setdefault(pi, []).append(img["filename"])

    for p in paragraphs:
        lines.append(f"[P{p.index}] {p.text}")
        # 在段落后插入该段落关联的图片
        for fn in image_by_para.get(p.index, []):
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
    extracted_images: list[dict],
    output_dir: str,
) -> str:
    """将投标文件按章节树生成文件夹结构。

    图片统一存放在 output_dir/images/，MD 中用相对路径引用。
    父节点如果有子节点未覆盖的段落，生成 _概述.md。

    Args:
        paragraphs: 投标文件段落列表
        tender_index: 章节树（含 chapters）
        extracted_images: 已提取的图片信息 [{filename, path, near_para_index}]
        output_dir: 输出根目录

    Returns:
        输出目录路径
    """
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    chapters = tender_index.get("chapters", [])

    # 图片按 near_para_index 分组
    image_by_para: dict[int, list[dict]] = {}
    for img in extracted_images:
        pi = img.get("near_para_index")
        if pi is not None:
            image_by_para.setdefault(pi, []).append(img)

    # 统一复制所有图片到 output_dir/images/
    if extracted_images:
        img_root = os.path.join(output_dir, "images")
        os.makedirs(img_root, exist_ok=True)
        for img in extracted_images:
            src = img.get("path", "")
            if src and os.path.isfile(src):
                dst = os.path.join(img_root, img["filename"])
                shutil.copy2(src, dst)

    def _images_rel_prefix(depth: int) -> str:
        """根据 MD 文件所在深度计算到根 images/ 的相对路径。"""
        if depth == 0:
            return "images"
        return "/".join([".."] * depth) + "/images"

    # 递归生成文件夹
    def _write_node(node: dict, parent_dir: str, depth: int = 0):
        title = node["title"]
        safe_title = _sanitize_filename(title)
        children = node.get("children", [])
        start = node.get("start_para", 0)
        end = node.get("end_para", 0)

        if children:
            # 非叶子：创建子目录
            node_dir = os.path.join(parent_dir, safe_title)
            os.makedirs(node_dir, exist_ok=True)

            # 检查父节点是否有子节点未覆盖的段落
            children_start = min(c.get("start_para", 0) for c in children)
            if start < children_start:
                intro_paras = [p for p in paragraphs if start <= p.index < children_start]
                if intro_paras:
                    intro_images = []
                    for p in intro_paras:
                        intro_images.extend(image_by_para.get(p.index, []))
                    prefix = _images_rel_prefix(depth + 1)
                    md = _build_leaf_md(f"{title} 概述", intro_paras, intro_images, prefix)
                    with open(os.path.join(node_dir, "_概述.md"), "w", encoding="utf-8") as f:
                        f.write(md)

            for child in children:
                _write_node(child, node_dir, depth + 1)
        else:
            # 叶子：生成 MD 文件
            node_paras = [p for p in paragraphs if start <= p.index <= end]
            node_images = []
            for p in node_paras:
                node_images.extend(image_by_para.get(p.index, []))

            prefix = _images_rel_prefix(depth)
            md_content = _build_leaf_md(title, node_paras, node_images, prefix)
            md_path = os.path.join(parent_dir, f"{safe_title}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

    for chapter in chapters:
        _write_node(chapter, output_dir, depth=0)

    # 生成目录文件
    toc_content = _build_toc_md(chapters)
    with open(os.path.join(output_dir, "_目录.md"), "w", encoding="utf-8") as f:
        f.write(toc_content)

    # 生成图片索引文件：为智能体提供全局图片清单
    if extracted_images:
        image_index_content = _build_image_index_md(extracted_images, paragraphs)
        with open(os.path.join(output_dir, "_图片索引.md"), "w", encoding="utf-8") as f:
            f.write(image_index_content)

    logger.info("Tender folder built at %s with %d chapters, %d images", output_dir, len(chapters), len(extracted_images))
    return output_dir


def _build_image_index_md(
    extracted_images: list[dict],
    paragraphs: list,
) -> str:
    """生成全局图片索引文件，列出所有图片及其关联的段落上下文。

    每个图片条目包含：
    - 文件名和格式
    - 关联的段落索引 [Pxxx] 和文本片段
    - Markdown 引用路径
    """
    lines = ["# 图片索引", ""]
    lines.append(f"共 {len(extracted_images)} 张图片。审查时请逐一使用 Read 工具查看。")
    lines.append("")

    para_map = {p.index: p.text for p in paragraphs}

    for i, img in enumerate(extracted_images, 1):
        fn = img["filename"]
        ext = os.path.splitext(fn)[1].lower()
        near_pi = img.get("near_para_index")

        lines.append(f"## {i}. `{fn}`")
        lines.append(f"- 格式: {ext.lstrip('.').upper()}")
        lines.append(f"- 路径: `images/{fn}`")

        if near_pi is not None and near_pi in para_map:
            text_snippet = para_map[near_pi][:100]
            lines.append(f"- 关联段落: [P{near_pi}] {text_snippet}")
        elif near_pi is not None:
            lines.append(f"- 关联段落索引: P{near_pi}（段落文本为空或已脱敏）")
        else:
            lines.append(f"- 关联段落: 无（独立图片）")

        lines.append("")

    lines.append("---")
    lines.append("**重要**: 审查签字盖章、营业执照、资质证书等条款时，必须逐一查看相关图片。")
    return "\n".join(lines)
