"""Tests for smart_reviewer HTTP client."""
from unittest.mock import patch, MagicMock

import httpx
import pytest

from src.reviewer.smart_reviewer import call_smart_review


class TestCallSmartReview:
    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "pass",
            "confidence": 90,
            "reason": "满足要求",
            "locations": [],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        clause = {
            "clause_index": 1,
            "clause_text": "须提供营业执照",
            "basis_text": "资格要求",
            "severity": "critical",
            "source_module": "module_c",
        }
        result = call_smart_review(clause, "/data/tender_folder", "测试项目")

        assert result["result"] == "pass"
        assert result["confidence"] == 90
        assert result["source_module"] == "module_c"
        assert result["clause_index"] == 1

    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_fail_with_locations(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "fail",
            "confidence": 85,
            "reason": "仅提供2个业绩",
            "locations": [
                {"para_index": 42, "text_snippet": "业绩证明", "reason": "数量不足"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        clause = {
            "clause_index": 5,
            "clause_text": "须提供3个业绩",
            "basis_text": "",
            "severity": "major",
            "source_module": "module_c",
        }
        result = call_smart_review(clause, "/data/folder", "项目")

        assert result["result"] == "fail"
        assert result["tender_locations"][0]["para_indices"] == [42]
        assert result["tender_locations"][0]["per_para_reasons"][42] == "数量不足"

    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_http_error(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        clause = {
            "clause_index": 2,
            "clause_text": "测试条款",
            "basis_text": "",
            "severity": "minor",
            "source_module": "module_a",
        }
        result = call_smart_review(clause, "/data/folder", "项目")

        assert result["result"] == "error"
        assert result["clause_index"] == 2
        assert "Connection refused" in result["reason"]

    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timeout")

        clause = {
            "clause_index": 3,
            "clause_text": "超时条款",
            "basis_text": "",
            "severity": "major",
            "source_module": "module_b",
        }
        result = call_smart_review(clause, "/data/folder", "项目")

        assert result["result"] == "error"
        assert "超时" in result["reason"]
