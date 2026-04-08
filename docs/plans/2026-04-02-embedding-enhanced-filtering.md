# 向量增强段落筛选 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有关键词筛选基础上，增加向量语义匹配作为第二层补漏，提升各模块段落召回率。

**Architecture:** Pipeline 在索引之后、提取之前新增"向量化"步骤，批量并行（16并发）计算全部段落的 embedding。各模块 `_filter_paragraphs` 保留关键词第一层，新增向量相似度第二层，合并去重。

**Tech Stack:** DashScope text-embedding-v3（OpenAI 兼容接口）、ThreadPoolExecutor、cosine similarity

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `config/module_descriptions.yaml` | 新建 | 9个模块的语义描述文本 |
| `config/settings.yaml` | 修改 | 新增 `embedding` 配置块 |
| `src/extractor/embedding.py` | 新建 | embedding 计算、相似度、批量并行 |
| `src/extractor/extractor.py` | 修改 | `extract_single_module` 接收并传递 embedding 数据 |
| `src/extractor/module_a.py` | 修改 | `_filter_paragraphs` 和 `extract_module_a` 增加向量参数 |
| `src/extractor/module_b.py` | 修改 | 同上 |
| `src/extractor/module_c.py` | 修改 | 同上 |
| `src/extractor/module_d.py` | 修改 | 同上 |
| `src/extractor/module_e.py` | 修改 | 同上 |
| `src/extractor/module_f.py` | 修改 | 同上 |
| `src/extractor/module_g.py` | 修改 | 同上 |
| `src/extractor/bid_format.py` | 修改 | 同上 |
| `src/extractor/checklist.py` | 修改 | 同上 |
| `server/app/tasks/pipeline_task.py` | 修改 | 新增向量化步骤，调整进度条 |
| `src/extractor/tests/test_embedding.py` | 新建 | embedding 模块单测 |

---

## Task 1: 配置文件

**Files:**
- Create: `config/module_descriptions.yaml`
- Modify: `config/settings.yaml`

- [ ] **Step 1: 创建模块描述文件**

```yaml
# config/module_descriptions.yaml
module_a: "项目基本信息：项目名称、采购编号、预算金额、招标人、采购代理机构、投标截止时间、开标时间、服务期限、交付地点、采购方式"
module_b: "投标人资格条件：企业资质要求、营业执照、注册资本、ISO认证、行业许可证、信用要求、联合体限制、禁止参投情形、行政处罚记录"
module_c: "评分标准：评标办法、技术评分、商务评分、价格评分、评分权重、加分项、扣分项、评标委员会评审规则、报价方式、限价"
module_d: "其他关键信息：投标保证金、履约保证金、投标有效期、交货期、质保期、付款方式、验收标准"
module_e: "废标与无效标风险：废标条件、否决投标情形、资格审查不合格、符合性审查不通过、投标文件密封要求、签字盖章要求"
module_f: "合同管理：合同条款、违约责任、知识产权归属、保密条款、争议解决、合同变更终止"
module_g: "综合评价：项目整体风险评估、投标建议、重点关注事项"
bid_format: "投标文件格式：投标函格式、报价表模板、授权委托书、法定代表人身份证明、声明函、承诺书、投标文件组成及装订要求"
checklist: "投标文件合规检查清单：需提交的证明材料、资质文件、盖章签字要求、份数要求、密封要求"
```

- [ ] **Step 2: settings.yaml 新增 embedding 配置**

在 `config/settings.yaml` 的 `api` 块之后新增：

```yaml
embedding:
  model: "text-embedding-v3"
  dimensions: 1024
  batch_size: 25
  max_workers: 16
  similarity_threshold: 0.5
```

- [ ] **Step 3: src/config.py 新增加载函数**

```python
def load_module_descriptions() -> dict:
    return _load_yaml("module_descriptions.yaml")
```

- [ ] **Step 4: Commit**

```bash
git add config/module_descriptions.yaml config/settings.yaml src/config.py
git commit -m "feat: add module descriptions and embedding config"
```

---

## Task 2: embedding 核心模块（含测试）

**Files:**
- Create: `src/extractor/embedding.py`
- Create: `src/extractor/tests/test_embedding.py`

- [ ] **Step 1: 写测试**

```python
# src/extractor/tests/test_embedding.py
"""Tests for embedding module."""
import math
from unittest.mock import patch, MagicMock

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


class TestFilterBySimilarity:
    def test_above_threshold_included(self):
        paras = [TaggedParagraph(index=0, text="test")]
        emb_map = {0: [1.0, 0.0]}
        module_emb = [1.0, 0.0]  # identical = similarity 1.0
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 1

    def test_below_threshold_excluded(self):
        paras = [TaggedParagraph(index=0, text="test")]
        emb_map = {0: [1.0, 0.0]}
        module_emb = [0.0, 1.0]  # orthogonal = similarity 0.0
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 0

    def test_missing_embedding_skipped(self):
        paras = [TaggedParagraph(index=0, text="test"), TaggedParagraph(index=1, text="t2")]
        emb_map = {0: [1.0, 0.0]}  # index 1 missing
        module_emb = [1.0, 0.0]
        result = filter_by_similarity(paras, emb_map, module_emb, threshold=0.5)
        assert len(result) == 1
        assert result[0].index == 0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest src/extractor/tests/test_embedding.py -v
```

Expected: FAIL（ImportError，模块不存在）

- [ ] **Step 3: 实现 embedding.py**

```python
# src/extractor/embedding.py
"""向量增强段落筛选：embedding 计算、相似度、批量并行。"""
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

from src.config import load_settings, load_module_descriptions
from src.models import TaggedParagraph

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "text-embedding-v3"
_DEFAULT_DIMENSIONS = 1024
_DEFAULT_BATCH_SIZE = 25
_DEFAULT_MAX_WORKERS = 16
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

    # 准备文本和索引映射
    texts = []
    indices = []
    for p in paragraphs:
        text = p.text.strip()
        if text:
            # 拼接章节标题提供上下文
            if p.section_title:
                text = f"[{p.section_title}] {text}"
            texts.append(text)
            indices.append(p.index)

    if not texts:
        return {}

    batches = _batch_texts(texts, batch_size)
    # indices 也需要对应分批
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
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest src/extractor/tests/test_embedding.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/extractor/embedding.py src/extractor/tests/test_embedding.py
git commit -m "feat: add embedding module with cosine similarity and batch parallel"
```

---

## Task 3: 修改 extractor.py 传递 embedding 数据

**Files:**
- Modify: `src/extractor/extractor.py`

- [ ] **Step 1: 修改 extract_single_module 签名**

为 `extract_single_module` 和 `extract_all` 添加 `embeddings_map` 和 `module_embeddings` 可选参数，传递给各模块的 extract 函数：

```python
def extract_single_module(
    module_key: str,
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embeddings: dict[str, list[float]] | None = None,
) -> dict | None:
    """提取单个模块，供 Web Celery Worker 调用。"""
    if module_key not in _MODULE_REGISTRY:
        raise ValueError(f"Unknown module: {module_key}")
    mod_path, func_name = _MODULE_REGISTRY[module_key]
    mod = importlib.import_module(mod_path)
    func = getattr(mod, func_name)

    # 传递 embedding 数据（各模块可选接收）
    module_emb = module_embeddings.get(module_key) if module_embeddings else None
    return func(
        tagged_paragraphs, settings,
        embeddings_map=embeddings_map,
        module_embedding=module_emb,
    )
```

同样更新 `extract_all`，在循环中传递 embedding 参数。

- [ ] **Step 2: 验证导入正常**

```bash
python -c "from src.extractor.extractor import extract_single_module; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/extractor/extractor.py
git commit -m "feat: pass embedding data through extractor to modules"
```

---

## Task 4: 修改9个模块的 _filter_paragraphs

所有9个模块遵循相同的改动模式。以 module_b 为例展示完整变更，其余模块同理。

**Files:**
- Modify: `src/extractor/module_a.py`
- Modify: `src/extractor/module_b.py`
- Modify: `src/extractor/module_c.py`
- Modify: `src/extractor/module_d.py`
- Modify: `src/extractor/module_e.py`
- Modify: `src/extractor/module_f.py`
- Modify: `src/extractor/module_g.py`
- Modify: `src/extractor/bid_format.py`
- Modify: `src/extractor/checklist.py`

- [ ] **Step 1: 修改每个模块的 extract 函数签名**

为每个模块的 `extract_module_X` 函数添加 `embeddings_map` 和 `module_embedding` 关键字参数：

```python
# 以 module_b 为例，其余模块同理
def extract_module_b(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """提取 B. 投标人资格条件。"""
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    # ... 后续不变
```

- [ ] **Step 2: 修改每个模块的 _filter_paragraphs 签名和逻辑**

在每个模块的 `_filter_paragraphs` 末尾、fallback 之前，添加向量匹配第二层：

```python
from src.extractor.embedding import filter_by_similarity

def _filter_paragraphs(
    tagged_paragraphs: list[TaggedParagraph],
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> list[TaggedParagraph]:
    # --- 第一层：关键词匹配（原有逻辑不变）---
    selected = []
    selected_indices = set()
    for tp in tagged_paragraphs:
        # ... 原有的 section_title / tags / text_keywords 匹配 ...

    # --- 第二层：向量补漏 ---
    if embeddings_map and module_embedding:
        extra = filter_by_similarity(
            tagged_paragraphs, embeddings_map, module_embedding,
            exclude_indices=selected_indices,
        )
        for tp in extra:
            if tp.index not in selected_indices:
                selected.append(tp)
                selected_indices.add(tp.index)

    # --- fallback（原有逻辑不变）---
    if len(selected) < 5 and ...:
        ...

    selected.sort(key=lambda tp: tp.index)
    return selected
```

对 module_c 特殊处理：向量补漏放在 `_resolve_references()` 之前。

- [ ] **Step 3: 运行现有测试确认无破坏**

```bash
python -m pytest src/extractor/tests/ -v
```

Expected: 全部 PASS（新参数有默认值 None，不影响现有调用）

- [ ] **Step 4: Commit**

```bash
git add src/extractor/module_a.py src/extractor/module_b.py src/extractor/module_c.py \
        src/extractor/module_d.py src/extractor/module_e.py src/extractor/module_f.py \
        src/extractor/module_g.py src/extractor/bid_format.py src/extractor/checklist.py
git commit -m "feat: add embedding similarity fallback to all 9 module filters"
```

---

## Task 5: 修改 pipeline_task 集成向量化步骤

**Files:**
- Modify: `server/app/tasks/pipeline_task.py`

- [ ] **Step 1: 在索引后新增向量化步骤**

在 Layer 2（Index）和 Layer 3（Extract）之间插入向量化：

```python
        # Layer 2b: Embedding (15-25%) — 新增
        self.update_state(
            state="PROGRESS",
            meta={"step": "indexing", "detail": "计算向量中...", "progress": 18},
        )
        from src.extractor.embedding import (
            compute_paragraph_embeddings,
            compute_module_embeddings,
        )
        embeddings_map = compute_paragraph_embeddings(tagged, api_settings)
        module_embeddings = compute_module_embeddings(api_settings)

        self.update_state(
            state="PROGRESS",
            meta={"step": "indexing", "detail": "向量计算完成", "progress": 25},
        )
```

- [ ] **Step 2: 修改提取阶段传递 embedding 数据**

调整进度范围从 `25-90%`，在 `_extract_module` 闭包中传递 embedding：

```python
        # Layer 3: Extract (25-90%)
        def _extract_module(module_key: str) -> tuple[str, dict | None]:
            try:
                return module_key, extract_single_module(
                    module_key, tagged, api_settings,
                    embeddings_map=embeddings_map,
                    module_embeddings=module_embeddings,
                )
            except Exception as e:
                return module_key, {"status": "failed", "error": str(e)}

        with ThreadPoolExecutor(max_workers=MAX_EXTRACT_WORKERS) as executor:
            futures = {executor.submit(_extract_module, mk): mk for mk in _MODULE_KEYS}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                module_key, result_data = future.result()
                modules_result[module_key] = result_data
                progress = 25 + int(65 * completed / len(_MODULE_KEYS))
                # ... update_state ...
```

- [ ] **Step 3: 验证 worker 启动正常**

```bash
docker-compose restart worker && sleep 3 && docker-compose logs --tail=5 worker
```

Expected: `celery@... ready.`

- [ ] **Step 4: Commit**

```bash
git add server/app/tasks/pipeline_task.py
git commit -m "feat: integrate embedding step into pipeline with progress tracking"
```

---

## Task 6: 端到端验证

- [ ] **Step 1: 运行全部测试**

```bash
python -m pytest src/ -v
```

Expected: 全部 PASS

- [ ] **Step 2: 重启 Docker 服务**

```bash
docker-compose restart worker
```

- [ ] **Step 3: 在前端触发一次解读任务，观察日志**

```bash
docker-compose logs -f worker
```

确认：
1. 日志出现 `Computed embeddings for N/M paragraphs`
2. 进度条在"索引"阶段显示"计算向量中..."
3. 各模块筛选段落数是否有增加（对比之前的日志）
4. 任务正常完成

- [ ] **Step 4: Final Commit**

```bash
git add -A
git commit -m "feat: embedding-enhanced paragraph filtering with parallel computation"
```
