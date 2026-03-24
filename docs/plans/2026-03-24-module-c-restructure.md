# 模块C重构：评分与商务综合模块 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构模块C的提取和渲染流程，使其严格按原文子标题层级输出嵌套评分表，并支持交叉引用内联展开。

**Architecture:** 修改3个文件：LLM prompt（重写JSON结构）、段落筛选器（扩大范围+引用检测）、报告生成器（多级编号+note渲染）。模块D不变。

**Tech Stack:** Python 3.12, python-docx, re (正则), 现有 Qwen/DashScope API 调用链

---

## Task 1: 重写模块C的LLM Prompt

**Files:**
- Modify: `config/prompts/module_c.txt` (全部重写)

**Context:** 当前 prompt 输出平铺结构 (C1评标方法 → C2评分细则 → C3价格公式)。需改为支持嵌套子标题层级，分离报价/商务/技术评分，涵盖报价要求、后评价管理、分配规则等商务内容，并处理交叉引用。

- [ ] **Step 1: 重写 prompt 文件**

将 `config/prompts/module_c.txt` 替换为以下内容：

```text
你是招标文件分析专家。请从以下招标文件内容中提取【C. 技术评分模块】的完整信息。

## 提取范围

需要提取以下所有内容（如果文档中存在）：
1. 评分分值构成（评分大类及其分值、权重）
2. 报价评分标准（含各子评分项的评分规则）
3. 商务评分标准（含各子评分项的评分因素、分值、评分标准、证明材料要求）
4. 技术评分标准（含各子评分项的评分因素、分值、评分标准）
5. 评分相等时的优先顺序
6. 报价要求（报价方式、报价范围、报价限制、结算方式、报价货币等）
7. 报价明细/单价最高限价
8. 后评价管理（评价指标、评价运用规则）
9. 分配规则（份额分配机制）

## 核心规则

### 子标题层级
- **严格按照原文的章节编号和子标题结构输出**，不要自行合并或拆分
- 如果原文有 C2.1、C2.2、C2.3 这样的子章节，必须保持这个层级结构
- 使用 `type: "parent"` 表示包含子节的父级，子节通过 `sections` 数组嵌套
- 最多支持两级嵌套（如 C2 → C2.1, C2.2）

### 评分类型分离
- 报价评分、商务评分、技术评分必须作为独立的顶级 section
- 每个评分大类下的子评分项作为嵌套 section

### 交叉引用展开
- 当原文出现"详见评标办法前附表"、"据第X.X款规定的标准"、"见附件XX"等引用时
- 在提供的段落中查找被引用的内容
- 将被引用内容直接展开为完整的表格数据，嵌入到引用位置
- 如果引用的内容在输入段落中找不到，保留原文引用文字并在末尾标注 [未找到引用内容]

### 证明材料与备注
- 如果某个评分项附带"证明材料要求"或"重要提示"，使用 `note` 字段记录
- note 内容不放入表格的 rows 中

## 输出 JSON 格式

```json
{
  "title": "C. 技术评分模块",
  "sections": [
    {
      "id": "C1",
      "title": "评分分值构成",
      "type": "standard_table",
      "columns": ["评分部分", "分值", "权重"],
      "rows": [
        ["投标报价（A）", "70分", "70%"],
        ["商务部分（B）", "20分", "20%"],
        ["技术部分（C）", "10分", "10%"],
        ["总分", "100分", "100%"]
      ]
    },
    {
      "id": "C2",
      "title": "报价评分标准（70分）",
      "type": "parent",
      "sections": [
        {
          "id": "C2.1",
          "title": "卡基部分（20分）",
          "type": "standard_table",
          "columns": ["评分规则", "分值范围"],
          "rows": [
            ["基准价", "所有通过初步评审的供应商卡基报价（不含税）的算术平均值"],
            ["等于基准价", "18分"],
            ["每高于基准价1%", "扣0.3分（最多扣2分）"],
            ["每低于基准价1%", "加0.2分（最多加2分）"]
          ]
        }
      ]
    },
    {
      "id": "C3",
      "title": "商务评分标准（20分）",
      "type": "parent",
      "sections": [
        {
          "id": "C3.1",
          "title": "同类项目案例（6分）",
          "type": "standard_table",
          "columns": ["评分因素", "分值", "评分标准"],
          "rows": [
            ["同类项目案例", "6分", "近三年内...每提供1个有效案例得0.5分，满分6分"]
          ],
          "note": "证明材料要求：合同或协议（需包含合同首页、标的物名称、甲乙双方签章等关键信息）"
        }
      ]
    },
    {
      "id": "C5",
      "title": "评分相等时的优先顺序",
      "type": "standard_table",
      "columns": ["优先顺序", "评分因素"],
      "rows": [["1", "综合得分相等时，投标报价低的优先"]]
    },
    {
      "id": "C6",
      "title": "报价要求",
      "type": "key_value_table",
      "columns": ["项目", "要求"],
      "rows": [["报价方式", "含税包干价格"]]
    },
    {
      "id": "C8",
      "title": "后评价管理",
      "type": "parent",
      "sections": [
        {
          "id": "C8.1",
          "title": "评价指标",
          "type": "standard_table",
          "columns": ["序号", "评价指标", "分值", "评分标准"],
          "rows": [["1", "交货期", "30分", "接到数据后24小时内邮寄..."]]
        }
      ]
    }
  ]
}
```

## 字段说明
- id: 编号，支持两级 C1, C2, C2.1, C2.2 等
- title: 严格跟随原文子标题，包含分值（如"卡基部分（20分）"）
- type: "parent"（含子节）/ "standard_table" / "key_value_table" / "text"
- columns: 表头列名（parent 类型无此字段）
- rows: 数据行（parent 类型无此字段）
- sections: 仅 parent 类型，包含子节数组
- note: 可选，证明材料要求或重要提示

## 注意事项
- 评分表可能跨多页，以表格或正文形式出现，请完整提取
- 如果存在"评标办法"和"评分表"两个独立章节，需要合并
- 分值加总应与总分一致（通常为100分），如有偏差请标注
- 评分细则要尽可能详细，包括每个评分项的具体得分规则
- 保持 JSON 格式严格，不要在 JSON 外添加任何文字说明
- id 必须以 "C" 开头
- 子标题的编号和标题必须与原文一致，不要自行编造
- 如果文档中没有某些内容（如后评价管理、分配规则），则省略对应 section
```

- [ ] **Step 2: 验证 prompt 文件**

Run: `python -c "from pathlib import Path; c = Path('config/prompts/module_c.txt').read_text(encoding='utf-8'); assert '技术评分模块' in c; assert 'parent' in c; assert 'note' in c; assert '交叉引用' in c; print('OK:', len(c), 'chars')"`
Expected: OK with character count

- [ ] **Step 3: Commit**

```bash
git add config/prompts/module_c.txt
git commit -m "refactor(prompt): rewrite module_c prompt for hierarchical scoring structure"
```

---

## Task 2: 增强模块C段落筛选 — 扩大关键词范围

**Files:**
- Modify: `src/extractor/module_c.py:23-28` (关键词常量)
- Modify: `src/extractor/module_c.py:39-45` (文本关键词)
- Test: `tests/test_module_c.py`

**Context:** 现在模块C需要覆盖报价要求、后评价管理、分配规则等内容，段落筛选关键词需扩展。当前 `_RELEVANT_TAGS` 只有 `{"评分", "报价"}`，`_RELEVANT_SECTION_KEYWORDS` 缺少合同/后评价相关词。

- [ ] **Step 1: 写测试 — 验证扩展关键词能筛选到商务内容段落**

在 `tests/test_module_c.py` 中添加：

```python
def test_filter_paragraphs_includes_commercial_content():
    """扩展后的筛选应包含报价要求、后评价、分配规则相关段落"""
    from src.extractor.module_c import _filter_paragraphs
    from src.models import TaggedParagraph

    paragraphs = [
        TaggedParagraph(index=0, text="评分分值构成表", section_title="评标办法"),
        TaggedParagraph(index=1, text="报价方式：含税包干价格"),
        TaggedParagraph(index=2, text="单价最高限价：3.32元/张"),
        TaggedParagraph(index=3, text="后评价管理：季度评价指标"),
        TaggedParagraph(index=4, text="分配规则：首次分配50%：50%"),
        TaggedParagraph(index=5, text="履约保证金金额为20万元"),
        TaggedParagraph(index=6, text="这是一段无关内容"),
    ]
    filtered = _filter_paragraphs(paragraphs)
    filtered_indices = {tp.index for tp in filtered}
    # 前6段都应被选中，第7段不应被选中
    assert 0 in filtered_indices, "评分相关段落应被选中"
    assert 1 in filtered_indices, "报价方式段落应被选中"
    assert 2 in filtered_indices, "限价段落应被选中"
    assert 3 in filtered_indices, "后评价段落应被选中"
    assert 4 in filtered_indices, "分配规则段落应被选中"
    assert 6 not in filtered_indices, "无关段落不应被选中"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_module_c.py::test_filter_paragraphs_includes_commercial_content -v`
Expected: FAIL — 当前关键词缺少 "限价"、"后评价"、"分配" 等词

- [ ] **Step 3: 扩展关键词**

修改 `src/extractor/module_c.py`：

将 `_RELEVANT_TAGS` 改为：
```python
_RELEVANT_TAGS = {"评分", "报价", "合同条款", "商务要求"}
```

将 `_RELEVANT_SECTION_KEYWORDS` 改为：
```python
_RELEVANT_SECTION_KEYWORDS = [
    "评标", "评分", "评审", "打分", "计分", "得分",
    "评标办法", "评分标准", "评分表", "评标标准",
    "报价", "价格", "商务", "技术评审",
    "后评价", "评价管理", "分配规则", "分配方式",
    "报价要求", "报价明细", "限价",
]
```

将 `text_keywords` 改为：
```python
text_keywords = [
    "评标", "评分", "评审", "打分", "计分", "得分",
    "总分", "满分", "权重", "分值",
    "报价得分", "价格得分", "技术得分", "商务得分",
    "最低价", "基准价", "综合评分", "评标委员会",
    "扣分", "加分", "不得分",
    # 报价与商务扩展
    "报价方式", "报价范围", "报价限制", "限价", "单价",
    "后评价", "评价指标", "评价运用",
    "分配规则", "分配比例",
    "履约保证金",
]
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_module_c.py::test_filter_paragraphs_includes_commercial_content -v`
Expected: PASS

- [ ] **Step 5: 运行已有测试确保不回归**

Run: `python -m pytest tests/test_module_c.py -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add src/extractor/module_c.py tests/test_module_c.py
git commit -m "feat(module_c): expand keyword filters for commercial content coverage"
```

---

## Task 3: 增强模块C段落筛选 — 交叉引用检测

**Files:**
- Modify: `src/extractor/module_c.py` (新增 `_resolve_references` 函数，修改 `_filter_paragraphs`)
- Test: `tests/test_module_c.py`

**Context:** 当筛选到的段落中出现"详见评标办法前附表"、"据第2.1款规定"等引用时，需要在全文档段落中搜索被引用的附表/章节段落，追加到筛选结果中，确保 LLM 能看到完整上下文。

- [ ] **Step 1: 写测试 — 交叉引用检测与段落追加**

在 `tests/test_module_c.py` 中添加：

```python
def test_resolve_references_appends_referenced_paragraphs():
    """当筛选段落中有'详见XX'引用时，应从全文档追加被引用段落"""
    from src.extractor.module_c import _resolve_references
    from src.models import TaggedParagraph

    all_paragraphs = [
        TaggedParagraph(index=0, text="评分标准详见评标办法前附表"),
        TaggedParagraph(index=1, text="这是无关段落"),
        TaggedParagraph(index=2, text="这是无关段落2"),
        TaggedParagraph(index=3, text="评标办法前附表：评分项与分值", section_title="评标办法前附表"),
        TaggedParagraph(index=4, text="技术评分30分，商务评分20分"),
        TaggedParagraph(index=5, text="据第2.1款规定的标准执行"),
        TaggedParagraph(index=6, text="第2.1款 卡片质量标准", section_title="2.1 卡片质量标准"),
    ]
    selected = [all_paragraphs[0], all_paragraphs[5]]
    selected_indices = {0, 5}

    resolved = _resolve_references(selected, all_paragraphs, selected_indices)
    resolved_indices = {tp.index for tp in resolved}

    assert 3 in resolved_indices, "应追加'评标办法前附表'段落"
    assert 6 in resolved_indices, "应追加'第2.1款'段落"
    assert 1 not in resolved_indices, "不应追加无关段落"


def test_resolve_references_no_duplicates():
    """已选中的段落不应被重复追加"""
    from src.extractor.module_c import _resolve_references
    from src.models import TaggedParagraph

    all_paragraphs = [
        TaggedParagraph(index=0, text="详见评标办法前附表", section_title="评标办法"),
        TaggedParagraph(index=1, text="评标办法前附表内容", section_title="评标办法前附表"),
    ]
    selected = [all_paragraphs[0], all_paragraphs[1]]
    selected_indices = {0, 1}

    resolved = _resolve_references(selected, all_paragraphs, selected_indices)
    assert len(resolved) == 0, "已选中的段落不应被重复追加"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_module_c.py::test_resolve_references_appends_referenced_paragraphs tests/test_module_c.py::test_resolve_references_no_duplicates -v`
Expected: FAIL — `_resolve_references` 函数不存在

- [ ] **Step 3: 实现 `_resolve_references` 函数**

在 `src/extractor/module_c.py` 中，在 `import` 区域添加 `import re`，然后在 `_filter_paragraphs` 函数之前添加：

```python
import re

_REF_PATTERNS = [
    re.compile(r"详见[《「]?(.+?)[》」\s，。]"),
    re.compile(r"按照?[《「]?(.+?)[》」]?的?规定"),
    re.compile(r"据第\s*(\d+\.?\d*)\s*款"),
    re.compile(r"见附[件表录]\s*[《「]?(.+?)[》」\s，。]"),
    re.compile(r"参照[《「]?(.+?)[》」\s，。]"),
]


def _resolve_references(
    selected: list[TaggedParagraph],
    all_paragraphs: list[TaggedParagraph],
    selected_indices: set[int],
) -> list[TaggedParagraph]:
    """检测已筛选段落中的交叉引用，从全文档追加被引用段落。

    返回新追加的段落列表（不含已选中的）。
    """
    ref_targets: list[str] = []
    for tp in selected:
        for pattern in _REF_PATTERNS:
            for match in pattern.finditer(tp.text):
                ref_targets.append(match.group(1))

    if not ref_targets:
        return []

    appended: list[TaggedParagraph] = []
    for tp in all_paragraphs:
        if tp.index in selected_indices:
            continue
        for target in ref_targets:
            if tp.section_title and target in tp.section_title:
                appended.append(tp)
                selected_indices.add(tp.index)
                break
            if target in tp.text and len(target) >= 2:
                appended.append(tp)
                selected_indices.add(tp.index)
                break

    return appended
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_module_c.py::test_resolve_references_appends_referenced_paragraphs tests/test_module_c.py::test_resolve_references_no_duplicates -v`
Expected: PASS

- [ ] **Step 5: 在 `_filter_paragraphs` 末尾集成引用解析**

在 `_filter_paragraphs` 函数中，`selected.sort(...)` 之前添加：

```python
    # 交叉引用解析：检测已筛选段落中的引用，追加被引用段落
    ref_appended = _resolve_references(selected, tagged_paragraphs, selected_indices)
    if ref_appended:
        selected.extend(ref_appended)
        logger.info("module_c: 交叉引用追加了 %d 个段落", len(ref_appended))
```

- [ ] **Step 6: 运行所有 module_c 测试**

Run: `python -m pytest tests/test_module_c.py -v`
Expected: 所有测试 PASS

- [ ] **Step 7: Commit**

```bash
git add src/extractor/module_c.py tests/test_module_c.py
git commit -m "feat(module_c): add cross-reference detection and paragraph resolution"
```

---

## Task 4: 更新模块C默认标题

**Files:**
- Modify: `src/extractor/module_c.py:140` (默认标题)

**Context:** 模块C标题从"C. 评标办法与评分标准"改为"C. 技术评分模块"。

- [ ] **Step 1: 修改默认标题**

将 `src/extractor/module_c.py` 第140行：
```python
        result["title"] = "C. 评标办法与评分标准"
```
改为：
```python
        result["title"] = "C. 技术评分模块"
```

- [ ] **Step 2: 更新模块 docstring**

将文件开头的 docstring：
```python
"""module_c: C. 评标办法与评分标准 提取模块

最复杂的模块之一：需精确提取评分表结构（多层嵌套的评分项及其分值）。
可能需要合并"评标办法"和"评分表"两个独立章节。
"""
```
改为：
```python
"""module_c: C. 技术评分模块 提取模块

提取评分分值构成、报价/商务/技术评分标准、报价要求、后评价管理、分配规则。
支持多层嵌套子标题结构和交叉引用段落追加。
"""
```

- [ ] **Step 3: 运行已有测试确保不回归**

Run: `python -m pytest tests/test_module_c.py -v`
Expected: 所有测试 PASS（`test_module_c_json_schema` 中检查 `startswith("C")`，新标题仍以 C 开头）

- [ ] **Step 4: Commit**

```bash
git add src/extractor/module_c.py
git commit -m "refactor(module_c): update module title and docstring"
```

---

## Task 5: 报告生成器 — 多级编号支持

**Files:**
- Modify: `src/generator/report_gen.py:104-141` (`_render_sections` 函数)
- Test: `tests/test_report_gen.py`

**Context:** 当前 `_render_sections` 对所有层级使用 `{letter}.{idx}` 编号。递归调用子 sections 时仍传递 `module_letter`，导致子节编号也是 `C.1`, `C.2` 格式而非 `C2.1`, `C2.2`。需要改为：顶层用 `C1, C2`，嵌套层用 `C2.1, C2.2`。

JSON 中已有 `id` 字段（如 `C1`, `C2.1`），直接使用 `id` 作为编号前缀，不再自行计算。

- [ ] **Step 1: 写测试 — 嵌套 sections 使用正确编号**

在 `tests/test_report_gen.py` 中添加：

```python
def test_render_report_nested_section_numbering(tmp_path):
    """嵌套 sections 应使用 id 字段作为编号，如 C2.1, C2.2"""
    data = {
        "schema_version": "1.0",
        "modules": {
            "module_c": {
                "title": "C. 技术评分模块",
                "sections": [
                    {
                        "id": "C1",
                        "title": "评分分值构成",
                        "type": "standard_table",
                        "columns": ["评分部分", "分值"],
                        "rows": [["报价", "70分"], ["商务", "20分"]],
                    },
                    {
                        "id": "C2",
                        "title": "报价评分标准（70分）",
                        "type": "parent",
                        "sections": [
                            {
                                "id": "C2.1",
                                "title": "卡基部分（20分）",
                                "type": "standard_table",
                                "columns": ["规则", "分值"],
                                "rows": [["等于基准价", "18分"]],
                            },
                            {
                                "id": "C2.2",
                                "title": "特殊工艺部分（15分）",
                                "type": "standard_table",
                                "columns": ["规则", "分值"],
                                "rows": [["等于基准价", "13.5分"]],
                            },
                        ],
                    },
                ],
            },
        },
    }
    out = str(tmp_path / "report.docx")
    render_report(data, out)

    doc = Document(out)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "C1" in full_text, "应显示 C1 编号"
    assert "C2" in full_text, "应显示 C2 编号"
    assert "C2.1" in full_text, "应显示 C2.1 编号"
    assert "C2.2" in full_text, "应显示 C2.2 编号"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_report_gen.py::test_render_report_nested_section_numbering -v`
Expected: FAIL — 当前 parent type 没有输出表格，且编号逻辑不对

- [ ] **Step 3: 修改 `_render_sections` 使用 section id 作为编号**

将 `src/generator/report_gen.py` 中的 `_render_sections` 函数替换为：

```python
def _render_sections(
    doc: Document,
    sections: list,
    table_builder: TableBuilder,
    style_mgr: StyleManager,
    module_letter: str,
    parent_idx: int = 0,
) -> None:
    """渲染 sections 列表，使用 section 的 id 字段作为编号前缀。"""
    for idx, section in enumerate(sections, 1):
        section_type = section.get("type", "")
        section_title = section.get("title", "")
        section_id = section.get("id", "")

        # 子标题：使用 id 作为编号前缀
        if section_title:
            if section_id:
                numbered_title = f"{section_id} {section_title}"
            elif module_letter:
                numbered_title = f"{module_letter}.{idx} {section_title}"
            else:
                numbered_title = section_title
            sub_para = doc.add_paragraph()
            sub_run = sub_para.add_run(numbered_title)
            style_mgr.apply_run_style(sub_run, "heading3")

        # 渲染内容 — 只允许表格，并添加勾选列
        if section_type in ("key_value_table", "standard_table"):
            section_no_title = {k: v for k, v in section.items() if k != "title"}
            section_with_check = _add_checkbox_column(section_no_title)
            table_builder.build(section_with_check, doc)
        elif section_type in ("text", "template"):
            content = section.get("content", "")
            if content:
                _render_text_as_table(doc, section_title, content, table_builder, style_mgr)

        # note 字段渲染
        note = section.get("note", "")
        if note:
            _render_note(doc, note, style_mgr)

        # 递归处理子 sections（parent type）
        sub_sections = section.get("sections", [])
        if sub_sections:
            _render_sections(doc, sub_sections, table_builder, style_mgr, module_letter)
```

- [ ] **Step 4: 运行新测试验证通过**

Run: `python -m pytest tests/test_report_gen.py::test_render_report_nested_section_numbering -v`
Expected: PASS

- [ ] **Step 5: 运行已有测试确保编号不回归**

Run: `python -m pytest tests/test_report_gen.py -v`
Expected: `test_render_report_section_numbering` 会 FAIL，因为它期望 `A.1` / `A.2` 格式但现在使用 `id` 字段（`A1` / `A2`）

- [ ] **Step 6: 更新已有编号测试**

将 `tests/test_report_gen.py::test_render_report_section_numbering` 中的断言改为：

```python
    assert "A1" in full_text
    assert "A2" in full_text
```

因为现在使用 section 的 `id` 字段作为编号。

- [ ] **Step 7: 再次运行全部测试**

Run: `python -m pytest tests/test_report_gen.py -v`
Expected: 所有测试 PASS

- [ ] **Step 8: Commit**

```bash
git add src/generator/report_gen.py tests/test_report_gen.py
git commit -m "feat(report_gen): use section id for numbering, support nested sections"
```

---

## Task 6: 报告生成器 — note 字段渲染

**Files:**
- Modify: `src/generator/report_gen.py` (新增 `_render_note` 函数)
- Test: `tests/test_report_gen.py`

**Context:** 部分评分项有证明材料要求或重要提示，通过 `note` 字段传递，需渲染在表格下方，灰色小字。

- [ ] **Step 1: 写测试 — note 字段应渲染在表格下方**

在 `tests/test_report_gen.py` 中添加：

```python
def test_render_report_note_field(tmp_path):
    """section 的 note 字段应渲染在表格下方"""
    data = {
        "schema_version": "1.0",
        "modules": {
            "module_c": {
                "title": "C. 技术评分模块",
                "sections": [
                    {
                        "id": "C3.1",
                        "title": "同类项目案例（6分）",
                        "type": "standard_table",
                        "columns": ["评分因素", "分值"],
                        "rows": [["同类项目案例", "6分"]],
                        "note": "证明材料要求：合同或协议（需包含合同首页、标的物名称）",
                    },
                ],
            },
        },
    }
    out = str(tmp_path / "report.docx")
    render_report(data, out)

    doc = Document(out)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "证明材料要求" in full_text, "note 内容应出现在段落中"

    # 验证 note 文字为灰色
    found_gray = False
    for para in doc.paragraphs:
        for run in para.runs:
            if "证明材料要求" in run.text:
                if run.font.color.rgb == RGBColor(0x99, 0x99, 0x99):
                    found_gray = True
    assert found_gray, "note 文字应为灰色"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_report_gen.py::test_render_report_note_field -v`
Expected: FAIL — `_render_note` 函数不存在（如果 Task 5 的 `_render_sections` 已引用它）

- [ ] **Step 3: 实现 `_render_note` 函数**

在 `src/generator/report_gen.py` 的 `_render_text_as_table` 函数之后添加：

```python
def _render_note(doc: Document, note: str, style_mgr: StyleManager) -> None:
    """渲染 note 备注文本，灰色小字。"""
    para = doc.add_paragraph()
    run = para.add_run(note)
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_report_gen.py::test_render_report_note_field -v`
Expected: PASS

- [ ] **Step 5: 运行全部报告生成器测试**

Run: `python -m pytest tests/test_report_gen.py -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add src/generator/report_gen.py tests/test_report_gen.py
git commit -m "feat(report_gen): render note field as gray text below tables"
```

---

## Task 7: 集成测试 — 完整模块C数据渲染

**Files:**
- Test: `tests/test_report_gen.py`

**Context:** 用一份完整的模块C嵌套JSON数据测试端到端渲染，确保所有功能协同工作。

- [ ] **Step 1: 写集成测试**

在 `tests/test_report_gen.py` 中添加：

```python
def test_render_report_full_module_c_structure(tmp_path):
    """完整模块C结构：嵌套parent、note、多种表格类型"""
    data = {
        "schema_version": "1.0",
        "modules": {
            "module_c": {
                "title": "C. 技术评分模块",
                "sections": [
                    {
                        "id": "C1",
                        "title": "评分分值构成",
                        "type": "standard_table",
                        "columns": ["评分部分", "分值", "权重"],
                        "rows": [
                            ["投标报价", "70分", "70%"],
                            ["商务部分", "20分", "20%"],
                            ["技术部分", "10分", "10%"],
                        ],
                    },
                    {
                        "id": "C2",
                        "title": "报价评分标准（70分）",
                        "type": "parent",
                        "sections": [
                            {
                                "id": "C2.1",
                                "title": "卡基部分（20分）",
                                "type": "standard_table",
                                "columns": ["评分规则", "分值范围"],
                                "rows": [["等于基准价", "18分"]],
                            },
                        ],
                    },
                    {
                        "id": "C3",
                        "title": "商务评分标准（20分）",
                        "type": "parent",
                        "sections": [
                            {
                                "id": "C3.1",
                                "title": "同类项目案例（6分）",
                                "type": "standard_table",
                                "columns": ["评分因素", "分值", "评分标准"],
                                "rows": [["同类项目案例", "6分", "每个案例0.5分"]],
                                "note": "证明材料要求：合同或协议",
                            },
                        ],
                    },
                    {
                        "id": "C5",
                        "title": "评分相等时的优先顺序",
                        "type": "standard_table",
                        "columns": ["优先顺序", "评分因素"],
                        "rows": [["1", "投标报价低的优先"]],
                    },
                    {
                        "id": "C6",
                        "title": "报价要求",
                        "type": "key_value_table",
                        "columns": ["项目", "要求"],
                        "rows": [["报价方式", "含税包干价格"]],
                    },
                ],
            },
        },
    }
    out = str(tmp_path / "report.docx")
    render_report(data, out)

    doc = Document(out)
    full_text = "\n".join(p.text for p in doc.paragraphs)

    # 验证所有编号标题存在
    assert "C1" in full_text
    assert "C2" in full_text
    assert "C2.1" in full_text
    assert "C3" in full_text
    assert "C3.1" in full_text
    assert "C5" in full_text
    assert "C6" in full_text

    # 验证关键内容
    assert "技术评分模块" in full_text
    assert "证明材料要求" in full_text

    # 验证表格数量：C1(1) + C2.1(1) + C3.1(1) + C5(1) + C6(1) = 5
    assert len(doc.tables) == 5
```

- [ ] **Step 2: 运行集成测试**

Run: `python -m pytest tests/test_report_gen.py::test_render_report_full_module_c_structure -v`
Expected: PASS

- [ ] **Step 3: 运行完整测试套件**

Run: `python -m pytest tests/ -v --ignore=tests/test_e2e.py`
Expected: 所有测试 PASS（排除 e2e 测试，因为它可能需要测试文档）

- [ ] **Step 4: Commit**

```bash
git add tests/test_report_gen.py
git commit -m "test(report_gen): add integration test for full Module C structure"
```
