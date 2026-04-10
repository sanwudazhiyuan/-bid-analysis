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

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_b.txt"

_RELEVANT_TAGS = {"资格", "材料"}
_RELEVANT_SECTION_KEYWORDS = [
    "资格", "合格", "条件", "供应商", "投标人", "须知",
    "公告", "总则", "禁止", "要求",
]


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    """筛选与投标人资格条件相关的段落。"""
    text_keywords = [
        "营业执照", "注册资本", "资格条件", "投标人应", "投标人须",
        "法人资格", "失信", "禁止", "联合体", "资质", "许可证",
        "ISO", "认证", "信用", "经营范围", "纳税", "社保",
        "不得参加", "不允许", "排除", "行政处罚",
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

    if len(selected) < 5 and len(tagged_paragraphs) > 0:
        front_count = max(int(len(tagged_paragraphs) * 0.2), 10)
        for tp in tagged_paragraphs[:front_count]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    selected.sort(key=lambda tp: tp.index)
    return selected



def extract_module_b(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 B. 投标人资格条件。"""
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_b: 未筛选到相关段落")
        return None

    logger.info("module_b: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered)
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
