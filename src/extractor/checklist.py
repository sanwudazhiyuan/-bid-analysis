"""checklist: 投标所需资料清单 提取模块

驱动独立的 .docx 交付物（资料清单）。
需要全文扫描：材料要求散落在各个章节中。
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "checklist.txt"

_RELEVANT_TAGS = {"材料", "资格"}
_RELEVANT_SECTION_KEYWORDS = [
    "资格", "条件", "投标文件", "评分", "须知",
    "材料", "证明", "附件", "格式", "组成",
]


def _filter_paragraphs(tagged_paragraphs: list[TaggedParagraph]) -> list[TaggedParagraph]:
    """筛选与资料清单相关的段落。

    checklist 需要全文扫描，材料要求散落在各处。
    """
    text_keywords = [
        "提供", "提交", "资质", "证明", "材料",
        "营业执照", "身份证", "授权", "复印件", "原件",
        "加盖公章", "扫描件", "有效期",
        "技术方案", "报价表", "投标函",
        "业绩", "合同", "中标通知", "案例",
        "ISO", "认证", "许可证", "资格证",
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

    # checklist 范围广，如果筛选太少则补充更多
    if len(selected) < 15 and len(tagged_paragraphs) > 0:
        count = max(int(len(tagged_paragraphs) * 0.4), 20)
        for tp in tagged_paragraphs[:count]:
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


def extract_checklist(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
) -> dict | None:
    """提取投标所需资料清单。"""
    filtered = _filter_paragraphs(tagged_paragraphs)
    if not filtered:
        logger.warning("checklist: 未筛选到相关段落")
        return None

    logger.info("checklist: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    total_tokens = estimate_tokens(input_text)
    logger.info("checklist: 输入文本约 %d tokens", total_tokens)

    if total_tokens > 120000:
        logger.info("checklist: 输入超过 120K tokens，分批处理")
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
        logger.error("checklist: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "投标所需资料清单"

    return result
