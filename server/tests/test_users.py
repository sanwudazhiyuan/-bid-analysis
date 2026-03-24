"""Tests for admin user management API — Task 6.1."""
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# 1. Admin can list all users
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_users_admin(client, admin_headers, test_user, admin_user):
    resp = await client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    usernames = [u["username"] for u in data]
    assert "testuser" in usernames
    assert "admin" in usernames


# ---------------------------------------------------------------------------
# 2. Regular user gets 403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_users_forbidden(client, auth_headers):
    resp = await client.get("/api/users", headers=auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 3. Admin can create a user
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_user_admin(client, admin_headers):
    resp = await client.post(
        "/api/users",
        json={"username": "newuser", "password": "newpass123", "display_name": "New User", "role": "user"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert "id" in data


# ---------------------------------------------------------------------------
# 4. Duplicate username returns 400
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_user_duplicate(client, admin_headers, test_user):
    resp = await client.post(
        "/api/users",
        json={"username": "testuser", "password": "whatever", "role": "user"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5. Admin can update user display_name / role / password
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_user_admin(client, admin_headers, test_user):
    resp = await client.put(
        f"/api/users/{test_user.id}",
        json={"display_name": "Updated Name", "role": "user"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"


# ---------------------------------------------------------------------------
# 6. Admin can delete a non-admin user
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_user_admin(client, admin_headers, test_user):
    resp = await client.delete(f"/api/users/{test_user.id}", headers=admin_headers)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# 7. Cannot delete an admin user (returns 400)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_admin_blocked(client, admin_headers, admin_user):
    resp = await client.delete(f"/api/users/{admin_user.id}", headers=admin_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 8. No token returns 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_endpoints_require_auth(client):
    endpoints = [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PUT", "/api/users/1"),
        ("DELETE", "/api/users/1"),
    ]
    for method, path in endpoints:
        resp = await client.request(method, path, json={})
        assert resp.status_code in (401, 403), f"{method} {path} should require auth, got {resp.status_code}"
