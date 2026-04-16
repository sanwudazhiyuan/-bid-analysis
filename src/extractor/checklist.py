"""checklist: 投标所需资料清单 提取模块

驱动独立的 .docx 交付物（资料清单）。
需要全文扫描：材料要求散落在各个章节中。
使用关键词得分制筛选相关段落。
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "checklist.txt"


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与资料清单相关的段落。返回 (段落列表, 得分映射)。"""
    return filter_paragraphs_by_score(
        tagged_paragraphs, "checklist",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=15,
    )



def extract_checklist(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取投标所需资料清单。"""
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("checklist: 未筛选到相关段落")
        return None

    logger.info("checklist: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("checklist: 输入文本约 %d tokens", total_tokens)

    if total_tokens > 120000:
        logger.info("checklist: 输入超过 120K tokens，分批处理")
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for i, batch in enumerate(batches):
            batch_text = build_input_text(batch, score_map)
            messages = build_messages(system=system_prompt, user=batch_text)
            batch_result = call_qwen(messages, settings)
            if batch_result:
                results.append(batch_result)
        if not results:
            return None
        result = merge_batch_results(results)
    else:
        messages = build_messages(system=system_prompt, user=input_text)
        result = call_qwen(messages, settings)

    if result is None:
        logger.error("checklist: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "投标所需资料清单"

    return result
