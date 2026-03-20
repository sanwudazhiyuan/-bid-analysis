"""索引层统一入口：规则切分 + 语义标签"""

from src.models import Paragraph, TaggedParagraph
from src.indexer.rule_splitter import rule_split
from src.indexer.tagger import tag_paragraphs


def build_index(paragraphs: list[Paragraph]) -> dict:
    """构建索引：切分章节 + 打语义标签。

    Returns:
        {
            "confidence": float,
            "sections": list[dict],
            "tagged_paragraphs": list[TaggedParagraph],
        }
    """
    split_result = rule_split(paragraphs)

    # 用 tagger 重新打标（在 rule_split 的 assignments 基础上）
    tagged = tag_paragraphs(paragraphs, split_result["assignments"])

    return {
        "confidence": split_result["confidence"],
        "sections": split_result["sections"],
        "tagged_paragraphs": tagged,
    }
