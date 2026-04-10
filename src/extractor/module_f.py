"""module_f: F. 投标文件编制要求 提取模块"""
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

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_f.txt"

_RELEVANT_TAGS = {"格式", "材料"}
_RELEVANT_SECTION_KEYWORDS = [
    "投标文件", "文件格式", "编制", "须知", "密封", "装订",
    "递交", "份数", "格式", "组成",
]


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    """筛选与投标文件编制要求相关的段落。"""
    text_keywords = [
        "正本", "副本", "份数", "密封", "装订", "胶装",
        "A4", "签字", "盖章", "公章", "法人签字",
        "U盘", "光盘", "电子版", "投标文件组成",
        "递交", "送达", "投标文件格式",
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
        front_count = max(int(len(tagged_paragraphs) * 0.3), 10)
        for tp in tagged_paragraphs[:front_count]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    selected.sort(key=lambda tp: tp.index)
    return selected



def extract_module_f(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 F. 投标文件编制要求。"""
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_f: 未筛选到相关段落")
        return None

    logger.info("module_f: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered)
    logger.info("module_f: 输入文本约 %d tokens", estimate_tokens(input_text))

    messages = build_messages(system=system_prompt, user=input_text)
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_f: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "F. 投标文件编制要求"

    return result
