"""索引层集成测试 — build_index 端到端验证"""
import glob
import pytest
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))


def test_index_returns_required_structure():
    paragraphs = parse_document("测试文档/招标公告.docx")
    result = build_index(paragraphs)
    assert "confidence" in result
    assert "sections" in result
    assert "tagged_paragraphs" in result
    assert result["confidence"] >= 0


def test_index_tags_coverage():
    """对较大的招标文件，检查主要标签类型都有段落命中"""
    paragraphs = parse_document(
        "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
    )
    result = build_index(paragraphs)
    all_tags = set()
    for tp in result["tagged_paragraphs"]:
        all_tags.update(tp.tags)

    # 建行的完整招标文件应覆盖多种标签
    expected_tags = {"评分", "资格", "报价", "风险"}
    missing = expected_tags - all_tags
    assert len(missing) <= 1, f"缺少标签: {missing}, 实际标签: {all_tags}"


@pytest.mark.parametrize(
    "docx_path",
    TEST_DOCX_FILES,
    ids=lambda p: p.replace("\\", "/").split("/")[-1],
)
def test_index_all_test_documents(docx_path):
    """每个测试文档: build_index 不崩溃，有章节，有标签"""
    paragraphs = parse_document(docx_path)
    result = build_index(paragraphs)

    assert result["confidence"] >= 0
    assert len(result["sections"]) >= 1
    assert len(result["tagged_paragraphs"]) == len(paragraphs)

    # 至少部分段落应被打标
    tagged_with_tags = [tp for tp in result["tagged_paragraphs"] if tp.tags]
    assert len(tagged_with_tags) > 0, f"{docx_path} 无任何段落被打标"


# ========== 归属正确性测试 ==========

class TestAssignmentCorrectness:
    """验证关键内容段落归属到正确的章节"""

    def _find_paragraph(self, tagged, keyword):
        """在 tagged_paragraphs 中找到包含 keyword 的第一个非标题段落"""
        for tp in tagged:
            if keyword in tp.text and len(tp.text) > len(keyword) + 5:
                return tp
        return None

    def _section_contains(self, section_title, *keywords):
        """检查 section_title 是否包含任意一个关键词"""
        if section_title is None:
            return False
        return any(kw in section_title for kw in keywords)

    def test_qualification_content_in_qualification_section(self):
        """资格要求相关内容应在投标人资格/供应商须知章节"""
        paragraphs = parse_document(
            "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
        )
        result = build_index(paragraphs)
        tp = self._find_paragraph(result["tagged_paragraphs"], "营业执照")
        assert tp is not None, "未找到含'营业执照'的段落"
        assert self._section_contains(
            tp.section_title, "资格", "须知", "投标人"
        ), f"'营业执照'段落应在资格相关章节，实际在: {tp.section_title}"

    def test_scoring_content_in_scoring_section(self):
        """评分标准相关内容应在评标办法章节"""
        paragraphs = parse_document(
            "测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx"
        )
        result = build_index(paragraphs)
        tp = self._find_paragraph(result["tagged_paragraphs"], "满分")
        if tp is not None:
            assert self._section_contains(
                tp.section_title, "评标", "评分", "评审", "项目内容"
            ), f"'满分'段落应在评标相关章节，实际在: {tp.section_title}"

    def test_contract_content_in_contract_section(self):
        """合同相关内容应在合同条款章节"""
        paragraphs = parse_document(
            "测试文档/招标文件-2025-A-01-044-信用卡制卡工艺及寄送项目（二次招标）.docx"
        )
        result = build_index(paragraphs)
        tp = self._find_paragraph(result["tagged_paragraphs"], "违约")
        if tp is not None:
            assert self._section_contains(
                tp.section_title, "合同", "条款", "商务"
            ), f"'违约'段落应在合同相关章节，实际在: {tp.section_title}"

    def test_bidding_announcement_content(self):
        """招标公告中的项目名称应在公告相关章节"""
        paragraphs = parse_document("测试文档/招标公告.docx")
        result = build_index(paragraphs)
        tp = self._find_paragraph(result["tagged_paragraphs"], "采购人")
        assert tp is not None, "未找到含'采购人'的段落"
        assert self._section_contains(
            tp.section_title, "项目", "简介", "公告", "概况"
        ), f"'采购人'段落应在项目简介/公告章节，实际在: {tp.section_title}"

    def test_adjacent_paragraphs_same_section(self):
        """同一章节内的连续段落应归属同一章节（不应被错误切分）"""
        paragraphs = parse_document(
            "测试文档/【招标文件】甘肃银行借记IC空白卡及个人化外包服务采购项目-终稿.docx"
        )
        result = build_index(paragraphs)
        tagged = result["tagged_paragraphs"]

        # 找到"投标人资格要求"章节的段落
        qual_paras = [
            tp for tp in tagged
            if tp.section_title and "资格" in tp.section_title
        ]
        if len(qual_paras) >= 3:
            # 连续的资格段落应在同一章节
            indices = [tp.index for tp in qual_paras[:5]]
            sections = [tp.section_title for tp in qual_paras[:5]]
            # 至少前几个应在同一section
            assert sections[0] == sections[1], (
                f"连续资格段落被拆到不同章节: {indices[0]}→{sections[0]}, {indices[1]}→{sections[1]}"
            )
