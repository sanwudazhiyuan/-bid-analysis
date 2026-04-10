# 招标文件分析系统 — 部署与技术架构说明

## 一、系统概述

本系统用于自动化解读招标文件（.doc / .docx / .pdf），通过 LLM 提取关键信息并生成结构化分析报告。用户通过 Web 界面上传招标文件后，后端异步执行解析、索引、提取（9 个模块）和文档生成（3 份 .docx），全程可实时查看进度。

---

## 二、技术架构

```
┌───────────────┐     HTTP/WS     ┌──────────────┐
│   浏览器       │ ◄────────────► │   Nginx:80   │
│  (Vue 3 SPA)  │                 │  静态文件托管  │
└───────────────┘                 │  反向代理 /api │
                                  └──────┬───────┘
                                         │
                                         ▼
                                  ┌──────────────┐
                                  │  FastAPI:8000 │
                                  │  (uvicorn)    │
                                  └──┬───────┬───┘
                                     │       │
                              ┌──────┘       └──────┐
                              ▼                      ▼
                       ┌────────────┐         ┌───────────┐
                       │ PostgreSQL │         │   Redis    │
                       │   :5432    │         │   :6379    │
                       └────────────┘         └─────┬─────┘
                                                    │
                                                    ▼
                                              ┌───────────┐
                                              │  Celery    │
                                              │  Worker    │
                                              │ (异步任务)  │
                                              └───────────┘
```

### 2.1 服务组成（5 个 Docker 容器）

| 服务 | 镜像 | 端口 | 职责 |
|------|------|------|------|
| **nginx** | node:20 构建 → nginx:alpine | 80 | 托管前端 SPA，反向代理 `/api` 到后端，支持 SSE 长连接 |
| **api** | python:3.11-slim | 8000 | FastAPI 应用，提供 REST API，非 root 用户运行 |
| **worker** | python:3.11-slim（同 api） | — | Celery worker，执行文件解析和 LLM 提取任务 |
| **postgres** | postgres:16-alpine | 5432 | 主数据库，存储用户、任务、标注、生成文件记录 |
| **redis** | redis:7-alpine | 6379 | Celery 消息队列 + 结果后端 |

### 2.2 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| FastAPI | ≥0.110 | Web 框架，异步路由 |
| SQLAlchemy | ≥2.0（async） | ORM + 异步数据库访问 |
| asyncpg | ≥0.29 | PostgreSQL 异步驱动 |
| Alembic | ≥1.13 | 数据库迁移 |
| Celery | ≥5.3 | 异步任务队列 |
| Pydantic v2 | ≥2.5 | 请求/响应模型校验 |
| python-jose | ≥3.3 | JWT 令牌签发/验证 |
| bcrypt | ≥4.0 | 密码哈希（SHA-256 预哈希 → bcrypt） |
| 通义千问 (DashScope) | OpenAI 兼容接口 | LLM 信息提取 |
| python-docx | ≥1.1 | 生成 .docx 报告 |
| pdfplumber | ≥0.11 | PDF 文本提取 |

### 2.3 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ≥3.5 | 前端框架（Composition API + `<script setup>`） |
| Vue Router | ≥4.6 | 单页路由 |
| Pinia | ≥3.0 | 状态管理 |
| Axios | ≥1.13 | HTTP 客户端（含 JWT 拦截器） |
| Tailwind CSS | v4 | 样式框架 |
| Vite | v8 | 构建工具 |
| TypeScript | ≥5.9 | 类型安全 |

### 2.4 数据模型

```
users                tasks                    annotations          generated_files
├─ id (PK)           ├─ id (UUID PK)          ├─ id (PK)           ├─ id (PK)
├─ username          ├─ user_id (FK→users)    ├─ task_id (FK)      ├─ task_id (FK)
├─ password_hash     ├─ filename              ├─ user_id (FK)      ├─ file_type
├─ display_name      ├─ file_path             ├─ module_key        ├─ file_path
├─ role              ├─ file_size             ├─ section_id        ├─ file_size
├─ created_at        ├─ status                ├─ row_index         ├─ version
└─ last_login        ├─ current_step          ├─ annotation_type   └─ created_at
                     ├─ progress              ├─ content
                     ├─ error_message         ├─ status
                     ├─ celery_task_id        ├─ llm_response
                     ├─ extracted_data (JSONB) └─ created_at
                     ├─ checkbox_data (JSONB)
                     ├─ created_at
                     └─ completed_at
```

### 2.5 API 路由总览

| 路径 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/api/health` | GET | 健康检查 | 无 |
| `/api/auth/login` | POST | 登录获取 JWT | 无 |
| `/api/auth/me` | GET | 当前用户信息 | Bearer |
| `/api/auth/refresh` | POST | 刷新令牌 | Bearer |
| `/api/tasks` | POST | 上传文件创建任务 | Bearer |
| `/api/tasks` | GET | 任务列表（分页） | Bearer |
| `/api/tasks/{id}` | GET | 任务详情 | Bearer |
| `/api/tasks/{id}` | DELETE | 删除任务 | Bearer |
| `/api/tasks/{id}/progress` | GET | SSE 实时进度 | Bearer |
| `/api/tasks/{id}/preview` | GET | 预览提取数据 | Bearer |
| `/api/tasks/{id}/preview/checkbox` | PUT | 勾选确认 | Bearer |
| `/api/tasks/{id}/download/{type}` | GET | 下载生成文件 | Bearer |
| `/api/tasks/{id}/regenerate` | POST | 重新生成文档 | Bearer |
| `/api/tasks/{id}/annotations` | GET/POST | 标注列表/创建 | Bearer |
| `/api/tasks/{id}/annotations/{ann_id}` | PUT/DELETE | 更新/删除标注 | Bearer |
| `/api/tasks/{id}/reextract` | POST | 触发 LLM 重提取 | Bearer |
| `/api/users` | GET/POST | 用户列表/创建 | Admin |
| `/api/users/{id}` | PUT/DELETE | 更新/删除用户 | Admin |

### 2.6 LLM 提取模块

系统包含 9 个提取模块，每个模块有独立的 prompt 模板和提取逻辑：

| 模块 | 文件 | 说明 |
|------|------|------|
| module_a | 项目概况 | 项目名称、编号、预算、时间等 |
| module_b | 投标人资格要求 | 资质、业绩、人员等要求 |
| module_c | 评标办法 | 评分标准、技术/商务评分细则 |
| module_d | 招标范围 | 采购内容、技术参数、服务要求 |
| module_e | 合同条款 | 付款、验收、违约责任等 |
| module_f | 投标文件组成 | 投标文件格式和组成要求 |
| module_g | 其他注意事项 | 其他重要条款 |
| bid_format | 投标文件格式 | 格式规范和模板 |
| checklist | 资料清单 | 需准备的材料清单 |

生成 3 份 .docx 文档：**分析报告**、**投标文件格式**、**资料清单**。

---

## 三、快速启动（Docker Compose）

### 3.1 前提条件

- Docker ≥ 24.0 和 Docker Compose ≥ 2.20
- 通义千问 API Key（DashScope）

### 3.2 配置环境变量

在项目根目录创建 `.env` 文件（参考 `.env.example`）：

```bash
# 数据库密码
DB_PASSWORD=your_secure_password

# 通义千问 API Key（必填，LLM 提取功能依赖此 Key）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# JWT 签名密钥（生产环境务必修改）
JWT_SECRET=your_random_secret_string
```

### 3.3 构建并启动

```bash
# 1. 构建所有镜像
docker-compose build

# 2. 启动所有服务（后台运行）
docker-compose up -d

# 3. 等待服务健康就绪（观察 postgres 和 redis 的 healthcheck）
docker-compose ps

# 4. 执行数据库迁移
docker-compose exec api alembic -c server/alembic.ini upgrade head

# 5. 创建初始管理员账号（admin / admin123）
docker-compose exec api python -m server.scripts.create_admin
```

### 3.4 访问系统

| 地址 | 说明 |
|------|------|
| `http://localhost` | Web 界面（Nginx 代理） |
| `http://localhost:8000/docs` | FastAPI Swagger 文档 |
| `http://localhost:8000/api/health` | 健康检查端点 |

默认管理员账号：`admin` / `admin123`（首次登录后建议修改密码）。

### 3.5 停止服务

```bash
# 停止并保留数据卷
docker-compose down

# 停止并清除所有数据（包括数据库）
docker-compose down -v
```

---

## 四、本地开发

### 4.1 后端开发

```bash
# 安装依赖
pip install -r requirements.txt -r server/requirements.txt

# 需要本地运行 PostgreSQL 和 Redis，或通过 Docker 启动：
docker-compose up -d postgres redis

# 设置环境变量
export DATABASE_URL=postgresql+asyncpg://biduser:devpassword@localhost:5432/bid_analyzer
export REDIS_URL=redis://localhost:6379/0

# 运行数据库迁移
alembic -c server/alembic.ini upgrade head

# 启动 API 服务（热重载）
uvicorn server.app.main:app --reload --port 8000

# 另一个终端启动 Celery worker
celery -A server.app.tasks.celery_app worker --loglevel=info
```

### 4.2 前端开发

```bash
cd web
npm install
npm run dev    # Vite 开发服务器，默认 http://localhost:5173
```

Vite 开发模式下通过 proxy 将 `/api` 请求转发到 `http://localhost:8000`。

### 4.3 运行测试

```bash
# 后端测试（使用 SQLite 内存数据库，无需外部依赖）
python -m pytest server/tests/ -v

# 当前测试覆盖：85 个测试用例
#   - test_auth.py        : 14 tests（登录、刷新、登出）
#   - test_security.py    : 20 tests（密码哈希、JWT 令牌）
#   - test_tasks.py       : 13 tests（上传、SSE、列表、删除）
#   - test_preview.py     :  6 tests（预览数据、勾选）
#   - test_download.py    :  6 tests（下载、重新生成）
#   - test_annotations.py :  6 tests（标注 CRUD）
#   - test_reextract.py   :  3 tests（LLM 重提取）
#   - test_pipeline.py    :  2 tests（模块提取逻辑）
#   - test_users.py       :  8 tests（用户管理 API）
#   - test_rate_limit.py  :  2 tests（限流中间件）
```

---

## 五、安全措施

| 措施 | 说明 |
|------|------|
| JWT 认证 | Access Token（24h）+ Refresh Token（7d），HS256 签名 |
| 密码哈希 | SHA-256 预哈希 → bcrypt（防超长密码） |
| CORS 白名单 | 仅允许 `http://localhost` 和 `http://localhost:80` |
| 上传限流 | POST /api/tasks 每 IP 每分钟最多 10 次（429） |
| 文件类型校验 | 仅允许 .doc / .docx / .pdf |
| 文件大小限制 | 最大 50MB |
| 非 root 容器 | API/Worker 容器以 `appuser` 身份运行 |
| 服务自动重启 | 所有容器配置 `restart: unless-stopped` |
| 健康检查 | PostgreSQL、Redis、API 均配置 healthcheck |
| 数据隔离 | 用户只能访问自己的任务和标注 |
| Admin 保护 | 管理员账号不可通过 API 删除 |

---

## 六、项目目录结构

```
├── .env.example                  # 环境变量模板
├── docker-compose.yml            # Docker 编排（5 个服务）
├── requirements.txt              # Python 核心依赖
│
├── config/
│   └── prompts/                  # 9 个 LLM prompt 模板
│       ├── module_a.txt ~ module_g.txt
│       ├── bid_format.txt
│       └── checklist.txt
│
├── src/
│   ├── extractor/                # LLM 信息提取模块
│   │   ├── base.py               # 基础 LLM 调用 + 重提取逻辑
│   │   ├── extractor.py          # 统一入口（extract_all / extract_single_module）
│   │   └── module_a.py ~ module_g.py, bid_format.py, checklist.py
│   └── generator/                # .docx 文档生成
│       ├── report_gen.py         # 分析报告生成
│       ├── format_gen.py         # 投标文件格式生成
│       ├── checklist_gen.py      # 资料清单生成
│       ├── style_manager.py      # Word 样式管理
│       └── table_builder.py      # 表格构建工具
│
├── server/
│   ├── Dockerfile                # 后端镜像（非 root）
│   ├── requirements.txt          # 后端额外依赖
│   ├── alembic.ini               # 数据库迁移配置
│   ├── scripts/
│   │   └── create_admin.py       # 初始管理员创建脚本
│   ├── app/
│   │   ├── main.py               # FastAPI 入口 + 中间件
│   │   ├── config.py             # 配置（Pydantic Settings）
│   │   ├── database.py           # 异步数据库引擎
│   │   ├── deps.py               # 依赖注入（认证、Admin）
│   │   ├── security.py           # JWT + bcrypt
│   │   ├── models/               # ORM 模型
│   │   │   ├── user.py
│   │   │   ├── task.py
│   │   │   ├── annotation.py
│   │   │   └── generated_file.py
│   │   ├── schemas/              # Pydantic 响应模型
│   │   ├── services/             # 业务逻辑层
│   │   ├── routers/              # API 路由
│   │   │   ├── auth.py           # 认证（登录/刷新/登出）
│   │   │   ├── tasks.py          # 任务（上传/列表/进度/删除）
│   │   │   ├── preview.py        # 预览（数据/勾选）
│   │   │   ├── download.py       # 下载（文件/重新生成）
│   │   │   ├── annotations.py    # 标注（CRUD + 重提取）
│   │   │   └── users.py          # 用户管理（Admin）
│   │   └── tasks/                # Celery 异步任务
│   │       ├── celery_app.py     # Celery 实例
│   │       ├── pipeline_task.py  # 完整解析流水线
│   │       └── reextract_task.py # LLM 重提取任务
│   └── tests/                    # 85 个自动化测试
│
└── web/
    ├── Dockerfile                # 前端镜像（多阶段构建）
    ├── nginx.conf                # Nginx 配置（反向代理 + SSE）
    ├── package.json
    └── src/
        ├── api/                  # Axios API 客户端
        ├── components/           # Vue 组件
        ├── composables/          # 组合式函数
        ├── layouts/              # 布局模板
        ├── router/               # 路由配置
        ├── stores/               # Pinia 状态
        ├── types/                # TypeScript 类型定义
        └── views/                # 页面视图
            ├── LoginView.vue
            ├── DashboardView.vue
            ├── TaskDetailView.vue
            ├── PreviewView.vue
            └── AdminUsersView.vue
```

---

## 七、完整使用流程

1. **登录** → 输入用户名密码获取 JWT
2. **上传文件** → 拖拽或点击上传 .doc/.docx/.pdf 文件
3. **实时进度** → SSE 推送解析、索引、9 模块提取进度
4. **预览结果** → 按模块浏览提取的结构化表格数据
5. **勾选确认** → 逐行确认提取结果的准确性
6. **添加标注** → 对有误的行添加修改意见
7. **提交修改** → 批量触发 LLM 重新提取标注的段落
8. **下载文档** → 下载生成的分析报告、投标格式、资料清单（.docx）
9. **用户管理** → 管理员可创建/删除用户账号
