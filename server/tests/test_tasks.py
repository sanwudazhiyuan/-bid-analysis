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


# ---------------------------------------------------------------------------
# SSE progress endpoint tests (Task 2.3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_progress_endpoint_returns_sse_no_celery_id(client, test_user, auth_headers, db_session):
    """Task with no celery_task_id returns SSE with pending payload immediately."""
    from server.app.models.task import Task
    import uuid

    task = Task(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="test.docx",
        file_path="/tmp/test.docx",
        file_size=100,
        status="pending",
        celery_task_id=None,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    resp = await client.get(f"/api/tasks/{task.id}/progress", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    # The body should contain at least one SSE data line with progress=0
    assert b"data:" in resp.content
    assert b'"progress": 0' in resp.content or b'"progress":0' in resp.content


@pytest.mark.asyncio
async def test_progress_endpoint_404_for_other_user(client, test_user, admin_user, auth_headers, db_session):
    """Task belonging to admin should not be accessible by test_user via progress endpoint."""
    from server.app.models.task import Task
    import uuid

    task = Task(
        id=uuid.uuid4(),
        user_id=admin_user.id,  # belongs to admin
        filename="admin.docx",
        file_path="/tmp/admin.docx",
        file_size=100,
        status="extracting",
        celery_task_id="fake-id",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(f"/api/tasks/{task.id}/progress", headers=auth_headers)  # test_user's token
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_progress_endpoint_requires_auth(client, test_user, db_session):
    """Progress endpoint without token returns 401/403."""
    from server.app.models.task import Task
    import uuid

    task = Task(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="test.docx",
        file_path="/tmp/test.docx",
        file_size=100,
        status="pending",
        celery_task_id=None,
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(f"/api/tasks/{task.id}/progress")
    assert resp.status_code in (401, 403)
