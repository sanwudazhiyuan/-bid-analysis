"""extractor base 模块测试 — token 估算、JSON 解析、消息构建、分批、合并"""
import pytest
from src.models import TaggedParagraph


def test_estimate_tokens_chinese():
    """中文 token 估算: 字符数 × 0.6"""
    from src.extractor.base import estimate_tokens

    text = "这是一段中文测试文本"
    tokens = estimate_tokens(text)
    assert tokens == int(len(text) * 0.6)


def test_estimate_tokens_empty():
    from src.extractor.base import estimate_tokens

    assert estimate_tokens("") == 0


def test_estimate_tokens_english():
    """英文以空格分词, 约每词1.3 token"""
    from src.extractor.base import estimate_tokens

    text = "this is a test"
    tokens = estimate_tokens(text)
    assert tokens > 0


def test_parse_llm_json_normal():
    """正常 JSON 字符串"""
    from src.extractor.base import parse_llm_json

    raw = '{"title": "A. 项目信息", "sections": []}'
    result = parse_llm_json(raw)
    assert result["title"] == "A. 项目信息"


def test_parse_llm_json_with_markdown():
    """带 markdown 代码块包裹的 JSON"""
    from src.extractor.base import parse_llm_json

    raw = '```json\n{"title": "test"}\n```'
    result = parse_llm_json(raw)
    assert result["title"] == "test"


def test_parse_llm_json_with_markdown_no_lang():
    """带 ``` 但无语言标记的代码块"""
    from src.extractor.base import parse_llm_json

    raw = '```\n{"title": "test2"}\n```'
    result = parse_llm_json(raw)
    assert result["title"] == "test2"


def test_parse_llm_json_invalid():
    """非法 JSON 返回 None"""
    from src.extractor.base import parse_llm_json

    raw = "not json at all"
    result = parse_llm_json(raw)
    assert result is None


def test_parse_llm_json_with_trailing_text():
    """JSON 后面有多余文本"""
    from src.extractor.base import parse_llm_json

    raw = '{"title": "ok"}\n\n以上是提取结果。'
    result = parse_llm_json(raw)
    assert result["title"] == "ok"


def test_build_messages():
    """构建 OpenAI 格式消息"""
    from src.extractor.base import build_messages

    msgs = build_messages(system="你是专家", user="提取信息")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "你是专家"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "提取信息"


def test_load_prompt_template():
    """加载 prompt 模板文件"""
    from src.extractor.base import load_prompt_template

    # 先创建一个测试用 prompt 文件
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("你是测试 prompt")
        tmp_path = f.name

    try:
        content = load_prompt_template(tmp_path)
        assert content == "你是测试 prompt"
    finally:
        os.unlink(tmp_path)


def test_batch_paragraphs_single_batch():
    """段落总量不超限时应返回单批"""
    from src.extractor.base import batch_paragraphs

    paras = [
        TaggedParagraph(
            i, f"段落{i}", section_title="第一章", section_level=1, tags=[], table_data=None
        )
        for i in range(5)
    ]
    batches = batch_paragraphs(paras, max_tokens=50000)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_batch_paragraphs_splits_when_exceeds():
    """段落总量超限时应分批"""
    from src.extractor.base import batch_paragraphs, estimate_tokens

    # 每段 250 tokens (1000 chars / 4), 100 段 = 25000 tokens, max=10000 应分 3 批
    paras = [
        TaggedParagraph(
            i,
            "x" * 1000,
            section_title=f"第{i // 10}章",
            section_level=1,
            tags=[],
            table_data=None,
        )
        for i in range(100)
    ]
    batches = batch_paragraphs(paras, max_tokens=10000)
    assert len(batches) > 1
    # 每批 token 不超限
    for batch in batches:
        total = sum(estimate_tokens(p.text) for p in batch)
        assert total <= 10000


def test_batch_paragraphs_empty():
    """空列表返回空"""
    from src.extractor.base import batch_paragraphs

    batches = batch_paragraphs([], max_tokens=50000)
    assert batches == []


def test_merge_batch_results():
    """合并多批结果, 同 id 取最后一批"""
    from src.extractor.base import merge_batch_results

    r1 = {"sections": [{"id": "A1", "title": "v1"}, {"id": "A2", "title": "v1"}]}
    r2 = {"sections": [{"id": "A1", "title": "v2"}]}
    merged = merge_batch_results([r1, r2])
    a1 = [s for s in merged["sections"] if s["id"] == "A1"][0]
    a2 = [s for s in merged["sections"] if s["id"] == "A2"][0]
    assert a1["title"] == "v2"  # A1 被 r2 更新
    assert a2["title"] == "v1"  # A2 保留 r1 的值


def test_merge_batch_results_empty():
    """空列表返回空 sections"""
    from src.extractor.base import merge_batch_results

    merged = merge_batch_results([])
    assert merged["sections"] == []


def test_merge_batch_results_single():
    """单批结果直接返回"""
    from src.extractor.base import merge_batch_results

    r = {"sections": [{"id": "X1", "title": "hello"}]}
    merged = merge_batch_results([r])
    assert merged["sections"] == [{"id": "X1", "title": "hello"}]
