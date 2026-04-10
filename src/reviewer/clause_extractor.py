"""Extract review clauses from bid analysis extracted_data."""
import re

_UNCLEAR_VALUES = {"未明确", "未提及", "未说明", "未规定", "未要求", "不明确", "待定"}

_PARA_INDEX_RE = re.compile(r"\[(\d+)\]")


def _parse_para_indices(text: str) -> list[int]:
    """从文本中提取 [N] 格式的段落索引。"""
    return [int(m.group(1)) for m in _PARA_INDEX_RE.finditer(text)]


def _build_enriched_basis(
    basis_text: str,
    source_text: str,
    tagged_paragraphs: list,
) -> str:
    """用原文段落丰富 basis_text。

    从 basis_text 和 source_text 中解析段落索引，
    从 tagged_paragraphs 中取完整原文拼接到 basis_text 后面。
    """
    indices = _parse_para_indices(basis_text) + _parse_para_indices(source_text)
    if not indices or not tagged_paragraphs:
        return basis_text

    para_map = {p.index: p.text for p in tagged_paragraphs}
    context_lines = []
    seen = set()
    for idx in indices:
        if idx in seen:
            continue
        seen.add(idx)
        text = para_map.get(idx)
        if text:
            context_lines.append(f"[{idx}] {text}")

    if not context_lines:
        return basis_text

    return f"{basis_text}\n\n--- 原文段落 ---\n" + "\n".join(context_lines)


def _find_column(columns: list[str], *keywords: str) -> int | None:
    """Find column index by keyword match."""
    for i, col in enumerate(columns):
        for kw in keywords:
            if kw in col:
                return i
    return None


def _extract_module_clauses(
    modules: dict, module_key: str, severity: str,
    tagged_paragraphs: list | None = None,
    text_cols: tuple[str, ...] = ("风险项", "条件", "要求", "内容", "评分"),
    basis_cols: tuple[str, ...] = ("原文依据", "依据", "说明"),
    source_cols: tuple[str, ...] = ("来源章节", "来源", "章节"),
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
        source_idx = None
        for col_name in source_cols:
            source_idx = _find_column(columns, col_name)
            if source_idx is not None:
                break

        for i, row in enumerate(section.get("rows", [])):
            clause_text = row[text_idx] if text_idx is not None and text_idx < len(row) else ""
            basis_text = row[basis_idx] if basis_idx is not None and basis_idx < len(row) else ""
            source_text = row[source_idx] if source_idx is not None and source_idx < len(row) else ""
            if not clause_text or clause_text.strip() in _UNCLEAR_VALUES:
                continue

            if tagged_paragraphs:
                basis_text = _build_enriched_basis(basis_text, source_text, tagged_paragraphs)

            clauses.append({
                "source_module": module_key,
                "clause_index": i,
                "clause_text": clause_text,
                "basis_text": basis_text,
                "severity": severity,
            })
    return clauses


def extract_review_clauses(extracted_data: dict, tagged_paragraphs: list | None = None) -> list[dict]:
    """Extract all review clauses from extracted_data, ordered by priority.

    Each clause gets a globally unique clause_index across all modules.
    When tagged_paragraphs is provided, basis_text is enriched with full
    original paragraph text referenced by [N] indices in extraction results.
    """
    modules = extracted_data.get("modules", {})
    clauses = []
    # P0: 废标条款
    clauses.extend(_extract_module_clauses(modules, "module_e", "critical", tagged_paragraphs))
    # P1: 资格条件 + 编制要求
    clauses.extend(_extract_module_clauses(modules, "module_b", "major", tagged_paragraphs))
    clauses.extend(_extract_module_clauses(modules, "module_f", "major", tagged_paragraphs))
    # P2: 技术评分
    clauses.extend(_extract_module_clauses(modules, "module_c", "minor", tagged_paragraphs))

    # 重新分配全局唯一的 clause_index（各模块内部编号会重复）
    for i, clause in enumerate(clauses):
        clause["clause_index"] = i

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
