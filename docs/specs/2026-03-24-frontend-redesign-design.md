# 前端界面重构设计文档

## 目标

将现有的简单 header + 内容区布局重构为侧边导航栏 + 状态驱动的招标解读工作流，提升交互体验和文件管理能力。

## 架构概览

- 去掉顶部 header，改为左侧 200px 文字式侧边导航栏
- 侧栏分为两个区域：**招标解读**（主功能）和 **文档管理**（4个文件库栏）
- 用户信息移至侧栏底部，点击头像弹出菜单（管理员：用户管理+退出；普通用户：退出）
- 招标解读采用**单任务、状态替换**模式，6个阶段依次切换

## 技术栈

- Vue 3 + Composition API + TypeScript
- Pinia 状态管理
- Tailwind CSS
- 复用现有 API 客户端、SSE composable、批注系统

---

## 1. 页面结构

### 1.1 整体布局

```
┌─────────────────────────────────────────────────┐
│ ┌──────────┬──────────────────────────────────┐  │
│ │ 侧边栏    │        内容区                     │  │
│ │ 200px    │        flex: 1                   │  │
│ │          │                                  │  │
│ │ 招标解读  │  （根据当前路由渲染不同视图）       │  │
│ │ ──────── │                                  │  │
│ │ 文档管理  │                                  │  │
│ │  招标文件 │                                  │  │
│ │  解析报告 │                                  │  │
│ │  文件格式 │                                  │  │
│ │  资料清单 │                                  │  │
│ │          │                                  │  │
│ │ ──────── │                                  │  │
│ │ 👤 用户   │                                  │  │
│ └──────────┴──────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### 1.2 侧边栏组件 `AppSidebar.vue`

**结构：**
- 顶部：系统名称 "招标分析系统"
- 第一栏：📝 招标解读（与下方用分割线隔开）
- 分割线
- 分组标签："文档管理"
- 第二栏：📁 招标文件
- 第三栏：📊 解析报告
- 第四栏：📐 文件格式
- 第五栏：📋 资料清单
- 底部（margin-top: auto）：用户头像+名称+角色

**交互：**
- 当前激活栏高亮（左侧 3px 紫色边框 + 浅紫背景）
- 登录后默认进入"招标解读"
- 点击头像弹出下拉菜单：
  - 管理员：显示"用户管理"和"退出登录"
  - 普通用户：仅显示"退出登录"
  - 点击"用户管理"导航到 `/admin/users`
  - 点击"退出登录"清除 token 并跳转到 `/login`

### 1.3 布局组件变更

**删除** `DefaultLayout.vue` 中的顶部 header。

**新建** `SidebarLayout.vue` 作为主布局：
```
<div class="flex h-screen">
  <AppSidebar />
  <main class="flex-1 overflow-auto bg-gray-50">
    <router-view />
  </main>
</div>
```

---

## 2. 路由设计

| 路由 | 视图 | 说明 |
|------|------|------|
| `/login` | LoginView | 登录页（无侧栏） |
| `/` | BidAnalysisView | 招标解读（默认页） |
| `/files/bid-documents` | FileManagerView | 招标文件列表 |
| `/files/reports` | FileManagerView | 解析报告列表 |
| `/files/formats` | FileManagerView | 文件格式列表 |
| `/files/checklists` | FileManagerView | 资料清单列表 |
| `/files/:fileType/:id/preview` | FilePreviewView | 文件预览页 |
| `/admin/users` | AdminUsersView | 用户管理（管理员） |

**说明：**
- `FileManagerView` 是通用组件，通过路由参数 `fileType` 区分显示哪种文件
- 文件预览页复用现有的预览能力

---

## 3. 招标解读工作流（BidAnalysisView）

### 3.1 状态机

**状态转换表：**

| 当前状态 | 事件 | 下一状态 |
|----------|------|----------|
| `upload` | 文件上传成功 | `processing` |
| `processing` | SSE 收到 step='review' | `review` |
| `processing` | SSE 收到 step='failed' | `processing`（显示错误+重试） |
| `review` | 点击"跳过人工审核" | `generating` |
| `review` | 点击"提交修改" | `reprocessing` |
| `reprocessing` | SSE 收到 step='review' | `review` |
| `reprocessing` | SSE 收到 step='failed' | `reprocessing`（显示错误） |
| `generating` | SSE 收到 step='completed' | `preview` |
| `generating` | SSE 收到 step='failed' | `generating`（显示错误+重试） |
| `preview` | 点击"开始新的解读" | `upload` |

**说明：** `processing` 和 `generating` 共用 `ProcessingStage.vue` 组件，通过 SSE 返回的 `step` 字段判断当前高亮哪些步骤指示器。错误不是独立状态，而是 `processing`/`generating`/`reprocessing` 内的条件分支（通过 `error` 字段控制）。

6个前端阶段，内容区根据当前阶段完全替换：

| 阶段 | 说明 | 触发条件 |
|------|------|----------|
| `upload` | 初始上传界面 | 默认状态 / 完成后重置 |
| `processing` | 解析+提取进度 | 文件上传成功后 |
| `review` | 人工审核界面 | 提取完成，后端 status='review' |
| `reprocessing` | 批注修改进度 | 提交批注后 |
| `generating` | 生成进度 | 跳过审核或批注修改完成后 |
| `preview` | 预览+下载界面 | 生成完成 |

### 3.2 状态 — upload（上传）

**界面：** 居中显示拖拽上传区域
- 标题："招标文件深度解析"
- 副标题："上传招标文件，AI智能解析生成分析报告"
- 拖拽区域，支持点击选择文件
- 支持格式提示：".doc / .docx / .pdf"

**行为：**
- 用户拖入或选择文件 → 调用 `POST /api/tasks` 上传
- 上传成功 → 后端 dispatch Celery 任务 → 切换到 `processing` 状态
- 上传失败 → 在上传区域下方显示错误提示

### 3.3 状态 — processing（解析中）

**界面：**
- 文件名 + 状态标签（"解析中"）
- 进度条（0-100%，渐变紫色）
- 当前步骤文字（如"正在提取模块C: 评标办法..."）
- 步骤指示器：解析 → 索引 → 提取 → 生成（已完成绿色、进行中黄色、待处理灰色）

**行为：**
- 通过 SSE 连接 `GET /api/tasks/{id}/progress` 获取实时进度
- 复用现有 `useSSE` composable
- SSE 收到 `step='review'` → 切换到 `review` 阶段
- 如果任务失败 → 显示错误信息 + "重试"按钮

**关键变更 — 人工审核插入点：**

当前后端 pipeline 流程是 `解析→索引→提取→生成` 连续执行。需要在**提取完成、生成之前**插入一个暂停点。

**Celery task 行为：**
1. `run_pipeline` task 执行完提取后，发出最后一个 `update_state(state='PROGRESS', meta={step: 'review', progress: 90})`
2. 将 DB 中 task.status 设为 `review`，task.progress 设为 90
3. Celery task 返回 SUCCESS（释放 worker）
4. SSE 端点检测到 Celery SUCCESS 后，查询 DB task.status：
   - 如果 status='review'，发送 `{step: 'review', progress: 90}` 而非 `{step: 'completed', progress: 100}`
   - 如果 status='completed'，正常发送完成事件
5. 前端收到 `step='review'` 后切换到审核界面

**继续生成：**
- 用户操作后前端调用 `POST /api/tasks/{id}/continue`
- 后端 dispatch 新的 `run_generate` Celery task
- 更新 task.celery_task_id 为新 task ID，task.status 设为 `generating`
- 前端重新连接 SSE 监听新 task 的进度

### 3.4 状态 — review（人工审核）

**界面：** 左右分栏
- 左侧 1/3：招标原文（只读滚动浏览）
- 右侧 2/3：解析结果 + 批注交互

**右侧结构：**
- 顶部 Tab 栏：按模块切换（A 基本信息、B 资格要求、C 评标办法、D 废标条款...）
  - 有批注的模块 Tab 上显示黄色圆点提示
- 内容区：当前模块的提取结果以**表格**形式展示
  - 每张表格底部有"对此表批注"按钮
  - 点击后在表格下方展开批注输入框
  - 已有批注的表格显示黄色边框高亮，批注内容展示在表格下方
  - 每条批注显示用户头像、用户名、时间、内容，右侧有删除按钮
  - 可对同一表格追加多条批注
- 底部操作栏：
  - 左侧：统计信息（"共 N 个模块，M 条待处理批注"）
  - 右侧：两个按钮
    - "跳过人工审核"（白色）→ 调用 `POST /api/tasks/{id}/continue` → 切换到 `generating` 阶段
    - "提交修改 (M条批注)"（紫色）→ 调用 `POST /api/tasks/{id}/bulk-reextract` → 切换到 `reprocessing`

**批注粒度：** 以模块/表格为单位批注。Annotation 的 `section_id` 字段对应模块 key（如 `module_a`），`row_index` 始终为 null。批注内容是对整个表格的修改意见。

**数据来源：**
- 原文：调用 `GET /api/tasks/{id}/parsed` 获取段落列表
- 解析结果：从 `Task.extracted_data` (JSONB) 获取（现有 `GET /api/tasks/{id}` 已返回）
- 批注：复用现有 `annotations` API

### 3.5 状态 — reprocessing（修改中）

**界面：** 与 processing 类似的进度展示
- 提示文字："正在根据批注重新提取..."
- 进度条

**行为：**
- 调用 `POST /api/tasks/{id}/bulk-reextract`（新端点，批量重提取所有有批注的模块）
- 后端 dispatch 新的 Celery task，对每个有待处理批注的模块调用 reextract
- 完成后将 task.status 设回 `review`，更新 task.extracted_data
- SSE 收到 `step='review'` → 切换回 `review` 阶段，用户可继续审核
- 如果用户满意 → 点击"跳过人工审核"进入生成

### 3.6 状态 — preview（预览下载）

**界面：**
- 顶部 Tab 栏：3个文件切换
  - 📊 分析报告
  - 📐 投标文件格式
  - 📋 资料清单
- 内容区：当前 Tab 对应文件的预览渲染
- 底部操作栏：
  - 左侧：文件名 + 大小信息
  - 右侧：
    - "下载当前"按钮 → 调用 `GET /api/tasks/{id}/download/{file_type}`
    - "全部下载"按钮（绿色）→ 依次下载3个文件（或后端打包 zip）
- 预览区下方："开始新的解读 →" 按钮 → 重置到 `upload` 状态

**文件自动入库：**
- 任务完成后，生成的3个文件自动出现在对应的文件管理栏中
- 上传的原始文件自动出现在"招标文件"栏中
- 无需用户手动操作

---

## 4. 文件管理视图（FileManagerView）

### 4.1 通用列表界面

四个文件栏共用同一个视图组件 `FileManagerView.vue`，通过路由参数区分文件类型。

**界面：**
- 顶部：栏目标题 + 文件总数 + 搜索框
- 内容区：文件卡片列表
  - 每张卡片：图标 + 文件名 + 文件大小 + 创建时间 + 来源任务名
  - 右侧操作按钮：预览、下载、删除
- 底部：分页器

| 栏目 | file_type 参数 | 图标 | 数据来源 |
|------|---------------|------|----------|
| 招标文件 | `bid-documents` | 📁 | 原始上传文件 |
| 解析报告 | `reports` | 📊 | generated_files (type=report) |
| 文件格式 | `formats` | 📐 | generated_files (type=format) |
| 资料清单 | `checklists` | 📋 | generated_files (type=checklist) |

### 4.2 文件操作

- **预览**：导航到 `/files/:fileType/:id/preview`，打开文件预览页面
  - 预览策略：服务端使用 python-docx 将 .docx 转为 HTML 片段返回，前端直接渲染
  - 对于原始上传的 .doc/.pdf 文件，仅提供下载，不提供在线预览
- **下载**：调用 `GET /api/files/{file_type}/{id}/download`，浏览器下载文件
- **删除**：确认弹窗后调用 `DELETE /api/files/{file_type}/{id}`，从列表中移除
- **搜索**：后端支持 `q` 查询参数，对文件名进行模糊搜索

### 4.3 空状态

无文件时显示："暂无文件，请在「招标解读」中上传并完成解析"

---

## 5. 新增/变更 API

### 5.1 后端新增

#### `POST /api/tasks/{id}/continue`
触发生成阶段（跳过审核或审核完成后调用）。
- **Guard**：仅当 task.status == 'review' 时允许调用，否则返回 409
- **Request body**：无（空 POST）
- **行为**：
  1. dispatch `run_generate` Celery task
  2. 更新 task.celery_task_id 为新 task ID
  3. 更新 task.status = 'generating'
- **Response**：`{"task_id": "...", "status": "generating"}`
- **幂等性**：重复调用不会重复 dispatch（检查 status 不为 review 时返回 409）

#### `POST /api/tasks/{id}/bulk-reextract`
批量重新提取所有有待处理批注的模块。
- **Guard**：仅当 task.status == 'review' 时允许
- **Request body**：无（自动查找所有 status='pending' 的 annotations）
- **行为**：
  1. 查询该 task 下所有 pending annotations，按 section_id (module key) 分组
  2. dispatch `run_bulk_reextract` Celery task
  3. 更新 task.celery_task_id、task.status = 'reprocessing'
- **Response**：`{"task_id": "...", "status": "reprocessing", "modules": ["module_a", "module_c"]}`

#### `GET /api/tasks/{id}/parsed`
获取原文段落数据（审核界面左侧面板用）。
- **Response**：`{"paragraphs": [{"index": 0, "text": "...", "style": "heading1"}, ...]}`
- 从 `intermediate/{task_id}/parsed.json` 读取

#### `GET /api/files`
文件库列表，支持 file_type 筛选、分页、搜索。
- **Query params**：`file_type` (bid-documents|reports|formats|checklists), `page`, `page_size`, `q` (文件名模糊搜索)
- **数据来源**：
  - `bid-documents`：查询 tasks 表（status=completed），返回 filename、file_size、created_at、task_id
  - `reports|formats|checklists`：查询 generated_files 表（file_type 对应），返回 filename、file_size、created_at、task_id
- **Response schema**（统一格式）：
  ```json
  {
    "items": [{"id": "...", "filename": "...", "file_size": 1234, "created_at": "...", "task_name": "..."}],
    "total": 10, "page": 1, "page_size": 20
  }
  ```
  - 其中 `id` 对 bid-documents 是 task UUID，对其他三种是 generated_file 的整数 ID

#### `GET /api/files/{file_type}/{id}/preview`
获取文件预览 HTML。
- 仅支持 generated files (.docx)，使用 python-docx 转 HTML
- bid-documents 不支持预览，返回 501

#### `GET /api/files/{file_type}/{id}/download`
下载文件（StreamingResponse）。

#### `DELETE /api/files/{file_type}/{id}`
删除文件。
- bid-documents：不允许单独删除上传文件（关联到 task），返回 403
- generated files：删除文件记录和磁盘文件

### 5.2 Task status 新增值

在现有 status 枚举中新增 `review` 和 `generating` 状态：
- `pending → parsing → indexing → extracting → review → generating → completed`
- `review`：提取完成，等待人工审核（Celery task 已结束，worker 已释放）
- `generating`：生成阶段（由 `run_generate` Celery task 执行）

### 5.3 Pipeline 变更

**`run_pipeline` task 修改：**
1. 执行：解析 → 索引 → 提取
2. 提取完成后：发出 `update_state(state='PROGRESS', meta={step: 'review', progress: 90})`
3. 设置 DB：task.status = 'review'，task.progress = 90
4. 返回 SUCCESS（释放 worker）

**`run_generate` task（新增）：**
1. 从 task.extracted_data 读取提取结果
2. 执行：生成分析报告 + 投标文件格式 + 资料清单
3. 记录 generated_files
4. 设置 DB：task.status = 'completed'，task.progress = 100

**`run_bulk_reextract` task（新增）：**
1. 查询所有 pending annotations，按 module key 分组
2. 对每个模块调用 reextract，更新 task.extracted_data
3. 将处理过的 annotations 标记为 resolved
4. 设置 DB：task.status = 'review'

**SSE 端点修改：**
- Celery task 返回 SUCCESS 后，额外检查 DB task.status
- 如果 status='review'，发送 `{step: 'review', progress: 90}` 而非 completed
- 如果 status='completed'，正常发送完成事件
- 如果 status='generating'/'reprocessing'，使用新的 celery_task_id 继续追踪

---

## 6. 前端文件变更清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `web/src/layouts/SidebarLayout.vue` | 新主布局（侧栏+内容区） |
| `web/src/components/AppSidebar.vue` | 侧边导航栏组件 |
| `web/src/components/UserMenu.vue` | 头像下拉菜单组件 |
| `web/src/views/BidAnalysisView.vue` | 招标解读主视图（状态机驱动） |
| `web/src/views/FileManagerView.vue` | 文件管理通用视图 |
| `web/src/views/FilePreviewView.vue` | 文件预览页 |
| `web/src/components/UploadStage.vue` | 上传阶段组件 |
| `web/src/components/ProcessingStage.vue` | 进度阶段组件（processing/generating/reprocessing 三种阶段共用，通过 prop `mode` 区分显示文案和步骤指示器高亮） |
| `web/src/components/ReviewStage.vue` | 人工审核阶段组件 |
| `web/src/components/PreviewStage.vue` | 预览下载阶段组件 |
| `web/src/components/FileCard.vue` | 文件卡片组件（文件管理用） |
| `web/src/api/files.ts` | 文件管理 API |
| `web/src/stores/analysisStore.ts` | 招标解读状态管理 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `web/src/router/index.ts` | 新增路由，默认布局改为 SidebarLayout |
| `web/src/api/tasks.ts` | 新增 `continue`、`parsed`、`bulkReextract` 方法 |
| `web/src/types/task.ts` | Task status 新增 `review` 值 |

### 可删除/废弃文件

| 文件 | 说明 |
|------|------|
| `web/src/layouts/DefaultLayout.vue` | 被 SidebarLayout 替代 |
| `web/src/views/DashboardView.vue` | 被 BidAnalysisView 替代 |
| `web/src/views/TaskDetailView.vue` | 功能合并到 BidAnalysisView |
| `web/src/components/TaskList.vue` | 不再需要任务列表 |

### 复用文件（保留不变或小改动）

| 文件 | 说明 |
|------|------|
| `web/src/components/FileUpload.vue` | 复用拖拽上传组件 |
| `web/src/components/TaskProgress.vue` | 复用进度条组件 |
| `web/src/components/SectionTable.vue` | 复用表格渲染组件 |
| `web/src/components/AnnotationPanel.vue` | 改造为表格级批注（section_id=module key, row_index=null） |
| `web/src/components/ModuleNav.vue` | 改造为 Tab 栏形式 |
| `web/src/composables/useSSE.ts` | 复用 SSE 连接 |
| `web/src/composables/useAnnotation.ts` | 复用批注逻辑 |
| `web/src/views/AdminUsersView.vue` | 保留用户管理页 |

---

## 7. 后端文件变更清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `server/app/routers/files.py` | 文件管理 CRUD API |
| `server/app/services/file_service.py` | 文件查询/删除业务逻辑 |
| `server/app/tasks/generate_task.py` | 独立的生成阶段 Celery task（`run_generate`） |
| `server/app/tasks/bulk_reextract_task.py` | 批量重提取 Celery task（`run_bulk_reextract`） |

### 修改文件

| 文件 | 变更 |
|------|------|
| `server/app/tasks/pipeline_task.py` | 提取完成后暂停，status 设为 review |
| `server/app/routers/tasks.py` | 新增 `/continue`、`/parsed`、`/bulk-reextract` 端点 |
| `server/app/models/task.py` | status 枚举新增 `review` |
| `server/app/main.py` | 注册 files router |
| `server/app/tasks/celery_app.py` | include 新增 generate_task、bulk_reextract_task 模块 |

---

## 8. 状态管理 — analysisStore

```typescript
interface AnalysisState {
  stage: 'upload' | 'processing' | 'review' | 'reprocessing' | 'generating' | 'preview'
  currentTaskId: string | null
  progress: number
  currentStep: string
  extractedData: Record<string, any> | null
  error: string | null
}
```

**核心逻辑：**
- `startUpload(file)` → 调用上传 API → 设置 taskId → stage='processing' → 连接 SSE
- SSE 收到 `step='review'` → stage='review' → 加载 extracted_data + parsed data
- `skipReview()` → 调用 continue API → stage='generating' → 重新连接 SSE
- `submitAnnotations()` → 调用 bulk-reextract API → stage='reprocessing' → 重新连接 SSE
- SSE 收到 `step='review'`（reprocessing 完成）→ stage='review'
- SSE 收到 `step='completed'` → stage='preview'
- `resetToUpload()` → 清空状态 → stage='upload'

**页面刷新恢复：**
- analysisStore 初始化时，将 `currentTaskId` 持久化到 `localStorage`
- 页面加载时检查 localStorage 中是否有 taskId
- 如果有，调用 `GET /api/tasks/{id}` 查询 task.status
- 根据 status 恢复到对应的 stage（review→review, generating→generating, completed→preview, 其他→processing）
- 重新连接 SSE（如果是进行中的状态）

---

## 9. 设计约束与注意事项

1. **单任务模式**：每个用户同一时间只处理一个文件，状态替换而非叠加。多用户互不影响。
2. **文件自动入库**：任务完成后，上传文件和生成文件自动出现在对应栏目，无需手动操作
3. **后四栏为全局文件库**：汇总所有历史任务的文件，按时间倒序排列
4. **后四栏不支持独立上传**：文件只通过"招标解读"流程产生
5. **Pipeline 暂停机制**：需要修改后端 Celery task，在提取和生成之间插入暂停点
6. **登录页不显示侧栏**：LoginView 使用独立布局，不包含 SidebarLayout
7. **响应式**：侧栏在小屏幕上可考虑折叠，但非 MVP 优先级
