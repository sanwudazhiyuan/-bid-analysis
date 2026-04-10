# 细粒度索引 + 精确映射 + 智能拆分 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将审查系统的索引从 2-3 层固定结构升级为任意深度章节树，条款映射精确到叶子节点 path，避免批注堆叠和错位标记。

**Architecture:** 新建 `chapter_tree.py` 实现栈式任意深度树构建算法；`clause_mapper` 新增叶子节点映射函数；`tender_indexer` 新增精确段落提取和智能拆分；`review_task` 从批量审查改为逐条独立审查；`docx_annotator` 读取新的 `global_para_indices` 格式并合并同段落批注。

**Tech Stack:** Python 3.11, dataclasses, regex, Celery, python-docx, lxml

---

## 文件变更清单

### 新建
- `src/reviewer/chapter_tree.py` — 章节树构建核心算法（栈式层级构建 + path 赋值 + needs_split 标记）
- `src/reviewer/tests/test_chapter_tree.py` — 树构建单元测试

### 修改
- `src/reviewer/tender_rule_splitter.py` — 扩展编号正则支持 5+ 级 + 替换 `_sections_to_chapters` 为 `chapter_tree.build_chapter_tree` + `all_paths` 生成
- `src/reviewer/tender_indexer.py` — 新增 `find_node_by_path`、`get_text_for_clause`、`ClauseBatch`、`_paragraphs_to_text`、`map_review_location`、`_map_batch_indices_to_global`
- `src/reviewer/clause_mapper.py` — 新增 `llm_map_clauses_to_leaf_nodes` + `_build_chapter_tree_text`；旧函数标注废弃
- `config/prompts/review_mapping.txt` — 替换为叶子节点映射版本
- `src/reviewer/reviewer.py` — `llm_review_batch` 标注 `@deprecated`
- `src/reviewer/docx_annotator.py` — 改为读取 `global_para_indices` + 合并同段落批注
- `server/app/tasks/review_task.py` — 逐条独立审查循环 + 新辅助函数 + 细粒度进度更新

---

## Chunk 1: 索引层 — 任意深度章节树

### Task 1: chapter_tree.py — 数据结构与构建算法

**Files:**
- Create: `src/reviewer/chapter_tree.py`
- Test: `src/reviewer/tests/test_chapter_tree.py`

- [ ] **Step 1: 写 test_chapter_tree.py 失败测试 — 基本树构建**

```python
# src/reviewer/tests/test_chapter_tree.py
"""Tests for chapter tree builder."""


def test_build_single_level():
    """只有 level-1 节点的扁平文档。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章 投标函", "start": 0, "level": 1},
        {"title": "第二章 技术方案", "start": 10, "level": 1},
        {"title": "第三章 商务报价", "start": 20, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=30)

    assert len(tree) == 3
    assert tree[0]["title"] == "第一章 投标函"
    assert tree[0]["path"] == "/第一章 投标函"
    assert tree[0]["start_para"] == 0
    assert tree[0]["end_para"] == 9
    assert tree[0]["is_leaf"] is True
    assert tree[0]["para_count"] == 10
    assert tree[2]["end_para"] == 29


def test_build_nested_two_levels():
    """2 层嵌套：level-1 下有 level-2 子节点。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章 投标函", "start": 0, "level": 1},
        {"title": "1.1 投标函内容", "start": 2, "level": 2},
        {"title": "1.2 授权委托书", "start": 8, "level": 2},
        {"title": "第二章 技术方案", "start": 15, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=30)

    assert len(tree) == 2  # 两个 level-1 根节点
    ch1 = tree[0]
    assert ch1["is_leaf"] is False
    assert len(ch1["children"]) == 2
    assert ch1["children"][0]["path"] == "/第一章 投标函/1.1 投标函内容"
    assert ch1["children"][0]["is_leaf"] is True
    assert ch1["children"][1]["path"] == "/第一章 投标函/1.2 授权委托书"


def test_build_four_levels():
    """4 层嵌套树。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "一、概述", "start": 2, "level": 2},
        {"title": "（一）背景", "start": 3, "level": 3},
        {"title": "1.1.1 详情", "start": 4, "level": 4},
        {"title": "第二章", "start": 10, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=20)

    ch1 = tree[0]
    assert ch1["is_leaf"] is False
    child_l2 = ch1["children"][0]
    assert child_l2["title"] == "一、概述"
    child_l3 = child_l2["children"][0]
    assert child_l3["title"] == "（一）背景"
    child_l4 = child_l3["children"][0]
    assert child_l4["title"] == "1.1.1 详情"
    assert child_l4["path"] == "/第一章/一、概述/（一）背景/1.1.1 详情"
    assert child_l4["is_leaf"] is True


def test_needs_split_large_leaf():
    """叶子节点段落数超 1200 标记 needs_split=True。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=2000)

    assert tree[0]["is_leaf"] is True
    assert tree[0]["needs_split"] is True
    assert tree[0]["para_count"] == 2000


def test_needs_split_small_leaf():
    """叶子节点段落数 <= 1200 不标记 needs_split。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=100)

    assert tree[0]["needs_split"] is False


def test_collect_all_paths():
    """collect_all_paths 返回扁平 path 列表。"""
    from src.reviewer.chapter_tree import build_chapter_tree, collect_all_paths

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "1.1 概述", "start": 2, "level": 2},
        {"title": "第二章", "start": 10, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=20)
    paths = collect_all_paths(tree)

    assert "/第一章" in paths
    assert "/第一章/1.1 概述" in paths
    assert "/第二章" in paths
    assert len(paths) == 3


def test_empty_sections():
    """空输入返回空列表。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    assert build_chapter_tree([], total_paragraphs=100) == []


def test_siblings_same_level():
    """同级兄弟节点 end_para 正确切分。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "1.1", "start": 2, "level": 2},
        {"title": "1.2", "start": 5, "level": 2},
        {"title": "1.3", "start": 8, "level": 2},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=12)

    ch1 = tree[0]
    assert len(ch1["children"]) == 3
    assert ch1["children"][0]["end_para"] == 4
    assert ch1["children"][1]["end_para"] == 7
    assert ch1["children"][2]["end_para"] == 11
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_chapter_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.reviewer.chapter_tree'`

- [ ] **Step 3: 实现 chapter_tree.py**

```python
# src/reviewer/chapter_tree.py
"""任意深度章节树构建算法。

从扁平 sections（含 title, start, level）构建嵌套章节树，
支持任意层级深度、path 赋值、叶子拆分标记。
"""

from dataclasses import dataclass, field

LEAF_SPLIT_THRESHOLD = 1200  # 段落数阈值（约 30 页）


@dataclass
class _Section:
    title: str
    start: int
    level: int
    end: int = 0
    para_count: int = 0
    children: list["_Section"] = field(default_factory=list)
    _path: str = ""


def build_chapter_tree(
    sections: list[dict], total_paragraphs: int
) -> list[dict]:
    """从扁平 sections 构建任意深度章节树。

    Args:
        sections: [{title, start, level}] 已按 start 升序排序
        total_paragraphs: 文档总段落数

    Returns:
        嵌套章节树列表，每个节点含 title, path, level, start_para, end_para,
        para_count, is_leaf, needs_split, children
    """
    if not sections:
        return []

    nodes = [
        _Section(title=s["title"], start=s["start"], level=s["level"])
        for s in sorted(sections, key=lambda s: s["start"])
    ]

    # Step 1: 计算 end_para
    for i, node in enumerate(nodes):
        if i + 1 < len(nodes):
            node.end = nodes[i + 1].start - 1
        else:
            node.end = total_paragraphs - 1

    # Step 2: 用栈构建层级关系
    stack: list[_Section] = []
    root: list[_Section] = []

    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()

        if not stack:
            root.append(node)
        else:
            stack[-1].children.append(node)

        stack.append(node)

    # Step 3: 赋值 path
    def assign_paths(nodes: list[_Section], parent_path: str = "") -> None:
        for n in nodes:
            n._path = f"{parent_path}/{n.title}"
            assign_paths(n.children, n._path)

    assign_paths(root)

    # Step 4: 递归 finalize — 计算 para_count、is_leaf、needs_split
    def finalize(n: _Section) -> dict:
        if not n.children:
            n.para_count = n.end - n.start + 1
            is_leaf = True
        else:
            children_dicts = [finalize(c) for c in n.children]
            n.para_count = sum(c.para_count for c in n.children)
            is_leaf = False

        result = {
            "title": n.title,
            "path": n._path,
            "level": n.level,
            "start_para": n.start,
            "end_para": n.end,
            "para_count": n.para_count,
            "is_leaf": is_leaf,
            "needs_split": is_leaf and n.para_count > LEAF_SPLIT_THRESHOLD,
            "children": [] if is_leaf else children_dicts,
        }
        return result

    return [finalize(n) for n in root]


def collect_all_paths(tree: list[dict]) -> list[str]:
    """递归收集所有节点的 path 为扁平列表。"""
    paths: list[str] = []

    def _walk(nodes: list[dict]) -> None:
        for node in nodes:
            paths.append(node["path"])
            _walk(node.get("children", []))

    _walk(tree)
    return paths
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_chapter_tree.py -v`
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/chapter_tree.py src/reviewer/tests/test_chapter_tree.py
git commit -m "feat(reviewer): add chapter_tree module for arbitrary-depth indexing"
```

---

### Task 2: tender_rule_splitter.py — 扩展正则 + 替换树构建

**Files:**
- Modify: `src/reviewer/tender_rule_splitter.py:49-55` (正则), `128-173` (_sections_to_chapters), `356-419` (build_tender_index)
- Modify: `src/reviewer/tests/test_tender_rule_splitter.py`

- [ ] **Step 1: 写测试 — 数字层级正则匹配**

在 `src/reviewer/tests/test_tender_rule_splitter.py` 末尾追加：

```python
# ========== 扩展正则（数字层级）==========

class TestDotNumberRegex:
    def test_dot_number_l4(self):
        """1.1.1 匹配为 level 4+。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert _RE_DOT.match("1.1.1 基本信息")

    def test_dot_number_l5(self):
        """1.1.1.1 匹配为 level 4+。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert _RE_DOT.match("1.1.1.1 公司名称")

    def test_dot_number_not_single(self):
        """单个数字不匹配。"""
        from src.reviewer.tender_rule_splitter import _RE_DOT
        assert not _RE_DOT.match("1 概述")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_rule_splitter.py::TestDotNumberRegex -v`
Expected: FAIL — `ImportError: cannot import name '_RE_DOT'`

- [ ] **Step 3: 添加 _RE_DOT 正则 + 扩展 strategy_numbering**

在 `src/reviewer/tender_rule_splitter.py:55` 之后添加：

```python
_RE_DOT = re.compile(r"^\d+(?:\.\d+)+")
```

修改 `strategy_numbering` 函数，在 level 3 检测后追加：

```python
        # Level 4+: 数字层级 1.1 / 1.1.1 / 1.1.1.1
        elif _RE_DOT.match(text):
            dot_count = text.split()[0].count(".")
            level = 3 + dot_count  # 1.1→L4, 1.1.1→L5, 1.1.1.1→L6
            sections.append({"title": text, "start": para.index, "level": level})
```

- [ ] **Step 4: 运行正则测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_rule_splitter.py::TestDotNumberRegex -v`
Expected: 3 tests PASS

- [ ] **Step 5: 替换 _sections_to_chapters 为 chapter_tree 调用**

删除 `src/reviewer/tender_rule_splitter.py:129-173` 的全部旧实现代码（扁平 sections→层级构建逻辑），替换 `_sections_to_chapters` 函数体为：

```python
def _sections_to_chapters(sections: list[dict], total_paragraphs: int) -> list[dict]:
    """对外接口：调用 chapter_tree.build_chapter_tree 构建任意深度树。"""
    from src.reviewer.chapter_tree import build_chapter_tree
    return build_chapter_tree(sections, total_paragraphs)
```

- [ ] **Step 6: 修改 build_tender_index 返回值添加 all_paths**

在 `src/reviewer/tender_rule_splitter.py` 的 `build_tender_index` 函数中，每个 `return` 前添加 `all_paths`：

```python
from src.reviewer.chapter_tree import collect_all_paths

# 在每个 return 语句之前：
chapters = _sections_to_chapters(...)
all_paths = collect_all_paths(chapters)
return {
    "toc_source": ...,
    "confidence": ...,
    "chapters": chapters,
    "all_paths": all_paths,
}
```

共 3 处 return 需要修改：
- 行 377-381（策略 1）：`chapters = _sections_to_chapters(...)` 后加 `all_paths = collect_all_paths(chapters)`
- 行 407-409（LLM 兜底）：此分支返回 `build_index_from_toc()` 结果，需在 return 前加 `index["all_paths"] = collect_all_paths(index.get("chapters", []))`
- 行 414-419（最佳规则）：同策略 1 处理方式

注意：LLM 兜底分支的 `build_index_from_toc()` 返回旧格式（无 `path`/`is_leaf` 字段），`collect_all_paths` 需要 `path` 字段。因此需要先将 `_sections_to_chapters`（已改为调用 `build_chapter_tree`）应用到 LLM 兜底的结果上，或在 LLM 兜底后也使用 `_sections_to_chapters` 重建 chapters。修改方式：

```python
# LLM 兜底分支修改为：
toc = llm_extract_toc(paragraphs, api_settings)
if toc:
    index = build_index_from_toc(toc, paragraphs)
    # 重建为新格式树
    flat_sections = []
    for ch in index.get("chapters", []):
        flat_sections.append({"title": ch["title"], "start": ch["start_para"], "level": ch["level"]})
        for child in ch.get("children", []):
            flat_sections.append({"title": child["title"], "start": child["start_para"], "level": child["level"]})
    chapters = _sections_to_chapters(flat_sections, total)
    all_paths = collect_all_paths(chapters)
    return {
        "toc_source": "llm_generated",
        "confidence": 0.5,
        "chapters": chapters,
        "all_paths": all_paths,
    }
```

- [ ] **Step 7: 运行全部 tender_rule_splitter 测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_rule_splitter.py -v`
Expected: 所有测试 PASS（现有测试兼容新 chapter 格式，因为新格式保留了 title、level、start_para、end_para、children 字段）

- [ ] **Step 8: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/tender_rule_splitter.py src/reviewer/tests/test_tender_rule_splitter.py
git commit -m "feat(reviewer): extend numbering regex to 5+ levels, use chapter_tree for indexing"
```

---

## Chunk 2: 映射层 — 精确到叶子节点

### Task 3: clause_mapper.py — 新增叶子节点映射函数

**Files:**
- Modify: `src/reviewer/clause_mapper.py:42-80`
- Replace: `config/prompts/review_mapping.txt`

- [ ] **Step 1: 替换 review_mapping.txt prompt 模板**

覆写 `config/prompts/review_mapping.txt`：

```text
你是招标审查专家。请将以下审查条款映射到投标文件的最细粒度章节节点。

## 审查条款
{clauses}

## 投标文件章节树（从最细粒度列出所有叶子节点及其父级路径）
{chapter_tree}

映射规则:
- 优先映射到叶子节点（段落数最少，定位最精准）
- 如果某条款在所有叶子节点中都没有明确相关，则映射到其最小相关父节点
- 一个条款可以映射到多个节点（如条款涉及多个方面）
- 返回每个条款所有相关节点的完整 path（与下方列表中的 path 完全一致）
- 只返回直接相关的节点，不要返回上级节点（除非上级本身有关联内容）

## 返回格式
返回 JSON 数组，每个元素对应一条条款：
[
  {{"clause_index": 0, "relevant_paths": ["/第一章 投标函/1.1 投标函内容/1.1.1 基本信息/1.1.1.1 公司名称", ...]}},
  ...
]
```

- [ ] **Step 2: 写测试 — _build_chapter_tree_text 格式验证**

在 `src/reviewer/tests/test_tender_rule_splitter.py` 末尾追加（clause_mapper 测试放在同文件，因为它依赖索引结构）：

```python
class TestBuildChapterTreeText:
    def test_output_format(self):
        """验证章节树文本输出缩进和叶子标签。"""
        from src.reviewer.clause_mapper import _build_chapter_tree_text

        tender_index = {"chapters": [
            {"path": "/第一章", "para_count": 20, "is_leaf": False, "needs_split": False, "children": [
                {"path": "/第一章/1.1", "para_count": 10, "is_leaf": True, "needs_split": False, "children": []},
                {"path": "/第一章/1.2", "para_count": 10, "is_leaf": True, "needs_split": False, "children": []},
            ]},
        ]}
        text = _build_chapter_tree_text(tender_index)
        lines = text.strip().split("\n")
        assert len(lines) == 3
        assert "/第一章" in lines[0]
        assert "叶子" not in lines[0]  # 非叶子不标记
        assert "  /第一章/1.1" in lines[1]  # 缩进
        assert "叶子" in lines[1]

    def test_needs_split_tag(self):
        """需要拆分的叶子显示拆分标签。"""
        from src.reviewer.clause_mapper import _build_chapter_tree_text

        tender_index = {"chapters": [
            {"path": "/大章", "para_count": 2000, "is_leaf": True, "needs_split": True, "children": []},
        ]}
        text = _build_chapter_tree_text(tender_index)
        assert "需拆分" in text
```

- [ ] **Step 3: 在 clause_mapper.py 添加 _build_chapter_tree_text 辅助函数**

在 `src/reviewer/clause_mapper.py` 末尾追加：

```python
def _build_chapter_tree_text(tender_index: dict) -> str:
    """将章节树格式化为供 LLM 阅读的缩进文本。"""
    lines: list[str] = []

    def _walk(nodes: list[dict], depth: int = 0) -> None:
        indent = "  " * depth
        for node in nodes:
            leaf_tag = ", 叶子" if node.get("is_leaf") else ""
            split_tag = ", 需拆分" if node.get("needs_split") else ""
            lines.append(
                f"{indent}{node['path']} [段落数: {node.get('para_count', 0)}{leaf_tag}{split_tag}]"
            )
            _walk(node.get("children", []), depth + 1)

    _walk(tender_index.get("chapters", []))
    return "\n".join(lines)
```

- [ ] **Step 4: 在 clause_mapper.py 添加 llm_map_clauses_to_leaf_nodes 函数**

在 `_build_chapter_tree_text` 之后追加：

```python
def llm_map_clauses_to_leaf_nodes(
    clauses: list[dict],
    tender_index: dict,
    api_settings: dict | None = None,
) -> dict[int, list[str]]:
    """Map clauses to leaf node paths. Returns {clause_index: [path, ...]}.

    替代 llm_map_clauses_to_chapters，映射到精确的叶子节点 path 而非章节标题。
    """
    chapter_tree_text = _build_chapter_tree_text(tender_index)

    clauses_text = "\n".join(
        f"[{c['clause_index']}] [{c['severity']}] {c['clause_text']}"
        for c in clauses
    )

    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{clauses}", clauses_text)
        .replace("{chapter_tree}", chapter_tree_text)
    )

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    mapping: dict[int, list[str]] = {}
    if isinstance(result, list):
        for item in result:
            idx = item.get("clause_index")
            paths = item.get("relevant_paths", [])
            if idx is not None:
                mapping[idx] = paths
    elif isinstance(result, dict) and "mappings" in result:
        for item in result["mappings"]:
            idx = item.get("clause_index")
            paths = item.get("relevant_paths", [])
            if idx is not None:
                mapping[idx] = paths

    return mapping
```

- [ ] **Step 5: 标注旧函数废弃**

在 `llm_map_clauses_to_chapters` 函数（行 42）的 docstring 开头添加：

```python
    """[DEPRECATED] Use llm_map_clauses_to_leaf_nodes instead.

    Map clause indices to relevant chapter titles via LLM.
    ...
    """
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_rule_splitter.py::TestBuildChapterTreeText -v`
Expected: 2 tests PASS

- [ ] **Step 7: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/clause_mapper.py config/prompts/review_mapping.txt src/reviewer/tests/test_tender_rule_splitter.py
git commit -m "feat(reviewer): add leaf-node clause mapping with tree-formatted prompt"
```

---

## Chunk 3: 检索层 + 审查层 — 精确段落提取 + 逐条审查

### Task 4: tender_indexer.py — 新增精确段落提取和拆分

**Files:**
- Modify: `src/reviewer/tender_indexer.py`
- Test: `src/reviewer/tests/test_tender_indexer.py`

- [ ] **Step 1: 写失败测试 — find_node_by_path**

在 `src/reviewer/tests/test_tender_indexer.py` 末尾追加：

```python
# ========== 新增：精确段落提取 ==========

class TestFindNodeByPath:
    def test_find_root(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": [
            {"path": "/第一章", "title": "第一章", "children": []},
        ]}
        node = find_node_by_path(index, "/第一章")
        assert node is not None
        assert node["title"] == "第一章"

    def test_find_nested(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": [
            {"path": "/第一章", "title": "第一章", "children": [
                {"path": "/第一章/1.1", "title": "1.1", "children": [
                    {"path": "/第一章/1.1/1.1.1", "title": "1.1.1", "children": []},
                ]},
            ]},
        ]}
        node = find_node_by_path(index, "/第一章/1.1/1.1.1")
        assert node is not None
        assert node["title"] == "1.1.1"

    def test_not_found(self):
        from src.reviewer.tender_indexer import find_node_by_path

        index = {"chapters": []}
        assert find_node_by_path(index, "/不存在") is None


class TestGetTextForClause:
    def test_single_batch(self):
        from src.reviewer.tender_indexer import get_text_for_clause
        from src.models import Paragraph

        paras = [Paragraph(index=i, text=f"段落{i}") for i in range(10)]
        index = {"chapters": [
            {"path": "/ch1", "title": "ch1", "start_para": 0, "end_para": 9,
             "is_leaf": True, "para_count": 10, "children": []},
        ]}
        batches = get_text_for_clause(0, ["/ch1"], index, paras)
        assert len(batches) == 1
        assert batches[0].batch_id == "/ch1#0"
        assert len(batches[0].paragraphs) == 10

    def test_split_large_leaf(self):
        """超大叶子节点按字符数拆分为多批次。"""
        from src.reviewer.tender_indexer import get_text_for_clause
        from src.models import Paragraph

        # 创建 1500 个段落（超过 LEAF_SPLIT_THRESHOLD=1200），每个 50 字符
        paras = [Paragraph(index=i, text="X" * 50) for i in range(1500)]
        index = {"chapters": [
            {"path": "/big", "title": "big", "start_para": 0, "end_para": 1499,
             "is_leaf": True, "para_count": 1500, "children": []},
        ]}
        batches = get_text_for_clause(0, ["/big"], index, paras)
        assert len(batches) > 1
        assert all(b.batch_id.startswith("/big#") for b in batches)


class TestMapReviewLocation:
    def test_global_index_mapping(self):
        from src.reviewer.tender_indexer import map_review_location, ClauseBatch
        from src.models import Paragraph

        paras = [Paragraph(index=100 + i, text=f"p{i}") for i in range(5)]
        batch = ClauseBatch(clause_index=0, path="/ch1", batch_id="/ch1#0", paragraphs=paras)

        result = map_review_location(batch, {"para_index": 2, "text_snippet": "p2"})
        assert result["global_para_index"] == 102  # 100 + 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_indexer.py::TestFindNodeByPath -v`
Expected: FAIL — `ImportError: cannot import name 'find_node_by_path'`

- [ ] **Step 3: 实现 tender_indexer.py 新增函数**

在 `src/reviewer/tender_indexer.py` 末尾追加（保留现有 `build_index_from_toc`、`get_chapter_text`）：

```python
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

LEAF_SPLIT_THRESHOLD = 1200
MAX_CHARS_PER_BATCH = 30000


@dataclass
class ClauseBatch:
    """一个条款在某个叶子节点上的段落批次。"""
    clause_index: int
    path: str
    batch_id: str
    paragraphs: list  # list[Paragraph]


def find_node_by_path(tender_index: dict, path: str) -> dict | None:
    """根据 path 精确查找节点（DFS）。"""
    def dfs(nodes):
        for node in nodes:
            if node.get("path") == path:
                return node
            found = dfs(node.get("children", []))
            if found:
                return found
        return None
    return dfs(tender_index.get("chapters", []))


def get_text_for_clause(
    clause_index: int,
    paths: list[str],
    tender_index: dict,
    paragraphs: list,
) -> list[ClauseBatch]:
    """为单个条款获取精确段落批次。

    每个 path 单独提取段落；叶子节点段落数 > 1200 时按字符数拆分。
    """
    batches: list[ClauseBatch] = []

    for path in paths:
        node = find_node_by_path(tender_index, path)
        if not node:
            logger.warning("Path not found: %s", path)
            continue

        node_paras = _get_paragraphs_in_node(node, paragraphs)
        if not node_paras:
            continue

        if len(node_paras) > LEAF_SPLIT_THRESHOLD:
            sub_batches = _split_by_char_count(node_paras, MAX_CHARS_PER_BATCH)
            for i, sub_paras in enumerate(sub_batches):
                batches.append(ClauseBatch(
                    clause_index=clause_index,
                    path=path,
                    batch_id=f"{path}#{i}",
                    paragraphs=sub_paras,
                ))
        else:
            batches.append(ClauseBatch(
                clause_index=clause_index,
                path=path,
                batch_id=f"{path}#0",
                paragraphs=node_paras,
            ))

    return batches


def _get_paragraphs_in_node(node: dict, paragraphs: list) -> list:
    """获取节点范围内的所有段落（排除子节点的标题段落）。"""
    start = node["start_para"]
    end = node["end_para"]

    # 收集所有后代节点的 start_para（即标题段落），排除自身
    child_starts: set[int] = set()
    def _collect_child_starts(children: list[dict]) -> None:
        for ch in children:
            child_starts.add(ch["start_para"])
            _collect_child_starts(ch.get("children", []))
    _collect_child_starts(node.get("children", []))

    return [p for p in paragraphs if start <= p.index <= end and p.index not in child_starts]


def _split_by_char_count(paragraphs: list, max_chars: int) -> list[list]:
    """按字符数拆分段落列表。"""
    batches: list[list] = []
    current_batch: list = []
    current_chars = 0

    for para in paragraphs:
        para_chars = len(para.text)
        if current_chars + para_chars > max_chars and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(para)
        current_chars += para_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def paragraphs_to_text(paragraphs: list) -> str:
    """将段落列表拼接为审查用文本。"""
    return "\n".join(f"[{p.index}] {p.text}" for p in paragraphs)


def map_review_location(batch: ClauseBatch, result_location: dict) -> dict:
    """将批次内段落索引映射回全局段落索引。"""
    local_idx = result_location.get("para_index", 0)
    global_idx = local_idx + batch.paragraphs[0].index if batch.paragraphs else local_idx
    return {
        "batch_id": batch.batch_id,
        "path": batch.path,
        "global_para_index": global_idx,
        "text_snippet": result_location.get("text_snippet", ""),
    }


def map_batch_indices_to_global(result: dict, batch: ClauseBatch) -> dict:
    """将 llm_review_clause 返回结果中的批次内索引映射为全局索引。"""
    mapped_locations = []
    for loc in result.get("tender_locations", []):
        for pi in loc.get("para_indices", []):
            mapped = map_review_location(batch, {"para_index": pi, "text_snippet": loc.get("text_snippet", "")})
            mapped_locations.append(mapped)

    result["tender_locations"] = [{
        "batch_id": batch.batch_id,
        "path": batch.path,
        "global_para_indices": [loc["global_para_index"] for loc in mapped_locations],
        "text_snippet": mapped_locations[0]["text_snippet"] if mapped_locations else "",
    }] if mapped_locations else []

    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_indexer.py -v`
Expected: 所有新旧测试 PASS

- [ ] **Step 5: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/tender_indexer.py src/reviewer/tests/test_tender_indexer.py
git commit -m "feat(reviewer): add precise paragraph extraction and batch splitting to tender_indexer"
```

---

### Task 5: review_task.py — 逐条独立审查循环

**Files:**
- Modify: `server/app/tasks/review_task.py:27-29` (imports), `135-248` (审查循环)

- [ ] **Step 1: 修改 imports**

在 `server/app/tasks/review_task.py` 修改导入：

```python
# 替换:
# from src.reviewer.clause_mapper import llm_map_clauses_to_chapters
# from src.reviewer.tender_indexer import get_chapter_text
# from src.reviewer.reviewer import llm_review_clause, llm_review_batch, compute_summary

# 改为:
from src.reviewer.clause_mapper import llm_map_clauses_to_leaf_nodes
from src.reviewer.tender_indexer import (
    get_text_for_clause, paragraphs_to_text, map_batch_indices_to_global,
)
from src.reviewer.reviewer import llm_review_clause, compute_summary
```

- [ ] **Step 2: 替换 Step 4 条款映射**

将 `review_task.py` 中的 Step 4（约行 135-137）替换为：

```python
            # Step 4: Clause mapping to leaf nodes (12-15%)
            self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 12, "detail": "条款映射"})
            clause_mapping = llm_map_clauses_to_leaf_nodes(clauses, tender_index, api_settings)
```

- [ ] **Step 3: 替换 Step 5-7 为统一逐条审查循环**

将 `review_task.py` 中的 Step 5（P0 审查，约行 139-170）、Step 6（P1 批量审查，约行 172-209）、Step 7（P2 批量审查，约行 211-248）全部替换为：

```python
            # Step 5-7: 逐条独立审查 (15-95%)
            _SEVERITY_ORDER = {"fail": 0, "error": 1, "warning": 2, "pass": 3}

            def _is_worse(a: dict, b: dict) -> bool:
                return _SEVERITY_ORDER.get(a.get("result", ""), 99) < _SEVERITY_ORDER.get(b.get("result", ""), 99)

            def _no_match_item(clause: dict) -> dict:
                return {
                    "source_module": clause["source_module"],
                    "clause_index": clause["clause_index"],
                    "clause_text": clause["clause_text"],
                    "result": "warning",
                    "confidence": 0,
                    "reason": "条款未能映射到投标文件任何章节节点",
                    "severity": clause["severity"],
                    "tender_locations": [],
                }

            review_items = []
            item_id = 0
            all_clauses = sorted(clauses, key=lambda c: {"critical": 0, "major": 1, "minor": 2}.get(c["severity"], 9))
            clause_progress_start = 15
            clause_progress_end = 95

            for i, clause in enumerate(all_clauses):
                progress = clause_progress_start + int(
                    (clause_progress_end - clause_progress_start) * i / max(len(all_clauses), 1)
                )
                step_key = (
                    "p0_review" if clause["severity"] == "critical" else
                    "p1_review" if clause["severity"] == "major" else "p2_review"
                )
                review.progress = progress
                review.current_step = f"审查 [{i+1}/{len(all_clauses)}] {clause['clause_text'][:20]}..."
                db.commit()
                self.update_state(state="PROGRESS", meta={
                    "step": step_key, "progress": progress,
                    "detail": review.current_step,
                })

                paths = clause_mapping.get(clause["clause_index"], [])
                if not paths:
                    item = _no_match_item(clause)
                    item["id"] = item_id
                    review_items.append(item)
                    item_id += 1
                    continue

                batches = get_text_for_clause(
                    clause["clause_index"], paths, tender_index, paragraphs
                )

                if not batches:
                    item = _no_match_item(clause)
                    item["id"] = item_id
                    review_items.append(item)
                    item_id += 1
                    continue

                if len(batches) == 1:
                    batch = batches[0]
                    tender_text = paragraphs_to_text(batch.paragraphs)
                    try:
                        result = llm_review_clause(clause, tender_text, project_context, api_settings)
                        result = map_batch_indices_to_global(result, batch)
                        result["id"] = item_id
                        review_items.append(result)
                    except Exception as e:
                        logger.error("Clause review failed for %d: %s", clause["clause_index"], e)
                        review_items.append({
                            "id": item_id, "source_module": clause["source_module"],
                            "clause_index": clause["clause_index"], "clause_text": clause["clause_text"],
                            "result": "error", "confidence": 0, "reason": f"LLM 调用失败: {e}",
                            "severity": clause["severity"], "tender_locations": [],
                        })
                else:
                    # 多批次：各批次独立审查，取最严格结果但合并所有位置信息
                    best_result = None
                    all_locations = []
                    for batch in batches:
                        tender_text = paragraphs_to_text(batch.paragraphs)
                        try:
                            r = llm_review_clause(clause, tender_text, project_context, api_settings)
                            r = map_batch_indices_to_global(r, batch)
                            all_locations.extend(r.get("tender_locations", []))
                            if best_result is None or _is_worse(r, best_result):
                                best_result = r
                        except Exception as e:
                            logger.error("Clause batch review failed for %s: %s", batch.batch_id, e)
                    if best_result is None:
                        best_result = {
                            "source_module": clause["source_module"],
                            "clause_index": clause["clause_index"],
                            "clause_text": clause["clause_text"],
                            "result": "error", "confidence": 0,
                            "reason": "所有批次 LLM 调用失败",
                            "severity": clause["severity"], "tender_locations": [],
                        }
                    else:
                        # 合并所有批次的位置信息
                        best_result["tender_locations"] = all_locations
                    best_result["id"] = item_id
                    review_items.append(best_result)

                item_id += 1
```

- [ ] **Step 4: 验证 review_task.py 语法正确**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -c "import ast; ast.parse(open('server/app/tasks/review_task.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add server/app/tasks/review_task.py
git commit -m "feat(review-task): replace batch review with per-clause independent review loop"
```

---

### Task 6: reviewer.py — 标注废弃

**Files:**
- Modify: `src/reviewer/reviewer.py:59`

- [ ] **Step 1: 标注 llm_review_batch 为废弃**

在 `src/reviewer/reviewer.py` 的 `llm_review_batch` 函数（行 59）docstring 开头添加：

```python
def llm_review_batch(
    clauses: list[dict],
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> list[dict]:
    """[DEPRECATED] Use per-clause llm_review_clause instead.

    Review multiple clauses in a single LLM call.
    ...
    """
```

- [ ] **Step 2: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/reviewer.py
git commit -m "refactor(reviewer): deprecate llm_review_batch in favor of per-clause review"
```

---

## Chunk 4: 批注层 — 读取新格式 + 合并同段落批注

### Task 7: docx_annotator.py — 兼容新 tender_locations 格式

**Files:**
- Modify: `src/reviewer/docx_annotator.py:180-218`
- Modify: `src/reviewer/tests/test_docx_annotator.py`

- [ ] **Step 1: 写失败测试 — 新格式 para_review_map 构建**

在 `src/reviewer/tests/test_docx_annotator.py` 末尾追加：

```python
class TestBuildParaReviewMap:
    def test_new_format_global_para_indices(self):
        """新格式 global_para_indices 正确映射。"""
        from src.reviewer.docx_annotator import _build_para_review_map

        items = [{
            "result": "fail", "severity": "critical",
            "tender_locations": [{
                "batch_id": "/ch1#0",
                "path": "/ch1",
                "global_para_indices": [5, 6, 7],
                "text_snippet": "test",
            }],
        }]
        para_map = _build_para_review_map(items)
        assert 5 in para_map
        assert 6 in para_map
        assert 7 in para_map
        assert len(para_map[5]) == 1

    def test_old_format_para_indices(self):
        """旧格式 para_indices 仍然兼容。"""
        from src.reviewer.docx_annotator import _build_para_review_map

        items = [{
            "result": "fail", "severity": "critical",
            "tender_locations": [{
                "chapter": "第一章",
                "para_indices": [10, 11],
                "text_snippet": "test",
            }],
        }]
        para_map = _build_para_review_map(items)
        assert 10 in para_map
        assert 11 in para_map

    def test_dedup_same_para(self):
        """同一段落同一 item 只出现一次。"""
        from src.reviewer.docx_annotator import _build_para_review_map

        item = {
            "result": "fail", "severity": "critical",
            "tender_locations": [
                {"global_para_indices": [5], "text_snippet": "a"},
                {"global_para_indices": [5], "text_snippet": "b"},
            ],
        }
        para_map = _build_para_review_map([item])
        # 同一 item 在同一 para 只记录一次
        assert len(para_map[5]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_docx_annotator.py::TestBuildParaReviewMap -v`
Expected: FAIL — `ImportError: cannot import name '_build_para_review_map'`

- [ ] **Step 3: 重构 docx_annotator.py — 提取 _build_para_review_map**

在 `src/reviewer/docx_annotator.py` 的 `generate_review_docx` 函数之前插入：

```python
def _build_para_review_map(review_items: list[dict]) -> dict[int, list[dict]]:
    """建立全局段落索引 → 相关 review_items 的映射。

    兼容新旧两种格式：
    - 新格式: tender_locations[].global_para_indices
    - 旧格式: tender_locations[].para_indices
    """
    para_map: dict[int, list[dict]] = {}
    for item in review_items:
        if item["result"] not in ("fail", "warning"):
            continue
        seen_paras: set[int] = set()  # 同一 item 同一 para 只记录一次
        for loc in item.get("tender_locations", []):
            # 新格式
            indices = loc.get("global_para_indices", [])
            # 旧格式 fallback
            if not indices:
                indices = loc.get("para_indices", [])
            for pi in indices:
                if pi not in seen_paras:
                    seen_paras.add(pi)
                    para_map.setdefault(pi, []).append(item)
    return para_map
```

- [ ] **Step 4: 修改 generate_review_docx 使用 _build_para_review_map**

将 `generate_review_docx` 中的内联 `para_review_map` 构建逻辑（约行 180-186）替换为：

```python
    # Build para_index → review_items mapping
    para_review_map = _build_para_review_map(review_items)
```

删除原来的内联构建代码：
```python
    # 删除以下行:
    para_review_map: dict[int, list[dict]] = {}
    for item in review_items:
        if item["result"] in ("fail", "warning"):
            for loc in item.get("tender_locations", []):
                for pi in loc.get("para_indices", []):
                    para_review_map.setdefault(pi, []).append(item)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_docx_annotator.py -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
git add src/reviewer/docx_annotator.py src/reviewer/tests/test_docx_annotator.py
git commit -m "feat(annotator): support global_para_indices format with dedup per paragraph"
```

---

## 验收检查清单

完成所有 Task 后，执行以下验证：

- [ ] **运行全部测试**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
python -m pytest src/reviewer/tests/ -v
```
Expected: 所有测试 PASS

- [ ] **验证导入链完整**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
python -c "
from src.reviewer.chapter_tree import build_chapter_tree, collect_all_paths
from src.reviewer.tender_rule_splitter import build_tender_index
from src.reviewer.clause_mapper import llm_map_clauses_to_leaf_nodes
from src.reviewer.tender_indexer import find_node_by_path, get_text_for_clause, ClauseBatch, map_batch_indices_to_global, paragraphs_to_text
from src.reviewer.docx_annotator import _build_para_review_map
print('All imports OK')
"
```

- [ ] **确认 review_task.py 不再引用旧函数**

```bash
cd /d/BaiduSyncdisk/标书项目/招标文件解读
grep -n "llm_map_clauses_to_chapters\|llm_review_batch\|get_chapter_text" server/app/tasks/review_task.py
```
Expected: 无输出（旧引用已全部移除）
