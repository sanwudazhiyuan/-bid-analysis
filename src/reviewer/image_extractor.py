"""Extract embedded images from docx and PDF files.

Returns metadata about each image: filename, saved path, and approximate
paragraph position for cross-referencing in the preview UI.
"""
import os
import logging
from zipfile import ZipFile

logger = logging.getLogger(__name__)

_MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
}


def extract_images(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from a document file.

    Args:
        file_path: Path to the docx or PDF file.
        output_dir: Directory to save extracted images.

    Returns:
        List of dicts: [{filename, path, near_para_index, near_para_indices, content_type}]

        near_para_indices is the full list of paragraph indices that reference this image;
        near_para_index is kept as indices[0] for backward compatibility.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return _extract_from_docx(file_path, output_dir)
    elif ext == ".pdf":
        return _extract_from_pdf(file_path, output_dir)
    return []


def _extract_from_docx(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from docx by reading the media/ directory in the zip.

    Also parses document.xml.rels to map images to paragraph positions.
    """
    os.makedirs(output_dir, exist_ok=True)
    images = []

    try:
        with ZipFile(file_path, "r") as zf:
            media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
            if not media_files:
                return []

            # Build rId → media filename mapping from rels
            rid_to_media = {}
            rels_path = "word/_rels/document.xml.rels"
            if rels_path in zf.namelist():
                from lxml import etree
                rels_xml = etree.fromstring(zf.read(rels_path))
                for rel in rels_xml:
                    target = rel.get("Target", "")
                    rid = rel.get("Id", "")
                    if "media/" in target:
                        rid_to_media[rid] = target.split("/")[-1]

            # Find paragraph positions of images via document.xml
            # A single physical image can be referenced by multiple paragraphs
            # (e.g., same certificate appears in both 资格证明 and 技术部分 chapters).
            # We must record ALL referencing paragraphs, not just the last one.
            para_image_map: dict[str, list[int]] = {}  # media_filename → [para_index, ...]
            if "word/document.xml" in zf.namelist():
                from lxml import etree
                doc_xml = etree.fromstring(zf.read("word/document.xml"))
                ns = {
                    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
                    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
                }
                # Iterate only body-level children (matching parse_docx behavior)
                # parse_docx skips empty paragraphs (no run text) — they get no index.
                # For image-only paragraphs (no text but has image), we associate the
                # image with the NEXT text paragraph's index (para_idx), so the image
                # displays next to the first paragraph after it.
                body = doc_xml.find(f"{{{ns['w']}}}body")
                w_p = f"{{{ns['w']}}}p"
                w_tbl = f"{{{ns['w']}}}tbl"
                w_r = f"{{{ns['w']}}}r"
                w_t = f"{{{ns['w']}}}t"
                para_idx = 0
                pending_images = []  # images from text-empty paragraphs
                if body is not None:
                    for child in body:
                        if child.tag == w_p:
                            # Check text content (matching parse_docx lines 28-34)
                            runs_text = []
                            for r in child.findall(w_r):
                                t = r.find(w_t)
                                if t is not None and t.text:
                                    runs_text.append(t.text)
                            has_text = bool("".join(runs_text).strip())

                            # Check if this paragraph contains an image
                            blip_elems = child.findall(".//a:blip", ns)
                            found_images = []
                            for blip in blip_elems:
                                embed = blip.get(f"{{{ns['r']}}}embed")
                                if embed and embed in rid_to_media:
                                    found_images.append(rid_to_media[embed])

                            def _append_ref(media_fn: str, idx: int) -> None:
                                lst = para_image_map.setdefault(media_fn, [])
                                if not lst or lst[-1] != idx:
                                    lst.append(idx)

                            if has_text:
                                # 图片专用段落（无文字仅有图片）通常与紧随其后的文字段落
                                # 属于同一逻辑内容（如证书图片+证书标题），应关联到当前
                                # 文字段落的索引，而非前一个段落。
                                for media_fn in pending_images:
                                    _append_ref(media_fn, para_idx)
                                pending_images.clear()
                                # Assign current paragraph's images
                                for media_fn in found_images:
                                    _append_ref(media_fn, para_idx)
                                para_idx += 1
                            else:
                                # Image-only paragraph: defer to next text paragraph
                                pending_images.extend(found_images)
                        elif child.tag == w_tbl:
                            # Flush pending images to the table's index (images visually
                            # adjacent to the table should be associated with it).
                            for media_fn in pending_images:
                                lst = para_image_map.setdefault(media_fn, [])
                                if not lst or lst[-1] != para_idx:
                                    lst.append(para_idx)
                            pending_images.clear()
                            # Table images
                            blip_elems = child.findall(".//a:blip", ns)
                            for blip in blip_elems:
                                embed = blip.get(f"{{{ns['r']}}}embed")
                                if embed and embed in rid_to_media:
                                    media_fn = rid_to_media[embed]
                                    lst = para_image_map.setdefault(media_fn, [])
                                    if not lst or lst[-1] != para_idx:
                                        lst.append(para_idx)
                            para_idx += 1
                    # Handle trailing pending images (assign to last index)
                    if pending_images and para_idx > 0:
                        tail_idx = para_idx - 1
                        for media_fn in pending_images:
                            lst = para_image_map.setdefault(media_fn, [])
                            if not lst or lst[-1] != tail_idx:
                                lst.append(tail_idx)

            # Extract each media file
            for media_path in media_files:
                filename = os.path.basename(media_path)
                # Skip non-image files (e.g., .emf, .wmf are usually decorative)
                ext_lower = os.path.splitext(filename)[1].lower()
                if ext_lower not in _MIME_TYPES:
                    continue

                out_path = os.path.join(output_dir, filename)
                with open(out_path, "wb") as f:
                    f.write(zf.read(media_path))

                content_type = _MIME_TYPES[ext_lower]

                indices = para_image_map.get(filename, [])
                images.append({
                    "filename": filename,
                    "path": out_path,
                    "near_para_index": indices[0] if indices else None,
                    "near_para_indices": indices,
                    "content_type": content_type,
                })

    except Exception as e:
        logger.warning("Failed to extract images from docx: %s", e)

    logger.info(
        "图片提取完成: %d 张, 映射关系: %s",
        len(images),
        {img["filename"]: img.get("near_para_indices") for img in images}
    )
    return images


def _extract_from_pdf(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from PDF using pymupdf (fitz) if available."""
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.info("pymupdf not installed, skipping PDF image extraction")
        return []

    os.makedirs(output_dir, exist_ok=True)
    images = []

    try:
        doc = fitz.open(file_path)
        img_index = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    ext = base_image["ext"]
                    dot_ext = f".{ext}"
                    if dot_ext not in _MIME_TYPES:
                        continue
                    filename = f"page{page_num+1}_img{img_index}.{ext}"
                    out_path = os.path.join(output_dir, filename)
                    with open(out_path, "wb") as f:
                        f.write(base_image["image"])
                    content_type = _MIME_TYPES[dot_ext]
                    images.append({
                        "filename": filename,
                        "path": out_path,
                        "near_para_index": None,  # PDF images lack precise paragraph mapping
                        "near_para_indices": [],
                        "content_type": content_type,
                        "page": page_num + 1,
                    })
                    img_index += 1
                except Exception:
                    continue
        doc.close()
    except Exception as e:
        logger.warning("Failed to extract images from PDF: %s", e)

    return images
