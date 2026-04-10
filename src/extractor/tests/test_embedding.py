"""Tests for embedding module."""
import pytest

from src.extractor.embedding import (
    cosine_similarity,
    _batch_texts,
    filter_by_similarity,
)
from src.models import TaggedParagraph


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0, 0], [1, 1]) == 0.0


class TestBatchTexts:
    def test_exact_batches(self):
        texts = ["a", "b", "c", "d"]
        batches = _batch_texts(texts, batch_size=2)
        assert batches == [["a", "b"], ["c", "d"]]

    def test_remainder_batch(self):
        texts = ["a", "b", "c"]
        batches = _batch_texts(texts, batch_size=2)
        assert batches == [["a", "b"], ["c"]]

    def test_empty(self):
        assert _batch_texts([], batch_size=5) == []

    def test_single_batch(self):
        texts = ["a", "b"]
        assert _batch_texts(texts, batch_size=10) == [["a", "b"]]


class TestFilterBySimilarity:
    def test_above_threshold_included(self):
        paras = [TaggedParagraph(index=0, text="test")]
        emb_map = {0: [1.0, 0.0]}
        module_emb = [1.0, 0.0]
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 1

    def test_below_threshold_excluded(self):
        paras = [TaggedParagraph(index=0, text="test")]
        emb_map = {0: [1.0, 0.0]}
        module_emb = [0.0, 1.0]
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 0

    def test_missing_embedding_skipped(self):
        paras = [TaggedParagraph(index=0, text="test"), TaggedParagraph(index=1, text="t2")]
        emb_map = {0: [1.0, 0.0]}
        module_emb = [1.0, 0.0]
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 1
        assert result[0].index == 0

    def test_exclude_indices(self):
        paras = [TaggedParagraph(index=0, text="a"), TaggedParagraph(index=1, text="b")]
        emb_map = {0: [1.0, 0.0], 1: [1.0, 0.0]}
        module_emb = [1.0, 0.0]
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5, exclude_indices={0})
        assert len(result) == 1
        assert result[0].index == 1
