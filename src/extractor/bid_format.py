"""bid_format: 投标文件格式模板 提取模块

驱动独立的 .docx 交付物（投标文件格式模板）。
投标文件格式通常在招标文件最后一章或附件中。
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



def _summarize_modules(modules_context: dict) -> str:
    """将 module_a~g 结果精简为 LLM 可用的上下文文本。"""
    summaries = []
    for key, result in modules_context.items():
        if result is None or key in ("bid_format", "checklist"):
            continue
        if not isinstance(result, dict):
            continue
        title = result.get("title", key)
        sections = result.get("sections", [])
        section_titles = [s.get("title", "") for s in sections if isinstance(s, dict)]
        summary_line = f"## {title}"
        if section_titles:
            summary_line += f"\n包含: {', '.join(section_titles)}"
        summaries.append(summary_line)
    return "\n\n".join(summaries)


FALLBACK_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "bid_format_fallback.txt"


def extract_bid_format(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
    modules_context: dict | None = None,
) -> dict | None:
    """提取投标文件格式模板（两次调用策略）。

    第一次：判断招标文件是否包含格式样例，有则直接构建。
    第二次（仅在无样例时）：基于 module_a~g 结果按默认结构构建。
    """
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("bid_format: 未筛选到相关段落")
        return None

    logger.info("bid_format: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    # --- 第一次 LLM 调用：判断 + 构建 ---
    result = _first_pass(filtered, score_map, settings)
    if result and result.get("has_template") is not False:
        if "title" not in result:
            result["title"] = "投标文件格式"
        return result

    # --- 第二次 LLM 调用：基于模块结果构建 ---
    logger.info("bid_format: 未检测到格式样例，使用 fallback 构建")
    return _fallback_pass(modules_context, settings)


def _first_pass(filtered: list[TaggedParagraph], score_map: dict[int, int], settings: dict | None) -> dict | None:
    """第一次 LLM 调用：判断有无格式样例，有则直接构建。"""
    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("bid_format: 第一次调用，输入文本约 %d tokens", total_tokens)

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


def _fallback_pass(modules_context: dict | None, settings: dict | None) -> dict | None:
    """第二次 LLM 调用：基于 module_a~g 结果按默认结构构建。"""
    fallback_template = load_prompt_template(str(FALLBACK_PROMPT_PATH))
    modules_summary = _summarize_modules(modules_context or {})
    prompt = fallback_template.replace("{modules_summary}", modules_summary)
    messages = build_messages(system=prompt, user="请根据以上模块信息构建投标文件格式。")
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("bid_format: fallback LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "投标文件格式"

    return result
