# 向量增强段落筛选设计

## 背景

当前各提取模块（module_a ~ checklist）通过关键词匹配筛选相关段落，存在漏选问题——关键词无法覆盖所有同义词和变体表述。引入向量语义匹配作为第二层补漏机制，提升召回率。

## 设计目标

- 关键词匹配作为第一层（快速、确定性强）
- 向量匹配作为第二层（对全量段落做语义匹配，补充关键词漏掉的）
- 最终结果 = 关键词命中 ∪ 向量命中（合并去重）
- 向量生成并行执行，并行数 = 2 × LLM 并行数 = 16

## Pipeline 变更

```
解析(0-10%) → 索引(10-15%) → 向量化(15-25%) → 提取(25-90%) → 审核(90%)
                                ↑ 新增步骤
```

## 技术方案

### 1. Embedding 模型

使用阿里云 DashScope `text-embedding-v3`，通过 OpenAI 兼容接口调用：

```python
client = OpenAI(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=api_key,
)
response = client.embeddings.create(
    model="text-embedding-v3",
    input=["文本1", "文本2", ...],  # 每批最多 25 条
    dimensions=1024,
)
```

### 2. 新增文件

#### `src/extractor/embedding.py`

核心模块，职责：
- `compute_paragraph_embeddings(paragraphs, settings, max_workers=16)` — 并行批量计算段落 embedding，返回 `dict[int, list[float]]`（段落索引 → 向量）
- `compute_module_embeddings(settings)` — 计算9个模块描述文本的 embedding，返回 `dict[str, list[float]]`
- `cosine_similarity(vec_a, vec_b)` — 余弦相似度计算
- `filter_by_similarity(paragraphs, embeddings_map, module_embedding, threshold=0.5)` — 按阈值筛选

#### `config/module_descriptions.yaml`

9个模块的语义描述文本：

```yaml
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

### 3. 文件变更

| 文件 | 变更 |
|------|------|
| `src/extractor/embedding.py` | 新建：embedding 计算、相似度、批量并行 |
| `config/module_descriptions.yaml` | 新建：模块语义描述 |
| `src/extractor/module_a.py` ~ `module_g.py`, `bid_format.py`, `checklist.py` | `_filter_paragraphs` 增加 `embeddings_map` 和 `module_embedding` 参数，添加向量匹配第二层 |
| `src/extractor/extractor.py` | `extract_single_module` 接收 embeddings_map 参数并传入模块 |
| `server/app/tasks/pipeline_task.py` | 索引后新增向量化步骤（15-25%），调整提取阶段进度为 25-90% |
| `src/config.py` 或 `config/settings.yaml` | embedding 模型配置（model_name, dimensions, batch_size） |

### 4. 并行策略

```python
# 段落 embedding：16 并发，每批 25 条
# 3000 段落 → 120 批 → 16 并发 ≈ 8 轮 ≈ 数秒完成
with ThreadPoolExecutor(max_workers=16) as executor:
    futures = {executor.submit(_embed_batch, batch): i for i, batch in enumerate(batches)}
```

### 5. 模块筛选逻辑变更

```python
def _filter_paragraphs(tagged_paragraphs, embeddings_map=None, module_embedding=None):
    # 第一层：关键词匹配（不变）
    selected = keyword_match(tagged_paragraphs)
    selected_indices = {tp.index for tp in selected}

    # 第二层：向量补漏
    if embeddings_map and module_embedding:
        for tp in tagged_paragraphs:
            if tp.index in selected_indices:
                continue
            sim = cosine_similarity(embeddings_map[tp.index], module_embedding)
            if sim >= 0.5:
                selected.append(tp)
                selected_indices.add(tp.index)

    selected.sort(key=lambda tp: tp.index)
    return selected
```

### 6. 性能预估

| 操作 | 数量 | 并发 | 预计耗时 |
|------|------|------|----------|
| 段落 embedding | ~3000 段落 / 25批 = 120 次 API | 16 | ~3-5 秒 |
| 模块描述 embedding | 9 条（一次调用） | 1 | <1 秒 |
| 相似度计算 | 3000 × 9 = 27000 次余弦计算 | 本地 CPU | <0.1 秒 |

总新增耗时约 5 秒，对整体 pipeline 影响很小。
