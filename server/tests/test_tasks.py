"""Tests for file upload / task creation endpoint (TDD)."""

import sys
import pytest
from io import BytesIO
from unittest.mock import MagicMock

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _install_pipeline_mock():
    """Inject a fake pipeline_task module so the lazy import in the router resolves.

    The router does `from server.app.tasks.pipeline_task import run_pipeline`
    inside the endpoint body.  Because `pipeline_task` requires psycopg2 (not
    available in the test environment) we register a lightweight mock module in
    sys.modules *before* the request is processed.  The mock is removed after
    each test to keep the module cache clean.
    """
    fake_task = MagicMock()
    fake_task.delay.return_value = MagicMock(id="fake-celery-task-id")

    fake_module = MagicMock()
    fake_module.run_pipeline = fake_task

    sys.modules["server.app.tasks.pipeline_task"] = fake_module
    return fake_task, fake_module


def _remove_pipeline_mock():
    sys.modules.pop("server.app.tasks.pipeline_task", None)


@pytest.mark.asyncio
async def test_upload_file_creates_task(client, test_user, auth_headers):
    fake_task, _ = _install_pipeline_mock()
    try:
        files = {"file": ("test.docx", BytesIO(b"fake docx content"), _DOCX_CONTENT_TYPE)}
        resp = await client.post("/api/tasks", files=files, headers=auth_headers)
    finally:
        _remove_pipeline_mock()

    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.docx"
    assert data["status"] == "pending"
    fake_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_upload_rejects_invalid_extension(client, test_user, auth_headers):
    # Invalid extension — rejected before Celery dispatch; no mock needed
    files = {"file": ("test.exe", BytesIO(b"evil"), "application/octet-stream")}
    resp = await client.post("/api/tasks", files=files, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    files = {"file": ("test.docx", BytesIO(b"content"), _DOCX_CONTENT_TYPE)}
    resp = await client.post("/api/tasks", files=files)
    assert resp.status_code in (401, 403)  # No credentials → unauthenticated
