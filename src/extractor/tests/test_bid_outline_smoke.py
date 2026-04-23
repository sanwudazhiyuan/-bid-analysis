"""烟雾集成测试（env-var gated）：跑一份真实招标文件验证端到端流程。

运行方式：
    BID_OUTLINE_SAMPLE_DOCX=path/to/sample.docx python -m pytest \
        src/extractor/tests/test_bid_outline_smoke.py -v
"""
import os
from pathlib import Path

import pytest

from src.parser.docx_parser import parse_docx
from src.indexer.indexer import build_index
from src.extractor.bid_outline import extract_bid_outline, _render_docx


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("BID_OUTLINE_SAMPLE_DOCX"),
    reason="set BID_OUTLINE_SAMPLE_DOCX to a real tender .docx path",
)
def test_bid_outline_end_to_end(tmp_path):
    sample = Path(os.environ["BID_OUTLINE_SAMPLE_DOCX"])
    assert sample.exists(), f"样本文件不存在: {sample}"

    paragraphs = parse_docx(str(sample))
    index_result = build_index(paragraphs)
    tagged = index_result.get("tagged_paragraphs", [])
    assert tagged, "build_index 未产出 tagged_paragraphs"

    tree = extract_bid_outline(tagged, settings=None)
    assert tree is not None, "三重空信号，无法生成；检查样本或关键词表"
    assert tree.get("nodes"), "目录为空"

    out = tmp_path / "out.docx"
    _render_docx(tree, str(out))
    assert out.exists() and out.stat().st_size > 0
