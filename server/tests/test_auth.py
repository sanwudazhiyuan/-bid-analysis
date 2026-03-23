"""Integration tests for auth API routes.

Covers: login, logout, refresh, /me, edge cases, error handling.
Tests are isolated per function via db_session fixture rollback.
"""

import pytest


# ── POST /api/auth/login ──────────────────────────────────────────

class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user):
        resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "wrong"})
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        resp = await client.post("/api/auth/login", json={"username": "ghost", "password": "pass"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_empty_username(self, client):
        resp = await client.post("/api/auth/login", json={"username": "", "password": "pass"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, client):
        resp = await client.post("/api/auth/login", json={})
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_login_extra_fields_ignored(self, client, test_user):
        resp = await client.post("/api/auth/login", json={
            "username": "testuser", "password": "testpass", "extra": "ignored"
        })
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_updates_last_login(self, client, test_user, db_session):
        assert test_user.last_login is None
        await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        await db_session.refresh(test_user)
        assert test_user.last_login is not None


# ── GET /api/auth/me ──────────────────────────────────────────────

class TestMe:
    @pytest.mark.asyncio
    async def test_me_with_valid_token(self, client, test_user, auth_headers):
        resp = await client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["display_name"] == "Test User"
        assert data["role"] == "user"
        assert "password" not in data  # Password hash must not leak

    @pytest.mark.asyncio
    async def test_me_without_token(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)  # No credentials → unauthorized

    @pytest.mark.asyncio
    async def test_me_with_invalid_token(self, client):
        resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_refresh_token_rejected(self, client, test_user):
        """Refresh tokens must not be usable as access tokens."""
        login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        refresh = login_resp.json()["refresh_token"]
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_admin_user(self, client, admin_headers):
        resp = await client.get("/api/auth/me", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


# ── POST /api/auth/refresh ────────────────────────────────────────

class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_success(self, client, test_user):
        login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        refresh_token = login_resp.json()["refresh_token"]
        resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, client, test_user):
        """Access tokens must not be usable as refresh tokens."""
        login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        access_token = login_resp.json()["access_token"]
        resp = await client.post("/api/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token(self, client):
        resp = await client.post("/api/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_new_tokens_are_valid(self, client, test_user):
        """Refreshed tokens must be usable for subsequent requests."""
        login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
        refresh_token = login_resp.json()["refresh_token"]
        refresh_resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
        new_access = refresh_resp.json()["access_token"]
        me_resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "testuser"


# ── POST /api/auth/logout ─────────────────────────────────────────

class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_returns_ok(self, client):
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── GET /api/health ────────────────────────────────────────────────

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client):
        """Health endpoint must not require authentication."""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
