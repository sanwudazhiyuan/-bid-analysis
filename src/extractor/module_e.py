"""module_e: E. 废标/无效标风险提示 提取模块

需要全文扫描：废标条款散落在文档各处（投标须知、评分标准、资格条件等）。
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

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_e.txt"

_RELEVANT_TAGS = {"风险", "资格", "格式"}
_RELEVANT_SECTION_KEYWORDS = [
    "须知", "资格", "评标", "评分", "投标", "废标", "无效",
    "密封", "递交", "格式", "要求", "条件",
]


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    """筛选与废标/无效标风险相关的段落。

    module_e 需要扫描全文范围较广，因为废标条款散落各处。
    """
    text_keywords = [
        "废标", "无效", "否则", "必须", "应当", "不得",
        "拒绝", "取消", "不予", "不接受", "视为放弃",
        "密封", "截止时间", "逾期", "迟到",
        "不得分", "扣除", "扣分", "零分",
        "原件", "加盖公章", "法人签字",
        "资格审查", "符合性审查",
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

    # 向量语义匹配补漏
    if embeddings_map and module_embedding:
        from src.extractor.embedding import filter_by_similarity
        extra = filter_by_similarity(
            tagged_paragraphs, embeddings_map, module_embedding,
            exclude_indices=selected_indices,
        )
        for tp in extra:
            selected.append(tp)
            selected_indices.add(tp.index)

    # module_e 范围广，如果筛选太少则取更多段落
    if len(selected) < 10 and len(tagged_paragraphs) > 0:
        count = max(int(len(tagged_paragraphs) * 0.4), 20)
        for tp in tagged_paragraphs[:count]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    selected.sort(key=lambda tp: tp.index)
    return selected



def extract_module_e(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 E. 废标/无效标风险提示。"""
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_e: 未筛选到相关段落")
        return None

    logger.info("module_e: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered)
    total_tokens = estimate_tokens(input_text)
    logger.info("module_e: 输入文本约 %d tokens", total_tokens)

    # 废标条款可能涉及全文，可能需要分批
    if total_tokens > 120000:
        logger.info("module_e: 输入超过 120K tokens，分批处理")
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for i, batch in enumerate(batches):
            batch_text = build_input_text(batch)
            messages = build_messages(system=system_prompt, user=batch_text)
            batch_result = call_qwen(messages, settings)
            if batch_result:
                results.append(batch_result)
            logger.info("module_e: 批次 %d/%d 完成", i + 1, len(batches))
        if not results:
            return None
        result = merge_batch_results(results)
    else:
        messages = build_messages(system=system_prompt, user=input_text)
        result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_e: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "E. 废标/无效标风险提示"

    return result
