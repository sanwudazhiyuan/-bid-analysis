# 暗标审查功能设计文档

> 日期：2026-04-17
> 方案：方案 B — 扩展复用 + 暗标专用模块

---

## 1. 概述

在现有标书审查管线基础上，新增独立的"暗标审查"功能。用户上传两个文档（暗标规则文档 + 待审查标书），系统自动将规则分为**格式规则**和**内容规则**两类分别审查，输出带批注的审查报告。

### 1.1 核心原则

- **最大化复用**：文档解析、图片提取/描述、SSE 进度推送、docx 报告生成框架均复用现有代码
- **独立入口**：侧边栏独立导航项，独立的页面/store/API/数据库模型
- **格式+内容双轨审查**：格式规则基于 XML 格式元数据由 LLM 判断；内容规则按批次扫描全文并批注
- **通用规则兜底**：内置从 10 个标书暗标要求中总结的通用规则，项目规则优先级高于通用规则

---

## 2. 通用暗标规则（从 10 个标书提取）

忽略物理世界规则（打印颜色、纸张、装订等），保留可在电子文档层面审核的规则。

### 2.1 格式类规则（format）

| 类别 | 规则 | 强制 |
|------|------|------|
| 页码 | 须编制连续的阿拉伯数字页码，第一页页码为"1"，页码在页面底端居中位置 | 是 |
| 页眉页脚 | 任何一页均不得设置页眉和页脚，只准出现页码 | 是 |
| 文字颜色 | 所有文字均为黑色 | 是 |
| 分模块页码 | 如分多个评审模块，每个模块须独立生成连续页码，正文第一页页码均为"1" | 是 |
| 排版建议 | 字体：宋体；字号：标题三号，其他四号；行距：1.5 倍；页边距：上下 2.54cm，左右 3.17cm | 否 |
| 页数限制 | 每个评审节点文件页数不得超过指定上限（由项目规则指定） | 是 |

### 2.2 内容类规则（content）

| 类别 | 规则 | 强制 |
|------|------|------|
| 身份信息 | 不得出现投标人名称（含简称、外文名称）、公司商标/徽标、公司网址（含邮箱域名）、公司电话、资质证书编号、人员姓名/身份证号/证书编号、人员照片、可辨识的公章、企业标准名称或编号 | 是 |
| 客户名称 | 不得出现过往业绩案例客户名称，如需体现应以"某金融企业"等代替 | 是 |
| 文档痕迹 | 不得出现任何涂改、行间插字或删除痕迹 | 是 |
| 图片使用 | 非必要不使用图片（包括人员照片、工作照片等）、图表、PPT 幻灯片 | 否 |
| 业绩案例 | 非必要不使用过往业绩案例 | 否 |
| 证书使用 | 非必要不使用公司证书、人员证书 | 否 |

强制规则违反 → **fail**；非强制规则违反 → **warning**（仍需批注供人工确认）。

---

## 3. 数据模型

### 3.1 格式信息模型（扩展 `src/models.py`）

```python
@dataclass
class RunFormat:
    """单个 run 的字符级格式"""
    text: str = ""
    font_name_ascii: str | None = None
    font_name_east_asia: str | None = None   # 中文字体（如"宋体"）
    font_size_pt: float | None = None         # 字号（磅值）
    font_color_rgb: str | None = None         # 颜色 hex（如"000000"=黑色）
    bold: bool | None = None
    italic: bool | None = None
    underline: str | None = None

@dataclass
class ParagraphFormat:
    """段落级格式"""
    heading_level: int | None = None         # None=正文, 1=H1, 2=H2...
    outline_level: int | None = None
    line_spacing: float | None = None        # 行距倍数
    line_spacing_rule: str | None = None     # auto/exact/atLeast
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    alignment: str | None = None             # left/center/right/both
    indent_left_cm: float | None = None
    indent_right_cm: float | None = None
    indent_first_line_cm: float | None = None
    runs: list[RunFormat] = field(default_factory=list)
    dominant_font: str | None = None
    dominant_size_pt: float | None = None
    dominant_color: str | None = None
    has_non_black_text: bool = False

@dataclass
class HeaderFooterInfo:
    """单个页眉/页脚详情"""
    hf_type: str              # "default" | "first" | "even"
    has_text: bool = False
    text_content: str = ""    # 文字内容（检测公司名等）
    has_image: bool = False   # 图片（logo 检测）
    has_page_number: bool = False
    image_count: int = 0

@dataclass
class SectionFormat:
    """文档节级格式"""
    section_index: int
    margin_top_cm: float | None = None
    margin_bottom_cm: float | None = None
    margin_left_cm: float | None = None
    margin_right_cm: float | None = None
    page_width_cm: float | None = None
    page_height_cm: float | None = None
    section_break_type: str | None = None   # nextPage/continuous/evenPage/oddPage
    para_range: tuple[int, int] | None = None
    section_heading: str | None = None
    headers: list[HeaderFooterInfo] = field(default_factory=list)
    has_different_first_page: bool = False
    has_even_odd_headers: bool = False
    footers: list[HeaderFooterInfo] = field(default_factory=list)
    page_number_start: int | None = None
    page_number_format: str | None = None
    estimated_page_count: int | None = None
    page_range: tuple[int, int] | None = None

@dataclass
class FormatSummary:
    """格式统计摘要（给 LLM 的结构化输入）"""
    heading_stats: dict       # {level: {font, size, bold, count, anomalies}}
    body_stats: dict          # {font_distribution, size_distribution, color_anomalies}
    non_black_paragraphs: list[dict]
    mixed_font_paragraphs: list[dict]
    def to_prompt_text(self) -> str: ...

@dataclass
class DocumentFormat:
    """文档整体格式元数据"""
    sections: list[SectionFormat] = field(default_factory=list)
    total_pages: int | None = None
    format_summary: FormatSummary | None = None
```

### 3.2 Paragraph 扩展

```python
@dataclass
class Paragraph:
    index: int
    text: str
    source_file: str = ""
    style: str | None = None
    is_table: bool = False
    table_data: list | None = None
    format_info: ParagraphFormat | None = None   # 新增
```

### 3.3 暗标规则模型

```python
@dataclass
class AnbiaoRule:
    rule_index: int
    rule_text: str
    rule_type: str           # "format" | "content"
    source_section: str      # "编制要求" | "编制建议"
    is_mandatory: bool = True
    category: str = ""       # 页码/页眉页脚/身份信息/图片使用...

    @property
    def violation_level(self) -> str:
        return "fail" if self.is_mandatory else "warning"
```

### 3.4 数据库模型

```python
class AnbiaoReview(Base):
    __tablename__ = "anbiao_reviews"

    id: UUID
    user_id: UUID
    rule_file_path: str | None      # 暗标规则文档路径（可选）
    rule_file_name: str | None
    tender_file_path: str           # 被审查标书路径
    tender_file_name: str
    use_default_rules: bool = True  # 是否使用通用规则
    status: str                     # pending/indexing/reviewing/completed/failed
    progress: int
    current_step: str
    parsed_rules: dict | None       # 解析后的规则列表
    format_results: list | None     # 格式审查结果
    content_results: list | None    # 内容审查结果（含批注）
    review_summary: dict | None     # {total, pass, fail, warning}
    output_file_path: str | None
    preview_html: str | None        # 预缓存的预览 HTML
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
```

---

## 4. 文档解析层

### 4.1 `docx_parser.py` 扩展

```python
def parse_docx(file_path: str, extract_format: bool = False) -> list[Paragraph]:
    """扩展：当 extract_format=True 时额外提取 ParagraphFormat。

    从每个段落的 XML 中提取：
    - w:pPr → 行距(w:spacing)、对齐(w:jc)、缩进(w:ind)、大纲级别(w:outlineLvl)
    - w:pPr/w:pStyle → heading_level 识别
    - 每个 w:r 的 w:rPr → 字体(w:rFonts ascii/eastAsia)、字号(w:sz)、
      颜色(w:color)、加粗(w:b)、斜体(w:i)、下划线(w:u)
    - 聚合计算 dominant_font/dominant_size/dominant_color/has_non_black_text

    extract_format=False 时行为完全不变。
    """

def extract_document_format(file_path: str) -> DocumentFormat:
    """独立函数：提取文档级格式信息。

    解析每个 section 的 w:sectPr：
    - w:pgMar → 页边距（twips → cm）
    - w:pgSz → 纸张大小
    - w:headerReference (default/first/even) → 深入解析 header XML：
        - 遍历 w:p 检测文字内容
        - 检测 w:drawing 图片（logo）
        - 检测 w:fldSimple/w:fldChar PAGE 页码域
    - w:footerReference (default/first/even) → 同上
    - w:titlePg → 首页不同标记
    - w:pgNumType → 页码起始和格式
    - section break type（从上一个 sectPr 的 w:type 属性）
    - para_range：通过遍历 body 定位每个 sectPr 的段落范围
    - section_heading：该 section 范围内第一个标题段落文本

    页数估算：
    - 如有 LibreOffice，调 soffice 转 PDF 计算每节实际页数
    - 否则 estimated_page_count = None，LLM 基于段落数粗略估算
    """
```

---

## 5. 暗标规则解析（新建 `src/reviewer/anbiao_rule_parser.py`）

```python
def parse_anbiao_rules(file_path: str, api_settings: dict) -> list[AnbiaoRule]:
    """解析暗标规则文档 → 逐条规则列表。

    流程：
    1. unified.py 解析文档得到 paragraphs
    2. tender_rule_splitter 降级策略构建章节索引
    3. 按最小章节拆分，识别每条独立规则
    4. LLM 对每条规则分类（调 call_qwen）：
       - rule_type: format / content
       - is_mandatory: True（"不得/不应/必须/要求"）/ False（"建议/非必要/尽量"）
       - category: 页码/页眉页脚/身份信息/...
       - 过滤物理世界规则（打印/纸张/装订/封皮等）
    """

def load_default_rules() -> list[dict]:
    """加载 config/anbiao_default_rules.json 通用规则"""

def merge_rules(
    project_rules: list[AnbiaoRule],
    default_rules: list[dict],
) -> list[AnbiaoRule]:
    """合并规则：项目规则覆盖通用规则中同 category 条目，
    通用规则中未被覆盖的作为补充加入。"""
```

---

## 6. 暗标审查引擎（新建 `src/reviewer/anbiao_reviewer.py`）

### 6.1 格式规则审查

```python
def review_format_rules(
    rules: list[AnbiaoRule],         # 仅 rule_type=="format" 的规则
    doc_format: DocumentFormat,
    paragraphs: list[Paragraph],     # 带 format_info
    api_settings: dict,
) -> list[dict]:
    """逐条格式规则调 LLM 判断。

    对每条规则：
    1. 构建 prompt：规则文本 + DocumentFormat 结构化摘要 + FormatSummary
    2. 调 call_qwen 判断
    3. 返回 {rule_index, rule_text, result(pass/fail/warning), reason, details}

    云端可并发审查多条规则；本地逐条串行。
    """
```

prompt 示例：
```
你是暗标格式审查专家。

## 当前审查规则
{rule_text}

## 规则严重等级: {mandatory/advisory}
- mandatory: 违反判定为 fail
- advisory: 违反判定为 warning

## 文档格式元数据
### 文档结构（共 N 个 section）
Section 0: 段落 0-45, 页码起始=1, 分节符=nextPage, 首标题="施工方案"
  页边距: 上2.54cm 下2.54cm 左3.17cm 右3.17cm
  页眉: [default] 有文字"xxx公司", 有图片1张; [first] 无内容
  页脚: [default] 有页码(底端居中); [first] 无页码
  预估页数: 23
  ...

### 段落格式统计
标题段落(Heading 1-3): 共15个, 字体=宋体, 字号=三号(16pt), 加粗
正文段落: 共120个, 主要字体=宋体(95%)/仿宋(5%), 主要字号=四号(14pt)(90%)
非黑色文字段落: [段落23: 红色"重要", 段落67: 蓝色"链接"]

请判断是否符合规则，输出 JSON:
{
  "result": "pass" | "fail" | "warning",
  "reason": "不通过/警告原因说明",
  "details": [{"location": "...", "issue": "..."}]
}
```

### 6.2 内容规则审查

```python
def review_content_rules(
    rules: list[AnbiaoRule],         # 仅 rule_type=="content" 的规则
    paragraphs: list[Paragraph],
    tender_index: dict,
    extracted_images: list[dict],
    doc_format: DocumentFormat,       # 页眉页脚文字内容也要审查
    api_settings: dict,
    is_local_mode: bool,
) -> list[dict]:
    """内容规则按批次审查，复用 reviewer.py 的三阶段模式。

    流程：
    1. 按章节分批次（复用 tender_indexer 的分批逻辑）
    2. 对每条内容规则：
       a. 页眉页脚文字内容作为首批次优先审查
       b. 正文按批次送 LLM 批注
       c. 图片通过多模态审查（复用 reviewer.py 的 _build_multimodal_content）
       d. 云端一次多章节，本地一次一章节
       e. 中间批次 intermediate + 末批次 final 汇总
    3. 非强制规则发现违反时标注 warning 而非 fail
    4. 返回 [{rule_index, rule_text, result, confidence, reason,
              tender_locations: [{para_indices, text_snippet, reason}]}]
    """
```

---

## 7. 审查管线（Celery Task）

新建 `server/app/tasks/anbiao_review_task.py`：

```python
@celery_app.task(bind=True, name="run_anbiao_review")
def run_anbiao_review(self, review_id: str):
    """暗标审查管线。

    Step 1: 解析暗标规则文档 (0-5%)
      → unified.py 解析 → anbiao_rule_parser 拆分 → LLM 分类 format/content
      → 合并通用规则

    Step 2: 解析被审查标书 (5-15%)
      → parse_docx(extract_format=True) 提取段落+格式
      → extract_document_format() 提取文档级格式
      → extract_images() 提取图片
      → build_tender_index() 构建章节索引

    Step 3: 格式规则审查 (15-40%)
      → 构建 FormatSummary
      → review_format_rules() 逐条 LLM 判断

    Step 4: 内容规则审查 (40-90%)
      → review_content_rules() 按批次扫描全文
      → 含图片多模态审查
      → 含页眉页脚文字内容审查

    Step 5: 生成报告 (90-100%)
      → 生成预览 HTML（复用 build_preview_html 逻辑）
      → 生成 docx 报告（扩展 docx_annotator）
    """
```

复用清单：
| 模块 | 复用方式 |
|------|----------|
| `unified.py` | 直接调用，解析规则文档和标书 |
| `docx_parser.py` | 扩展 `extract_format` 参数 |
| `image_extractor.py` | 直接调用 |
| `image_describer.py` | 直接调用 |
| `tender_rule_splitter.py` | 直接调用，构建章节索引 |
| `tender_indexer.py` | 复用分批逻辑 |
| `reviewer.py` | 复用 `_build_multimodal_content`、三阶段审查模式 |
| `call_qwen` / `build_messages` | 直接调用 |
| `docx_annotator.py` | 扩展支持双表格（格式+内容） |
| `review_preview.py` | 复用 `build_preview_html` 逻辑 |
| SSE 进度推送 | 复用现有 Celery + SSE 机制 |

---

## 8. API 设计

### 8.1 路由：`server/app/routers/anbiao_reviews.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/anbiao-reviews/` | 创建暗标审查（上传规则文档+标书） |
| GET | `/api/anbiao-reviews/` | 列表 |
| GET | `/api/anbiao-reviews/{id}` | 获取状态和结果 |
| GET | `/api/anbiao-reviews/{id}/progress` | SSE 进度推送 |
| GET | `/api/anbiao-reviews/{id}/preview` | 获取预览数据（HTML+审查项） |
| GET | `/api/anbiao-reviews/{id}/download` | 下载 docx 报告 |
| GET | `/api/anbiao-reviews/{id}/images/{filename}` | 图片静态服务 |
| DELETE | `/api/anbiao-reviews/{id}` | 删除 |

### 8.2 请求/响应

创建请求（multipart/form-data）：
```
tender_file: File (必填)
rule_file: File (可选)
use_default_rules: bool = true
```

预览响应：
```json
{
  "tender_html": "<div>...</div>",
  "format_results": [
    {"id": 1, "rule_text": "...", "result": "fail", "reason": "...", "details": [...]}
  ],
  "content_results": [
    {"id": 1, "rule_text": "...", "result": "warning", "confidence": 85,
     "reason": "...", "tender_locations": [...]}
  ],
  "summary": {"total": 12, "pass": 8, "fail": 2, "warning": 2}
}
```

---

## 9. 前端设计

### 9.1 侧边栏

`AppSidebar.vue` navItems 中"标书审查"之后插入：
```typescript
{ path: '/anbiao-review', label: '暗标审查', icon: EyeOff, group: 'main' },
```

### 9.2 路由

```typescript
{ path: 'anbiao-review', name: 'anbiao-review',
  component: () => import('../views/AnbiaoReviewView.vue') },
{ path: 'anbiao-results/:id', name: 'anbiao-detail',
  component: () => import('../views/AnbiaoDetailView.vue'), props: true },
```

### 9.3 页面结构

**AnbiaoReviewView.vue** — 三阶段切换：

1. **上传阶段（AnbiaoUploadStage.vue）**
   - 左侧：暗标规则文档上传区（可选，复用 FileUpload 组件）
   - 右侧：待审查标书上传区（必填）
   - 底部：勾选"同时使用通用暗标规则"
   - 按钮："开始暗标审查"

2. **处理阶段（复用 ProcessingStage.vue）**
   - 自定义步骤：解析规则 → 解析标书 → 合并规则 → 格式审查 → 内容审查 → 生成报告
   - SSE 进度推送（复用 useSSE composable）

3. **预览阶段（AnbiaoPreviewStage.vue）**
   - 顶部：统计栏 + "暗标"badge
   - 顶部 tab：[格式审查] / [内容审查]
   - 左侧：文档 HTML 预览 + 高亮标记（复用 data-review-id + review-highlight 机制）
   - 右侧：批注/审查结果面板
     - 格式 tab：规则结果卡片（结果 + 原因，无置信度）
     - 内容 tab：批注卡片（结果 + 置信度 + 原因，与标书审查一致）
   - 左右联动：点击高亮 ↔ 滚动到批注（复用 onHighlightClick / scrollToHighlight 逻辑）
   - 底部：[新建审查] / [下载审查报告]

### 9.4 Store

`web/src/stores/anbiaoStore.ts`：
```typescript
interface AnbiaoState {
  stage: 'upload' | 'processing' | 'preview'
  currentReviewId: string | null
  progress: number
  currentStep: string
  detail: string
  error: string | null
  formatResults: AnbiaoFormatResult[]
  contentResults: AnbiaoContentResult[]
  summary: { total: number; pass: number; fail: number; warning: number }
}
```

### 9.5 审查结果列表

`ReviewResultsView.vue` 扩展：
- 增加 tab 筛选：[全部] / [标书审查] / [暗标审查]
- 暗标审查结果显示紫色"暗标" badge

---

## 10. 输出报告（docx）

扩展 `docx_annotator.py`，新增暗标报告生成函数：

```python
def generate_anbiao_review_docx(
    tender_file_path: str,
    format_results: list[dict],
    content_results: list[dict],
    summary: dict,
    output_path: str,
    rule_filename: str,
    tender_filename: str,
):
    """生成暗标审查报告 docx。

    结构：
    1. 标题："暗标审查报告"
    2. 元信息：规则文档名、标书文档名、审查时间
    3. 统计摘要：总计/通过/不通过/警告
    4. 格式审查表格：序号 | 规则 | 结果 | 说明
    5. 内容审查表格：序号 | 规则 | 结果 | 置信度 | 说明
    6. Word 批注（fail=红色, warning=橙色）标注在正文对应段落
    """
```

---

## 11. 新增文件清单

| 文件 | 说明 |
|------|------|
| `src/models.py` | 扩展 Paragraph + 新增 RunFormat/ParagraphFormat/SectionFormat/DocumentFormat 等 |
| `src/parser/docx_parser.py` | 扩展 extract_format 参数 + 新增 extract_document_format() |
| `src/reviewer/anbiao_rule_parser.py` | 新建：暗标规则解析/分类/合并 |
| `src/reviewer/anbiao_reviewer.py` | 新建：格式+内容审查引擎 |
| `config/anbiao_default_rules.json` | 新建：通用暗标规则配置 |
| `config/prompts/anbiao_format_review.txt` | 新建：格式审查 prompt 模板 |
| `config/prompts/anbiao_content_review.txt` | 新建：内容审查 prompt 模板 |
| `config/prompts/anbiao_rule_classify.txt` | 新建：规则分类 prompt 模板 |
| `server/app/models/anbiao_review.py` | 新建：数据库模型 |
| `server/app/routers/anbiao_reviews.py` | 新建：API 路由 |
| `server/app/tasks/anbiao_review_task.py` | 新建：Celery 审查管线 |
| `server/app/services/anbiao_preview.py` | 新建：预览 HTML 生成 |
| `server/alembic/versions/xxx_add_anbiao_reviews.py` | 新建：数据库迁移 |
| `web/src/views/AnbiaoReviewView.vue` | 新建：暗标审查主页面 |
| `web/src/components/AnbiaoUploadStage.vue` | 新建：上传阶段 |
| `web/src/components/AnbiaoPreviewStage.vue` | 新建：预览阶段 |
| `web/src/stores/anbiaoStore.ts` | 新建：状态管理 |
| `web/src/api/anbiao.ts` | 新建：API 客户端 |
| `web/src/router/index.ts` | 修改：新增路由 |
| `web/src/components/AppSidebar.vue` | 修改：新增导航项 |
| `web/src/views/ReviewResultsView.vue` | 修改：增加暗标 tab 和 badge |
| `src/reviewer/docx_annotator.py` | 修改：新增暗标报告生成函数 |
