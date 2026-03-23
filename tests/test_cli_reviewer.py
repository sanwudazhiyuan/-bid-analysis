"""Tests for CLI reviewer (Layer 4 — 人工校对层)"""

import json
import os
from unittest.mock import patch, MagicMock, call

import pytest

from src.reviewer.cli_reviewer import (
    display_module,
    review_all,
    open_in_editor,
    save_reviewed,
)


# --------------- fixtures ---------------


@pytest.fixture
def sample_extracted():
    """模拟 Layer 3 提取结果"""
    return {
        "schema_version": "1.0",
        "generated_at": "2026-03-20T10:30:00",
        "modules": {
            "module_a": {
                "title": "A. 项目基本信息",
                "sections": [
                    {
                        "id": "A1",
                        "title": "基本信息",
                        "type": "key_value_table",
                        "columns": ["项目", "内容"],
                        "rows": [
                            ["项目名称", "信用卡外包制递卡采购项目"],
                            ["采购编号", "GXTC-2025-001"],
                        ],
                    }
                ],
            },
            "module_b": {
                "title": "B. 资格要求",
                "sections": [
                    {
                        "id": "B1",
                        "title": "资格条件",
                        "type": "standard_table",
                        "columns": ["序号", "要求", "说明"],
                        "rows": [["1", "营业执照", "提供复印件"]],
                    }
                ],
            },
        },
    }


@pytest.fixture
def sample_module_data():
    return {
        "title": "A. 项目基本信息",
        "sections": [
            {
                "id": "A1",
                "title": "基本信息",
                "type": "key_value_table",
                "columns": ["项目", "内容"],
                "rows": [
                    ["项目名称", "测试项目"],
                    ["采购编号", "TEST001"],
                ],
            }
        ],
    }


@pytest.fixture
def failed_module_data():
    return {
        "status": "failed",
        "error": "LLM 返回非法 JSON",
    }


# --------------- display_module ---------------


class TestDisplayModule:
    def test_display_normal_module(self, sample_module_data, capsys):
        """正常模块应渲染表格预览，不抛异常"""
        display_module("module_a", sample_module_data)
        captured = capsys.readouterr()
        # rich 输出应包含模块标题和关键数据
        assert "项目基本信息" in captured.out or "module_a" in captured.out

    def test_display_failed_module(self, failed_module_data, capsys):
        """失败模块应显示错误信息，不抛异常"""
        display_module("module_c", failed_module_data)
        captured = capsys.readouterr()
        assert "失败" in captured.out or "failed" in captured.out.lower() or "错误" in captured.out

    def test_display_none_module(self, capsys):
        """None 模块应显示提示信息"""
        display_module("module_x", None)
        captured = capsys.readouterr()
        assert "无数据" in captured.out or "None" in captured.out or "跳过" in captured.out

    def test_display_module_with_multiple_sections(self, capsys):
        """多 section 模块应全部渲染"""
        data = {
            "title": "D. 评分标准",
            "sections": [
                {
                    "id": "D1",
                    "title": "技术评分",
                    "type": "standard_table",
                    "columns": ["序号", "评分项", "分值"],
                    "rows": [["1", "方案", "30"]],
                },
                {
                    "id": "D2",
                    "title": "商务评分",
                    "type": "standard_table",
                    "columns": ["序号", "评分项", "分值"],
                    "rows": [["1", "价格", "40"]],
                },
            ],
        }
        display_module("module_d", data)
        # 不抛异常即可


# --------------- open_in_editor ---------------


class TestOpenInEditor:
    def test_open_in_editor_roundtrip(self, tmp_path):
        """编辑器打开并原样返回时，数据不变"""
        original = {"title": "测试", "rows": [["a", "b"]]}

        with patch("subprocess.call") as mock_call:
            # 模拟编辑器不修改文件
            result = open_in_editor(original)

        assert result == original
        mock_call.assert_called_once()

    def test_open_in_editor_modified(self):
        """模拟编辑器修改了 JSON，返回修改后的数据"""
        original = {"title": "原始", "rows": []}
        modified = {"title": "已修改", "rows": [["1", "2"]]}

        def mock_editor(cmd, **kwargs):
            # 找到临时文件路径并写入修改后的内容
            # cmd 是列表，临时文件是最后一个参数
            tmp_file = cmd[-1] if isinstance(cmd, list) else cmd.split()[-1]
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(modified, f, ensure_ascii=False)
            return 0

        with patch("subprocess.call", side_effect=mock_editor):
            result = open_in_editor(original)

        assert result == modified
        assert result["title"] == "已修改"

    def test_open_in_editor_invalid_json(self):
        """编辑器返回非法 JSON 时应返回 None"""
        original = {"title": "测试"}

        def mock_editor(cmd, **kwargs):
            tmp_file = cmd[-1] if isinstance(cmd, list) else cmd.split()[-1]
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write("这不是合法的JSON{{{")
            return 0

        with patch("subprocess.call", side_effect=mock_editor):
            result = open_in_editor(original)

        assert result is None


# --------------- save_reviewed ---------------


class TestSaveReviewed:
    def test_save_and_load(self, tmp_path, sample_extracted):
        """保存校对结果并验证可正确加载"""
        out_path = str(tmp_path / "reviewed.json")
        save_reviewed(sample_extracted, out_path)

        assert os.path.exists(out_path)

        with open(out_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["schema_version"] == "1.0"
        assert "reviewed_at" in loaded
        assert "modules" in loaded
        assert loaded["modules"]["module_a"]["title"] == "A. 项目基本信息"

    def test_save_creates_parent_dirs(self, tmp_path, sample_extracted):
        """保存时应自动创建不存在的父目录"""
        out_path = str(tmp_path / "sub" / "dir" / "reviewed.json")
        save_reviewed(sample_extracted, out_path)
        assert os.path.exists(out_path)


# --------------- review_all ---------------


class TestReviewAll:
    def test_review_all_approve_all(self, sample_extracted):
        """用户对所有模块选择 [Y] 直接通过"""
        with patch("builtins.input", return_value="y"):
            result = review_all(sample_extracted)

        assert result is not None
        assert "modules" in result
        assert result["modules"]["module_a"]["title"] == "A. 项目基本信息"
        assert result["modules"]["module_b"]["title"] == "B. 资格要求"

    def test_review_all_mark_rerun(self, sample_extracted):
        """用户选择 [n] 标记模块需重跑"""
        # 第一个模块选 n，第二个选 y
        inputs = iter(["n", "y"])
        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            result = review_all(sample_extracted)

        assert result is not None
        # 标记为 needs_rerun 的模块
        module_a = result["modules"]["module_a"]
        assert module_a.get("needs_rerun") is True

    def test_review_all_edit_module(self, sample_extracted):
        """用户选择 [e] 打开编辑器"""
        edited_module = {
            "title": "A. 项目基本信息（已编辑）",
            "sections": [],
        }

        # 第一个模块选 e，第二个选 y
        inputs = iter(["e", "y"])

        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            with patch(
                "src.reviewer.cli_reviewer.open_in_editor",
                return_value=edited_module,
            ):
                result = review_all(sample_extracted)

        assert result["modules"]["module_a"]["title"] == "A. 项目基本信息（已编辑）"

    def test_review_all_edit_returns_none_keeps_original(self, sample_extracted):
        """编辑器返回 None（非法JSON）时保留原始数据"""
        inputs = iter(["e", "y"])

        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            with patch(
                "src.reviewer.cli_reviewer.open_in_editor",
                return_value=None,
            ):
                result = review_all(sample_extracted)

        # 应保留原始数据
        assert result["modules"]["module_a"]["title"] == "A. 项目基本信息"

    def test_review_all_empty_modules(self):
        """无模块时应正常返回"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-03-20T10:30:00",
            "modules": {},
        }
        with patch("builtins.input", return_value="y"):
            result = review_all(data)
        assert result is not None
        assert result["modules"] == {}

    def test_review_all_with_none_module(self):
        """模块值为 None 时应跳过或显示提示"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-03-20T10:30:00",
            "modules": {
                "module_a": None,
                "module_b": {
                    "title": "B. 资格要求",
                    "sections": [],
                },
            },
        }
        inputs = iter(["y", "y"])
        with patch("builtins.input", side_effect=lambda _="": next(inputs)):
            result = review_all(data)
        assert result is not None
