# 标书审查：细粒度索引 + 精确映射 + 智能拆分

**日期:** 2026-04-01
**状态:** 设计中

## 背景

当前审查系统存在两个根本性问题，均源于索引和映射粒度不够精细：

1. **批注标记在毫不相关内容上** — 当前映射粒度粗，LLM 把整个大章节（可能几百页）所有段落丢给 LLM，导致 LLM 只能靠关键词匹配找原文，找错了段落位置。
2. **多个批注堆叠在同一图片/段落** — 同一节点下多条条款引用相同的 `para_index`，批注添加逻辑没有去重。

根本解法：
- **索引支持任意深度**（不限 3 层），每个节点有唯一 path 和精确段落范围
- **条款映射到叶子节点 path**，每条条款只拿它相关的段落
- **叶子超 30 页时智能拆分**，每条条款独立审查
- **para_index 精确到段落级别**，避免批注堆叠

## 设计

### 一、索引层：任意深度章节树

#### 1.1 数据结构

`tender_index` 结构从两层树改为任意深度嵌套：

```python
{
    "toc_source": "document_toc",
    "confidence": 0.85,
    "chapters": [
        {
            "title": "第一章 投标函",
            "path": "/第一章 投标函",
            "level": 1,
            "start_para": 0,
            "end_para": 25,
            "para_count": 26,           # 该节点下段落总数
            "is_leaf": False,           # 有 children，不是叶子
            "children": [
                {
                    "title": "1.1 投标函内容",
                    "path": "/第一章 投标函/1.1 投标函内容",
                    "level": 2,
                    "start_para": 1,
                    "end_para": 10,
                    "para_count": 10,
                    "is_leaf": False,
                    "children": [
                        {
                            "title": "1.1.1 基本信息",
                            "path": "/第一章 投标函/1.1 投标函内容/1.1.1 基本信息",
                            "level": 3,
                            "start_para": 2,
                            "end_para": 8,
                            "para_count": 7,
                            "is_leaf": False,
                            "children": [
                                {
                                    "title": "1.1.1.1 公司名称",
                                    "path": "/第一章 投标函/1.1 投标函内容/1.1.1 基本信息/1.1.1.1 公司名称",
                                    "level": 4,
                                    "start_para": 3,
                                    "end_para": 4,
                                    "para_count": 2,
                                    "is_leaf": True,   # 没有 children，是叶子
                                    "children": [],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ],
    "all_paths": ["/第一章 投标函", "/第一章 投标函/1.1 投标函内容", ...],  # 扁平 path 列表，供 clause_mapper 使用
}
```

关键字段：
- `path`: 唯一标识，从根到当前节点的完整路径，保留标题原文
- `is_leaf`: `True` 表示没有 children，是最细粒度节点
- `para_count`: 该节点下段落总数（不含 children 标题段落本身）
- `all_paths`: 扁平 path 列表，在 `_sections_to_chapters` 末尾自动生成（递归收集所有 path）

#### 1.2 编号正则扩展（支持 5+ 级）

当前只检测到 level 3（一二三 / （一）（二））。扩展正则：

```python
# Level 1: 第X章/节/篇/部分
_RE_L1 = re.compile(r"^第[一二三四五六七八九十百零]+[章节篇部]")
# Level 2: 一、二、三、
_RE_L2 = re.compile(r"^[一二三四五六七八九十]+[、\.\．]")
# Level 3: （一）（二）
_RE_L3 = re.compile(r"^（[一二三四五六七八九十]+）|^\([一二三四五六七八九十]+\)")
# Level 4+: 纯数字层级 1.1 / 1.1.1 / 1.1.1.1 / 1.1.1.1.1
_RE_DOT = re.compile(r"^\d+(?:\.\d+)+")
```

匹配优先级：L1 → L2 → L3 → Ln（数字层级），同一行只取最高优先级。

#### 1.3 章节树构建（核心算法）

实现放在 `src/reviewer/chapter_tree.py`。`tender_rule_splitter.py` 的 `_sections_to_chapters` 函数替换为调用 `chapter_tree.build_chapter_tree`：

```python
# src/reviewer/chapter_tree.py

from dataclasses import dataclass


@dataclass
class _Section:
    title: str
    start: int
    level: int
    end: int = 0
    para_count: int = 0
    children: list = None

    def __post_init__(self):
        if self.children is None:
            self.children = []


def build_chapter_tree(
    sections: list[dict], total_paragraphs: int
) -> list[dict]:
    """从扁平 sections 构建任意深度章节树。

    Args:
        sections: [{title, start, level}] 已按 start 升序排序
        total_paragraphs: 文档总段落数

    Returns:
        嵌套章节树列表，同时设置 is_leaf, para_count, needs_split
    """
    if not sections:
        return []

    nodes = [_Section(title=s["title"], start=s["start"], level=s["level"]) for s in sections]

    # Step 1: 计算 end_para（找下一个更大 start 的节点）
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

    # Step 3: 递归计算 para_count、is_leaf、needs_split
    def finalize(n: _Section) -> dict:
        if not n.children:
            # 叶子：para_count = end - start + 1
            n.para_count = n.end - n.start + 1
            is_leaf = True
            needs_split = n.para_count > LEAF_SPLIT_THRESHOLD
        else:
            # 非叶子：合并所有子节点的 para_count
            total = 0
            for child in n.children:
                finalize(child)
                total += child.para_count
            n.para_count = total
            is_leaf = False
            needs_split = False

        return {
            "title": n.title,
            "level": n.level,
            "start_para": n.start,
            "end_para": n.end,
            "para_count": n.para_count,
            "is_leaf": is_leaf,
            "needs_split": needs_split,
            "children": [finalize(c) for c in n.children],
        }

    # 构建 path（在 finalize 前一次性计算）
    def assign_paths(nodes: list[_Section], parent_path: str = ""):
        for n in nodes:
            path = f"{parent_path}/{n.title}"
            n._path = path
            assign_paths(n.children, path)

    assign_paths(root)

    # 重写 finalize 加入 path
    def finalize2(n: _Section) -> dict:
        if not n.children:
            n.para_count = n.end - n.start + 1
            is_leaf = True
        else:
            total = 0
            for child in n.children:
                finalize2(child)
                total += child.para_count
            n.para_count = total
            is_leaf = False
        return {
            "title": n.title,
            "path": n._path,
            "level": n.level,
            "start_para": n.start,
            "end_para": n.end,
            "para_count": n.para_count,
            "is_leaf": is_leaf,
            "needs_split": is_leaf and n.para_count > LEAF_SPLIT_THRESHOLD,
            "children": [finalize2(c) for c in n.children],
        }

    return [finalize2(n) for n in root]
```

`tender_rule_splitter.py` 中的 `_sections_to_chapters` 替换为：

```python
from src.reviewer.chapter_tree import build_chapter_tree

def _sections_to_chapters(sections: list[dict], total_paragraphs: int) -> list[dict]:
    """对外接口：调用 chapter_tree.build_chapter_tree"""
    return build_chapter_tree(sections, total_paragraphs)
```

#### 1.4 叶子节点拆分标记

阈值: **1200 段落 ≈ 30 页**（假设每页约 40 段落）

```python
LEAF_SPLIT_THRESHOLD = 1200  # 段落数

def _mark_split_nodes(node):
    """递归标记需要拆分的叶子节点"""
    if node["is_leaf"]:
        node["needs_split"] = node["para_count"] > LEAF_SPLIT_THRESHOLD
        return

    for child in node.get("children", []):
        _mark_split_nodes(child)

    # 父节点不是叶子，合并其下所有子节点的 para_count
    node["is_leaf"] = False
```

### 二、映射层：精确到叶子节点

#### 2.1 新映射 prompt

当前 `config/prompts/review_mapping.txt` 使用 `{clauses}` 和 `{chapters}` 占位符，返回 `relevant_chapters` 字符串数组。**替换为以下内容**：

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

#### 2.2 章节树文本格式

```text
/第一章 投标函 [段落数: 26]
  /第一章 投标函/1.1 投标函内容 [段落数: 10]
    /第一章 投标函/1.1 投标函内容/1.1.1 基本信息 [段落数: 7]
      /第一章 投标函/1.1 投标函内容/1.1.1 基本信息/1.1.1.1 公司名称 [段落数: 2, 叶子]
      /第一章 投标函/1.1 投标函内容/1.1.1 基本信息/1.1.1.2 联系方式 [段落数: 3, 叶子]
    /第一章 投标函/1.1 投标函内容/1.1.2 承诺书 [段落数: 5, 叶子]
  /第一章 投标函/1.2 授权委托书 [段落数: 12]
/第二章 技术方案 [段落数: 150]
  ...
```

#### 2.3 clause_mapper.py 改动

```python
def llm_map_clauses_to_leaf_nodes(
    clauses: list[dict],
    tender_index: dict,
    api_settings: dict | None = None,
) -> dict[int, list[str]]:
    """Map clauses to leaf node paths. Returns {clause_index: [path, ...]}"""

    # 构建章节树文本
    chapter_tree_text = _build_chapter_tree_text(tender_index)

    # 构建条款文本
    clauses_text = "\n".join(
        f"[{c['clause_index']}] [{c['severity']}] {c['clause_text']}"
        for c in clauses
    )

    # 调用 LLM
    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{clauses}", clauses_text)
        .replace("{chapter_tree}", chapter_tree_text)
    )

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    # 解析返回
    mapping: dict[int, list[str]] = {}
    if isinstance(result, list):
        for item in result:
            idx = item.get("clause_index")
            paths = item.get("relevant_paths", [])
            if idx is not None:
                mapping[idx] = paths

    return mapping
```

### 三、检索层：精确段落提取 + 智能拆分

#### 3.1 节点 path 查询

```python
def find_node_by_path(tender_index: dict, path: str) -> dict | None:
    """根据 path 精确查找节点（DFS）"""
    def dfs(nodes):
        for node in nodes:
            if node["path"] == path:
                return node
            found = dfs(node.get("children", []))
            if found:
                return found
        return None
    return dfs(tender_index.get("chapters", []))
```

#### 3.2 叶子节点段落提取 + 拆分

```python
LEAF_SPLIT_THRESHOLD = 1200  # 段落数
MAX_CHARS_PER_BATCH = 30000  # 每次传给 LLM 的最大字符数

@dataclass
class ClauseBatch:
    clause_index: int
    path: str                          # 原始叶子节点 path
    batch_id: str                      # e.g. "/第一章 投标函#0"
    paragraphs: list[Paragraph]        # 该批次相关段落


def get_text_for_clause(
    clause_index: int,
    paths: list[str],
    tender_index: dict,
    paragraphs: list[Paragraph],
) -> list[ClauseBatch]:
    """为单个条款获取精确段落批次。

    规则:
    - 每个 path 单独提取段落
    - 叶子节点段落数 <= 1200: 整块返回，batch_id = "path#0"
    - 叶子节点段落数 > 1200: 按段落数均分，batch_id = "path#0", "path#1", ...
    - 每次传给 LLM 不超过 MAX_CHARS_PER_BATCH 字符
    """
    batches: list[ClauseBatch] = []

    for path in paths:
        node = find_node_by_path(tender_index, path)
        if not node:
            logger.warning(f"Path not found: {path}")
            continue

        node_paras = _get_paragraphs_in_node(node, paragraphs)
        if not node_paras:
            continue

        # 如果段落数过多，按字符数拆分
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


def _get_paragraphs_in_node(node: dict, paragraphs: list[Paragraph]) -> list[Paragraph]:
    """获取节点范围内的所有段落（不含子节点的标题段落）"""
    start = node["start_para"]
    end = node["end_para"]

    # 排除子节点的标题段落（它们的 index 在 children 的 start_para 上）
    child_starts = {ch["start_para"] for ch in _iter_leaves(node)}

    result = []
    for p in paragraphs:
        if start <= p.index <= end and p.index not in child_starts:
            result.append(p)

    return result


def _iter_leaves(node: dict):
    """递归遍历所有叶子节点"""
    if node.get("is_leaf"):
        yield node
    for child in node.get("children", []):
        yield from _iter_leaves(child)


def _split_by_char_count(paragraphs: list[Paragraph], max_chars: int) -> list[list[Paragraph]]:
    """按字符数均分段落列表"""
    batches: list[list[Paragraph]] = []
    current_batch: list[Paragraph] = []
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
```

#### 3.3 精确段落定位（避免批注堆叠）

每个 `ClauseBatch` 包含 `paragraphs: list[Paragraph]`，review 时 LLM 返回该批次内的 `para_index`（相对于批次，不是全局）。需要映射回全局段落索引：

```python
def map_review_location(
    batch: ClauseBatch,
    result_location: dict,  # LLM 返回的 {para_index, text_snippet}
) -> dict:
    """将批次内段落索引映射回全局段落索引。"""
    return {
        "batch_id": batch.batch_id,
        "path": batch.path,
        "global_para_index": result_location["para_index"] + batch.paragraphs[0].index,
        "text_snippet": result_location["text_snippet"],
    }
```

`_paragraphs_to_text` 辅助函数：

```python
def _paragraphs_to_text(paragraphs: list[Paragraph]) -> str:
    """将段落列表拼接为审查用文本。"""
    return "\n".join(f"[{p.index}] {p.text}" for p in paragraphs)
```

`_map_batch_indices_to_global` 辅助函数（调用 `map_review_location`）：

```python
def _map_batch_indices_to_global(result: dict, batch: ClauseBatch) -> dict:
    """将 llm_review_clause 返回结果中的批次内索引映射为全局索引。"""
    mapped_locations = []
    for loc in result.get("locations", []):
        if loc.get("para_index") is not None:
            mapped = map_review_location(batch, loc)
            mapped_locations.append(mapped)

    result["tender_locations"] = [{
        "batch_id": batch.batch_id,
        "path": batch.path,
        "global_para_indices": [loc["global_para_index"] for loc in mapped_locations],
        "text_snippet": mapped_locations[0]["text_snippet"] if mapped_locations else "",
    }]
    # 删除旧的 locations（批次内索引）
    if "locations" in result:
        del result["locations"]
    return result
```

### 四、审查层：独立审查 + 精确位置

#### 4.1 review_task.py 改造

当前流程：
```
条款列表 → 批量获取整章文本 → 批量审查
```

改造后：
```
条款列表 → clause_mapper（映射到叶子 path）→ 为每条条款获取精确段落批次 → 独立审查每条 → 汇总
```

```python
# Step 4: Clause mapping（改为叶子节点 path）
clause_mapping = llm_map_clauses_to_leaf_nodes(clauses, tender_index, api_settings)

# Step 5-N: 逐条审查（不再按 severity 分批，每条独立审查）
all_review_items = []
_SEVERITY_ORDER = {"fail": 0, "error": 1, "warning": 2, "pass": 3}

for i, clause in enumerate(all_clauses):
    paths = clause_mapping.get(clause["clause_index"], [])
    progress = clause_progress_start + int(
        (clause_progress_end - clause_progress_start) * i / max(len(all_clauses), 1)
    )
    self.update_state(state="PROGRESS", meta={
        "step": "p0_review" if clause["severity"] == "critical" else
                "p1_review" if clause["severity"] == "major" else "p2_review",
        "progress": progress,
        "detail": f"审查 [{i+1}/{len(all_clauses)}] {clause['clause_text'][:20]}...",
    })

    if not paths:
        all_review_items.append(_no_match_item(clause))
        continue

    batches = get_text_for_clause(
        clause["clause_index"], paths, tender_index, paragraphs
    )

    if len(batches) == 1:
        batch = batches[0]
        tender_text = _paragraphs_to_text(batch.paragraphs)
        try:
            result = llm_review_clause(clause, tender_text, project_context, api_settings)
            result = _map_batch_indices_to_global(result, batch)
            all_review_items.append(result)
        except Exception as e:
            logger.error("Clause review failed for %d: %s", clause["clause_index"], e)
            all_review_items.append(_error_item(clause))
    else:
        # 多个批次（如叶子节点被拆分），各批次独立审查后取最严格结果
        best_result = None
        for batch in batches:
            tender_text = _paragraphs_to_text(batch.paragraphs)
            try:
                r = llm_review_clause(clause, tender_text, project_context, api_settings)
                r = _map_batch_indices_to_global(r, batch)
                if best_result is None or _is_worse(r, best_result):
                    best_result = r
            except Exception as e:
                logger.error("Clause batch review failed for %s: %s", batch.batch_id, e)

        if best_result is None:
            best_result = _error_item(clause)
        all_review_items.append(best_result)
```

辅助函数（放在 `review_task.py` 内部）：

```python
_SEVERITY_ORDER = {"fail": 0, "error": 1, "warning": 2, "pass": 3}


def _is_worse(a: dict, b: dict) -> bool:
    """比较两个审查结果，fail > error > warning > pass。"""
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
```

**`reviewer.py` 不需要改动接口** — `llm_review_clause` 和 `llm_review_batch` 保持原样。`review_task.py` 通过 `_map_batch_indices_to_global`（放在 `tender_indexer.py` 中）将旧格式转换为新格式的 `tender_locations`。

**`llm_review_batch` 处置** — 保留函数定义但不调用，标注 `@deprecated`。

#### 4.2 批注不堆叠逻辑 + 格式兼容

`docx_annotator.py` 的批注添加逻辑需要改进：**同一 global_para_index 同一个 result 只加一条批注**。

新 `tender_locations` 格式：
```python
{
    "batch_id": "/第一章/1.1#0",
    "path": "/第一章/1.1",
    "global_para_indices": [5, 6, 7],  # 列表，因为一个批次可能引用多个段落
    "text_snippet": "...",
}
```

注意：`para_indices` 列表在 `_map_batch_indices_to_global` 中被删除（转换为 `global_para_indices`），所以 annotator 只需读取新的格式。

```python
def _build_para_review_map(review_items: list[dict]) -> dict[int, list[dict]]:
    """建立全局段落索引 → 相关 review_items 的映射。"""
    para_map: dict[int, list[dict]] = {}
    for item in review_items:
        for loc in item.get("tender_locations", []):
            # 读取新格式: global_para_indices 列表
            for gpi in loc.get("global_para_indices", []):
                para_map.setdefault(gpi, []).append(item)
    return para_map


def _merge_review_comments(items: list[dict]) -> str:
    """合并同一段落上多个 review_item 的批注内容。"""
    lines = []
    for item in items:
        severity_tag = {"critical": "🔴废标", "major": "🟡资格审查", "minor": "🟢评分"}.get(
            item.get("severity", ""), ""
        )
        result = item.get("result", "")
        reason = item.get("reason", "")
        lines.append(f"{severity_tag} {result}: {reason[:100]}")
    return "\n".join(lines)
```

#### 4.3 图片批注精确化

当前问题：图片周围的 `near_para_index` 可能不准确，导致批注在错误位置。

改进：LLM 审查结果返回的 `global_para_index` 指向的图片段落本身，不需要依赖 `near_para_index`。

```
审查时传入的图片信息改为：
- 图片所属的段落 index（精确）
- 图片的 filename（用于标注）
- 如果某条款引用了包含 [图片: xxx] 的段落，LLM 可以明确指出
```

### 五、review_task.py 进度更新

拆分后进度更细，后端进度更新也要跟上：

```python
# 条款审查进度 = (已审查条款数 / 总条款数) * 分配百分比
clause_progress_start = 15  # P0 开始
clause_progress_end = 95    # 生成前结束

for i, clause in enumerate(all_clauses):
    progress = clause_progress_start + int(
        (clause_progress_end - clause_progress_start) * i / max(len(all_clauses), 1)
    )
    self.update_state(state="PROGRESS", meta={
        "step": "p0_review" if clause["severity"] == "critical" else
                "p1_review" if clause["severity"] == "major" else "p2_review",
        "progress": progress,
        "detail": f"审查 [{i+1}/{len(all_clauses)}] {clause['clause_text'][:20]}...",
    })
```

注意：进度按所有条款统一编号（P0+P1+P2 混合顺序），不按 severity 分段。这样进度条更平滑。

## 文件变更清单

### 新建
- `src/reviewer/chapter_tree.py` — 章节树构建核心算法（`_build_chapter_tree` + 辅助函数）。供 `tender_rule_splitter.py` 调用。
- `src/reviewer/tests/test_chapter_tree.py` — 树构建测试（边界情况：同级兄弟、首节点 start=0、多子节点 para_count）

### 修改
- `src/reviewer/tender_rule_splitter.py` — 扩展编号正则（支持 5+ 级）+ 调用 `chapter_tree._build_chapter_tree` 构建任意深度树 + 叶子拆分标记（`needs_split` 字段）。**保留现有 5 层策略逻辑**，树构建函数替换为 `chapter_tree` 中的新实现。
- `src/reviewer/tender_indexer.py` — 新增 `find_node_by_path`、`get_text_for_clause`、`_get_paragraphs_in_node`、`_iter_leaves`、`_split_by_char_count`、`_paragraphs_to_text`、`map_review_location`、`_map_batch_indices_to_global`、`_is_worse`、`_no_match_item`。
- `src/reviewer/clause_mapper.py` — 新增 `llm_map_clauses_to_leaf_nodes`（替换 `llm_map_clauses_to_chapters`）。保留原函数但标注废弃。
- `src/reviewer/reviewer.py` — **接口不变**。`llm_review_batch` 保留但标注 `@deprecated`（不再被调用）。
- `src/reviewer/docx_annotator.py` — `_build_para_review_map` 改为读取 `global_para_indices` 列表；`_merge_review_comments` 合并逻辑；每个 `global_para_index` 只添加一条批注。
- `server/app/tasks/review_task.py` — 改造审查循环（逐条独立审查）；新增辅助函数（`_no_match_item`、`_is_worse`）；进度更新粒度到条款级别。
- `config/prompts/review_mapping.txt` — 替换 prompt 模板为叶子节点映射版本。

## 验收标准

1. 批注标记在条款相关的精确段落下，不再出现在无关内容上
2. 同一段落只有一个合并后的批注，不再堆叠
3. 索引支持投标文件的 5+ 级目录结构（实际投标文件常见 4-5 级）
4. 叶子节点超 30 页时自动拆分，每条条款独立审查
5. 每条条款审查的文本不超过 30000 字符
