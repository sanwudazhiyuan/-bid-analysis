"""Tests for pipeline components (extract_single_module, pipeline task logic)."""
import pytest
from unittest.mock import patch, MagicMock


def test_extract_single_module_unknown_raises():
    from src.extractor.extractor import extract_single_module
    with pytest.raises(ValueError, match="Unknown module"):
        extract_single_module("nonexistent_module", [])


def test_extract_single_module_calls_correct_function():
    from src.extractor.extractor import extract_single_module
    mock_mod = MagicMock()
    mock_mod.extract_module_a.return_value = {"title": "A. Test"}
    with patch("src.extractor.extractor.importlib.import_module", return_value=mock_mod) as mock_import:
        result = extract_single_module("module_a", [], None)
        mock_import.assert_called_with("src.extractor.module_a")
        mock_mod.extract_module_a.assert_called_once()
