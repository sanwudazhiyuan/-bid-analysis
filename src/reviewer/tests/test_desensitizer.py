"""Tests for PII desensitization in tender documents."""
from src.models import Paragraph
from src.reviewer.desensitizer import desensitize_paragraphs


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t, style=None) for i, t in enumerate(texts)]


def test_phone_number_masked():
    """Mobile phone numbers are replaced with numbered placeholders."""
    paras = _make_paras(["联系人电话：13812345678，备用：13987654321"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[电话_1]" in result[0].text
    assert "[电话_2]" in result[0].text
    assert "13812345678" not in result[0].text
    assert mapping["[电话_1]"] == "13812345678"
    assert mapping["[电话_2]"] == "13987654321"


def test_id_card_masked():
    """18-digit ID card numbers with valid dates are masked."""
    paras = _make_paras(["身份证号：110101199003074518"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[身份证_1]" in result[0].text
    assert "110101199003074518" not in result[0].text


def test_id_card_with_x_suffix():
    """ID cards ending with X are masked."""
    paras = _make_paras(["身份证：32010619880215371X"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[身份证_1]" in result[0].text
    assert "32010619880215371X" not in result[0].text


def test_id_card_invalid_date_not_masked():
    """18-digit numbers with invalid dates are NOT matched as ID cards."""
    # Month 13 is invalid
    paras = _make_paras(["编号：110101199013074518"])
    result, _ = desensitize_paragraphs(paras)
    # Should not be masked as ID card (invalid month 13)
    assert "[身份证_1]" not in result[0].text


def test_email_masked():
    """Email addresses are masked."""
    paras = _make_paras(["请发送至 zhangsan@example.com 或 lisi@company.cn"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[邮箱_1]" in result[0].text
    assert "[邮箱_2]" in result[0].text
    assert "zhangsan@example.com" not in result[0].text


def test_bank_account_masked():
    """16-19 digit bank account numbers are masked."""
    paras = _make_paras(["开户账号：6222021234567890123"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[银行账号_1]" in result[0].text
    assert "6222021234567890123" not in result[0].text


def test_name_in_context_masked():
    """Names following context keywords (联系人、项目经理 etc.) are masked."""
    paras = _make_paras([
        "项目经理：张三",
        "联系人：李四  电话：13800001111",
        "法定代表人：王五",
    ])
    result, mapping = desensitize_paragraphs(paras)
    assert "张三" not in result[0].text
    assert "[姓名_1]" in result[0].text
    assert "李四" not in result[1].text
    assert "[姓名_2]" in result[1].text
    assert "王五" not in result[2].text


def test_table_data_desensitized():
    """PII in table cells is also desensitized."""
    para = Paragraph(
        index=0, text="联系方式", style=None,
        is_table=True,
        table_data=[
            ["联系人", "张三"],
            ["电话", "13812345678"],
            ["邮箱", "zs@test.com"],
        ],
    )
    result, mapping = desensitize_paragraphs([para])
    flat = str(result[0].table_data)
    assert "张三" not in flat
    assert "13812345678" not in flat
    assert "zs@test.com" not in flat


def test_table_keyword_as_substring():
    """Cross-cell name detection works when keyword is a substring of cell text."""
    para = Paragraph(
        index=0, text="人员信息", style=None,
        is_table=True,
        table_data=[
            ["项目联系人", "赵六"],
            ["职务", "经理"],
        ],
    )
    result, mapping = desensitize_paragraphs([para])
    flat = str(result[0].table_data)
    assert "赵六" not in flat
    assert "[姓名_1]" in flat


def test_no_pii_unchanged():
    """Text without PII is not modified."""
    paras = _make_paras(["投标文件须双面打印并装订成册", "技术方案不少于30页"])
    result, mapping = desensitize_paragraphs(paras)
    assert result[0].text == "投标文件须双面打印并装订成册"
    assert result[1].text == "技术方案不少于30页"
    assert len(mapping) == 0


def test_same_value_gets_same_placeholder():
    """Identical PII values reuse the same placeholder."""
    paras = _make_paras(["电话13812345678", "再次确认13812345678"])
    result, mapping = desensitize_paragraphs(paras)
    assert result[0].text.count("[电话_1]") == 1
    assert result[1].text.count("[电话_1]") == 1
    assert len([k for k in mapping if k.startswith("[电话_")]) == 1
