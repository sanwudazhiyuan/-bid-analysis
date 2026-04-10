"""Tests for tender document hybrid indexer."""
from src.models import Paragraph
from src.reviewer.tender_rule_splitter import (
    strategy_toc,
    strategy_style,
    strategy_keywords,
    strategy_numbering,
    compute_confidence,
    build_tender_index,
    _sections_to_chapters,
    _count_assigned,
)


def _make_paras(texts: list[str], styles: list[str | None] | None = None) -> list[Paragraph]:
    if styles is None:
        styles = [None] * len(texts)
    return [Paragraph(index=i, text=t, style=s) for i, (t, s) in enumerate(zip(texts, styles))]


# ========== strategy_toc ==========

class TestStrategyToc:
    def test_toc_style_detection(self):
        """TOC style 段落被识别并匹配到正文。"""
        paras = _make_paras(
            ["目录", "第一章 投标函 ........ 1", "第二章 技术方案 ...... 5",
             "第三章 商务报价 ...... 10",
             # 正文
             "第一章 投标函", "致采购人", "第二章 技术方案", "本系统采用",
             "第三章 商务报价", "报价明细"],
            ["TOCHeading", "TOC1", "TOC1", "TOC1",
             None, None, None, None, None, None],
        )
        result = strategy_toc(paras)
        assert result is not None
        assert len(result) >= 3
        assert result[0]["title"] == "第一章 投标函"
        assert result[0]["start"] == 4  # 匹配到正文段落

    def test_toc_pattern_after_heading(self):
        """'目录'标题后的连续条目被识别。"""
        paras = _make_paras(
            ["目  录",
             "第一章 投标函 1", "第二章 授权委托书 3",
             "第三章 技术方案 5", "第四章 商务方案 12",
             # 正文
             "第一章 投标函", "内容A",
             "第二章 授权委托书", "内容B",
             "第三章 技术方案", "内容C",
             "第四章 商务方案", "内容D"]
        )
        result = strategy_toc(paras)
        assert result is not None
        assert len(result) >= 3

    def test_no_toc_returns_none(self):
        """无目录文档返回 None。"""
        paras = _make_paras([f"普通段落 {i}" for i in range(60)])
        result = strategy_toc(paras)
        assert result is None


# ========== strategy_style ==========

class TestStrategyStyle:
    def test_numeric_style_ids(self):
        """数字 style ID 按频率推断层级。"""
        texts = (
            ["章节标题A", "章节标题B"]  # style "1", 出现 2 次 → level 1
            + ["小节标题1", "小节标题2", "小节标题3"]  # style "2", 出现 3 次 → level 2
            + [f"正文段落 {i}" for i in range(20)]  # style None
        )
        styles: list[str | None] = (
            ["1", "1"]
            + ["2", "2", "2"]
            + [None] * 20
        )
        paras = _make_paras(texts, styles)
        result = strategy_style(paras)
        assert len(result) >= 2
        # style "1" 出现最少 → level 1
        level1 = [s for s in result if s["level"] == 1]
        assert len(level1) == 2

    def test_excludes_normal_style(self):
        """Normal style 被排除。"""
        paras = _make_paras(
            ["段落A", "段落B", "段落C"],
            ["Normal", "Normal", "Normal"],
        )
        result = strategy_style(paras)
        assert result == []

    def test_excludes_high_frequency_styles(self):
        """出现频率 >= 20% 的 style 被排除。"""
        texts = [f"段落 {i}" for i in range(10)]
        styles: list[str | None] = ["1"] * 3 + [None] * 7  # 3/10 = 30% >= 20%
        paras = _make_paras(texts, styles)
        result = strategy_style(paras)
        # style "1" should be excluded due to high frequency
        assert all(s["title"] != "段落 0" for s in result)


# ========== strategy_keywords ==========

class TestStrategyKeywords:
    def test_l1_keywords(self):
        """顶层关键词被识别为 level 1。"""
        paras = _make_paras([
            "一、投标函", "致采购人...",
            "二、技术方案", "本系统...",
            "三、商务方案", "报价...",
        ])
        result = strategy_keywords(paras)
        titles = [s["title"] for s in result]
        assert "一、投标函" in titles
        assert "二、技术方案" in titles
        assert all(s["level"] == 1 for s in result)

    def test_l2_keywords(self):
        """次级关键词被识别为 level 2。"""
        paras = _make_paras([
            "投标函", "内容...",
            "营业执照", "证照编号...",
            "资质证书", "证书编号...",
        ])
        result = strategy_keywords(paras)
        l2 = [s for s in result if s["level"] == 2]
        assert len(l2) >= 2

    def test_long_text_excluded(self):
        """超过 80 字符的段落不被识别为关键词标题。"""
        paras = _make_paras(["投标函" + "x" * 80])
        result = strategy_keywords(paras)
        assert result == []


# ========== strategy_numbering ==========

class TestStrategyNumbering:
    def test_chapter_numbering(self):
        """'第X章' 模式被识别为 level 1。"""
        paras = _make_paras(["第一章 总则", "内容", "第二章 技术要求", "内容"])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 1 for s in result)

    def test_ordinal_numbering(self):
        """'一、' 模式被识别为 level 2。"""
        paras = _make_paras(["一、概述", "二、范围", "正文内容" * 30])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 2 for s in result)

    def test_paren_numbering(self):
        """'（一）' 模式被识别为 level 3。"""
        paras = _make_paras(["（一）投标人资格", "（二）投标文件"])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 3 for s in result)


# ========== compute_confidence ==========

class TestComputeConfidence:
    def test_basic(self):
        assert compute_confidence(6, 100, 90) == 0.9

    def test_capped_sections(self):
        """超过 6 个 sections 不增加置信度。"""
        assert compute_confidence(12, 100, 100) == 1.0

    def test_zero_paragraphs(self):
        assert compute_confidence(3, 0, 0) == 0.0


# ========== _sections_to_chapters ==========

class TestSectionsToChapters:
    def test_hierarchy(self):
        """level 2 成为前一个 level 1 的 children。"""
        sections = [
            {"title": "第一章", "start": 0, "level": 1},
            {"title": "1.1 小节", "start": 3, "level": 2},
            {"title": "第二章", "start": 5, "level": 1},
        ]
        chapters = _sections_to_chapters(sections, 10)
        assert len(chapters) == 2
        assert len(chapters[0]["children"]) == 1
        assert chapters[0]["children"][0]["title"] == "1.1 小节"
        # build_chapter_tree 按"下一相邻节点 start-1"计算 end_para：
        # 第一章 start=0，下一节点（1.1 小节）start=3，故 end_para=2
        assert chapters[0]["end_para"] == 2
        assert chapters[1]["end_para"] == 9


# ========== build_tender_index ==========

class TestBuildTenderIndex:
    def test_toc_takes_priority(self):
        """有目录时直接采用，不参与竞争。"""
        paras = _make_paras(
            ["目录",
             "第一章 投标函 1", "第二章 技术方案 3", "第三章 商务报价 5",
             "第一章 投标函", "内容A",
             "第二章 技术方案", "内容B",
             "第三章 商务报价", "内容C"],
        )
        result = build_tender_index(paras)
        assert result["toc_source"] == "document_toc"
        assert len(result["chapters"]) >= 3

    def test_keywords_fallback(self):
        """无目录时关键词策略生效。"""
        paras = _make_paras(
            ["投标函", "致采购人...", "承诺...",
             "技术方案", "系统架构...", "实施计划...",
             "商务方案", "报价明细...", "付款方式...",
             "售后服务方案", "服务承诺...", "维保...",
             "偏离表", "无偏离...", "确认...",
             "项目业绩", "业绩1...", "业绩2...",
             ] + [f"正文{i}" for i in range(30)]
        )
        result = build_tender_index(paras)
        assert result["toc_source"] in ("keywords", "numbering", "style_analysis")
        assert result["confidence"] > 0

    def test_returns_compatible_format(self):
        """返回格式兼容 get_chapter_text。"""
        paras = _make_paras(
            ["第一章 投标函", "内容A", "第二章 技术方案", "内容B"],
        )
        result = build_tender_index(paras)
        assert "toc_source" in result
        assert "confidence" in result
        assert "chapters" in result
        for ch in result["chapters"]:
            assert "title" in ch
            assert "start_para" in ch
            assert "end_para" in ch
            assert "children" in ch


# ========== 扩展正则（数字层级）==========

class TestDotNumberRegex:
    def test_dot_number_l4(self):
        """1.1.1 匹配为 level 4+。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert _RE_DOT.match("1.1.1 基本信息")

    def test_dot_number_l5(self):
        """1.1.1.1 匹配为 level 4+。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert _RE_DOT.match("1.1.1.1 公司名称")

    def test_dot_number_not_single(self):
        """单个数字不匹配。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert not _RE_DOT.match("1 概述")


class TestBuildNumberedChapterList:
    def test_output_format(self):
        """验证编号列表输出格式和编号→path映射。"""
        from src.reviewer.clause_mapper import _build_numbered_chapter_list

        tender_index = {"chapters": [
            {"title": "第一章", "path": "/第一章", "para_count": 20, "is_leaf": False, "needs_split": False, "children": [
                {"title": "1.1", "path": "/第一章/1.1", "para_count": 10, "is_leaf": True, "needs_split": False, "children": []},
                {"title": "1.2", "path": "/第一章/1.2", "para_count": 10, "is_leaf": True, "needs_split": False, "children": []},
            ]},
        ]}
        text, id_to_path = _build_numbered_chapter_list(tender_index)
        lines = text.strip().split("\n")
        assert len(lines) == 3
        assert "[0]" in lines[0]
        assert "叶子" not in lines[0]  # 非叶子不标记
        assert "[1]" in lines[1]  # 子节点编号
        assert "叶子" in lines[1]
        # 验证映射
        assert id_to_path[0] == "/第一章"
        assert id_to_path[1] == "/第一章/1.1"
        assert id_to_path[2] == "/第一章/1.2"

    def test_needs_split_tag(self):
        """需要拆分的叶子显示拆分标签。"""
        from src.reviewer.clause_mapper import _build_numbered_chapter_list

        tender_index = {"chapters": [
            {"title": "大章", "path": "/大章", "para_count": 2000, "is_leaf": True, "needs_split": True, "children": []},
        ]}
        text, id_to_path = _build_numbered_chapter_list(tender_index)
        assert "需拆分" in text
        assert id_to_path[0] == "/大章"
