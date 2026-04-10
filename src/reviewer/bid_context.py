"""从招标文件索引中构建章节树并提取条款相关原文上下文。

智能审核模式下，条款映射应映射到招标文件（而非投标文件）的章节，
提取招标原文作为上下文，帮助 agent 理解条款要求。
"""
import logging

from src.reviewer.chapter_tree import build_chapter_tree, collect_all_paths
from src.reviewer.tender_indexer import get_text_for_clause, paragraphs_to_text

logger = logging.getLogger(__name__)


def build_bid_chapter_index(indexed_data: dict) -> dict:
    """从招标解读的 indexed.json 数据构建 chapters 树结构。

    Args:
        indexed_data: indexed.json 的内容，包含 sections 和 tagged_paragraphs

    Returns:
        兼容 tender_index 格式的 dict:
        {
            "toc_source": "bid_indexed",
            "confidence": float,
            "chapters": [...],
            "all_paths": [...]
        }
    """
    sections = indexed_data.get("sections", [])
    if not sections:
        return {
            "toc_source": "bid_indexed",
            "confidence": 0,
            "chapters": [],
            "all_paths": [],
        }

    tagged_paragraphs = indexed_data.get("tagged_paragraphs", [])
    total_paragraphs = len(tagged_paragraphs)
    if total_paragraphs == 0:
        # 没有 tagged_paragraphs 时，用 sections 最后一个 start 估算
        total_paragraphs = max(s["start"] for s in sections) + 100

    chapters = build_chapter_tree(sections, total_paragraphs)
    all_paths = collect_all_paths(chapters)

    return {
        "toc_source": "bid_indexed",
        "confidence": indexed_data.get("confidence", 0),
        "chapters": chapters,
        "all_paths": all_paths,
    }


def extract_bid_context_for_clauses(
    clause_mapping: dict[int, list[str]],
    bid_index: dict,
    tagged_paragraphs: list,
) -> dict[int, str]:
    """根据条款映射结果从招标文件中提取相关原文上下文。

    Args:
        clause_mapping: {clause_index: [path, ...]} 条款到招标文件章节的映射
        bid_index: build_bid_chapter_index 返回的招标文件章节索引
        tagged_paragraphs: 招标文件的 TaggedParagraph 列表

    Returns:
        {clause_index: "招标原文文本"} 每个条款对应的招标文件原文
    """
    contexts: dict[int, str] = {}

    for clause_index, paths in clause_mapping.items():
        if not paths:
            continue

        batches = get_text_for_clause(clause_index, paths, bid_index, tagged_paragraphs)
        if batches:
            # 合并所有批次的文本
            all_texts = [paragraphs_to_text(batch.paragraphs) for batch in batches]
            contexts[clause_index] = "\n\n".join(all_texts)

    return contexts
