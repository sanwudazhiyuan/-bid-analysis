"""Build chapter index from TOC entries + paragraphs."""
import difflib
import logging
from dataclasses import dataclass
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


logger = logging.getLogger(__name__)

LEAF_SPLIT_THRESHOLD = 1200
MAX_CHARS_PER_BATCH = 30000


@dataclass
class ClauseBatch:
    """一个条款在某个叶子节点上的段落批次。"""
    clause_index: int
    path: str
    batch_id: str
    paragraphs: list  # list[Paragraph]


def _normalize_path(path: str) -> str:
    """归一化 path：去除空格，统一全角/半角标点，用于模糊匹配。"""
    s = path.replace(" ", "").replace("\u3000", "").strip()
    # 全角→半角括号、冒号、逗号
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("：", ":").replace("，", ",")
    return s


def find_node_by_path(tender_index: dict, path: str) -> dict | None:
    """根据 path 查找节点（DFS），忽略空格差异。"""
    target = _normalize_path(path)
    def dfs(nodes):
        for node in nodes:
            if _normalize_path(node.get("path", "")) == target:
                return node
            found = dfs(node.get("children", []))
            if found:
                return found
        return None
    return dfs(tender_index.get("chapters", []))


def get_text_for_clause(
    clause_index: int,
    paths: list[str],
    tender_index: dict,
    paragraphs: list,
) -> list[ClauseBatch]:
    """为单个条款获取精确段落批次。

    每个 path 单独提取段落；叶子节点段落数 > 1200 时按字符数拆分。
    """
    batches: list[ClauseBatch] = []

    for path in paths:
        node = find_node_by_path(tender_index, path)
        if not node:
            logger.warning("Path not found: %s", path)
            continue

        node_paras = _get_paragraphs_in_node(node, paragraphs)
        if not node_paras:
            continue

        if len(node_paras) > LEAF_SPLIT_THRESHOLD:
            sub_batches = _split_by_char_count(node_paras, MAX_CHARS_PER_BATCH)
            for i, sub_paras in enumerate(sub_batches):
                batches.append(ClauseBatch(
                    clause_index=clause_index,
                    path=path,
                    batch_id=f"{path}#{i}",
                    paragraphs=sub_paras,
                ))
        else:
            batches.append(ClauseBatch(
                clause_index=clause_index,
                path=path,
                batch_id=f"{path}#0",
                paragraphs=node_paras,
            ))

    return batches


def _get_paragraphs_in_node(node: dict, paragraphs: list) -> list:
    """获取节点范围内的所有段落（排除子节点的标题段落）。"""
    start = node["start_para"]
    end = node["end_para"]

    # 收集所有后代节点的 start_para（即标题段落），排除自身
    child_starts: set[int] = set()
    def _collect_child_starts(children: list[dict]) -> None:
        for ch in children:
            child_starts.add(ch["start_para"])
            _collect_child_starts(ch.get("children", []))
    _collect_child_starts(node.get("children", []))

    return [p for p in paragraphs if start <= p.index <= end and p.index not in child_starts]


def _split_by_char_count(paragraphs: list, max_chars: int) -> list[list]:
    """按字符数拆分段落列表。"""
    batches: list[list] = []
    current_batch: list = []
    current_chars = 0

    for para in paragraphs:
        para_chars = len(para.text)
        if current_chars + para_chars > max_chars and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(para)
        current_chars += para_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def paragraphs_to_text(paragraphs: list) -> str:
    """将段落列表拼接为审查用文本。"""
    return "\n".join(f"[{p.index}] {p.text}" for p in paragraphs)


def map_batch_indices_to_global(result: dict, batch: ClauseBatch) -> dict:
    """校验 LLM 返回的段落索引是否在批次范围内，过滤无效索引。

    paragraphs_to_text 给 LLM 展示的是全局索引 [para.index]，
    所以 LLM 返回的 para_index 本身就是全局索引，不需要偏移转换。
    只需校验它是否在当前批次段落范围内。
    """
    batch_indices = {p.index for p in batch.paragraphs} if batch.paragraphs else set()

    valid_indices = []
    snippet = ""
    per_para_reasons: dict[int, str] = {}
    for loc in result.get("tender_locations", []):
        # 收集 per-para reasons
        loc_reasons = loc.get("per_para_reasons", {})
        for pi in loc.get("para_indices", []):
            try:
                pi = int(pi)
            except (TypeError, ValueError):
                continue
            if pi in batch_indices:
                valid_indices.append(pi)
                if pi in loc_reasons:
                    per_para_reasons[pi] = loc_reasons[pi]
            else:
                logger.debug("para_index %d not in batch %s range, skipping", pi, batch.batch_id)
        if not snippet:
            snippet = loc.get("text_snippet", "")

    result["tender_locations"] = [{
        "batch_id": batch.batch_id,
        "path": batch.path,
        "global_para_indices": valid_indices,
        "text_snippet": snippet,
        "per_para_reasons": per_para_reasons,
    }] if valid_indices else []

    return result
