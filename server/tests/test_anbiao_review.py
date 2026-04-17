"""Integration tests for anbiao review API endpoints."""
import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_create_anbiao_review_missing_file(client, auth_headers):
    """POST without tender_file should fail."""
    resp = await client.post("/api/anbiao-reviews", headers=auth_headers)
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_list_anbiao_reviews_empty(client, auth_headers):
    """GET list should return empty list initially."""
    resp = await client.get("/api/anbiao-reviews", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 0


@pytest.mark.asyncio
async def test_get_anbiao_review_not_found(client, auth_headers):
    """GET non-existent review should return 404."""
    resp = await client.get("/api/anbiao-reviews/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_anbiao_review_not_found(client, auth_headers):
    """DELETE non-existent review should return 404."""
    resp = await client.delete("/api/anbiao-reviews/nonexistent-id", headers=auth_headers)
    assert resp.status_code == 404