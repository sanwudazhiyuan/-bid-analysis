"""语义标签打标器：基于关键词和章节归属为段落添加语义标签"""

import logging
from src.models import Paragraph, TaggedParagraph
from src.config import load_tag_rules

logger = logging.getLogger(__name__)

# 章节标题 → 隐含标签的映射
_SECTION_TAG_MAP = {
    "评标办法": "评分",
    "评审办法": "评分",
    "评分标准": "评分",
    "评分办法": "评分",
    "评标方法": "评分",
    "合同条款": "合同",
    "合同格式": "合同",
    "合同范本": "合同",
    "技术要求": "材料",
    "技术商务要求": "材料",
    "投标文件格式": "格式",
    "投标格式": "格式",
    "供应商须知": "资格",
    "投标人须知": "资格",
}


def tag_paragraphs(
    paragraphs: list[Paragraph],
    section_assignments: dict[int, tuple[str, int]],
) -> list[TaggedParagraph]:
    """为每个段落添加语义标签。

    标签来源：
    1. 段落文本中包含 tag_rules.yaml 中的关键词
    2. 段落所属章节标题隐含的标签
    """
    try:
        tag_rules = load_tag_rules()
    except Exception:
        logger.warning("无法加载 tag_rules.yaml，使用空规则")
        tag_rules = {}

    tagged = []
    for p in paragraphs:
        tags = set()

        # 1. 关键词匹配
        for tag_name, keywords in tag_rules.items():
            for kw in keywords:
                if kw in p.text:
                    tags.add(tag_name)
                    break  # 同一标签只需匹配一次

        # 2. 章节隐含标签
        if p.index in section_assignments:
            section_title, section_level = section_assignments[p.index]
            # 检查章节标题是否隐含某个标签
            for title_keyword, implied_tag in _SECTION_TAG_MAP.items():
                if title_keyword in section_title:
                    tags.add(implied_tag)
                    break
        else:
            section_title = None
            section_level = 0

        tagged.append(TaggedParagraph(
            index=p.index,
            text=p.text,
            section_title=section_title,
            section_level=section_level,
            tags=sorted(tags),
            table_data=p.table_data,
        ))

    return tagged
