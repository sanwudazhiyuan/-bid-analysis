# Sequential Accumulative Review Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace multi-batch "independent review + take worst" with sequential accumulative review that passes context between batches and lets the final batch make the ultimate judgment.

**Architecture:** New intermediate/final prompt templates and corresponding `llm_review_clause_intermediate()` / `llm_review_clause_final()` functions in `reviewer.py`. The multi-batch branch in `review_task.py` calls intermediate for all-but-last batch, then final for the last batch, and assembles locations based on the final result. All logic covered by mock-LLM tests.

**Tech Stack:** Python 3.11, pytest, unittest.mock

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config/prompts/review_clause_intermediate.txt` | Create | Intermediate batch prompt template |
| `config/prompts/review_clause_final.txt` | Create | Final batch prompt template |
| `src/reviewer/reviewer.py` | Modify | Add `llm_review_clause_intermediate()`, `llm_review_clause_final()`, `_assemble_multi_batch_result()` |
| `server/app/tasks/review_task.py` | Modify | Replace multi-batch branch with sequential accumulative calls |
| `src/reviewer/tests/test_reviewer.py` | Modify | Add mock-LLM tests for intermediate, final, and assembly logic |

---

## Chunk 1: Prompt Templates + Core Functions + Tests

### Task 1: Create intermediate prompt template

**Files:**
- Create: `config/prompts/review_clause_intermediate.txt`

- [ ] **Step 1: Create the intermediate prompt file**

```text
你是招标文件审查专家。你正在分批次审查投标文件是否符合某条招标要求。这是中间批次，你不需要做最终判定，只需审查当前批次内容并提供发现摘要。

## 隐私保护规则（必须遵守）
投标文件中的个人隐私数据已被脱敏处理，以 [姓名_N]、[电话_N]、[身份证_N]、[邮箱_N]、[银行账号_N] 等占位符表示。
- 你的回复中**禁止**填充、还原、猜测任何脱敏占位符的真实内容
- 引用原文时保持占位符原样输出
- 如果条款审查涉及人员资质或联系方式，只需判断"是否提供了相关信息"，无需关注具体内容
- 包含图片的位置以 [图片: filename] 标记，存在该标记即视为已提供扫描件/证书

## 项目背景
{project_context}

## 审查条款
条款内容：{clause_text}
原文依据：{basis_text}
严重程度：{severity}

{prev_context}

## 当前批次投标文件内容
{tender_text}

请审查当前批次内容，返回 JSON 格式：
{{
  "candidates": [
    {{"para_index": 段落编号, "text_snippet": "相关原文片段", "reason": "该段落与条款的关系说明"}}
  ],
  "summary": "本批次审查发现的摘要，包括：已确认符合的内容、疑似不符合的内容、尚未找到的内容"
}}

注意：
- candidates 只列出与条款审查相关的段落（无论是符合还是不符合），不需要列出不相关的段落
- summary 要包含足够信息，使后续批次能在不看当前批次原文的情况下理解审查进展
- 你不需要做最终判定（pass/fail/warning），只需如实报告当前批次的发现
```

- [ ] **Step 2: Commit**

```bash
git add config/prompts/review_clause_intermediate.txt
git commit -m "feat(review): add intermediate batch prompt template"
```

---

### Task 2: Create final prompt template

**Files:**
- Create: `config/prompts/review_clause_final.txt`

- [ ] **Step 1: Create the final prompt file**

```text
你是招标文件审查专家。你正在分批次审查投标文件是否符合某条招标要求。这是最后一个批次，你需要综合所有前序批次的发现，做出最终判定。

## 隐私保护规则（必须遵守）
投标文件中的个人隐私数据已被脱敏处理，以 [姓名_N]、[电话_N]、[身份证_N]、[邮箱_N]、[银行账号_N] 等占位符表示。
- 你的回复中**禁止**填充、还原、猜测任何脱敏占位符的真实内容
- 引用原文时保持占位符原样输出
- 如果条款审查涉及人员资质或联系方式，只需判断"是否提供了相关信息"，无需关注具体内容
- 包含图片的位置以 [图片: filename] 标记，存在该标记即视为已提供扫描件/证书

## 项目背景
{project_context}

## 审查条款
条款内容：{clause_text}
原文依据：{basis_text}
严重程度：{severity}

## 前序批次审查摘要
{accumulated_summary}

## 前序批次候选批注
{candidates_text}

## 当前批次投标文件内容（最后一批）
{tender_text}

请综合所有批次的发现，做出最终判定，返回 JSON 格式：
{{
  "result": "pass" 或 "fail" 或 "warning",
  "confidence": 0-100 的整数,
  "reason": "综合所有批次的最终判断依据和说明",
  "locations": [
    {{"para_index": 段落编号, "text_snippet": "相关原文片段", "reason": "该段落的具体审查说明"}}
  ],
  "retained_candidates": [保留要批注的前序候选段落编号列表]
}}

注意：
- result 是综合所有批次后的最终判定，不是只看当前批次
- reason 是整体总结，需要引用各批次的关键发现
- locations 只包含当前（最后）批次中需要批注的段落
- retained_candidates 是从前序候选中选择仍需保留批注的 para_index 列表：
  - 如果最终判定为 pass，retained_candidates 应为空列表 []
  - 如果最终判定为 fail 或 warning，保留与问题相关的前序候选段落编号
- confidence 反映你对最终判断结果的确信程度

判断标准：
- pass: 综合所有批次，投标文件明确符合该条款要求
- fail: 综合所有批次，投标文件明确不符合或缺失相关内容
- warning: 综合所有批次，投标文件部分符合或表述模糊，需人工确认
```

- [ ] **Step 2: Commit**

```bash
git add config/prompts/review_clause_final.txt
git commit -m "feat(review): add final batch prompt template"
```

---

### Task 3: Add `llm_review_clause_intermediate()` to reviewer.py

**Files:**
- Modify: `src/reviewer/reviewer.py:12-14` (add prompt path constants)
- Modify: `src/reviewer/reviewer.py` (add new function after `llm_review_clause`)

- [ ] **Step 1: Write failing test for intermediate review**

Add to `src/reviewer/tests/test_reviewer.py`:

```python
from unittest.mock import patch

def _make_clause(clause_index=1, severity="critical"):
    """Helper to build a test clause dict."""
    return {
        "source_module": "module_a",
        "clause_index": clause_index,
        "clause_text": "同时提供供应商版与芯片厂商版证书",
        "basis_text": "招标文件第3章",
        "severity": severity,
    }

@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_review_basic(mock_call):
    """中间批次应返回 candidates + summary，不做最终判定。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版证书"}
        ],
        "summary": "本批次发现供应商版证书（段落42），未见芯片厂商版证书。"
    }
    clause = _make_clause()
    result = llm_review_clause_intermediate(clause, "[42] 供应商版证书...", "某项目")
    assert "candidates" in result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["para_index"] == 42
    assert "summary" in result
    assert "供应商版" in result["summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_intermediate_review_basic -v`
Expected: FAIL with `ImportError` (function not defined)

- [ ] **Step 3: Add prompt path constants and implement `llm_review_clause_intermediate()`**

In `src/reviewer/reviewer.py`, after line 13 (`_BATCH_PROMPT_PATH`), add:

```python
_INTERMEDIATE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause_intermediate.txt"
_FINAL_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause_final.txt"
```

After the existing `llm_review_clause()` function (after line 133), add:

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
    """非末批次审查：返回 candidates + summary，不做最终判定。"""
    prompt_template = _INTERMEDIATE_PROMPT_PATH.read_text(encoding="utf-8")

    # 构建前序上下文
    prev_context = ""
    if prev_summary:
        prev_context += f"## 前序批次审查摘要\n{prev_summary}\n"
    if prev_candidates:
        lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in prev_candidates]
        prev_context += f"\n## 前序批次候选批注\n" + "\n".join(lines)

    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{prev_context}", prev_context)
        .replace("{tender_text}", tender_text)
    )

    has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
    if has_images:
        content = _build_multimodal_content(prompt, image_map)
        messages = [
            {"role": "system", "content": "你是招标文件审查专家。"},
            {"role": "user", "content": content},
        ]
    else:
        messages = build_messages(system="你是招标文件审查专家。", user=prompt)

    result = call_qwen(messages, api_settings)

    if not result or not isinstance(result, dict):
        return {"candidates": [], "summary": "LLM 调用失败，无法获取本批次审查结果。"}

    # 规范化 candidates
    raw_candidates = result.get("candidates", [])
    candidates = []
    for c in raw_candidates:
        if isinstance(c, dict) and c.get("para_index") is not None:
            candidates.append({
                "para_index": c["para_index"],
                "text_snippet": c.get("text_snippet", ""),
                "reason": c.get("reason", ""),
            })

    return {
        "candidates": candidates,
        "summary": result.get("summary", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_intermediate_review_basic -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/reviewer.py src/reviewer/tests/test_reviewer.py
git commit -m "feat(review): add llm_review_clause_intermediate with test"
```

---

### Task 4: Add `llm_review_clause_final()` to reviewer.py

**Files:**
- Modify: `src/reviewer/reviewer.py` (add new function after intermediate)
- Modify: `src/reviewer/tests/test_reviewer.py` (add test)

- [ ] **Step 1: Write failing test for final review**

Add to `src/reviewer/tests/test_reviewer.py`:

```python
@patch("src.reviewer.reviewer.call_qwen")
def test_final_review_pass(mock_call):
    """末批次综合判定 pass 时，retained_candidates 为空。"""
    from src.reviewer.reviewer import llm_review_clause_final
    mock_call.return_value = {
        "result": "pass",
        "confidence": 90,
        "reason": "供应商版和芯片厂商版证书均已提供",
        "locations": [],
        "retained_candidates": [],
    }
    clause = _make_clause()
    accumulated_summary = "批次1发现供应商版证书（段落42）。批次2发现芯片厂商版证书（段落1105）。"
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
        {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"},
    ]
    result = llm_review_clause_final(
        clause, "[1200] 其他内容", "某项目",
        accumulated_summary, all_candidates,
    )
    assert result["result"] == "pass"
    assert result["confidence"] == 90
    assert result["retained_candidates"] == []


@patch("src.reviewer.reviewer.call_qwen")
def test_final_review_fail_with_retained(mock_call):
    """末批次综合判定 fail 时，retained_candidates 保留相关前序候选。"""
    from src.reviewer.reviewer import llm_review_clause_final
    mock_call.return_value = {
        "result": "fail",
        "confidence": 85,
        "reason": "仅提供供应商版证书，未见芯片厂商版",
        "locations": [
            {"para_index": 1250, "text_snippet": "此处缺失", "reason": "应包含芯片厂商版证书"}
        ],
        "retained_candidates": [42],
    }
    clause = _make_clause()
    result = llm_review_clause_final(
        clause, "[1200] 其他内容", "某项目",
        "批次1发现供应商版证书（段落42）",
        [{"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}],
    )
    assert result["result"] == "fail"
    assert result["retained_candidates"] == [42]
    assert len(result["locations"]) == 1
    assert result["locations"][0]["para_index"] == 1250
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_final_review_pass src/reviewer/tests/test_reviewer.py::test_final_review_fail_with_retained -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `llm_review_clause_final()`**

Add after `llm_review_clause_intermediate()` in `src/reviewer/reviewer.py`:

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
    """末批次审查：综合所有前序发现，做最终判定。

    返回 dict 包含 result/confidence/reason/locations/retained_candidates。
    """
    prompt_template = _FINAL_PROMPT_PATH.read_text(encoding="utf-8")

    # 构建前序候选文本
    if all_candidates:
        lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
        candidates_text = "\n".join(lines)
    else:
        candidates_text = "（无前序候选）"

    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{accumulated_summary}", accumulated_summary or "（首批次，无前序摘要）")
        .replace("{candidates_text}", candidates_text)
        .replace("{tender_text}", tender_text)
    )

    has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
    if has_images:
        content = _build_multimodal_content(prompt, image_map)
        messages = [
            {"role": "system", "content": "你是招标文件审查专家。"},
            {"role": "user", "content": content},
        ]
    else:
        messages = build_messages(system="你是招标文件审查专家。", user=prompt)

    result = call_qwen(messages, api_settings)

    if not result:
        return _error_item(clause)

    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], dict) else None
    if not isinstance(result, dict):
        return _error_item(clause)

    # Normalize locations
    locations = result.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict):
            normalized_locations.append({
                "para_index": loc.get("para_index"),
                "text_snippet": loc.get("text_snippet", ""),
                "reason": loc.get("reason", ""),
            })

    # Normalize retained_candidates to list[int]
    raw_retained = result.get("retained_candidates", [])
    retained = []
    for r in raw_retained:
        try:
            retained.append(int(r))
        except (TypeError, ValueError):
            pass

    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": result.get("result", "error"),
        "confidence": int(result.get("confidence", 0)),
        "reason": result.get("reason", ""),
        "severity": clause["severity"],
        "locations": normalized_locations,
        "retained_candidates": retained,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_final_review_pass src/reviewer/tests/test_reviewer.py::test_final_review_fail_with_retained -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/reviewer.py src/reviewer/tests/test_reviewer.py
git commit -m "feat(review): add llm_review_clause_final with tests"
```

---

### Task 5: Add `_assemble_multi_batch_result()` to reviewer.py

**Files:**
- Modify: `src/reviewer/reviewer.py` (add assembly function)
- Modify: `src/reviewer/tests/test_reviewer.py` (add tests)

- [ ] **Step 1: Write failing tests for assembly logic**

Add to `src/reviewer/tests/test_reviewer.py`:

```python
def test_assemble_pass_clears_locations():
    """最终 pass → 清空所有 locations。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "pass",
        "confidence": 90,
        "reason": "全部符合",
        "severity": "critical",
        "locations": [],
        "retained_candidates": [],
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "pass"
    assert result["tender_locations"] == []
    assert "retained_candidates" not in result
    assert "locations" not in result


def test_assemble_fail_retains_candidates():
    """最终 fail → retained_candidates 中的前序候选 + 末批次 locations 保留。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "fail",
        "confidence": 85,
        "reason": "缺失芯片厂商版",
        "severity": "critical",
        "locations": [
            {"para_index": 1250, "text_snippet": "此处缺失", "reason": "缺失证书"}
        ],
        "retained_candidates": [42],
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
        {"para_index": 55, "text_snippet": "无关内容", "reason": "不相关"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "fail"
    # 应有 tender_locations 包含 retained para 42 和末批次 para 1250
    all_indices = []
    all_reasons = {}
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
        all_reasons.update(loc.get("per_para_reasons", {}))
    assert 42 in all_indices
    assert 1250 in all_indices
    assert 55 not in all_indices  # 未被 retain
    assert 42 in all_reasons
    assert 1250 in all_reasons
    assert "retained_candidates" not in result
    assert "locations" not in result


def test_assemble_warning_retains_candidates():
    """最终 warning → 同 fail 逻辑保留 locations。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "warning",
        "confidence": 60,
        "reason": "表述模糊",
        "severity": "major",
        "locations": [
            {"para_index": 80, "text_snippet": "模糊表述", "reason": "表述不清"}
        ],
        "retained_candidates": [30],
    }
    all_candidates = [
        {"para_index": 30, "text_snippet": "相关内容", "reason": "部分符合"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    assert result["result"] == "warning"
    all_indices = []
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 30 in all_indices
    assert 80 in all_indices


def test_assemble_invalid_retained_filtered():
    """retained_candidates 引用不存在的候选索引 → 被过滤。"""
    from src.reviewer.reviewer import assemble_multi_batch_result
    final_result = {
        "source_module": "module_a",
        "clause_index": 1,
        "clause_text": "test",
        "result": "fail",
        "confidence": 80,
        "reason": "缺失",
        "severity": "critical",
        "locations": [],
        "retained_candidates": [42, 9999],  # 9999 不在 candidates 中
    }
    all_candidates = [
        {"para_index": 42, "text_snippet": "证书", "reason": "提供了证书"},
    ]
    result = assemble_multi_batch_result(final_result, all_candidates)
    all_indices = []
    for loc in result["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 42 in all_indices
    assert 9999 not in all_indices
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_assemble_pass_clears_locations src/reviewer/tests/test_reviewer.py::test_assemble_fail_retains_candidates src/reviewer/tests/test_reviewer.py::test_assemble_warning_retains_candidates src/reviewer/tests/test_reviewer.py::test_assemble_invalid_retained_filtered -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `assemble_multi_batch_result()`**

Add to `src/reviewer/reviewer.py` after `llm_review_clause_final()`:

```python
def assemble_multi_batch_result(
    final_result: dict,
    all_candidates: list[dict],
) -> dict:
    """根据最终 result 组装 tender_locations。

    - pass → tender_locations 清空
    - fail/warning → 保留 retained_candidates 中的前序候选 + 末批次自身 locations
    """
    retained_indices = set(final_result.pop("retained_candidates", []))
    final_locations_raw = final_result.pop("locations", [])

    if final_result["result"] == "pass":
        final_result["tender_locations"] = []
        return final_result

    # 构建候选索引集合（用于过滤无效 retained）
    candidate_index_set = {c["para_index"] for c in all_candidates}

    tender_locations = []

    # 保留的前序候选
    retained_candidates = [
        c for c in all_candidates
        if c["para_index"] in retained_indices and c["para_index"] in candidate_index_set
    ]
    if retained_candidates:
        retained_para_indices = [c["para_index"] for c in retained_candidates]
        retained_reasons = {c["para_index"]: c["reason"] for c in retained_candidates}
        tender_locations.append({
            "batch_id": "retained_candidates",
            "path": "accumulated",
            "global_para_indices": retained_para_indices,
            "text_snippet": retained_candidates[0].get("text_snippet", "") if retained_candidates else "",
            "per_para_reasons": retained_reasons,
        })

    # 末批次自身 locations
    if final_locations_raw:
        final_para_indices = [loc["para_index"] for loc in final_locations_raw if loc.get("para_index") is not None]
        final_reasons = {loc["para_index"]: loc.get("reason", "") for loc in final_locations_raw if loc.get("para_index") is not None}
        if final_para_indices:
            tender_locations.append({
                "batch_id": "final_batch",
                "path": "final",
                "global_para_indices": final_para_indices,
                "text_snippet": final_locations_raw[0].get("text_snippet", "") if final_locations_raw else "",
                "per_para_reasons": final_reasons,
            })

    final_result["tender_locations"] = tender_locations
    return final_result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py -k "assemble" -v`
Expected: PASS (all 4 assembly tests)

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/reviewer.py src/reviewer/tests/test_reviewer.py
git commit -m "feat(review): add assemble_multi_batch_result with tests"
```

---

## Chunk 2: Integration + End-to-End Tests

### Task 6: Add intermediate candidate validation test

**Files:**
- Modify: `src/reviewer/tests/test_reviewer.py`

- [ ] **Step 1: Write test for intermediate with prev_summary**

```python
@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_with_prev_context(mock_call):
    """中间批次传入前序摘要和候选时，应将其传递给 LLM。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"}
        ],
        "summary": "前序已确认供应商版证书；本批次发现芯片厂商版证书（段落1105）。"
    }
    clause = _make_clause()
    prev_candidates = [
        {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"},
    ]
    result = llm_review_clause_intermediate(
        clause, "[1105] 芯片厂商版证书...", "某项目",
        prev_summary="批次1发现供应商版证书（段落42）",
        prev_candidates=prev_candidates,
    )
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["para_index"] == 1105
    # 验证 call_qwen 收到的 prompt 包含前序摘要
    call_args = mock_call.call_args[0][0]  # messages list
    user_content = call_args[1]["content"]
    assert "批次1发现供应商版证书" in user_content
    assert "段落42" in user_content


@patch("src.reviewer.reviewer.call_qwen")
def test_intermediate_llm_failure(mock_call):
    """中间批次 LLM 调用失败 → 返回空 candidates 和失败摘要。"""
    from src.reviewer.reviewer import llm_review_clause_intermediate
    mock_call.return_value = None
    clause = _make_clause()
    result = llm_review_clause_intermediate(clause, "[42] text", "某项目")
    assert result["candidates"] == []
    assert "失败" in result["summary"]
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py::test_intermediate_with_prev_context src/reviewer/tests/test_reviewer.py::test_intermediate_llm_failure -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/reviewer/tests/test_reviewer.py
git commit -m "test(review): add intermediate edge case tests"
```

---

### Task 7: Add end-to-end multi-batch test

This test simulates the full multi-batch flow: 2 intermediate + 1 final, verifying the complete pipeline.

**Files:**
- Modify: `src/reviewer/tests/test_reviewer.py`

- [ ] **Step 1: Write end-to-end test**

```python
@patch("src.reviewer.reviewer.call_qwen")
def test_multi_batch_e2e_pass(mock_call):
    """端到端：3批次累积审查，最终 pass → locations 清空。"""
    from src.reviewer.reviewer import (
        llm_review_clause_intermediate,
        llm_review_clause_final,
        assemble_multi_batch_result,
    )
    clause = _make_clause()

    # Batch 1: intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}
        ],
        "summary": "发现供应商版证书（段落42），未见芯片厂商版。"
    }
    r1 = llm_review_clause_intermediate(clause, "[42] 供应商版证书", "项目A")
    all_candidates = r1["candidates"]
    accumulated_summary = r1["summary"]

    # Batch 2: intermediate
    mock_call.return_value = {
        "candidates": [
            {"para_index": 1105, "text_snippet": "芯片厂商版证书", "reason": "提供了芯片厂商版"}
        ],
        "summary": "前序已确认供应商版（段落42）；本批次发现芯片厂商版（段落1105）。"
    }
    r2 = llm_review_clause_intermediate(
        clause, "[1105] 芯片厂商版证书", "项目A",
        prev_summary=accumulated_summary,
        prev_candidates=all_candidates,
    )
    all_candidates.extend(r2["candidates"])
    accumulated_summary = r2["summary"]

    # Batch 3: final
    mock_call.return_value = {
        "result": "pass",
        "confidence": 92,
        "reason": "供应商版和芯片厂商版证书均已在前序批次中确认提供",
        "locations": [],
        "retained_candidates": [],
    }
    r3 = llm_review_clause_final(
        clause, "[1300] 其他内容", "项目A",
        accumulated_summary, all_candidates,
    )

    # Assemble
    final = assemble_multi_batch_result(r3, all_candidates)
    assert final["result"] == "pass"
    assert final["tender_locations"] == []
    assert final["confidence"] == 92


@patch("src.reviewer.reviewer.call_qwen")
def test_multi_batch_e2e_fail(mock_call):
    """端到端：2批次累积审查，最终 fail → 保留相关 locations。"""
    from src.reviewer.reviewer import (
        llm_review_clause_intermediate,
        llm_review_clause_final,
        assemble_multi_batch_result,
    )
    clause = _make_clause()

    # Batch 1: intermediate - 只找到供应商版
    mock_call.return_value = {
        "candidates": [
            {"para_index": 42, "text_snippet": "供应商版证书", "reason": "提供了供应商版"}
        ],
        "summary": "发现供应商版证书（段落42），未见芯片厂商版。"
    }
    r1 = llm_review_clause_intermediate(clause, "[42] 供应商版证书", "项目A")
    all_candidates = r1["candidates"]

    # Batch 2: final - 仍未找到芯片厂商版
    mock_call.return_value = {
        "result": "fail",
        "confidence": 88,
        "reason": "仅提供供应商版证书，未见芯片厂商版证书",
        "locations": [
            {"para_index": 500, "text_snippet": "缺失区域", "reason": "此处应包含芯片厂商版证书"}
        ],
        "retained_candidates": [42],
    }
    r2 = llm_review_clause_final(
        clause, "[500] 其他内容", "项目A",
        r1["summary"], all_candidates,
    )

    # Assemble
    final = assemble_multi_batch_result(r2, all_candidates)
    assert final["result"] == "fail"
    assert final["confidence"] == 88
    # 应有 2 个 location 组: retained(42) + final(500)
    all_indices = []
    for loc in final["tender_locations"]:
        all_indices.extend(loc.get("global_para_indices", []))
    assert 42 in all_indices
    assert 500 in all_indices
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py -k "e2e" -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/reviewer/tests/test_reviewer.py
git commit -m "test(review): add end-to-end multi-batch accumulative tests"
```

---

### Task 8: Update multi-batch branch in review_task.py

**Files:**
- Modify: `server/app/tasks/review_task.py:29-33` (imports)
- Modify: `server/app/tasks/review_task.py:199-233` (multi-batch branch)

- [ ] **Step 1: Update imports**

In `server/app/tasks/review_task.py`, change line 32:

```python
    from src.reviewer.reviewer import llm_review_clause, compute_summary
```

to:

```python
    from src.reviewer.reviewer import (
        llm_review_clause, llm_review_clause_intermediate,
        llm_review_clause_final, assemble_multi_batch_result, compute_summary,
    )
```

- [ ] **Step 2: Replace the multi-batch branch**

Replace lines 199-233 (the `else:` branch inside `_review_single_clause`) with:

```python
                else:
                    # 顺序累积审查：逐批次传递摘要，末批次综合判定
                    accumulated_summary = ""
                    all_candidates = []

                    for i, batch in enumerate(batches):
                        tender_text = paragraphs_to_text(batch.paragraphs)
                        is_last = (i == len(batches) - 1)

                        if is_last:
                            try:
                                result = llm_review_clause_final(
                                    clause, tender_text, project_context,
                                    accumulated_summary, all_candidates,
                                    api_settings, image_map=image_map,
                                )
                                # 校验末批次 locations 的索引
                                validated_locations = []
                                batch_indices = {p.index for p in batch.paragraphs}
                                for loc in result.get("locations", []):
                                    pi = loc.get("para_index")
                                    if pi is not None and int(pi) in batch_indices:
                                        validated_locations.append(loc)
                                result["locations"] = validated_locations
                                return assemble_multi_batch_result(result, all_candidates)
                            except Exception as e:
                                logger.error("Clause final review failed for %d: %s", clause["clause_index"], e)
                                return {
                                    "source_module": clause["source_module"],
                                    "clause_index": clause["clause_index"],
                                    "clause_text": clause["clause_text"],
                                    "result": "error", "confidence": 0,
                                    "reason": f"LLM 调用失败: {e}",
                                    "severity": clause["severity"], "tender_locations": [],
                                }
                        else:
                            try:
                                intermediate = llm_review_clause_intermediate(
                                    clause, tender_text, project_context,
                                    prev_summary=accumulated_summary,
                                    prev_candidates=all_candidates if all_candidates else None,
                                    api_settings=api_settings,
                                    image_map=image_map,
                                )
                                # 校验候选索引是否在当前批次范围内
                                batch_indices = {p.index for p in batch.paragraphs}
                                valid_candidates = [
                                    c for c in intermediate.get("candidates", [])
                                    if c.get("para_index") is not None and int(c["para_index"]) in batch_indices
                                ]
                                all_candidates.extend(valid_candidates)
                                accumulated_summary = intermediate.get("summary", accumulated_summary)
                            except Exception as e:
                                logger.error("Clause intermediate review failed for batch %s: %s", batch.batch_id, e)
                                # 中间批次失败不致命，继续下一批次
                                accumulated_summary += f"\n批次{batch.batch_id}审查失败: {e}"
```

- [ ] **Step 3: Remove now-unused imports/code**

Remove the `_is_worse` function (lines 156-157) and the `ClauseBatch` import if it was added previously. The `_SEVERITY_ORDER` dict can also be removed since it's only used by `_is_worse`.

Check: `_is_worse` and `_SEVERITY_ORDER` are not used anywhere else in the file after this change.

- [ ] **Step 4: Run existing tests to ensure nothing breaks**

Run: `python -m pytest src/reviewer/tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/tasks/review_task.py
git commit -m "feat(review): replace multi-batch worst-result with sequential accumulative review"
```

---

### Task 9: Run full test suite

- [ ] **Step 1: Run all reviewer tests**

Run: `python -m pytest src/reviewer/tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run a quick syntax check on modified files**

Run: `python -c "import py_compile; py_compile.compile('src/reviewer/reviewer.py', doraise=True); py_compile.compile('server/app/tasks/review_task.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git status
```
