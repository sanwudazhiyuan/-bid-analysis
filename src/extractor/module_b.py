"""module_b: B. 投标人资格条件 提取模块"""
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_b.txt"


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与投标人资格条件相关的段落。返回 (段落列表, 得分映射)。"""
    return filter_paragraphs_by_score(
        tagged_paragraphs, "module_b",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=5,
    )



def extract_module_b(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 B. 投标人资格条件。"""
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_b: 未筛选到相关段落")
        return None

    logger.info("module_b: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("module_b: 输入文本约 %d tokens", total_tokens)

    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_b: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "B. 投标人资格条件"

    return result
