---
name: ollama-local-model-switching-design
description: Admin config UI for switching between cloud (DashScope) and local (Ollama) models, with context-length-aware batching
type: project
---

# Ollama 本地模型切换功能设计文档

## 概述

管理员可以通过配置界面将系统切换为使用本地 Ollama 服务器（10.165.25.39 用于 LLM，10.165.44.28 用于 Embedding），或切换回云端 DashScope 配置。全局开关：要么全本地，要么全云端。切换后立即生效（新 API 调用使用新配置，正在运行的任务继续用旧配置完成）。

本地模式下需额外关注上下文长度配额，单次请求不能超过上下文，否则分批次传输。

## 需求决策汇总

| 决策点 | 选择 |
|--------|------|
| 管理界面形式 | Vue 新增管理员页面 `/admin/config` |
| 配置生效时机 | 立即生效（新调用用新配置，正在运行任务用旧配置） |
| 模型选择方式 | 自动拉取 Ollama `/api/tags` 下拉选择 |
| 上下文长度获取 | 自动查询 `/api/show` 优先，查询不到时手动填写 |
| 配置持久化 | 数据库存储 + 同步到 settings.yaml |
| Smart Review | 同步切换，haha-code 也用本地 Ollama |
| haha-code 配置更新 | `/config` API 热更新 |
| 切换粒度 | 全局开关（全本地/全云端） |
| Embedding batch_size | 自动查询 + 动态计算，手动兜底 |
| LLM 审评分批 | 单条款也支持分批审评（intermediate → final） |
| 前端风格 | 与现有 Tailwind oklch 主题色和 AdminUsersView 布局一致 |
| Smart Review 模型选择 | Sonnet/Haiku/Default 三个模型从 10.165.25.39 下拉选择 |

## 架构方案：配置中心 + 动态运行时切换

新增 `ModelConfigService` 作为配置的权威中心，所有 LLM/Embedding 调用不再直接读 `settings.yaml`，而是从 `ModelConfigService` 获取当前生效配置。

---

## 1. 数据库模型

新增 `system_config` 表，存储模型配置（只保留一条记录，每次更新覆盖写入）：

```
system_config
├── id (Integer, PK)
├── mode (String) — "cloud" | "local"，全局开关
├── cloud_config (JSON) — 云端配置快照
│   ├── api: { base_url, api_key, model, temperature, max_output_tokens, ... }
│   ├── embedding: { model, dimensions, batch_size, ... }
│   └── haha_code: { anthropic_base_url, anthropic_model, ... }
├── local_llm_config (JSON) — 本地 LLM 配置
│   ├── server_url (String) — e.g. "http://10.165.25.39:11434"
│   ├── model_name (String) — e.g. "qwen2.5:14b"
│   ├── context_length (Integer) — e.g. 32768
│   ├── context_length_manual (Boolean) — 是否手动设定
│   ├── temperature, max_output_tokens, ...
├── local_embedding_config (JSON) — 本地 Embedding 配置
│   ├── server_url (String) — e.g. "http://10.165.44.28:11434"
│   ├── model_name (String) — e.g. "bge-m3"
│   ├── context_length (Integer)
│   ├── context_length_manual (Boolean)
│   ├── dimensions (Integer)
│   ├── dimensions_manual (Boolean)
│   ├── batch_size (Integer) — 动态计算或手动设定
├── local_haha_code_config (JSON) — 本地 haha-code 配置
│   ├── anthropic_base_url (String) — e.g. "http://10.165.25.39:11434/v1"
│   ├── anthropic_model (String) — 默认主模型，从 10.165.25.39 下拉选择
│   ├── anthropic_sonnet_model (String) — Sonnet 模型，从 10.165.25.39 下拉选择
│   ├── anthropic_haiku_model (String) — Haiku 模型，从 10.165.25.39 下拉选择
│   ├── anthropic_auth_token (String) — Ollama 兼容端点使用 "ollama"
├── updated_at (DateTime)
├── updated_by (Integer, FK → users.id)
```

### 嵌入维度适配

- `local_embedding_config` 中增加 `dimensions` 和 `dimensions_manual` 字段
- 切换嵌入模型时，后端比较新维度与当前已存储的维度：
  - 维度相同 → 无需处理，直接切换
  - 维度不同 → 前端弹确认对话框："切换嵌入模型将导致所有已有索引失效，需要重新解析和索引所有招标文件。是否继续？"
  - 管理员确认 → 标记所有 `Task` 索引状态为 `needs_reindex`
- 运行时防护：`embedding.py` 检查当前配置维度与请求维度是否一致，不一致则拒绝并提示重建索引

---

## 2. 后端 API 与服务层

### 新增 API 端点

```
server/app/routers/config.py (新文件)

GET  /api/admin/config           — 获取当前完整配置
PUT  /api/admin/config           — 更新配置（全局保存，立即生效）
GET  /api/admin/config/ollama/models?server_url=xxx  — 查询 Ollama 服务器可用模型列表
GET  /api/admin/config/ollama/info?server_url=xxx&model=xxx  — 查询模型详情（context_length 等）
GET  /api/admin/config/ollama/test?server_url=xxx&model=xxx  — 测试模型连通性
```

所有端点仅 admin 角色可访问。

### ModelConfigService

```
server/app/services/model_config_service.py (新文件)

class ModelConfigService:
    get_current_config() → dict
        # 从 DB 读取当前配置，缓存到内存
        # 返回: mode, llm_config, embedding_config, haha_code_config
        # 包含动态计算的: context_length, max_input_tokens, batch_size

    save_config(config, user_id) → dict
        # 1. 写入数据库（覆盖单条记录）
        # 2. 根据 mode 组装完整配置 dict
        # 3. 同步写入 config/settings.yaml
        # 4. 通知 haha-code /config API 热更新
        # 5. 如果嵌入维度变更 → 标记需要重建索引
        # 6. 清除内存缓存

    query_ollama_models(server_url) → list[str]
        # 调用 Ollama /api/tags 获取已安装模型列表

    query_ollama_model_info(server_url, model_name) → dict
        # 调用 Ollama /api/show 获取 context_length、dimensions 等参数
        # 如果查询失败 → 返回 None，前端提示手动填写

    calculate_embedding_batch_size(context_length) → int
        # 可用空间 ≈ context_length - safety_margin
        # 每条文本占用 ≈ avg_text_length (500 tokens)
        # batch_size = max(1, floor(可用空间 / avg_text_length))
        # 上限不超过 50

    test_ollama_connection(server_url, model_name) → bool
        # 发送简单请求测试连通性
```

### 现有代码改造点

| 文件 | 改造内容 |
|------|----------|
| `src/extractor/base.py` | `call_qwen()` 的 settings 参数改为从 `ModelConfigService` 获取 |
| `src/extractor/embedding.py` | `_call_embedding_api()` 同上，batch_size 从动态配置获取 |
| `src/reviewer/reviewer.py` | `llm_review_clause()` 分批逻辑的 max_tokens 从动态配置获取 |
| `src/reviewer/smart_reviewer.py` | `call_smart_review()` 连接地址从动态配置获取 |
| `src/config.py` | 启动时从 DB 加载配置写入 yaml，后续调用者从 Service 获取 |
| `server/app/tasks/review_task.py` | 任务启动时查询一次 ModelConfigService 获取当前配置，整个任务期间使用该配置 |
| `haha-code/server.ts` | 新增 `/config` POST 端点接收配置热更新 |

---

## 3. 前端管理员配置界面

### 路由与权限

- 路由：`/admin/config`（在 router/index.ts 的 SidebarLayout children 中新增）
- 权限：`meta: { requiresAdmin: true }`
- 导航：在 AppSidebar.vue 中为 admin 用户新增"模型配置"入口（使用 `Settings` 或 `Server` 图标 from lucide-vue-next）

### 页面布局

使用与 `AdminUsersView.vue` 一致的风格：
- `p-6` 外层容器
- `text-xl font-bold` 标题
- `bg-surface` 卡片容器
- `rounded-lg shadow` 圆角阴影
- `text-sm` 正文字号
- Tailwind oklch 主题色变量（primary, surface, border, text-primary 等）

### 界面区块

**运行模式切换：**
- 两个选项：云端模式 (DashScope) / 本地模式 (Ollama)
- 选择云端时隐藏所有本地配置区块，显示当前云端配置摘要（只读）
- 选择本地时展开三个配置区块

**LLM 配置区块：**
- 服务器地址（文本输入，默认 http://10.165.25.39:11434）
- 连接测试按钮 → 成功后自动拉取模型列表
- 模型选择（下拉框，数据源为 Ollama `/api/tags`）
- 上下文长度（自动获取显示绿色标记，查询失败时显示手动输入框）
- 最大输出 Tokens、Temperature（可编辑输入框）

**Embedding 配置区块：**
- 服务器地址（文本输入，默认 http://10.165.44.28:11434）
- 连接测试按钮 → 成功后自动拉取模型列表
- 模型选择（下拉框，数据源为 Embedding Ollama `/api/tags`）
- 上下文长度（自动获取优先，手动兜底）
- 嵌入维度（自动获取优先，手动兜底）
- Batch Size（动态计算显示，不可手动编辑）

**Smart Review 配置区块：**
- LLM 服务器地址（Anthropic 兼容端点，如 http://10.165.25.39:11434/v1）
- Sonnet 模型（下拉框，从 10.165.25.39 `/api/tags` 拉取，对应 ANTHROPIC_DEFAULT_SONNET_MODEL）
- Haiku 模型（下拉框，从 10.165.25.39 `/api/tags` 拉取，对应 ANTHROPIC_DEFAULT_HAIKU_MODEL）
- 默认模型（下拉框，从 10.165.25.39 `/api/tags` 拉取，对应 ANTHROPIC_MODEL）

**维度变更警告：**
- 保存前比较嵌入维度，变更时弹确认对话框
- 使用 `warning` 色系（oklch 主题色中的 warning/warning-light）

**保存按钮：**
- `bg-primary text-white rounded-md`，与 AdminUsersView 的创建按钮风格一致

### 交互流程

1. 选择模式 → 云端隐藏本地配置 / 本地展开配置区块
2. 输入服务器地址 → 点击连接测试 → 成功则自动拉取模型列表 → 失败则显示错误信息
3. 选择模型 → 自动查询 `/api/show` → 填充 context_length、dimensions → 查询失败显示手动输入框
4. 保存前检查嵌入维度 → 变更则弹确认对话框
5. 保存 → PUT `/api/admin/config` → DB写入 + 同步yaml + 通知haha-code → 提示"配置已生效"

---

## 4. LLM 审评分批逻辑（核心）

### 分批审评流程

```
条款审评流程（本地模式，小上下文）:

1. 构建条款的 bid_context（招标文件相关段落）
2. 估算 bid_context 的 token 数量
3. 如果 token 数 ≤ max_input_tokens → 单次审评（现有流程不变）
4. 如果 token 数 > max_input_tokens → 分批审评：
   a. 将 bid_context 拆分为多个批次（保留章节边界优先）
   b. 第1批：发送条款 + 第1批上下文 → review_clause_intermediate → summary_1, candidates_1
   c. 第2批：发送条款 + 第2批上下文 + summary_1 + candidates_1 → intermediate → summary_2, candidates_2
   d. ... 重复直到所有批次处理完毕
   e. 最终批：条款 + accumulated_summary + all_candidates → review_clause_final → 最终审评结论
```

### 关键参数动态计算

```
max_input_tokens = context_length - max_output_tokens - safety_margin

其中:
- context_length: 从 ModelConfigService 获取（自动查询或手动设定）
- max_output_tokens: 配置中的 max_output_tokens（如 65536 云端 / 8192 本地）
- safety_margin: 固定 500 tokens（预留 prompt 模板开销）
```

### 分批拆分策略

```
batch_bid_context(context_paragraphs, max_input_tokens):
  1. 先计算条款本身 + prompt模板 的 token 占用
  2. 剩余空间 = max_input_tokens - clause_tokens - prompt_tokens - safety_margin
  3. 尝试按章节边界分组，每组不超过剩余空间
  4. 无法按章节分时，按段落逐个累积，超过限制时断开
  5. 每批至少包含1个段落（即使超限也要发送，避免无限循环）
```

### Embedding 分批逻辑

```
calculate_embedding_batch_size(context_length, avg_text_length=500):
  1. 每批可用空间 ≈ context_length - safety_margin (200 tokens)
  2. 每条文本占用 ≈ avg_text_length tokens
  3. batch_size = max(1, floor(可用空间 / avg_text_length))
  4. 上限不超过 50（避免单次请求过大）
```

### 改造的文件清单

| 文件 | 改造内容 |
|------|----------|
| `src/extractor/base.py` | `batch_paragraphs()` 的 max_tokens 参数改为从配置动态获取 |
| `src/reviewer/reviewer.py` | `llm_review_clause()` 新增分批逻辑：估算 token → 超限时分批 → intermediate/final 流程 |
| `src/reviewer/bid_context.py` | `build_clause_bid_contexts()` 返回的段落列表需支持按 token 拆分 |
| `src/extractor/embedding.py` | `batch_size` 从配置动态获取而非 yaml 固定值 |
| `src/reviewer/tender_indexer.py` | `MAX_CHARS_PER_BATCH` 改为根据 context_length 动态计算 |
| `config/prompts/review_clause_intermediate.txt` | 已支持 prev_summary 和 prev_candidates |
| `config/prompts/review_clause_final.txt` | 已支持 accumulated_summary 和 all_candidates |

---

## 5. 配置同步与 haha-code 热更新

### 数据库 → settings.yaml 同步

```
配置保存流程:
1. 管理员 PUT /api/admin/config → ModelConfigService.save_config()
2. 写入 system_config 表（覆盖单条记录）
3. 根据 mode 组装完整的配置 dict:
   - cloud: 直接使用 cloud_config JSON
   - local: 将 local_*_config 转换为 settings.yaml 格式
4. 写入 config/settings.yaml（保持与现有格式一致）
5. 通知 haha-code 热更新
6. 清除内存缓存
```

settings.yaml 本地模式格式示例：
```yaml
api:
  base_url: "http://10.165.25.39:11434/v1"
  api_key: "ollama"
  model: "qwen2.5:14b"
  temperature: 0.1
  max_output_tokens: 8192
  context_length: 32768
  enable_thinking: false
  retry: 3
  timeout: 600

embedding:
  base_url: "http://10.165.44.28:11434/v1"
  model: "bge-m3"
  dimensions: 1024
  batch_size: 3
  context_length: 8192
  max_workers: 4
  similarity_threshold: 0.5
```

### haha-code 热更新

```
POST /config
{
  "mode": "local",
  "anthropic_base_url": "http://10.165.25.39:11434/v1",
  "anthropic_auth_token": "ollama",
  "anthropic_model": "qwen2.6:14b",
  "anthropic_haiku_model": "qwen2.5:7b",
  "anthropic_sonnet_model": "qwen2.5:14b"
}

haha-code/server.ts 改造:
- 新增 /config POST 端点
- 收到配置后更新内存中的环境变量映射
- 下次 /review 请求时使用新配置
- 配置变更日志记录
```

### Celery Worker 配置刷新

```
Celery 任务中的配置获取:
- review_task.py 在任务开始时调用 ModelConfigService.get_current_config()
- 整个任务执行期间使用这次获取的配置（不会中途切换）
- 配置通过 task 参数传入，不依赖全局变量
- 正在运行的任务自然使用旧配置完成
```

### 启动初始化

```
应用启动流程 (server/app/main.py):
1. 启动时检查 system_config 表是否有记录
2. 如果没有 → 从 config/settings.yaml 读取，作为 cloud_config 初始化写入数据库
3. 如果有 → 从数据库读取当前配置，同步写入 settings.yaml（确保文件与 DB 一致）
```