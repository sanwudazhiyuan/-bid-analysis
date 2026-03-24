"""module_c: C. 评标办法与评分标准 提取模块

最复杂的模块之一：需精确提取评分表结构（多层嵌套的评分项及其分值）。
可能需要合并"评标办法"和"评分表"两个独立章节。
"""
import logging
import re
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

PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "module_c.txt"

_RELEVANT_TAGS = {"评分", "报价", "合同条款", "商务要求"}
_RELEVANT_SECTION_KEYWORDS = [
    "评标", "评分", "评审", "打分", "计分", "得分",
    "评标办法", "评分标准", "评分表", "评标标准",
    "报价", "价格", "商务", "技术评审",
    "后评价", "评价管理", "分配规则", "分配方式",
    "报价要求", "报价明细", "限价",
]


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


def _filter_paragraphs(tagged_paragraphs: list[TaggedParagraph]) -> list[TaggedParagraph]:
    """筛选与评标办法和评分标准相关的段落。

    评分内容可能出现在：
    - 评标办法专章
    - 评分表/评分标准附件
    - 投标须知中的评标相关条款
    """
    text_keywords = [
        "评标", "评分", "评审", "打分", "计分", "得分",
        "总分", "满分", "权重", "分值",
        "报价得分", "价格得分", "技术得分", "商务得分",
        "最低价", "基准价", "综合评分", "评标委员会",
        "扣分", "加分", "不得分",
        # 报价与商务扩展
        "报价方式", "报价范围", "报价限制", "限价", "单价",
        "后评价", "评价指标", "评价运用",
        "分配规则", "分配比例",
        "履约保证金",
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

    # 评分表可能在表格中，检查包含数字分值的段落
    for tp in tagged_paragraphs:
        if tp.index in selected_indices:
            continue
        if tp.table_data and ("分" in tp.text or "%" in tp.text):
            selected.append(tp)
            selected_indices.add(tp.index)

    if len(selected) < 5 and len(tagged_paragraphs) > 0:
        mid = len(tagged_paragraphs) // 2
        count = max(int(len(tagged_paragraphs) * 0.2), 10)
        for tp in tagged_paragraphs[mid : mid + count]:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    # 交叉引用解析：检测已筛选段落中的引用，追加被引用段落
    ref_appended = _resolve_references(selected, tagged_paragraphs, selected_indices)
    if ref_appended:
        selected.extend(ref_appended)
        logger.info("module_c: 交叉引用追加了 %d 个段落", len(ref_appended))

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


def extract_module_c(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
) -> dict | None:
    """提取 C. 评标办法与评分标准。"""
    filtered = _filter_paragraphs(tagged_paragraphs)
    if not filtered:
        logger.warning("module_c: 未筛选到相关段落")
        return None

    logger.info("module_c: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    total_tokens = estimate_tokens(input_text)
    logger.info("module_c: 输入文本约 %d tokens", total_tokens)

    # 评分标准可能很长，检查是否需要分批
    if total_tokens > 120000:
        logger.info("module_c: 输入超过 120K tokens，分批处理")
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for i, batch in enumerate(batches):
            batch_text = _build_input_text(batch)
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
        result["title"] = "C. 评标办法与评分标准"

    return result
