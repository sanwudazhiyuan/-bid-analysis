"""关键词得分制段落筛选工具。

基于 config/keyword_scores.yaml 配置，为每个段落计算关键词得分，
按得分降序排列，得分高的段落排在前面，让模型优先参考。
低于阈值的段落不予采纳。
"""
import logging
from dataclasses import dataclass

from src.models import TaggedParagraph
from src.config import load_keyword_scores

logger = logging.getLogger(__name__)

# 缓存配置，避免每次调用都重新读取 yaml
_scores_config = None


def _get_scores_config() -> dict:
    global _scores_config
    if _scores_config is None:
        _scores_config = load_keyword_scores()
    return _scores_config


@dataclass
class ScoredParagraph:
    """带得分的段落，用于排序和筛选。"""
    paragraph: TaggedParagraph
    score: int
    matched_keywords: list[str]  # 匹配到的关键词列表（供日志和调试）

    @property
    def index(self) -> int:
        return self.paragraph.index


def compute_paragraph_scores(
    tagged_paragraphs: list[TaggedParagraph],
    module_key: str,
) -> list[ScoredParagraph]:
    """计算段落得分：对每个段落根据模块的关键词配置计算匹配得分。

    Args:
        tagged_paragraphs: 带标签的段落列表
        module_key: 模块名（如 "module_e", "module_b" 等）

    Returns:
        ScoredParagraph 列表，按得分降序排列
    """
    config = _get_scores_config()
    tier_scores = config.get("tier_scores", {"high": 7, "medium": 4, "low": 2})
    global_threshold = config.get("global_threshold", 3)

    module_config = config.get(module_key, {})
    if not module_config:
        logger.warning("No keyword_scores config for %s, using global threshold only", module_key)
        return [
            ScoredParagraph(paragraph=tp, score=1, matched_keywords=[])
            for tp in tagged_paragraphs
        ]

    threshold = module_config.get("threshold", global_threshold)
    section_kw = module_config.get("section_keywords", {})
    text_kw = module_config.get("text_keywords", {})
    tag_kw = module_config.get("tag_keywords", {})

    results = []
    for tp in tagged_paragraphs:
        score = 0
        matched = []

        # 1. 章节标题关键词匹配
        if tp.section_title:
            for tier, keywords in section_kw.items():
                tier_score = tier_scores.get(tier, 0)
                for kw in keywords:
                    if kw in tp.section_title:
                        score += tier_score
                        matched.append(f"section:{kw}({tier})")

        # 2. 段落正文关键词匹配
        for tier, keywords in text_kw.items():
            tier_score = tier_scores.get(tier, 0)
            for kw in keywords:
                if kw in tp.text:
                    score += tier_score
                    matched.append(f"text:{kw}({tier})")

        # 3. 语义标签匹配加分
        if tp.tags:
            for tier, tag_names in tag_kw.items():
                tier_score = tier_scores.get(tier, 0)
                for tag_name in tag_names:
                    if tag_name in tp.tags:
                        score += tier_score
                        matched.append(f"tag:{tag_name}({tier})")

        results.append(ScoredParagraph(paragraph=tp, score=score, matched_keywords=matched))

    # 按得分降序排列
    results.sort(key=lambda sp: (-sp.score, sp.index))

    # 过滤低于阈值的段落
    above_threshold = [sp for sp in results if sp.score >= threshold]
    below_threshold = [sp for sp in results if sp.score < threshold]

    if below_threshold:
        logger.info(
            "%s: %d paragraphs scored below threshold %d (discarded), "
            "%d above threshold (kept)",
            module_key, len(below_threshold), threshold, len(above_threshold),
        )

    # 日志：得分最高的前5个段落
    if above_threshold:
        top5 = above_threshold[:5]
        for sp in top5:
            logger.debug(
                "%s: para[%d] score=%d matched=%s",
                module_key, sp.index, sp.score,
                ",".join(sp.matched_keywords[:6]) if sp.matched_keywords else "none",
            )

    return above_threshold


def filter_paragraphs_by_score(
    tagged_paragraphs: list[TaggedParagraph],
    module_key: str,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
    similarity_threshold: float = 0.5,
    min_count: int = 5,
) -> tuple[list[TaggedParagraph], dict[int, int]]:
    """得分制段落筛选：替代各模块原有的 _filter_paragraphs()。

    流程：
    1. 计算每个段落的关键词得分
    2. 丢弃低于阈值的段落
    3. 按原文顺序排列（保持文档结构）
    4. 若向量可用，用语义匹配补漏
    5. 若筛选结果太少（< min_count），从剩余有得分的段落中取得分最高的补够

    Args:
        tagged_paragraphs: 带标签的段落列表
        module_key: 模块名
        embeddings_map: 段落向量映射
        module_embedding: 模块向量
        similarity_threshold: 语义匹配阈值
        min_count: 最低保留段落数

    Returns:
        (段落列表, 得分映射) —— 段落按原文顺序排列，得分映射 {para_index: score}
        供 build_input_text 使用，将得分暴露给模型。
    """
    scored = compute_paragraph_scores(tagged_paragraphs, module_key)
    score_map = {sp.index: sp.score for sp in scored}
    selected_indices = {sp.index for sp in scored}
    selected = [sp.paragraph for sp in scored]

    # 向量语义匹配补漏：对未达阈值的段落用向量匹配
    if embeddings_map and module_embedding and len(selected) < len(tagged_paragraphs):
        from src.extractor.embedding import filter_by_similarity
        extra = filter_by_similarity(
            tagged_paragraphs, embeddings_map, module_embedding,
            exclude_indices=selected_indices,
            threshold=similarity_threshold,
        )
        for tp in extra:
            selected.append(tp)
            selected_indices.add(tp.index)
            # 向量匹配的段落得分标记为 0（非关键词匹配，语义补漏）
            score_map[tp.index] = 0
        if extra:
            logger.info("%s: 向量匹配补充了 %d 个段落", module_key, len(extra))

    # 最低数量保障：如果得分筛选+向量补漏仍不够，从剩余段落中取得分最高的
    if len(selected) < min_count and len(tagged_paragraphs) > min_count:
        remaining = [sp for sp in compute_paragraph_scores(tagged_paragraphs, module_key)
                     if sp.index not in selected_indices and sp.score > 0]
        need = min_count - len(selected)
        for sp in remaining[:need]:
            selected.append(sp.paragraph)
            selected_indices.add(sp.index)
            score_map[sp.index] = sp.score
            logger.debug(
                "%s: min_count补充 para[%d] score=%d",
                module_key, sp.index, sp.score,
            )

    # 最终排序：按原文顺序排列（保持文档结构）
    selected.sort(key=lambda tp: tp.index)

    logger.info(
        "%s: 得分筛选最终保留 %d 个段落 (共 %d)，按原文顺序排列",
        module_key, len(selected), len(tagged_paragraphs),
    )
    return selected, score_map