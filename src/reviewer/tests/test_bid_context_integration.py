"""集成测试：用实际 LLM API 测试条款映射到招标文件章节。

运行方式: python -m pytest src/reviewer/tests/test_bid_context_integration.py -v -s
需要环境变量: DASHSCOPE_API_KEY
"""
import os
import json
import pytest
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 跳过条件：无 API key 或无测试文件
TENDER_DOC = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "招标文档",
    "【招标文件】甘肃银行借记IC空白卡及个人化外包服务采购项目-终稿.docx",
)
HAS_API_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))
HAS_TENDER_DOC = os.path.exists(TENDER_DOC)

skip_reason = ""
if not HAS_API_KEY:
    skip_reason = "需要 DASHSCOPE_API_KEY 环境变量"
elif not HAS_TENDER_DOC:
    skip_reason = f"需要测试招标文件: {TENDER_DOC}"

pytestmark = pytest.mark.skipif(bool(skip_reason), reason=skip_reason)


@pytest.fixture(scope="module")
def bid_indexed_data():
    """解析招标文件并建索引。"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index

    logger.info("解析招标文件: %s", TENDER_DOC)
    paragraphs = parse_document(TENDER_DOC)
    logger.info("段落数: %d", len(paragraphs))

    index_result = build_index(paragraphs)
    logger.info("索引置信度: %.2f, 章节数: %d",
                index_result["confidence"], len(index_result["sections"]))
    return index_result


@pytest.fixture(scope="module")
def bid_tagged_paragraphs(bid_indexed_data):
    """从 indexed_data 构建 TaggedParagraph 列表。"""
    from src.models import TaggedParagraph

    return [
        TaggedParagraph(
            index=p["index"] if isinstance(p, dict) else p.index,
            text=p["text"] if isinstance(p, dict) else p.text,
            section_title=p.get("section_title") if isinstance(p, dict) else p.section_title,
            section_level=p.get("section_level", 0) if isinstance(p, dict) else p.section_level,
            tags=p.get("tags", []) if isinstance(p, dict) else p.tags,
        )
        for p in bid_indexed_data["tagged_paragraphs"]
    ]


@pytest.fixture(scope="module")
def bid_chapter_index(bid_indexed_data):
    """构建招标文件的 chapters 树索引。"""
    from src.reviewer.bid_context import build_bid_chapter_index

    index = build_bid_chapter_index(bid_indexed_data)
    logger.info("招标文件章节树: %d 个顶层章节, %d 个路径",
                len(index["chapters"]), len(index["all_paths"]))
    for ch in index["chapters"]:
        logger.info("  - %s (段落 %d-%d)", ch["title"], ch["start_para"], ch["end_para"])
    return index


@pytest.fixture(scope="module")
def sample_clauses():
    """模拟从招标文件提取的审查条款。"""
    return [
        {
            "clause_index": 0,
            "clause_text": "投标人须具有独立法人资格，持有有效的营业执照",
            "basis_text": "资格条件要求",
            "severity": "critical",
            "source_module": "module_e",
        },
        {
            "clause_index": 1,
            "clause_text": "投标文件须密封递交，未按要求密封的作废标处理",
            "basis_text": "投标须知",
            "severity": "critical",
            "source_module": "module_e",
        },
        {
            "clause_index": 2,
            "clause_text": "技术方案需包含制卡工艺流程说明",
            "basis_text": "评分标准",
            "severity": "minor",
            "source_module": "module_c",
        },
    ]


class TestBidChapterIndex:
    """测试招标文件章节索引构建。"""

    def test_has_chapters(self, bid_chapter_index):
        assert len(bid_chapter_index["chapters"]) > 0

    def test_has_all_paths(self, bid_chapter_index):
        assert len(bid_chapter_index["all_paths"]) > 0

    def test_toc_source(self, bid_chapter_index):
        assert bid_chapter_index["toc_source"] == "bid_indexed"


class TestClauseMappingToBid:
    """测试条款映射到招标文件章节（使用实际 LLM API）。"""

    def test_map_clauses_to_bid_chapters(self, sample_clauses, bid_chapter_index):
        """条款应能映射到招标文件的章节节点。"""
        from src.reviewer.clause_mapper import llm_map_clauses_to_leaf_nodes
        from src.config import load_settings

        settings = load_settings()
        settings["api"] = {**settings["api"], "model": "qwen3.5-flash"}

        mapping = llm_map_clauses_to_leaf_nodes(
            sample_clauses, bid_chapter_index, settings
        )

        logger.info("条款映射结果:")
        for clause_idx, paths in mapping.items():
            logger.info("  条款 %d → %s", clause_idx, paths)

        # 至少应有部分条款被映射
        assert len(mapping) > 0, "应至少有一个条款被映射到招标文件章节"

    def test_extract_bid_context(self, sample_clauses, bid_chapter_index, bid_tagged_paragraphs):
        """映射后应能提取招标文件原文作为上下文。"""
        from src.reviewer.clause_mapper import llm_map_clauses_to_leaf_nodes
        from src.reviewer.bid_context import extract_bid_context_for_clauses
        from src.config import load_settings

        settings = load_settings()
        settings["api"] = {**settings["api"], "model": "qwen3.5-flash"}

        mapping = llm_map_clauses_to_leaf_nodes(
            sample_clauses, bid_chapter_index, settings
        )

        contexts = extract_bid_context_for_clauses(
            mapping, bid_chapter_index, bid_tagged_paragraphs
        )

        logger.info("提取的招标原文上下文:")
        for clause_idx, text in contexts.items():
            preview = text[:200].replace("\n", " ")
            logger.info("  条款 %d: %s...", clause_idx, preview)

        # 验证提取的是招标文件内容
        assert len(contexts) > 0, "应至少提取到一个条款的招标原文"
        for clause_idx, text in contexts.items():
            assert len(text) > 0, f"条款 {clause_idx} 的招标原文不应为空"
            assert "[" in text, f"条款 {clause_idx} 的原文应包含段落编号标记"
