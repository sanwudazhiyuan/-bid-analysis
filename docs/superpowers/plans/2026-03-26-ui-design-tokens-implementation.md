# UI 设计令牌与色彩体系实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将所有前端组件的硬编码 Tailwind 颜色类替换为语义化设计令牌，Emoji 图标替换为 Lucide Icons，统一蓝灰色系风格。

**Architecture:** 在 `main.css` 中用 Tailwind v4 `@theme` 定义 CSS 变量作为设计令牌，所有组件通过 `bg-primary`、`text-text-secondary` 等语义类引用。安装 `lucide-vue-next` 替换 Emoji 图标。纯替换操作，不改动组件结构或业务逻辑。

**Tech Stack:** Vue 3, Tailwind CSS v4.2.2 (`@theme`), lucide-vue-next

**Spec:** `docs/superpowers/specs/2026-03-25-ui-design-tokens-and-color-system-design.md`

---

## Chunk 1: 基础设施

### Task 1: 安装 lucide-vue-next 依赖

**Files:**
- Modify: `web/package.json`

- [ ] **Step 1: 安装依赖**

```bash
cd web && npm install lucide-vue-next
```

- [ ] **Step 2: 验证安装成功**

```bash
cd web && node -e "require('lucide-vue-next')"
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add web/package.json web/package-lock.json
git commit -m "chore: add lucide-vue-next icon library"
```

---

### Task 2: 建立设计令牌

**Files:**
- Modify: `web/src/assets/main.css`

- [ ] **Step 1: 替换 main.css 内容**

将 `web/src/assets/main.css` 的全部内容替换为：

```css
@import "tailwindcss";

@theme {
  /* 主色 - 蓝色系 */
  --color-primary: oklch(45% 0.15 250);
  --color-primary-hover: oklch(40% 0.17 250);
  --color-primary-light: oklch(95% 0.03 250);
  --color-primary-foreground: oklch(98% 0 0);

  /* 中性色 */
  --color-background: oklch(98.5% 0.005 264);
  --color-surface: oklch(100% 0 0);
  --color-border: oklch(91% 0.01 264);
  --color-text-primary: oklch(20% 0.02 264);
  --color-text-secondary: oklch(45% 0.02 264);
  --color-text-muted: oklch(60% 0.015 264);

  /* 语义色 */
  --color-success: oklch(55% 0.17 145);
  --color-success-light: oklch(95% 0.03 145);
  --color-success-foreground: oklch(30% 0.1 145);
  --color-warning: oklch(70% 0.15 75);
  --color-warning-light: oklch(95% 0.04 75);
  --color-warning-foreground: oklch(35% 0.1 75);
  --color-danger: oklch(55% 0.2 27);
  --color-danger-light: oklch(95% 0.03 27);
  --color-danger-foreground: oklch(30% 0.12 27);

  /* 交互/信息色 */
  --color-info: oklch(55% 0.18 250);
  --color-info-light: oklch(96% 0.02 250);
  --color-info-foreground: oklch(30% 0.12 250);

  /* 高亮色 */
  --color-highlight: oklch(90% 0.08 85);
  --color-highlight-foreground: oklch(35% 0.1 75);
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-text-primary antialiased;
  }
}
```

- [ ] **Step 2: 验证构建**

```bash
cd web && npx vite build 2>&1 | head -20
```

Expected: 构建成功，无错误

- [ ] **Step 3: Commit**

```bash
git add web/src/assets/main.css
git commit -m "feat: add design tokens via Tailwind v4 @theme"
```

---

## Chunk 2: 布局与导航组件

### Task 3: SidebarLayout.vue

**Files:**
- Modify: `web/src/layouts/SidebarLayout.vue:8`

- [ ] **Step 1: 替换颜色类**

| 行 | 替换前 | 替换后 |
|----|--------|--------|
| 8 | `bg-gray-50` | `bg-background` |

- [ ] **Step 2: Commit**

```bash
git add web/src/layouts/SidebarLayout.vue
git commit -m "refactor(SidebarLayout): use design tokens"
```

---

### Task 4: AppSidebar.vue

**Files:**
- Modify: `web/src/components/AppSidebar.vue`

- [ ] **Step 1: 添加 Lucide 图标 import**

在 `<script setup>` 中添加：

```typescript
import { PenLine, FolderOpen, BarChart3, Ruler, ClipboardList } from 'lucide-vue-next'
```

- [ ] **Step 2: 替换 navItems 图标字段为组件引用**

```typescript
const navItems = [
  { path: '/', label: '招标解读', icon: PenLine, group: 'main' },
  { path: '/files/bid-documents', label: '招标文件', icon: FolderOpen, group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: BarChart3, group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: Ruler, group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: ClipboardList, group: 'files' },
]
```

- [ ] **Step 3: 替换模板中的图标渲染**

将两处 `<span>{{ item.icon }}</span>` 替换为：

```html
<component :is="item.icon" class="size-4" />
```

- [ ] **Step 4: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| aside 容器 (L21) | `bg-white border-r border-gray-200` | `bg-surface border-r border-border` |
| 标题 (L22) | `text-gray-800` | `text-text-primary` |
| 选中态 (L35,54) | `bg-purple-50 text-purple-700 font-medium border-l-[3px] border-purple-600` | `bg-primary-light text-primary font-medium border-l-[3px] border-primary` |
| 未选中态 (L36,55) | `text-gray-600 hover:bg-gray-50` | `text-text-secondary hover:bg-background` |
| 分隔线 (L43) | `bg-gray-200` | `bg-border` |
| 分类标题 (L44) | `text-gray-400` | `text-text-muted` |
| 底部边框 (L63) | `border-gray-200` | `border-border` |

- [ ] **Step 5: Commit**

```bash
git add web/src/components/AppSidebar.vue
git commit -m "refactor(AppSidebar): use design tokens + Lucide icons"
```

---

### Task 5: UserMenu.vue

**Files:**
- Modify: `web/src/components/UserMenu.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 头像容器 hover (L31) | `hover:bg-gray-100` | `hover:bg-background` |
| 头像圆 (L33) | `bg-purple-600` | `bg-primary` |
| 用户名 (L37) | `text-gray-800` | `text-text-primary` |
| 用户ID (L38) | `text-gray-400` | `text-text-muted` |
| 箭头 (L40) | `text-gray-400` | `text-text-muted` |
| 下拉菜单 (L45) | `bg-white border border-gray-200` | `bg-surface border border-border` |
| 菜单项 (L49) | `text-gray-600 hover:bg-gray-50` | `text-text-secondary hover:bg-background` |
| 退出按钮 (L55) | `text-red-500 hover:bg-gray-50` | `text-danger hover:bg-background` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/UserMenu.vue
git commit -m "refactor(UserMenu): use design tokens"
```

---

## Chunk 3: 小型共享组件

### Task 6: FileCard.vue

> **注意:** 此任务仅做颜色替换。FileCard 的图标渲染改造（`{{ icon }}` → `<component :is="icon" />`）在 Task 19 Step 3 中与 FileManagerView 一并完成，因为图标 prop 类型变更需要两个文件同步修改。

**Files:**
- Modify: `web/src/components/FileCard.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 容器 (L25) | `bg-white border border-gray-200` | `bg-surface border border-border` |
| 图标背景 (L26) | `bg-purple-50` | `bg-primary-light` |
| 文件名 (L30) | `text-gray-800` | `text-text-primary` |
| 文件信息 (L31) | `text-gray-400` | `text-text-muted` |
| 预览/下载按钮 (L37,41) | `border border-gray-300 ... text-gray-500 hover:bg-gray-50` | `border border-border ... text-text-muted hover:bg-background` |
| 删除按钮 (L45) | `border border-red-200 ... text-red-500 hover:bg-red-50` | `border border-danger/30 ... text-danger hover:bg-danger-light` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/FileCard.vue
git commit -m "refactor(FileCard): use design tokens"
```

---

### Task 7: AnnotationBadge.vue

**Files:**
- Modify: `web/src/components/AnnotationBadge.vue`

- [ ] **Step 1: 替换颜色类**

| 替换前 | 替换后 |
|--------|--------|
| `bg-yellow-100 text-yellow-800` | `bg-highlight text-highlight-foreground` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/AnnotationBadge.vue
git commit -m "refactor(AnnotationBadge): use design tokens"
```

---

### Task 8: AnnotationPanel.vue

**Files:**
- Modify: `web/src/components/AnnotationPanel.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 容器 (L28) | `bg-gray-50` | `bg-background` |
| 标题 (L29) | `text-gray-700` | `text-text-secondary` |
| 标注类型 (L36) | `text-gray-500` | `text-text-muted` |
| 标注内容 (L37) | `text-gray-700` | `text-text-secondary` |
| 已处理状态 (L38) | `text-green-500` | `text-success` |
| 处理失败状态 (L39) | `text-red-500` | `text-danger` |
| 删除按钮 (L41) | `text-red-400 hover:text-red-600` | `text-danger/70 hover:text-danger` |
| 输入框 focus (L46) | `focus:ring-2 focus:ring-blue-500` | `focus:ring-2 focus:ring-primary` |
| 添加按钮 (L47) | `bg-blue-600 ... hover:bg-blue-700` | `bg-primary ... hover:bg-primary-hover` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/AnnotationPanel.vue
git commit -m "refactor(AnnotationPanel): use design tokens"
```

---

### Task 9: DownloadCard.vue

**Files:**
- Modify: `web/src/components/DownloadCard.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 容器 (L27) | `bg-white border` | `bg-surface border` |
| 下载链接 (L29) | `text-blue-600` | `text-info` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/DownloadCard.vue
git commit -m "refactor(DownloadCard): use design tokens"
```

---

### Task 10: TaskProgress.vue

**Files:**
- Modify: `web/src/components/TaskProgress.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 进度条轨道 (L40) | `bg-gray-200` | `bg-border` |
| 进度条填充 (L41) | `bg-blue-600` | `bg-info` |
| 百分比文字 (L44) | `text-gray-500` | `text-text-muted` |
| 完成图标 (L48) | `text-green-500` | `text-success` |
| 活跃图标 (L49) | `text-blue-500` | `text-info` |
| 失败图标 (L50) | `text-red-500` | `text-danger` |
| 待处理图标 (L51) | `text-gray-300` | `text-border` |
| 步骤文字 (L52) | `text-gray-500` | `text-text-muted` |
| 详情文字 (L53) | `text-gray-400` | `text-text-muted` |
| 失败提示 (L59) | `bg-red-50 text-red-700` | `bg-danger-light text-danger-foreground` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/TaskProgress.vue
git commit -m "refactor(TaskProgress): use design tokens"
```

---

### Task 11: FileUpload.vue

**Files:**
- Modify: `web/src/components/FileUpload.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 拖拽激活 (L49) | `border-blue-500 bg-blue-50` | `border-primary bg-primary-light` |
| 默认边框 (L49) | `border-gray-300 hover:border-gray-400` | `border-border hover:border-text-muted` |
| 文字 (L51) | `text-gray-500` | `text-text-muted` |
| 上传按钮 (L54) | `bg-blue-600 ... hover:bg-blue-700` | `bg-primary ... hover:bg-primary-hover` |
| 错误文字 (L59) | `text-red-500` | `text-danger` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/FileUpload.vue
git commit -m "refactor(FileUpload): use design tokens"
```

---

### Task 12: ModuleNav.vue

**Files:**
- Modify: `web/src/components/ModuleNav.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 容器 (L20) | `bg-white border-r` | `bg-surface border-r` |
| 模块按钮 hover (L24) | `hover:bg-gray-100` | `hover:bg-background` |
| 选中模块 (L25) | `bg-blue-50 text-blue-700` | `bg-primary-light text-primary` |
| 未选中模块 (L25) | `text-gray-700` | `text-text-secondary` |
| 小节 hover (L31) | `hover:bg-gray-50` | `hover:bg-background` |
| 选中小节 (L32) | `text-blue-600` | `text-primary` |
| 未选中小节 (L32) | `text-gray-500` | `text-text-muted` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/ModuleNav.vue
git commit -m "refactor(ModuleNav): use design tokens"
```

---

### Task 13: SectionTable.vue

**Files:**
- Modify: `web/src/components/SectionTable.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 标题 (L43) | `text-gray-700` | `text-text-secondary` |
| 表头 (L48) | `bg-gray-50` | `bg-background` |
| 表头文字 (L49,52,53) | `text-gray-600` | `text-text-secondary` |
| 行悬停 (L60) | `hover:bg-blue-50` | `hover:bg-info-light` |
| 选中行 (L61) | `bg-yellow-50` | `bg-highlight` |
| 单元格文字 (L64) | `text-gray-700` | `text-text-secondary` |
| 复选框 (L69) | `text-blue-600` | `text-info` |
| 文本内容区 (L79) | `bg-gray-50 ... text-gray-700` | `bg-background ... text-text-secondary` |
| 备注 (L84) | `text-gray-400` | `text-text-muted` |

- [ ] **Step 2: 添加表格 overflow-x-auto**

在 `<table>` 标签 (L46) 外包裹一层 `<div class="overflow-x-auto">`：

```html
<div class="overflow-x-auto">
  <table v-if="section.columns && section.rows" class="w-full text-sm border-collapse border">
    ...
  </table>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/SectionTable.vue
git commit -m "refactor(SectionTable): use design tokens + overflow-x-auto"
```

---

## Chunk 4: 阶段组件 (Stage Components)

### Task 14: UploadStage.vue

**Files:**
- Modify: `web/src/components/UploadStage.vue`

- [ ] **Step 1: 添加 Lucide import**

```typescript
import { FileText } from 'lucide-vue-next'
```

- [ ] **Step 2: 替换图标和颜色**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 标题 (L39) | `text-gray-800` | `text-text-primary` |
| 说明文字 (L40) | `text-gray-500` | `text-text-muted` |
| 拖拽激活 (L48) | `border-purple-500 bg-purple-50` | `border-primary bg-primary-light` |
| 默认边框 (L48) | `border-gray-300 hover:border-gray-400` | `border-border hover:border-text-muted` |
| Emoji 📄 (L51) | `<div class="text-4xl mb-3">📄</div>` | `<FileText class="size-10 text-text-muted mb-3 mx-auto" />` |
| 拖拽文字 (L52) | `text-gray-600` | `text-text-secondary` |
| 格式提示 (L53) | `text-gray-400` | `text-text-muted` |
| 禁用按钮 (L57) | `bg-purple-400` | `bg-primary/70` |
| 正常按钮 (L57) | `bg-purple-600 hover:bg-purple-700` | `bg-primary hover:bg-primary-hover` |
| 错误 (L65) | `text-red-500` | `text-danger` |

- [ ] **Step 3: Commit**

```bash
git add web/src/components/UploadStage.vue
git commit -m "refactor(UploadStage): use design tokens + Lucide icon"
```

---

### Task 15: ProcessingStage.vue

**Files:**
- Modify: `web/src/components/ProcessingStage.vue`

- [ ] **Step 1: 添加 Lucide import**

```typescript
import { FileText } from 'lucide-vue-next'
```

- [ ] **Step 2: 替换图标和颜色**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 卡片 (L40) | `bg-white ... border border-gray-200` | `bg-surface ... border border-border` |
| 文件名区 (L41-42) | 整行替换，见下方模板 | 将 span 拆为 flex 容器 + 图标 + 文字 |

文件名区域模板替换（L41-42），将：

```html
<div class="flex items-center gap-2 mb-4">
  <span class="text-sm text-gray-800">📄 {{ filename }}</span>
```

替换为：

```html
<div class="flex items-center gap-2 mb-4">
  <FileText class="size-4 text-text-primary" />
  <span class="text-sm text-text-primary">{{ filename }}</span>
```
| 文件名文字 (L42) | `text-gray-800` | `text-text-primary` |
| 状态标签 (L43) | `bg-amber-100 text-amber-700` | `bg-warning-light text-warning-foreground` |
| 进度条轨道 (L46) | `bg-gray-200` | `bg-border` |
| 进度条填充 (L48) | `bg-gradient-to-r from-purple-600 to-purple-400` | `bg-gradient-to-r from-primary to-info` |
| 详情文字 (L53) | `text-gray-400` | `text-text-muted` |
| 步骤完成 (L64) | `bg-green-100 text-green-700` | `bg-success-light text-success-foreground` |
| 步骤激活 (L65) | `bg-amber-100 text-amber-700` | `bg-warning-light text-warning-foreground` |
| 步骤待定 (L66) | `bg-gray-100 text-gray-400` | `bg-background text-text-muted` |
| 错误区 (L73) | `bg-red-50 border border-red-200` | `bg-danger-light border border-danger/30` |
| 错误文字 (L74) | `text-red-600` | `text-danger` |
| 重试按钮 (L76) | `text-red-600 ... hover:text-red-800` | `text-danger ... hover:text-danger-foreground` |

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ProcessingStage.vue
git commit -m "refactor(ProcessingStage): use design tokens + Lucide icon"
```

---

### Task 16: ReviewStage.vue

**Files:**
- Modify: `web/src/components/ReviewStage.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 左面板 (L63) | `border-r border-gray-200 bg-gray-50` | `border-r border-border bg-background` |
| 左面板标题 (L64) | `border-b border-gray-200 bg-white text-sm font-medium text-gray-500` | `border-b border-border bg-surface text-sm font-medium text-text-muted` |
| 原文区 (L67) | `text-gray-600` | `text-text-secondary` |
| 标题段落 (L71) | `text-gray-800` | `text-text-primary` |
| 普通段落 (L71) | `text-gray-500` | `text-text-muted` |
| 模块 tab 栏 (L81) | `border-b border-gray-200 bg-white` | `border-b border-border bg-surface` |
| 选中 tab (L89) | `border-b-2 border-purple-600 text-purple-700` | `border-b-2 border-primary text-primary` |
| 未选中 tab (L90) | `text-gray-400 hover:text-gray-600` | `text-text-muted hover:text-text-secondary` |
| 批注圆点 (L96) | `bg-amber-500` | `bg-warning` |
| 内容区 (L102) | `bg-gray-50` | `bg-background` |
| 有批注边框 (L107) | `border border-amber-400` | `border border-warning` |
| 无批注边框 (L108) | `border border-gray-200` | `border border-border` |
| 批注头 (L114) | `bg-amber-50` | `bg-warning-light` |
| 批注头文字 (L116) | `text-amber-800` | `text-warning-foreground` |
| 批注计数 (L119) | `bg-amber-500` | `bg-warning` |
| 表头 (L127) | `bg-gray-50` | `bg-background` |
| 表头文字 (L128-129) | `text-gray-500 ... border-b border-gray-200` | `text-text-muted ... border-b border-border` |
| 行边框 (L135,142) | `border-b border-gray-100` | `border-b border-border/50` |
| 字段名 (L136,143) | `text-gray-700` | `text-text-secondary` |
| 字段值 (L137,144) | `text-gray-600` | `text-text-secondary` |
| 批注底部 (L151) | `border-t border-amber-200 bg-amber-50` | `border-t border-warning/30 bg-warning-light` |
| 批注头像 (L157) | `bg-amber-500` | `bg-warning` |
| 批注时间 (L161) | `text-amber-700` | `text-warning-foreground` |
| 批注内容 (L162) | `text-amber-900` | `text-warning-foreground` |
| 删除按钮 (L165) | `text-amber-600 hover:text-amber-800` | `text-warning hover:text-warning-foreground` |
| 输入区边框 (L172) | `border-t border-gray-200` | `border-t border-border` |
| textarea focus (L176) | `border border-gray-300 ... focus:ring-2 focus:ring-purple-500` | `border border-border ... focus:ring-2 focus:ring-primary` |
| 取消按钮 (L181) | `text-gray-500 hover:text-gray-700` | `text-text-muted hover:text-text-secondary` |
| 提交按钮 (L185) | `bg-purple-600 ... hover:bg-purple-700` | `bg-primary ... hover:bg-primary-hover` |
| 操作区底边框 (L192) | `border-t border-gray-200` | `border-t border-border` |
| 标注按钮 (L194) | `text-gray-500 border border-gray-300 ... hover:bg-gray-50` | `text-text-muted border border-border ... hover:bg-background` |
| 底栏 (L204) | `border-t border-gray-200 ... bg-white` | `border-t border-border ... bg-surface` |
| 底栏提示 (L205) | `text-gray-400` | `text-text-muted` |
| 跳过按钮 (L211) | `border border-gray-300 ... text-gray-600 hover:bg-gray-50` | `border border-border ... text-text-secondary hover:bg-background` |
| 提交按钮 (L215) | `bg-purple-600 ... hover:bg-purple-700 disabled:bg-purple-300` | `bg-primary ... hover:bg-primary-hover disabled:opacity-50` |

- [ ] **Step 2: 添加左面板 min-w**

将左面板 `<div class="w-1/3 border-r ...">` (L63) 添加 `min-w-[320px]`：

```
w-1/3 min-w-[320px] border-r border-border bg-background flex flex-col
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ReviewStage.vue
git commit -m "refactor(ReviewStage): use design tokens + min-w guard"
```

---

### Task 17: PreviewStage.vue

**Files:**
- Modify: `web/src/components/PreviewStage.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| tab 栏 (L65) | `border-b border-gray-200 bg-white` | `border-b border-border bg-surface` |
| 选中 tab (L73) | `border-b-2 border-emerald-500 text-emerald-600` | `border-b-2 border-success text-success` |
| 未选中 tab (L74) | `text-gray-400 hover:text-gray-600` | `text-text-muted hover:text-text-secondary` |
| 加载文字 (L83) | `text-gray-400` | `text-text-muted` |
| 底栏 (L88) | `border-t border-gray-200 ... bg-white` | `border-t border-border ... bg-surface` |
| 文件名 (L89) | `text-gray-400` | `text-text-muted` |
| 下载当前按钮 (L92) | `border border-gray-300 ... text-gray-600 hover:bg-gray-50` | `border border-border ... text-text-secondary hover:bg-background` |
| 全部下载按钮 (L96) | `bg-emerald-500 ... hover:bg-emerald-600` | `bg-success ... hover:bg-success/90` |
| 新解读按钮 (L105) | `text-gray-500 hover:text-gray-700` | `text-text-muted hover:text-text-secondary` |
| 预览区域背景 (L82) | `bg-white` | `bg-surface` |
| 底部操作区背景 (L103) | `bg-white` | `bg-surface` |

- [ ] **Step 2: Commit**

```bash
git add web/src/components/PreviewStage.vue
git commit -m "refactor(PreviewStage): use design tokens"
```

---

## Chunk 5: 视图页面 (Views)

### Task 18: LoginView.vue

**Files:**
- Modify: `web/src/views/LoginView.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 页面背景 (L32) | `bg-gray-50` | `bg-background` |
| 卡片 (L33) | `bg-white` | `bg-surface` |
| 标题 (L34) | `text-gray-800` | `text-text-primary` |
| label (L37) | `text-gray-700` | `text-text-secondary` |
| 输入框 (L39) | `border border-gray-300 ... focus:ring-2 focus:ring-blue-500` | `border border-border ... focus:ring-2 focus:ring-primary` |
| 密码 label (L42) | `text-gray-700` | `text-text-secondary` |
| 密码输入框 (L44) | `border border-gray-300 ... focus:ring-2 focus:ring-blue-500` | `border border-border ... focus:ring-2 focus:ring-primary` |
| 错误文字 (L46) | `text-red-500` | `text-danger` |
| 登录按钮 (L48) | `bg-blue-600 ... hover:bg-blue-700` | `bg-primary ... hover:bg-primary-hover` |

- [ ] **Step 2: Commit**

```bash
git add web/src/views/LoginView.vue
git commit -m "refactor(LoginView): use design tokens"
```

---

### Task 19: FileManagerView.vue

**Files:**
- Modify: `web/src/views/FileManagerView.vue`

- [ ] **Step 1: 添加 Lucide import**

```typescript
import { FolderOpen, BarChart3, Ruler, ClipboardList, FileText } from 'lucide-vue-next'
import { markRaw, type Component } from 'vue'
```

- [ ] **Step 2: 替换 typeConfig 图标为 Lucide 组件**

```typescript
const typeConfig: Record<string, { title: string; icon: Component }> = {
  'bid-documents': { title: '招标文件', icon: markRaw(FolderOpen) },
  reports: { title: '解析报告', icon: markRaw(BarChart3) },
  formats: { title: '文件格式', icon: markRaw(Ruler) },
  checklists: { title: '资料清单', icon: markRaw(ClipboardList) },
}

const config = computed(() => typeConfig[props.fileType] || { title: props.fileType, icon: markRaw(FileText) })
```

注意：FileCard 的 `:icon` prop 类型也需要从 `string` 改为 `Component`，在 FileCard.vue 中修改 `icon` prop 的类型。

- [ ] **Step 3: 修改 FileCard.vue 以支持 Lucide 组件图标**

在 `web/src/components/FileCard.vue` 中：

将 `icon: string` 改为 `icon: any`（因为 `Component` 类型在 template 中通过 `:is` 渲染），并将模板中的 `{{ icon }}` 替换为：

```html
<component :is="icon" class="size-5" />
```

- [ ] **Step 4: 替换 FileManagerView 颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 顶栏 (L92) | `bg-white border-b border-gray-200` | `bg-surface border-b border-border` |
| 标题 (L94) | `text-gray-800` | `text-text-primary` |
| 副标题 (L95) | `text-gray-400` | `text-text-muted` |
| 搜索框 (L100) | `border border-gray-300` | `border border-border` |
| 加载文字 (L106) | `text-gray-400` | `text-text-muted` |
| 空状态 (L108) | `border-gray-300 ... text-gray-400` | `border-border ... text-text-muted` |
| 分页栏 (L126) | `border-t border-gray-200 bg-white` | `border-t border-border bg-surface` |
| 分页信息 (L127) | `text-gray-400` | `text-text-muted` |
| 分页按钮 (L130,133,140) | `border border-gray-300 text-gray-500` | `border border-border text-text-muted` |
| 当前页 (L137) | `bg-purple-600 text-white` | `bg-primary text-primary-foreground` |
| 非当前页 (L137) | `border border-gray-300 text-gray-500` | `border border-border text-text-muted` |

- [ ] **Step 5: Commit**

```bash
git add web/src/views/FileManagerView.vue web/src/components/FileCard.vue
git commit -m "refactor(FileManagerView): use design tokens + Lucide icons"
```

---

### Task 20: AdminUsersView.vue

**Files:**
- Modify: `web/src/views/AdminUsersView.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 创建按钮 (L34) | `bg-blue-600 ... hover:bg-blue-700` | `bg-primary ... hover:bg-primary-hover` |
| 创建表单 (L38) | `bg-white` | `bg-surface` |
| 确认按钮 (L47) | `bg-green-600` | `bg-success` |
| 表格容器 (L53) | `bg-white` | `bg-surface` |
| 表头 (L55) | `bg-gray-50` | `bg-background` |
| 删除按钮 (L67) | `text-red-500` | `text-danger` |

- [ ] **Step 2: Commit**

```bash
git add web/src/views/AdminUsersView.vue
git commit -m "refactor(AdminUsersView): use design tokens"
```

---

### Task 21: FilePreviewView.vue

**Files:**
- Modify: `web/src/views/FilePreviewView.vue`

- [ ] **Step 1: 替换颜色类**

| 位置 | 替换前 | 替换后 |
|------|--------|--------|
| 顶栏 (L48) | `bg-white border-b border-gray-200` | `bg-surface border-b border-border` |
| 返回按钮 (L50) | `text-gray-400 hover:text-gray-600` | `text-text-muted hover:text-text-secondary` |
| 文件名 (L51) | `text-gray-800` | `text-text-primary` |
| 下载按钮 (L54) | `bg-purple-600 ... hover:bg-purple-700` | `bg-primary ... hover:bg-primary-hover` |
| 预览区域 (L58) | `bg-white` | `bg-surface` |
| 加载文字 (L59) | `text-gray-400` | `text-text-muted` |

- [ ] **Step 2: Commit**

```bash
git add web/src/views/FilePreviewView.vue
git commit -m "refactor(FilePreviewView): use design tokens"
```

---

### Task 22: BidAnalysisView.vue — 无颜色类需替换

`BidAnalysisView.vue` 本身不包含任何硬编码颜色类，仅引用子组件。所有颜色替换已在子组件任务中完成。

**无需操作。**

> **注意:** `web/src/views/PreviewView.vue` 是遗留文件（未被路由引用），**不在本次迁移范围内**。Task 23 验证步骤中如果 grep 到该文件的硬编码颜色属于预期结果，可忽略。

---

## Chunk 6: 最终验证

### Task 23: 全量构建验证

- [ ] **Step 1: 运行构建**

```bash
cd web && npx vite build
```

Expected: 构建成功

- [ ] **Step 2: 检查是否有遗漏的硬编码颜色**

```bash
cd web && grep -rn "purple-\|blue-[0-9]\|gray-[0-9]\|red-[0-9]\|green-[0-9]\|amber-\|yellow-\|emerald-" src/components/ src/views/ src/layouts/ --include="*.vue" | grep -v "node_modules"
```

Expected: 只有 `PreviewView.vue`（遗留文件，不在本次范围）中可能存在硬编码颜色，其余文件应无输出。

注意：`text-red-500` 等出现在内联 HTML 字符串中（如 JS 模板字面量 `'<p class="text-red-500">...'`）属于服务端返回内容的回退渲染，不需要替换。

- [ ] **Step 3: 最终 Commit（如有遗漏修复）**

```bash
git add -A
git commit -m "refactor: complete design token migration"
```
