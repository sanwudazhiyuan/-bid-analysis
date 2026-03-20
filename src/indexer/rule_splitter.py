"""规则切分器：四种策略识别招标文件章节结构

策略优先级（由高到低）：
1. split_by_style — Word 文档的 Heading 样式
2. split_by_numbering — 正则匹配中文章节编号
3. split_by_keywords — 基于 synonyms.yaml 关键词匹配
4. 取置信度最高的策略结果
"""

import re
import logging
from src.models import Paragraph, TaggedParagraph
from src.config import load_synonyms

logger = logging.getLogger(__name__)

# ========== 编号模式正则 ==========
# Level 1: 第X章、第X部分、第X篇
_RE_CHAPTER = re.compile(
    r"^第[一二三四五六七八九十百零]+[章节篇部]"
    r"|^第[一二三四五六七八九十百零]+部分"
)

# Level 2: 一、二、三、 or 一. 二. (中文顶层序号，要求行首，且总长度<80)
_RE_ORDINAL = re.compile(
    r"^[一二三四五六七八九十]+[、\.\．]"
)

# Level 3: （一）（二）
_RE_PAREN = re.compile(
    r"^（[一二三四五六七八九十]+）"
    r"|^\([一二三四五六七八九十]+\)"
)

# 数字编号 — 仅在短文本中才视为标题候选（长文本视为内容编号项）
_RE_DIGIT = re.compile(
    r"^\d+[\.\s]\d*"
)

# 最大标题长度 — 超过此长度的不视为标题
_MAX_HEADING_LEN = 60


def _detect_heading_level(text: str, style: str | None) -> int | None:
    """检测段落的标题等级，返回 None 表示不是标题。

    Returns:
        1 = 第X章/部分 (顶层)
        2 = 一、二、三 (大节)
        3 = （一）（二）(小节)
        None = 非标题
    """
    stripped = text.strip()

    # 章/部分级别
    if _RE_CHAPTER.match(stripped):
        return 1

    # 中文序号级别 — 限长度
    if _RE_ORDINAL.match(stripped) and len(stripped) < _MAX_HEADING_LEN:
        return 2

    # 括号序号级别
    if _RE_PAREN.match(stripped) and len(stripped) < _MAX_HEADING_LEN:
        return 3

    return None


def split_by_numbering(paragraphs: list[Paragraph]) -> list[dict]:
    """按编号模式切分章节。

    Returns:
        list of {title, start, level} — start 是段落在 paragraphs 中的位置索引。
    """
    sections = []
    for i, p in enumerate(paragraphs):
        level = _detect_heading_level(p.text, p.style)
        if level is not None:
            sections.append({
                "title": p.text.strip(),
                "start": i,
                "level": level,
            })
    return sections


def split_by_keywords(paragraphs: list[Paragraph]) -> list[dict]:
    """基于 synonyms.yaml 关键词匹配识别章节。

    匹配规则：段落文本较短（<80字符）且包含同义词表中的关键词。
    """
    try:
        synonyms = load_synonyms()
    except Exception:
        logger.warning("无法加载 synonyms.yaml，跳过关键词切分")
        return []

    sections = []
    for i, p in enumerate(paragraphs):
        text = p.text.strip()
        if len(text) > 80:
            continue
        for canonical, keyword_list in synonyms.items():
            if any(kw in text for kw in keyword_list):
                sections.append({
                    "title": text,
                    "start": i,
                    "level": 1,  # 关键词匹配默认为顶层
                    "keyword_match": canonical,
                })
                break  # 只匹配第一个类别
    return sections


def split_by_style(paragraphs: list[Paragraph]) -> list[dict]:
    """基于 Word 文档的 Heading 样式切分章节。"""
    sections = []
    for i, p in enumerate(paragraphs):
        if not p.style:
            continue
        style_lower = p.style.lower()
        if "heading" in style_lower or "标题" in style_lower:
            # 推断层级: Heading1 → 1, Heading2 → 2, etc.
            level = 1
            digits = re.findall(r"\d+", p.style)
            if digits:
                level = min(int(digits[0]), 3)
            sections.append({
                "title": p.text.strip(),
                "start": i,
                "level": level,
            })
    return sections


def compute_confidence(
    found_sections: int,
    total_paragraphs: int,
    assigned_paragraphs: int,
) -> float:
    """计算切分置信度。

    公式: (found_sections / 6) * (assigned_paragraphs / total_paragraphs)
    - found_sections / 6: 招标文件通常有 ~6 个大章节，找到越多越好（上限 1.0）
    - assigned_paragraphs / total_paragraphs: 段落覆盖率
    """
    if total_paragraphs == 0 or found_sections == 0:
        return 0.0
    section_ratio = min(found_sections / 6.0, 1.0)
    coverage_ratio = assigned_paragraphs / total_paragraphs
    return round(section_ratio * coverage_ratio, 4)


def _build_assignments(
    paragraphs: list[Paragraph],
    sections: list[dict],
) -> dict[int, tuple[str, int]]:
    """为每个段落分配所属章节。

    规则：每个段落归属于其之前最近的章节标题。
    """
    if not sections:
        return {}

    # 按 start 排序
    sorted_sections = sorted(sections, key=lambda s: s["start"])
    assignments = {}

    for idx in range(len(paragraphs)):
        # 找到最后一个 start <= idx 的 section
        assigned_section = None
        for sec in sorted_sections:
            if sec["start"] <= idx:
                assigned_section = sec
            else:
                break
        if assigned_section:
            assignments[idx] = (assigned_section["title"], assigned_section["level"])

    return assignments


def _select_best_strategy(
    paragraphs: list[Paragraph],
    strategies: list[tuple[str, list[dict]]],
) -> tuple[list[dict], float]:
    """从多个策略中选择置信度最高的。"""
    best_sections = []
    best_confidence = 0.0

    for name, sections in strategies:
        if not sections:
            continue
        assignments = _build_assignments(paragraphs, sections)
        # 只计算顶层章节数
        top_sections = [s for s in sections if s["level"] == 1]
        if not top_sections:
            top_sections = sections  # 如果没有level=1，用全部
        confidence = compute_confidence(
            found_sections=len(top_sections),
            total_paragraphs=len(paragraphs),
            assigned_paragraphs=len(assignments),
        )
        logger.debug("策略 %s: %d 章节, 置信度 %.4f", name, len(sections), confidence)
        if confidence > best_confidence:
            best_confidence = confidence
            best_sections = sections

    return best_sections, best_confidence


def rule_split(paragraphs: list[Paragraph]) -> dict:
    """运行所有规则切分策略，返回最佳结果。

    Returns:
        {
            "confidence": float,
            "sections": list[dict],
            "assignments": dict[int, tuple[str, int]],
            "tagged_paragraphs": list[TaggedParagraph],
        }
    """
    # 运行各策略
    strategies = [
        ("style", split_by_style(paragraphs)),
        ("numbering", split_by_numbering(paragraphs)),
        ("keywords", split_by_keywords(paragraphs)),
    ]

    best_sections, confidence = _select_best_strategy(paragraphs, strategies)

    # 如果编号策略有多层级，合并层级信息
    # 优先使用 numbering 的多层级结果
    numbering_sections = strategies[1][1]
    if numbering_sections and best_sections:
        # 如果 numbering 策略有 level>1 的子节且置信度也可接受
        numbering_assignments = _build_assignments(paragraphs, numbering_sections)
        numbering_confidence = compute_confidence(
            found_sections=len([s for s in numbering_sections if s["level"] == 1]) or len(numbering_sections),
            total_paragraphs=len(paragraphs),
            assigned_paragraphs=len(numbering_assignments),
        )
        # 如果 numbering 策略置信度接近最佳，优先使用它（因为它有层级信息）
        if numbering_confidence >= confidence * 0.8:
            best_sections = numbering_sections
            confidence = max(confidence, numbering_confidence)

    # 构建分配关系
    assignments = _build_assignments(paragraphs, best_sections)

    # 构建 tagged_paragraphs
    tagged = []
    for p in paragraphs:
        if p.index in assignments:
            section_title, section_level = assignments[p.index]
        else:
            section_title, section_level = None, 0
        tagged.append(TaggedParagraph(
            index=p.index,
            text=p.text,
            section_title=section_title,
            section_level=section_level,
            tags=[],  # 标签由 tagger 填充
            table_data=p.table_data,
        ))

    return {
        "confidence": confidence,
        "sections": best_sections,
        "assignments": assignments,
        "tagged_paragraphs": tagged,
    }
