"""Detect and extract Table of Contents from tender documents."""
import re
from src.models import Paragraph

# TOC line pattern: "第X章 标题 ... 页码" or "X.X 标题 ... 页码"
_TOC_LINE_RE = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节篇]|[\d]+(?:\.[\d]+)*)\s*"
    r"(.+?)"
    r"[\s.…·\-_]*(\d+)?\s*$"
)

def _parse_level(prefix: str) -> int:
    """Determine heading level from prefix. '第X章'→1, 'X.X'→dot count."""
    if prefix.startswith("第"):
        return 1
    return prefix.count(".") + 1 if "." in prefix else 1


def _has_toc_style(para: Paragraph) -> bool:
    return bool(para.style and ("toc" in para.style.lower() or "目录" in para.style.lower()))


def detect_toc(paragraphs: list[Paragraph]) -> list[dict] | None:
    """Detect and extract TOC entries from the first 50 paragraphs.

    Returns list of {title, level, page_hint} or None if no TOC found.
    """
    scan_range = paragraphs[:50]
    if not scan_range:
        return None

    # Strategy 1: TOC styles
    toc_entries = []
    for para in scan_range:
        if _has_toc_style(para) and para.text.strip() != "目录":
            m = _TOC_LINE_RE.match(para.text.strip())
            if m:
                prefix, title, page = m.group(1), m.group(2).strip(), m.group(3)
                toc_entries.append({
                    "title": f"{prefix} {title}".strip(),
                    "level": _parse_level(prefix),
                    "page_hint": int(page) if page else None,
                })
    if len(toc_entries) >= 3:
        return toc_entries

    # Strategy 2: Pattern matching after a "目录" heading
    toc_start = None
    for i, para in enumerate(scan_range):
        text = para.text.strip().replace(" ", "").replace("\u3000", "")
        if text in ("目录", "CONTENTS"):
            toc_start = i + 1
            break

    if toc_start is None:
        return None

    toc_entries = []
    consecutive_misses = 0
    for para in scan_range[toc_start:]:
        m = _TOC_LINE_RE.match(para.text.strip())
        if m:
            prefix, title, page = m.group(1), m.group(2).strip(), m.group(3)
            toc_entries.append({
                "title": f"{prefix} {title}".strip(),
                "level": _parse_level(prefix),
                "page_hint": int(page) if page else None,
            })
            consecutive_misses = 0
        else:
            consecutive_misses += 1
            if consecutive_misses >= 3:
                break

    return toc_entries if len(toc_entries) >= 5 else None
