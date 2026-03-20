"""LLM 兜底索引：当规则切分置信度低时，用 LLM 辅助识别章节结构。"""
import logging

from src.models import Paragraph
from src.extractor.base import (
    build_messages,
    call_qwen,
    estimate_tokens,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是文档结构分析专家。请分析以下招标文件内容，识别出文档的章节结构。

## 要求
1. 识别所有一级章节（如"第一章 招标公告"、"第二章 投标人须知"等）
2. 返回每个章节的标题和起始段落索引
3. 章节层级：1=一级章节

## 输出 JSON 格式
{
  "sections": [
    {"title": "第一章 招标公告", "start": 0, "level": 1},
    {"title": "第二章 投标人须知", "start": 15, "level": 1},
    ...
  ]
}

## 注意事项
- 只返回 JSON，不要添加其他文字
- start 是段落的索引号（[N] 中的 N）
- 如果无法确定章节，返回 {"sections": []}
"""


def llm_split(paragraphs: list[Paragraph], settings: dict | None = None) -> dict:
    """使用 LLM 识别文档章节结构。

    Returns:
        {
            "sections": [{"title": str, "start": int, "level": int}, ...],
            "assignments": {para_index: {"section_title": str, "section_level": int}, ...},
        }
    """
    # 取文档前 2000 字 + 所有标题行的摘要
    summary_lines = []
    total_chars = 0
    max_chars = 3000

    for p in paragraphs:
        line = f"[{p.index}] {p.text[:100]}"
        # 标题行（style 含 Heading）优先保留
        is_heading = p.style and "heading" in p.style.lower() if p.style else False
        if is_heading:
            summary_lines.append(line)
            total_chars += len(line)
        elif total_chars < max_chars:
            summary_lines.append(line)
            total_chars += len(line)

    input_text = "\n".join(summary_lines)
    logger.info("llm_split: 输入文本约 %d tokens", estimate_tokens(input_text))

    messages = build_messages(system=_SYSTEM_PROMPT, user=input_text)
    result = call_qwen(messages, settings)

    if result is None or "sections" not in result:
        logger.warning("llm_split: LLM 返回无效结果，使用空章节")
        return {"sections": [], "assignments": {}}

    sections = result["sections"]

    # 构建 assignments：每个段落分配到最近的章节
    assignments = {}
    if sections:
        sorted_sections = sorted(sections, key=lambda s: s.get("start", 0))
        for p in paragraphs:
            assigned_section = None
            for s in sorted_sections:
                if p.index >= s.get("start", 0):
                    assigned_section = s
                else:
                    break
            if assigned_section:
                assignments[p.index] = (
                    assigned_section["title"],
                    assigned_section.get("level", 1),
                )

    return {"sections": sections, "assignments": assignments}
