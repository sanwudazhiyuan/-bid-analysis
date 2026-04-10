"""Tests for /api/reviews endpoints — uses conftest fixtures (client, db_session, auth_headers)."""
import uuid
import pytest

from server.app.models.task import Task

pytestmark = pytest.mark.asyncio


async def test_create_review_missing_bid_task(client, auth_headers):
    """POST /api/reviews with invalid bid_task_id returns 404."""
    resp = await client.post(
        "/api/reviews",
        data={"bid_task_id": str(uuid.uuid4())},
        files={"tender_file": ("投标.docx", b"dummy", "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_list_reviews_empty(client, auth_headers):
    """GET /api/reviews returns empty list when no reviews exist."""
    resp = await client.get("/api/reviews", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_delete_review_not_found(client, auth_headers):
    """DELETE /api/reviews/{id} returns 404 for non-existent review."""
    resp = await client.delete(
        f"/api/reviews/{uuid.uuid4()}", headers=auth_headers,
    )
    assert resp.status_code == 404
