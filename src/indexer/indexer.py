"""索引层统一入口：规则切分 + 语义标签 + LLM 兜底"""

import logging

from src.models import Paragraph, TaggedParagraph
from src.indexer.rule_splitter import rule_split
from src.indexer.tagger import tag_paragraphs

logger = logging.getLogger(__name__)

LLM_FALLBACK_THRESHOLD = 0.7


def build_index(paragraphs: list[Paragraph]) -> dict:
    """构建索引：切分章节 + 打语义标签。

    当规则切分置信度 < 0.7 时，调用 LLM 兜底索引。

    Returns:
        {
            "confidence": float,
            "sections": list[dict],
            "tagged_paragraphs": list[TaggedParagraph],
        }
    """
    split_result = rule_split(paragraphs)

    if split_result["confidence"] < LLM_FALLBACK_THRESHOLD:
        logger.info(
            "规则切分置信度 %.2f < %.2f，启用 LLM 兜底索引",
            split_result["confidence"], LLM_FALLBACK_THRESHOLD,
        )
        try:
            from src.indexer.llm_splitter import llm_split
            llm_result = llm_split(paragraphs)
            if llm_result["sections"]:
                split_result["sections"] = llm_result["sections"]
                split_result["assignments"] = llm_result["assignments"]
                logger.info("LLM 兜底索引成功，识别 %d 个章节", len(llm_result["sections"]))
        except Exception as e:
            logger.warning("LLM 兜底索引失败，继续使用规则切分结果: %s", e)

    tagged = tag_paragraphs(paragraphs, split_result["assignments"])

    return {
        "confidence": split_result["confidence"],
        "sections": split_result["sections"],
        "tagged_paragraphs": tagged,
    }
