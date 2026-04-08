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


def _build_numbered_chapter_list(tender_index: dict) -> tuple[str, dict[int, str]]:
    """将章节树格式化为带编号的列表，返回 (文本, {编号: path}) 映射。

    LLM 只需返回编号，避免 path 字符串不匹配的问题。
    """
    lines: list[str] = []
    id_to_path: dict[int, str] = {}
    counter = [0]  # mutable counter for closure

    def _walk(nodes: list[dict], depth: int = 0) -> None:
        indent = "  " * depth
        for node in nodes:
            nid = counter[0]
            counter[0] += 1
            id_to_path[nid] = node["path"]
            leaf_tag = ", 叶子" if node.get("is_leaf") else ""
            split_tag = ", 需拆分" if node.get("needs_split") else ""
            lines.append(
                f"{indent}[{nid}] {node['title']} [段落数: {node.get('para_count', 0)}{leaf_tag}{split_tag}]"
            )
            _walk(node.get("children", []), depth + 1)

    _walk(tender_index.get("chapters", []))
    return "\n".join(lines), id_to_path


def _map_single_clause(
    clause: dict,
    chapter_list_text: str,
    id_to_path: dict[int, str],
    prompt_template: str,
    api_settings: dict | None,
) -> tuple[int, list[str]]:
    """映射单个条款到章节节点。返回 (clause_index, [path, ...])。"""
    prompt = (
        prompt_template
        .replace("{clause_index}", str(clause["clause_index"]))
        .replace("{severity}", clause["severity"])
        .replace("{clause_text}", clause["clause_text"])
        .replace("{chapter_tree}", chapter_list_text)
    )

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    paths = []
    raw_ids = []
    if isinstance(result, dict):
        raw_ids = result.get("relevant_node_ids", [])
    elif isinstance(result, list):
        raw_ids = result

    for rid in raw_ids:
        if isinstance(rid, int) or (isinstance(rid, str) and rid.isdigit()):
            real_path = id_to_path.get(int(rid))
            if real_path:
                paths.append(real_path)
            else:
                logger.warning("Unknown node id %s for clause %d", rid, clause["clause_index"])

    return clause["clause_index"], paths


def llm_map_clauses_to_leaf_nodes(
    clauses: list[dict],
    tender_index: dict,
    api_settings: dict | None = None,
    max_workers: int = 8,
) -> dict[int, list[str]]:
    """逐条并发映射条款到章节节点。Returns {clause_index: [path, ...]}.

    每个条款独立调用 LLM 映射，比批量映射更准确，通过并发保持效率。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    chapter_list_text, id_to_path = _build_numbered_chapter_list(tender_index)
    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")

    mapping: dict[int, list[str]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _map_single_clause, clause, chapter_list_text,
                id_to_path, prompt_template, api_settings,
            ): clause
            for clause in clauses
        }

        for future in as_completed(futures):
            clause = futures[future]
            try:
                clause_idx, paths = future.result()
                if paths:
                    mapping[clause_idx] = paths
            except Exception as e:
                logger.error("Clause mapping failed for %d: %s", clause["clause_index"], e)

    return mapping
