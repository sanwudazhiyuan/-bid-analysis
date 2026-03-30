"""Tests for reviewer compute_summary."""
from src.reviewer.reviewer import compute_summary


def test_compute_summary():
    items = [
        {"result": "pass", "confidence": 90, "severity": "critical"},
        {"result": "fail", "confidence": 85, "severity": "critical"},
        {"result": "warning", "confidence": 60, "severity": "major"},
        {"result": "pass", "confidence": 95, "severity": "minor"},
    ]
    summary = compute_summary(items)
    assert summary["total"] == 4
    assert summary["pass"] == 2
    assert summary["fail"] == 1
    assert summary["warning"] == 1
    assert summary["critical_fails"] == 1
    assert summary["by_severity"]["critical"]["total"] == 2
    assert summary["by_severity"]["major"]["warning"] == 1
    # avg_confidence is 0-1 scale: (90+85+60+95)/4/100 = 0.825 → round to 0.82
    assert summary["avg_confidence"] == 0.82
