# 智能审核模式设计文档

## 概述

新增"智能审核"模式，与现有"固定审核"并行，用户可自主选择。智能审核利用 haha-code 智能体框架，将投标文件按章节树生成文件夹结构，让智能体像人类审核员一样自主导航、阅读文件（包括图片）、判定条款合规性。

## 动机

现有固定审核流程存在以下局限：
1. **章节映射依赖 LLM 预判** — clause_mapper 映射错误会导致审查遗漏
2. **上下文受限于预切分的批次** — 智能体无法自主跨章节查阅
3. **图片审查能力弱** — 图片作为 base64 嵌入 prompt，LLM 被动接收而非主动查阅

智能审核让智能体自主决定阅读哪些文件、查看哪些图片，更接近人类审核员的工作方式。

## 架构

```
┌─────────────┐       HTTP POST        ┌──────────────────┐
│  Server     │  ──────────────────►   │  haha-code 服务   │
│  (Celery    │  条款 + 文件夹路径       │  (Bun HTTP)      │
│   Worker)   │  ◄──────────────────   │  调用 CLI -p 模式  │
│             │     JSON 审查结果       │  自主读取文件夹    │
└─────────────┘                        └──────────────────┘
       │                                       │
       │         共享 Docker Volume            │
       └──────── /data/reviews/xxx/ ───────────┘
                   ├── 第一章_投标函/
                   │   ├── 1.1_投标函正文.md
                   │   └── images/
                   │       └── img001.png
                   ├── 第二章_商务部分/
                   │   ├── 2.1_企业资质.md
                   │   └── 2.2_业绩证明.md
                   └── ...
```

## 核心决策

| 项目 | 决策 | 理由 |
|------|------|------|
| 模式定位 | 与固定审核并行，用户选择 | 两种模式各有优劣，用户按需选择 |
| 部署方式 | 独立 Docker 容器 | 不依赖本地环境，docker-compose 集成 |
| 通信方式 | HTTP API | 容器间标准通信方式 |
| 审核编排 | 逐条款调用 | 条款所需阅读内容多，整批易超上下文 |
| 章节映射 | 不做预映射 | 智能体自主导航是核心价值 |
| 输出格式 | 与固定审核一致 | 下游批注和展示无需修改 |

## 组件设计

### 1. 文件夹生成器 — `src/reviewer/folder_builder.py`

将投标文件的章节树 + 段落转化为磁盘上的文件夹结构。

**输入：**
- `paragraphs: list[Paragraph]` — 投标文件段落（脱敏后）
- `tender_index: dict` — 章节树（含 chapters/children/path 等）
- `extracted_images: list[dict]` — 已提取的图片信息
- `output_dir: str` — 输出根目录

**输出：** 磁盘上的文件夹结构

**文件夹命名规则：**
- 一级目录：`第一章_招标公告/`（章节标题，特殊字符替换为下划线）
- 二级目录：`1.1_投标人须知/`
- 叶子节点文件：`1.1.1_资格要求.md`

**叶子节点 MD 格式：**
```markdown
# 1.1.1 资格要求

[P45] 投标人应当具有独立法人资格...
[P46] 投标人须提供以下资质证明文件...
[P47] ![图片](images/img003.png)
[P48] 近三年类似项目业绩不少于3个...
```

- 每个段落以 `[Pxxx]` 标记开头，xxx 为全局段落索引
- 图片使用 Markdown 图片语法 `![图片](images/xxx.png)`，引用相对路径
- 图片文件从已提取目录复制到对应章节的 `images/` 子目录

**根目录额外生成 `_目录.md`：**
```markdown
# 投标文件目录

- 第一章_招标公告/
  - 内容.md (P1-P14)
- 第二章_投标人须知/
  - 2.1_一般规定.md (P15-P30)
  - 2.2_资格要求.md (P31-P45)
  ...
```

### 2. haha-code 审核 Skill — `haha-code/skills/bid-review.md`

注入到 haha-code 的 skill 文件，指导智能体的审查行为和输出规范。

**Skill 核心内容：**

```markdown
---
name: bid-review
description: 审查投标文件条款合规性
---

# 投标文件条款审查

## 你的角色
你是资深招标审查专家，需要审查投标文件是否满足招标条款的要求。

## 输入
你会收到：
1. 一个条款（clause_text）及其依据（basis_text）和严重等级（severity）
2. 一个投标文件文件夹路径

## 审查流程

### 第一步：浏览目录结构
使用 Read 工具阅读文件夹根目录的 `_目录.md`，了解投标文件的整体结构。

### 第二步：定位相关章节
根据条款内容，判断哪些章节可能包含相关内容。主动浏览多个章节，不要仅凭文件名猜测。

### 第三步：深入阅读
逐一阅读相关章节的 MD 文件，注意：
- 记住每个段落的 [Pxxx] 标记，这是你定位问题的依据
- **重点：必须查看所有图片** — 图片中包含关键的资质证明、盖章文件、表格等内容
  - 遇到 `![图片](images/xxx.png)` 时，必须使用 Read 工具读取该图片文件
  - 图片内容可能包含：营业执照、资质证书、业绩合同、报价表、盖章承诺函等
  - 不查看图片可能导致严重的审查遗漏
- 如果一个章节不够，继续查看其他可能相关的章节

### 第四步：综合判定
基于所有阅读的内容，对条款做出判定。

## 输出格式
严格返回以下 JSON，不要添加任何其他文字：

{
  "result": "pass 或 fail 或 warning",
  "confidence": 0-100 的整数,
  "reason": "判定理由，简明扼要",
  "locations": [
    {
      "para_index": 段落索引号（即 [Pxxx] 中的数字）,
      "text_snippet": "该段落中的关键文本片段",
      "reason": "该段落存在问题的具体原因"
    }
  ]
}

## 判定标准
- **pass**: 投标文件完全满足该条款要求，confidence >= 80
- **fail**: 投标文件明确不满足该条款要求，有具体的缺失或违规
- **warning**: 无法确定是否满足（信息模糊、部分满足、需人工确认）

## 重要规则
1. 图片是审查的重要依据，必须逐一查看，不可跳过
2. locations 中的 para_index 必须是你实际阅读到的 [Pxxx] 中的数字
3. 如果整个文件夹中找不到与条款相关的内容，result 为 "warning"，reason 说明未找到
4. 不要凭推测判定 pass，必须找到实际依据
5. 只输出 JSON，不要输出思考过程
```

### 3. haha-code HTTP 服务 — `haha-code/server.ts`

轻量 Bun.serve 封装，提供 HTTP 接口。

**接口：**

```
POST /review
Content-Type: application/json

{
  "clause": {
    "clause_index": 3,
    "clause_text": "投标人须提供近三年不少于3个类似项目业绩证明",
    "basis_text": "第二章 2.3.1 资格要求",
    "severity": "critical",
    "source_module": "module_c"
  },
  "folder_path": "/data/reviews/xxx/tender_folder",
  "project_context": "项目名称：xxx 采购项目"
}
```

**响应：**
```json
{
  "result": "fail",
  "confidence": 90,
  "reason": "投标文件中仅提供了2个业绩证明，不满足3个的要求",
  "locations": [
    {"para_index": 156, "text_snippet": "...", "reason": "..."}
  ]
}
```

**实现逻辑：**
1. 接收请求，校验参数
2. 拼接 prompt（条款信息 + 文件夹路径 + project_context）
3. 调用 `bun cli.tsx -p "prompt" --add-dir folder_path` 并加载 bid-review skill
4. 解析 stdout，提取 JSON
5. 返回响应

**超时与错误处理：**
- 单次审查超时：5 分钟
- 返回解析失败时，返回 `{"result": "error", "confidence": 0, "reason": "智能体审查失败"}`

### 4. review_task.py 路由

**修改 ReviewTask 模型：**
- 新增 `review_mode` 字段：`"fixed"` | `"smart"`，默认 `"fixed"`

**修改 run_review 任务：**
- Step 1-3（解析、索引、提取条款）两种模式共享
- Step 4 分支：
  - `fixed` 模式：走现有 clause_mapper + batch review 流程
  - `smart` 模式：
    1. 调用 `folder_builder.build_tender_folder()` 生成文件夹
    2. 逐条款并发 HTTP 调用 haha-code `/review`
    3. 收集结果，格式化为统一的 review_items
- Step 5（生成 docx）两种模式共享

**并发控制：**
- 最多 4 个条款同时发给 haha-code（每个条款的智能体会占用大量资源）

### 5. Docker 集成

**haha-code/Dockerfile：**
```dockerfile
FROM oven/bun:1

WORKDIR /app
COPY haha-code/package.json haha-code/bun.lockb ./
RUN bun install --frozen-lockfile

COPY haha-code/ ./
COPY haha-code/.env .env

EXPOSE 3000
CMD ["bun", "run", "server.ts"]
```

**docker-compose.yml 新增：**
```yaml
haha-code:
  build:
    context: .
    dockerfile: haha-code/Dockerfile
  restart: unless-stopped
  environment:
    ANTHROPIC_AUTH_TOKEN: ${DASHSCOPE_API_KEY:-}
    ANTHROPIC_BASE_URL: https://dashscope.aliyuncs.com/apps/anthropic
    ANTHROPIC_MODEL: qwen3.6-plus
  volumes:
    - filedata:/data
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
    interval: 10s
    retries: 3
```

**server 端新增环境变量：**
```
HAHA_CODE_URL=http://haha-code:3000
```

### 6. 前端改动

**BidReviewView.vue：**
- 上传投标文件时新增审核模式选择：`固定审核` / `智能审核`
- 传入 `review_mode` 参数到后端 API

**API 层：**
- `POST /reviews` 请求体新增 `review_mode` 字段

## 数据流（智能审核模式）

```
1. 用户上传投标文件，选择"智能审核"
2. Celery worker 启动 run_review(review_mode="smart")
3. 解析投标文件 → paragraphs
4. 构建索引 → tender_index
5. 脱敏 + 图片提取
6. folder_builder 生成文件夹 → /data/reviews/xxx/tender_folder/
7. 提取审查条款 → clauses[]
8. 对每个 clause 并发:
   POST http://haha-code:3000/review
   → haha-code 智能体自主浏览文件夹
   → 返回 JSON 审查结果
9. 汇总 review_items
10. 生成 docx 批注文档
11. 返回结果
```

## 文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/reviewer/folder_builder.py` | 新建 | 文件夹生成器 |
| `haha-code/server.ts` | 新建 | HTTP 服务封装 |
| `haha-code/skills/bid-review.md` | 新建 | 审查 skill |
| `haha-code/Dockerfile` | 新建 | Docker 构建文件 |
| `server/app/tasks/review_task.py` | 修改 | 新增 smart 分支 |
| `server/app/models/review_task.py` | 修改 | 新增 review_mode 字段 |
| `server/app/schemas/review.py` | 修改 | 新增 review_mode 参数 |
| `server/app/services/review_service.py` | 修改 | 传递 review_mode |
| `docker-compose.yml` | 修改 | 新增 haha-code 服务 |
| `web/src/views/BidReviewView.vue` | 修改 | 模式选择 UI |
| `web/src/api/reviews.ts` | 修改 | 传递 review_mode |
