"""语义标签打标器测试"""
from src.models import Paragraph, TaggedParagraph
from src.indexer.tagger import tag_paragraphs


def test_tag_scoring_content():
    paragraphs = [
        Paragraph(0, "评分标准如下，满分100分"),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("评标办法", 1)})
    assert "评分" in tagged[0].tags


def test_tag_qualification_content():
    paragraphs = [
        Paragraph(0, "供应商须提供有效营业执照"),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("供应商须知", 1)})
    assert "资格" in tagged[0].tags


def test_tag_risk_content():
    paragraphs = [
        Paragraph(0, "投标保证金不符合要求的，否决投标"),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("供应商须知", 1)})
    assert "风险" in tagged[0].tags


def test_multiple_tags():
    """一个段落可以有多个标签"""
    paragraphs = [
        Paragraph(0, "报价评分标准：满分70分，最低报价得满分"),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("评标办法", 1)})
    assert "评分" in tagged[0].tags
    assert "报价" in tagged[0].tags


def test_no_tags_for_generic_content():
    """无关键词的段落不应被打标"""
    paragraphs = [
        Paragraph(0, "本项目由甲方发起"),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("总则", 1)})
    assert len(tagged[0].tags) == 0


def test_section_title_implies_tag():
    """章节标题本身可触发标签（如属于'评标办法'章节）"""
    paragraphs = [
        Paragraph(0, "普通段落，没有特殊关键词"),
    ]
    # 属于"合同条款"章节的段落应自动获得"合同"标签
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("合同条款", 1)})
    assert "合同" in tagged[0].tags


def test_preserves_paragraph_info():
    """打标后应保留段落原始信息"""
    paragraphs = [
        Paragraph(0, "表格内容", style=None, is_table=True, table_data=[["a", "b"]]),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("总则", 1)})
    assert tagged[0].table_data == [["a", "b"]]
    assert tagged[0].text == "表格内容"
    assert tagged[0].section_title == "总则"
