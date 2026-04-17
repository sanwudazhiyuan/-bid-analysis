"""Test fixtures — async SQLite for fast, isolated testing.

Uses SQLite + aiosqlite to avoid needing a running PostgreSQL for tests.
Registers type compilers so PG-specific types (UUID, JSONB) work on SQLite.
"""

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, JSON, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app.database import Base, get_db
from server.app.main import app
from server.app.security import hash_password
from server.app.models import User, Task, Annotation, GeneratedFile, ReviewTask  # noqa: F401
from server.app.models.anbiao_review import AnbiaoReview  # noqa: F401

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _register_sqlite_compilers(engine):
    """Make PG-specific column types work on SQLite for testing."""
    from sqlalchemy.ext.compiler import compiles

    @compiles(PG_UUID, "sqlite")
    def compile_uuid(element, compiler, **kw):
        return "VARCHAR(36)"

    @compiles(JSONB, "sqlite")
    def compile_jsonb(element, compiler, **kw):
        return "JSON"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    _register_sqlite_compilers(engine)

    # Enable WAL mode + foreign keys for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        # Rollback any uncommitted changes after each test
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session):
    user = User(
        username="testuser",
        password_hash=hash_password("testpass"),
        display_name="Test User",
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session):
    user = User(
        username="admin",
        password_hash=hash_password("adminpass"),
        display_name="Admin",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(client, test_user):
    """Helper: returns Authorization headers for test_user."""
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_headers(client, admin_user):
    """Helper: returns Authorization headers for admin_user."""
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
