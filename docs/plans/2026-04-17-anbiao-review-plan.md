# 暗标审查功能实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立的暗标审查功能，用户上传暗标规则文档+待审查标书，系统区分格式规则和内容规则分别审查，输出带批注的审查报告。

**Architecture:** 扩展现有 `Paragraph` 模型增加格式字段，新建暗标专用模块（规则解析、审查引擎、Celery task），复用文档解析、图片处理、SSE 进度、docx 报告生成等基础设施。前端新增独立页面和 store，侧边栏增加导航项。

**Tech Stack:** Python / FastAPI / SQLAlchemy / Celery / PostgreSQL / Vue 3 / Pinia / TypeScript / Tailwind CSS / python-docx / lxml

**Design Spec:** `docs/specs/2026-04-17-anbiao-review-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `src/models.py` (modify) | 新增 `RunFormat`, `ParagraphFormat`, `HeaderFooterInfo`, `SectionFormat`, `FormatSummary`, `DocumentFormat` dataclass；`Paragraph` 增加 `format_info` 字段 |
| `src/parser/docx_parser.py` (modify) | 新增 `extract_format` 参数 + `extract_document_format()` 函数 |
| `src/reviewer/anbiao_rule_parser.py` (create) | 暗标规则文档解析、LLM 分类、规则合并 |
| `src/reviewer/anbiao_reviewer.py` (create) | 格式规则审查 + 内容规则审查引擎 |
| `config/anbiao_default_rules.json` (create) | 通用暗标规则配置 |
| `config/prompts/anbiao_format_review.txt` (create) | 格式审查 prompt 模板 |
| `config/prompts/anbiao_content_review.txt` (create) | 内容审查 prompt 模板（中间批次） |
| `config/prompts/anbiao_content_review_final.txt` (create) | 内容审查 prompt 模板（末批次） |
| `config/prompts/anbiao_rule_classify.txt` (create) | 规则分类 prompt 模板 |
| `server/app/models/anbiao_review.py` (create) | `AnbiaoReview` ORM 模型 |
| `server/app/services/anbiao_service.py` (create) | 暗标审查业务逻辑（创建、查询、删除） |
| `server/app/routers/anbiao_reviews.py` (create) | 暗标审查 API 路由 |
| `server/app/tasks/anbiao_review_task.py` (create) | Celery 暗标审查管线 |
| `server/app/services/anbiao_preview.py` (create) | 暗标审查预览 HTML 生成 |
| `server/alembic/versions/xxxx_add_anbiao_reviews.py` (create) | 数据库迁移 |
| `web/src/api/anbiao.ts` (create) | 暗标审查 API 客户端 |
| `web/src/stores/anbiaoStore.ts` (create) | 暗标审查状态管理 |
| `web/src/views/AnbiaoReviewView.vue` (create) | 暗标审查主页面 |
| `web/src/components/AnbiaoUploadStage.vue` (create) | 上传阶段组件 |
| `web/src/components/AnbiaoPreviewStage.vue` (create) | 预览阶段组件 |

### Modified Files
| File | Changes |
|------|---------|
| `web/src/router/index.ts` | 新增 `anbiao-review` 路由 |
| `web/src/components/AppSidebar.vue` | navItems 新增暗标审查 |
| `web/src/views/ReviewResultsView.vue` | 增加暗标 tab 和 badge |
| `server/app/main.py` | 注册 anbiao_reviews router |
| `server/alembic/env.py` | import AnbiaoReview 模型 |
| `src/reviewer/docx_annotator.py` | 新增 `generate_anbiao_review_docx()` 函数 |

---

## Chunk 1: 数据模型层

### Task 1: 扩展 Paragraph 模型添加格式信息

**Files:**
- Modify: `src/models.py`
- Test: `src/reviewer/tests/test_models_format.py`

- [ ] **Step 1: 在 `src/models.py` 中新增格式 dataclass**

在 `TaggedParagraph` 之后添加：

```python
@dataclass
class RunFormat:
    """单个 run 的字符级格式"""
    text: str = ""
    font_name_ascii: str | None = None
    font_name_east_asia: str | None = None
    font_size_pt: float | None = None
    font_color_rgb: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: str | None = None

@dataclass
class ParagraphFormat:
    """段落级格式"""
    heading_level: int | None = None
    outline_level: int | None = None
    line_spacing: float | None = None
    line_spacing_rule: str | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    alignment: str | None = None
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
    hf_type: str = "default"
    has_text: bool = False
    text_content: str = ""
    has_image: bool = False
    has_page_number: bool = False
    image_count: int = 0

@dataclass
class SectionFormat:
    """文档节级格式"""
    section_index: int = 0
    margin_top_cm: float | None = None
    margin_bottom_cm: float | None = None
    margin_left_cm: float | None = None
    margin_right_cm: float | None = None
    page_width_cm: float | None = None
    page_height_cm: float | None = None
    section_break_type: str | None = None
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
    """格式统计摘要"""
    heading_stats: dict = field(default_factory=dict)
    body_stats: dict = field(default_factory=dict)
    non_black_paragraphs: list[dict] = field(default_factory=list)
    mixed_font_paragraphs: list[dict] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = []
        if self.heading_stats:
            lines.append("### 标题段落格式统计")
            for level, stats in sorted(self.heading_stats.items()):
                lines.append(f"  Heading {level}: 共{stats.get('count', 0)}个, "
                             f"字体={stats.get('font', '未知')}, "
                             f"字号={stats.get('size_pt', '?')}pt, "
                             f"加粗={stats.get('bold', '?')}")
                for a in stats.get("anomalies", []):
                    lines.append(f"    异常: 段落{a['para_index']} {a['issue']}")
        if self.body_stats:
            lines.append("### 正文段落格式统计")
            fd = self.body_stats.get("font_distribution", {})
            if fd:
                lines.append(f"  字体分布: {', '.join(f'{k}({v}%)' for k, v in fd.items())}")
            sd = self.body_stats.get("size_distribution", {})
            if sd:
                lines.append(f"  字号分布: {', '.join(f'{k}pt({v}%)' for k, v in sd.items())}")
        if self.non_black_paragraphs:
            lines.append("### 非黑色文字段落")
            for p in self.non_black_paragraphs[:20]:
                lines.append(f"  段落{p['para_index']}: 颜色={p.get('color', '?')}, "
                             f"内容=\"{p.get('text_snippet', '')[:30]}\"")
        if self.mixed_font_paragraphs:
            lines.append("### 混合字体段落")
            for p in self.mixed_font_paragraphs[:10]:
                lines.append(f"  段落{p['para_index']}: 字体={p.get('fonts', [])}")
        return "\n".join(lines)

@dataclass
class DocumentFormat:
    """文档整体格式元数据"""
    sections: list[SectionFormat] = field(default_factory=list)
    total_pages: int | None = None
    format_summary: FormatSummary | None = None

    def to_prompt_text(self) -> str:
        lines = [f"## 文档格式元数据\n### 文档结构（共 {len(self.sections)} 个 section）"]
        for s in self.sections:
            pr = f"段落 {s.para_range[0]}-{s.para_range[1]}" if s.para_range else "?"
            lines.append(f"Section {s.section_index}: {pr}, "
                         f"页码起始={s.page_number_start}, "
                         f"分节符={s.section_break_type}, "
                         f"首标题=\"{s.section_heading or '?'}\"")
            lines.append(f"  页边距: 上{s.margin_top_cm}cm 下{s.margin_bottom_cm}cm "
                         f"左{s.margin_left_cm}cm 右{s.margin_right_cm}cm")
            for h in s.headers:
                parts = []
                if h.has_text: parts.append(f"有文字\"{h.text_content[:30]}\"")
                if h.has_image: parts.append(f"有图片{h.image_count}张")
                if h.has_page_number: parts.append("有页码")
                if not parts: parts.append("无内容")
                lines.append(f"  页眉[{h.hf_type}]: {', '.join(parts)}")
            for f in s.footers:
                parts = []
                if f.has_text: parts.append(f"有文字\"{f.text_content[:30]}\"")
                if f.has_image: parts.append(f"有图片{f.image_count}张")
                if f.has_page_number: parts.append("有页码")
                if not parts: parts.append("无内容")
                lines.append(f"  页脚[{f.hf_type}]: {', '.join(parts)}")
            if s.estimated_page_count is not None:
                lines.append(f"  预估页数: {s.estimated_page_count}")
        if self.total_pages is not None:
            lines.append(f"\n总页数: {self.total_pages}")
        if self.format_summary:
            lines.append(self.format_summary.to_prompt_text())
        return "\n".join(lines)
```

- [ ] **Step 2: 给 `Paragraph` 添加 `format_info` 字段**

在 `src/models.py` 的 `Paragraph` dataclass 中，在 `table_data` 之后添加：

```python
    format_info: Optional[ParagraphFormat] = None
```

- [ ] **Step 3: 写测试验证数据模型**

创建 `src/reviewer/tests/test_models_format.py`：

```python
"""Test format-related data models."""
from src.models import (
    RunFormat, ParagraphFormat, HeaderFooterInfo,
    SectionFormat, FormatSummary, DocumentFormat, Paragraph,
)


def test_paragraph_format_info_default_none():
    p = Paragraph(index=0, text="hello")
    assert p.format_info is None


def test_paragraph_with_format_info():
    fmt = ParagraphFormat(
        heading_level=1,
        alignment="center",
        runs=[RunFormat(text="标题", font_name_east_asia="宋体", font_size_pt=16.0, bold=True)],
        dominant_font="宋体",
        dominant_size_pt=16.0,
    )
    p = Paragraph(index=0, text="标题", format_info=fmt)
    assert p.format_info.heading_level == 1
    assert p.format_info.runs[0].font_size_pt == 16.0


def test_document_format_to_prompt_text():
    doc_fmt = DocumentFormat(
        sections=[SectionFormat(
            section_index=0,
            margin_top_cm=2.54, margin_bottom_cm=2.54,
            margin_left_cm=3.17, margin_right_cm=3.17,
            para_range=(0, 45),
            section_heading="施工方案",
            page_number_start=1,
            headers=[HeaderFooterInfo(hf_type="default", has_image=True, image_count=1)],
            footers=[HeaderFooterInfo(hf_type="default", has_page_number=True)],
        )],
        total_pages=23,
        format_summary=FormatSummary(
            heading_stats={1: {"count": 5, "font": "宋体", "size_pt": 16, "bold": True}},
            non_black_paragraphs=[{"para_index": 23, "color": "FF0000", "text_snippet": "重要"}],
        ),
    )
    text = doc_fmt.to_prompt_text()
    assert "Section 0" in text
    assert "有图片1张" in text
    assert "有页码" in text
    assert "段落23" in text


def test_format_summary_to_prompt_text_empty():
    fs = FormatSummary()
    assert fs.to_prompt_text() == ""
```

- [ ] **Step 4: 运行测试**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_models_format.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/models.py src/reviewer/tests/test_models_format.py
git commit -m "feat(models): add format info dataclasses for anbiao review"
```

---

### Task 2: 扩展 docx_parser 提取格式信息

**Files:**
- Modify: `src/parser/docx_parser.py`
- Test: `src/reviewer/tests/test_docx_format_parser.py`

- [ ] **Step 1: 在 `docx_parser.py` 中添加格式提取辅助函数**

在文件顶部 import 之后添加：

```python
from src.models import Paragraph, RunFormat, ParagraphFormat, HeaderFooterInfo, SectionFormat, DocumentFormat, FormatSummary
from collections import Counter


def _twips_to_cm(twips: str | None) -> float | None:
    """Convert twips (1/20 point, 1440 twips = 1 inch = 2.54 cm) to cm."""
    if twips is None:
        return None
    try:
        return round(int(twips) / 1440 * 2.54, 2)
    except (ValueError, TypeError):
        return None


def _half_points_to_pt(val: str | None) -> float | None:
    """Convert half-points (w:sz value) to pt. sz=24 means 12pt."""
    if val is None:
        return None
    try:
        return int(val) / 2
    except (ValueError, TypeError):
        return None


def _extract_run_format(run_element, qn_func) -> RunFormat:
    """Extract format info from a w:r element."""
    text_parts = []
    for t in run_element.findall(qn_func("w:t")):
        if t.text:
            text_parts.append(t.text)
    text = "".join(text_parts)

    rf = RunFormat(text=text)
    rPr = run_element.find(qn_func("w:rPr"))
    if rPr is None:
        return rf

    # Font
    rFonts = rPr.find(qn_func("w:rFonts"))
    if rFonts is not None:
        rf.font_name_ascii = rFonts.get(qn_func("w:ascii"))
        rf.font_name_east_asia = rFonts.get(qn_func("w:eastAsia"))

    # Size
    sz = rPr.find(qn_func("w:sz"))
    if sz is not None:
        rf.font_size_pt = _half_points_to_pt(sz.get(qn_func("w:val")))

    # Color
    color = rPr.find(qn_func("w:color"))
    if color is not None:
        rf.font_color_rgb = color.get(qn_func("w:val"))

    # Bold
    b = rPr.find(qn_func("w:b"))
    if b is not None:
        val = b.get(qn_func("w:val"))
        rf.bold = val != "0" if val else True

    # Italic
    i = rPr.find(qn_func("w:i"))
    if i is not None:
        val = i.get(qn_func("w:val"))
        rf.italic = val != "0" if val else True

    # Underline
    u = rPr.find(qn_func("w:u"))
    if u is not None:
        rf.underline = u.get(qn_func("w:val"))

    return rf


def _extract_para_format(element, style_id_to_name, qn_func) -> ParagraphFormat:
    """Extract format info from a w:p element."""
    pf = ParagraphFormat()
    pPr = element.find(qn_func("w:pPr"))

    if pPr is not None:
        # Style → heading level
        pStyle = pPr.find(qn_func("w:pStyle"))
        if pStyle is not None:
            style_id = pStyle.get(qn_func("w:val"))
            style_name = style_id_to_name.get(style_id, style_id or "")
            if style_name.lower().startswith("heading"):
                try:
                    pf.heading_level = int(style_name.split()[-1])
                except (ValueError, IndexError):
                    pf.heading_level = 0

        # Outline level
        outlineLvl = pPr.find(qn_func("w:outlineLvl"))
        if outlineLvl is not None:
            try:
                pf.outline_level = int(outlineLvl.get(qn_func("w:val"), "0"))
            except ValueError:
                pass

        # Spacing
        spacing = pPr.find(qn_func("w:spacing"))
        if spacing is not None:
            line = spacing.get(qn_func("w:line"))
            line_rule = spacing.get(qn_func("w:lineRule"))
            pf.line_spacing_rule = line_rule
            if line:
                try:
                    line_val = int(line)
                    if line_rule == "auto" or line_rule is None:
                        pf.line_spacing = round(line_val / 240, 2)
                    else:
                        pf.line_spacing = round(line_val / 20, 2)
                except ValueError:
                    pass
            before = spacing.get(qn_func("w:before"))
            if before:
                pf.space_before_pt = _half_points_to_pt(before)
            after = spacing.get(qn_func("w:after"))
            if after:
                pf.space_after_pt = _half_points_to_pt(after)

        # Alignment
        jc = pPr.find(qn_func("w:jc"))
        if jc is not None:
            pf.alignment = jc.get(qn_func("w:val"))

        # Indent
        ind = pPr.find(qn_func("w:ind"))
        if ind is not None:
            pf.indent_left_cm = _twips_to_cm(ind.get(qn_func("w:left")))
            pf.indent_right_cm = _twips_to_cm(ind.get(qn_func("w:right")))
            first_line = ind.get(qn_func("w:firstLine"))
            if first_line:
                pf.indent_first_line_cm = _twips_to_cm(first_line)

    # Runs
    runs = []
    for r in element.findall(qn_func("w:r")):
        runs.append(_extract_run_format(r, qn_func))
    pf.runs = runs

    # Dominant calculations
    if runs:
        fonts = [r.font_name_east_asia or r.font_name_ascii for r in runs if r.font_name_east_asia or r.font_name_ascii]
        sizes = [r.font_size_pt for r in runs if r.font_size_pt is not None]
        colors = [r.font_color_rgb for r in runs if r.font_color_rgb is not None]
        if fonts:
            pf.dominant_font = Counter(fonts).most_common(1)[0][0]
        if sizes:
            pf.dominant_size_pt = Counter(sizes).most_common(1)[0][0]
        if colors:
            pf.dominant_color = Counter(colors).most_common(1)[0][0]
        pf.has_non_black_text = any(
            c and c.upper() not in ("000000", "auto", "FFFFFF")
            for c in colors
        )

    return pf
```

- [ ] **Step 2: 修改 `parse_docx` 函数签名添加 `extract_format` 参数**

修改 `parse_docx` 函数：

```python
def parse_docx(file_path: str, extract_format: bool = False) -> list[Paragraph]:
```

在段落创建部分，当 `extract_format=True` 时：

```python
            # 在 paragraphs.append(Paragraph(...)) 之前
            fmt = None
            if extract_format:
                fmt = _extract_para_format(element, style_id_to_name, qn)

            paragraphs.append(Paragraph(
                index=idx,
                text=text,
                style=style_name,
                is_table=False,
                table_data=None,
                format_info=fmt,
            ))
```

- [ ] **Step 3: 添加 `extract_document_format()` 函数**

在 `parse_docx` 函数之后添加：

```python
def extract_document_format(file_path: str) -> DocumentFormat:
    """提取文档级格式信息（sections/headers/footers/page setup）。"""
    from docx.oxml.ns import qn
    doc = Document(file_path)

    sections = []
    for si, section in enumerate(doc.sections):
        sf = SectionFormat(section_index=si)
        sectPr = section._sectPr

        # Page margins
        pgMar = sectPr.find(qn("w:pgMar"))
        if pgMar is not None:
            sf.margin_top_cm = _twips_to_cm(pgMar.get(qn("w:top")))
            sf.margin_bottom_cm = _twips_to_cm(pgMar.get(qn("w:bottom")))
            sf.margin_left_cm = _twips_to_cm(pgMar.get(qn("w:left")))
            sf.margin_right_cm = _twips_to_cm(pgMar.get(qn("w:right")))

        # Page size
        pgSz = sectPr.find(qn("w:pgSz"))
        if pgSz is not None:
            sf.page_width_cm = _twips_to_cm(pgSz.get(qn("w:w")))
            sf.page_height_cm = _twips_to_cm(pgSz.get(qn("w:h")))

        # Section break type
        sec_type = sectPr.find(qn("w:type"))
        if sec_type is not None:
            sf.section_break_type = sec_type.get(qn("w:val"))

        # Page number type
        pgNumType = sectPr.find(qn("w:pgNumType"))
        if pgNumType is not None:
            start = pgNumType.get(qn("w:start"))
            if start is not None:
                try:
                    sf.page_number_start = int(start)
                except ValueError:
                    pass
            sf.page_number_format = pgNumType.get(qn("w:fmt"))

        # Title page (different first page header/footer)
        titlePg = sectPr.find(qn("w:titlePg"))
        sf.has_different_first_page = titlePg is not None

        # Headers
        for hdr_ref in sectPr.findall(qn("w:headerReference")):
            hf_type = hdr_ref.get(qn("w:type")) or "default"
            rid = hdr_ref.get(qn("r:id"))
            hfi = HeaderFooterInfo(hf_type=hf_type)
            if rid and rid in doc.part.rels:
                _parse_hf_content(doc.part.rels[rid].target_part._element, hfi, qn)
            sf.headers.append(hfi)

        # Footers
        for ftr_ref in sectPr.findall(qn("w:footerReference")):
            hf_type = ftr_ref.get(qn("w:type")) or "default"
            rid = ftr_ref.get(qn("r:id"))
            hfi = HeaderFooterInfo(hf_type=hf_type)
            if rid and rid in doc.part.rels:
                _parse_hf_content(doc.part.rels[rid].target_part._element, hfi, qn)
            sf.footers.append(hfi)

        sections.append(sf)

    # Map sections to paragraph ranges
    _assign_section_para_ranges(doc, sections)

    return DocumentFormat(sections=sections)


def _parse_hf_content(hf_element, hfi: HeaderFooterInfo, qn_func):
    """解析页眉/页脚 XML 内容，检测文字、图片、页码域。"""
    from lxml import etree

    text_parts = []
    for p in hf_element.findall(f".//{qn_func('w:t')}"):
        if p.text and p.text.strip():
            text_parts.append(p.text.strip())
    if text_parts:
        hfi.has_text = True
        hfi.text_content = " ".join(text_parts)

    # Images (w:drawing)
    drawings = hf_element.findall(f".//{qn_func('w:drawing')}")
    if drawings:
        hfi.has_image = True
        hfi.image_count = len(drawings)

    # Page number fields: w:fldSimple containing PAGE, or w:fldChar sequence
    for fld in hf_element.findall(f".//{qn_func('w:fldSimple')}"):
        instr = fld.get(qn_func("w:instr")) or ""
        if "PAGE" in instr.upper():
            hfi.has_page_number = True
            break
    # Also check fldChar-based page numbering
    for instrText in hf_element.findall(f".//{qn_func('w:instrText')}"):
        if instrText.text and "PAGE" in instrText.text.upper():
            hfi.has_page_number = True
            break


def _assign_section_para_ranges(doc, sections: list[SectionFormat]):
    """Assign paragraph index ranges to each section."""
    from docx.oxml.ns import qn
    body = doc.element.body

    para_idx = 0
    section_para_starts = []
    current_section = 0

    for element in body:
        if element.tag == qn("w:p"):
            runs_text = []
            for r in element.findall(qn("w:r")):
                t = r.find(qn("w:t"))
                if t is not None and t.text:
                    runs_text.append(t.text)
            text = "".join(runs_text).strip()
            if not text:
                continue

            if current_section >= len(section_para_starts):
                section_para_starts.append(para_idx)

            # Check if this paragraph contains a section break
            pPr = element.find(qn("w:pPr"))
            if pPr is not None:
                sectPr = pPr.find(qn("w:sectPr"))
                if sectPr is not None:
                    current_section += 1

            para_idx += 1
        elif element.tag == qn("w:tbl"):
            if current_section >= len(section_para_starts):
                section_para_starts.append(para_idx)
            para_idx += 1

    # Also handle the final section (body-level sectPr)
    if current_section >= len(section_para_starts):
        section_para_starts.append(para_idx if para_idx > 0 else 0)

    # Assign ranges
    total_paras = para_idx
    for i, sf in enumerate(sections):
        start = section_para_starts[i] if i < len(section_para_starts) else 0
        end = section_para_starts[i + 1] - 1 if i + 1 < len(section_para_starts) else total_paras - 1
        sf.para_range = (start, end)
```

- [ ] **Step 4: 写测试**

创建 `src/reviewer/tests/test_docx_format_parser.py`：

```python
"""Test docx format extraction."""
import os
from src.parser.docx_parser import parse_docx, extract_document_format

# 使用项目中已有的投标文件做集成测试
_SAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "投标文档",
                        "响应文件-2025-2026年华师校园卡卡片采购项目-整合版20250311.docx")


def test_parse_docx_without_format():
    """extract_format=False 时行为不变，format_info 为 None。"""
    if not os.path.exists(_SAMPLE):
        return  # CI 中无样本文件时跳过
    paras = parse_docx(_SAMPLE, extract_format=False)
    assert len(paras) > 0
    assert all(p.format_info is None for p in paras)


def test_parse_docx_with_format():
    """extract_format=True 时每个段落都有 format_info。"""
    if not os.path.exists(_SAMPLE):
        return
    paras = parse_docx(_SAMPLE, extract_format=True)
    assert len(paras) > 0
    assert all(p.format_info is not None for p in paras)
    # 至少应该有一些段落检测到了字号
    has_size = any(p.format_info.dominant_size_pt is not None for p in paras)
    assert has_size


def test_extract_document_format():
    """提取文档级格式信息。"""
    if not os.path.exists(_SAMPLE):
        return
    doc_fmt = extract_document_format(_SAMPLE)
    assert len(doc_fmt.sections) >= 1
    s0 = doc_fmt.sections[0]
    assert s0.margin_top_cm is not None
    # 该样本文件有 header（含图片 logo）
    assert len(s0.headers) > 0
```

- [ ] **Step 5: 运行测试**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_docx_format_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/parser/docx_parser.py src/reviewer/tests/test_docx_format_parser.py
git commit -m "feat(parser): add format extraction to docx_parser for anbiao review"
```

---

### Task 3: 创建暗标规则模型和通用规则配置

**Files:**
- Create: `config/anbiao_default_rules.json`
- Create: `src/reviewer/anbiao_rule_parser.py` (dataclass only, parser logic in Chunk 2)

- [ ] **Step 1: 创建通用规则配置文件**

创建 `config/anbiao_default_rules.json`：

```json
[
  {
    "rule_text": "须编制连续的阿拉伯数字页码，第一页页码为\"1\"，页码在页面底端居中位置",
    "rule_type": "format",
    "is_mandatory": true,
    "category": "页码"
  },
  {
    "rule_text": "任何一页均不得设置页眉和页脚，只准出现页码",
    "rule_type": "format",
    "is_mandatory": true,
    "category": "页眉页脚"
  },
  {
    "rule_text": "所有文字均为黑色",
    "rule_type": "format",
    "is_mandatory": true,
    "category": "文字颜色"
  },
  {
    "rule_text": "如暗标文件分多个评审模块评审时，应分别编制各评审模块的暗标文件，每个评审模块的文件须独立生成连续的页码，正文第一页页码均为\"1\"",
    "rule_type": "format",
    "is_mandatory": true,
    "category": "分模块页码"
  },
  {
    "rule_text": "不得出现可识别投标人身份的任何字符、徽标、公司名称（包括简称、外文名称、外文简称）、公司网址（包括邮箱域名）、公司电话、资质证书编号、人员姓名、身份证号、证书编号、人员照片、可辨识的公章、企业标准名称或编号等",
    "rule_type": "content",
    "is_mandatory": true,
    "category": "身份信息"
  },
  {
    "rule_text": "不得出现过往业绩案例客户名称，如需体现客户名称应以\"某金融企业\"、\"某国有商业银行\"等代替",
    "rule_type": "content",
    "is_mandatory": true,
    "category": "客户名称"
  },
  {
    "rule_text": "不得出现任何涂改、行间插字或删除痕迹",
    "rule_type": "content",
    "is_mandatory": true,
    "category": "文档痕迹"
  },
  {
    "rule_text": "非必要不使用图片（包括人员照片、工作照片等）、图表、PPT幻灯片",
    "rule_type": "content",
    "is_mandatory": false,
    "category": "图片使用"
  },
  {
    "rule_text": "非必要不使用过往业绩案例",
    "rule_type": "content",
    "is_mandatory": false,
    "category": "业绩案例"
  },
  {
    "rule_text": "非必要不使用公司证书、人员证书",
    "rule_type": "content",
    "is_mandatory": false,
    "category": "证书使用"
  }
]
```

- [ ] **Step 2: 创建 `anbiao_rule_parser.py` 骨架（含 dataclass + load_default_rules）**

创建 `src/reviewer/anbiao_rule_parser.py`：

```python
"""暗标规则解析：拆分文档为逐条规则、LLM 分类、与通用规则合并。"""
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "anbiao_default_rules.json"
_CLASSIFY_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_rule_classify.txt"


@dataclass
class AnbiaoRule:
    rule_index: int
    rule_text: str
    rule_type: str           # "format" | "content"
    source_section: str = ""
    is_mandatory: bool = True
    category: str = ""

    @property
    def violation_level(self) -> str:
        return "fail" if self.is_mandatory else "warning"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["violation_level"] = self.violation_level
        return d


def load_default_rules() -> list[dict]:
    """加载通用暗标规则配置。"""
    with open(_DEFAULT_RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_rules(
    project_rules: list[AnbiaoRule],
    default_rules: list[dict],
) -> list[AnbiaoRule]:
    """合并项目规则和通用规则。项目规则覆盖同 category 的通用规则。"""
    project_categories = {r.category for r in project_rules if r.category}

    merged = list(project_rules)
    next_index = max((r.rule_index for r in project_rules), default=0) + 1

    for dr in default_rules:
        if dr.get("category") in project_categories:
            continue
        merged.append(AnbiaoRule(
            rule_index=next_index,
            rule_text=dr["rule_text"],
            rule_type=dr["rule_type"],
            source_section="通用规则",
            is_mandatory=dr.get("is_mandatory", True),
            category=dr.get("category", ""),
        ))
        next_index += 1

    return merged


def parse_anbiao_rules(file_path: str, api_settings: dict) -> list[AnbiaoRule]:
    """解析暗标规则文档为逐条规则列表。（详见 Chunk 2 Task 4 实现）"""
    raise NotImplementedError("Will be implemented in Chunk 2")
```

- [ ] **Step 3: 写测试**

创建 `src/reviewer/tests/test_anbiao_rule_parser.py`：

```python
"""Test anbiao rule parser utilities."""
from src.reviewer.anbiao_rule_parser import AnbiaoRule, load_default_rules, merge_rules


def test_load_default_rules():
    rules = load_default_rules()
    assert len(rules) >= 8
    assert all("rule_text" in r for r in rules)
    assert all(r["rule_type"] in ("format", "content") for r in rules)


def test_anbiao_rule_violation_level():
    mandatory = AnbiaoRule(rule_index=0, rule_text="test", rule_type="format", is_mandatory=True)
    advisory = AnbiaoRule(rule_index=1, rule_text="test", rule_type="content", is_mandatory=False)
    assert mandatory.violation_level == "fail"
    assert advisory.violation_level == "warning"


def test_merge_rules_project_overrides_default():
    project = [AnbiaoRule(rule_index=0, rule_text="自定义页码规则", rule_type="format", category="页码")]
    defaults = load_default_rules()
    merged = merge_rules(project, defaults)
    # 页码 category 被项目规则覆盖，不应出现默认的页码规则
    page_rules = [r for r in merged if r.category == "页码"]
    assert len(page_rules) == 1
    assert page_rules[0].rule_text == "自定义页码规则"


def test_merge_rules_default_supplements():
    project = [AnbiaoRule(rule_index=0, rule_text="test", rule_type="format", category="页码")]
    defaults = load_default_rules()
    merged = merge_rules(project, defaults)
    # 其他 category 的通用规则应被补充进来
    categories = {r.category for r in merged}
    assert "身份信息" in categories
    assert "图片使用" in categories
```

- [ ] **Step 4: 运行测试**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_anbiao_rule_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/anbiao_default_rules.json src/reviewer/anbiao_rule_parser.py src/reviewer/tests/test_anbiao_rule_parser.py
git commit -m "feat(anbiao): add rule dataclass, default rules config, and merge logic"
```

---

## Chunk 2: 暗标审查引擎

### Task 4: 实现暗标规则文档解析（LLM 分类）

**Files:**
- Modify: `src/reviewer/anbiao_rule_parser.py`
- Create: `config/prompts/anbiao_rule_classify.txt`

- [ ] **Step 1: 创建规则分类 prompt 模板**

创建 `config/prompts/anbiao_rule_classify.txt`：

```
你是暗标规则分析专家。请分析以下暗标规则文本，将每条规则分类。

## 规则文本
{rules_text}

请对每条规则输出 JSON 数组，每个元素包含：
- "rule_text": 原始规则文本
- "rule_type": "format"（排版格式类：页码、页眉页脚、字体字号、行距、页边距、颜色等）或 "content"（内容类：不得出现的信息、身份标识、图片使用等）
- "is_mandatory": true（强制要求："不得/不应/必须/要求"等）或 false（建议："建议/非必要/尽量"等）
- "category": 规则类别简称（如"页码"、"页眉页脚"、"身份信息"、"图片使用"等）
- "is_physical": true（仅在物理世界可审核：打印颜色、纸张、装订、封皮等）或 false（可在电子文档中审核）

请注意：
- 只返回 JSON 数组，不需要其他解释
- "is_physical" 为 true 的规则将被过滤掉，不参与电子文档审查
- 同一条规则可能包含多个子要求，请拆分为独立规则

输出格式：
```json
[
  {"rule_text": "...", "rule_type": "format", "is_mandatory": true, "category": "页码", "is_physical": false},
  ...
]
```
```

- [ ] **Step 2: 实现 `parse_anbiao_rules` 函数**

在 `src/reviewer/anbiao_rule_parser.py` 中替换占位实现：

```python
def parse_anbiao_rules(file_path: str, api_settings: dict) -> list[AnbiaoRule]:
    """解析暗标规则文档为逐条规则列表。

    流程：
    1. unified.py 解析文档
    2. tender_rule_splitter 构建章节索引
    3. 按最小章节拆分出规则文本
    4. LLM 分类每条规则
    """
    from src.parser.unified import parse_document
    from src.extractor.base import call_qwen, build_messages

    paragraphs = parse_document(file_path)
    if not paragraphs:
        logger.warning("暗标规则文档解析为空: %s", file_path)
        return []

    # 拼接全文给 LLM 分类
    rules_text = "\n".join(f"[{p.index}] {p.text}" for p in paragraphs if p.text.strip())

    prompt_template = _CLASSIFY_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{rules_text}", rules_text)
    messages = build_messages(system="你是暗标规则分析专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not isinstance(result, list):
        logger.error("LLM 规则分类返回格式错误: %s", type(result))
        return []

    rules = []
    for idx, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        # 过滤物理世界规则
        if item.get("is_physical", False):
            continue
        rules.append(AnbiaoRule(
            rule_index=idx,
            rule_text=item.get("rule_text", ""),
            rule_type=item.get("rule_type", "content"),
            source_section=item.get("source_section", "项目规则"),
            is_mandatory=item.get("is_mandatory", True),
            category=item.get("category", ""),
        ))

    logger.info("暗标规则解析: %d 条规则（已过滤物理世界规则）", len(rules))
    return rules
```

- [ ] **Step 3: Commit**

```bash
git add config/prompts/anbiao_rule_classify.txt src/reviewer/anbiao_rule_parser.py
git commit -m "feat(anbiao): implement rule document parsing with LLM classification"
```

---

### Task 5: 实现格式规则审查引擎

**Files:**
- Create: `src/reviewer/anbiao_reviewer.py`
- Create: `config/prompts/anbiao_format_review.txt`

- [ ] **Step 1: 创建格式审查 prompt 模板**

创建 `config/prompts/anbiao_format_review.txt`：

```
你是暗标格式审查专家。请根据以下规则和文档格式元数据，判断文档是否符合要求。

## 当前审查规则
{rule_text}

## 规则严重等级: {severity_level}
- mandatory: 违反判定为 fail
- advisory: 违反判定为 warning（建议性规则，仍需说明）

## 文档格式元数据
{document_format_text}

请判断文档是否符合上述规则，输出 JSON：
```json
{
  "result": "pass" 或 "fail" 或 "warning",
  "reason": "判断依据和不通过/警告的具体原因",
  "details": [
    {"location": "具体位置描述", "issue": "具体问题"}
  ]
}
```

注意：
- 仅基于提供的格式元数据判断，不要推测未提供的信息
- 如果元数据不足以判断（如无页数信息），请标注在 reason 中并给 warning
- details 数组中的每个元素描述一个具体违规位置
```

- [ ] **Step 2: 创建 `anbiao_reviewer.py` 中的格式审查函数**

创建 `src/reviewer/anbiao_reviewer.py`：

```python
"""暗标审查引擎：格式规则审查 + 内容规则审查。"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.extractor.base import call_qwen, build_messages
from src.models import Paragraph, DocumentFormat
from src.reviewer.anbiao_rule_parser import AnbiaoRule

logger = logging.getLogger(__name__)

_FORMAT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_format_review.txt"
_CONTENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review.txt"
_CONTENT_FINAL_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_content_review_final.txt"


def review_format_rules(
    rules: list[AnbiaoRule],
    doc_format: DocumentFormat,
    paragraphs: list[Paragraph],
    api_settings: dict,
    is_local_mode: bool = False,
) -> list[dict]:
    """逐条格式规则调 LLM 判断。返回 [{rule_index, rule_text, result, reason, details}]。"""
    prompt_template = _FORMAT_PROMPT_PATH.read_text(encoding="utf-8")
    doc_format_text = doc_format.to_prompt_text()
    results = []

    def _review_one(rule: AnbiaoRule) -> dict:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"
        prompt = (
            prompt_template
            .replace("{rule_text}", rule.rule_text)
            .replace("{severity_level}", severity_level)
            .replace("{document_format_text}", doc_format_text)
        )
        messages = build_messages(system="你是暗标格式审查专家。", user=prompt)
        llm_result = call_qwen(messages, api_settings)

        if not isinstance(llm_result, dict):
            return {
                "rule_index": rule.rule_index,
                "rule_text": rule.rule_text,
                "rule_type": "format",
                "result": "error",
                "reason": "LLM 调用失败",
                "details": [],
                "is_mandatory": rule.is_mandatory,
            }

        result_val = llm_result.get("result", "error")
        # 非强制规则：fail 降级为 warning
        if not rule.is_mandatory and result_val == "fail":
            result_val = "warning"

        return {
            "rule_index": rule.rule_index,
            "rule_text": rule.rule_text,
            "rule_type": "format",
            "result": result_val,
            "reason": llm_result.get("reason", ""),
            "details": llm_result.get("details", []),
            "is_mandatory": rule.is_mandatory,
        }

    if is_local_mode:
        for rule in rules:
            results.append(_review_one(rule))
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(_review_one, rule): rule for rule in rules}
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda r: r["rule_index"])
    return results
```

- [ ] **Step 3: Commit**

```bash
git add src/reviewer/anbiao_reviewer.py config/prompts/anbiao_format_review.txt
git commit -m "feat(anbiao): implement format rule review engine"
```

---

### Task 6: 实现内容规则审查引擎

**Files:**
- Modify: `src/reviewer/anbiao_reviewer.py`
- Create: `config/prompts/anbiao_content_review.txt`
- Create: `config/prompts/anbiao_content_review_final.txt`

- [ ] **Step 1: 创建内容审查 prompt 模板（中间批次）**

创建 `config/prompts/anbiao_content_review.txt`：

```
你是暗标内容审查专家。请检查以下投标文件片段是否违反暗标规则。

## 当前审查规则
{rule_text}

## 规则严重等级: {severity_level}
- mandatory: 违反标注为 fail
- advisory: 违反标注为 warning（建议性规则，请标注位置供人工确认）

{prev_context}

## 当前批次的投标文件内容
{tender_text}

请扫描上述内容，找出所有违反规则的位置。输出 JSON：
```json
{
  "candidates": [
    {
      "para_index": 段落编号（[N] 中的数字）,
      "text_snippet": "违规文本片段（20字以内）",
      "reason": "违规原因"
    }
  ],
  "summary": "本批次审查摘要"
}
```

注意：
- para_index 必须是文本中 [N] 标记的实际数字
- 对于图片标记 [图片: xxx]，如果图片内容可能违规也请标注
- 如本批次无违规内容，candidates 返回空数组
- advisory 规则：只要发现使用了图片/业绩案例/证书等，都应标注为 candidate
```

- [ ] **Step 2: 创建内容审查末批次 prompt 模板**

创建 `config/prompts/anbiao_content_review_final.txt`：

```
你是暗标内容审查专家。这是最后一批投标文件内容，请做出最终判定。

## 当前审查规则
{rule_text}

## 规则严重等级: {severity_level}
- mandatory: 违反判定为 fail
- advisory: 违反判定为 warning

## 前序批次审查摘要
{accumulated_summary}

## 前序批次候选违规项
{candidates_text}

## 当前批次（末批次）的投标文件内容
{tender_text}

综合所有批次的审查结果，做出最终判定。输出 JSON：
```json
{
  "result": "pass" 或 "fail" 或 "warning",
  "confidence": 0-100,
  "reason": "最终判定依据",
  "locations": [
    {
      "para_index": 段落编号,
      "text_snippet": "违规文本片段",
      "reason": "违规原因"
    }
  ],
  "retained_candidates": [保留的前序候选 para_index 列表]
}
```

注意：
- retained_candidates 只保留确实违规的前序候选，去掉误报
- advisory 规则：result 只能是 "pass" 或 "warning"，不会是 "fail"
- confidence 表示判定的置信度
```

- [ ] **Step 3: 在 `anbiao_reviewer.py` 中添加内容规则审查函数**

在 `review_format_rules` 之后添加：

```python
def review_content_rules(
    rules: list[AnbiaoRule],
    paragraphs: list[Paragraph],
    tender_index: dict,
    extracted_images: list[dict],
    doc_format: DocumentFormat,
    api_settings: dict,
    is_local_mode: bool = False,
    image_map: dict[str, str] | None = None,
    progress_callback=None,
) -> list[dict]:
    """内容规则按批次审查。复用 reviewer.py 的三阶段模式。

    Returns list of dicts, one per rule, each with:
      rule_index, rule_text, result, confidence, reason, tender_locations
    """
    from src.reviewer.tender_indexer import paragraphs_to_text, map_batch_indices_to_global
    from src.reviewer.reviewer import _build_multimodal_content, _IMAGE_MARKER_RE, assemble_multi_batch_result

    content_prompt_template = _CONTENT_PROMPT_PATH.read_text(encoding="utf-8")
    content_final_prompt_template = _CONTENT_FINAL_PROMPT_PATH.read_text(encoding="utf-8")

    # 页眉页脚文字也要审查
    hf_text_parts = []
    for section in doc_format.sections:
        for h in section.headers:
            if h.has_text:
                hf_text_parts.append(f"[页眉 Section{section.section_index} {h.hf_type}] {h.text_content}")
        for f in section.footers:
            if f.has_text:
                hf_text_parts.append(f"[页脚 Section{section.section_index} {f.hf_type}] {f.text_content}")
    hf_context = "\n".join(hf_text_parts) if hf_text_parts else ""

    # 分批逻辑：从 tender_index 的 chapters 提取段落范围
    chapters = tender_index.get("chapters", [])
    if not chapters:
        # 无章节时按段落数分批（每批约 50 段）
        batch_size = 50
        batches = []
        for i in range(0, len(paragraphs), batch_size):
            batch_paras = paragraphs[i:i + batch_size]
            batch_text = "\n".join(f"[{p.index}] {p.text}" for p in batch_paras)
            batches.append({"text": batch_text, "para_indices": [p.index for p in batch_paras]})
    else:
        batches = []
        if is_local_mode:
            # 本地模式：每章节一批
            for ch in chapters:
                start = ch.get("start_para", 0)
                end = ch.get("end_para", len(paragraphs) - 1)
                paras_in_node = [p for p in paragraphs if start <= p.index <= end]
                if paras_in_node:
                    batch_text = paragraphs_to_text(paras_in_node)
                    batches.append({"text": batch_text, "para_indices": [p.index for p in paras_in_node]})
        else:
            # 云端模式：多章节合并为一批（控制 token 量）
            from src.extractor.base import estimate_tokens
            current_batch_text = []
            current_batch_indices = []
            for ch in chapters:
                start = ch.get("start_para", 0)
                end = ch.get("end_para", len(paragraphs) - 1)
                paras_in_node = [p for p in paragraphs if start <= p.index <= end]
                if paras_in_node:
                    text = paragraphs_to_text(paras_in_node)
                    current_batch_text.append(text)
                    current_batch_indices.extend([p.index for p in paras_in_node])
                    if estimate_tokens("\n".join(current_batch_text)) > 15000:
                        batches.append({"text": "\n".join(current_batch_text), "para_indices": current_batch_indices})
                        current_batch_text = []
                        current_batch_indices = []
            if current_batch_text:
                batches.append({"text": "\n".join(current_batch_text), "para_indices": current_batch_indices})

    if not batches:
        batches = [{"text": "\n".join(f"[{p.index}] {p.text}" for p in paragraphs), "para_indices": [p.index for p in paragraphs]}]

    # 对每条内容规则，遍历所有批次
    all_results = []
    total_work = len(rules) * len(batches)
    done_work = 0

    for rule in rules:
        severity_level = "mandatory" if rule.is_mandatory else "advisory"
        accumulated_summary = ""
        all_candidates = []

        for bi, batch in enumerate(batches):
            is_final = (bi == len(batches) - 1)
            tender_text = batch["text"]
            if bi == 0 and hf_context:
                tender_text = f"## 页眉页脚内容\n{hf_context}\n\n## 正文内容\n{tender_text}"

            if is_final and len(batches) > 1:
                # 末批次：综合判定
                if all_candidates:
                    cand_lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
                    candidates_text = "\n".join(cand_lines)
                else:
                    candidates_text = "（无前序候选）"

                prompt = (
                    content_final_prompt_template
                    .replace("{rule_text}", rule.rule_text)
                    .replace("{severity_level}", severity_level)
                    .replace("{accumulated_summary}", accumulated_summary or "（首批次，无前序摘要）")
                    .replace("{candidates_text}", candidates_text)
                    .replace("{tender_text}", tender_text)
                )
            else:
                prev_context = ""
                if accumulated_summary:
                    prev_context = f"## 前序批次审查摘要\n{accumulated_summary}\n"
                if all_candidates:
                    lines = [f"- 段落{c['para_index']}: {c.get('reason', '')}" for c in all_candidates]
                    prev_context += f"\n## 前序批次候选批注\n" + "\n".join(lines)

                prompt = (
                    content_prompt_template
                    .replace("{rule_text}", rule.rule_text)
                    .replace("{severity_level}", severity_level)
                    .replace("{prev_context}", prev_context)
                    .replace("{tender_text}", tender_text)
                )

            # 多模态图片支持
            has_images = image_map and _IMAGE_MARKER_RE.search(prompt)
            if has_images:
                content = _build_multimodal_content(prompt, image_map)
                messages = [
                    {"role": "system", "content": "你是暗标内容审查专家。"},
                    {"role": "user", "content": content},
                ]
            else:
                messages = build_messages(system="你是暗标内容审查专家。", user=prompt)

            llm_result = call_qwen(messages, api_settings)
            done_work += 1
            if progress_callback:
                progress_callback(done_work, total_work)

            if not isinstance(llm_result, dict):
                continue

            if is_final and len(batches) > 1:
                # 末批次最终判定
                result_val = llm_result.get("result", "error")
                if not rule.is_mandatory and result_val == "fail":
                    result_val = "warning"

                final_result = {
                    "source_module": "anbiao",
                    "clause_index": rule.rule_index,
                    "clause_text": rule.rule_text,
                    "rule_type": "content",
                    "result": result_val,
                    "confidence": int(llm_result.get("confidence", 0)),
                    "reason": llm_result.get("reason", ""),
                    "severity": "critical" if rule.is_mandatory else "minor",
                    "is_mandatory": rule.is_mandatory,
                    "locations": llm_result.get("locations", []),
                    "retained_candidates": llm_result.get("retained_candidates", []),
                }
                assembled = assemble_multi_batch_result(final_result, all_candidates)
                all_results.append(assembled)
            elif not is_final:
                # 中间批次：累积候选
                new_candidates = llm_result.get("candidates", [])
                # 映射 batch-local para_index 到 global
                for c in new_candidates:
                    if isinstance(c, dict) and c.get("para_index") is not None:
                        all_candidates.append(c)
                summary = llm_result.get("summary", "")
                if summary:
                    accumulated_summary = f"{accumulated_summary}\n{summary}" if accumulated_summary else summary
            else:
                # 单批次直接判定
                result_val = llm_result.get("result", "error")
                if not rule.is_mandatory and result_val == "fail":
                    result_val = "warning"

                locations = llm_result.get("locations", [])
                if not locations:
                    # 单批次可能返回 candidates 而非 locations
                    candidates = llm_result.get("candidates", [])
                    if candidates and result_val != "pass":
                        locations = candidates

                tender_locations = []
                if locations:
                    para_indices = [loc["para_index"] for loc in locations if isinstance(loc, dict) and loc.get("para_index") is not None]
                    per_para_reasons = {loc["para_index"]: loc.get("reason", "") for loc in locations if isinstance(loc, dict) and loc.get("para_index") is not None}
                    if para_indices:
                        tender_locations.append({
                            "batch_id": "single_batch",
                            "path": "single",
                            "global_para_indices": para_indices,
                            "text_snippet": locations[0].get("text_snippet", "") if locations else "",
                            "per_para_reasons": per_para_reasons,
                        })

                all_results.append({
                    "source_module": "anbiao",
                    "clause_index": rule.rule_index,
                    "clause_text": rule.rule_text,
                    "rule_type": "content",
                    "result": result_val,
                    "confidence": int(llm_result.get("confidence", 0)),
                    "reason": llm_result.get("reason", ""),
                    "severity": "critical" if rule.is_mandatory else "minor",
                    "is_mandatory": rule.is_mandatory,
                    "tender_locations": tender_locations,
                })

    all_results.sort(key=lambda r: r["clause_index"])
    return all_results


def compute_anbiao_summary(format_results: list[dict], content_results: list[dict]) -> dict:
    """计算暗标审查汇总统计。"""
    all_items = format_results + content_results
    total = len(all_items)
    pass_count = sum(1 for r in all_items if r["result"] == "pass")
    fail_count = sum(1 for r in all_items if r["result"] == "fail")
    warning_count = sum(1 for r in all_items if r["result"] == "warning")
    error_count = sum(1 for r in all_items if r["result"] == "error")
    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warning": warning_count,
        "error": error_count,
        "format_total": len(format_results),
        "content_total": len(content_results),
    }
```

- [ ] **Step 4: Commit**

```bash
git add src/reviewer/anbiao_reviewer.py config/prompts/anbiao_content_review.txt config/prompts/anbiao_content_review_final.txt
git commit -m "feat(anbiao): implement content rule review engine with batch support"
```

---

## Chunk 3: 后端服务层（DB + API + Celery Task）

### Task 7: 创建数据库模型和迁移

**Files:**
- Create: `server/app/models/anbiao_review.py`
- Modify: `server/alembic/env.py`

- [ ] **Step 1: 创建 AnbiaoReview ORM 模型**

创建 `server/app/models/anbiao_review.py`：

```python
"""AnbiaoReview ORM model for anonymous bid review."""
import datetime
import uuid as _uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class AnbiaoReview(Base):
    __tablename__ = "anbiao_reviews"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    rule_file_path: Mapped[str | None] = mapped_column(String(1000))
    rule_file_name: Mapped[str | None] = mapped_column(String(500))
    tender_file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    tender_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    use_default_rules: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(200))

    parsed_rules: Mapped[dict | None] = mapped_column(JSONB)
    format_results: Mapped[list | None] = mapped_column(JSONB)
    content_results: Mapped[list | None] = mapped_column(JSONB)
    review_summary: Mapped[dict | None] = mapped_column(JSONB)
    annotated_file_path: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    user = relationship("User")
```

- [ ] **Step 2: 在 `server/alembic/env.py` 中导入新模型**

在 `from server.app.models.review_task import ReviewTask` 之后添加：

```python
from server.app.models.anbiao_review import AnbiaoReview  # noqa: F401
```

- [ ] **Step 3: 在 `server/app/main.py` 中导入新模型确保表创建**

在 `import server.app.models.review_task` 之后添加：

```python
import server.app.models.anbiao_review  # noqa: F401 — ensure table is created
```

- [ ] **Step 4: 生成 Alembic 迁移**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m alembic revision --autogenerate -m "add anbiao_reviews table"`

- [ ] **Step 5: Commit**

```bash
git add server/app/models/anbiao_review.py server/alembic/env.py server/app/main.py server/alembic/versions/
git commit -m "feat(db): add AnbiaoReview model and migration"
```

---

### Task 8: 创建暗标审查服务层和 API 路由

**Files:**
- Create: `server/app/services/anbiao_service.py`
- Create: `server/app/routers/anbiao_reviews.py`
- Modify: `server/app/main.py`

- [ ] **Step 1: 创建服务层**

创建 `server/app/services/anbiao_service.py`（参照 `review_service.py` 结构）：

```python
"""Business logic for anbiao (anonymous bid) review tasks."""
import os
import shutil
import uuid as _uuid

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.anbiao_review import AnbiaoReview

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}


async def create_anbiao_review(
    db: AsyncSession,
    tender_file: UploadFile,
    user_id: int,
    rule_file: UploadFile | None = None,
    use_default_rules: bool = True,
) -> AnbiaoReview:
    """Create an anbiao review task: save files, create DB record."""
    # Validate tender file
    tender_filename = tender_file.filename or "unknown"
    try:
        tender_filename = tender_filename.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    _, ext = os.path.splitext(tender_filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    tender_content = await tender_file.read()
    if len(tender_content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    review_id = _uuid.uuid4()
    review_dir = os.path.join(settings.DATA_DIR, "anbiao_reviews", str(review_id))
    os.makedirs(review_dir, exist_ok=True)

    tender_path = os.path.join(review_dir, tender_filename)
    with open(tender_path, "wb") as f:
        f.write(tender_content)

    # Save rule file if provided
    rule_path = None
    rule_name = None
    if rule_file and rule_file.filename:
        rule_name = rule_file.filename
        try:
            rule_name = rule_name.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        _, rule_ext = os.path.splitext(rule_name)
        if rule_ext.lower() not in ALLOWED_EXT:
            raise HTTPException(status_code=400, detail=f"规则文件不支持的类型: {rule_ext}")
        rule_content = await rule_file.read()
        rule_path = os.path.join(review_dir, f"rules_{rule_name}")
        with open(rule_path, "wb") as f:
            f.write(rule_content)

    review = AnbiaoReview(
        id=review_id,
        user_id=user_id,
        tender_file_path=tender_path,
        tender_file_name=tender_filename,
        rule_file_path=rule_path,
        rule_file_name=rule_name,
        use_default_rules=use_default_rules,
        status="pending",
        progress=0,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def get_anbiao_reviews(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20, q: str | None = None
):
    base = select(AnbiaoReview).where(AnbiaoReview.user_id == user_id)
    if q:
        base = base.where(AnbiaoReview.tender_file_name.ilike(f"%{q}%"))
    base = base.order_by(AnbiaoReview.created_at.desc())

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0
    result = await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return items, total


async def get_anbiao_review(db: AsyncSession, review_id: str, user_id: int) -> AnbiaoReview | None:
    try:
        rid = _uuid.UUID(review_id)
    except ValueError:
        return None
    result = await db.execute(
        select(AnbiaoReview).where(AnbiaoReview.id == rid, AnbiaoReview.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_anbiao_review(db: AsyncSession, review_id: str, user_id: int):
    review = await get_anbiao_review(db, review_id, user_id)
    if not review:
        raise HTTPException(status_code=404, detail="暗标审查任务不存在")
    review_dir = os.path.dirname(review.tender_file_path)
    if os.path.isdir(review_dir):
        shutil.rmtree(review_dir, ignore_errors=True)
    await db.delete(review)
    await db.commit()
```

- [ ] **Step 2: 创建 API 路由**

创建 `server/app/routers/anbiao_reviews.py`（参照 `reviews.py` 结构）：

```python
"""Router for anbiao (anonymous bid) review — create, list, detail, delete, progress, preview, download."""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.services.anbiao_service import (
    create_anbiao_review, get_anbiao_reviews, get_anbiao_review, delete_anbiao_review,
)

router = APIRouter(prefix="/api/anbiao-reviews", tags=["anbiao-reviews"])
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_anbiao_review_endpoint(
    tender_file: UploadFile = File(...),
    rule_file: UploadFile | None = File(None),
    use_default_rules: bool = Form(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_anbiao_review(db, tender_file, user.id, rule_file, use_default_rules)
    from server.app.tasks.anbiao_review_task import run_anbiao_review
    celery_result = run_anbiao_review.delay(str(review.id))
    review.celery_task_id = celery_result.id
    await db.commit()
    return {"id": str(review.id), "status": review.status}


@router.get("")
async def list_anbiao_reviews_endpoint(
    page: int = 1, page_size: int = 20, q: str | None = None,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    items, total = await get_anbiao_reviews(db, user.id, page, page_size, q)
    return {
        "items": [
            {
                "id": str(r.id),
                "tender_file_name": r.tender_file_name,
                "rule_file_name": r.rule_file_name,
                "status": r.status,
                "review_summary": r.review_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/{review_id}")
async def get_anbiao_review_endpoint(
    review_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    review = await get_anbiao_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="暗标审查任务不存在")
    return {
        "id": str(review.id),
        "tender_file_name": review.tender_file_name,
        "rule_file_name": review.rule_file_name,
        "use_default_rules": review.use_default_rules,
        "status": review.status,
        "progress": review.progress,
        "current_step": review.current_step,
        "error_message": review.error_message,
        "format_results": review.format_results,
        "content_results": review.content_results,
        "review_summary": review.review_summary,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


@router.delete("/{review_id}", status_code=204)
async def delete_anbiao_review_endpoint(
    review_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    await delete_anbiao_review(db, review_id, user.id)


@router.get("/{review_id}/progress")
async def anbiao_review_progress(
    review_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for anbiao review progress."""
    review = await get_anbiao_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="暗标审查任务不存在")

    celery_task_id = review.celery_task_id

    async def event_generator():
        nonlocal celery_task_id
        from celery.result import AsyncResult
        import asyncio, json

        while True:
            if not celery_task_id:
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
                await asyncio.sleep(2)
                await db.refresh(review)
                celery_task_id = review.celery_task_id
                continue

            result = AsyncResult(celery_task_id)
            if result.state == "PROGRESS":
                meta = result.info or {}
                yield f"data: {json.dumps(meta)}\n\n"
            elif result.state == "SUCCESS":
                await db.refresh(review)
                if review.status == "completed":
                    yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                    return
                elif review.status == "failed":
                    yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': review.error_message})}\n\n"
                    return
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': str(result.info)})}\n\n"
                return

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{review_id}/preview")
async def preview_anbiao_review(
    review_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    review = await get_anbiao_review(db, review_id, user.id)
    if not review or review.status != "completed":
        raise HTTPException(status_code=404, detail="审查结果不存在")

    summary = review.review_summary or {}
    preview_path = summary.get("preview_html_path")
    tender_html = None
    if preview_path and os.path.exists(preview_path):
        try:
            with open(preview_path, "r", encoding="utf-8") as f:
                tender_html = f.read()
        except Exception:
            tender_html = None

    if tender_html is None:
        from server.app.services.review_preview import build_preview_html
        all_items = (review.content_results or [])
        tender_html = build_preview_html(
            review.tender_file_path, all_items,
            summary.get("extracted_images", []), review_id,
        )

    return {
        "tender_html": tender_html,
        "format_results": review.format_results or [],
        "content_results": review.content_results or [],
        "summary": summary,
    }


@router.get("/{review_id}/download")
async def download_anbiao_review(
    review_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    review = await get_anbiao_review(db, review_id, user.id)
    if not review or not review.annotated_file_path or not os.path.exists(review.annotated_file_path):
        raise HTTPException(status_code=404, detail="审查报告不存在")
    return FileResponse(
        review.annotated_file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"暗标审查报告_{review.tender_file_name}",
    )


@router.get("/{review_id}/images/{filename}")
async def serve_anbiao_review_image(
    review_id: str, filename: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    review = await get_anbiao_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="暗标审查任务不存在")
    images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
    image_path = os.path.join(images_dir, filename)
    if not os.path.realpath(image_path).startswith(os.path.realpath(images_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")
    content_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
    return FileResponse(image_path, media_type=content_type)
```

- [ ] **Step 3: 在 `server/app/main.py` 中注册路由**

在 `app.include_router(config_router.router)` 之后添加：

```python
from server.app.routers import anbiao_reviews
app.include_router(anbiao_reviews.router)
```

- [ ] **Step 4: Commit**

```bash
git add server/app/services/anbiao_service.py server/app/routers/anbiao_reviews.py server/app/main.py
git commit -m "feat(api): add anbiao review service layer and API routes"
```

---

### Task 9: 创建 Celery 暗标审查管线

**Files:**
- Create: `server/app/tasks/anbiao_review_task.py`

- [ ] **Step 1: 创建暗标审查 Celery task**

创建 `server/app/tasks/anbiao_review_task.py`（参照 `review_task.py` 的结构，但使用暗标专有逻辑）：

```python
"""Celery task: run anbiao (anonymous bid) review pipeline."""
import logging
import os
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="run_anbiao_review")
def run_anbiao_review(self, review_id: str):
    """Anbiao review pipeline: parse rules -> parse tender -> format review -> content review -> generate report."""
    from server.app.models.anbiao_review import AnbiaoReview
    from src.parser.unified import parse_document
    from src.parser.docx_parser import parse_docx, extract_document_format
    from src.reviewer.image_extractor import extract_images
    from src.reviewer.tender_rule_splitter import build_tender_index
    from src.reviewer.anbiao_rule_parser import parse_anbiao_rules, load_default_rules, merge_rules, AnbiaoRule
    from src.reviewer.anbiao_reviewer import review_format_rules, review_content_rules, compute_anbiao_summary
    from src.reviewer.docx_annotator import generate_anbiao_review_docx
    from src.config import load_settings_from_db, load_settings
    from src.reviewer.reviewer import _IMAGE_MARKER_RE
    from src.models import DocumentFormat
    import datetime

    api_settings = load_settings_from_db() or load_settings()
    is_local_mode = "/v1" in (api_settings.get("api", {}).get("base_url", "").lower()) and "dashscope" not in api_settings.get("api", {}).get("base_url", "").lower()

    with Session(_sync_engine) as db:
        review = db.get(AnbiaoReview, _uuid.UUID(review_id))
        if not review:
            return {"error": "Anbiao review task not found"}

        try:
            # Step 1: Parse rules (0-5%)
            review.status = "indexing"
            review.progress = 0
            review.current_step = "解析暗标规则"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_rules", "progress": 0, "detail": "解析暗标规则"})

            project_rules = []
            if review.rule_file_path and os.path.exists(review.rule_file_path):
                project_rules = parse_anbiao_rules(review.rule_file_path, api_settings)

            default_rules = load_default_rules() if review.use_default_rules else []
            if project_rules:
                all_rules = merge_rules(project_rules, default_rules)
            else:
                # 无项目规则时，将通用规则直接转为 AnbiaoRule 列表
                all_rules = [
                    AnbiaoRule(
                        rule_index=i, rule_text=r["rule_text"], rule_type=r["rule_type"],
                        source_section="通用规则", is_mandatory=r.get("is_mandatory", True),
                        category=r.get("category", ""),
                    ) for i, r in enumerate(default_rules)
                ]

            review.parsed_rules = [r.to_dict() for r in all_rules]
            review.progress = 5
            db.commit()
            logger.info("暗标规则解析完成: %d 条规则", len(all_rules))

            format_rules = [r for r in all_rules if r.rule_type == "format"]
            content_rules = [r for r in all_rules if r.rule_type == "content"]

            # Step 2: Parse tender document (5-15%)
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 5, "detail": "解析标书文档"})
            review.current_step = "解析标书文档"
            db.commit()

            # 使用扩展的格式提取
            file_ext = os.path.splitext(review.tender_file_path)[1].lower()
            if file_ext in (".docx",):
                paragraphs = parse_docx(review.tender_file_path, extract_format=True)
                doc_format = extract_document_format(review.tender_file_path)
            else:
                paragraphs = parse_document(review.tender_file_path)
                doc_format = DocumentFormat()

            # Extract images
            review.progress = 8
            review.current_step = "提取图片"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 8, "detail": "提取图片"})

            images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
            extracted_images = extract_images(review.tender_file_path, images_dir)

            # Build index
            review.progress = 10
            review.current_step = "构建索引"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "parsing_tender", "progress": 10, "detail": "构建索引"})

            tender_index = build_tender_index(paragraphs, api_settings)

            # Inject image markers
            from dataclasses import replace as dc_replace
            index_to_pos = {p.index: pos for pos, p in enumerate(paragraphs)}
            image_by_para = {}
            for img in extracted_images:
                indices = img.get("near_para_indices") or ([img.get("near_para_index")] if img.get("near_para_index") is not None else [])
                for pi in indices:
                    image_by_para.setdefault(pi, []).append(img["filename"])

            for pi, filenames in image_by_para.items():
                pos = index_to_pos.get(pi)
                if pos is not None:
                    marker = " ".join(f"[图片: {fn}]" for fn in filenames)
                    paragraphs[pos] = dc_replace(paragraphs[pos], text=paragraphs[pos].text + f" {marker}")

            # Build image map for multimodal
            image_map = {}
            for img in extracted_images:
                image_map[img["filename"]] = os.path.join(images_dir, img["filename"])

            # Build format summary
            if paragraphs and paragraphs[0].format_info is not None:
                from src.models import FormatSummary
                from collections import Counter

                heading_stats = {}
                body_fonts = []
                body_sizes = []
                non_black = []

                for p in paragraphs:
                    fi = p.format_info
                    if fi is None:
                        continue
                    if fi.heading_level is not None:
                        lvl = fi.heading_level
                        if lvl not in heading_stats:
                            heading_stats[lvl] = {"count": 0, "font": fi.dominant_font, "size_pt": fi.dominant_size_pt, "bold": any(r.bold for r in fi.runs if r.bold), "anomalies": []}
                        heading_stats[lvl]["count"] += 1
                    else:
                        if fi.dominant_font:
                            body_fonts.append(fi.dominant_font)
                        if fi.dominant_size_pt:
                            body_sizes.append(fi.dominant_size_pt)
                    if fi.has_non_black_text:
                        non_black.append({"para_index": p.index, "color": fi.dominant_color, "text_snippet": p.text[:30]})

                font_dist = {}
                if body_fonts:
                    total_f = len(body_fonts)
                    for font, count in Counter(body_fonts).most_common():
                        font_dist[font] = round(count / total_f * 100)
                size_dist = {}
                if body_sizes:
                    total_s = len(body_sizes)
                    for size, count in Counter(body_sizes).most_common():
                        size_dist[str(size)] = round(count / total_s * 100)

                doc_format.format_summary = FormatSummary(
                    heading_stats=heading_stats,
                    body_stats={"font_distribution": font_dist, "size_distribution": size_dist},
                    non_black_paragraphs=non_black,
                )

            review.progress = 15
            db.commit()

            # Step 3: Format review (15-40%)
            self.update_state(state="PROGRESS", meta={"step": "format_review", "progress": 15, "detail": f"格式审查（{len(format_rules)}条规则）"})
            review.status = "reviewing"
            review.current_step = "格式审查"
            db.commit()

            format_results = review_format_rules(format_rules, doc_format, paragraphs, api_settings, is_local_mode) if format_rules else []

            review.format_results = format_results
            review.progress = 40
            db.commit()

            # Step 4: Content review (40-90%)
            self.update_state(state="PROGRESS", meta={"step": "content_review", "progress": 40, "detail": f"内容审查（{len(content_rules)}条规则）"})
            review.current_step = "内容审查"
            db.commit()

            def _content_progress(done, total):
                p = 40 + int(50 * done / max(total, 1))
                review.progress = min(p, 90)
                db.commit()
                self.update_state(state="PROGRESS", meta={"step": "content_review", "progress": review.progress, "detail": f"内容审查 ({done}/{total})"})

            content_results = review_content_rules(
                content_rules, paragraphs, tender_index, extracted_images,
                doc_format, api_settings, is_local_mode, image_map, _content_progress,
            ) if content_rules else []

            review.content_results = content_results
            review.progress = 90
            db.commit()

            # Step 5: Generate report (90-100%)
            self.update_state(state="PROGRESS", meta={"step": "generating", "progress": 90, "detail": "生成审查报告"})
            review.current_step = "生成报告"
            db.commit()

            summary = compute_anbiao_summary(format_results, content_results)
            summary["extracted_images"] = extracted_images

            # Generate annotated docx
            output_dir = os.path.dirname(review.tender_file_path)
            annotated_path = generate_anbiao_review_docx(
                review.tender_file_path,
                format_results, content_results, summary,
                rule_filename=review.rule_file_name or "通用规则",
                tender_filename=review.tender_file_name,
                output_dir=output_dir,
            )
            review.annotated_file_path = annotated_path

            # Generate preview HTML
            from server.app.services.review_preview import build_preview_html
            preview_html = build_preview_html(
                review.tender_file_path, content_results, extracted_images, review_id,
            )
            preview_path = os.path.join(output_dir, "preview.html")
            with open(preview_path, "w", encoding="utf-8") as f:
                f.write(preview_html)
            summary["preview_html_path"] = preview_path

            review.review_summary = summary
            review.status = "completed"
            review.progress = 100
            review.completed_at = datetime.datetime.now()
            db.commit()

            self.update_state(state="PROGRESS", meta={"step": "completed", "progress": 100})
            logger.info("暗标审查完成: %s", review_id)
            return {"status": "completed", "review_id": review_id}

        except Exception as e:
            logger.exception("暗标审查失败: %s", review_id)
            review.status = "failed"
            review.error_message = str(e)[:2000]
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "failed", "progress": 0, "error": str(e)[:500]})
            return {"error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add server/app/tasks/anbiao_review_task.py
git commit -m "feat(task): add Celery anbiao review pipeline"
```

---

### Task 10: 扩展 docx_annotator 支持暗标双表格报告

**Files:**
- Modify: `src/reviewer/docx_annotator.py`

- [ ] **Step 1: 在 `docx_annotator.py` 末尾添加 `generate_anbiao_review_docx` 函数**

```python
def generate_anbiao_review_docx(
    tender_file_path: str,
    format_results: list[dict],
    content_results: list[dict],
    summary: dict,
    rule_filename: str = "",
    tender_filename: str = "",
    output_dir: str | None = None,
) -> str:
    """Generate anbiao review docx with dual summary tables + highlights + comments."""
    doc = Document(tender_file_path)

    # Build para_review_map from content_results only (format results don't map to paragraphs)
    para_review_map = _build_para_review_map(content_results)

    comment_mgr = _CommentManager(doc)
    from docx.oxml.ns import qn
    body = doc.element.body

    para_idx = 0
    for element in body:
        tag = element.tag
        if tag == qn("w:p"):
            runs_text = []
            for r in element.findall(qn("w:r")):
                t = r.find(qn("w:t"))
                if t is not None and t.text:
                    runs_text.append(t.text)
            text = "".join(runs_text).strip()
            if not text:
                continue

            if para_idx in para_review_map:
                entries = para_review_map[para_idx]
                highlight_color = "red" if any(item["result"] == "fail" for item, _ in entries) else "yellow"
                _highlight_paragraph(element, highlight_color)
                for item, per_para_reason in entries:
                    result_label = {"pass": "合规", "fail": "不合规", "warning": "需注意"}.get(item["result"], item["result"])
                    display_reason = per_para_reason or item.get("reason", "")
                    comment_text = (
                        f"[暗标审查 #{item.get('clause_index', '')}] "
                        f"置信度: {item.get('confidence', 0)}%\n"
                        f"判定: {_result_symbol(item['result'])} {result_label}\n"
                        f"规则: {item.get('clause_text', '')}\n"
                        f"原因: {display_reason}"
                    )
                    comment_mgr.add_comment(element, comment_text)
            para_idx += 1
        elif tag == qn("w:tbl"):
            para_idx += 1

    # Insert summary at beginning
    original_count = len(list(body))
    _add_anbiao_summary_section(doc, format_results, content_results, summary, rule_filename, tender_filename)

    new_elements = list(body)[original_count:]
    for i, elem in enumerate(new_elements):
        body.remove(elem)
        body.insert(i, elem)

    if output_dir is None:
        output_dir = os.path.dirname(tender_file_path)
    output_filename = f"暗标审查报告_{os.path.basename(tender_file_path)}"
    output_path = os.path.join(output_dir, output_filename)
    doc.save(output_path)
    return output_path


def _add_anbiao_summary_section(doc, format_results, content_results, summary,
                                 rule_filename, tender_filename):
    """Insert anbiao summary with dual tables."""
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("暗标审查报告")
    run.bold = True
    run.font.size = Pt(18)

    meta = doc.add_paragraph()
    meta.add_run(f"暗标规则: {rule_filename}").font.size = Pt(10)
    meta.add_run("\n")
    meta.add_run(f"审查文件: {tender_filename}").font.size = Pt(10)
    meta.add_run("\n")
    meta.add_run(f"审查时间: {datetime.date.today().isoformat()}").font.size = Pt(10)

    stats = doc.add_paragraph()
    stats_text = f"共{summary['total']}条 | 通过{summary['pass']} | 不通过{summary['fail']} | 警告{summary['warning']}"
    stats.add_run(stats_text).font.size = Pt(10)

    # Format results table
    if format_results:
        doc.add_paragraph()
        fmt_title = doc.add_paragraph()
        fmt_title.add_run("格式审查结果").bold = True
        fmt_title.runs[0].font.size = Pt(14)

        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for i, h in enumerate(["序号", "规则", "结果", "说明"]):
            cell = table.rows[0].cells[i]
            cell.text = h
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(9)

        for idx, item in enumerate(format_results):
            row = table.add_row()
            row.cells[0].text = str(idx + 1)
            row.cells[1].text = item.get("rule_text", "")
            row.cells[2].text = _result_symbol(item.get("result", ""))
            row.cells[3].text = item.get("reason", "")
            # Color the result cell
            for p in row.cells[2].paragraphs:
                for r in p.runs:
                    r.font.color.rgb = _result_color(item.get("result", ""))
                    r.font.size = Pt(8)
            for cell in row.cells:
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8)

    # Content results table
    if content_results:
        doc.add_paragraph()
        ct_title = doc.add_paragraph()
        ct_title.add_run("内容审查结果").bold = True
        ct_title.runs[0].font.size = Pt(14)

        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for i, h in enumerate(["序号", "规则", "结果", "置信度", "说明"]):
            cell = table.rows[0].cells[i]
            cell.text = h
            for p in cell.paragraphs:
                for r in p.runs:
                    r.bold = True
                    r.font.size = Pt(9)

        for idx, item in enumerate(content_results):
            row = table.add_row()
            row.cells[0].text = str(idx + 1)
            row.cells[1].text = item.get("clause_text", "")
            row.cells[2].text = _result_symbol(item.get("result", ""))
            row.cells[3].text = f"{item.get('confidence', 0)}%"
            row.cells[4].text = item.get("reason", "")
            for p in row.cells[2].paragraphs:
                for r in p.runs:
                    r.font.color.rgb = _result_color(item.get("result", ""))
                    r.font.size = Pt(8)
            for cell in row.cells:
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8)

    doc.add_paragraph("─" * 60)
    doc.add_paragraph()
```

- [ ] **Step 2: Commit**

```bash
git add src/reviewer/docx_annotator.py
git commit -m "feat(annotator): add anbiao dual-table review docx generation"
```

---

## Chunk 4: 前端实现

### Task 11: API 客户端和 Store

**Files:**
- Create: `web/src/api/anbiao.ts`
- Create: `web/src/stores/anbiaoStore.ts`

- [ ] **Step 1: 创建 API 客户端**

创建 `web/src/api/anbiao.ts`：

```typescript
import client from './client'

export interface AnbiaoFormatResult {
  rule_index: number
  rule_text: string
  rule_type: 'format'
  result: 'pass' | 'fail' | 'warning' | 'error'
  reason: string
  details: Array<{ location: string; issue: string }>
  is_mandatory: boolean
}

export interface AnbiaoContentResult {
  clause_index: number
  clause_text: string
  rule_type: 'content'
  result: 'pass' | 'fail' | 'warning' | 'error'
  confidence: number
  reason: string
  is_mandatory: boolean
  tender_locations: Array<{
    global_para_indices: number[]
    text_snippet: string
    per_para_reasons: Record<number, string>
  }>
}

export interface AnbiaoSummary {
  total: number
  pass: number
  fail: number
  warning: number
  format_total: number
  content_total: number
}

export interface AnbiaoReviewTask {
  id: string
  tender_file_name: string
  rule_file_name: string | null
  status: string
  progress: number
  current_step: string | null
  error_message: string | null
  format_results: AnbiaoFormatResult[] | null
  content_results: AnbiaoContentResult[] | null
  review_summary: AnbiaoSummary | null
  created_at: string
}

export const anbiaoApi = {
  create(tenderFile: File, ruleFile: File | null, useDefaultRules: boolean = true) {
    const form = new FormData()
    form.append('tender_file', tenderFile)
    if (ruleFile) form.append('rule_file', ruleFile)
    form.append('use_default_rules', String(useDefaultRules))
    return client.post<{ id: string; status: string }>('/anbiao-reviews', form)
  },
  list(page = 1, pageSize = 20, q?: string) {
    return client.get('/anbiao-reviews', { params: { page, page_size: pageSize, q } })
  },
  get(id: string) {
    return client.get<AnbiaoReviewTask>(`/anbiao-reviews/${id}`)
  },
  delete(id: string) {
    return client.delete(`/anbiao-reviews/${id}`)
  },
  preview(id: string) {
    return client.get<{
      tender_html: string
      format_results: AnbiaoFormatResult[]
      content_results: AnbiaoContentResult[]
      summary: AnbiaoSummary
    }>(`/anbiao-reviews/${id}/preview`)
  },
  download(id: string) {
    return client.get(`/anbiao-reviews/${id}/download`, { responseType: 'blob' })
  },
}
```

- [ ] **Step 2: 创建 Store**

创建 `web/src/stores/anbiaoStore.ts`：

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { anbiaoApi } from '../api/anbiao'
import type { AnbiaoFormatResult, AnbiaoContentResult, AnbiaoSummary } from '../api/anbiao'

export type AnbiaoStage = 'upload' | 'processing' | 'preview'

export const useAnbiaoStore = defineStore('anbiao', () => {
  const stage = ref<AnbiaoStage>('upload')
  const currentReviewId = ref<string | null>(localStorage.getItem('current_anbiao_id'))
  const progress = ref(0)
  const currentStep = ref('')
  const detail = ref('')
  const error = ref<string | null>(null)

  const formatResults = ref<AnbiaoFormatResult[]>([])
  const contentResults = ref<AnbiaoContentResult[]>([])
  const summary = ref<AnbiaoSummary | null>(null)

  async function startReview(tenderFile: File, ruleFile: File | null, useDefaultRules: boolean) {
    error.value = null
    try {
      const res = await anbiaoApi.create(tenderFile, ruleFile, useDefaultRules)
      currentReviewId.value = res.data.id
      localStorage.setItem('current_anbiao_id', res.data.id)
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建暗标审查任务失败'
      throw e
    }
  }

  const STEP_LABELS: Record<string, string> = {
    parsing_rules: '解析规则',
    parsing_tender: '解析标书',
    merging: '合并规则',
    format_review: '格式审查',
    content_review: '内容审查',
    generating: '生成报告',
  }

  function handleProgressEvent(event: { progress: number; step: string; detail?: string; error?: string }) {
    progress.value = event.progress
    currentStep.value = event.step
    detail.value = event.detail || STEP_LABELS[event.step] || ''
    error.value = event.error || null
    if (event.step === 'completed') stage.value = 'preview'
    else if (event.step === 'failed') error.value = event.error || '审查失败'
  }

  async function loadReviewState() {
    if (!currentReviewId.value) return
    try {
      const res = await anbiaoApi.get(currentReviewId.value)
      const review = res.data
      progress.value = review.progress || 0
      currentStep.value = review.current_step || ''
      formatResults.value = review.format_results || []
      contentResults.value = review.content_results || []
      summary.value = review.review_summary || null
      error.value = review.error_message || null

      const statusMap: Record<string, AnbiaoStage> = {
        pending: 'processing', indexing: 'processing', reviewing: 'processing',
        completed: 'preview', failed: 'upload',
      }
      stage.value = statusMap[review.status] || 'processing'
    } catch {
      resetToUpload()
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    currentReviewId.value = null
    localStorage.removeItem('current_anbiao_id')
    progress.value = 0
    currentStep.value = ''
    detail.value = ''
    formatResults.value = []
    contentResults.value = []
    summary.value = null
    error.value = null
  }

  return {
    stage, currentReviewId, progress, currentStep, detail, error,
    formatResults, contentResults, summary,
    startReview, handleProgressEvent, loadReviewState, resetToUpload,
  }
})
```

- [ ] **Step 3: Commit**

```bash
git add web/src/api/anbiao.ts web/src/stores/anbiaoStore.ts
git commit -m "feat(frontend): add anbiao API client and store"
```

---

### Task 12: 前端页面和组件

**Files:**
- Create: `web/src/views/AnbiaoReviewView.vue`
- Create: `web/src/components/AnbiaoUploadStage.vue`
- Create: `web/src/components/AnbiaoPreviewStage.vue`
- Modify: `web/src/router/index.ts`
- Modify: `web/src/components/AppSidebar.vue`

- [ ] **Step 1: 创建上传组件 `AnbiaoUploadStage.vue`**

参照 `ReviewUploadStage.vue` 结构，但改为双文件上传 + 通用规则勾选框。具体内容请参照设计文档 Part 3 Section 3.3 的 UI 描述实现。

- [ ] **Step 2: 创建预览组件 `AnbiaoPreviewStage.vue`**

参照 `ReviewPreviewStage.vue` 结构，增加格式/内容 tab 切换。左侧文档 HTML + 右侧批注面板 + 左右联动。具体内容请参照设计文档 Part 3 Section 3.3（修订）的 UI 描述实现。

- [ ] **Step 3: 创建主页面 `AnbiaoReviewView.vue`**

创建 `web/src/views/AnbiaoReviewView.vue`：

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useAnbiaoStore } from '../stores/anbiaoStore'
import { useSSE } from '../composables/useSSE'
import AnbiaoUploadStage from '../components/AnbiaoUploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import AnbiaoPreviewStage from '../components/AnbiaoPreviewStage.vue'

const store = useAnbiaoStore()

const anbiaoSteps = [
  { key: 'parsing_rules', label: '解析规则' },
  { key: 'parsing_tender', label: '解析标书' },
  { key: 'format_review', label: '格式审查' },
  { key: 'content_review', label: '内容审查' },
  { key: 'generating', label: '生成报告' },
]

onMounted(async () => {
  if (store.currentReviewId && store.stage === 'upload') {
    await store.loadReviewState()
  }
})

let sseInstance: ReturnType<typeof useSSE> | null = null

function connectSSE(reviewId: string) {
  if (sseInstance) sseInstance.disconnect()
  sseInstance = useSSE(reviewId, `/api/anbiao-reviews/${reviewId}/progress`)
  watch(sseInstance.progress, (event) => {
    if (event) store.handleProgressEvent(event)
  })
  sseInstance.connect()
}

function disconnectSSE() {
  if (sseInstance) { sseInstance.disconnect(); sseInstance = null }
}

watch(() => store.stage, (s) => {
  if (s === 'processing' && store.currentReviewId) connectSSE(store.currentReviewId)
  else if (s !== 'processing') disconnectSSE()
}, { immediate: true })

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <AnbiaoUploadStage v-if="store.stage === 'upload'" />
    <ProcessingStage
      v-else-if="store.stage === 'processing'"
      :filename="'暗标审查'"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.detail"
      mode="processing"
      :custom-steps="anbiaoSteps"
      :error="store.error"
      @retry="store.currentReviewId && connectSSE(store.currentReviewId)"
    />
    <AnbiaoPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>
```

- [ ] **Step 4: 修改路由**

在 `web/src/router/index.ts` 的 children 数组中，`bid-review` 之后添加：

```typescript
      {
        path: 'anbiao-review',
        name: 'anbiao-review',
        component: () => import('../views/AnbiaoReviewView.vue'),
      },
```

- [ ] **Step 5: 修改侧边栏**

在 `web/src/components/AppSidebar.vue` 中：

1. 顶部 import 添加：`EyeOff` icon
2. `navItems` 数组中 `bid-review` 之后添加：

```typescript
  { path: '/anbiao-review', label: '暗标审查', icon: EyeOff, group: 'main' },
```

- [ ] **Step 6: 修改审查结果列表页**

在 `web/src/views/ReviewResultsView.vue` 中增加暗标审查结果的展示（添加 tab 切换和"暗标" badge）。

- [ ] **Step 7: Commit**

```bash
git add web/src/views/AnbiaoReviewView.vue web/src/components/AnbiaoUploadStage.vue web/src/components/AnbiaoPreviewStage.vue web/src/router/index.ts web/src/components/AppSidebar.vue web/src/views/ReviewResultsView.vue
git commit -m "feat(frontend): add anbiao review pages, components, and navigation"
```

---

## Chunk 5: 集成测试和收尾

### Task 13: 后端集成测试

**Files:**
- Create: `server/tests/test_anbiao_review.py`

- [ ] **Step 1: 编写集成测试**

测试完整的 API 流程：创建任务、查询状态、列表、删除。

- [ ] **Step 2: 运行测试**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_anbiao_review.py -v`

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_anbiao_review.py
git commit -m "test: add anbiao review API integration tests"
```

---

### Task 14: 端到端验证

- [ ] **Step 1: 启动后端服务**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && docker-compose up -d`

- [ ] **Step 2: 运行 Alembic 迁移**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m alembic upgrade head`

- [ ] **Step 3: 启动前端 dev server**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npm run dev`

- [ ] **Step 4: 手动测试完整流程**

1. 打开浏览器访问前端
2. 侧边栏确认"暗标审查"入口可见
3. 上传暗标规则文档 + 投标文件
4. 观察进度推送
5. 查看格式/内容审查结果
6. 下载审查报告 docx 验证双表格和批注

- [ ] **Step 5: Final commit**

```bash
git commit --allow-empty -m "feat: anbiao review feature complete"
```
