"""Tests for rate limiting middleware (TDD — Task 6.3)."""

import sys
import pytest
from io import BytesIO
from unittest.mock import MagicMock

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _install_pipeline_mock():
    fake_task = MagicMock()
    fake_task.delay.return_value = MagicMock(id="fake-celery-task-id")
    fake_module = MagicMock()
    fake_module.run_pipeline = fake_task
    sys.modules["server.app.tasks.pipeline_task"] = fake_module
    return fake_task


def _remove_pipeline_mock():
    sys.modules.pop("server.app.tasks.pipeline_task", None)


@pytest.mark.asyncio
async def test_rate_limit_allows_normal_requests(client, test_user, auth_headers):
    """5 upload requests should all succeed (well under the 10/min limit)."""
    from server.app.main import _rate_limits
    _rate_limits.clear()

    _install_pipeline_mock()
    try:
        for _ in range(5):
            files = {
                "file": (
                    "test.docx",
                    BytesIO(b"fake"),
                    _DOCX_CONTENT_TYPE,
                )
            }
            resp = await client.post("/api/tasks", files=files, headers=auth_headers)
            assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    finally:
        _remove_pipeline_mock()
        _rate_limits.clear()


@pytest.mark.asyncio
async def test_rate_limit_blocks_excessive_requests(client, test_user, auth_headers):
    """11th upload request in a row should return 429."""
    from server.app.main import _rate_limits
    _rate_limits.clear()

    _install_pipeline_mock()
    try:
        statuses = []
        for _ in range(11):
            files = {
                "file": (
                    "test.docx",
                    BytesIO(b"fake"),
                    _DOCX_CONTENT_TYPE,
                )
            }
            resp = await client.post("/api/tasks", files=files, headers=auth_headers)
            statuses.append(resp.status_code)

        # First 10 should succeed, 11th should be blocked
        assert all(s == 201 for s in statuses[:10]), f"First 10 statuses: {statuses[:10]}"
        assert statuses[10] == 429, f"Expected 429 on 11th request, got {statuses[10]}"
    finally:
        _remove_pipeline_mock()
        _rate_limits.clear()
