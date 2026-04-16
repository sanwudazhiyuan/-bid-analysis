"""module_c: C. 技术评分模块 提取模块

提取评分分值构成、报价/商务/技术评分标准、报价要求、后评价管理、分配规则。
支持多层嵌套子标题结构和交叉引用段落追加。
"""
import logging
import re
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_c.txt"


_REF_PATTERNS = [
    re.compile(r"详见[《「]?(.+?)[》」\s，。,.]|详见[《「]?(.+?)$"),
    re.compile(r"按照?[《「]?(.+?)[》」]?的?规定"),
    re.compile(r"据第\s*(\d+\.?\d*)\s*款"),
    re.compile(r"见附[件表录]\s*[《「]?(.+?)[》」\s，。,.]|见附[件表录]\s*[《「]?(.+?)$"),
    re.compile(r"参照[《「]?(.+?)[》」\s，。,.]|参照[《「]?(.+?)$"),
]


def _resolve_references(
    selected: list[TaggedParagraph],
    all_paragraphs: list[TaggedParagraph],
    selected_indices: set[int],
) -> list[TaggedParagraph]:
    """检测已筛选段落中的交叉引用，从全文档追加被引用段落。

    返回新追加的段落列表（不含已选中的）。
    """
    ref_targets: list[str] = []
    for tp in selected:
        for pattern in _REF_PATTERNS:
            for match in pattern.finditer(tp.text):
                # 多分支正则可能命中不同 group，取第一个非 None 的
                target = next((g for g in match.groups() if g is not None), None)
                if target:
                    ref_targets.append(target)

    if not ref_targets:
        return []

    appended: list[TaggedParagraph] = []
    for tp in all_paragraphs:
        if tp.index in selected_indices:
            continue
        for target in ref_targets:
            if tp.section_title and target in tp.section_title:
                appended.append(tp)
                selected_indices.add(tp.index)
                break
            if target in tp.text and len(target) >= 2:
                appended.append(tp)
                selected_indices.add(tp.index)
                break

    return appended


def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制筛选与评标办法和评分标准相关的段落。返回 (段落列表, 得分映射)。"""
    selected, score_map = filter_paragraphs_by_score(
        tagged_paragraphs, "module_c",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=5,
    )

    # 评分表可能在表格中，额外检查包含数字分值的段落
    selected_indices = {tp.index for tp in selected}
    for tp in tagged_paragraphs:
        if tp.index in selected_indices:
            continue
        if tp.table_data and ("分" in tp.text or "%" in tp.text):
            selected.append(tp)
            selected_indices.add(tp.index)
            score_map[tp.index] = 0

    # 交叉引用解析：检测已筛选段落中的引用，追加被引用段落
    ref_appended = _resolve_references(selected, tagged_paragraphs, selected_indices)
    if ref_appended:
        selected.extend(ref_appended)
        for tp in ref_appended:
            score_map[tp.index] = 0
        logger.info("module_c: 交叉引用追加了 %d 个段落", len(ref_appended))

    selected.sort(key=lambda tp: tp.index)
    return selected, score_map


def extract_module_c(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 C. 评标办法与评分标准。"""
    filtered, score_map = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("module_c: 未筛选到相关段落")
        return None

    logger.info("module_c: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = build_input_text(filtered, score_map)
    total_tokens = estimate_tokens(input_text)
    logger.info("module_c: 输入文本约 %d tokens", total_tokens)

    # 评分标准可能很长，检查是否需要分批
    if total_tokens > 120000:
        logger.info("module_c: 输入超过 120K tokens，分批处理")
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for i, batch in enumerate(batches):
            batch_text = build_input_text(batch, score_map)
            messages = build_messages(system=system_prompt, user=batch_text)
            batch_result = call_qwen(messages, settings)
            if batch_result:
                results.append(batch_result)
            logger.info("module_c: 批次 %d/%d 完成", i + 1, len(batches))
        if not results:
            return None
        result = merge_batch_results(results)
    else:
        messages = build_messages(system=system_prompt, user=input_text)
        result = call_qwen(messages, settings)

    if result is None:
        logger.error("module_c: LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "C. 技术评分模块"

    return result
