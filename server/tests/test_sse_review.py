# server/tests/test_sse_review.py
"""Tests for SSE endpoint handling review/generating status transitions."""
import json
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, PropertyMock

from server.app.models.task import Task


@pytest_asyncio.fixture
async def review_task_with_celery(db_session, test_user):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="test.docx",
        file_path="/data/test.docx", status="review", progress=90,
        celery_task_id="celery-done-123",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestSSEReviewStatus:
    @pytest.mark.asyncio
    async def test_sse_returns_review_when_celery_success_and_status_review(
        self, client, auth_headers, review_task_with_celery
    ):
        """When Celery task is SUCCESS but DB status is 'review', SSE should send step='review'."""
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"

        with patch("celery.result.AsyncResult", return_value=mock_result):
            resp = await client.get(
                f"/api/tasks/{review_task_with_celery.id}/progress",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        last = json.loads(data_lines[-1].replace("data: ", ""))
        assert last["step"] == "review"
        assert last["progress"] == 90

    @pytest.mark.asyncio
    async def test_sse_follows_new_celery_task_when_generating(
        self, client, auth_headers, review_task_with_celery, db_session
    ):
        """When Celery SUCCESS but DB status is 'generating' with new celery_task_id, SSE should follow new task."""
        review_task_with_celery.status = "generating"
        review_task_with_celery.celery_task_id = "celery-gen-456"
        await db_session.commit()

        mock_old = MagicMock()
        mock_old.state = "SUCCESS"

        # mock_new returns PROGRESS on first call, SUCCESS on subsequent calls
        # so the SSE loop terminates naturally.
        new_call_count = 0
        def new_result_side_effect():
            nonlocal new_call_count
            new_call_count += 1
            m = MagicMock()
            if new_call_count == 1:
                m.state = "PROGRESS"
                m.info = {"step": "generating", "progress": 95, "detail": "生成报告..."}
            else:
                m.state = "SUCCESS"
            return m

        def mock_async_result(task_id, app=None):
            if task_id == "celery-done-123":
                return mock_old
            return new_result_side_effect()

        with patch("celery.result.AsyncResult", side_effect=mock_async_result):
            resp = await client.get(
                f"/api/tasks/{review_task_with_celery.id}/progress",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        # At least one PROGRESS event for the generating step
        progress_events = [
            json.loads(l.replace("data: ", ""))
            for l in data_lines
            if json.loads(l.replace("data: ", "")).get("step") == "generating"
        ]
        assert len(progress_events) >= 1
