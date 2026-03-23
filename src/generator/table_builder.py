"""Table builder for generating tables in .docx documents."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument


class TableBuilder:
    """Builds Word tables from structured section dicts.

    Parameters
    ----------
    style_manager : optional
        A StyleManager instance used to apply styles to header and body cells.
        When *None* (the default), no styling is applied.
    """

    def __init__(self, style_manager: Optional[Any] = None) -> None:
        self._style_manager = style_manager

    def build(self, section: Dict[str, Any], doc: "DocxDocument") -> None:
        """Create a table inside *doc* based on a *section* dict.

        Expected keys in *section*:
            - ``columns`` – list of column header strings
            - ``rows``    – list of lists (each inner list is one data row)
            - ``title``   – (optional) heading text to insert before the table
            - ``type``    – (informational) e.g. ``"key_value_table"``,
              ``"standard_table"``
        """
        columns: List[str] = section.get("columns", [])
        rows: List[List[str]] = section.get("rows", [])
        title: Optional[str] = section.get("title")

        # ---- optional title paragraph ----
        if title:
            doc.add_paragraph(title)

        # ---- create table (header + data rows) ----
        num_data_rows = len(rows)
        num_cols = len(columns)
        table = doc.add_table(rows=num_data_rows + 1, cols=num_cols)

        # ---- fill header row ----
        header_row = table.rows[0]
        for idx, col_name in enumerate(columns):
            cell = header_row.cells[idx]
            cell.text = col_name
            if self._style_manager is not None:
                self._style_manager.apply_cell_style(cell, "table_header")

        # ---- fill data rows ----
        for row_idx, row_data in enumerate(rows):
            row = table.rows[row_idx + 1]
            for col_idx, value in enumerate(row_data):
                cell = row.cells[col_idx]
                cell.text = str(value)
                if self._style_manager is not None:
                    self._style_manager.apply_cell_style(cell, "table_body")
