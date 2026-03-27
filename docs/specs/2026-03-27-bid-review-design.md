# 标书审查功能设计规格

> 日期: 2026-03-27
> 状态: 待确认
> 范围: 新增"标书审查"功能，将招标解析报告中的条款与用户上传的投标文件逐条核对，生成带批注的审查报告

---

## 1. 功能概述

### 1.1 目标

在现有招标文件解析系统的基础上，新增投标文件审查功能：

- 用户上传投标文件，系统自动与已解析的招标文件逐条核对
- 重点审查废标条款（module_e），同时覆盖资格条件、投标编制要求、评标标准等
- LLM 对每条审查项给出 pass/fail/warning 判定及置信度（0-100）
- 生成带 Word 原生批注的 docx 审查报告（开头含汇总表 + 正文高亮与批注）
- 前端提供左原文右批注的预览界面，支持互相联动滚动

### 1.2 用户流程

```
标书审查页面
  ↓
选择招标文件（搜索框 + 最近5条）+ 上传投标文件
  ↓
自动检查招标文件解析状态:
  ├── completed → 直接使用 extracted_data
  ├── review → 自动调用 run_generate（跳过人工审核），等待完成
  ├── pending/extracting 等中间状态 → 等待 run_pipeline 完成后自动 run_generate
  └── failed → 提示用户重新解析招标文件
  ↓
投标文件索引:
  ├── 检测到目录页 → 按目录结构分段建索引
  └── 未检测到目录 → LLM 分批提取章节目录 → 合并 → 按目录建索引
  ↓
逐条核对（废标优先 → 资格 → 编制要求 → 评标）
  ↓
生成审查报告 docx（汇总表 + 高亮 + Word 原生批注）
  ↓
预览界面（左原文 + 右批注列表）/ 下载 docx
```

### 1.3 设计原则

- **复用现有解析器**：投标文件的解析复用 `src/parser/` 的 `parse_document()`，不复用 `src/indexer/` 的 tag 规则（投标文件结构不同），而是新建轻量级的 `tender_indexer`
- **优先级分级审查**：废标条款逐条严格审查，其他条款按重要性批量审查
- **增量式设计**：新增独立的 ReviewTask 模型和路由，不修改现有 Task 表和 API
- **自包含存储**：审查结果文件直接由 ReviewTask 管理，不依赖 GeneratedFile 表

---

## 2. 模块与审查优先级映射

现有招标解析的 9 个模块中，以下模块的提取结果将作为审查基准：

| 优先级 | 模块 | 内容 | 严重程度 | 审查策略 |
|--------|------|------|----------|----------|
| P0 | module_e | 废标/无效标风险提示 | critical | 逐条独立审查 |
| P1 | module_b | 投标人资格条件 | major | 按类别批量审查（5-8条/批） |
| P1 | module_f | 投标文件编制要求 | major | 按类别批量审查 |
| P2 | module_c | 技术评分标准 | minor | 检查响应完整性 |

module_a（项目基本信息）的关键约束（预算上限、投标截止时间等）作为每次 LLM 审查调用的背景上下文，附加在 system prompt 中，但不产生独立的审查条目。

module_d（合同条款）、module_g（开评标流程）、bid_format、checklist 不参与审查核对。

---

## 3. 数据模型

### 3.1 ReviewTask 表

```python
class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[uuid.UUID]          # PK, default=uuid4
    user_id: Mapped[int]           # FK → users.id
    bid_task_id: Mapped[uuid.UUID] # FK → tasks.id (关联的招标解析任务)
    tender_filename: Mapped[str]   # 投标文件原始文件名
    tender_file_path: Mapped[str]  # 投标文件存储路径（审查完成后保留）
    version: Mapped[int]           # 同 bid_task_id + 同 tender_filename 递增
    status: Mapped[str]            # pending|indexing|reviewing|completed|failed
    progress: Mapped[int]          # 0-100
    current_step: Mapped[str|None] # 当前步骤描述
    error_message: Mapped[str|None]
    celery_task_id: Mapped[str|None]

    # 审查结果
    review_summary: Mapped[dict|None]    # JSONB, 见 3.2
    review_items: Mapped[list|None]      # JSONB, 见 3.3
    tender_index: Mapped[dict|None]      # JSONB, 投标文件索引结构

    # 生成的文件（直接存路径，不依赖 GeneratedFile）
    annotated_file_path: Mapped[str|None]  # 带批注的 docx 路径

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime|None]

    # Relationships
    user = relationship("User")
    bid_task = relationship("Task")

    # DB-level unique constraint prevents version race condition
    __table_args__ = (
        UniqueConstraint('bid_task_id', 'tender_filename', 'version',
                         name='uq_review_version'),
    )
```

**认证与权限**：所有 API 端点通过 `get_current_user` 依赖注入获取当前用户，查询时过滤 `user_id`。admin 用户可查看所有审查任务。

**版本逻辑**：创建审查任务时，查询 `SELECT COALESCE(MAX(version), 0) FROM review_tasks WHERE bid_task_id=? AND tender_filename=?`，新版本 = max + 1。配合 UniqueConstraint 防止并发冲突。

**投标文件保留**：投标文件保存在 `/data/reviews/{review_task_id}/` 目录下，与审查结果共存。删除 ReviewTask 时一并清理整个目录。

### 3.2 review_summary 结构

```json
{
  "total": 32,
  "pass": 18,
  "fail": 6,
  "warning": 8,
  "critical_fails": 3,
  "avg_confidence": 0.78,
  "by_severity": {
    "critical": { "total": 12, "pass": 9, "fail": 3, "warning": 0 },
    "major": { "total": 14, "pass": 7, "fail": 2, "warning": 5 },
    "minor": { "total": 6, "pass": 2, "fail": 1, "warning": 3 }
  }
}
```

### 3.3 review_items 结构

每个审查条目的 `id` 为从 0 开始的顺序整数（在审查任务内唯一），按处理顺序分配。

```json
[
  {
    "id": 0,
    "source_module": "module_e",
    "clause_index": 0,
    "clause_text": "投标文件未按要求密封的，作废标处理",
    "result": "fail",
    "confidence": 92,
    "reason": "投标文件中未找到密封说明或骑缝章相关内容",
    "severity": "critical",
    "tender_locations": [
      {
        "chapter": "第三章 投标文件格式",
        "para_indices": [45, 46, 47],
        "text_snippet": "投标文件按照以下顺序装订..."
      }
    ]
  }
]
```

**字段说明**：
- `id`: 顺序整数，从 0 开始
- `confidence`: 整数 0-100
- `tender_locations`: 可以为空数组（当 LLM 未找到对应内容时）
- `para_indices`: 投标文件段落索引数组，用于前端高亮定位和 docx 批注定位

### 3.4 tender_index 结构

```json
{
  "toc_source": "document_toc | llm_generated",
  "chapters": [
    {
      "title": "第一章 投标函",
      "level": 1,
      "start_para": 0,
      "end_para": 23,
      "children": [
        {
          "title": "1.1 投标承诺",
          "level": 2,
          "start_para": 5,
          "end_para": 15
        }
      ]
    }
  ]
}
```

### 3.5 文件存储

审查相关文件统一存储在 `/data/reviews/{review_task_id}/` 目录下：

```
/data/reviews/{review_task_id}/
  ├── {tender_filename}                    # 投标文件原件
  └── 审查报告_{tender_filename}            # 带批注的审查报告 docx
```

不使用 `GeneratedFile` 表存储审查结果。`ReviewTask.annotated_file_path` 直接记录路径。删除 ReviewTask 时，`shutil.rmtree` 清理整个目录。

---

## 4. 投标文件索引流程

### 4.1 目录检测

投标文件通常在前几页有目录。检测策略：

1. 解析投标文件全部段落（复用 `parse_document()`，返回 `list[Paragraph]`）
2. 扫描前 50 个段落，检测目录特征：
   - 段落样式包含 "TOC" 或 "toc" 相关样式名
   - 连续多行匹配正则 `^(第[一二三四五六七八九十\d]+[章节篇]|[\d.]+)\s*.+[\d.]+$`（标题+页码）
   - 存在 "目录" 标题段落且其后 ≥5 行连续符合目录行格式
3. 如检测到，提取目录项：`[{ title, level, page_hint }]`

```python
def detect_toc(paragraphs: list[Paragraph]) -> list[dict] | None:
    """检测并提取投标文件的目录结构。
    返回目录项列表，未检测到则返回 None。"""
```

### 4.2 基于目录的索引构建

当检测到目录时：

1. 遍历全文段落，根据目录标题和级别匹配段落位置
2. 使用标题文本的模糊匹配（`difflib.SequenceMatcher`，阈值 0.7），因为正文标题可能与目录条目略有差异
3. 构建 `tender_index`：每个章节记录 `start_para` 和 `end_para`
4. 支持多级目录（最多 3 级）

### 4.3 LLM 辅助目录生成

当未检测到目录时：

1. 将投标文件按 token 上限分批（每批约 30k tokens，TOC 提取是轻量任务不需要大窗口）
2. 每批发给 LLM，提取章节结构：`[{ title, level, first_sentence }]`
3. 合并多批结果，去重，按段落顺序排列
4. 用脚本将 `first_sentence` 模糊匹配到段落索引，构建 `tender_index`

Prompt 模板（`config/prompts/review_toc.txt`）：
```
你是文档结构分析专家。请分析以下投标文件片段，提取所有章节标题及其层级。
返回 JSON 格式：{"chapters": [{"title": "章节标题", "level": 1, "first_sentence": "该章节第一句话"}]}
注意：只提取章节结构，不需要总结内容。level 1 为最高层级（如"第一章"），level 2 为子章节。
```

### 4.4 章节-段落映射

无论目录来源如何，最终都生成标准化的 `tender_index` 结构（见 3.4）。每个章节包含其对应的段落范围，用于后续审查时快速定位相关内容。

---

## 5. 审查核对流程

### 5.1 条款提取

从招标文件的 `extracted_data` 中提取审查条目。`extracted_data` 的结构为 `{"schema_version": "1.0", "modules": {"module_e": {"sections": [...]}, ...}}`。

module_e 的 sections 中，每个 section 有 `columns`（如 `["序号", "风险项", "原文依据", "来源章节"]`）和 `rows`。条款文本取 "风险项" 和 "原文依据" 列，忽略序号列。

```python
def extract_review_clauses(extracted_data: dict) -> list[dict]:
    """从招标解析结果中提取所有需要核对的条款。"""
    clauses = []
    modules = extracted_data.get("modules", {})

    # P0: 废标条款 (module_e) — 逐条提取
    module_e = modules.get("module_e", {})
    for section in module_e.get("sections", []):
        columns = section.get("columns", [])
        # 找到 "风险项" 和 "原文依据" 列的索引
        risk_idx = _find_column(columns, "风险项")
        basis_idx = _find_column(columns, "原文依据")
        for i, row in enumerate(section.get("rows", [])):
            clause_text = row[risk_idx] if risk_idx is not None else ""
            basis_text = row[basis_idx] if basis_idx is not None else ""
            clauses.append({
                "source_module": "module_e",
                "clause_index": i,
                "clause_text": clause_text,
                "basis_text": basis_text,
                "severity": "critical",
            })

    # P1: 资格条件 (module_b) + 编制要求 (module_f) — 类似逻辑
    # P2: 技术评分 (module_c) — 类似逻辑
    return clauses
```

### 5.2 项目上下文提取

从 module_a（项目基本信息）提取关键约束，作为审查的背景信息：

```python
def extract_project_context(extracted_data: dict) -> str:
    """从 module_a 提取项目名称、预算、截止时间等，拼为上下文文本。"""
    # 附加在每次 LLM 审查调用的 system prompt 中
```

### 5.3 章节语义映射

在逐条核对之前，先用一次 LLM 调用将所有条款映射到投标文件的章节：

```
输入:
  - 审查条款列表 (clause_text + severity)
  - 投标文件目录结构 (chapter titles from tender_index)

输出:
  [{ clause_index, relevant_chapters: ["第三章 投标文件格式", "第五章 技术方案"] }]
```

这样每条核对只需发送相关章节的段落，大幅减少 token 消耗。

### 5.4 逐条核对

按优先级顺序处理：

**P0 废标条款**：每条独立调用 LLM
```
输入:
  - 项目上下文（来自 module_a）
  - 条款内容（clause_text + basis_text）
  - 投标文件中对应章节的段落文本（带段落索引）

输出:
  {
    "result": "pass" | "fail" | "warning",
    "confidence": 92,
    "reason": "未找到密封说明相关内容",
    "locations": [{ "para_index": 45, "text_snippet": "..." }]
  }
```

**P1/P2 条款**：批量核对（每 5-8 条一批）
```
输入:
  - 项目上下文
  - 条款列表 (最多 8 条)
  - 投标文件中对应章节的段落文本

输出:
  [{ "clause_index": 0, "result": "pass", "confidence": 85, ... }, ...]
```

### 5.5 错误处理

- **单条 LLM 调用失败**（超时/JSON 解析错误）：重试 2 次（复用现有 `call_qwen` 的 3 次重试机制）。全部失败后，将该条标记为 `result="error", confidence=0, reason="LLM 调用失败"`，继续处理后续条款。
- **章节映射失败**：如果 `llm_map_clauses_to_chapters` 返回空映射，回退到全文搜索模式（从投标文件全文中按关键词筛选相关段落）。
- **映射结果中某条款无对应章节**（`relevant_chapters` 为空）：将投标文件全文发给 LLM 核对该条（可能该条款对应的内容散落在多处）。
- **批量核对部分失败**：对失败的条款单独重试一次。

### 5.6 进度计算

```
0-10%    : 投标文件解析与索引构建
10-15%   : 条款提取与章节映射
15-60%   : P0 废标条款逐条核对
60-85%   : P1 资格/编制要求批量核对
85-95%   : P2 评标标准核对
95-100%  : 生成审查报告 docx
```

---

## 6. 审查报告生成

### 6.1 docx 结构

生成的审查报告 docx 包含两部分：

**Part 1: 审查汇总表（文档开头）**

```
┌──────────────────────────────────────────────────┐
│              投标文件审查报告                       │
│  招标项目: XXX采购项目                              │
│  投标文件: 某公司投标文件.docx                       │
│  审查时间: 2026-03-27                              │
├──────┬──────┬──────┬──────┬──────────────────────┤
│ 序号 │ 条款 │ 结果 │ 置信度│ 说明                  │
├──────┼──────┼──────┼──────┼──────────────────────┤
│  1   │ 废标1│  ✗   │ 92%  │ 未找到密封说明         │
│  2   │ 废标2│  ✓   │ 88%  │ 投标保证金已提供       │
│ ...  │ ...  │ ...  │ ...  │ ...                   │
└──────┴──────┴──────┴──────┴──────────────────────┘

统计: 共32条 | 通过18 | 不合规6 | 警告8
废标风险: 3条不合规 (critical)
```

**Part 2: 投标文件正文（带高亮和批注）**

- 打开投标文件原件（`python-docx` 的 `Document(tender_file_path)`）
- 根据 `review_items[].tender_locations[].para_indices` 定位到具体段落
- 不合规段落的 runs 添加高亮色：`fail` → 红色高亮，`warning` → 黄色高亮
- 在高亮段落上添加 Word 原生批注（`w:comment`）

实际生成流程：
1. 用 python-docx 打开投标文件原件（只读副本）
2. 在文档开头插入汇总表部分（标题 + 表格 + 统计）
3. 遍历 review_items，对每个有 `tender_locations` 的条目在对应段落添加高亮和批注
4. 保存为新文件到 `annotated_file_path`

### 6.2 Word 原生批注实现

python-docx 不原生支持 Comment API，需要操作底层 XML（`lxml`）：

1. **创建 comments.xml part**：在 docx 的 OPC 包中添加 `word/comments.xml` 文件
2. **添加关系**：在 `word/_rels/document.xml.rels` 中注册 comments part 的关系
3. **插入批注元素**：
   - 在目标段落的 run 前插入 `<w:commentRangeStart w:id="N"/>`
   - 在目标段落的 run 后插入 `<w:commentRangeEnd w:id="N"/>`
   - 在 run 中添加 `<w:commentReference w:id="N"/>`
   - 在 comments.xml 中添加对应的 `<w:comment w:id="N">` 元素
4. **维护全局 comment ID**：从 0 开始递增

```python
def add_word_comment(doc, para_element, comment_id: int,
                     comment_text: str, author: str = "AI审查"):
    """在指定段落上添加 Word 原生批注。
    需要操作 doc.part (OPC package) 来管理 comments.xml。"""
```

批注内容格式：
```
[废标条款 #3] 置信度: 92%
判定: 不合规
条款: 投标文件未按要求密封的，作废标处理
原因: 投标文件中未找到关于密封方式和骑缝章的说明
```

---

## 7. API 设计

### 7.1 审查任务接口

所有端点需要 JWT 认证（`Depends(get_current_user)`），查询时过滤 `user_id`。

```
POST   /api/reviews
  Body: multipart/form-data
    - tender_file: File (投标文件, .doc/.docx/.pdf)
    - bid_task_id: str (关联的招标任务 UUID)
  Validation:
    - bid_task_id 必须是当前用户的有效 Task
    - 文件类型限制同现有上传（.doc/.docx/.pdf）
  Response: { id, status, version }

GET    /api/reviews
  Query: page, page_size, q (搜索 tender_filename)
  Response: { items: [...], total, page, page_size }
  说明: 每个 (bid_task_id, tender_filename) 只返回最新版本

GET    /api/reviews/{id}
  Response: { id, bid_task_id, bid_filename, tender_filename, version,
              status, review_summary, review_items, created_at }

DELETE /api/reviews/{id}
  Response: 204
  Side effects: 删除 /data/reviews/{id}/ 目录及所有文件
```

### 7.2 审查进度与预览

```
GET    /api/reviews/{id}/progress
  Response: SSE stream（复用现有 SSE 模式，通过 Celery AsyncResult 轮询）
  Events: { progress, step, detail, error }

GET    /api/reviews/{id}/preview
  Response: {
    tender_html: "...",
    review_items: [...],
    summary: { total, pass, fail, warning, critical_fails }
  }
  说明:
    - tender_html 由服务端用 _docx_to_html() 渲染，在高亮段落的 HTML 标签上
      注入 data-review-id="N" 属性（N 对应 review_items[].id）
    - 未命中任何审查条目的段落正常渲染，无额外属性

GET    /api/reviews/{id}/download
  Response: FileResponse (带批注的 docx)
  Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

### 7.3 招标文件搜索（供审查上传页使用）

复用现有 `GET /api/tasks` 端点，前端传 `status=completed` 和 `q` 参数即可：

```
GET /api/tasks?status=completed&q=甘肃银行&page_size=5
```

如果现有 `/api/tasks` 端点不支持 `status` 过滤，需要在 `tasks.py` 路由中新增该查询参数。

---

## 8. Celery 任务

### 8.1 run_review 任务

```python
@celery_app.task(bind=True, name="run_review")
def run_review(self, review_id: str):
    """主审查任务：索引 → 映射 → 核对 → 生成报告"""

    with Session(engine) as db:
        review = db.get(ReviewTask, uuid.UUID(review_id))
        bid_task = db.get(Task, review.bid_task_id)

        # Step 0: 确保招标文件已完成解析
        ensure_bid_analysis_complete(bid_task, db)
        extracted_data = bid_task.extracted_data

        # Step 1: 解析投标文件 (0-5%)
        self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 0})
        paragraphs = parse_document(review.tender_file_path)

        # Step 2: 构建投标文件索引 (5-10%)
        toc = detect_toc(paragraphs)
        if toc:
            tender_index = build_index_from_toc(toc, paragraphs)
            tender_index["toc_source"] = "document_toc"
        else:
            toc = llm_extract_toc(paragraphs, api_settings)
            tender_index = build_index_from_toc(toc, paragraphs)
            tender_index["toc_source"] = "llm_generated"
        review.tender_index = tender_index

        # Step 3: 提取审查条款 + 项目上下文 (10-12%)
        self.update_state(state="PROGRESS", meta={"step": "reviewing", "progress": 10})
        clauses = extract_review_clauses(extracted_data)
        project_context = extract_project_context(extracted_data)

        # Step 4: 章节语义映射 (12-15%)
        chapter_mapping = llm_map_clauses_to_chapters(clauses, tender_index, api_settings)

        # Step 5: P0 逐条核对 (15-60%)
        review_items = []
        item_id = 0
        p0 = [c for c in clauses if c["severity"] == "critical"]
        for i, clause in enumerate(p0):
            progress = 15 + int(45 * i / max(len(p0), 1))
            self.update_state(state="PROGRESS", meta={
                "step": "reviewing",
                "detail": f"废标审查 [{i+1}/{len(p0)}]",
                "progress": progress,
            })
            relevant_text = get_chapter_text(paragraphs, tender_index, chapter_mapping.get(clause["clause_index"], []))
            try:
                result = llm_review_clause(clause, relevant_text, project_context, api_settings)
                result["id"] = item_id
                review_items.append(result)
            except Exception:
                review_items.append({"id": item_id, "result": "error", "confidence": 0, "reason": "LLM 调用失败", ...})
            item_id += 1

        # Step 6: P1 批量核对 (60-85%)
        p1 = [c for c in clauses if c["severity"] == "major"]
        for batch in chunk(p1, 8):
            results = llm_review_batch(batch, relevant_texts, project_context, api_settings)
            for r in results:
                r["id"] = item_id
                review_items.append(r)
                item_id += 1

        # Step 7: P2 批量核对 (85-95%) — 同 Step 6 逻辑

        # Step 8: 生成审查报告 docx (95-100%)
        self.update_state(state="PROGRESS", meta={"step": "generating", "progress": 95})
        summary = compute_summary(review_items)
        annotated_path = generate_review_docx(
            review.tender_file_path, review_items, summary,
            bid_filename=bid_task.filename
        )

        review.review_summary = summary
        review.review_items = review_items
        review.annotated_file_path = annotated_path
        review.status = "completed"
        review.progress = 100
        db.commit()

    return {"status": "completed", "review_id": review_id}
```

### 8.2 招标文件自动解析

```python
def ensure_bid_analysis_complete(bid_task: Task, db: Session):
    """确保招标文件已完成全流程解析（含文档生成）。

    状态处理:
    - completed: 直接返回
    - review: 调用 run_generate.delay()，轮询等待完成（超时 10 分钟）
    - pending/parsing/indexing/extracting: 轮询等待 run_pipeline 完成，
      然后自动调用 run_generate，再等待完成（总超时 30 分钟）
    - failed: 抛出异常，审查任务标记为 failed

    等待方式：每 5 秒查询一次 DB 中 bid_task.status。
    """
```

---

## 9. 前端设计

### 9.1 导航栏更新

在 `AppSidebar.vue` 的 `navItems` 数组中新增两项：

```typescript
const navItems = [
  // 上侧 - 主功能
  { path: '/', label: '招标解读', icon: PenLine, group: 'main' },
  { path: '/bid-review', label: '标书审查', icon: ShieldCheck, group: 'main' },
  // 分隔线 + "文档管理"
  { path: '/files/bid-documents', label: '招标文件', icon: FolderOpen, group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: BarChart3, group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: Ruler, group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: ClipboardList, group: 'files' },
  { path: '/review-results', label: '审查结果', icon: FileCheck, group: 'files' },
]
```

### 9.2 路由

新增路由作为 SidebarLayout 的子路由（与现有路由同级）：

```typescript
// 在 SidebarLayout children 中新增
{ path: 'bid-review', name: 'bid-review', component: BidReviewView },
{ path: 'review-results', name: 'review-results', component: ReviewResultsView },
{ path: 'review-results/:id', name: 'review-detail', component: ReviewDetailView },
```

### 9.3 BidReviewView 三阶段

**阶段 1: Upload (ReviewUploadStage.vue)**

```
┌─────────────────────────────────────────────────────┐
│                                                       │
│  ┌─ 选择招标文件 ─────────────────────────────────┐  │
│  │ 🔍 搜索已解析的招标文件...                      │  │
│  │                                                  │  │
│  │ 最近使用:                                        │  │
│  │  ● 甘肃银行IC卡外包服务采购     2026-03-25      │  │
│  │  ● 普洱市医保刷脸终端设备        2026-03-25      │  │
│  │  ● 重庆三峡银行金融IC卡          2026-03-24      │  │
│  └──────────────────────────────────────────────────┘  │
│                                                       │
│  ┌─ 上传投标文件 ─────────────────────────────────┐  │
│  │                                                  │  │
│  │        拖拽文件到此处或点击上传                    │  │
│  │        支持 .doc / .docx / .pdf                  │  │
│  │                                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                       │
│                              [开始审查]                │
│                                                       │
└─────────────────────────────────────────────────────┘
```

搜索框调用 `GET /api/tasks?status=completed&q=...&page_size=5`，300ms 防抖。未输入时显示最近 5 条已完成任务。选中后显示文件名和绿色勾。

**阶段 2: Processing**

复用现有 ProcessingStage 组件的样式，步骤标签改为：
`索引 → 映射 → 废标审查 → 资格审查 → 生成报告`

**阶段 3: Preview (ReviewPreviewStage.vue)**

```
┌──────────────────────────────────────────────────────┐
│ 审查概览                                              │
│ 共32条  ✓通过18  ⚠警告8  ✗不合规6  废标风险:3条       │
│                                          [下载报告]   │
├─────────────────────┬────────────────────────────────┤
│   投标文件原文       │   审查批注                      │
│   (scrollable)      │   (scrollable)                  │
│                     │                                 │
│ ...正常文本...       │  ✗ [废标#3] 置信度 92%          │
│ ██ 高亮段落 ██ ←───│──  未找到密封说明                │
│                     │    来源: 废标条款第3条            │
│ ...正常文本...       │                                 │
│                     │  ⚠ [资格#5] 置信度 67%          │
│ ██ 高亮段落 ██ ←───│──  社保证明仅2个月              │
│                     │    来源: 资格条件第5条            │
│                     │                                 │
├─────────────────────┴────────────────────────────────┤
│ 某公司投标文件.docx  v2        [下载报告]  [开始新审查] │
└──────────────────────────────────────────────────────┘
```

**联动逻辑实现**：
- 服务端在 `GET /api/reviews/{id}/preview` 返回的 `tender_html` 中，对命中审查条目的段落注入 `data-review-id="N"` 属性和高亮 CSS class
- 前端左侧使用 `v-html` 渲染 `tender_html`
- 右侧渲染 `review_items` 列表，每项有 `data-review-id="N"`
- 点击右侧批注 → `document.querySelector('[data-review-id="N"]')` 在左侧 `.scrollIntoView({ behavior: 'smooth' })`，并添加闪烁动画 class
- 点击左侧高亮段落 → 同理滚动右侧对应批注
- 对于无法定位的审查条目（`para_indices` 为空），右侧批注不显示定位图标

### 9.4 ReviewResultsView

独立的审查结果列表页面（不复用 FileManagerView，因为数据源是 `review_tasks` 表而非 `generated_files`）。

功能：列表展示、搜索、分页、点击查看详情/下载/删除。每条显示：招标文件名、投标文件名、版本号、审查结果摘要、时间。

### 9.5 reviewStore (Pinia)

```typescript
export const useReviewStore = defineStore('review', () => {
  const stage = ref<'upload' | 'processing' | 'preview'>('upload')
  const selectedBidTask = ref<{ id: string; filename: string } | null>(null)
  const currentReviewId = ref<string | null>(null)
  const progress = ref(0)
  const currentStep = ref('')
  const reviewSummary = ref<ReviewSummary | null>(null)
  const reviewItems = ref<ReviewItem[]>([])
  const error = ref<string | null>(null)

  async function startReview(bidTaskId: string, tenderFile: File) { ... }
  function handleProgressEvent(event: ProgressEvent) { ... }
  function resetToUpload() { ... }
  async function loadReviewResult(reviewId: string) { ... }

  return { ... }
})
```

---

## 10. 置信度展示规则

| 置信度范围 | 颜色 | 含义 |
|-----------|------|------|
| ≥ 80 | 红/绿（按 result） | 高置信度，结果可信 |
| 50-79 | 橙色 | 中置信度，建议人工复核 |
| < 50 | 灰色 | 低置信度，仅供参考 |

在预览界面和 docx 汇总表中均使用此规则。汇总表中用条件格式着色（fail=红底, warning=橙底, pass=绿底）。

---

## 11. 新增文件清单

### 后端
```
server/app/models/review_task.py         — ReviewTask ORM 模型
server/app/routers/reviews.py            — 审查相关 API 路由
server/app/services/review_service.py    — 审查业务逻辑（条款提取、结果存储、版本管理）
server/app/tasks/review_task.py          — run_review Celery 任务
src/reviewer/                            — 审查核心模块（新目录）
  ├── __init__.py
  ├── toc_detector.py                    — 目录检测与提取
  ├── tender_indexer.py                  — 投标文件索引构建（基于目录 → 段落映射）
  ├── clause_extractor.py               — 从 extracted_data 提取审查条款 + 项目上下文
  ├── clause_mapper.py                   — 条款-章节语义映射（LLM）
  ├── reviewer.py                        — LLM 逐条/批量核对
  └── docx_annotator.py                  — 生成带批注的 docx（汇总表 + 高亮 + w:comment）
```

### 前端
```
web/src/views/BidReviewView.vue          — 审查主界面（3阶段状态机）
web/src/views/ReviewResultsView.vue      — 审查结果列表
web/src/views/ReviewDetailView.vue       — 审查详情预览（左右联动）
web/src/components/ReviewUploadStage.vue — 上传阶段（搜索选择+拖拽上传）
web/src/components/ReviewPreviewStage.vue— 预览阶段（左原文右批注）
web/src/stores/reviewStore.ts            — 审查状态管理
web/src/api/reviews.ts                   — 审查 API 调用
```

### 配置
```
config/prompts/review_toc.txt            — 目录提取 prompt
config/prompts/review_mapping.txt        — 条款-章节映射 prompt
config/prompts/review_clause.txt         — 单条核对 prompt
config/prompts/review_batch.txt          — 批量核对 prompt
```

---

## 12. 数据库迁移

新增 `review_tasks` 表。通过 SQLAlchemy 的 `Base.metadata.create_all()` 自动创建（项目当前不使用 Alembic）。

不修改现有 `tasks`、`annotations`、`generated_files` 表。

---

## 13. 测试策略

| 层级 | 范围 | 工具 |
|------|------|------|
| 单元测试 | toc_detector, clause_extractor, tender_indexer | pytest |
| 集成测试 | run_review 任务流程（mock LLM 返回） | pytest + sync SQLite |
| API 测试 | /api/reviews CRUD、SSE、preview、download | httpx AsyncClient |
| 前端测试 | ReviewUploadStage, ReviewPreviewStage 组件 | vitest + @vue/test-utils |
| E2E | 上传 → 审查 → 预览 → 下载完整流程 | 手动测试 |
