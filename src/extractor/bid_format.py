"""Layer 1 helpers for bid outline generation.

保留用于 `src.extractor.bid_outline._run_layer1` 的段落筛选工具。
对外的 `bid_format` 模块入口已迁移到 `src.extractor.bid_outline.extract_bid_outline`。
"""
import logging
from pathlib import Path

from src.models import TaggedParagraph
from src.extractor.base import (
    load_prompt_template,
    build_messages,
    build_input_text,
    call_qwen,
    estimate_tokens,
    batch_paragraphs,
    merge_batch_results,
)
from src.extractor.scoring import filter_paragraphs_by_score

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "bid_format.txt"


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与投标文件格式模板相关的段落。返回 (段落列表, 得分映射)。"""
    return filter_paragraphs_by_score(
        tagged_paragraphs, "bid_format",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=10,
    )


def _first_pass(filtered: list[TaggedParagraph], score_map: dict[int, int], settings: dict | None) -> dict | None:
    """Layer 1：调用 LLM 从已筛选段落中抽取格式样例（含 standard_table / 占位符）。"""
    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("bid_format layer1: 输入文本约 %d tokens", total_tokens)

    if total_tokens > 120000:
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for batch in batches:
            batch_text = build_input_text(batch, score_map)
            messages = build_messages(system=system_prompt, user=batch_text)
            batch_result = call_qwen(messages, settings)
            if batch_result:
                results.append(batch_result)
        if not results:
            return None
        return merge_batch_results(results)
    else:
        messages = build_messages(system=system_prompt, user=input_text)
        return call_qwen(messages, settings)
