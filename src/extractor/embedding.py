"""向量增强段落筛选：embedding 计算、相似度、批量并行。"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from src.config import load_settings, load_module_descriptions
from src.models import TaggedParagraph

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-v3"
_DEFAULT_DIMENSIONS = 1024
_DEFAULT_BATCH_SIZE = 10
_DEFAULT_MAX_WORKERS = 4
_DEFAULT_THRESHOLD = 0.5


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _batch_texts(texts: list[str], batch_size: int = 25) -> list[list[str]]:
    """将文本列表按 batch_size 分批。"""
    if not texts:
        return []
    return [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]


def _call_embedding_api(
    texts: list[str],
    settings: dict,
) -> list[list[float]]:
    """调用 DashScope embedding API，返回向量列表。"""
    api_cfg = settings["api"]
    emb_cfg = settings.get("embedding", {})
    client = OpenAI(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
        timeout=api_cfg.get("timeout", 120),
        max_retries=5,
    )
    response = client.embeddings.create(
        model=emb_cfg.get("model", _DEFAULT_MODEL),
        input=texts,
        dimensions=emb_cfg.get("dimensions", _DEFAULT_DIMENSIONS),
    )
    return [item.embedding for item in response.data]


def compute_paragraph_embeddings(
    paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
) -> dict[int, list[float]]:
    """并行批量计算段落 embedding。返回 {段落索引: 向量}。"""
    if settings is None:
        settings = load_settings()
    emb_cfg = settings.get("embedding", {})
    batch_size = emb_cfg.get("batch_size", _DEFAULT_BATCH_SIZE)
    max_workers = emb_cfg.get("max_workers", _DEFAULT_MAX_WORKERS)

    texts = []
    indices = []
    for p in paragraphs:
        text = p.text.strip()
        if text:
            if p.section_title:
                text = f"[{p.section_title}] {text}"
            texts.append(text)
            indices.append(p.index)

    if not texts:
        return {}

    batches = _batch_texts(texts, batch_size)
    index_batches = _batch_texts(indices, batch_size)

    embeddings_map: dict[int, list[float]] = {}

    def _embed_batch(batch_idx: int) -> list[tuple[int, list[float]]]:
        batch_texts = batches[batch_idx]
        batch_indices = index_batches[batch_idx]
        try:
            vectors = _call_embedding_api(batch_texts, settings)
            return list(zip(batch_indices, vectors))
        except Exception as e:
            logger.error("Embedding batch %d failed: %s", batch_idx, e)
            return []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_embed_batch, i): i
            for i in range(len(batches))
        }
        for future in as_completed(futures):
            for para_idx, vector in future.result():
                embeddings_map[para_idx] = vector

    logger.info(
        "Computed embeddings for %d/%d paragraphs",
        len(embeddings_map), len(paragraphs),
    )
    return embeddings_map


def compute_module_embeddings(
    settings: dict | None = None,
) -> dict[str, list[float]]:
    """计算各模块描述文本的 embedding。返回 {module_key: 向量}。"""
    if settings is None:
        settings = load_settings()
    descriptions = load_module_descriptions()
    if not descriptions:
        return {}

    keys = list(descriptions.keys())
    texts = [descriptions[k] for k in keys]
    vectors = _call_embedding_api(texts, settings)
    return dict(zip(keys, vectors))


def filter_by_similarity(
    paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]],
    module_embedding: list[float],
    threshold: float = _DEFAULT_THRESHOLD,
    exclude_indices: set[int] | None = None,
) -> list[TaggedParagraph]:
    """按向量相似度筛选段落，返回超过阈值的段落列表。"""
    exclude = exclude_indices or set()
    result = []
    for p in paragraphs:
        if p.index in exclude:
            continue
        vec = embeddings_map.get(p.index)
        if vec is None:
            continue
        sim = cosine_similarity(vec, module_embedding)
        if sim >= threshold:
            result.append(p)
    return result
