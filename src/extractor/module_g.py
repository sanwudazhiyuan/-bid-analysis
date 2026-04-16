"""module_g: G. 开评标流程 提取模块"""
import logging
from pathlib import Path

from src.models import TaggedParagraph
from src.extractor.base import (
    load_prompt_template,
    build_messages,
    build_input_text,
    call_qwen,
    estimate_tokens,
)
from src.extractor.scoring import filter_paragraphs_by_score

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_g.txt"


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与开评标流程相关的段落。返回 (段落列表, 得分映射)。"""
    return filter_paragraphs_by_score(
        tagged_paragraphs, "module_g",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=5,
    )



def extract_module_g(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 G. 开评标流程。"""
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_g: 未筛选到相关段落")
        return None

    logger.info("module_g: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    logger.info("module_g: 输入文本约 %d tokens", estimate_tokens(input_text))

    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_g: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "G. 开评标流程"

    return result
