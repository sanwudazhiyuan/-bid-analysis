"""Tests for download and regenerate endpoints."""
import uuid
import pytest
from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile

@pytest.mark.asyncio
async def test_download_invalid_file_type(client, test_user, auth_headers, db_session):
    task_id = uuid.uuid4()
    task = Task(id=task_id, user_id=test_user.id, filename="test.docx", file_path="/tmp/test.docx", file_size=100, status="completed")
    db_session.add(task)
    await db_session.commit()
    resp = await client.get(f"/api/tasks/{task_id}/download/invalid", headers=auth_headers)
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_download_task_not_found(client, test_user, auth_headers):
    resp = await client.get(f"/api/tasks/{uuid.uuid4()}/download/report", headers=auth_headers)
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_download_file_not_found(client, test_user, auth_headers, db_session):
    """Task exists but no GeneratedFile record."""
    task_id = uuid.uuid4()
    task = Task(id=task_id, user_id=test_user.id, filename="test.docx", file_path="/tmp/test.docx", file_size=100, status="completed")
    db_session.add(task)
    await db_session.commit()
    resp = await client.get(f"/api/tasks/{task_id}/download/report", headers=auth_headers)
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_download_requires_auth(client):
    resp = await client.get(f"/api/tasks/{uuid.uuid4()}/download/report")
    assert resp.status_code in (401, 403)

@pytest.mark.asyncio
async def test_regenerate_task_not_found(client, test_user, auth_headers):
    resp = await client.post(f"/api/tasks/{uuid.uuid4()}/regenerate", headers=auth_headers)
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_regenerate_no_extracted_data(client, test_user, auth_headers, db_session):
    """Task exists but has no extracted_data."""
    task_id = uuid.uuid4()
    task = Task(id=task_id, user_id=test_user.id, filename="test.docx", file_path="/tmp/test.docx", file_size=100, status="completed", extracted_data=None)
    db_session.add(task)
    await db_session.commit()
    resp = await client.post(f"/api/tasks/{task_id}/regenerate", headers=auth_headers)
    assert resp.status_code == 404
