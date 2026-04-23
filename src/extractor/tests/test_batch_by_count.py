"""测试 batch_by_count：按段落数分批，token 超上限时提前切。"""
from src.models import TaggedParagraph
from src.extractor.base import batch_by_count


def _mk(index: int, text: str = "一段普通段落") -> TaggedParagraph:
    return TaggedParagraph(index=index, text=text)


def test_batch_by_count_basic():
    paras = [_mk(i) for i in range(100)]
    batches = batch_by_count(paras, batch_size=40, token_safety_cap=100_000)
    assert len(batches) == 3
    assert [len(b) for b in batches] == [40, 40, 20]


def test_batch_by_count_token_safety_splits_early():
    """一个超长中文段（远超 cap）加若干普通段，不应压进同一批。"""
    # 中文字符的 estimate_tokens = len * 0.6，20 万字 ≈ 12 万 tokens，超 10 万 cap
    long_text = "中" * 200_000
    paras = [_mk(0, long_text)] + [_mk(i) for i in range(1, 10)]
    batches = batch_by_count(paras, batch_size=40, token_safety_cap=100_000)
    # 长段必须和后续小段分开
    assert len(batches) >= 2
    assert len(batches[0]) == 1  # 长段独占


def test_batch_by_count_empty_input():
    assert batch_by_count([], batch_size=40) == []


def test_batch_by_count_exact_batch_size():
    """段落数恰好等于 batch_size 时只产出一个批。"""
    paras = [_mk(i) for i in range(40)]
    batches = batch_by_count(paras, batch_size=40)
    assert len(batches) == 1
    assert len(batches[0]) == 40


def test_batch_by_count_single_item_exceeds_cap_kept_in_own_batch():
    """单条超大段即使超 cap 也自己占一批，不会死循环。"""
    paras = [_mk(0, "中" * 200_000), _mk(1, "小段")]
    batches = batch_by_count(paras, batch_size=40, token_safety_cap=100_000)
    # 超长段独占一批，后续小段在另一批
    assert len(batches) == 2
    assert len(batches[0]) == 1
    assert len(batches[1]) == 1
