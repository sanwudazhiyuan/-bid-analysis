"""module_g: G. 开评标流程 提取模块"""
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_g.txt"

_RELEVANT_TAGS = {"流程"}
_RELEVANT_SECTION_KEYWORDS = [
    "开标", "评标", "定标", "中标", "流程", "评审",
    "签订合同", "公示", "须知", "投诉", "质疑",
]


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    """筛选与开评标流程相关的段落。"""
    text_keywords = [
        "开标", "评标", "定标", "中标", "评审",
        "评标委员会", "中标候选人", "中标通知",
        "公示", "公告", "质疑", "投诉",
        "签订合同", "合同签订", "投产",
        "资格审查", "符合性审查", "详细评审",
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
        count = max(int(len(tagged_paragraphs) * 0.2), 10)
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


def extract_module_g(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 G. 开评标流程。"""
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_g: 未筛选到相关段落")
        return None

    logger.info("module_g: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    logger.info("module_g: 输入文本约 %d tokens", estimate_tokens(input_text))

    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_g: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "G. 开评标流程"

    return result
