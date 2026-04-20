"""Tests for anbiao chapter-based content review."""
from dataclasses import fields
from src.models import Paragraph


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t) for i, t in enumerate(texts)]


def test_chapter_batch_dataclass_fields():
    """ChapterBatch 应有 text/para_indices/chapter_title/image_map 四个字段。"""
    from src.reviewer.anbiao_reviewer import ChapterBatch
    field_names = {f.name for f in fields(ChapterBatch)}
    assert field_names == {"text", "para_indices", "chapter_title", "image_map"}
