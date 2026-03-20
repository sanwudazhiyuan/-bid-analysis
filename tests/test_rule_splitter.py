"""规则切分器测试 — 覆盖四种切分策略和置信度计算"""
import glob
import pytest
from src.models import Paragraph
from src.indexer.rule_splitter import (
    split_by_numbering,
    split_by_keywords,
    split_by_style,
    compute_confidence,
    rule_split,
)

# ========== 编号模式测试 ==========

def test_split_by_numbering_chinese_chapters():
    """第X章 模式"""
    paragraphs = [
        Paragraph(0, "第一章 采购公告", style=None),
        Paragraph(1, "内容段落1"),
        Paragraph(2, "第二章 供应商须知"),
        Paragraph(3, "内容段落2"),
        Paragraph(4, "第三章 评标办法"),
        Paragraph(5, "内容段落3"),
    ]
    sections = split_by_numbering(paragraphs)
    assert len(sections) == 3
    assert sections[0]["title"] == "第一章 采购公告"
    assert sections[1]["title"] == "第二章 供应商须知"
    assert sections[2]["start"] == 4


def test_split_by_numbering_chinese_parts():
    """第X部分 模式"""
    paragraphs = [
        Paragraph(0, "第一部分 资格文件"),
        Paragraph(1, "内容"),
        Paragraph(2, "第二部分 技术方案"),
        Paragraph(3, "内容"),
    ]
    sections = split_by_numbering(paragraphs)
    assert len(sections) == 2
    assert "资格文件" in sections[0]["title"]


def test_split_by_numbering_chinese_ordinals():
    """一、二、三 模式"""
    paragraphs = [
        Paragraph(0, "一、项目简介"),
        Paragraph(1, "内容1"),
        Paragraph(2, "二、投标人资格要求"),
        Paragraph(3, "内容2"),
        Paragraph(4, "三、评标办法"),
    ]
    sections = split_by_numbering(paragraphs)
    assert len(sections) == 3
    assert sections[0]["title"] == "一、项目简介"


def test_split_by_numbering_parenthetical():
    """（一）（二）模式"""
    paragraphs = [
        Paragraph(0, "（一）领取比选文件与报名时间"),
        Paragraph(1, "内容"),
        Paragraph(2, "（二）比选文件获取方式"),
    ]
    sections = split_by_numbering(paragraphs)
    assert len(sections) == 2


def test_split_by_numbering_ignores_long_numbered_content():
    """不应将内容中的编号项（长文本）当作章节标题"""
    paragraphs = [
        Paragraph(0, "第一章 总则"),
        Paragraph(1, "1.投标人当前未处于限制开展生产经营活动、责令停产停业、责令关闭、限制从业等重大行政处罚期内。"),
        Paragraph(2, "2.投标人需要提供营业执照复印件以及相关资质证明文件原件和复印件各一份。"),
        Paragraph(3, "第二章 评标"),
    ]
    sections = split_by_numbering(paragraphs)
    # 长编号内容不应被切为独立章节，只应有2个章节
    assert len(sections) == 2


def test_split_by_numbering_mixed_levels():
    """混合编号层级时，顶层识别正确"""
    paragraphs = [
        Paragraph(0, "第一章 招标公告"),
        Paragraph(1, "一、招标条件"),
        Paragraph(2, "内容"),
        Paragraph(3, "二、项目概况和招标范围"),
        Paragraph(4, "（一）采购内容"),
        Paragraph(5, "内容"),
        Paragraph(6, "第二章 投标人须知"),
    ]
    sections = split_by_numbering(paragraphs)
    # 顶层切分应以"第X章"为准
    top_sections = [s for s in sections if s["level"] == 1]
    assert len(top_sections) == 2


# ========== 关键词匹配测试 ==========

def test_split_by_keywords_standard():
    paragraphs = [
        Paragraph(0, "采购公告"),
        Paragraph(1, "内容"),
        Paragraph(2, "评标办法"),
        Paragraph(3, "内容"),
    ]
    sections = split_by_keywords(paragraphs)
    assert len(sections) >= 2


def test_split_by_keywords_synonyms():
    """同义词匹配：'比选公告' 应匹配 '采购公告' 类别"""
    paragraphs = [
        Paragraph(0, "比选公告"),
        Paragraph(1, "内容"),
        Paragraph(2, "供应商须知"),
        Paragraph(3, "内容"),
    ]
    sections = split_by_keywords(paragraphs)
    assert len(sections) >= 2


# ========== 样式切分测试 ==========

def test_split_by_style_headings():
    paragraphs = [
        Paragraph(0, "招标公告", style="Heading1"),
        Paragraph(1, "内容", style="Normal"),
        Paragraph(2, "投标须知", style="Heading1"),
        Paragraph(3, "内容", style="Normal"),
    ]
    sections = split_by_style(paragraphs)
    assert len(sections) == 2


def test_split_by_style_no_headings():
    """没有 Heading 样式的文档返回空"""
    paragraphs = [
        Paragraph(0, "内容1", style="Normal"),
        Paragraph(1, "内容2", style="Normal"),
    ]
    sections = split_by_style(paragraphs)
    assert len(sections) == 0


# ========== 置信度计算测试 ==========

def test_confidence_high():
    score = compute_confidence(found_sections=5, total_paragraphs=100, assigned_paragraphs=90)
    assert 0 <= score <= 1
    assert score > 0.7


def test_confidence_low_when_few_sections():
    score = compute_confidence(found_sections=1, total_paragraphs=100, assigned_paragraphs=20)
    assert score < 0.7


def test_confidence_zero_when_nothing_found():
    score = compute_confidence(found_sections=0, total_paragraphs=100, assigned_paragraphs=0)
    assert score == 0


def test_confidence_capped_at_one():
    score = compute_confidence(found_sections=10, total_paragraphs=10, assigned_paragraphs=10)
    assert score <= 1.0


# ========== rule_split 集成测试 ==========

def test_rule_split_returns_required_keys():
    paragraphs = [
        Paragraph(0, "第一章 总则"),
        Paragraph(1, "内容"),
        Paragraph(2, "第二章 评标"),
        Paragraph(3, "内容"),
    ]
    result = rule_split(paragraphs)
    assert "confidence" in result
    assert "sections" in result
    assert "assignments" in result
    assert "tagged_paragraphs" in result


# ========== 测试文档全量鲁棒性测试 ==========

TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.replace("\\", "/").split("/")[-1],
)
def test_rule_split_on_all_test_documents(docx_path):
    """对每个测试文档：规则切分不应崩溃，且能识别出至少1个章节"""
    from src.parser.unified import parse_document
    paragraphs = parse_document(docx_path)
    result = rule_split(paragraphs)

    assert result["confidence"] >= 0, f"{docx_path} 置信度为负"
    assert len(result["sections"]) >= 1, f"{docx_path} 未识别出任何章节"
    # 每个 section 有必要字段
    for sec in result["sections"]:
        assert "title" in sec
        assert "start" in sec
        assert "level" in sec
    # tagged_paragraphs 数量应等于输入段落数
    assert len(result["tagged_paragraphs"]) == len(paragraphs)


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.replace("\\", "/").split("/")[-1],
)
def test_rule_split_assigns_most_paragraphs(docx_path):
    """大部分段落应被分配到某个章节"""
    from src.parser.unified import parse_document
    paragraphs = parse_document(docx_path)
    result = rule_split(paragraphs)

    assigned_count = sum(
        1 for tp in result["tagged_paragraphs"]
        if tp.section_title is not None
    )
    ratio = assigned_count / len(paragraphs) if paragraphs else 0
    assert ratio > 0.5, f"{docx_path} 分配比例过低: {ratio:.2f}"
