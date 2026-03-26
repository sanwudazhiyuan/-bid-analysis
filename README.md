# 招标文件智能解析系统

一套面向政企办公场景的招标文件深度解析工具。上传招标文件（.doc / .docx / .pdf），AI 自动提取关键信息并生成结构化分析报告、投标文件格式模板和资料清单。

## 功能特性

- **智能解析** — 基于通义千问大模型，自动提取招标文件 7 大模块（基本信息、资格要求、评标办法、废标条款、投标要求、合同条款、其他）
- **人工审核** — 逐模块对照原文校对 AI 提取结果，支持批注修改后重新生成
- **文档生成** — 自动生成分析报告、投标文件格式、资料清单三类 Word 文档
- **文件管理** — 按类型浏览、搜索、预览、下载所有生成文件
- **多用户** — JWT 认证，管理员可创建/管理用户
- **实时进度** — SSE 推送解析进度，四步流水线可视化（解析 → 索引 → 提取 → 生成）

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Tailwind CSS v4 + Lucide Icons |
| 后端 API | FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL |
| 任务队列 | Celery + Redis |
| AI 模型 | 通义千问（DashScope API） |
| 文档解析 | python-docx + antiword + pdfplumber |
| 部署 | Docker Compose (Nginx + API + Worker + PostgreSQL + Redis) |

## 项目结构

```
├── web/                    # 前端 (Vue 3 SPA)
│   ├── src/
│   │   ├── views/          # 页面（登录、招标解读、文件管理、用户管理）
│   │   ├── components/     # 组件（上传、处理进度、审核、预览等阶段组件）
│   │   ├── stores/         # Pinia 状态管理
│   │   ├── api/            # Axios API 封装
│   │   └── assets/         # 设计令牌 (Tailwind @theme)
│   ├── Dockerfile          # Nginx 多阶段构建
│   └── nginx.conf          # 反向代理配置
├── server/                 # 后端 (FastAPI)
│   ├── app/
│   │   ├── routers/        # API 路由（认证、任务、文件、标注、用户）
│   │   ├── services/       # 业务逻辑层
│   │   ├── models/         # SQLAlchemy ORM 模型
│   │   ├── tasks/          # Celery 异步任务
│   │   └── schemas/        # Pydantic 请求/响应模型
│   ├── Dockerfile
│   └── requirements.txt
├── src/extractor/          # AI 提取引擎
│   ├── base.py             # 提取器基类（文档解析、分段、LLM 调用）
│   ├── module_a~g.py       # 7 个模块提取器
│   ├── bid_format.py       # 投标文件格式提取
│   └── checklist.py        # 资料清单提取
├── config/
│   ├── prompts/            # 各模块 LLM 提示词模板
│   ├── settings.yaml       # 全局配置
│   └── tag_rules.yaml      # 段落分类规则
├── docker-compose.yml      # 一键部署编排
└── requirements.txt        # Python 基础依赖
```

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
- 构建前端 (npm ci + vite build) 和后端镜像
- 启动 PostgreSQL、Redis、API 服务、Celery Worker、Nginx
- 等待数据库健康检查通过后启动应用

### 4. 访问系统

- **前端界面**: http://localhost
- **API 文档**: http://localhost:8000/docs

## 使用流程

```
上传招标文件 → AI 解析提取 → 人工审核批注 → 重新生成/确认 → 预览下载文档
```

1. 登录系统，进入「招标解读」页面
2. 上传 .doc / .docx / .pdf 格式的招标文件
3. 等待 AI 自动解析（实时显示四步进度）
4. 逐模块审核提取结果，可添加批注修改意见
5. 提交批注后 AI 根据修改意见重新提取，或跳过审核直接生成
6. 预览和下载生成的分析报告、投标文件格式、资料清单

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
pytest tests/

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
                          └─────────┘   └──────────┘  └───────────┘
                                                           │
                                                      通义千问 API
```

## 许可证

[MIT](LICENSE)
