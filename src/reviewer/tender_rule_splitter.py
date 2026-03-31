"""投标文件混合索引器：5 层策略识别章节结构

策略优先级（由高到低）：
1. 目录识别匹配（TOC detection）— 单独赛道，匹配成功直接采用
2. Style ID 层级分析 — 竞争赛道
3. 投标文件关键词匹配 — 竞争赛道
4. 编号正则 — 竞争赛道
5. LLM 兜底（当最高置信度 < 0.7 时启用）
"""

import re
import difflib
import logging
from collections import Counter

from src.models import Paragraph

logger = logging.getLogger(__name__)

# ========== TOC 正则 ==========
_TOC_LINE_RE = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节篇]|[\d]+(?:\.[\d]+)*)\s*"
    r"(.+?)"
    r"[\s.…·\-_]*(\d+)?\s*$"
)

# ========== 排除的通用 style ==========
_EXCLUDED_STYLES = {
    "normal", "body text", "body", "default paragraph font",
    "list paragraph", "no spacing", "annotation text",
    "header", "footer", "footnote text",
}

# ========== 投标文件关键词 ==========
_TENDER_KEYWORDS_L1 = [
    "投标函", "开标一览表", "法人授权委托书", "授权委托书",
    "报价表", "唱标表", "资格证明文件", "资格证明",
    "技术方案", "技术部分", "商务条款", "商务部分", "商务方案",
    "偏离表", "项目业绩", "售后服务方案", "售后服务",
    "投标保证金", "联合体协议", "投标文件格式",
]

_TENDER_KEYWORDS_L2 = [
    "营业执照", "财务报告", "审计报告", "纳税证明",
    "社保证明", "信用查询", "资质证书", "业绩证明",
    "人员资质", "类似项目", "获奖证明",
]

# ========== 编号正则（复用 rule_splitter.py 模式）==========
_RE_CHAPTER = re.compile(
    r"^第[一二三四五六七八九十百零]+[章节篇部]"
    r"|^第[一二三四五六七八九十百零]+部分"
)
_RE_ORDINAL = re.compile(r"^[一二三四五六七八九十]+[、\.\．]")
_RE_PAREN = re.compile(r"^（[一二三四五六七八九十]+）|^\([一二三四五六七八九十]+\)")

_MAX_HEADING_LEN = 80


# ========== 工具函数 ==========

def _parse_toc_level(prefix: str) -> int:
    if prefix.startswith("第"):
        return 1
    return prefix.count(".") + 1 if "." in prefix else 1


def _has_toc_style(para: Paragraph) -> bool:
    return bool(para.style and ("toc" in para.style.lower() or "目录" in para.style.lower()))


def _fuzzy_match(title: str, para_text: str, threshold: float = 0.7) -> bool:
    clean_title = title.strip()
    clean_para = para_text.strip()
    if clean_para.startswith(clean_title):
        return True
    ratio = difflib.SequenceMatcher(
        None, clean_title, clean_para[: len(clean_title) + 20]
    ).ratio()
    return ratio >= threshold


def compute_confidence(
    found_sections: int, total_paragraphs: int, assigned_paragraphs: int
) -> float:
    """置信度 = min(sections/6, 1.0) * (assigned/total)"""
    if total_paragraphs == 0 or found_sections == 0:
        return 0.0
    section_ratio = min(found_sections / 6.0, 1.0)
    coverage_ratio = assigned_paragraphs / total_paragraphs
    return round(section_ratio * coverage_ratio, 4)


def _count_assigned(paragraphs: list[Paragraph], sections: list[dict]) -> int:
    """计算被章节覆盖的段落数（从第一个章节标题到文档末尾）。"""
    if not sections:
        return 0
    first_start = min(s["start"] for s in sections)
    return len(paragraphs) - first_start


def _select_best_strategy(
    paragraphs: list[Paragraph],
    strategies: list[tuple[str, list[dict]]],
) -> tuple[list[dict], float, str]:
    """从多个策略中选择置信度最高的。"""
    best_sections: list[dict] = []
    best_confidence = 0.0
    best_name = ""

    for name, sections in strategies:
        if not sections:
            continue
        top_sections = [s for s in sections if s["level"] == 1]
        if not top_sections:
            top_sections = sections
        assigned = _count_assigned(paragraphs, sections)
        confidence = compute_confidence(len(top_sections), len(paragraphs), assigned)
        logger.debug("策略 %s: %d 章节, 置信度 %.4f", name, len(sections), confidence)
        if confidence > best_confidence:
            best_confidence = confidence
            best_sections = sections
            best_name = name

    return best_sections, best_confidence, best_name


def _sections_to_chapters(sections: list[dict], total_paragraphs: int) -> list[dict]:
    """将扁平 sections 转换为层级 chapters 格式（兼容 tender_indexer）。"""
    if not sections:
        return []

    sorted_secs = sorted(sections, key=lambda s: s["start"])

    # 分离 level-1 和子级
    l1_indices = [i for i, s in enumerate(sorted_secs) if s["level"] == 1]

    # 计算 level-1 的 end_para（到下一个 level-1 之前）
    for pos, idx in enumerate(l1_indices):
        if pos + 1 < len(l1_indices):
            sorted_secs[idx]["end"] = sorted_secs[l1_indices[pos + 1]]["start"] - 1
        else:
            sorted_secs[idx]["end"] = total_paragraphs - 1

    # 计算子级的 end_para（到下一个同级或更高级之前）
    for i, sec in enumerate(sorted_secs):
        if sec["level"] == 1:
            continue
        if i + 1 < len(sorted_secs):
            sec["end"] = sorted_secs[i + 1]["start"] - 1
        else:
            sec["end"] = total_paragraphs - 1

    # 构建层级
    root_chapters: list[dict] = []
    current_parent: dict | None = None
    for sec in sorted_secs:
        ch = {
            "title": sec["title"],
            "level": sec["level"],
            "start_para": sec["start"],
            "end_para": sec["end"],
            "children": [],
        }
        if sec["level"] == 1:
            current_parent = ch
            root_chapters.append(ch)
        elif current_parent is not None:
            current_parent["children"].append(ch)
        else:
            root_chapters.append(ch)

    return root_chapters


# ========== 策略实现 ==========

def strategy_toc(paragraphs: list[Paragraph]) -> list[dict] | None:
    """策略 1：目录识别 + 模糊匹配定位正文段落。

    成功条件：匹配到 >= 3 个 TOC 条目。
    Returns None if no TOC detected.
    """
    scan_range = paragraphs[:80]

    # 子策略 A：TOC style 检测
    toc_entries: list[dict] = []
    for para in scan_range:
        if _has_toc_style(para) and para.text.strip() != "目录":
            m = _TOC_LINE_RE.match(para.text.strip())
            if m:
                prefix, title = m.group(1), m.group(2).strip()
                toc_entries.append({
                    "title": f"{prefix} {title}".strip(),
                    "level": _parse_toc_level(prefix),
                })
    if len(toc_entries) >= 3:
        return _match_toc_to_body(toc_entries, paragraphs)

    # 子策略 B："目录"标题后的连续条目
    toc_start = None
    for i, para in enumerate(scan_range):
        text = para.text.strip().replace(" ", "").replace("\u3000", "")
        if text in ("目录", "CONTENTS"):
            toc_start = i + 1
            break

    if toc_start is None:
        return None

    toc_entries = []
    consecutive_misses = 0
    for para in scan_range[toc_start:]:
        m = _TOC_LINE_RE.match(para.text.strip())
        if m:
            prefix, title = m.group(1), m.group(2).strip()
            toc_entries.append({
                "title": f"{prefix} {title}".strip(),
                "level": _parse_toc_level(prefix),
            })
            consecutive_misses = 0
        else:
            consecutive_misses += 1
            if consecutive_misses >= 3:
                break

    if len(toc_entries) >= 3:
        return _match_toc_to_body(toc_entries, paragraphs)

    return None


def _match_toc_to_body(
    toc_entries: list[dict], paragraphs: list[Paragraph]
) -> list[dict]:
    """将 TOC 条目模糊匹配到正文段落，返回 sections。跳过 TOC 区域本身。"""
    sections: list[dict] = []
    for entry in toc_entries:
        for para in paragraphs:
            # 跳过 TOC style 的段落，避免匹配到目录区域本身
            if _has_toc_style(para):
                continue
            if _fuzzy_match(entry["title"], para.text):
                sections.append({
                    "title": entry["title"],
                    "start": para.index,
                    "level": entry["level"],
                })
                break
    return sections


def strategy_style(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 2：Style ID 频率分析。

    适用于 style 为数字 ID（如 '1','2','3'）的投标文档。
    按出现频率推断层级：最少 → level 1。
    """
    style_counter: Counter[str] = Counter()
    style_texts: dict[str, list[tuple[int, str]]] = {}

    for p in paragraphs:
        if not p.style:
            continue
        s = p.style.strip()
        if s.lower() in _EXCLUDED_STYLES:
            continue
        style_counter[s] += 1
        style_texts.setdefault(s, []).append((p.index, p.text))

    if not style_counter:
        return []

    total = len(paragraphs)

    # 过滤候选标题 style
    candidates: list[tuple[str, int]] = []
    for style, count in style_counter.items():
        if count >= total * 0.2:
            continue
        texts = style_texts[style]
        avg_len = sum(len(t) for _, t in texts) / len(texts) if texts else 0
        if avg_len >= 80:
            continue
        candidates.append((style, count))

    if not candidates:
        return []

    # 按频率升序：最少 → level 1
    candidates.sort(key=lambda x: x[1])

    style_to_level: dict[str, int] = {}
    for i, (style, _) in enumerate(candidates[:3]):
        style_to_level[style] = i + 1

    sections: list[dict] = []
    for p in paragraphs:
        if p.style and p.style.strip() in style_to_level:
            text = p.text.strip()
            if text and len(text) < 80:
                sections.append({
                    "title": text,
                    "start": p.index,
                    "level": style_to_level[p.style.strip()],
                })

    return sections


def strategy_keywords(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 3：投标文件关键词匹配。"""
    sections: list[dict] = []
    for p in paragraphs:
        text = p.text.strip()
        if len(text) > 80:
            continue

        matched = False
        for kw in _TENDER_KEYWORDS_L1:
            if kw in text:
                sections.append({"title": text, "start": p.index, "level": 1})
                matched = True
                break

        if not matched:
            for kw in _TENDER_KEYWORDS_L2:
                if kw in text:
                    sections.append({"title": text, "start": p.index, "level": 2})
                    break

    return sections


def strategy_numbering(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 4：编号正则匹配。"""
    sections: list[dict] = []
    for p in paragraphs:
        text = p.text.strip()

        if _RE_CHAPTER.match(text):
            sections.append({"title": text, "start": p.index, "level": 1})
        elif _RE_ORDINAL.match(text) and len(text) < _MAX_HEADING_LEN:
            sections.append({"title": text, "start": p.index, "level": 2})
        elif _RE_PAREN.match(text) and len(text) < _MAX_HEADING_LEN:
            sections.append({"title": text, "start": p.index, "level": 3})

    return sections


# ========== 统一入口 ==========

LLM_FALLBACK_THRESHOLD = 0.7


def build_tender_index(
    paragraphs: list[Paragraph], api_settings: dict | None = None
) -> dict:
    """构建投标文件索引（5 层混合策略）。

    返回格式兼容现有 tender_indexer:
    {
        "toc_source": "document_toc"|"style_analysis"|"keywords"|"numbering"|"llm_generated",
        "confidence": float,
        "chapters": [{"title", "level", "start_para", "end_para", "children": [...]}]
    }
    """
    total = len(paragraphs)

    # 策略 1：目录识别（单独赛道，成功直接采用）
    toc_sections = strategy_toc(paragraphs)
    if toc_sections and len(toc_sections) >= 3:
        chapters = _sections_to_chapters(toc_sections, total)
        top = [s for s in toc_sections if s["level"] == 1] or toc_sections
        assigned = _count_assigned(paragraphs, toc_sections)
        confidence = compute_confidence(len(top), total, assigned)
        return {
            "toc_source": "document_toc",
            "confidence": confidence,
            "chapters": chapters,
        }

    # 策略 2-4：竞争赛道
    strategies = [
        ("style_analysis", strategy_style(paragraphs)),
        ("keywords", strategy_keywords(paragraphs)),
        ("numbering", strategy_numbering(paragraphs)),
    ]

    best_sections, best_confidence, best_name = _select_best_strategy(
        paragraphs, strategies
    )

    # 策略 5：LLM 兜底
    if best_confidence < LLM_FALLBACK_THRESHOLD and api_settings:
        logger.info(
            "最高置信度 %.2f < %.2f，启用 LLM 兜底",
            best_confidence, LLM_FALLBACK_THRESHOLD,
        )
        try:
            from src.reviewer.clause_mapper import llm_extract_toc
            from src.reviewer.tender_indexer import build_index_from_toc

            toc = llm_extract_toc(paragraphs, api_settings)
            if toc:
                index = build_index_from_toc(toc, paragraphs)
                index["toc_source"] = "llm_generated"
                index["confidence"] = 0.5
                return index
        except Exception as e:
            logger.warning("LLM 兜底索引失败: %s", e)

    # 使用最佳规则结果
    chapters = _sections_to_chapters(best_sections, total)
    return {
        "toc_source": best_name or "numbering",
        "confidence": best_confidence,
        "chapters": chapters,
    }
