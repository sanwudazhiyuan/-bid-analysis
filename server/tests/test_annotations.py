"""Tests for annotation CRUD API."""
import uuid
import pytest
import pytest_asyncio
from server.app.models.task import Task


@pytest_asyncio.fixture
async def completed_task(db_session, test_user):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="t.docx",
        file_path="/tmp/t.docx", file_size=100, status="completed",
        extracted_data={"modules": {}},
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.mark.asyncio
async def test_create_annotation(client, test_user, auth_headers, completed_task):
    resp = await client.post(
        f"/api/tasks/{completed_task.id}/annotations",
        json={
            "module_key": "module_d", "section_id": "D3",
            "row_index": 1, "annotation_type": "correction",
            "content": "原文写的是5万不是1万",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "原文写的是5万不是1万"
    assert data["status"] == "pending"
    assert data["module_key"] == "module_d"


@pytest.mark.asyncio
async def test_list_annotations(client, test_user, auth_headers, completed_task):
    # Create one first
    await client.post(
        f"/api/tasks/{completed_task.id}/annotations",
        json={"module_key": "module_a", "section_id": "A1", "content": "test note"},
        headers=auth_headers,
    )
    resp = await client.get(f"/api/tasks/{completed_task.id}/annotations", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_update_annotation(client, test_user, auth_headers, completed_task):
    create_resp = await client.post(
        f"/api/tasks/{completed_task.id}/annotations",
        json={"module_key": "module_a", "section_id": "A1", "content": "original"},
        headers=auth_headers,
    )
    ann_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/tasks/{completed_task.id}/annotations/{ann_id}",
        json={"content": "修改后的内容"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "修改后的内容"


@pytest.mark.asyncio
async def test_delete_annotation(client, test_user, auth_headers, completed_task):
    create_resp = await client.post(
        f"/api/tasks/{completed_task.id}/annotations",
        json={"module_key": "module_a", "section_id": "A1", "content": "to delete"},
        headers=auth_headers,
    )
    ann_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/tasks/{completed_task.id}/annotations/{ann_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Verify deleted
    list_resp = await client.get(f"/api/tasks/{completed_task.id}/annotations", headers=auth_headers)
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_annotation_requires_auth(client, completed_task):
    resp = await client.get(f"/api/tasks/{completed_task.id}/annotations")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_update_other_user_annotation_404(client, test_user, admin_user, auth_headers, admin_headers, completed_task):
    # Admin creates annotation
    create_resp = await client.post(
        f"/api/tasks/{completed_task.id}/annotations",
        json={"module_key": "module_a", "section_id": "A1", "content": "admin note"},
        headers=admin_headers,
    )
    ann_id = create_resp.json()["id"]

    # test_user tries to update it
    resp = await client.put(
        f"/api/tasks/{completed_task.id}/annotations/{ann_id}",
        json={"content": "hijack"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
