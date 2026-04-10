# 招标文件智能解析系统

一套面向政企办公场景的招标文件深度解析与标书审查工具。上传招标文件（.doc / .docx / .pdf），AI 自动提取关键信息并生成结构化分析报告、投标文件格式模板和资料清单。同时支持基于招标文件的**智能标书审查**，自动判定投标文件是否满足招标要求。

## 功能特性

### 招标解读

- **智能解析** — 基于通义千问大模型，自动提取招标文件 7 大模块（基本信息、资格要求、评标办法、废标条款、投标要求、合同条款、其他）
- **智能索引** — 混合策略（TOC 识别 + 层级编号 + 章节关键词）自动构建任意深度章节树，支持 5+ 层级编号
- **表格完整提取** — Word 表格渲染为 Markdown 格式输入 LLM，确保评分细则、报价明细等表格内容完整解析
- **人工审核** — 逐模块对照原文校对 AI 提取结果，支持批注修改后重新生成
- **文档生成** — 自动生成分析报告、投标文件格式、资料清单三类 Word 文档
- **文件管理** — 按类型浏览、搜索、预览、下载所有生成文件

### 标书审查

- **固定审核** — 将审查条款映射到投标文件章节，提取对应原文供 LLM 逐条审查，输出 pass/fail/warning 判定
- **智能审核** — 基于 Agent 自主浏览投标文件文件夹（Markdown + AI 图片描述），无需预提取原文，Agent 自行定位相关章节并判定
- **条款自动提取** — 从废标条款、资格条件、编制要求、技术评分等模块自动提取审查条款，按 critical/major/minor 严重程度分级
- **招标原文映射** — 智能审核模式下，将条款映射到招标文件章节并提取原文作为上下文，帮助 Agent 理解条款背景
- **图片智能审查** — AI 预描述提取图片内容（证书编号、有效期、盖章情况），嵌入章节 MD 文件，Agent 无需读取原始图片即可完成合规判定
- **顺序累积审查** — 对超长条款分批审查，逐批次传递摘要，末批次综合判定，保证长条款审查准确性
- **逐段批注** — 在投标文件原文中标注每个问题的具体段落位置，支持 Word 文档批注导出
- **实时进度** — SSE 推送审查进度，7 步流水线可视化（索引 → 图片描述 → 构建文件夹 → 条款提取 → 条款映射 → 审查 → 生成报告）

### 平台能力

- **多用户** — JWT 认证，管理员可创建/管理用户
- **实时进度** — SSE 推送解析/审查进度，流水线可视化
- **隐私脱敏** — 自动识别并替换姓名、电话、身份证号、邮箱、银行账号等 PII 信息

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Tailwind CSS v4 + Lucide Icons + Pinia |
| 后端 API | FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL |
| 任务队列 | Celery + Redis（异步审查管线） |
| AI 审查 Agent | Claude Code (Ink TUI) + Skills 系统 + MCP |
| AI 模型 | 通义千问（DashScope API，支持关闭思考模式 + JSON 结构化输出） |
| 文档解析 | python-docx + antiword + pdfplumber |
| 部署 | Docker Compose (Nginx + API + Worker + PostgreSQL + Redis + Agent) |

## 项目结构

```
├── web/                    # 前端 (Vue 3 SPA)
│   ├── src/
│   │   ├── views/          # 页面（登录、招标解读、标书审查、文件管理、审查结果）
│   │   ├── components/     # 组件（上传、处理进度、审核、预览等阶段组件）
│   │   ├── stores/         # Pinia 状态管理（reviewStore, analysisStore）
│   │   ├── api/            # Axios API 封装
│   │   ├── composables/    # 组合式函数（useSSE 实时进度订阅）
│   │   └── assets/         # 设计令牌 (Tailwind @theme)
│   ├── Dockerfile          # Nginx 多阶段构建
│   └── nginx.conf          # 反向代理配置
├── server/                 # 后端 (FastAPI)
│   ├── app/
│   │   ├── routers/        # API 路由（认证、任务、文件、标注、审查、用户）
│   │   ├── services/       # 业务逻辑层
│   │   ├── models/         # SQLAlchemy ORM 模型（Task, ReviewTask, User 等）
│   │   ├── tasks/          # Celery 异步任务（review_task 审查管线）
│   │   └── schemas/        # Pydantic 请求/响应模型
│   ├── Dockerfile
│   └── requirements.txt
├── haha-code/              # AI 审查 Agent（基于 Claude Code）
│   ├── server.ts           # HTTP 服务（/review 端点，超时控制 + JSON 修正重试）
│   ├── skills/             # Skills 系统（bid-review 审查技能）
│   ├── src/                # Claude Code 核心（CLI 入口、TUI、工具、服务层）
│   ├── tests/              # Agent 集成测试
│   ├── Dockerfile
│   └── package.json
├── src/
│   ├── parser/             # 文档解析（docx、pdf、doc 统一接口）
│   ├── extractor/          # AI 提取引擎
│   │   ├── base.py         # 提取器基类（LLM 调用、JSON 解析、分批处理）
│   │   ├── module_a~g.py   # 7 个模块提取器
│   │   ├── bid_format.py   # 投标文件格式提取（两次调用策略）
│   │   └── checklist.py    # 资料清单提取
│   ├── indexer/            # 智能索引引擎（TOC 识别 + 层级编号 + 标签分类）
│   ├── reviewer/           # 审查引擎
│   │   ├── clause_extractor.py     # 条款自动提取
│   │   ├── clause_mapper.py        # 条款→章节 LLM 映射
│   │   ├── bid_context.py          # 招标原文上下文提取（智能审核模式）
│   │   ├── folder_builder.py       # 投标文件 Markdown 文件夹构建
│   │   ├── tender_rule_splitter.py # 混合策略索引（TOC + 编号 + 关键词）
│   │   ├── smart_reviewer.py       # HTTP 客户端调用 haha-code Agent
│   │   ├── reviewer.py             # 固定审核 LLM 审查引擎
│   │   ├── annotator.py            # Word 批注文档生成
│   │   ├── image_extractor.py      # 图片提取
│   │   ├── image_describer.py      # AI 图片预描述
│   │   └── desensitizer.py         # PII 隐私脱敏
│   └── generator/          # 文档生成（报告、格式、清单）
├── config/
│   ├── prompts/            # LLM 提示词模板
│   ├── settings.yaml       # 全局配置
│   └── tag_rules.yaml      # 段落分类规则
├── docker-compose.yml      # 一键部署编排
└── requirements.txt        # Python 基础依赖
```

## 标书审查流程

### 固定审核

```
提取条款 → 映射到投标文件章节 → 提取对应原文 → LLM 逐条审查 → 生成批注文档
```

- 条款映射使用 LLM 将每个条款匹配到投标文件中最相关的章节节点（叶子节点优先）
- 按章节提取原文，对超长内容拆分批次，逐批送入 LLM 审查
- 审查结果包含 pass/fail/warning 判定 + 置信度 + 标注段落位置

### 智能审核

```
提取条款 → 映射到招标文件原文 → 构建投标文件 Markdown 文件夹 → Agent 自主浏览审查
```

- 条款映射到**招标文件**章节（而非投标文件），提取招标原文作为条款上下文
- 将投标文件按章节拆分为 Markdown 文件 + `_目录.md` + `_图片索引.md`
- Agent 通过 Read/Glob/Grep 工具自主浏览文件夹，定位相关章节和图片
- 图片 AI 预描述嵌入章节 MD 文件，Agent 无需读取原始图片即可判定
- 支持并发审查（最多 4 个条款并行），实时推送进度

## 快速开始

### 环境要求

- Docker & Docker Compose
- 通义千问 API Key（[DashScope 控制台](https://dashscope.console.aliyun.com/)获取）

### 1. 克隆项目

```bash
git clone https://github.com/sanwudazhiyuan/-bid-analysis.git
cd -bid-analysis
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
DB_PASSWORD=your-db-password
DASHSCOPE_API_KEY=sk-your-api-key
JWT_SECRET=your-random-secret-string
```

### 3. 启动服务

```bash
docker compose up -d --build
```

首次启动会自动完成：
- 构建前端 (npm ci + vite build)、后端和 Agent 镜像
- 启动 PostgreSQL、Redis、API 服务、Celery Worker、Haha-Code Agent、Nginx
- 等待数据库健康检查通过后启动应用

### 4. 访问系统

- **前端界面**: http://localhost
- **API 文档**: http://localhost:8000/docs

## 使用流程

### 招标解读

```
上传招标文件 → AI 解析提取 → 人工审核批注 → 重新生成/确认 → 预览下载文档
```

1. 登录系统，进入「招标解读」页面
2. 上传 .doc / .docx / .pdf 格式的招标文件
3. 等待 AI 自动解析（实时显示四步进度）
4. 逐模块审核提取结果，可添加批注修改意见
5. 提交批注后 AI 根据修改意见重新提取，或跳过审核直接生成
6. 预览和下载生成的分析报告、投标文件格式、资料清单

### 标书审查

```
选择招标任务 → 上传投标文件 → 选择审核模式 → 等待 AI 审查 → 查看审查结果
```

1. 进入「标书审查」页面
2. 选择一个已完成解析的招标任务
3. 上传对应的投标文件（.docx）
4. 选择审核模式（固定审核 / 智能审核）
5. 等待 AI 自动审查（实时显示七步进度）
6. 在「审查结果」页面查看所有审查记录和批注详情
7. 下载标注了批注的审查报告 Word 文档

## 开发指南

### 本地开发（前端）

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

### 本地开发（后端）

```bash
pip install -r requirements.txt -r server/requirements.txt
uvicorn server.app.main:app --reload
```

### 运行测试

```bash
# 后端
pytest src/extractor/tests/ src/reviewer/tests/

# 前端
cd web && npm test
```

## 服务架构

```
                    ┌──────────┐
      用户浏览器 ──→│  Nginx   │:80
                    └────┬─────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         静态文件                API 代理
         (Vue SPA)             /api/* ──→ ┌──────────┐
                                         │ FastAPI  │:8000
                                         └────┬─────┘
                                              │
                               ┌──────────────┼──────────────┐
                               │              │              │
                          ┌────┴────┐   ┌─────┴────┐  ┌─────┴─────┐
                          │PostgreSQL│   │  Redis   │  │  Celery   │
                          │  :5432   │   │  :6379   │  │  Worker   │
                          └─────────┘   └──────────┘  └─────┬─────┘
                                                             │
                                                      ┌──────┴──────┐
                                                      │             │
                                                 通义千问 API   Haha-Code Agent
                                                              (审查技能)
```

## 许可证

[MIT](LICENSE)
