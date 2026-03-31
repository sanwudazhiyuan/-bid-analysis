"""Map review clauses to tender document chapters via LLM."""
import logging
from pathlib import Path

from src.extractor.base import call_qwen, build_messages

logger = logging.getLogger(__name__)

_MAPPING_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_mapping.txt"
_TOC_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_toc.txt"


def llm_extract_toc(paragraphs, api_settings: dict | None = None) -> list[dict]:
    """Use LLM to extract TOC when document TOC is not detected."""
    system_prompt = _TOC_PROMPT_PATH.read_text(encoding="utf-8")
    # Build text in batches of ~30k tokens
    all_chapters = []
    text_lines = [f"[{p.index}] {p.text}" for p in paragraphs]
    full_text = "\n".join(text_lines)

    # Simple batching by character count (~30k tokens ≈ 50k chars for Chinese)
    batch_size = 50000
    for start in range(0, len(full_text), batch_size):
        batch_text = full_text[start:start + batch_size]
        messages = build_messages(system=system_prompt, user=batch_text)
        result = call_qwen(messages, api_settings)
        if result and "chapters" in result:
            all_chapters.extend(result["chapters"])

    # Deduplicate by title
    seen = set()
    unique = []
    for ch in all_chapters:
        title = ch.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(ch)

    return unique


def llm_map_clauses_to_chapters(
    clauses: list[dict], tender_index: dict, api_settings: dict | None = None
) -> dict[int, list[str]]:
    """[DEPRECATED] Use llm_map_clauses_to_leaf_nodes instead.

    Map clause indices to relevant chapter titles via LLM.

    Returns: {clause_index: [chapter_title, ...]}
    """
    chapter_titles = [ch["title"] for ch in tender_index.get("chapters", [])]
    for ch in tender_index.get("chapters", []):
        for child in ch.get("children", []):
            chapter_titles.append(child["title"])

    clauses_text = "\n".join(
        f"[{c['clause_index']}] [{c['severity']}] {c['clause_text']}"
        for c in clauses
    )
    chapters_text = "\n".join(f"- {t}" for t in chapter_titles)

    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{clauses}", clauses_text).replace("{chapters}", chapters_text)

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    mapping = {}
    if isinstance(result, list):
        for item in result:
            idx = item.get("clause_index")
            chapters = item.get("relevant_chapters", [])
            if idx is not None:
                mapping[idx] = chapters
    elif isinstance(result, dict) and "mappings" in result:
        for item in result["mappings"]:
            idx = item.get("clause_index")
            chapters = item.get("relevant_chapters", [])
            if idx is not None:
                mapping[idx] = chapters

    return mapping


def _build_chapter_tree_text(tender_index: dict) -> str:
    """将章节树格式化为供 LLM 阅读的缩进文本。"""
    lines: list[str] = []

    def _walk(nodes: list[dict], depth: int = 0) -> None:
        indent = "  " * depth
        for node in nodes:
            leaf_tag = ", 叶子" if node.get("is_leaf") else ""
            split_tag = ", 需拆分" if node.get("needs_split") else ""
            lines.append(
                f"{indent}{node['path']} [段落数: {node.get('para_count', 0)}{leaf_tag}{split_tag}]"
            )
            _walk(node.get("children", []), depth + 1)

    _walk(tender_index.get("chapters", []))
    return "\n".join(lines)


def llm_map_clauses_to_leaf_nodes(
    clauses: list[dict],
    tender_index: dict,
    api_settings: dict | None = None,
) -> dict[int, list[str]]:
    """Map clauses to leaf node paths. Returns {clause_index: [path, ...]}.

    替代 llm_map_clauses_to_chapters，映射到精确的叶子节点 path 而非章节标题。
    """
    chapter_tree_text = _build_chapter_tree_text(tender_index)

    clauses_text = "\n".join(
        f"[{c['clause_index']}] [{c['severity']}] {c['clause_text']}"
        for c in clauses
    )

    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{clauses}", clauses_text)
        .replace("{chapter_tree}", chapter_tree_text)
    )

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    mapping: dict[int, list[str]] = {}
    if isinstance(result, list):
        for item in result:
            idx = item.get("clause_index")
            paths = item.get("relevant_paths", [])
            if idx is not None:
                mapping[idx] = paths
    elif isinstance(result, dict) and "mappings" in result:
        for item in result["mappings"]:
            idx = item.get("clause_index")
            paths = item.get("relevant_paths", [])
            if idx is not None:
                mapping[idx] = paths

    return mapping
