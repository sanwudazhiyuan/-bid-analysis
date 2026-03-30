"""Build chapter index from TOC entries + paragraphs."""
import difflib
from src.models import Paragraph


def _fuzzy_match(title: str, para_text: str, threshold: float = 0.7) -> bool:
    """Check if paragraph text starts with or closely matches the TOC title."""
    # Exact prefix match
    clean_title = title.strip()
    clean_para = para_text.strip()
    if clean_para.startswith(clean_title):
        return True
    # Fuzzy match on the shorter of the two
    ratio = difflib.SequenceMatcher(None, clean_title, clean_para[:len(clean_title) + 20]).ratio()
    return ratio >= threshold


def build_index_from_toc(toc_entries: list[dict], paragraphs: list[Paragraph]) -> dict:
    """Map TOC entries to paragraph ranges using fuzzy title matching.

    Returns tender_index structure with chapters and their paragraph ranges.
    """
    chapters = []
    matched_positions = []

    for entry in toc_entries:
        title = entry["title"]
        level = entry.get("level", 1)
        # Search paragraphs for matching title
        for para in paragraphs:
            if _fuzzy_match(title, para.text):
                matched_positions.append({
                    "title": title,
                    "level": level,
                    "start_para": para.index,
                    "children": [],
                })
                break

    # Compute end_para for each chapter
    for i, ch in enumerate(matched_positions):
        if i + 1 < len(matched_positions):
            ch["end_para"] = matched_positions[i + 1]["start_para"] - 1
        else:
            ch["end_para"] = len(paragraphs) - 1

    # Build hierarchy (level 2+ becomes children of previous level 1)
    root_chapters = []
    current_parent = None
    for ch in matched_positions:
        if ch["level"] == 1:
            current_parent = ch
            root_chapters.append(ch)
        elif current_parent is not None:
            current_parent["children"].append(ch)
        else:
            root_chapters.append(ch)

    return {"chapters": root_chapters}


def get_chapter_text(
    paragraphs: list[Paragraph],
    tender_index: dict,
    chapter_titles: list[str],
) -> str:
    """Get concatenated text for specified chapters (by title match)."""
    lines = []
    all_chapters = []
    for ch in tender_index.get("chapters", []):
        all_chapters.append(ch)
        all_chapters.extend(ch.get("children", []))

    for ch in all_chapters:
        if any(ch["title"] in t or t in ch["title"] for t in chapter_titles):
            start = ch["start_para"]
            end = ch["end_para"]
            for para in paragraphs:
                if start <= para.index <= end:
                    lines.append(f"[{para.index}] {para.text}")

    return "\n".join(lines) if lines else ""
