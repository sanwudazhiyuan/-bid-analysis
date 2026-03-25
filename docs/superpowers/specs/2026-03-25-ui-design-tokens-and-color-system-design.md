# UI 设计令牌与色彩体系设计

> 日期: 2026-03-25
> 状态: 已批准
> 范围: 前端色彩体系重构、设计令牌建立、图标替换、桌面适配加固

## 背景

当前项目是**招标文件解读分析工具**，面向政企办公场景，纯桌面端使用。前端基于 Vue 3 + Tailwind CSS v4.2.2，无第三方组件库。

### 现存问题

1. **颜色不一致** — 旧组件用 `blue-500` 做 focus，新组件用 `purple-500`，主色混乱
2. **无设计令牌** — 所有颜色以 Tailwind 原子类硬编码在各组件中（如 `bg-purple-600`、`text-gray-800`），改主题需逐文件修改
3. **无响应式** — 侧边栏固定 200px，内容区 `w-1/3` 硬分割，不同桌面分辨率体验差异大
4. **Emoji 做图标** — 使用 Unicode Emoji（📄📁📊），不同平台渲染差异大，专业感不足
5. **无暗色模式** — 仅亮色主题（经确认无需支持暗色模式）

## 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 色彩风格 | 蓝灰色系 | 契合政企/招标文件的专业、信任、可靠定位 |
| 暗色模式 | 不支持 | 办公场景足够，减少开发量 |
| 图标方案 | Lucide Icons (`lucide-vue-next`) | 轻量线性风格，Vue 组件化引用，社区活跃 |
| 适配策略 | 流式填满 | 充分利用屏幕空间，内容区 `flex-1` 铺满 |
| 设备范围 | 纯桌面端 | 内部工具，用户固定用 PC 访问 |

## 技术方案

### 1. 设计令牌体系

在 `web/src/assets/main.css` 中使用 Tailwind v4 的 `@theme` 指令建立 CSS 变量：

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

  /* 交互/信息色 — 用于表格悬停行、选中行、复选框、进度条等非品牌蓝色场景 */
  --color-info: oklch(55% 0.18 250);
  --color-info-light: oklch(96% 0.02 250);
  --color-info-foreground: oklch(30% 0.12 250);

  /* 高亮色 — 用于表格选中行、批注标记等 */
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

### 2. 色彩映射规范

全量替换组件中硬编码的 Tailwind 颜色类为语义令牌：

| UI 元素 | 当前用法 | 改为 |
|---------|---------|------|
| 侧边栏选中项 | `bg-purple-50 text-purple-700` | `bg-primary-light text-primary` |
| 侧边栏选中左边框 | `border-purple-600` | `border-primary` |
| 主要按钮 | `bg-purple-600 hover:bg-purple-700` | `bg-primary hover:bg-primary-hover` |
| 主要按钮文字 | `text-white` | `text-primary-foreground` |
| 次要按钮 | `border-gray-300 text-gray-600` | `border-border text-text-secondary` |
| 删除按钮 | `border-red-200 text-red-500` | `border-danger/30 text-danger` |
| Focus 环 | 混用 `ring-blue-500` / `ring-purple-500` | 统一 `ring-primary` |
| 页面背景 | `bg-gray-50` | `bg-background` |
| 卡片/面板背景 | `bg-white` | `bg-surface` |
| 边框 | `border-gray-200` | `border-border` |
| 主文字 | `text-gray-800` | `text-text-primary` |
| 次要文字 | `text-gray-600` | `text-text-secondary` |
| 辅助文字 | `text-gray-400` / `text-gray-500` | `text-text-muted` |
| 成功状态 | `bg-green-100 text-green-700` | `bg-success-light text-success-foreground` |
| 警告状态 | `bg-amber-50 text-amber-700` | `bg-warning-light text-warning-foreground` |
| 错误状态 | `bg-red-50 text-red-800` | `bg-danger-light text-danger-foreground` |
| 表格悬停行 | `bg-blue-50` | `bg-info-light` |
| 表格选中行 | `bg-yellow-50` | `bg-highlight` |
| 复选框/进度条 | `bg-blue-600` | `bg-info` |
| 批注标记 | `bg-yellow-100 text-yellow-800` | `bg-highlight text-highlight-foreground` |
| 链接/信息文字 | `text-blue-600` | `text-info` |
| 禁用状态 | 各组件自行处理 | 统一使用 `disabled:opacity-50 disabled:pointer-events-none` |

### 3. 图标替换

安装 `lucide-vue-next` 依赖，将 Emoji 替换为 Lucide 图标组件：

| Emoji | Lucide 组件 | 用途 |
|-------|-------------|------|
| 📄 | `<FileText />` | 文件 |
| 📁 | `<FolderOpen />` | 文件夹 |
| 📊 | `<BarChart3 />` | 分析/图表 |
| 📐 | `<Ruler />` | 规格/度量 |
| 📋 | `<ClipboardList />` | 清单 |
| 📝 | `<PenLine />` | 编辑/批注 |

图标统一使用 `size-4`（16px）或 `size-5`（20px），与文字对齐。

### 4. 桌面适配加固

适用场景：纯桌面端，需覆盖 1280px ~ 超宽屏。

| 改动点 | 当前 | 改为 |
|--------|------|------|
| 侧边栏 | 固定 `w-[200px]` | 保持不变 |
| 内容区 | `flex-1` | 保持 `flex-1` 流式填满 |
| 两栏分割 | `w-1/3` 硬分割 | `min-w-[320px] w-1/3`，确保小屏不压缩到不可读 |
| 表格 | 无溢出处理 | 包裹 `overflow-x-auto`，窄屏可横向滚动 |
| 输入框/卡片 | 无最大宽度限制 | 保持流式（不限制 `max-w`） |

## 改动文件清单

| 文件 | 改动内容 |
|------|----------|
| `web/src/assets/main.css` | 新增 `@theme` 设计令牌 + base 层样式 |
| `web/package.json` | 添加 `lucide-vue-next` 依赖 |
| `web/src/components/AppSidebar.vue` | 紫色 → 语义色 + Emoji → Lucide |
| `web/src/components/FileCard.vue` | 颜色语义化 |
| `web/src/components/ReviewStage.vue` | 紫色/琥珀 → 语义色 |
| `web/src/components/PreviewStage.vue` | 颜色语义化 + 图标替换 |
| `web/src/components/ProcessingStage.vue` | 状态色语义化 |
| `web/src/components/AnnotationPanel.vue` | focus 色统一 |
| `web/src/views/BidAnalysisView.vue` | 主色统一 + 图标替换 |
| `web/src/views/FileManagerView.vue` | 颜色语义化 + 图标替换 |
| `web/src/views/LoginView.vue` | 蓝色统一为 primary 令牌 |
| `web/src/views/AdminUsersView.vue` | 颜色语义化 |
| `web/src/views/FilePreviewView.vue` | 颜色语义化 |
| `web/src/layouts/SidebarLayout.vue` | 背景色语义化 |
| `web/src/components/UploadStage.vue` | 紫色 → 语义色 + Emoji → Lucide |
| `web/src/components/UserMenu.vue` | 头像/登出颜色语义化 |
| `web/src/components/SectionTable.vue` | 悬停/选中行 → info-light/highlight + 复选框色 |
| `web/src/components/ModuleNav.vue` | 蓝色 → primary 语义色 |
| `web/src/components/AnnotationBadge.vue` | 黄色 → highlight 语义色 |
| `web/src/components/TaskProgress.vue` | 进度条/状态色语义化 |
| `web/src/components/FileUpload.vue` | 蓝色 → primary 语义色 |
| `web/src/components/DownloadCard.vue` | 链接色语义化 |

## 无障碍与对比度

所有令牌颜色需满足 WCAG AA 标准（正文文字对比度 >= 4.5:1）。实施时需验证：

- `--color-primary`（oklch 45% 0.15 250）在白色背景上的对比度
- `--color-primary-foreground` 在 `--color-primary` 背景上的对比度
- 各语义色 foreground 在对应 light 背景上的对比度

如有不达标，调整 oklch 明度值直至合规。

## 遗留文件处理

- `web/src/views/PreviewView.vue` — 未被路由引用，属遗留文件，**不在本次改动范围内**，后续可删除

## 命名说明

- `--color-border` 生成的工具类为 `border-border`（如 `border-border`、`border-t-border`），这是 Tailwind v4 中 shadcn/ui 等主流项目的通用命名约定，已验证可正常工作

## 不做的事情

- **不做暗色模式** — 纯办公场景，亮色足够
- **不做移动端适配** — 纯桌面端工具
- **不引入 UI 组件库** — 保持当前纯 Tailwind 手写组件的方式
- **不重构组件结构** — 仅替换颜色和图标，不改组件架构
- **不添加动画/过渡效果** — 保持当前简洁风格
