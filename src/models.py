from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class RunFormat:
    """单个 run 的字符级格式"""
    text: str = ""
    font_name_ascii: Optional[str] = None
    font_name_east_asia: Optional[str] = None   # 中文字体（如"宋体"）
    font_size_pt: Optional[float] = None         # 字号（磅值）
    font_color_rgb: Optional[str] = None         # 颜色 hex（如"000000"=黑色）
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[str] = None


@dataclass
class ParagraphFormat:
    """段落级格式"""
    heading_level: Optional[int] = None         # None=正文, 1=H1, 2=H2...
    outline_level: Optional[int] = None
    line_spacing: Optional[float] = None        # 行距倍数
    line_spacing_rule: Optional[str] = None     # auto/exact/atLeast
    space_before_pt: Optional[float] = None
    space_after_pt: Optional[float] = None
    alignment: Optional[str] = None             # left/center/right/both
    indent_left_cm: Optional[float] = None
    indent_right_cm: Optional[float] = None
    indent_first_line_cm: Optional[float] = None
    runs: list[RunFormat] = field(default_factory=list)
    dominant_font: Optional[str] = None
    dominant_size_pt: Optional[float] = None
    dominant_color: Optional[str] = None
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
    margin_top_cm: Optional[float] = None
    margin_bottom_cm: Optional[float] = None
    margin_left_cm: Optional[float] = None
    margin_right_cm: Optional[float] = None
    page_width_cm: Optional[float] = None
    page_height_cm: Optional[float] = None
    section_break_type: Optional[str] = None
    para_range: Optional[tuple[int, int]] = None
    section_heading: Optional[str] = None
    headers: list[HeaderFooterInfo] = field(default_factory=list)
    has_different_first_page: bool = False
    has_even_odd_headers: bool = False
    footers: list[HeaderFooterInfo] = field(default_factory=list)
    page_number_start: Optional[int] = None
    page_number_format: Optional[str] = None
    estimated_page_count: Optional[int] = None
    page_range: Optional[tuple[int, int]] = None


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
    total_pages: Optional[int] = None
    format_summary: Optional[FormatSummary] = None

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


@dataclass
class Paragraph:
    index: int
    text: str
    source_file: str = ""  # 来自哪个源文件
    style: Optional[str] = None
    is_table: bool = False
    table_data: Optional[list] = None
    format_info: Optional[ParagraphFormat] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaggedParagraph:
    index: int
    text: str
    section_title: Optional[str] = None
    section_level: int = 0
    tags: list[str] = field(default_factory=list)
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)
