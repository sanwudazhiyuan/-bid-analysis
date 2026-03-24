"""Tests for file upload / task creation endpoint (TDD)."""

import pytest
from io import BytesIO


@pytest.mark.asyncio
async def test_upload_file_creates_task(client, test_user, auth_headers):
    files = {"file": ("test.docx", BytesIO(b"fake docx content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    resp = await client.post("/api/tasks", files=files, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.docx"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_upload_rejects_invalid_extension(client, test_user, auth_headers):
    files = {"file": ("test.exe", BytesIO(b"evil"), "application/octet-stream")}
    resp = await client.post("/api/tasks", files=files, headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    files = {"file": ("test.docx", BytesIO(b"content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    resp = await client.post("/api/tasks", files=files)
    assert resp.status_code in (401, 403)  # No credentials → unauthenticated
