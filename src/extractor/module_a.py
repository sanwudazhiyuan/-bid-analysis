"""module_a: A. 项目基本信息 提取模块"""
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_a.txt"


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与项目基本信息相关的段落。返回 (段落列表, 得分映射)。"""
    return filter_paragraphs_by_score(
        tagged_paragraphs, "module_a",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=10,
    )



def extract_module_a(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 A. 项目基本信息。

    返回结构化 JSON dict，失败时返回 None。
    """
    # 1. 筛选相关段落
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_a: 未筛选到相关段落")
        return None

    logger.info("module_a: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    # 2. 加载 prompt
    system_prompt = load_prompt_template(str(PROMPT_PATH))

    # 3. 构建输入文本（附带得分标记）
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("module_a: 输入文本约 %d tokens", total_tokens)

    # 4. 调用 LLM
    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_a: LLM 返回 None")
        return None

    # 5. 确保 title 字段
    if "title" not in result:
        result["title"] = "A. 项目基本信息"

    return result
