"""Tests for preview data and checkbox APIs."""
import uuid
import pytest
from server.app.models.task import Task


@pytest.mark.asyncio
async def test_preview_returns_extracted_data(client, test_user, auth_headers, db_session):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="t.docx",
        file_path="/tmp/t.docx", file_size=100, status="completed",
        extracted_data={"modules": {"module_a": {"title": "A. Test", "sections": []}}},
        checkbox_data={},
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(f"/api/tasks/{task.id}/preview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "extracted_data" in data
    assert "checkbox_data" in data
    assert data["extracted_data"]["modules"]["module_a"]["title"] == "A. Test"


@pytest.mark.asyncio
async def test_preview_404_no_data(client, test_user, auth_headers, db_session):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="t.docx",
        file_path="/tmp/t.docx", file_size=100, status="pending",
        extracted_data=None,
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(f"/api/tasks/{task.id}/preview", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_preview_404_wrong_user(client, test_user, admin_user, auth_headers, db_session):
    task = Task(
        id=uuid.uuid4(), user_id=admin_user.id, filename="admin.docx",
        file_path="/tmp/admin.docx", file_size=100, status="completed",
        extracted_data={"modules": {}},
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(f"/api/tasks/{task.id}/preview", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_toggle_checkbox(client, test_user, auth_headers, db_session):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="t.docx",
        file_path="/tmp/t.docx", file_size=100, status="completed",
        extracted_data={"modules": {}}, checkbox_data={},
    )
    db_session.add(task)
    await db_session.commit()

    # Toggle on
    resp = await client.put(
        f"/api/tasks/{task.id}/preview/checkbox",
        json={"module_key": "module_a", "section_id": "A1", "row_index": 0, "checked": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify via preview
    preview = await client.get(f"/api/tasks/{task.id}/preview", headers=auth_headers)
    assert preview.status_code == 200
    assert preview.json()["checkbox_data"]["module_a"]["A1"]["0"] is True


@pytest.mark.asyncio
async def test_toggle_checkbox_404(client, test_user, auth_headers):
    resp = await client.put(
        f"/api/tasks/{uuid.uuid4()}/preview/checkbox",
        json={"module_key": "module_a", "section_id": "A1", "row_index": 0, "checked": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_preview_requires_auth(client):
    resp = await client.get(f"/api/tasks/{uuid.uuid4()}/preview")
    assert resp.status_code in (401, 403)
