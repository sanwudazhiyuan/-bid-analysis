# 投标文件格式智能构建 设计文档

## 背景与问题

当前 `bid_format` 模块使用固定的 prompt 模板，从招标文件段落中提取投标文件格式。这种方式存在问题：

1. 当招标文件**没有提供格式样例**时，LLM 无法凭空构建合理的投标文件格式
2. 当招标文件**提供了格式样例**时，应直接照搬原文格式，而非用固定模板提取

## 目标

将 `extract_bid_format` 改为两层策略：

1. **有格式样例**：LLM 判断招标文件是否包含投标文件格式样例，有则直接照格式构建输出
2. **无格式样例**：LLM 接收 module_a~g 的提取结果作为上下文，按"身份证明→报价→商务技术部分"的默认结构构建

## 设计

### 流程

```
筛选格式相关段落
    ↓
第一次 LLM 调用 (bid_format.txt)
    输入：筛选的段落
    指令：判断有无格式样例，有则直接构建
    ├→ 有格式样例 → 返回完整格式 JSON → 结束
    └→ 无格式样例 → 返回 {"has_template": false}
         ↓
第二次 LLM 调用 (bid_format_fallback.txt)
    输入：module_a~g 精简后的提取结果
    指令：按默认结构（身份证明→报价→商务技术）构建
    → 返回完整格式 JSON → 结束
```

### 涉及的修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `config/prompts/bid_format.txt` | 重写 | 第一次调用 prompt：判断有无格式样例，有则构建，无则返回 `{"has_template": false}` |
| `config/prompts/bid_format_fallback.txt` | 新建 | 第二次调用 prompt：基于模块结果按默认结构构建 |
| `src/extractor/bid_format.py` | 修改 | 增加 `modules_context` 参数，实现两次调用逻辑，增加 `_summarize_modules()` 辅助函数 |
| `src/extractor/extractor.py` | 修改 | `extract_all` 在调用 `bid_format` 时传入已有模块结果 |

### Prompt 设计

#### 第一次调用 (`bid_format.txt`)

输入：格式相关段落文本。

指令要点：
- 判断招标文件中是否包含投标文件格式样例（如投标函模板、报价表格式、开标一览表模板等）
- 如果包含，按原文格式构建完整的投标文件格式 JSON 输出
- 如果不包含，仅返回 `{"has_template": false}`

输出格式（有样例时）：
```json
{
  "title": "投标文件格式",
  "sections": [
    {
      "id": "BF1",
      "title": "投标函",
      "type": "text",
      "content": "致：[采购人名称]\n..."
    }
  ]
}
```

输出格式（无样例时）：
```json
{"has_template": false}
```

#### 第二次调用 (`bid_format_fallback.txt`)

输入：module_a~g 精简后的提取结果 JSON。

指令要点：
- 根据各模块提取的招标要求，构建投标文件格式
- 总体按照：身份证明→报价→商务技术部分的顺序组织
- 身份证明部分包括：法人身份证明、营业执照、授权委托书等（根据模块中的资质要求）
- 报价部分包括：投标报价表、分项报价表等（根据模块中的报价结构）
- 商务技术部分包括：技术方案、服务承诺、业绩证明等（根据模块中的技术和商务要求）

输出格式：与第一次调用相同的 JSON 结构。

### 数据流变化

#### `extractor.py`

```python
def extract_all(...):
    modules = {}
    for key, (module_path, func_name) in _MODULE_REGISTRY.items():
        if key == "bid_format":
            result = func(
                tagged_paragraphs, settings,
                embeddings_map=embeddings_map,
                module_embedding=module_emb,
                modules_context=modules,
            )
        else:
            result = func(...)
        modules[key] = result
```

需确保 `_MODULE_REGISTRY` 中 `bid_format` 排在 module_a~g 之后（当前已是如此）。

#### `bid_format.py`

```python
def extract_bid_format(
    tagged_paragraphs, settings,
    embeddings_map=None, module_embedding=None,
    modules_context=None,  # 新增
):
    filtered = _filter_paragraphs(...)

    # 第一次 LLM：判断 + 构建
    result = _first_pass(filtered, settings)
    if result and result.get("has_template") is not False:
        return result

    # 第二次 LLM：基于模块结果构建
    return _fallback_pass(modules_context, settings)
```

### modules_context 精简策略

module_a~g 的完整 JSON 可能很大。`_summarize_modules()` 辅助函数负责精简：

- 遍历每个模块结果
- 只保留 `title`、每个 section 的 `title` 和关键字段（如 items 列表的名称）
- 跳过 `None` 的模块结果
- 控制总输出在合理范围内

```python
def _summarize_modules(modules_context: dict) -> str:
    """将 module_a~g 结果精简为 LLM 可用的上下文文本。"""
    summaries = []
    for key, result in modules_context.items():
        if result is None or key in ("bid_format", "checklist"):
            continue
        # 提取模块标题和各 section 标题
        title = result.get("title", key)
        sections = result.get("sections", [])
        section_titles = [s.get("title", "") for s in sections if isinstance(s, dict)]
        summaries.append(f"## {title}\n包含: {', '.join(section_titles)}")
    return "\n\n".join(summaries)
```

## 不变部分

- 段落筛选逻辑 `_filter_paragraphs` 不变
- 输出 JSON 格式不变（`{title, sections: [{id, title, type, ...}]}`）
- checklist 模块不受影响
- 下游消费方（table_builder、Web 前端）不受影响
