import json
import pytest
from src.models import Paragraph
from src.persistence import (
    save_parsed, load_parsed,
    save_extracted, load_extracted,
    save_reviewed, load_reviewed,
)


def test_save_and_load_parsed(tmp_path):
    paragraphs = [
        Paragraph(0, "测试段落", style="Heading 1", is_table=False, table_data=None),
        Paragraph(1, "表格", style=None, is_table=True, table_data=[["a", "b"]]),
    ]
    path = str(tmp_path / "test_parsed.json")
    save_parsed(paragraphs, path)
    loaded = load_parsed(path)
    assert len(loaded) == 2
    assert loaded[0].text == "测试段落"
    assert loaded[1].is_table is True
    assert loaded[1].table_data == [["a", "b"]]


def test_load_rejects_incompatible_version(tmp_path):
    """schema_version 不匹配时应抛出 ValueError"""
    path = str(tmp_path / "old.json")
    with open(path, "w") as f:
        json.dump({"schema_version": "0.1", "paragraphs": []}, f)
    with pytest.raises(ValueError, match="schema_version"):
        load_parsed(path)


def test_save_and_load_extracted(tmp_path):
    data = {
        "schema_version": "1.0",
        "modules": {"module_a": {"title": "A. 项目概况", "sections": []}}
    }
    path = str(tmp_path / "extracted.json")
    save_extracted(data, path)
    loaded = load_extracted(path)
    assert "module_a" in loaded["modules"]
    assert "generated_at" in loaded


def test_save_and_load_reviewed(tmp_path):
    data = {
        "schema_version": "1.0",
        "modules": {"module_a": {"title": "A. 项目概况", "sections": []}}
    }
    path = str(tmp_path / "reviewed.json")
    save_reviewed(data, path)
    loaded = load_reviewed(path)
    assert "reviewed_at" in loaded
