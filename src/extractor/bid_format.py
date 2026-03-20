"""bid_format: 投标文件格式模板 提取模块

驱动独立的 .docx 交付物（投标文件格式模板）。
投标文件格式通常在招标文件最后一章或附件中。
"""
import logging
from pathlib import Path

from src.models import TaggedParagraph
from src.extractor.base import (
    load_prompt_template,
    build_messages,
    call_qwen,
    estimate_tokens,
    batch_paragraphs,
    merge_batch_results,
)

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "bid_format.txt"

_RELEVANT_TAGS = {"格式", "材料"}
_RELEVANT_SECTION_KEYWORDS = [
    "投标文件格式", "附件", "附录", "格式", "模板",
    "投标函", "报价表", "开标一览表", "授权委托",
    "法定代表人", "投标文件组成",
]


def _filter_paragraphs(tagged_paragraphs: list[TaggedParagraph]) -> list[TaggedParagraph]:
    """筛选与投标文件格式模板相关的段落。

    投标文件格式通常在文档后半部分（附件/最后一章）。
    """
    text_keywords = [
        "投标函", "报价表", "开标一览表", "授权委托书",
        "法定代表人", "身份证明", "声明函", "承诺书",
        "致：", "兹证明", "特此声明", "模板", "格式",
        "投标文件格式", "附件",
    ]

    selected = []
    selected_indices = set()

    for tp in tagged_paragraphs:
        if tp.index in selected_indices:
            continue

        if tp.section_title and any(kw in tp.section_title for kw in _RELEVANT_SECTION_KEYWORDS):
            selected.append(tp)
            selected_indices.add(tp.index)
            continue

        if tp.tags and _RELEVANT_TAGS & set(tp.tags):
            selected.append(tp)
            selected_indices.add(tp.index)
            continue

        if any(kw in tp.text for kw in text_keywords):
            selected.append(tp)
            selected_indices.add(tp.index)
            continue

    # 投标文件格式通常在文档后半部分，如果筛选太少则补充后部段落
    if len(selected) < 10 and len(tagged_paragraphs) > 0:
        tail_start = max(int(len(tagged_paragraphs) * 0.6), 0)
        for tp in tagged_paragraphs[tail_start:]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    selected.sort(key=lambda tp: tp.index)
    return selected


def _build_input_text(paragraphs: list[TaggedParagraph]) -> str:
    lines = []
    for tp in paragraphs:
        prefix = f"[{tp.index}]"
        if tp.section_title:
            prefix += f" [{tp.section_title}]"
        lines.append(f"{prefix} {tp.text}")
    return "\n".join(lines)


def extract_bid_format(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
) -> dict | None:
    """提取投标文件格式模板。"""
    filtered = _filter_paragraphs(tagged_paragraphs)
    if not filtered:
        logger.warning("bid_format: 未筛选到相关段落")
        return None

    logger.info("bid_format: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    total_tokens = estimate_tokens(input_text)
    logger.info("bid_format: 输入文本约 %d tokens", total_tokens)

    if total_tokens > 120000:
        logger.info("bid_format: 输入超过 120K tokens，分批处理")
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for i, batch in enumerate(batches):
            batch_text = _build_input_text(batch)
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
        logger.error("bid_format: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "投标文件格式"

    return result
