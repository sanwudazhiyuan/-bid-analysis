"""Tests for continue, parsed, and bulk-reextract endpoints."""
import json
import sys
import uuid

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch

from server.app.models.task import Task
from server.app.models.annotation import Annotation


@pytest_asyncio.fixture
async def review_task(db_session, test_user, tmp_path):
    """Create a task in review status with extracted_data and a parsed.json file on disk."""
    parsed_file = tmp_path / "parsed.json"
    paragraphs = [{"index": 0, "text": "Hello", "style": "body"}]
    parsed_file.write_text(json.dumps(paragraphs), encoding="utf-8")

    task = Task(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="test.docx",
        file_path="/tmp/test.docx",
        file_size=1000,
        status="review",
        progress=90,
        parsed_path=str(parsed_file),
        extracted_data={
            "schema_version": "1.0",
            "modules": {
                "module_a": {
                    "title": "A",
                    "sections": [{"id": "A1", "title": "项目名称", "rows": []}],
                }
            },
        },
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


# -------------------------------------------------------------------------
# POST /{task_id}/continue
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_from_review(client, auth_headers, review_task, db_session):
    """POST /continue should dispatch run_generate and set status=generating."""
    fake_celery_result = MagicMock()
    fake_celery_result.id = "fake-generate-celery-id"
    fake_run_generate = MagicMock()
    fake_run_generate.delay.return_value = fake_celery_result

    fake_module = MagicMock()
    fake_module.run_generate = fake_run_generate
    sys.modules["server.app.tasks.generate_task"] = fake_module

    try:
        resp = await client.post(
            f"/api/tasks/{review_task.id}/continue",
            headers=auth_headers,
        )
    finally:
        sys.modules.pop("server.app.tasks.generate_task", None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "generating"
    assert data["task_id"] == str(review_task.id)
    fake_run_generate.delay.assert_called_once_with(str(review_task.id))


@pytest.mark.asyncio
async def test_continue_wrong_status(client, auth_headers, db_session, test_user):
    """POST /continue should return 409 when task is not in review status."""
    task = Task(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="t.docx",
        file_path="/tmp/t.docx",
        file_size=100,
        status="completed",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.post(
        f"/api/tasks/{task.id}/continue",
        headers=auth_headers,
    )
    assert resp.status_code == 409


# -------------------------------------------------------------------------
# GET /{task_id}/parsed
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_parsed(client, auth_headers, review_task):
    """GET /parsed should return paragraphs from file."""
    resp = await client.get(
        f"/api/tasks/{review_task.id}/parsed",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "paragraphs" in data
    assert isinstance(data["paragraphs"], list)
    assert len(data["paragraphs"]) == 1
    assert data["paragraphs"][0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_parsed_no_file(client, auth_headers, db_session, test_user):
    """GET /parsed should return 404 when parsed_path file doesn't exist."""
    task = Task(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="t.docx",
        file_path="/tmp/t.docx",
        file_size=100,
        status="review",
        parsed_path="/nonexistent/path/parsed.json",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(
        f"/api/tasks/{task.id}/parsed",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------------
# POST /{task_id}/bulk-reextract
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_reextract(client, auth_headers, review_task, db_session, test_user):
    """POST /bulk-reextract should dispatch run_bulk_reextract and return modules."""
    # Create a pending annotation
    annotation = Annotation(
        task_id=review_task.id,
        user_id=test_user.id,
        module_key="module_a",
        section_id="A1",
        row_index=0,
        annotation_type="correction",
        content="修正内容",
        status="pending",
    )
    db_session.add(annotation)
    await db_session.commit()

    fake_celery_result = MagicMock()
    fake_celery_result.id = "fake-bulk-reextract-celery-id"
    fake_run_bulk = MagicMock()
    fake_run_bulk.delay.return_value = fake_celery_result

    fake_module = MagicMock()
    fake_module.run_bulk_reextract = fake_run_bulk
    sys.modules["server.app.tasks.bulk_reextract_task"] = fake_module

    try:
        resp = await client.post(
            f"/api/tasks/{review_task.id}/bulk-reextract",
            headers=auth_headers,
        )
    finally:
        sys.modules.pop("server.app.tasks.bulk_reextract_task", None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "reprocessing"
    assert data["task_id"] == str(review_task.id)
    assert "module_a" in data["modules"]
    fake_run_bulk.delay.assert_called_once_with(str(review_task.id))


@pytest.mark.asyncio
async def test_bulk_reextract_no_annotations(client, auth_headers, review_task):
    """POST /bulk-reextract should return 400 when no pending annotations exist."""
    resp = await client.post(
        f"/api/tasks/{review_task.id}/bulk-reextract",
        headers=auth_headers,
    )
    assert resp.status_code == 400
