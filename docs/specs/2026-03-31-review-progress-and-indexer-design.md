# 标书审查：进度条优化 + 投标文件混合索引

**日期:** 2026-03-31
**状态:** 设计完成

## 背景

标书审查功能上线后发现两个问题：
1. 审查任务启动后没有像标书解读那样的进度条 UI
2. 投标文件的索引方式过于简单（仅 TOC 检测 + LLM 兜底），需要像标书解读一样使用混合解析策略

## 设计

### 一、进度条优化

#### 1.1 前端：复用 ProcessingStage + useSSE

**改造 `useSSE` composable：** 支持自定义 SSE URL，当前硬编码 `/api/tasks/${taskId}/progress`，改为接受 URL 参数。

**改造 `ProcessingStage` 组件：** 支持自定义步骤列表（当前硬编码 4 步），通过 prop 传入。

**BidReviewView 改造：**
- 移除自制的 `EventSource` 逻辑，改用 `useSSE` composable
- processing 阶段使用 `ProcessingStage` 组件，传入 review 专用 6 步骤

**review SSE 端点改造：** 当前 `/api/reviews/{id}/progress` 使用 query string 传 token，改为和 tasks 端点一致的 `Authorization: Bearer` header 方式（fetch API）。

#### 1.2 审查步骤拆分

当前 3 步（索引 → 审查 → 生成）→ 拆为 6 步：

| 步骤 key | 显示名称 | 进度范围 |
|----------|---------|---------|
| `indexing` | 索引 | 0-10% |
| `extracting` | 条款提取 | 10-15% |
| `p0_review` | 废标审查 | 15-60% |
| `p1_review` | 资格审查 | 60-85% |
| `p2_review` | 评分审查 | 85-95% |
| `generating` | 生成报告 | 95-100% |

后端 `review_task.py` 的 `self.update_state()` 调整 step 字段以匹配上述 key。每个 P0 条款、每批 P1/P2 发送细粒度进度（当前已实现，只需对齐 step key）。

### 二、投标文件混合索引

#### 2.1 新建 `src/reviewer/tender_rule_splitter.py`

统一入口函数 `build_tender_index(paragraphs) -> dict`，内部按优先级执行 5 层策略：

**策略 1 — 目录识别匹配（最高优先级）**
- 扫描前 80 段落
- 子策略 A：TOC style 检测（style 名含 "toc"/"目录"）
- 子策略 B："目录"标题后的连续条目模式匹配
- 匹配到的 TOC 条目用 `difflib.SequenceMatcher` 模糊匹配定位到正文段落
- 结果 >= 3 个条目且覆盖率合理 → 直接采用

**策略 2 — Style ID 层级分析**
- 统计文档中所有 style 的出现频率
- 过滤候选标题 style：出现次数 < 段落总数 20% 且对应段落文本长度 < 80 字符
- 按出现频率从少到多排序，推断层级（最少的 → level 1，次少的 → level 2，以此类推）
- 排除明显非标题的 style（如 Normal、Body Text 等通用 style）

**策略 3 — 投标文件关键词匹配**
- 投标文件专用关键词表：
  - 顶层（level 1）：投标函、开标一览表、法人授权委托书、报价表/唱标表、资格证明文件、技术方案/技术部分、商务条款/商务部分、偏离表、项目业绩、售后服务方案
  - 次级（level 2）：营业执照、财务报告/审计报告、纳税证明、社保证明、信用查询、资质证书、业绩证明
- 段落文本 < 80 字符且命中关键词 → 视为章节标题

**策略 4 — 编号正则**
- 复用招标解读 `rule_splitter.py` 的正则模式：
  - Level 1：`第X章/节/篇/部分`
  - Level 2：`一、二、三、`
  - Level 3：`（一）（二）`
  - 数字编号：`1.` `1.1` 等（仅短文本）

**策略 5 — LLM 兜底**
- 当以上策略最高置信度 < 0.7 时启用
- 复用现有 `clause_mapper.llm_extract_toc()`

#### 2.2 置信度评分

复用 `rule_splitter.py` 的 `compute_confidence` 逻辑：
```
confidence = min(found_sections / 6, 1.0) * (assigned_paragraphs / total_paragraphs)
```

用 `_select_best_strategy` 模式从策略 2/3/4 中选最优结果。策略 1（目录）单独判断：如果目录匹配成功（>= 3 条目），直接采用不参与竞争。

#### 2.3 返回格式

与现有 `build_index_from_toc` 返回格式兼容：
```python
{
    "toc_source": "document_toc" | "style_analysis" | "keywords" | "numbering" | "llm_generated",
    "confidence": float,
    "chapters": {
        "章节标题": {"start": int, "end": int, "level": int},
        ...
    }
}
```

#### 2.4 改动 `review_task.py`

Step 2（构建索引）从：
```python
toc = detect_toc(paragraphs)
if toc:
    tender_index = build_index_from_toc(toc, paragraphs)
else:
    toc = llm_extract_toc(paragraphs, api_settings)
    tender_index = build_index_from_toc(toc, paragraphs)
```

替换为：
```python
from src.reviewer.tender_rule_splitter import build_tender_index
tender_index = build_tender_index(paragraphs, api_settings)
```

## 文件变更清单

### 新建
- `src/reviewer/tender_rule_splitter.py` — 投标文件混合索引器
- `src/reviewer/tests/test_tender_rule_splitter.py` — 索引器测试

### 修改
- `web/src/composables/useSSE.ts` — 支持自定义 URL 参数
- `web/src/components/ProcessingStage.vue` — 支持自定义步骤列表 prop
- `web/src/views/BidReviewView.vue` — 用 useSSE + ProcessingStage 替换内联逻辑
- `server/app/tasks/review_task.py` — 替换索引逻辑 + 对齐 step key
- `server/app/routers/reviews.py` — SSE 端点改为 header auth
