from src.models import Paragraph, TaggedParagraph

def test_paragraph_creation():
    p = Paragraph(index=0, text="测试段落", style="Heading 1", is_table=False, table_data=None)
    assert p.index == 0
    assert p.text == "测试段落"
    assert p.style == "Heading 1"

def test_paragraph_table():
    p = Paragraph(index=1, text="", style=None, is_table=True, table_data=[["a", "b"], ["c", "d"]])
    assert p.is_table is True
    assert len(p.table_data) == 2

def test_tagged_paragraph():
    tp = TaggedParagraph(index=0, text="评分标准", section_title="第三章", section_level=1, tags=["评分"], table_data=None)
    assert "评分" in tp.tags
    assert tp.section_level == 1

def test_paragraph_to_dict():
    p = Paragraph(index=0, text="测试", style=None, is_table=False, table_data=None)
    d = p.to_dict()
    assert d["index"] == 0
    assert d["text"] == "测试"

def test_tagged_paragraph_to_dict():
    tp = TaggedParagraph(index=0, text="测试", section_title="章节", section_level=1, tags=["资格"], table_data=None)
    d = tp.to_dict()
    assert d["tags"] == ["资格"]
