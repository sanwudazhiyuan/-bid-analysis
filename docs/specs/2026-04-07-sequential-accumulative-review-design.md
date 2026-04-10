# 多批次累积审查（Sequential Accumulative Review）设计文档

## 背景与问题

当前多批次审查逻辑为：**各批次独立审查，取最差结果**。

这在跨章节条款上导致误判。例如条款要求"同时提供卡片供应商版与芯片厂商版证书"，被映射到两个不同章节：
- 批次 A 只看到芯片厂商版证书 → "没看到供应商版，fail"
- 批次 B 只看到供应商版证书 → "没看到芯片厂商版，fail"
- 最终取最差 → fail

实际两个证书都存在，应该是 pass。

## 目标

将多批次审查改为**顺序累积模式**：逐批次审查并传递摘要，由末批次综合判定最终结果。

## 约束

1. 分批次本身是为了压缩上下文窗口，**不能合并所有批次段落**
2. 非末批次不做最终判定，只提供候选批注和摘要供后续参考
3. 末批次做最终判定，并裁定前序候选批注的去留
4. 最终 result 为 pass → 清空所有 locations；为 fail/warning → 保留被 retain 的候选 + 末批次自身 locations
5. 单批次行为不变，仍走现有 `llm_review_clause()`
6. 必须编写带 mock LLM 回复的测试，覆盖解析和组装流程

## 设计

### 数据流

```
单批次:
  Batch → llm_review_clause() → result (不变)

多批次:
  Batch 1 → llm_review_clause_intermediate()
           → {candidates, summary}
  Batch 2 → llm_review_clause_intermediate(prev_summary, prev_candidates)
           → {candidates, summary}  (累积)
  ...
  Batch N → llm_review_clause_final(accumulated_summary, all_candidates)
           → {result, confidence, reason, locations, retained_candidates}

  组装: 根据 result 过滤 → 最终 review_item
```

### 新增 Prompt 模板

#### `config/prompts/review_clause_intermediate.txt`

非末批次 prompt。输入：条款信息、项目背景、前序摘要（如有）、当前批次段落。

要求返回：
```json
{
  "candidates": [
    {"para_index": 42, "text_snippet": "...", "reason": "该段提供了供应商版证书"}
  ],
  "summary": "本批次发现了供应商版证书（段落42），但未见芯片厂商版证书。"
}
```

- `candidates`: 当前批次中与条款审查相关的段落列表，每个段落附带初步 reason（仅供参考，非最终判定）
- `summary`: 自然语言摘要，总结到目前为止的审查发现和尚未确认的内容

#### `config/prompts/review_clause_final.txt`

末批次 prompt。输入：条款信息、项目背景、累积摘要、所有前序候选批注列表、当前批次段落。

要求返回：
```json
{
  "result": "pass|fail|warning",
  "confidence": 85,
  "reason": "综合所有批次的最终判断说明",
  "locations": [
    {"para_index": 1105, "text_snippet": "...", "reason": "该段的审查说明"}
  ],
  "retained_candidates": [42, 55]
}
```

- `result/confidence/reason`: 最终审查判定
- `locations`: 当前（末）批次中新增的批注
- `retained_candidates`: 从前序候选中保留要批注的 para_index 列表

### 新增函数（`src/reviewer/reviewer.py`）

#### `llm_review_clause_intermediate()`

```python
def llm_review_clause_intermediate(
    clause: dict,
    tender_text: str,
    project_context: str,
    prev_summary: str = "",
    prev_candidates: list[dict] | None = None,
    api_settings: dict | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    """非末批次审查。返回 {"candidates": [...], "summary": "..."}"""
```

#### `llm_review_clause_final()`

```python
def llm_review_clause_final(
    clause: dict,
    tender_text: str,
    project_context: str,
    accumulated_summary: str,
    all_candidates: list[dict],
    api_settings: dict | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    """末批次审查。返回最终 result + retained_candidates。"""
```

### 修改调用方（`server/app/tasks/review_task.py`）

`_review_single_clause` 中的多批次分支改为：

```python
if len(batches) == 1:
    # 不变
    ...
else:
    accumulated_summary = ""
    all_candidates = []       # list[dict], 每个含 para_index/text_snippet/reason
    all_batch_locations = []   # 收集每批次的候选，用于最终组装

    for i, batch in enumerate(batches):
        tender_text = paragraphs_to_text(batch.paragraphs)
        is_last = (i == len(batches) - 1)

        if is_last:
            result = llm_review_clause_final(
                clause, tender_text, project_context,
                accumulated_summary, all_candidates,
                api_settings, image_map=image_map,
            )
            result = map_batch_indices_to_global(result, batch)
            # 组装最终 locations
            result = _assemble_multi_batch_result(
                result, all_candidates, all_batch_locations, batches,
            )
            return result
        else:
            intermediate = llm_review_clause_intermediate(
                clause, tender_text, project_context,
                accumulated_summary, all_candidates,
                api_settings, image_map=image_map,
            )
            # 提取候选并做索引校验
            batch_candidates = _validate_candidates(
                intermediate.get("candidates", []), batch
            )
            all_candidates.extend(batch_candidates)
            accumulated_summary = intermediate.get("summary", "")
```

### 结果组装函数

```python
def _assemble_multi_batch_result(
    final_result: dict,
    all_candidates: list[dict],
    all_batch_locations: list[tuple[list[dict], ClauseBatch]],
    batches: list[ClauseBatch],
) -> dict:
    """根据最终 result 组装 tender_locations。"""
    if final_result["result"] == "pass":
        final_result["tender_locations"] = []
        return final_result

    # fail/warning: 保留 retained_candidates + 末批次自身 locations
    retained = set(final_result.pop("retained_candidates", []))
    retained_locs = [c for c in all_candidates if c["para_index"] in retained]

    # 合并: retained 前序候选 + 末批次 locations
    final_locations = final_result.get("tender_locations", [])
    # 将 retained 候选转为 tender_locations 格式
    if retained_locs:
        retained_indices = [c["para_index"] for c in retained_locs]
        retained_reasons = {c["para_index"]: c["reason"] for c in retained_locs}
        final_locations.append({
            "batch_id": "retained_candidates",
            "path": "accumulated",
            "global_para_indices": retained_indices,
            "text_snippet": "",
            "per_para_reasons": retained_reasons,
        })
    final_result["tender_locations"] = final_locations
    return final_result
```

### 测试计划

在 `src/reviewer/tests/test_reviewer.py` 中新增测试，使用 mock 替换 `call_qwen` 来模拟 LLM 回复：

#### 测试场景

1. **单批次不变** — 确认单批次仍走 `llm_review_clause`，行为不变
2. **多批次 pass** — 两个批次，中间批次报告"部分符合"，末批次综合判定 pass → locations 清空
3. **多批次 fail** — 三个批次，末批次判定 fail → retained_candidates 中的前序候选 + 末批次 locations 保留
4. **多批次 warning** — 末批次判定 warning → 同 fail 逻辑保留 locations
5. **中间批次 LLM 失败** — intermediate 调用异常 → 降级为 error
6. **末批次 retained_candidates 引用不存在的索引** — 无效索引被过滤
7. **候选索引校验** — intermediate 返回的 para_index 不在批次范围内 → 被过滤

每个测试通过 `unittest.mock.patch` mock `call_qwen`，提供预设的 JSON 回复，验证最终 review_item 的 result/locations/reason 是否正确。

## 不变部分

- `src/reviewer/tender_indexer.py` — 分批逻辑不变
- `src/reviewer/docx_annotator.py` — locations 格式不变，消费端无需修改
- `config/prompts/review_clause.txt` — 现有单批次 prompt 保留
- 单批次条款审查 — 行为完全不变
