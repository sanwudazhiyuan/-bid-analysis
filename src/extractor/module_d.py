"""module_d: D. 合同主要条款 提取模块"""
import logging
from pathlib import Path

from src.models import TaggedParagraph
from src.extractor.base import (
    load_prompt_template,
    build_messages,
    call_qwen,
    estimate_tokens,
)

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_d.txt"

_RELEVANT_TAGS = {"合同条款", "商务要求"}
_RELEVANT_SECTION_KEYWORDS = [
    "合同", "条款", "商务", "付款", "违约", "验收",
    "保修", "质保", "保密", "知识产权", "争议",
]


def _filter_paragraphs(tagged_paragraphs: list[TaggedParagraph]) -> list[TaggedParagraph]:
    """筛选与合同条款相关的段落。"""
    text_keywords = [
        "合同", "付款", "支付", "违约", "赔偿", "罚款",
        "验收", "保修", "质保", "保密", "知识产权",
        "签订", "履约", "保证金", "预付款", "尾款",
        "争议", "仲裁", "诉讼", "保险", "税费",
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

    if len(selected) < 5 and len(tagged_paragraphs) > 0:
        mid_start = len(tagged_paragraphs) // 3
        mid_end = mid_start + max(int(len(tagged_paragraphs) * 0.3), 10)
        for tp in tagged_paragraphs[mid_start:mid_end]:
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


def extract_module_d(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
) -> dict | None:
    """提取 D. 合同主要条款。"""
    filtered = _filter_paragraphs(tagged_paragraphs)
    if not filtered:
        logger.warning("module_d: 未筛选到相关段落")
        return None

    logger.info("module_d: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    logger.info("module_d: 输入文本约 %d tokens", estimate_tokens(input_text))

    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_d: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "D. 合同主要条款"

    return result
