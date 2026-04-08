# Bid Format Smart Build Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed-template bid format extraction with a two-pass LLM approach: detect format examples in the tender doc first, fall back to building from module results if none found.

**Architecture:** Rewrite `bid_format.txt` prompt for first-pass detection+build, add `bid_format_fallback.txt` for second-pass module-based build. Modify `extract_bid_format()` to accept `modules_context`, add `_summarize_modules()` helper. Update `extractor.py` and `pipeline_task.py` to pass module results to bid_format.

**Tech Stack:** Python 3.11, pytest, unittest.mock

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config/prompts/bid_format.txt` | Rewrite | First-pass prompt: detect format examples, build if found, else return `{"has_template": false}` |
| `config/prompts/bid_format_fallback.txt` | Create | Second-pass prompt: build from module results using default structure |
| `src/extractor/bid_format.py` | Modify | Add `modules_context` param, two-pass logic, `_summarize_modules()` |
| `src/extractor/extractor.py` | Modify | Pass completed module results to `bid_format` in both `extract_all` and `extract_single_module` |
| `server/app/tasks/pipeline_task.py` | Modify | Split concurrent extraction: phase 1 (module_a~g), phase 2 (bid_format, checklist with context) |
| `src/extractor/tests/test_bid_format.py` | Create | Mock-LLM tests for two-pass logic and module summarization |

---

## Chunk 1: Prompts + Core Logic + Tests

### Task 1: Rewrite bid_format.txt prompt

**Files:**
- Modify: `config/prompts/bid_format.txt`

- [ ] **Step 1: Rewrite the prompt**

```text
你是招标文件分析专家。请判断以下招标文件内容中是否包含投标文件格式样例（如投标函模板、报价表格式、开标一览表模板等具体模板文本）。

## 隐私保护规则
投标文件中的个人隐私数据以占位符表示，保持原样输出即可。

## 判断与提取要求
1. 如果招标文件中**包含**投标文件格式样例（存在具体的模板文本、表格格式、函件格式等），请按照原文格式构建完整的投标文件格式，返回以下 JSON：
{
  "title": "投标文件格式",
  "sections": [
    {
      "id": "BF1",
      "title": "投标函",
      "type": "text",
      "content": "致：[采购人名称]\n我方响应贵方...[投标函全文模板]"
    },
    {
      "id": "BF2",
      "title": "开标一览表",
      "type": "standard_table",
      "columns": ["项目名称", "投标报价（万元）", "服务期限", "备注"],
      "rows": [["[待填写]", "[待填写]", "[待填写]", ""]]
    }
  ]
}

2. 如果招标文件中**没有**提供具体的格式样例（只提到了需要哪些文件但没有给出模板），请仅返回：
{"has_template": false}

## 注意事项
- 格式样例是指招标文件中给出了具体的模板文本（如投标函正文、表格列名等），而不是仅仅列出了需要提交的文件清单
- 如果包含格式样例，完整提取所有模板，保持顺序
- 如果模板包含表格，完整提取列名和示例行
- 保留占位符（如"[公司名称]"、"[日期]"）
- id 必须以 "BF" 开头，如 BF1, BF2, BF3...
- 保持 JSON 格式严格，不要在 JSON 外添加任何文字说明
```

- [ ] **Step 2: Commit**

```bash
git add config/prompts/bid_format.txt
git commit -m "refactor(bid-format): rewrite prompt for template detection + build"
```

---

### Task 2: Create bid_format_fallback.txt prompt

**Files:**
- Create: `config/prompts/bid_format_fallback.txt`

- [ ] **Step 1: Create the fallback prompt**

```text
你是招标文件分析专家。招标文件中没有提供投标文件格式样例，请根据以下各模块提取的招标要求，构建投标文件格式。

## 各模块提取结果
{modules_summary}

## 构建要求
请按照以下总体结构构建投标文件格式：

1. **身份证明部分**：法定代表人身份证明书、授权委托书、营业执照副本等（根据资质要求模块的内容）
2. **报价部分**：投标报价表、分项报价表、开标一览表等（根据报价相关模块的内容）
3. **商务技术部分**：技术方案、服务承诺、业绩证明、人员配置等（根据技术和商务要求模块的内容）

每个部分根据模块中提取的具体要求来决定包含哪些模板。如果某个模块结果为空，则跳过相关部分。

## 输出 JSON 格式
{
  "title": "投标文件格式",
  "sections": [
    {
      "id": "BF1",
      "title": "模板名称",
      "type": "text 或 standard_table",
      "content": "模板内容（type 为 text 时）"
    }
  ]
}

## 注意事项
- type 为 "text" 时使用 content 字段存放模板文本
- type 为 "standard_table" 时使用 columns 和 rows 字段
- 保留占位符（如"[公司名称]"、"[日期]"、"[待填写]"）
- id 必须以 "BF" 开头，如 BF1, BF2, BF3...
- 保持 JSON 格式严格，不要在 JSON 外添加任何文字说明
```

- [ ] **Step 2: Commit**

```bash
git add config/prompts/bid_format_fallback.txt
git commit -m "feat(bid-format): add fallback prompt for module-based format build"
```

---

### Task 3: Add `_summarize_modules()` and two-pass logic to bid_format.py

**Files:**
- Modify: `src/extractor/bid_format.py:1-149`
- Create: `src/extractor/tests/test_bid_format.py`

- [ ] **Step 1: Write tests for `_summarize_modules`**

Create `src/extractor/tests/test_bid_format.py`:

```python
"""Tests for bid_format two-pass logic and module summarization."""
import json
from unittest.mock import patch

from src.extractor.bid_format import _summarize_modules


def test_summarize_modules_basic():
    """正常模块结果应提取标题和 section 列表。"""
    modules = {
        "module_a": {
            "title": "基本信息",
            "sections": [
                {"title": "项目概述", "content": "xxx"},
                {"title": "采购需求", "content": "yyy"},
            ],
        },
        "module_b": {
            "title": "资质要求",
            "sections": [
                {"title": "营业执照", "items": ["xxx"]},
            ],
        },
    }
    result = _summarize_modules(modules)
    assert "基本信息" in result
    assert "项目概述" in result
    assert "采购需求" in result
    assert "资质要求" in result
    assert "营业执照" in result


def test_summarize_modules_skips_none():
    """None 的模块应被跳过。"""
    modules = {
        "module_a": None,
        "module_b": {"title": "资质要求", "sections": []},
    }
    result = _summarize_modules(modules)
    assert "module_a" not in result
    assert "资质要求" in result


def test_summarize_modules_skips_bid_format_and_checklist():
    """bid_format 和 checklist 应被排除。"""
    modules = {
        "bid_format": {"title": "投标文件格式", "sections": []},
        "checklist": {"title": "检查清单", "sections": []},
        "module_a": {"title": "基本信息", "sections": []},
    }
    result = _summarize_modules(modules)
    assert "投标文件格式" not in result
    assert "检查清单" not in result
    assert "基本信息" in result


def test_summarize_modules_empty():
    """所有模块为 None 时返回空字符串。"""
    modules = {"module_a": None, "module_b": None}
    result = _summarize_modules(modules)
    assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/extractor/tests/test_bid_format.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add `_summarize_modules()` to bid_format.py**

Add after `_build_input_text()` function in `src/extractor/bid_format.py` (after line 99):

```python
def _summarize_modules(modules_context: dict) -> str:
    """将 module_a~g 结果精简为 LLM 可用的上下文文本。"""
    summaries = []
    for key, result in modules_context.items():
        if result is None or key in ("bid_format", "checklist"):
            continue
        if not isinstance(result, dict):
            continue
        title = result.get("title", key)
        sections = result.get("sections", [])
        section_titles = [s.get("title", "") for s in sections if isinstance(s, dict)]
        summary_line = f"## {title}"
        if section_titles:
            summary_line += f"\n包含: {', '.join(section_titles)}"
        summaries.append(summary_line)
    return "\n\n".join(summaries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/extractor/tests/test_bid_format.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/extractor/bid_format.py src/extractor/tests/test_bid_format.py
git commit -m "feat(bid-format): add _summarize_modules helper with tests"
```

---

### Task 4: Implement two-pass `extract_bid_format()`

**Files:**
- Modify: `src/extractor/bid_format.py:102-149`
- Modify: `src/extractor/tests/test_bid_format.py`

- [ ] **Step 1: Write tests for two-pass logic**

Add to `src/extractor/tests/test_bid_format.py`:

```python
from src.models import TaggedParagraph


def _make_tagged(index, text, section_title="投标文件格式"):
    return TaggedParagraph(index=index, text=text, section_title=section_title, tags=["格式"])


@patch("src.extractor.bid_format.call_qwen")
def test_first_pass_has_template(mock_call):
    """第一次调用发现有格式样例 → 直接返回结果，不调用第二次。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.return_value = {
        "title": "投标文件格式",
        "sections": [{"id": "BF1", "title": "投标函", "type": "text", "content": "致：..."}],
    }
    paras = [_make_tagged(0, "投标函格式：致：采购人")]
    result = extract_bid_format(paras, modules_context={"module_a": {"title": "基本信息", "sections": []}})
    assert result is not None
    assert result["title"] == "投标文件格式"
    assert len(result["sections"]) == 1
    # 只调用一次 LLM
    assert mock_call.call_count == 1


@patch("src.extractor.bid_format.call_qwen")
def test_first_pass_no_template_triggers_fallback(mock_call):
    """第一次调用无格式样例 → 触发第二次调用。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},  # 第一次：无模板
        {  # 第二次：fallback 构建
            "title": "投标文件格式",
            "sections": [{"id": "BF1", "title": "法定代表人身份证明书", "type": "text", "content": "兹证明..."}],
        },
    ]
    paras = [_make_tagged(0, "投标文件应包含投标函")]
    modules = {
        "module_a": {"title": "基本信息", "sections": [{"title": "项目概述"}]},
        "module_b": {"title": "资质要求", "sections": [{"title": "营业执照"}]},
    }
    result = extract_bid_format(paras, modules_context=modules)
    assert result is not None
    assert result["sections"][0]["title"] == "法定代表人身份证明书"
    # 两次 LLM 调用
    assert mock_call.call_count == 2


@patch("src.extractor.bid_format.call_qwen")
def test_fallback_without_modules_context(mock_call):
    """无 modules_context 且无模板 → fallback 仍然调用但 modules_summary 为空。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},
        {"title": "投标文件格式", "sections": [{"id": "BF1", "title": "投标函", "type": "text", "content": "..."}]},
    ]
    paras = [_make_tagged(0, "投标文件应包含投标函")]
    result = extract_bid_format(paras, modules_context=None)
    assert result is not None
    assert mock_call.call_count == 2


@patch("src.extractor.bid_format.call_qwen")
def test_both_passes_fail(mock_call):
    """两次 LLM 都失败 → 返回 None。"""
    from src.extractor.bid_format import extract_bid_format
    mock_call.side_effect = [
        {"has_template": False},
        None,
    ]
    paras = [_make_tagged(0, "投标文件格式")]
    result = extract_bid_format(paras, modules_context={})
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest src/extractor/tests/test_bid_format.py -k "first_pass or fallback or both_passes" -v`
Expected: FAIL

- [ ] **Step 3: Rewrite `extract_bid_format()` with two-pass logic**

Replace the `extract_bid_format` function (lines 102-149) in `src/extractor/bid_format.py`:

```python
FALLBACK_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "bid_format_fallback.txt"


def extract_bid_format(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
    modules_context: dict | None = None,
) -> dict | None:
    """提取投标文件格式模板（两次调用策略）。

    第一次：判断招标文件是否包含格式样例，有则直接构建。
    第二次（仅在无样例时）：基于 module_a~g 结果按默认结构构建。
    """
    filtered = _filter_paragraphs(
        tagged_paragraphs,
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
    )
    if not filtered:
        logger.warning("bid_format: 未筛选到相关段落")
        return None

    logger.info("bid_format: 筛选到 %d 个相关段落 (共 %d)", len(filtered), len(tagged_paragraphs))

    # --- 第一次 LLM 调用：判断 + 构建 ---
    result = _first_pass(filtered, settings)
    if result and result.get("has_template") is not False:
        if "title" not in result:
            result["title"] = "投标文件格式"
        return result

    # --- 第二次 LLM 调用：基于模块结果构建 ---
    logger.info("bid_format: 未检测到格式样例，使用 fallback 构建")
    return _fallback_pass(modules_context, settings)


def _first_pass(filtered: list[TaggedParagraph], settings: dict | None) -> dict | None:
    """第一次 LLM 调用：判断有无格式样例，有则直接构建。"""
    system_prompt = load_prompt_template(str(PROMPT_PATH))
    input_text = _build_input_text(filtered)
    total_tokens = estimate_tokens(input_text)
    logger.info("bid_format: 第一次调用，输入文本约 %d tokens", total_tokens)

    if total_tokens > 120000:
        batches = batch_paragraphs(filtered, max_tokens=120000)
        results = []
        for batch in batches:
            batch_text = _build_input_text(batch)
            messages = build_messages(system=system_prompt, user=batch_text)
            batch_result = call_qwen(messages, settings)
            if batch_result:
                results.append(batch_result)
        if not results:
            return None
        return merge_batch_results(results)
    else:
        messages = build_messages(system=system_prompt, user=input_text)
        return call_qwen(messages, settings)


def _fallback_pass(modules_context: dict | None, settings: dict | None) -> dict | None:
    """第二次 LLM 调用：基于 module_a~g 结果按默认结构构建。"""
    fallback_template = load_prompt_template(str(FALLBACK_PROMPT_PATH))
    modules_summary = _summarize_modules(modules_context or {})
    prompt = fallback_template.replace("{modules_summary}", modules_summary)
    messages = build_messages(system=prompt, user="请根据以上模块信息构建投标文件格式。")
    result = call_qwen(messages, settings)

    if result is None:
        logger.error("bid_format: fallback LLM 返回 None")
        return None

    if "title" not in result:
        result["title"] = "投标文件格式"

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest src/extractor/tests/test_bid_format.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/extractor/bid_format.py src/extractor/tests/test_bid_format.py
git commit -m "feat(bid-format): implement two-pass detection + fallback build"
```

---

## Chunk 2: Upstream Integration

### Task 5: Update `extract_all` and `extract_single_module` in extractor.py

**Files:**
- Modify: `src/extractor/extractor.py:24-91`

- [ ] **Step 1: Modify `extract_all` to pass modules_context**

In `src/extractor/extractor.py`, replace lines 47-58 (the for loop body):

```python
    for key, (module_path, func_name) in _MODULE_REGISTRY.items():
        logger.info("提取模块: %s", key)
        try:
            mod = importlib.import_module(module_path)
            func = getattr(mod, func_name)
            module_emb = module_embeddings.get(key) if module_embeddings else None
            kwargs = dict(
                embeddings_map=embeddings_map,
                module_embedding=module_emb,
            )
            # bid_format 需要前序模块结果作为上下文
            if key == "bid_format":
                kwargs["modules_context"] = modules
            result = func(tagged_paragraphs, settings, **kwargs)
            modules[key] = result
            status = "成功" if result is not None else "返回 None"
            logger.info("模块 %s: %s", key, status)
        except Exception as e:
            logger.error("模块 %s 失败: %s", key, e)
            modules[key] = None
```

- [ ] **Step 2: Modify `extract_single_module` to accept modules_context**

Replace `extract_single_module` function:

```python
def extract_single_module(
    module_key: str,
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embeddings: dict[str, list[float]] | None = None,
    modules_context: dict | None = None,
) -> dict | None:
    """提取单个模块，供 Web Celery Worker 调用。"""
    if module_key not in _MODULE_REGISTRY:
        raise ValueError(f"Unknown module: {module_key}")
    mod_path, func_name = _MODULE_REGISTRY[module_key]
    mod = importlib.import_module(mod_path)
    func = getattr(mod, func_name)
    module_emb = module_embeddings.get(module_key) if module_embeddings else None
    kwargs = dict(
        embeddings_map=embeddings_map,
        module_embedding=module_emb,
    )
    if module_key == "bid_format" and modules_context is not None:
        kwargs["modules_context"] = modules_context
    return func(tagged_paragraphs, settings, **kwargs)
```

- [ ] **Step 3: Verify existing pipeline test still passes**

Run: `python -m pytest server/tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/extractor/extractor.py
git commit -m "feat(extractor): pass modules_context to bid_format in extract_all and extract_single_module"
```

---

### Task 6: Update pipeline_task.py to two-phase extraction

**Files:**
- Modify: `server/app/tasks/pipeline_task.py:16-19,110-145`

The current pipeline runs all 9 modules concurrently. Since `bid_format` now depends on module_a~g results, split into two phases:
- Phase 1: module_a~g concurrently
- Phase 2: bid_format, checklist (with module results as context)

- [ ] **Step 1: Split _MODULE_KEYS into phases**

Replace lines 16-19:

```python
_PHASE1_KEYS = [
    "module_a", "module_b", "module_c", "module_d", "module_e",
    "module_f", "module_g",
]
_PHASE2_KEYS = ["bid_format", "checklist"]
_MODULE_KEYS = _PHASE1_KEYS + _PHASE2_KEYS
```

- [ ] **Step 2: Replace the extraction block with two-phase logic**

Replace lines 110-145 (the extraction section) with:

```python
        # Layer 4: Extract (25-90%) — 两阶段提取
        modules_result = {}
        MAX_EXTRACT_WORKERS = 8

        def _extract_module(module_key: str, extra_kwargs: dict | None = None) -> tuple[str, dict | None]:
            try:
                kwargs = dict(
                    embeddings_map=embeddings_map,
                    module_embeddings=module_embeddings,
                )
                if extra_kwargs:
                    kwargs.update(extra_kwargs)
                return module_key, extract_single_module(
                    module_key, tagged, api_settings, **kwargs,
                )
            except Exception as e:
                return module_key, {"status": "failed", "error": str(e)}

        # Phase 1: module_a~g 并发
        with ThreadPoolExecutor(max_workers=MAX_EXTRACT_WORKERS) as executor:
            futures = {executor.submit(_extract_module, mk): mk for mk in _PHASE1_KEYS}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                module_key, result_data = future.result()
                modules_result[module_key] = result_data
                progress = 25 + int(50 * completed / len(_MODULE_KEYS))
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "step": "extracting",
                        "detail": f"提取 {module_key} [{completed}/{len(_MODULE_KEYS)}]",
                        "progress": progress,
                        "modules_total": len(_MODULE_KEYS),
                        "modules_done": completed,
                    },
                )

        # Phase 2: bid_format, checklist（需要 phase1 结果）
        with ThreadPoolExecutor(max_workers=2) as executor:
            phase2_futures = {}
            for mk in _PHASE2_KEYS:
                extra = {"modules_context": modules_result} if mk == "bid_format" else None
                phase2_futures[executor.submit(_extract_module, mk, extra)] = mk
            for future in as_completed(phase2_futures):
                completed += 1
                module_key, result_data = future.result()
                modules_result[module_key] = result_data
                progress = 25 + int(65 * completed / len(_MODULE_KEYS))
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "step": "extracting",
                        "detail": f"提取 {module_key} [{completed}/{len(_MODULE_KEYS)}]",
                        "progress": progress,
                        "modules_total": len(_MODULE_KEYS),
                        "modules_done": completed,
                    },
                )
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('server/app/tasks/pipeline_task.py', doraise=True); print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add server/app/tasks/pipeline_task.py
git commit -m "feat(pipeline): split extraction into two phases for bid_format context"
```

---

### Task 7: Run full test suite

- [ ] **Step 1: Run all extractor tests**

Run: `python -m pytest src/extractor/tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run all server tests**

Run: `python -m pytest server/tests/ -v`
Expected: All PASS

- [ ] **Step 3: Run reviewer tests (regression)**

Run: `python -m pytest src/reviewer/tests/ -v`
Expected: All PASS

- [ ] **Step 4: Syntax check all modified files**

Run: `python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['src/extractor/bid_format.py', 'src/extractor/extractor.py', 'server/app/tasks/pipeline_task.py']]; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git status
```
