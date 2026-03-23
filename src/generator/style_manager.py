"""StyleManager — apply configured styles to python-docx paragraphs, runs and cells."""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from src.config import load_styles


def _parse_hex_color(hex_str: str) -> RGBColor:
    """Convert '#1a5276' to RGBColor(0x1a, 0x52, 0x76)."""
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class StyleManager:
    """Load styles from config/styles.yaml and apply them to docx elements."""

    def __init__(self) -> None:
        raw = load_styles()
        # The YAML has a top-level 'styles' key
        self.styles: dict = raw.get("styles", raw)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def apply_run_style(self, run, style_name: str) -> None:
        """Apply font, size, bold, color to a single Run."""
        cfg = self.styles.get(style_name, {})

        if "font" in cfg:
            run.font.name = cfg["font"]
            # Also set East-Asian font (needed for CJK characters)
            run._element.rPr.rFonts.set(qn("w:eastAsia"), cfg["font"])

        if "size" in cfg:
            run.font.size = Pt(cfg["size"])

        if "bold" in cfg:
            run.font.bold = cfg["bold"]

        if "color" in cfg:
            run.font.color.rgb = _parse_hex_color(cfg["color"])

    def apply_paragraph_style(self, paragraph, style_name: str) -> None:
        """Apply style to every run in *paragraph*.

        If the paragraph has no runs (e.g. just created), there is typically
        one run already populated by python-docx when text was set via
        ``add_paragraph(text)``.
        """
        for run in paragraph.runs:
            self.apply_run_style(run, style_name)

    def apply_cell_style(self, cell, style_name: str) -> None:
        """Apply style to all runs in a table cell, plus bg_color shading."""
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                self.apply_run_style(run, style_name)

        cfg = self.styles.get(style_name, {})
        if "bg_color" in cfg:
            self._set_cell_bg_color(cell, cfg["bg_color"])

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _set_cell_bg_color(cell, hex_color: str) -> None:
        """Set the background / shading fill colour on a table cell."""
        color_val = hex_color.lstrip("#").upper()
        tc = cell._tc
        tc_pr = tc.get_or_add_tcPr()
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), color_val)
        tc_pr.append(shading)
