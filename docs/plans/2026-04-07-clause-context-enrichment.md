# 审查条款上下文增强 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让审查 LLM 收到更完整的招标条款原文上下文，而非仅高度概括的摘要

**Architecture:** LLM 提取结果已在 `来源章节` 列中包含段落索引（如 `[57][68]`）。修改 `clause_extractor` 解析这些索引，回到 `tagged_paragraphs` 取完整原文段落，拼入 `basis_text`。同时修改 `review_task.py` 传递 `tagged_paragraphs` 给 `clause_extractor`。

**Tech Stack:** Python, regex

---

## Chunk 1: 条款上下文增强

### Task 1: 修改 clause_extractor 解析段落索引并补充原文

**Files:**
- Modify: `src/reviewer/clause_extractor.py`
- Test: `src/reviewer/tests/test_clause_extractor.py`

**背景：** 当前 module_e 的提取结果中 `来源章节` 列包含段落索引，例如：
- `"三、采购需求 [57][68]"`
- `"第二章 供应商须知 [144][146]"`
- `"二、供应商资格条件 [30] / 三、采购需求 [83]"`

`clause_extractor` 需要：
1. 新增 `_parse_para_indices(text) -> list[int]` 函数，用正则 `\[(\d+)\]` 从来源章节列提取所有段落索引
2. 新增 `_build_enriched_basis(basis_text, source_text, tagged_paragraphs) -> str` 函数：
   - 从 `basis_text` 和 `source_text`（来源章节列）中解析出段落索引
   - 从 `tagged_paragraphs` 中取对应段落的完整文本
   - 返回格式：`"{basis_text}\n\n--- 原文段落 ---\n[57] {完整文本}\n[68] {完整文本}"`
3. 修改 `_extract_module_clauses` 签名，增加 `tagged_paragraphs` 和 `source_cols` 参数
4. 修改 `extract_review_clauses` 签名，增加 `tagged_paragraphs` 参数并传递下去

- [ ] **Step 1: 写失败测试**

```python
# src/reviewer/tests/test_clause_extractor.py
import pytest
from src.reviewer.clause_extractor import _parse_para_indices, _build_enriched_basis


class TestParseParaIndices:
    def test_single_index(self):
        assert _parse_para_indices("[57]") == [57]

    def test_multiple_indices(self):
        assert _parse_para_indices("三、采购需求 [57][68]") == [57, 68]

    def test_mixed_text_and_indices(self):
        assert _parse_para_indices("二、资格条件 [30] / 三、采购需求 [83]") == [30, 83]

    def test_no_indices(self):
        assert _parse_para_indices("第三章 评审程序") == []

    def test_empty_string(self):
        assert _parse_para_indices("") == []


class TestBuildEnrichedBasis:
    def test_with_paragraphs(self):
        from dataclasses import dataclass

        @dataclass
        class FakeParagraph:
            index: int
            text: str

        paragraphs = [
            FakeParagraph(index=56, text="前一段"),
            FakeParagraph(index=57, text="投标时针对提供的样本卡片通过测试要求后为有效标"),
            FakeParagraph(index=68, text="否则视为废标"),
        ]
        result = _build_enriched_basis(
            basis_text="样卡测试需通过",
            source_text="三、采购需求 [57][68]",
            tagged_paragraphs=paragraphs,
        )
        assert "样卡测试需通过" in result
        assert "[57]" in result
        assert "投标时针对提供的样本卡片" in result
        assert "[68]" in result
        assert "否则视为废标" in result

    def test_no_indices_returns_basis_only(self):
        result = _build_enriched_basis("原文依据", "第三章", [])
        assert result == "原文依据"

    def test_missing_paragraph_skipped(self):
        result = _build_enriched_basis("依据", "[999]", [])
        assert result == "依据"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_clause_extractor.py -v`
Expected: FAIL (函数不存在)

- [ ] **Step 3: 实现 _parse_para_indices 和 _build_enriched_basis**

在 `src/reviewer/clause_extractor.py` 顶部添加 `import re`，然后添加两个函数：

```python
import re

_PARA_INDEX_RE = re.compile(r"\[(\d+)\]")


def _parse_para_indices(text: str) -> list[int]:
    """从文本中提取 [N] 格式的段落索引。"""
    return [int(m.group(1)) for m in _PARA_INDEX_RE.finditer(text)]


def _build_enriched_basis(
    basis_text: str,
    source_text: str,
    tagged_paragraphs: list,
) -> str:
    """用原文段落丰富 basis_text。

    从 basis_text 和 source_text 中解析段落索引，
    从 tagged_paragraphs 中取完整原文拼接到 basis_text 后面。
    """
    indices = _parse_para_indices(basis_text) + _parse_para_indices(source_text)
    if not indices or not tagged_paragraphs:
        return basis_text

    # 构建索引映射
    para_map = {p.index: p.text for p in tagged_paragraphs}
    context_lines = []
    seen = set()
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        text = para_map.get(idx)
        if text:
            context_lines.append(f"[{idx}] {text}")

    if not context_lines:
        return basis_text

    return f"{basis_text}\n\n--- 原文段落 ---\n" + "\n".join(context_lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_clause_extractor.py -v`
Expected: PASS

- [ ] **Step 5: 修改 _extract_module_clauses 接受 tagged_paragraphs**

修改 `_extract_module_clauses` 签名和逻辑：

```python
def _extract_module_clauses(
    modules: dict, module_key: str, severity: str,
    tagged_paragraphs: list | None = None,
    text_cols: tuple[str, ...] = ("风险项", "条件", "要求", "内容", "评分"),
    basis_cols: tuple[str, ...] = ("原文依据", "依据", "说明"),
    source_cols: tuple[str, ...] = ("来源章节", "来源", "章节"),
) -> list[dict]:
```

在循环中增加 `source_idx` 查找和 `_build_enriched_basis` 调用：

```python
        source_idx = None
        for col_name in source_cols:
            source_idx = _find_column(columns, col_name)
            if source_idx is not None:
                break

        for i, row in enumerate(section.get("rows", [])):
            clause_text = row[text_idx] if text_idx is not None and text_idx < len(row) else ""
            basis_text = row[basis_idx] if basis_idx is not None and basis_idx < len(row) else ""
            source_text = row[source_idx] if source_idx is not None and source_idx < len(row) else ""
            if not clause_text or clause_text.strip() in _UNCLEAR_VALUES:
                continue

            # 用原文段落丰富 basis_text
            if tagged_paragraphs:
                basis_text = _build_enriched_basis(basis_text, source_text, tagged_paragraphs)

            clauses.append({
                "source_module": module_key,
                "clause_index": i,
                "clause_text": clause_text,
                "basis_text": basis_text,
                "severity": severity,
            })
```

- [ ] **Step 6: 修改 extract_review_clauses 接受并传递 tagged_paragraphs**

```python
def extract_review_clauses(extracted_data: dict, tagged_paragraphs: list | None = None) -> list[dict]:
    modules = extracted_data.get("modules", {})
    clauses = []
    clauses.extend(_extract_module_clauses(modules, "module_e", "critical", tagged_paragraphs))
    clauses.extend(_extract_module_clauses(modules, "module_b", "major", tagged_paragraphs))
    clauses.extend(_extract_module_clauses(modules, "module_f", "major", tagged_paragraphs))
    clauses.extend(_extract_module_clauses(modules, "module_c", "minor", tagged_paragraphs))
    # ... 重新分配 clause_index
```

- [ ] **Step 7: 运行全部测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_clause_extractor.py -v`
Expected: ALL PASS

### Task 2: 修改 review_task.py 传递 tagged_paragraphs

**Files:**
- Modify: `server/app/tasks/review_task.py:126`
- Modify: `server/app/tasks/pipeline_task.py` (确保 parsed.json 可用)

**背景：** `review_task.py` 调用 `extract_review_clauses(extracted_data)` 时需要传入招标文件的 `tagged_paragraphs`。这些段落来自招标解读管线的 Index 阶段产出（`indexed.json`）。

- [ ] **Step 1: 在 review_task.py 中加载 tagged_paragraphs 并传递**

在 `review_task.py` Step 3 (提取条款) 之前，从 `bid_task` 的 `indexed_path` 加载 `tagged_paragraphs`：

```python
            # Load tagged_paragraphs from bid analysis index
            bid_tagged_paragraphs = _load_bid_tagged_paragraphs(bid_task)

            clauses = extract_review_clauses(extracted_data, tagged_paragraphs=bid_tagged_paragraphs)
```

新增辅助函数：

```python
def _load_bid_tagged_paragraphs(bid_task) -> list:
    """从招标解读的索引结果中加载 tagged_paragraphs。"""
    import json
    from src.models import TaggedParagraph

    indexed_path = bid_task.indexed_path
    if not indexed_path:
        return []
    try:
        with open(indexed_path, "r", encoding="utf-8") as f:
            indexed_data = json.load(f)
        raw_paragraphs = indexed_data.get("tagged_paragraphs", [])
        return [
            TaggedParagraph(
                index=p["index"],
                text=p["text"],
                section_title=p.get("section_title", ""),
                tags=p.get("tags", []),
                table_data=p.get("table_data"),
            )
            for p in raw_paragraphs
        ]
    except Exception:
        return []
```

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import ast; ast.parse(open('server/app/tasks/review_task.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: 重启 worker 并测试**

```bash
docker compose restart worker
```
