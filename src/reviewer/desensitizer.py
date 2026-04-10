"""PII desensitization for tender documents.

Detects and masks personal information (phone numbers, ID cards, emails,
bank accounts, names in context) before LLM review to protect privacy.
"""
import re
from dataclasses import replace
from src.models import Paragraph


# ── Regex patterns ──────────────────────────────────────────────────
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# ID card: region(6) + birth(8: YYYYMMDD) + seq(3) + check(1)
_ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")

# Context-based name detection: keyword + delimiter + 2-4 Chinese chars
_NAME_CONTEXT_RE = re.compile(
    r"(?:联系人|项目经理|项目负责人|法定代表人|授权代表|负责人|经办人|签字人|投标人代表)"
    r"[：:\s]*"
    r"([\u4e00-\u9fff]{2,4})"
)

# Ordered by specificity: ID card before bank account (18 digits vs 16-19)
_PATTERNS = [
    ("身份证", _ID_CARD_RE),
    ("电话", _PHONE_RE),
    ("邮箱", _EMAIL_RE),
    ("银行账号", _BANK_RE),
]


class _PlaceholderRegistry:
    """Tracks PII values → placeholders, deduplicating identical values."""

    def __init__(self):
        self._value_to_placeholder: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self.mapping: dict[str, str] = {}  # placeholder → original

    def get_placeholder(self, category: str, value: str) -> str:
        if value in self._value_to_placeholder:
            return self._value_to_placeholder[value]
        count = self._counters.get(category, 0) + 1
        self._counters[category] = count
        placeholder = f"[{category}_{count}]"
        self._value_to_placeholder[value] = placeholder
        self.mapping[placeholder] = value
        return placeholder


def _desensitize_text(text: str, registry: _PlaceholderRegistry) -> str:
    """Apply all PII patterns to a single text string."""
    # 1. Context-based names first (most specific)
    for m in list(_NAME_CONTEXT_RE.finditer(text)):
        name = m.group(1)
        placeholder = registry.get_placeholder("姓名", name)
        text = text.replace(name, placeholder, 1)

    # 2. Regex-based patterns
    for category, pattern in _PATTERNS:
        for m in list(pattern.finditer(text)):
            value = m.group(0)
            # Skip if value was already replaced by a prior pattern
            if value not in text:
                continue
            placeholder = registry.get_placeholder(category, value)
            text = text.replace(value, placeholder, 1)

    return text


# Keywords that indicate the *next* cell in a table row contains a name
_NAME_KEYWORDS = {"联系人", "项目经理", "项目负责人", "法定代表人", "授权代表",
                  "负责人", "经办人", "签字人", "投标人代表"}

# Standalone Chinese name pattern (2-4 chars, used only for table cells with keyword context)
_STANDALONE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")


def _desensitize_table_row(row: list[str], registry: _PlaceholderRegistry) -> list[str]:
    """Desensitize a table row with cross-cell name detection.

    In tables, keywords like "联系人" and the name "张三" are often in adjacent cells.
    First pass: detect keyword cells and mask the adjacent name cell.
    Second pass: apply standard regex patterns to each cell.
    """
    new_row = list(row)

    # Cross-cell name detection: if cell[i] contains a keyword, check cell[i+1] for a name
    for i in range(len(new_row) - 1):
        cell_text = new_row[i].strip()
        if any(kw in cell_text for kw in _NAME_KEYWORDS):
            next_cell = new_row[i + 1].strip()
            if _STANDALONE_NAME_RE.match(next_cell):
                placeholder = registry.get_placeholder("姓名", next_cell)
                new_row[i + 1] = new_row[i + 1].replace(next_cell, placeholder, 1)

    # Standard desensitization on each cell
    new_row = [_desensitize_text(cell, registry) for cell in new_row]
    return new_row


def desensitize_paragraphs(
    paragraphs: list[Paragraph],
) -> tuple[list[Paragraph], dict[str, str]]:
    """Desensitize PII in all paragraphs.

    Returns:
        - New list of Paragraph objects with PII replaced by placeholders
        - Mapping dict: {placeholder: original_value}
    """
    registry = _PlaceholderRegistry()
    result = []

    for para in paragraphs:
        new_text = _desensitize_text(para.text, registry)

        new_table_data = None
        if para.table_data:
            new_table_data = [
                _desensitize_table_row(row, registry)
                for row in para.table_data
            ]

        result.append(replace(para, text=new_text, table_data=new_table_data))

    return result, registry.mapping
