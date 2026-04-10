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

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_a.txt"

# module_a 关注的标签和章节关键词
_RELEVANT_TAGS = {"资格", "流程", "报价"}
_RELEVANT_SECTION_KEYWORDS = [
    "公告", "概况", "简介", "项目", "须知", "邀请", "采购",
    "投标人", "供应商", "总则", "说明",
]


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    """筛选与项目基本信息相关的段落。

    策略：
    1. 段落所属章节标题包含相关关键词
    2. 段落标签与 module_a 相关
    3. 段落文本包含项目信息关键词（采购人、预算、截止时间等）
    4. 向量语义匹配补漏
    5. 如果筛选太少，取文档前 30% 段落（项目信息通常在文档前部）
    """
    text_keywords = [
        "项目名称", "采购编号", "采购人", "预算", "招标人",
        "代理机构", "截止时间", "开标时间", "投标截止", "服务期",
        "交付地点", "采购方式", "招标方式", "联系人", "联系电话",
        "采购内容", "采购需求",
    ]

    selected = []
    selected_indices = set()

    for tp in tagged_paragraphs:
        if tp.index in selected_indices:
            continue

        # 章节标题匹配
        if tp.section_title and any(kw in tp.section_title for kw in _RELEVANT_SECTION_KEYWORDS):
            selected.append(tp)
            selected_indices.add(tp.index)
            continue

        # 标签匹配
        if tp.tags and _RELEVANT_TAGS & set(tp.tags):
            selected.append(tp)
            selected_indices.add(tp.index)
            continue

        # 文本关键词匹配
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

    # 如果筛选结果太少，补充文档前 30% 段落
    if len(selected) < 10 and len(tagged_paragraphs) > 0:
        front_count = max(int(len(tagged_paragraphs) * 0.3), 10)
        for tp in tagged_paragraphs[:front_count]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    # 按原始顺序排列
    selected.sort(key=lambda tp: tp.index)
    return selected



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
    filtered = _filter_paragraphs(
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

    # 3. 构建输入文本
    input_text = build_input_text(filtered)
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
