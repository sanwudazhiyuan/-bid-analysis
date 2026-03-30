"""Extract review clauses from bid analysis extracted_data."""


def _find_column(columns: list[str], *keywords: str) -> int | None:
    """Find column index by keyword match."""
    for i, col in enumerate(columns):
        for kw in keywords:
            if kw in col:
                return i
    return None


def _extract_module_clauses(
    modules: dict, module_key: str, severity: str,
    text_cols: tuple[str, ...] = ("风险项", "条件", "要求", "内容", "评分"),
    basis_cols: tuple[str, ...] = ("原文依据", "依据", "说明"),
) -> list[dict]:
    """Extract clauses from a module's sections."""
    clauses = []
    module = modules.get(module_key, {})
    if not module:
        return clauses

    for section in module.get("sections", []):
        columns = section.get("columns", [])
        text_idx = None
        for col_name in text_cols:
            text_idx = _find_column(columns, col_name)
            if text_idx is not None:
                break
        basis_idx = None
        for col_name in basis_cols:
            basis_idx = _find_column(columns, col_name)
            if basis_idx is not None:
                break

        for i, row in enumerate(section.get("rows", [])):
            clause_text = row[text_idx] if text_idx is not None and text_idx < len(row) else ""
            basis_text = row[basis_idx] if basis_idx is not None and basis_idx < len(row) else ""
            if not clause_text:
                continue
            clauses.append({
                "source_module": module_key,
                "clause_index": i,
                "clause_text": clause_text,
                "basis_text": basis_text,
                "severity": severity,
            })
    return clauses


def extract_review_clauses(extracted_data: dict) -> list[dict]:
    """Extract all review clauses from extracted_data, ordered by priority."""
    modules = extracted_data.get("modules", {})
    clauses = []
    # P0: 废标条款
    clauses.extend(_extract_module_clauses(modules, "module_e", "critical"))
    # P1: 资格条件 + 编制要求
    clauses.extend(_extract_module_clauses(modules, "module_b", "major"))
    clauses.extend(_extract_module_clauses(modules, "module_f", "major"))
    # P2: 技术评分
    clauses.extend(_extract_module_clauses(modules, "module_c", "minor"))
    return clauses


def extract_project_context(extracted_data: dict) -> str:
    """Extract project context from module_a for use in review prompts."""
    modules = extracted_data.get("modules", {})
    module_a = modules.get("module_a", {})
    if not module_a:
        return ""

    lines = []
    for section in module_a.get("sections", []):
        rows = section.get("rows", [])
        for row in rows:
            if len(row) >= 2:
                lines.append(f"{row[0]}: {row[1]}")
            elif len(row) == 1:
                lines.append(row[0])
    return "\n".join(lines)
