# 招标文件分析系统 Web 平台设计规格

> 日期: 2026-03-23
> 状态: 待确认
> 范围: 将现有 CLI 管线封装为 Web 服务，支持文件上传、进度展示、交互式预览与标注、LLM 迭代修改

---

## 1. 项目概述

### 1.1 目标

将已完成的 5 层招标文件分析管线（解析 → 索引 → 提取 → 校对 → 生成）从 CLI 工具升级为 Web 应用，提供：

- 文件上传与异步处理
- 模块级实时进度展示
- 交互式在线预览（可勾选、标注、修改意见）
- 行级标注 → LLM 对照原文重新提取
- 三份 .docx 文件下载
- 任务历史管理
- 用户账号系统

### 1.2 用户规模

部门级应用，10-30 人使用，简单账号密码认证。

### 1.3 设计原则

- **零改造现有管线**：后端直接 import 现有 src/ 模块，不重写
- **异步优先**：LLM 提取耗时 8-10 分钟，全程异步 + 进度推送
- **Docker 一键部署**：docker-compose up 即可运行全部服务

---

## 2. 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | 0.110+ |
| 任务队列 | Celery | 5.3+ |
| 消息中间件 | Redis | 7+ |
| 数据库 | PostgreSQL | 16+ |
| ORM | SQLAlchemy 2.0 + Alembic | |
| 前端框架 | Vue 3 (Composition API) | 3.4+ |
| 前端构建 | Vite | 5+ |
| UI 样式 | Tailwind CSS | 3.4+ |
| 状态管理 | Pinia | 2.1+ |
| HTTP 客户端 | Axios | |
| 实时通信 | SSE (Server-Sent Events) | |
| 反向代理 | Nginx | |
| 容器化 | Docker + docker-compose | |

---

## 3. 系统架构

### 3.1 容器架构

```
docker-compose.yml
├── nginx          (端口 80/443)    — 静态资源 + 反向代理
├── api            (端口 8000)      — FastAPI 应用
├── worker         (无端口)         — Celery Worker (运行管线任务)
├── redis          (端口 6379)      — 任务队列 broker + 进度缓存
└── postgres       (端口 5432)      — 业务数据持久化
```

### 3.2 请求流程

```
用户浏览器
    │
    ▼
  Nginx ──── /api/*  ──→ FastAPI (api 容器)
    │                        │
    │                        ├── 同步操作: 登录、查询任务、获取数据
    │                        │
    │                        ├── 异步操作: 提交分析任务 → Celery → Redis
    │                        │                                    │
    │                        │                              Worker 容器
    │                        │                          (执行5层管线)
    │                        │                                    │
    │                        ├── SSE: /api/tasks/{id}/progress ←──┘
    │                        │        (Worker 写进度到 Redis,
    │                        │         API 读 Redis 推送给前端)
    │                        │
    │                        └── 数据持久化 → PostgreSQL
    │
    └── /* (其他) ──→ Vue SPA 静态文件
```

### 3.3 文件存储

```
/data/
├── uploads/          # 用户上传的原始文档
│   └── {task_id}/
│       └── 原始文件.doc
├── intermediate/     # 中间结果 JSON
│   └── {task_id}/
│       ├── parsed.json
│       ├── indexed.json
│       └── extracted.json
└── output/           # 生成的 .docx 文件
    └── {task_id}/
        ├── 分析报告.docx
        ├── 投标文件格式.docx
        └── 资料清单.docx
```

Docker 中挂载为 volume，数据持久化。

---

## 4. 数据库设计

### 4.1 核心表

```sql
-- 用户表
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(100),
    role          VARCHAR(20) DEFAULT 'user',  -- 'admin' | 'user'
    created_at    TIMESTAMP DEFAULT NOW(),
    last_login    TIMESTAMP
);

-- 分析任务表
CREATE TABLE tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       INTEGER REFERENCES users(id),
    filename      VARCHAR(500) NOT NULL,         -- 原始文件名
    file_path     VARCHAR(1000) NOT NULL,        -- 存储路径
    file_size     BIGINT,
    status        VARCHAR(20) DEFAULT 'pending', -- pending|parsing|indexing|extracting|generating|completed|failed
    current_step  VARCHAR(100),                  -- 当前步骤描述（如"提取 D.合同条款 [4/9]"）
    progress      INTEGER DEFAULT 0,             -- 0-100 进度百分比（仅在任务完成/失败时同步到DB，运行期间以Redis为准）
    error_message TEXT,
    celery_task_id VARCHAR(255),                 -- Celery AsyncResult ID，用于 SSE 进度查询
    -- 管线结果引用
    parsed_path   VARCHAR(1000),
    indexed_path  VARCHAR(1000),
    extracted_path VARCHAR(1000),
    -- 提取结果直接存 JSONB（方便前端查询和标注）
    extracted_data JSONB,
    -- 勾选状态：{module_key: {section_id: {row_index: true/false}}}
    checkbox_data  JSONB DEFAULT '{}',
    -- 时间戳
    created_at    TIMESTAMP DEFAULT NOW(),
    started_at    TIMESTAMP,
    completed_at  TIMESTAMP
);

-- 用户标注表（行级标注）
CREATE TABLE annotations (
    id            SERIAL PRIMARY KEY,
    task_id       UUID REFERENCES tasks(id) ON DELETE CASCADE,
    user_id       INTEGER REFERENCES users(id),
    module_key    VARCHAR(50) NOT NULL,     -- 如 'module_d'
    section_id    VARCHAR(20) NOT NULL,     -- 如 'D3'
    row_index     INTEGER,                  -- 表格行号（NULL 表示 section 级标注）
    annotation_type VARCHAR(20) NOT NULL,   -- 'comment' | 'correction' | 'flag'
    content       TEXT NOT NULL,            -- 标注内容/修改意见
    status        VARCHAR(20) DEFAULT 'pending', -- pending | submitted | resolved | failed
    llm_response  TEXT,                     -- LLM 重新提取的结果
    reextract_celery_id VARCHAR(255),       -- 重提取 Celery 任务 ID（用于独立 SSE 查询）
    created_at    TIMESTAMP DEFAULT NOW(),
    resolved_at   TIMESTAMP
);

-- 生成文件表
CREATE TABLE generated_files (
    id            SERIAL PRIMARY KEY,
    task_id       UUID REFERENCES tasks(id) ON DELETE CASCADE,
    file_type     VARCHAR(50) NOT NULL,    -- 'report' | 'format' | 'checklist'
    file_path     VARCHAR(1000) NOT NULL,
    file_size     BIGINT,
    version       INTEGER DEFAULT 1,       -- 版本号（重新生成时递增）
    created_at    TIMESTAMP DEFAULT NOW()
);
```

### 4.2 索引

```sql
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX idx_annotations_task_id ON annotations(task_id);
CREATE INDEX idx_annotations_module_section ON annotations(module_key, section_id);
```

---

## 5. 后端 API 设计

### 5.1 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录，返回 JWT token |
| POST | `/api/auth/logout` | 登出 |
| GET  | `/api/auth/me` | 获取当前用户信息 |

认证方式：JWT Bearer Token（Authorization header），access_token 有效期 24h，refresh_token 有效期 7 天。refresh_token 用于无感续期，前端在 access_token 过期前自动调用刷新。

| POST | `/api/auth/refresh` | 刷新 access_token（需提供有效 refresh_token） |

### 5.2 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 上传文件并创建分析任务 |
| GET  | `/api/tasks` | 获取任务列表（支持分页、状态筛选） |
| GET  | `/api/tasks/{id}` | 获取任务详情 |
| DELETE | `/api/tasks/{id}` | 删除任务及相关文件 |
| GET  | `/api/tasks/{id}/progress` | **SSE 端点**：实时进度推送 |

### 5.3 预览与标注

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/tasks/{id}/preview` | 获取提取结果 JSON（前端渲染为交互表格） |
| PUT  | `/api/tasks/{id}/preview/checkbox` | 更新勾选状态 |
| POST | `/api/tasks/{id}/annotations` | 创建标注（行级/section级） |
| GET  | `/api/tasks/{id}/annotations` | 获取所有标注 |
| PUT  | `/api/tasks/{id}/annotations/{ann_id}` | 修改标注内容 |
| DELETE | `/api/tasks/{id}/annotations/{ann_id}` | 删除标注 |
| POST | `/api/tasks/{id}/reextract` | 提交标注后触发 LLM 重新提取，返回 `{celery_task_id}` |
| GET  | `/api/tasks/{id}/reextract/{celery_task_id}/progress` | **SSE 端点**：重提取任务进度 |

### 5.4 文件下载

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/tasks/{id}/download/{type}` | 下载文件（type: report/format/checklist） |
| POST | `/api/tasks/{id}/regenerate` | 根据最新数据重新生成 .docx |

### 5.5 用户管理（仅 admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/users` | 用户列表 |
| POST | `/api/users` | 创建用户 |
| PUT  | `/api/users/{id}` | 修改用户 |
| DELETE | `/api/users/{id}` | 删除用户 |

---

## 6. Celery 任务与进度上报

### 6.1 主任务流程

```python
@celery_app.task(bind=True)
def run_pipeline(self, task_id: str):
    """执行完整分析管线，逐步上报进度。"""

    # Layer 1: 解析 (0-10%)
    self.update_state(state="PROGRESS", meta={
        "step": "parsing", "detail": "解析文档中...", "progress": 5
    })
    paragraphs = parse_document(file_path)

    # Layer 2: 索引 (10-20%)
    self.update_state(state="PROGRESS", meta={
        "step": "indexing", "detail": "构建索引中...", "progress": 15
    })
    index_result = build_index(paragraphs)

    # Layer 3: LLM 提取 (20-90%) — 按模块上报
    modules = ["module_a", ..., "checklist"]  # 9个模块
    for i, module_key in enumerate(modules):
        progress = 20 + int(70 * i / 9)
        self.update_state(state="PROGRESS", meta={
            "step": "extracting",
            "detail": f"提取 {module_key} [{i+1}/9]",
            "progress": progress,
            "current_module": module_key,
            "modules_done": i,
            "modules_total": 9,
        })
        # 调用单个模块提取...

    # 注意：跳过 Layer 4（CLI 人工校验）
    # Web 版由用户通过交互式预览页完成校验（标注+LLM重提取），
    # 因此管线直接从提取跳到生成。用户在预览页确认后，可触发 regenerate 重新生成。

    # Layer 5: 生成 (90-100%)
    self.update_state(state="PROGRESS", meta={
        "step": "generating", "detail": "生成文档中...", "progress": 95
    })
    # 生成三份 .docx...
```

### 6.2 进度推送 (SSE)

```python
@router.get("/tasks/{task_id}/progress")
async def task_progress(task_id: str):
    """SSE 端点：从 Redis 读取 Celery 任务状态并推送。"""
    async def event_generator():
        while True:
            result = AsyncResult(celery_task_id)
            if result.state == "PROGRESS":
                yield f"data: {json.dumps(result.info)}\n\n"
            elif result.state == "SUCCESS":
                yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                break
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': -1, 'step': 'failed', 'error': str(result.result)})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 6.3 标注重提取任务

```python
@celery_app.task(bind=True)
def reextract_section(self, task_id: str, module_key: str, section_id: str, annotations: list):
    """根据用户标注，对照原文重新提取指定 section。

    1. 从 indexed.json 加载原始段落
    2. 筛选该 section 相关段落
    3. 将用户标注作为额外 prompt 上下文
    4. 调用 LLM 重新提取
    5. 合并回 extracted_data
    """
```

---

## 7. 前端设计

### 7.1 页面结构

```
/login                          — 登录页
/                               — 仪表板（任务列表 + 快捷上传）
/tasks/{id}                     — 任务详情页（进度 / 预览 / 下载）
/tasks/{id}/preview             — 交互式预览（全屏，表格+标注）
/admin/users                    — 用户管理（仅管理员）
```

### 7.2 仪表板页面 (/)

```
┌─────────────────────────────────────────────────────────┐
│  Logo   招标文件分析系统            [用户名] [退出]      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────┐        │
│  │  📁 拖拽上传招标文件                          │        │
│  │     支持 .doc / .docx / .pdf                │        │
│  │     [点击选择文件]                            │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  我的分析任务                          [筛选: 全部 ▼]    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 文件名              状态      进度    时间   操作  │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 信用卡外包制递...    ✅ 完成   100%   3/23   查看  │   │
│  │ 智慧银行设备入围...  ⏳ 提取中  45%   3/23   查看  │   │
│  │ 医保刷脸终端...      ❌ 失败    —     3/22   重试  │   │
│  └──────────────────────────────────────────────────┘   │
│                                        [1] [2] [下一页]  │
└─────────────────────────────────────────────────────────┘
```

### 7.3 任务详情页 (/tasks/{id})

**处理中状态：**

```
┌─────────────────────────────────────────────────────────┐
│  ← 返回    信用卡外包制递卡采购项目                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  分析进度                                                │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  67%          │
│                                                         │
│  ✅ 文档解析    899 段落                                  │
│  ✅ 智能索引    置信度 0.99                               │
│  ⏳ 结构提取    模块 D.合同条款 [4/9]                     │
│  ○  文档生成    等待中                                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**完成状态：**

```
┌─────────────────────────────────────────────────────────┐
│  ← 返回    信用卡外包制递卡采购项目                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [预览分析结果]   [下载全部]                              │
│                                                         │
│  生成文件                                                │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 📄 分析报告.docx         48KB    [预览] [下载]   │   │
│  │ 📄 投标文件格式.docx     40KB    [预览] [下载]   │   │
│  │ 📄 资料清单.docx         40KB    [预览] [下载]   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  提取概览                                                │
│  ┌──────────────────────────────────────────────────┐   │
│  │ A.项目基本信息  ✅ 5节  │ B.资格条件 ✅ 5节      │   │
│  │ C.评分标准      ✅ 5节  │ D.合同条款 ✅ 8节      │   │
│  │ E.风险提示      ✅ 3节  │ F.编制要求 ✅ 5节      │   │
│  │ G.其他条款      ✅ 5节  │                         │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 7.4 交互式预览页 (/tasks/{id}/preview)

这是最核心的页面，支持三种交互操作：

```
┌─────────────────────────────────────────────────────────────────┐
│  ← 返回   预览: 信用卡外包制递卡采购项目    [提交修改] [重新生成] │
├──────────┬──────────────────────────────────────────────────────┤
│ 模块导航  │                                                      │
│          │  D. 合同主要条款                                      │
│ A.项目信息│                                                      │
│ B.资格条件│  D.3 违约责任                                        │
│ C.评分标准│  ┌─────────────────────────────────────────┬────┐    │
│ D.合同条款│  │ 违约情形    │ 处罚措施              │ 确认 │    │
│   ├ D.1   │  ├─────────────────────────────────────────┼────┤    │
│   ├ D.2   │  │ 延期交货    │ 2000元/天；超10天终止  │ ☑  │    │
│  >├ D.3   │  ├─────────────────────────────────────────┼────┤    │
│   ├ D.4   │  │ 质量不合格  │ 1000元/卡/次          │ ☐  │    │
│ E.风险提示│  │             │ [💬 已标注 1 条]       │    │    │
│ F.编制要求│  ├─────────────────────────────────────────┼────┤    │
│ G.其他条款│  │ 信息泄露    │ 5万元/次，终止合同     │ ☐  │    │
│          │  └─────────────────────────────────────────┴────┘    │
│          │                                                      │
│          │  ┌─ 标注面板 ──────────────────────────────────┐     │
│          │  │ 📌 第2行「质量不合格: 1000元/卡/次」          │     │
│          │  │                                              │     │
│          │  │ 💬 张三: 原文写的是"不合格率超10%终止合同"，   │     │
│          │  │    这里漏了后半句，请核实补充                  │     │
│          │  │                                              │     │
│          │  │ [添加标注...]                                 │     │
│          │  └──────────────────────────────────────────────┘     │
│          │                                                      │
└──────────┴──────────────────────────────────────────────────────┘
```

**交互操作：**

1. **勾选确认**：点击 ☐ 切换为 ☑，状态即时保存
2. **行级标注**：点击表格行，右侧展开标注面板，输入修改意见
3. **提交修改**：点击"提交修改"按钮，将所有未解决的标注发送给 LLM
4. **LLM 重提取**：LLM 对照原文 + 用户标注重新提取对应 section，结果自动更新到表格
5. **重新生成**：基于修改后的数据重新生成三份 .docx

### 7.5 标注 → LLM 重提取流程

```
用户在预览页标注行级修改意见
        │
        ▼
点击「提交修改」
        │
        ▼
前端将标注按 section 分组，POST /api/tasks/{id}/reextract
        │
        ▼
后端创建 Celery 任务 reextract_section()
        │
        ├── 加载该 section 对应的原始段落（从 indexed.json）
        ├── 构建 prompt = 原始 prompt + 用户标注（作为修正上下文）
        ├── 调用 LLM 重新提取该 section
        └── 将结果合并回 extracted_data (JSONB)
        │
        ▼
前端通过 SSE 接收更新，自动刷新表格内容
标注状态变为 "resolved"
```

**LLM 重提取 Prompt 模板：**

```
你是招标文件分析专家。请根据用户的修改意见，对照原文重新提取以下内容。

## 原始提取结果
{original_section_json}

## 用户修改意见
- 第{row_index}行「{cell_content}」: {annotation_content}
- ...

## 对应原文段落
{relevant_paragraphs}

## 要求
1. 仔细对照原文，修正用户指出的问题
2. 保持与原始结果相同的 JSON 结构
3. 只修改用户指出的问题，其他内容保持不变
```

---

## 8. 前端组件设计

### 8.1 组件树

```
App.vue
├── layouts/
│   ├── DefaultLayout.vue          — 带顶栏的主布局
│   └── AuthLayout.vue             — 登录页布局
├── views/
│   ├── LoginView.vue              — 登录页
│   ├── DashboardView.vue          — 仪表板（任务列表+上传）
│   ├── TaskDetailView.vue         — 任务详情（进度/下载）
│   ├── PreviewView.vue            — 交互式预览（核心页面）
│   └── AdminUsersView.vue         — 用户管理
├── components/
│   ├── FileUpload.vue             — 拖拽上传组件
│   ├── TaskList.vue               — 任务列表表格
│   ├── TaskProgress.vue           — 进度展示（步骤条+百分比）
│   ├── ModuleNav.vue              — 左侧模块/section 导航树
│   ├── SectionTable.vue           — 可交互表格（勾选+点击标注）
│   ├── AnnotationPanel.vue        — 右侧标注面板
│   ├── AnnotationBadge.vue        — 行上的标注角标
│   └── DownloadCard.vue           — 文件下载卡片
├── composables/
│   ├── useAuth.ts                 — 认证逻辑
│   ├── useSSE.ts                  — SSE 连接管理
│   └── useAnnotation.ts           — 标注 CRUD 逻辑
└── stores/
    ├── authStore.ts               — 用户认证状态
    ├── taskStore.ts               — 任务数据
    └── previewStore.ts            — 预览页状态（当前模块、标注等）
```

### 8.2 核心组件说明

**SectionTable.vue** — 最复杂的组件：

- 接收 section JSON 数据，渲染为 Tailwind 样式表格
- 每行末尾有 ☐ 勾选框（可切换）
- 点击行高亮，触发 AnnotationPanel 展开
- 有标注的行显示角标（💬 数字）
- 支持 key_value_table 和 standard_table 两种布局

**TaskProgress.vue** — 进度组件：

- 接收 SSE 推送的进度数据
- 显示 4 个步骤（解析/索引/提取/生成）
- 提取步骤展开显示模块级进度（[4/9] 模块 D.合同条款）
- 动画进度条

---

## 9. 后端目录结构

```
server/                          # 新增 Web 服务目录
├── app/
│   ├── __init__.py
│   ├── main.py                  — FastAPI 应用入口
│   ├── config.py                — Web 服务配置（DB、Redis、JWT 等）
│   ├── database.py              — SQLAlchemy 引擎 + 会话管理
│   ├── models/                  — SQLAlchemy ORM 模型
│   │   ├── user.py
│   │   ├── task.py
│   │   ├── annotation.py
│   │   └── generated_file.py
│   ├── schemas/                 — Pydantic 请求/响应模型
│   │   ├── auth.py
│   │   ├── task.py
│   │   └── annotation.py
│   ├── routers/                 — API 路由
│   │   ├── auth.py
│   │   ├── tasks.py
│   │   ├── preview.py
│   │   ├── annotations.py
│   │   ├── download.py
│   │   └── users.py
│   ├── services/                — 业务逻辑层
│   │   ├── auth_service.py
│   │   ├── task_service.py
│   │   ├── preview_service.py
│   │   └── reextract_service.py
│   ├── tasks/                   — Celery 任务定义
│   │   ├── celery_app.py
│   │   ├── pipeline_task.py     — 完整管线任务
│   │   └── reextract_task.py    — 标注重提取任务
│   ├── deps.py                  — FastAPI 依赖注入（get_db, get_current_user）
│   └── security.py              — JWT + 密码哈希
├── alembic.ini                  — Alembic 配置（标准位置：server/ 根目录）
├── alembic/                     — 数据库迁移
│   ├── env.py
│   └── versions/
├── requirements.txt             — Web 服务额外依赖
├── Dockerfile                   — API + Worker 镜像
└── tests/
    └── test_api/
        ├── test_auth.py
        ├── test_tasks.py
        └── test_annotations.py
```

**关键：`server/` 作为新目录，不修改现有 `src/` 结构。** Celery Worker 通过 `from src.xxx import ...` 直接调用现有管线。

---

## 10. 前端目录结构

```
web/                              # 前端项目目录
├── public/
│   └── favicon.ico
├── src/
│   ├── App.vue
│   ├── main.ts
│   ├── router/
│   │   └── index.ts
│   ├── layouts/
│   │   ├── DefaultLayout.vue
│   │   └── AuthLayout.vue
│   ├── views/                    — 页面组件（见 7.1）
│   ├── components/               — 通用组件（见 8.1）
│   ├── composables/              — 组合式函数
│   ├── stores/                   — Pinia 状态管理
│   ├── api/                      — Axios 封装
│   │   ├── client.ts             — Axios 实例 + 拦截器
│   │   ├── auth.ts
│   │   ├── tasks.ts
│   │   └── annotations.ts
│   ├── types/                    — TypeScript 类型定义
│   │   ├── task.ts
│   │   ├── annotation.ts
│   │   └── preview.ts
│   └── assets/
│       └── main.css              — Tailwind 入口
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── Dockerfile                    — 构建静态文件 + Nginx
```

---

## 11. Docker 部署

### 11.1 docker-compose.yml

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: bid_analyzer
      POSTGRES_USER: biduser
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U biduser"]
      interval: 5s

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  api:
    build:
      context: .
      dockerfile: server/Dockerfile
    command: uvicorn server.app.main:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: postgresql://biduser:${DB_PASSWORD}@postgres:5432/bid_analyzer
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
      JWT_SECRET: ${JWT_SECRET}
    volumes:
      - filedata:/data
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  worker:
    build:
      context: .
      dockerfile: server/Dockerfile
    command: celery -A server.app.tasks.celery_app worker --loglevel=info --concurrency=2
    environment:
      DATABASE_URL: postgresql://biduser:${DB_PASSWORD}@postgres:5432/bid_analyzer
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY}
    volumes:
      - filedata:/data
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  nginx:
    build:
      context: ./web
      dockerfile: Dockerfile
    ports:
      - "80:80"
    depends_on:
      - api
    # Nginx 配置需要：
    # - proxy_pass http://api:8000 用于 /api/*
    # - SSE 端点需 proxy_buffering off; proxy_cache off; proxy_read_timeout 600s;
    # - 静态文件由 nginx 容器直接服务

volumes:
  pgdata:
  redisdata:
  filedata:
```

### 11.2 环境变量 (.env)

```
DB_PASSWORD=your_secure_password
DASHSCOPE_API_KEY=sk-xxx
JWT_SECRET=your_jwt_secret_key
```

### 11.3 一键启动

```bash
docker-compose up -d
# 首次启动后初始化数据库
docker-compose exec api alembic upgrade head
# 创建管理员账号
docker-compose exec api python -m server.app.scripts.create_admin
```

---

## 12. 对现有代码的改动

### 12.1 需要修改的文件

| 文件 | 改动 | 原因 |
|------|------|------|
| `src/extractor/extractor.py` | 添加 `extract_single_module(module_key, paragraphs, index_result)` 包装函数 | CLI 的 `cmd_extract` 已能按模块提取（通过 `_MODULE_REGISTRY`），此函数是干净的 API 包装，供 Celery Worker 和重提取任务调用 |
| `src/extractor/base.py` | 添加 `reextract_with_annotations()` | 支持带标注上下文的重提取 |
| `src/logger.py` | 添加回调支持 | 允许 Celery Worker 捕获日志进度 |

**`reextract_with_annotations()` 函数契约：**

```python
def reextract_with_annotations(
    module_key: str,           # 如 "module_d"
    section_id: str,           # 如 "D3"
    original_section: dict,    # 当前 extracted_data 中该 section 的 JSON
    relevant_paragraphs: list, # 从 indexed.json 中筛选的相关原文段落
    annotations: list[dict],   # [{row_index: int, content: str, annotation_type: str}, ...]
) -> dict:
    """带用户标注的 LLM 重提取。

    1. 将 original_section + annotations 注入 prompt 模板（见 7.5）
    2. 连同 relevant_paragraphs 调用 LLM API
    3. 返回新的 section JSON（与原始结构相同）
    4. 调用方负责将结果合并回 task.extracted_data JSONB

    异常处理：LLM 调用失败时抛出 ExtractError，
    调用方捕获后将 annotation.status 设为 'failed'。
    """
```

### 12.2 不修改的部分

- `src/parser/` — 原样使用
- `src/indexer/` — 原样使用
- `src/generator/` — 原样使用
- `src/reviewer/` — CLI 版保留。Web 版跳过自动校验，由用户通过交互式预览页进行人工校验（标注 + LLM 重提取）
- `src/persistence.py` — 原样使用
- `src/config.py` — 原样使用
- `config/` — 原样使用

---

## 13. 安全考虑

1. **文件上传**：FastAPI 中间件限制大小（50MB）、类型白名单（.doc/.docx/.pdf）、病毒扫描（可选）。通过 Starlette `Request.stream()` + 大小计数器实现，拒绝超限文件
2. **JWT**：access_token 24h + refresh_token 7d，通过 Authorization header 传递
3. **SQL 注入**：SQLAlchemy ORM 参数化查询
4. **XSS**：Vue 模板自动转义 + CSP header
5. **CORS**：仅允许同域或指定域名
6. **文件隔离**：每个任务独立目录，用户只能访问自己的任务
7. **API 限流**：上传接口限流（10次/分钟）

---

## 14. 测试策略

| 层级 | 范围 | 工具 |
|------|------|------|
| 后端单元测试 | API 路由、服务层、Celery 任务 | pytest + httpx (AsyncClient) |
| 前端单元测试 | 组件渲染、Store 逻辑 | Vitest + Vue Test Utils |
| 集成测试 | API → DB → Celery 流程 | pytest + testcontainers (PostgreSQL, Redis) |
| E2E 测试 | 全流程（上传→分析→预览→下载） | Playwright |

---

## 15. 实施阶段划分

| Phase | 内容 | 预估工作量 |
|-------|------|-----------|
| **Phase 1** | 项目骨架：Docker + FastAPI + PostgreSQL + Vue + 认证 | 基础 |
| **Phase 2** | 文件上传 + Celery 管线任务 + 进度推送 | 核心 |
| **Phase 3** | 任务列表 + 历史管理 + 文件下载 | 基础 |
| **Phase 4** | 交互式预览（表格渲染 + 勾选） | 核心 |
| **Phase 5** | 标注系统 + LLM 重提取 | 核心 |
| **Phase 6** | 用户管理 + 安全加固 + 部署优化 | 收尾 |
