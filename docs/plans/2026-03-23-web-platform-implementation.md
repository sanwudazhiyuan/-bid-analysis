# 招标文件分析系统 Web 平台实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 CLI 招标文件分析管线封装为 Web 应用，支持文件上传、异步 LLM 处理、实时进度、交互式预览与标注、Docker 一键部署。

**Architecture:** FastAPI 后端 + Celery 异步任务队列 + Redis 消息中间件 + PostgreSQL 数据库。Vue 3 + Tailwind CSS 前端。Nginx 反向代理。5 个 Docker 容器通过 docker-compose 编排。现有 `src/` 管线代码零改造，由 Celery Worker 直接 import 调用。

**Tech Stack:** Python 3.11+ / FastAPI / Celery / Redis / PostgreSQL / SQLAlchemy 2.0 / Alembic / Vue 3 / Vite / Tailwind CSS / Pinia / Axios / SSE / Docker

**Spec:** `docs/specs/2026-03-23-web-platform-design.md`

---

## File Structure Overview

### Backend (`server/`)

```
server/
├── app/
│   ├── __init__.py
│   ├── main.py                  — FastAPI 应用入口 + CORS + 路由挂载
│   ├── config.py                — 环境变量配置 (DB_URL, REDIS_URL, JWT_SECRET, etc.)
│   ├── database.py              — SQLAlchemy async engine + session factory
│   ├── models/
│   │   ├── __init__.py          — 导出 Base + 所有模型
│   │   ├── user.py              — User ORM
│   │   ├── task.py              — Task ORM
│   │   ├── annotation.py        — Annotation ORM
│   │   └── generated_file.py    — GeneratedFile ORM
│   ├── schemas/
│   │   ├── auth.py              — LoginRequest, TokenResponse, UserInfo
│   │   ├── task.py              — TaskCreate, TaskResponse, TaskListResponse
│   │   └── annotation.py        — AnnotationCreate, AnnotationResponse
│   ├── routers/
│   │   ├── auth.py              — POST login/logout/refresh, GET me
│   │   ├── tasks.py             — CRUD + SSE progress
│   │   ├── preview.py           — GET preview, PUT checkbox
│   │   ├── annotations.py       — Annotation CRUD + reextract
│   │   ├── download.py          — GET download, POST regenerate
│   │   └── users.py             — Admin user CRUD
│   ├── services/
│   │   ├── auth_service.py      — 密码验证、token 生成
│   │   ├── task_service.py      — 任务创建、查询、删除
│   │   ├── preview_service.py   — 预览数据组装、勾选更新
│   │   └── reextract_service.py — 标注分组、触发重提取
│   ├── tasks/
│   │   ├── celery_app.py        — Celery 实例配置
│   │   ├── pipeline_task.py     — run_pipeline 主任务
│   │   └── reextract_task.py    — reextract_section 任务
│   ├── deps.py                  — get_db, get_current_user 依赖
│   └── security.py              — JWT 编解码、密码哈希
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── scripts/
│   └── create_admin.py          — 初始管理员创建脚本
├── requirements.txt
├── Dockerfile
└── tests/
    ├── conftest.py              — 测试 fixtures (async client, test db)
    ├── test_auth.py
    ├── test_tasks.py
    ├── test_preview.py
    └── test_annotations.py
```

### Frontend (`web/`)

```
web/
├── public/
│   └── favicon.ico
├── src/
│   ├── App.vue
│   ├── main.ts
│   ├── router/index.ts
│   ├── layouts/
│   │   ├── DefaultLayout.vue
│   │   └── AuthLayout.vue
│   ├── views/
│   │   ├── LoginView.vue
│   │   ├── DashboardView.vue
│   │   ├── TaskDetailView.vue
│   │   ├── PreviewView.vue
│   │   └── AdminUsersView.vue
│   ├── components/
│   │   ├── FileUpload.vue
│   │   ├── TaskList.vue
│   │   ├── TaskProgress.vue
│   │   ├── ModuleNav.vue
│   │   ├── SectionTable.vue
│   │   ├── AnnotationPanel.vue
│   │   ├── AnnotationBadge.vue
│   │   └── DownloadCard.vue
│   ├── composables/
│   │   ├── useAuth.ts
│   │   ├── useSSE.ts
│   │   └── useAnnotation.ts
│   ├── stores/
│   │   ├── authStore.ts
│   │   ├── taskStore.ts
│   │   └── previewStore.ts
│   ├── api/
│   │   ├── client.ts
│   │   ├── auth.ts
│   │   ├── tasks.ts
│   │   └── annotations.ts
│   ├── types/
│   │   ├── task.ts
│   │   ├── annotation.ts
│   │   └── preview.ts
│   └── assets/
│       └── main.css
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── nginx.conf
└── Dockerfile
```

### Root Level (new files)

```
docker-compose.yml
.env.example
```

---

## Phase 1: 项目骨架 — Docker + FastAPI + PostgreSQL + Vue + 认证

> 目标: 搭建完整的开发环境骨架，实现用户登录/登出流程，前后端联调通过。

### Task 1.1: Backend Python 项目初始化

**Files:**
- Create: `server/requirements.txt`
- Create: `server/app/__init__.py`
- Create: `server/app/config.py`

- [ ] **Step 1: 创建 server/requirements.txt**

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
sqlalchemy[asyncio]>=2.0.25
asyncpg>=0.29.0
alembic>=1.13.0
celery[redis]>=5.3.0
redis>=5.0.0
python-jose[cryptography]>=3.3.0
bcrypt>=4.0.0
python-multipart>=0.0.6
httpx>=0.26.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

> **⚠️ 实施偏差:** `passlib[bcrypt]` 已替换为 `bcrypt>=4.0.0`。passlib 已停止维护且与 bcrypt>=5.0 不兼容（内部 wrap-bug 检测使用 >72 字节测试字符串触发 ValueError）。改为直接使用 bcrypt 库 + SHA-256 prehash 处理超长密码。

- [ ] **Step 2: 创建 config.py — 环境变量配置**

```python
# server/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "postgresql+asyncpg://biduser:password@localhost:5432/bid_analyzer"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DASHSCOPE_API_KEY: str = ""
    DATA_DIR: str = "/data"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: list[str] = [".doc", ".docx", ".pdf"]

settings = Settings()
```

> **⚠️ 实施偏差:** 使用 `model_config = SettingsConfigDict(...)` 替代已废弃的 `class Config`，避免 Pydantic V2 deprecation warning。

- [ ] **Step 3: 创建 `server/app/__init__.py`** (空文件)

- [ ] **Step 4: 验证 — 在 server/ 下执行 pip install**

Run: `cd server && pip install -r requirements.txt`
Expected: 所有依赖安装成功

- [ ] **Step 5: Commit**

```bash
git add server/requirements.txt server/app/__init__.py server/app/config.py
git commit -m "feat(web): init backend project with dependencies and config"
```

---

### Task 1.2: SQLAlchemy 数据库引擎 + ORM 模型

**Files:**
- Create: `server/app/database.py`
- Create: `server/app/models/__init__.py`
- Create: `server/app/models/user.py`
- Create: `server/app/models/task.py`
- Create: `server/app/models/annotation.py`
- Create: `server/app/models/generated_file.py`

- [ ] **Step 1: 创建 database.py**

```python
# server/app/database.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from server.app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 2: 创建 User 模型**

```python
# server/app/models/user.py
import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from server.app.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[datetime.datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 3: 创建 Task 模型**

```python
# server/app/models/task.py
import datetime
import uuid
from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.app.database import Base

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    current_step: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    parsed_path: Mapped[str | None] = mapped_column(String(1000))
    indexed_path: Mapped[str | None] = mapped_column(String(1000))
    extracted_path: Mapped[str | None] = mapped_column(String(1000))
    extracted_data: Mapped[dict | None] = mapped_column(JSONB)
    checkbox_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    annotations = relationship("Annotation", back_populates="task", cascade="all, delete-orphan")
    generated_files = relationship("GeneratedFile", back_populates="task", cascade="all, delete-orphan")
```

- [ ] **Step 4: 创建 Annotation 模型**

```python
# server/app/models/annotation.py
import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.app.database import Base

class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    module_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(20), nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    annotation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    llm_response: Mapped[str | None] = mapped_column(Text)
    reextract_celery_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    task = relationship("Task", back_populates="annotations")
```

- [ ] **Step 5: 创建 GeneratedFile 模型**

```python
# server/app/models/generated_file.py
import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from server.app.database import Base

class GeneratedFile(Base):
    __tablename__ = "generated_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    task = relationship("Task", back_populates="generated_files")
```

- [ ] **Step 6: 创建 models/__init__.py 导出所有模型**

```python
# server/app/models/__init__.py
from server.app.database import Base
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.annotation import Annotation
from server.app.models.generated_file import GeneratedFile

__all__ = ["Base", "User", "Task", "Annotation", "GeneratedFile"]
```

- [ ] **Step 7: Commit**

```bash
git add server/app/database.py server/app/models/
git commit -m "feat(web): add SQLAlchemy database engine and ORM models"
```

---

### Task 1.3: Alembic 数据库迁移

**Files:**
- Create: `server/alembic.ini`
- Create: `server/alembic/env.py`
- Create: `server/alembic/versions/` (directory)

- [ ] **Step 1: 初始化 Alembic**

```bash
cd server && alembic init alembic
```

- [ ] **Step 2: 编辑 alembic.ini — 设置 sqlalchemy.url 占位符**

将 `sqlalchemy.url` 设为空（由 env.py 动态获取）:
```ini
sqlalchemy.url =
```

- [ ] **Step 3: 编辑 alembic/env.py — 使用项目配置和模型**

```python
# server/alembic/env.py
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from server.app.config import settings
from server.app.database import Base
from server.app.models import User, Task, Annotation, GeneratedFile  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("+asyncpg", ""))
target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = settings.DATABASE_URL
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: 生成初始迁移**

```bash
cd server && alembic revision --autogenerate -m "initial tables"
```
Expected: 生成包含 users, tasks, annotations, generated_files 四张表的迁移文件

- [ ] **Step 5: Commit**

```bash
git add server/alembic.ini server/alembic/
git commit -m "feat(web): add Alembic migration with initial schema"
```

---

### Task 1.4: JWT 安全模块

**Files:**
- Create: `server/app/security.py`
- Create: `server/tests/conftest.py`
- Create: `server/tests/test_auth.py`

- [ ] **Step 1: 编写安全模块测试**

```python
# server/tests/test_auth.py
import pytest
from server.app.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

def test_password_hash_and_verify():
    pw = "testpassword123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)
    assert not verify_password("wrong", hashed)

def test_create_and_decode_access_token():
    token = create_access_token({"sub": "admin", "user_id": 1})
    payload = decode_token(token)
    assert payload["sub"] == "admin"
    assert payload["user_id"] == 1
    assert payload["type"] == "access"

def test_create_and_decode_refresh_token():
    token = create_refresh_token({"sub": "admin", "user_id": 1})
    payload = decode_token(token)
    assert payload["sub"] == "admin"
    assert payload["type"] == "refresh"

def test_decode_invalid_token():
    payload = decode_token("invalid.token.here")
    assert payload is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd server && python -m pytest tests/test_auth.py -v`
Expected: FAIL (security module not found)

- [ ] **Step 3: 实现 security.py**

```python
# server/app/security.py
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError
from server.app.config import settings

def _prehash(password: str) -> bytes:
    """Pre-hash with SHA-256 to handle passwords > 72 bytes (bcrypt limit)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except (JWTError, Exception):
        return None
```

> **⚠️ 实施偏差:** 直接使用 `bcrypt` 库替代 `passlib`。通过 SHA-256 prehash 将任意长度密码映射为 64 字节 hex 字符串，绕过 bcrypt 72 字节截断限制。`decode_token` 的异常捕获扩展为 `(JWTError, Exception)` 以处理 None 输入等边界情况。

- [ ] **Step 4: 运行测试验证通过**

Run: `cd server && python -m pytest tests/test_auth.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add server/app/security.py server/tests/
git commit -m "feat(web): add JWT security module with password hashing"
```

---

### Task 1.5: FastAPI 应用入口 + Auth 路由

**Files:**
- Create: `server/app/deps.py`
- Create: `server/app/schemas/auth.py`
- Create: `server/app/services/auth_service.py`
- Create: `server/app/routers/auth.py`
- Create: `server/app/main.py`

- [ ] **Step 1: 创建 Pydantic schemas**

```python
# server/app/schemas/auth.py
from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

class UserInfo(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    display_name: str | None
    role: str
```

- [ ] **Step 2: 创建依赖注入 deps.py**

```python
# server/app/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.security import decode_token
from server.app.models.user import User

security_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = payload.get("user_id")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
```

- [ ] **Step 3: 创建 auth_service.py**

```python
# server/app/services/auth_service.py
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.models.user import User
from server.app.security import verify_password, create_access_token, create_refresh_token

async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    return user

def generate_tokens(user: User) -> dict:
    data = {"sub": user.username, "user_id": user.id}
    return {
        "access_token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "token_type": "bearer",
    }
```

- [ ] **Step 4: 创建 auth 路由**

```python
# server/app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest, UserInfo
from server.app.services.auth_service import authenticate_user, generate_tokens
from server.app.security import decode_token, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return generate_tokens(user)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == payload["user_id"]))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return generate_tokens(user)

@router.post("/logout")
async def logout():
    """登出（JWT 无状态，服务端无需操作，前端清除 token 即可）"""
    return {"status": "ok"}

@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(get_current_user)):
    return user
```

- [ ] **Step 5: 创建 FastAPI 主入口**

```python
# server/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.app.routers import auth

app = FastAPI(title="招标文件分析系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 6 收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)

@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: 创建 schemas/__init__.py, services/__init__.py, routers/__init__.py** (空文件)

- [ ] **Step 7: 编写 API 集成测试**

```python
# server/tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from server.app.database import Base, get_db
from server.app.main import app
from server.app.security import hash_password
from server.app.models import User, Task, Annotation, GeneratedFile  # noqa: F401

# 使用 SQLite + aiosqlite 进行测试，无需运行 PostgreSQL
# 通过 type compiler 让 PG 专有类型 (UUID, JSONB) 在 SQLite 上工作
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

def _register_sqlite_compilers(engine):
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
    user = User(username="testuser", password_hash=hash_password("testpass"), display_name="Test User", role="user")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture
async def admin_user(db_session):
    user = User(username="admin", password_hash=hash_password("adminpass"), display_name="Admin", role="admin")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user

@pytest_asyncio.fixture
async def auth_headers(client, test_user):
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest_asyncio.fixture
async def admin_headers(client, admin_user):
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

> **⚠️ 实施偏差:** 测试改用 SQLite + aiosqlite（内存数据库），无需运行 PostgreSQL 即可执行全部测试。通过 `@compiles` 注册 PG_UUID → VARCHAR(36) 和 JSONB → JSON 的 SQLite 类型编译器，解决 PG 专有类型兼容问题。新增 `auth_headers` / `admin_headers` 便利 fixtures。

- [ ] **Step 8: 编写 auth API 测试**

```python
# server/tests/test_auth.py (追加以下测试到已有文件末尾)
import pytest

@pytest.mark.asyncio
async def test_login_success(client, test_user):
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data

@pytest.mark.asyncio
async def test_login_wrong_password(client, test_user):
    resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "wrong"})
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_me_with_token(client, test_user):
    login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login_resp.json()["access_token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"

@pytest.mark.asyncio
async def test_me_without_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 403  # no credentials

@pytest.mark.asyncio
async def test_refresh_token(client, test_user):
    login_resp = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    refresh = login_resp.json()["refresh_token"]
    resp = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
```

- [ ] **Step 9: 运行测试验证通过**

Run: `cd server && python -m pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 10: Commit**

```bash
git add server/app/ server/tests/
git commit -m "feat(web): add FastAPI app with auth routes and tests"
```

---

### Task 1.6: Vue 3 前端项目初始化

**Files:**
- Create: `web/` (entire Vue project via scaffolding)

- [ ] **Step 1: 使用 Vite 创建 Vue 3 + TypeScript 项目**

```bash
cd web && npm create vite@latest . -- --template vue-ts
```
如果 `web/` 目录不存在则先 `mkdir web`

- [ ] **Step 2: 安装依赖**

```bash
cd web && npm install
npm install vue-router@4 pinia axios
npm install -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 3: 配置 Tailwind CSS**

创建 `web/src/assets/main.css`:
```css
@import "tailwindcss";
```

编辑 `web/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 4: 配置路由**

```typescript
// web/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { requiresAuth: true } },
  { path: '/tasks/:id', name: 'task-detail', component: () => import('../views/TaskDetailView.vue'), meta: { requiresAuth: true } },
  { path: '/tasks/:id/preview', name: 'preview', component: () => import('../views/PreviewView.vue'), meta: { requiresAuth: true } },
  { path: '/admin/users', name: 'admin-users', component: () => import('../views/AdminUsersView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) return { name: 'login' }
})

export default router
```

- [ ] **Step 5: 配置 Pinia + Axios 客户端**

```typescript
// web/src/stores/authStore.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem('access_token') || '')
  const user = ref<{ id: number; username: string; display_name: string | null; role: string } | null>(null)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  function logout() {
    accessToken.value = ''
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { accessToken, user, isAuthenticated, isAdmin, setTokens, logout }
})
```

```typescript
// web/src/api/client.ts
import axios from 'axios'
import { useAuthStore } from '../stores/authStore'

const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401) {
      const refresh = localStorage.getItem('refresh_token')
      if (refresh && !error.config._retry) {
        error.config._retry = true
        try {
          const res = await axios.post('/api/auth/refresh', { refresh_token: refresh })
          const store = useAuthStore()
          store.setTokens(res.data.access_token, res.data.refresh_token)
          error.config.headers.Authorization = `Bearer ${res.data.access_token}`
          return client(error.config)
        } catch {
          const store = useAuthStore()
          store.logout()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

export default client
```

```typescript
// web/src/api/auth.ts
import client from './client'

export const authApi = {
  login: (username: string, password: string) =>
    client.post('/auth/login', { username, password }),
  me: () => client.get('/auth/me'),
}
```

- [ ] **Step 6: 创建登录页面**

```vue
<!-- web/src/views/LoginView.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import { authApi } from '../api/auth'

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const router = useRouter()
const authStore = useAuthStore()

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    const res = await authApi.login(username.value, password.value)
    authStore.setTokens(res.data.access_token, res.data.refresh_token)
    const meRes = await authApi.me()
    authStore.user = meRes.data
    router.push('/')
  } catch {
    error.value = '用户名或密码错误'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50">
    <div class="w-full max-w-md bg-white rounded-lg shadow-md p-8">
      <h1 class="text-2xl font-bold text-center text-gray-800 mb-8">招标文件分析系统</h1>
      <form @submit.prevent="handleLogin" class="space-y-6">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
          <input v-model="username" type="text" required
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
          <input v-model="password" type="password" required
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <p v-if="error" class="text-red-500 text-sm">{{ error }}</p>
        <button type="submit" :disabled="loading"
          class="w-full py-2 px-4 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50">
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
    </div>
  </div>
</template>
```

- [ ] **Step 7: 创建仪表板占位页面 + App.vue + main.ts**

```vue
<!-- web/src/views/DashboardView.vue -->
<template>
  <div class="p-6">
    <h1 class="text-2xl font-bold">仪表板</h1>
    <p class="text-gray-500 mt-2">Phase 1 完成 — 前后端联调成功</p>
  </div>
</template>
```

其余占位页面 (`TaskDetailView.vue`, `PreviewView.vue`, `AdminUsersView.vue`) 创建相同结构的最小占位。

编辑 `web/src/main.ts`:
```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/main.css'

createApp(App).use(createPinia()).use(router).mount('#app')
```

编辑 `web/src/App.vue`:
```vue
<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>
<template>
  <RouterView />
</template>
```

- [ ] **Step 8: 验证前端构建**

Run: `cd web && npm run build`
Expected: 构建成功，dist/ 目录生成

- [ ] **Step 9: Commit**

```bash
git add web/
git commit -m "feat(web): init Vue 3 + Tailwind frontend with login and routing"
```

---

### Task 1.7: Docker + docker-compose 集成

**Files:**
- Create: `server/Dockerfile`
- Create: `web/Dockerfile`
- Create: `web/nginx.conf`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: 创建后端 Dockerfile**

```dockerfile
# server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖 (antiword for .doc parsing)
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY server/requirements.txt /app/server/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r server/requirements.txt

# 复制源码
COPY src/ /app/src/
COPY config/ /app/config/
COPY server/ /app/server/

ENV PYTHONPATH=/app
```

- [ ] **Step 2: 创建前端 Dockerfile + Nginx 配置**

```nginx
# web/nginx.conf
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

```dockerfile
# web/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 3: 创建 docker-compose.yml**

```yaml
# docker-compose.yml (项目根目录)
name: bid-analyzer  # 必须显式指定，否则中文目录名导致 project name 为空

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: bid_analyzer
      POSTGRES_USER: biduser
      POSTGRES_PASSWORD: ${DB_PASSWORD:-devpassword}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U biduser"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: server/Dockerfile
    command: uvicorn server.app.main:app --host 0.0.0.0 --port 8000 --reload
    environment:
      DATABASE_URL: postgresql+asyncpg://biduser:${DB_PASSWORD:-devpassword}@postgres:5432/bid_analyzer
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}
      JWT_SECRET: ${JWT_SECRET:-dev-secret-change-in-production}
    volumes:
      - filedata:/data
      - ./src:/app/src
      - ./config:/app/config
      - ./server:/app/server
    ports:
      - "8000:8000"
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  worker:
    build:
      context: .
      dockerfile: server/Dockerfile
    command: celery -A server.app.tasks.celery_app worker --loglevel=info --concurrency=2
    environment:
      DATABASE_URL: postgresql+asyncpg://biduser:${DB_PASSWORD:-devpassword}@postgres:5432/bid_analyzer
      REDIS_URL: redis://redis:6379/0
      DASHSCOPE_API_KEY: ${DASHSCOPE_API_KEY:-}
    volumes:
      - filedata:/data
      - ./src:/app/src
      - ./config:/app/config
      - ./server:/app/server
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  nginx:
    build:
      context: ./web
      dockerfile: Dockerfile
    ports:
      - "80:80"
    depends_on:
      - api

volumes:
  pgdata:
  redisdata:
  filedata:
```

- [ ] **Step 4: 创建 .env.example**

```
DB_PASSWORD=devpassword
DASHSCOPE_API_KEY=sk-xxx
JWT_SECRET=change-me-in-production
```

- [ ] **Step 5: 创建 Celery app 占位** (worker 启动需要)

```python
# server/app/tasks/__init__.py
# (空文件)

# server/app/tasks/celery_app.py
from celery import Celery
from server.app.config import settings

celery_app = Celery("bid_analyzer", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_track_started=True,
)
# 自动发现同目录下的任务模块 (pipeline_task.py, reextract_task.py)
celery_app.autodiscover_tasks(["server.app.tasks"])
```

- [ ] **Step 6: 创建管理员创建脚本**

先创建 `server/scripts/__init__.py`（空文件，使其成为 Python 包）。

```python
# server/scripts/create_admin.py
"""创建初始管理员账号。用法: python -m server.scripts.create_admin"""
import asyncio
from sqlalchemy import select
from server.app.database import async_session_factory, engine, Base
from server.app.models.user import User
from server.app.security import hash_password

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            print("Admin user already exists.")
            return
        admin = User(username="admin", password_hash=hash_password("admin123"), display_name="管理员", role="admin")
        session.add(admin)
        await session.commit()
        print("Admin user created: admin / admin123")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7: 验证 docker-compose 构建**

Run: `docker-compose build`
Expected: 所有镜像构建成功

- [ ] **Step 8: 验证 docker-compose 启动**

Run: `docker-compose up -d && docker-compose ps`
Expected: 5 个容器全部 running/healthy

- [ ] **Step 9: 运行数据库迁移 + 创建管理员**

```bash
docker-compose exec api alembic -c server/alembic.ini upgrade head
docker-compose exec api python -m server.scripts.create_admin
```

- [ ] **Step 10: 验证完整流程**

1. 浏览器访问 `http://localhost` → 看到登录页
2. 输入 admin / admin123 → 跳转仪表板
3. `curl http://localhost/api/health` → `{"status": "ok"}`

- [ ] **Step 11: Commit**

```bash
git add server/Dockerfile web/Dockerfile web/nginx.conf docker-compose.yml .env.example server/app/tasks/ server/scripts/__init__.py server/scripts/create_admin.py
git commit -m "feat(web): add Docker infrastructure with 5-container compose stack"
```

---

## Phase 2: 文件上传 + Celery 管线任务 + 进度推送

> 目标: 用户可上传招标文件，后端异步执行完整分析管线，前端通过 SSE 实时展示进度。

### Task 2.1: 文件上传 API

**Files:**
- Create: `server/app/schemas/task.py`
- Create: `server/app/services/task_service.py`
- Create: `server/app/routers/tasks.py`
- Create: `server/tests/test_tasks.py`

- [ ] **Step 1: 创建 task schemas**

```python
# server/app/schemas/task.py
import datetime
import uuid
from pydantic import BaseModel

class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    filename: str
    file_size: int | None
    status: str
    current_step: str | None
    progress: int
    error_message: str | None
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None

class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 2: 编写上传测试**

```python
# server/tests/test_tasks.py
import pytest
from io import BytesIO

@pytest.mark.asyncio
async def test_upload_file_creates_task(client, test_user):
    # 先登录
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 上传文件
    files = {"file": ("test.docx", BytesIO(b"fake docx content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    resp = await client.post("/api/tasks", files=files, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "test.docx"
    assert data["status"] == "pending"

@pytest.mark.asyncio
async def test_upload_rejects_invalid_extension(client, test_user):
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    files = {"file": ("test.exe", BytesIO(b"evil"), "application/octet-stream")}
    resp = await client.post("/api/tasks", files=files, headers=headers)
    assert resp.status_code == 400
```

- [ ] **Step 3: 运行测试验证失败**

Run: `cd server && python -m pytest tests/test_tasks.py -v`
Expected: FAIL

- [ ] **Step 4: 实现 task_service.py**

```python
# server/app/services/task_service.py
import os
import uuid
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.task import Task

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}

async def create_task_from_upload(db: AsyncSession, file: UploadFile, user_id: int) -> Task:
    # 校验扩展名
    _, ext = os.path.splitext(file.filename or "")
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    # 校验大小
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (50MB)")

    # 保存文件
    task_id = uuid.uuid4()
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", str(task_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建任务记录
    task = Task(
        id=task_id,
        user_id=user_id,
        filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task
```

- [ ] **Step 5: 实现 tasks 路由 (上传部分)**

```python
# server/app/routers/tasks.py
from fastapi import APIRouter, Depends, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.schemas.task import TaskResponse
from server.app.services.task_service import create_task_from_upload

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def upload_and_create_task(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await create_task_from_upload(db, file, user.id)
    return task
```

在 `server/app/main.py` 中注册路由:
```python
from server.app.routers import auth, tasks
app.include_router(tasks.router)
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd server && python -m pytest tests/test_tasks.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add server/app/schemas/task.py server/app/services/task_service.py server/app/routers/tasks.py server/tests/test_tasks.py server/app/main.py
git commit -m "feat(web): add file upload endpoint with validation"
```

---

### Task 2.2: Celery 管线任务

**Files:**
- Create: `server/app/tasks/pipeline_task.py`
- Modify: `src/extractor/extractor.py` (添加 `extract_single_module`)

- [ ] **Step 1: 在现有 extractor.py 中添加 extract_single_module**

阅读 `src/extractor/extractor.py`，在 `extract_all()` 之后添加:

```python
def extract_single_module(module_key: str, tagged_paragraphs: list, settings: dict | None = None) -> dict | None:
    """提取单个模块，供 Web Celery Worker 调用。"""
    if module_key not in _MODULE_REGISTRY:
        raise ValueError(f"Unknown module: {module_key}")
    mod_path, func_name = _MODULE_REGISTRY[module_key]
    mod = importlib.import_module(mod_path)
    func = getattr(mod, func_name)
    return func(tagged_paragraphs, settings)
```

- [ ] **Step 2: 实现 pipeline_task.py**

```python
# server/app/tasks/pipeline_task.py
import json
import os
import uuid as _uuid
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.tasks.celery_app import celery_app
from server.app.config import settings

# 同步 DB 引擎 (Celery worker 中用同步)
_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)

# 9 个提取模块（与 src/extractor/extractor.py 的 _MODULE_REGISTRY 一致）
_MODULE_KEYS = [
    "module_a", "module_b", "module_c", "module_d", "module_e",
    "module_f", "module_g", "bid_format", "checklist",
]

def _get_task(db, task_id: str):
    """获取任务，正确转换 UUID。"""
    from server.app.models.task import Task
    return db.get(Task, _uuid.UUID(task_id))

@celery_app.task(bind=True, name="run_pipeline")
def run_pipeline(self, task_id: str):
    """执行完整分析管线，逐模块上报进度。"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index
    from src.extractor.extractor import extract_single_module
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from src.persistence import save_parsed, save_indexed, save_extracted
    from src.config import load_settings

    with Session(_sync_engine) as db:
        task = _get_task(db, task_id)
        if not task:
            return {"error": "Task not found"}
        task.status = "parsing"
        task.started_at = datetime.datetime.now(datetime.timezone.utc)
        file_path = task.file_path
        filename = task.filename
        db.commit()

    data_dir = os.path.join(settings.DATA_DIR, "intermediate", task_id)
    output_dir = os.path.join(settings.DATA_DIR, "output", task_id)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Layer 1: Parse (0-10%)
        self.update_state(state="PROGRESS", meta={"step": "parsing", "detail": "解析文档中...", "progress": 5})
        paragraphs = parse_document(file_path)
        parsed_path = os.path.join(data_dir, "parsed.json")
        save_parsed(paragraphs, parsed_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "indexing"
            task.parsed_path = parsed_path
            db.commit()

        # Layer 2: Index (10-20%)
        self.update_state(state="PROGRESS", meta={"step": "indexing", "detail": "构建索引中...", "progress": 15})
        index_result = build_index(paragraphs)
        indexed_path = os.path.join(data_dir, "indexed.json")
        save_indexed(index_result, indexed_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "extracting"
            task.indexed_path = indexed_path
            db.commit()

        # Layer 3: Extract (20-90%) — 逐模块提取并上报进度
        api_settings = load_settings()
        tagged = index_result.get("tagged_paragraphs", [])
        modules_result = {}
        for i, module_key in enumerate(_MODULE_KEYS):
            progress = 20 + int(70 * i / len(_MODULE_KEYS))
            self.update_state(state="PROGRESS", meta={
                "step": "extracting",
                "detail": f"提取 {module_key} [{i+1}/{len(_MODULE_KEYS)}]",
                "progress": progress,
                "current_module": module_key,
                "modules_done": i,
                "modules_total": len(_MODULE_KEYS),
            })
            try:
                modules_result[module_key] = extract_single_module(module_key, tagged, api_settings)
            except Exception as e:
                modules_result[module_key] = {"status": "failed", "error": str(e)}

        extracted = {"schema_version": "1.0", "modules": modules_result}
        extracted_path = os.path.join(data_dir, "extracted.json")
        save_extracted(extracted, extracted_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "generating"
            task.extracted_path = extracted_path
            task.extracted_data = extracted
            db.commit()

        # Layer 5: Generate (90-100%)
        self.update_state(state="PROGRESS", meta={"step": "generating", "detail": "生成文档中...", "progress": 95})
        stem = os.path.splitext(filename)[0]
        report_path = os.path.join(output_dir, f"{stem}_分析报告.docx")
        format_path = os.path.join(output_dir, f"{stem}_投标文件格式.docx")
        checklist_path = os.path.join(output_dir, f"{stem}_资料清单.docx")

        render_report(extracted, report_path)
        render_format(extracted, format_path)
        render_checklist(extracted, checklist_path)

        # 完成
        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.datetime.now(datetime.timezone.utc)

            from server.app.models.generated_file import GeneratedFile
            for ftype, fpath in [("report", report_path), ("format", format_path), ("checklist", checklist_path)]:
                size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
                db.add(GeneratedFile(task_id=_uuid.UUID(task_id), file_type=ftype, file_path=fpath, file_size=size))
            db.commit()

        return {"status": "completed", "task_id": task_id}

    except Exception as e:
        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
        raise
```

- [ ] **Step 3: 在上传路由中触发 Celery 任务**

修改 `server/app/routers/tasks.py` 的 `upload_and_create_task`:

```python
from server.app.tasks.pipeline_task import run_pipeline

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def upload_and_create_task(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await create_task_from_upload(db, file, user.id)
    # 触发异步管线
    celery_result = run_pipeline.delay(str(task.id))
    task.celery_task_id = celery_result.id
    await db.commit()
    await db.refresh(task)
    return task
```

- [ ] **Step 4: Commit**

```bash
git add server/app/tasks/pipeline_task.py server/app/routers/tasks.py src/extractor/extractor.py
git commit -m "feat(web): add Celery pipeline task with progress reporting"
```

---

### Task 2.3: SSE 进度推送

**Files:**
- Modify: `server/app/routers/tasks.py` (添加 SSE endpoint)

- [ ] **Step 1: 添加 SSE 进度端点**

在 `server/app/routers/tasks.py` 中添加:

```python
import asyncio
import json
from fastapi.responses import StreamingResponse
from celery.result import AsyncResult
from server.app.tasks.celery_app import celery_app

@router.get("/{task_id}/progress")
async def task_progress(task_id: str, token: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """SSE 端点：从 Redis 读取 Celery 任务状态并推送。
    注意: SSE EventSource 不支持自定义 header，前端通过 query param ?token=xxx 传递 JWT，
    或直接使用 fetch + ReadableStream。此处同时支持 Authorization header 和 query param。
    """
    from server.app.models.task import Task
    from sqlalchemy import select

    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user.id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    celery_task_id = task.celery_task_id

    async def event_generator():
        if not celery_task_id:
            yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            return

        while True:
            result = AsyncResult(celery_task_id, app=celery_app)
            if result.state == "PROGRESS":
                yield f"data: {json.dumps(result.info)}\n\n"
            elif result.state == "SUCCESS":
                yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                break
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': -1, 'step': 'failed', 'error': str(result.result)})}\n\n"
                break
            elif result.state == "PENDING":
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 2: Commit**

```bash
git add server/app/routers/tasks.py
git commit -m "feat(web): add SSE progress endpoint for pipeline tasks"
```

---

### Task 2.4: 前端上传组件 + 进度展示

**Files:**
- Create: `web/src/api/tasks.ts`
- Create: `web/src/components/FileUpload.vue`
- Create: `web/src/components/TaskProgress.vue`
- Create: `web/src/composables/useSSE.ts`
- Create: `web/src/stores/taskStore.ts`
- Create: `web/src/types/task.ts`

- [ ] **Step 1: 创建类型定义**

```typescript
// web/src/types/task.ts
export interface Task {
  id: string
  filename: string
  file_size: number | null
  status: string
  current_step: string | null
  progress: number
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface ProgressEvent {
  step: string
  detail?: string
  progress: number
  current_module?: string
  modules_done?: number
  modules_total?: number
  error?: string
}
```

- [ ] **Step 2: 创建 tasks API 模块**

```typescript
// web/src/api/tasks.ts
import client from './client'
import type { Task } from '../types/task'

export const tasksApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return client.post<Task>('/tasks', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    client.get('/tasks', { params }),
  get: (id: string) => client.get<Task>(`/tasks/${id}`),
  delete: (id: string) => client.delete(`/tasks/${id}`),
}
```

- [ ] **Step 3: 创建 SSE composable**

```typescript
// web/src/composables/useSSE.ts
import { ref, onUnmounted } from 'vue'
import type { ProgressEvent } from '../types/task'

export function useSSE(url: string) {
  const progress = ref<ProgressEvent | null>(null)
  const connected = ref(false)
  let eventSource: EventSource | null = null

  function connect() {
    const token = localStorage.getItem('access_token')
    // SSE 不支持自定义 header，通过 query param 传 token 或使用 EventSource polyfill
    // 简单方案: 直接使用 fetch + ReadableStream
    const fullUrl = `/api${url}`
    eventSource = new EventSource(fullUrl)
    connected.value = true

    eventSource.onmessage = (event) => {
      progress.value = JSON.parse(event.data)
    }

    eventSource.onerror = () => {
      connected.value = false
      eventSource?.close()
    }
  }

  function disconnect() {
    eventSource?.close()
    connected.value = false
  }

  onUnmounted(disconnect)

  return { progress, connected, connect, disconnect }
}
```

- [ ] **Step 4: 创建 FileUpload 组件**

```vue
<!-- web/src/components/FileUpload.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { tasksApi } from '../api/tasks'
import { useRouter } from 'vue-router'

const router = useRouter()
const dragging = ref(false)
const uploading = ref(false)
const error = ref('')

function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadFile(file)
}

function onSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) uploadFile(file)
}

async function uploadFile(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['doc', 'docx', 'pdf'].includes(ext || '')) {
    error.value = '仅支持 .doc / .docx / .pdf 文件'
    return
  }
  error.value = ''
  uploading.value = true
  try {
    const res = await tasksApi.upload(file)
    router.push(`/tasks/${res.data.id}`)
  } catch (e: any) {
    error.value = e.response?.data?.detail || '上传失败'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div
    @dragover.prevent="dragging = true"
    @dragleave="dragging = false"
    @drop.prevent="onDrop"
    :class="['border-2 border-dashed rounded-lg p-10 text-center cursor-pointer transition-colors',
      dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400']"
  >
    <div class="text-gray-500">
      <p class="text-lg font-medium">拖拽上传招标文件</p>
      <p class="text-sm mt-1">支持 .doc / .docx / .pdf</p>
      <label class="mt-4 inline-block px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 cursor-pointer">
        {{ uploading ? '上传中...' : '点击选择文件' }}
        <input type="file" class="hidden" accept=".doc,.docx,.pdf" @change="onSelect" :disabled="uploading" />
      </label>
    </div>
    <p v-if="error" class="text-red-500 text-sm mt-2">{{ error }}</p>
  </div>
</template>
```

- [ ] **Step 5: 创建 TaskProgress 组件**

```vue
<!-- web/src/components/TaskProgress.vue -->
<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { useSSE } from '../composables/useSSE'

const props = defineProps<{ taskId: string }>()
const emit = defineEmits<{ completed: [] }>()
const { progress, connect } = useSSE(`/tasks/${props.taskId}/progress`)

onMounted(connect)

const steps = [
  { key: 'parsing', label: '文档解析' },
  { key: 'indexing', label: '智能索引' },
  { key: 'extracting', label: '结构提取' },
  { key: 'generating', label: '文档生成' },
]

function stepStatus(stepKey: string) {
  if (!progress.value) return 'pending'
  const order = steps.map(s => s.key)
  const currentIdx = order.indexOf(progress.value.step)
  const thisIdx = order.indexOf(stepKey)
  if (progress.value.step === 'completed') return 'done'
  if (progress.value.step === 'failed') return thisIdx <= currentIdx ? 'failed' : 'pending'
  if (thisIdx < currentIdx) return 'done'
  if (thisIdx === currentIdx) return 'active'
  return 'pending'
}

watch(() => progress.value?.step, (step) => {
  if (step === 'completed') emit('completed')
})
</script>

<template>
  <div class="space-y-4">
    <!-- 进度条 -->
    <div class="w-full bg-gray-200 rounded-full h-3">
      <div class="bg-blue-600 h-3 rounded-full transition-all duration-500"
        :style="{ width: `${Math.max(progress?.progress || 0, 0)}%` }"></div>
    </div>
    <p class="text-sm text-gray-500 text-right">{{ progress?.progress || 0 }}%</p>

    <!-- 步骤列表 -->
    <div class="space-y-3">
      <div v-for="step in steps" :key="step.key" class="flex items-center gap-3">
        <span v-if="stepStatus(step.key) === 'done'" class="text-green-500">&#10003;</span>
        <span v-else-if="stepStatus(step.key) === 'active'" class="text-blue-500 animate-pulse">&#9679;</span>
        <span v-else-if="stepStatus(step.key) === 'failed'" class="text-red-500">&#10007;</span>
        <span v-else class="text-gray-300">&#9675;</span>
        <span :class="stepStatus(step.key) === 'active' ? 'font-medium' : 'text-gray-500'">{{ step.label }}</span>
        <span v-if="stepStatus(step.key) === 'active' && progress?.detail" class="text-sm text-gray-400 ml-2">
          {{ progress.detail }}
        </span>
      </div>
    </div>

    <!-- 错误信息 -->
    <div v-if="progress?.step === 'failed'" class="bg-red-50 text-red-700 p-3 rounded-md text-sm mt-4">
      {{ progress.error || '分析失败' }}
    </div>
  </div>
</template>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/
git commit -m "feat(web): add file upload, SSE progress, and task progress components"
```

---

## Phase 3: 任务列表 + 历史管理 + 文件下载

> 目标: 仪表板展示任务列表（分页、筛选），任务详情页展示下载，支持删除任务。

### Task 3.1: 任务列表 + 删除 API

**Files:**
- Modify: `server/app/services/task_service.py`
- Modify: `server/app/routers/tasks.py`
- Modify: `server/tests/test_tasks.py`

- [ ] **Step 1: 在 task_service.py 中添加查询/删除服务**

```python
# 追加到 server/app/services/task_service.py
import shutil
from sqlalchemy import select, func

async def get_tasks(db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20, status: str | None = None) -> tuple[list, int]:
    query = select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc())
    count_query = select(func.count()).select_from(Task).where(Task.user_id == user_id)
    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total

async def get_task(db: AsyncSession, task_id: str, user_id: int) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    return result.scalar_one_or_none()

async def delete_task(db: AsyncSession, task_id: str, user_id: int) -> bool:
    task = await get_task(db, task_id, user_id)
    if not task:
        return False
    # 删除文件
    for dir_prefix in ["uploads", "intermediate", "output"]:
        dir_path = os.path.join(settings.DATA_DIR, dir_prefix, str(task_id))
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
    await db.delete(task)
    await db.commit()
    return True
```

- [ ] **Step 2: 添加路由**

```python
# 追加到 server/app/routers/tasks.py
from server.app.schemas.task import TaskListResponse
from server.app.services.task_service import get_tasks, get_task, delete_task

@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await get_tasks(db, user.id, page, page_size, status)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)

@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_detail(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await get_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.delete("/{task_id}", status_code=204)
async def remove_task(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await delete_task(db, task_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")
```

- [ ] **Step 3: 编写测试并验证**

追加到 `server/tests/test_tasks.py`:

```python
@pytest.mark.asyncio
async def test_list_tasks(client, test_user):
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get("/api/tasks", headers=headers)
    assert resp.status_code == 200
    assert "items" in resp.json()
    assert "total" in resp.json()

@pytest.mark.asyncio
async def test_delete_task(client, test_user):
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 先上传
    from io import BytesIO
    files = {"file": ("test.docx", BytesIO(b"content"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    upload_resp = await client.post("/api/tasks", files=files, headers=headers)
    task_id = upload_resp.json()["id"]
    # 删除
    resp = await client.delete(f"/api/tasks/{task_id}", headers=headers)
    assert resp.status_code == 204
    # 确认已删除
    get_resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
    assert get_resp.status_code == 404
```

Run: `cd server && python -m pytest tests/test_tasks.py -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add server/app/services/task_service.py server/app/routers/tasks.py server/tests/test_tasks.py
git commit -m "feat(web): add task list, detail, and delete APIs"
```

---

### Task 3.2: 文件下载 + 重新生成 API

**Files:**
- Create: `server/app/routers/download.py`

- [ ] **Step 1: 实现下载和重新生成路由**

```python
# server/app/routers/download.py
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile

router = APIRouter(prefix="/api/tasks", tags=["download"])

@router.get("/{task_id}/download/{file_type}")
async def download_file(
    task_id: str,
    file_type: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type not in ("report", "format", "checklist"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    # 验证任务属于当前用户
    task_result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user.id))
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(GeneratedFile).where(
            GeneratedFile.task_id == task_id,
            GeneratedFile.file_type == file_type,
        ).order_by(GeneratedFile.version.desc())
    )
    gf = result.scalar_one_or_none()
    if not gf or not os.path.exists(gf.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        gf.file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=os.path.basename(gf.file_path),
    )

@router.post("/{task_id}/regenerate")
async def regenerate_files(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """根据最新 extracted_data 重新生成三份 .docx"""
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user.id))
    task = result.scalar_one_or_none()
    if not task or not task.extracted_data:
        raise HTTPException(status_code=404, detail="Task not found or no data")

    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from server.app.config import settings

    output_dir = os.path.join(settings.DATA_DIR, "output", str(task_id))
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(task.filename)[0]

    extracted = task.extracted_data
    paths = {
        "report": os.path.join(output_dir, f"{stem}_分析报告.docx"),
        "format": os.path.join(output_dir, f"{stem}_投标文件格式.docx"),
        "checklist": os.path.join(output_dir, f"{stem}_资料清单.docx"),
    }

    render_report(extracted, paths["report"])
    render_format(extracted, paths["format"])
    render_checklist(extracted, paths["checklist"])

    # 更新 generated_files 记录（递增版本号）
    for ftype, fpath in paths.items():
        result = await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == task_id, GeneratedFile.file_type == ftype
            ).order_by(GeneratedFile.version.desc())
        )
        existing = result.scalar_one_or_none()
        new_version = (existing.version + 1) if existing else 1
        db.add(GeneratedFile(
            task_id=task_id, file_type=ftype, file_path=fpath,
            file_size=os.path.getsize(fpath), version=new_version,
        ))
    await db.commit()

    return {"status": "ok", "message": "文件已重新生成"}
```

在 `server/app/main.py` 注册: `from server.app.routers import download; app.include_router(download.router)`

- [ ] **Step 2: Commit**

```bash
git add server/app/routers/download.py server/app/main.py
git commit -m "feat(web): add file download and regenerate APIs"
```

---

### Task 3.3: 前端仪表板 + 任务详情页

**Files:**
- Modify: `web/src/views/DashboardView.vue`
- Create: `web/src/components/TaskList.vue`
- Create: `web/src/components/DownloadCard.vue`
- Modify: `web/src/views/TaskDetailView.vue`
- Create: `web/src/layouts/DefaultLayout.vue`

- [ ] **Step 1: 创建 DefaultLayout (顶栏 + 内容)**

```vue
<!-- web/src/layouts/DefaultLayout.vue -->
<script setup lang="ts">
import { useAuthStore } from '../stores/authStore'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white shadow-sm border-b">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <router-link to="/" class="text-lg font-bold text-gray-800">招标文件分析系统</router-link>
        <div class="flex items-center gap-4">
          <span class="text-sm text-gray-600">{{ auth.user?.display_name || auth.user?.username }}</span>
          <button @click="logout" class="text-sm text-gray-500 hover:text-red-500">退出</button>
        </div>
      </div>
    </header>
    <main class="max-w-7xl mx-auto px-4 py-6">
      <slot />
    </main>
  </div>
</template>
```

- [ ] **Step 2: 创建 TaskList 组件**

```vue
<!-- web/src/components/TaskList.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { tasksApi } from '../api/tasks'
import type { Task } from '../types/task'

const tasks = ref<Task[]>([])
const total = ref(0)
const page = ref(1)
const statusFilter = ref('')
const loading = ref(false)

async function loadTasks() {
  loading.value = true
  try {
    const res = await tasksApi.list({ page: page.value, status: statusFilter.value || undefined })
    tasks.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

onMounted(loadTasks)
watch([page, statusFilter], loadTasks)

const statusMap: Record<string, { label: string; class: string }> = {
  pending: { label: '等待中', class: 'text-gray-500' },
  parsing: { label: '解析中', class: 'text-blue-500' },
  indexing: { label: '索引中', class: 'text-blue-500' },
  extracting: { label: '提取中', class: 'text-blue-500' },
  generating: { label: '生成中', class: 'text-blue-500' },
  completed: { label: '已完成', class: 'text-green-600' },
  failed: { label: '失败', class: 'text-red-500' },
}

defineExpose({ loadTasks })
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">我的分析任务</h2>
      <select v-model="statusFilter" class="border rounded px-2 py-1 text-sm">
        <option value="">全部</option>
        <option value="completed">已完成</option>
        <option value="failed">失败</option>
        <option value="extracting">进行中</option>
      </select>
    </div>
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-left">
          <tr>
            <th class="px-4 py-3">文件名</th>
            <th class="px-4 py-3">状态</th>
            <th class="px-4 py-3">进度</th>
            <th class="px-4 py-3">时间</th>
            <th class="px-4 py-3">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id" class="border-t hover:bg-gray-50">
            <td class="px-4 py-3 truncate max-w-xs">{{ task.filename }}</td>
            <td class="px-4 py-3">
              <span :class="statusMap[task.status]?.class || ''">{{ statusMap[task.status]?.label || task.status }}</span>
            </td>
            <td class="px-4 py-3">{{ task.progress }}%</td>
            <td class="px-4 py-3 text-gray-500">{{ new Date(task.created_at).toLocaleDateString() }}</td>
            <td class="px-4 py-3">
              <router-link :to="`/tasks/${task.id}`" class="text-blue-600 hover:underline">查看</router-link>
            </td>
          </tr>
          <tr v-if="tasks.length === 0">
            <td colspan="5" class="px-4 py-8 text-center text-gray-400">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="total > 20" class="flex justify-center gap-2 mt-4">
      <button @click="page--" :disabled="page <= 1" class="px-3 py-1 border rounded disabled:opacity-50">上一页</button>
      <span class="px-3 py-1 text-sm text-gray-500">第 {{ page }} 页</span>
      <button @click="page++" :disabled="page * 20 >= total" class="px-3 py-1 border rounded disabled:opacity-50">下一页</button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 更新 DashboardView**

```vue
<!-- web/src/views/DashboardView.vue -->
<script setup lang="ts">
import DefaultLayout from '../layouts/DefaultLayout.vue'
import FileUpload from '../components/FileUpload.vue'
import TaskList from '../components/TaskList.vue'
</script>

<template>
  <DefaultLayout>
    <FileUpload class="mb-8" />
    <TaskList />
  </DefaultLayout>
</template>
```

- [ ] **Step 4: 创建 DownloadCard 组件**

```vue
<!-- web/src/components/DownloadCard.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import client from '../api/client'

const props = defineProps<{ taskId: string; fileType: string; label: string }>()
const downloading = ref(false)

async function download() {
  downloading.value = true
  try {
    const res = await client.get(`/tasks/${props.taskId}/download/${props.fileType}`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    // 从 Content-Disposition 或 label 获取文件名
    const disposition = res.headers['content-disposition']
    const filename = disposition?.match(/filename="?(.+)"?/)?.[1] || props.label
    a.download = filename
    a.click()
    window.URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <div class="flex items-center justify-between bg-white border rounded-lg px-4 py-3">
    <span class="text-sm font-medium">{{ label }}</span>
    <button @click="download" :disabled="downloading" class="text-blue-600 hover:underline text-sm disabled:opacity-50">
      {{ downloading ? '下载中...' : '下载' }}
    </button>
  </div>
</template>
```

- [ ] **Step 5: 实现 TaskDetailView**

```vue
<!-- web/src/views/TaskDetailView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import TaskProgress from '../components/TaskProgress.vue'
import DownloadCard from '../components/DownloadCard.vue'
import { tasksApi } from '../api/tasks'
import type { Task } from '../types/task'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id as string
const task = ref<Task | null>(null)

onMounted(async () => {
  const res = await tasksApi.get(taskId)
  task.value = res.data
})

function onCompleted() {
  tasksApi.get(taskId).then(res => { task.value = res.data })
}

const fileTypes = [
  { type: 'report', label: '分析报告.docx' },
  { type: 'format', label: '投标文件格式.docx' },
  { type: 'checklist', label: '资料清单.docx' },
]
</script>

<template>
  <DefaultLayout>
    <div class="mb-4">
      <button @click="router.push('/')" class="text-sm text-blue-600 hover:underline">&larr; 返回</button>
    </div>
    <h1 class="text-xl font-bold mb-6">{{ task?.filename }}</h1>

    <!-- 进行中 -->
    <div v-if="task && !['completed', 'failed'].includes(task.status)" class="bg-white rounded-lg shadow p-6">
      <h2 class="text-lg font-semibold mb-4">分析进度</h2>
      <TaskProgress :task-id="taskId" @completed="onCompleted" />
    </div>

    <!-- 已完成 -->
    <div v-if="task?.status === 'completed'" class="space-y-4">
      <div class="flex gap-3">
        <router-link :to="`/tasks/${taskId}/preview`"
          class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">预览分析结果</router-link>
      </div>
      <div class="space-y-2">
        <h2 class="text-lg font-semibold">生成文件</h2>
        <DownloadCard v-for="ft in fileTypes" :key="ft.type" :task-id="taskId" :file-type="ft.type" :label="ft.label" />
      </div>
    </div>

    <!-- 失败 -->
    <div v-if="task?.status === 'failed'" class="bg-red-50 text-red-700 p-4 rounded-md">
      {{ task.error_message || '分析失败' }}
    </div>
  </DefaultLayout>
</template>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/
git commit -m "feat(web): add dashboard, task list, task detail, and download UI"
```

---

## Phase 4: 交互式预览（表格渲染 + 勾选）

> 目标: 完成预览页面三栏布局，可浏览所有模块表格数据，支持勾选确认。

### Task 4.1: 预览数据 API + 勾选 API

**Files:**
- Create: `server/app/routers/preview.py`
- Create: `server/app/services/preview_service.py`

- [ ] **Step 1: 实现 preview_service.py**

```python
# server/app/services/preview_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from server.app.models.task import Task

async def get_preview_data(db: AsyncSession, task_id: str, user_id: int) -> dict | None:
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    task = result.scalar_one_or_none()
    if not task or not task.extracted_data:
        return None
    return {
        "extracted_data": task.extracted_data,
        "checkbox_data": task.checkbox_data or {},
    }

async def update_checkbox(db: AsyncSession, task_id: str, user_id: int, module_key: str, section_id: str, row_index: int, checked: bool) -> bool:
    result = await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    task = result.scalar_one_or_none()
    if not task:
        return False
    cb = dict(task.checkbox_data or {})
    cb.setdefault(module_key, {}).setdefault(section_id, {})[str(row_index)] = checked
    task.checkbox_data = cb
    await db.commit()
    return True
```

- [ ] **Step 2: 实现 preview 路由**

```python
# server/app/routers/preview.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.services.preview_service import get_preview_data, update_checkbox

router = APIRouter(prefix="/api/tasks", tags=["preview"])

class CheckboxUpdate(BaseModel):
    module_key: str
    section_id: str
    row_index: int
    checked: bool

@router.get("/{task_id}/preview")
async def preview(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    data = await get_preview_data(db, task_id, user.id)
    if not data:
        raise HTTPException(status_code=404, detail="No preview data")
    return data

@router.put("/{task_id}/preview/checkbox")
async def toggle_checkbox(task_id: str, body: CheckboxUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ok = await update_checkbox(db, task_id, user.id, body.module_key, body.section_id, body.row_index, body.checked)
    if not ok:
        raise HTTPException(status_code=404)
    return {"status": "ok"}
```

在 `server/app/main.py` 注册: `from server.app.routers import preview; app.include_router(preview.router)`

- [ ] **Step 3: 编写测试**

```python
# server/tests/test_preview.py
import pytest

@pytest.mark.asyncio
async def test_toggle_checkbox(client, test_user, db_session):
    # 创建一个有 extracted_data 的任务
    from server.app.models.task import Task
    import uuid
    task = Task(id=uuid.uuid4(), user_id=test_user.id, filename="t.docx", file_path="/tmp/t.docx",
                status="completed", extracted_data={"modules": {}}, checkbox_data={})
    db_session.add(task)
    await db_session.commit()

    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(f"/api/tasks/{task.id}/preview/checkbox", json={
        "module_key": "module_a", "section_id": "A1", "row_index": 0, "checked": True
    }, headers=headers)
    assert resp.status_code == 200

    # 验证 preview 返回勾选状态
    preview = await client.get(f"/api/tasks/{task.id}/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["checkbox_data"]["module_a"]["A1"]["0"] is True
```

Run: `cd server && python -m pytest tests/test_preview.py -v`

- [ ] **Step 4: Commit**

```bash
git add server/app/routers/preview.py server/app/services/preview_service.py server/tests/test_preview.py server/app/main.py
git commit -m "feat(web): add preview and checkbox APIs"
```

---

### Task 4.2: 前端预览页面

**Files:**
- Create: `web/src/types/preview.ts`
- Create: `web/src/api/annotations.ts` (预留)
- Create: `web/src/stores/previewStore.ts`
- Create: `web/src/components/ModuleNav.vue`
- Create: `web/src/components/SectionTable.vue`
- Modify: `web/src/views/PreviewView.vue`

- [ ] **Step 1: 创建类型定义**

```typescript
// web/src/types/preview.ts
export interface Section {
  id: string
  title: string
  type: string
  columns?: string[]
  rows?: string[][]
  content?: string
  sections?: Section[]
}

export interface Module {
  title: string
  sections: Section[]
  status?: string
  error?: string
}

export interface PreviewData {
  extracted_data: {
    modules: Record<string, Module | null>
  }
  checkbox_data: Record<string, Record<string, Record<string, boolean>>>
}
```

- [ ] **Step 2: 创建 previewStore**

```typescript
// web/src/stores/previewStore.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'
import type { PreviewData } from '../types/preview'

export const usePreviewStore = defineStore('preview', () => {
  const data = ref<PreviewData | null>(null)
  const currentModule = ref('')
  const currentSection = ref('')
  const loading = ref(false)

  async function loadPreview(taskId: string) {
    loading.value = true
    try {
      const res = await client.get<PreviewData>(`/tasks/${taskId}/preview`)
      data.value = res.data
      // 默认选中第一个模块
      const modules = Object.keys(res.data.extracted_data.modules || {})
      if (modules.length) currentModule.value = modules[0]
    } finally {
      loading.value = false
    }
  }

  async function toggleCheckbox(taskId: string, moduleKey: string, sectionId: string, rowIndex: number, checked: boolean) {
    await client.put(`/tasks/${taskId}/preview/checkbox`, { module_key: moduleKey, section_id: sectionId, row_index: rowIndex, checked })
    // 更新本地状态
    if (data.value) {
      const cb = data.value.checkbox_data
      if (!cb[moduleKey]) cb[moduleKey] = {}
      if (!cb[moduleKey][sectionId]) cb[moduleKey][sectionId] = {}
      cb[moduleKey][sectionId][String(rowIndex)] = checked
    }
  }

  return { data, currentModule, currentSection, loading, loadPreview, toggleCheckbox }
})
```

- [ ] **Step 3: 创建 ModuleNav 组件**

```vue
<!-- web/src/components/ModuleNav.vue -->
<script setup lang="ts">
import { usePreviewStore } from '../stores/previewStore'
import type { Module } from '../types/preview'

const store = usePreviewStore()

const props = defineProps<{ modules: Record<string, Module | null> }>()

function selectModule(key: string) {
  store.currentModule = key
  store.currentSection = ''
}

function selectSection(moduleKey: string, sectionId: string) {
  store.currentModule = moduleKey
  store.currentSection = sectionId
}
</script>

<template>
  <nav class="w-56 bg-white border-r overflow-y-auto h-full">
    <div v-for="(mod, key) in props.modules" :key="key" class="py-1">
      <button v-if="mod"
        @click="selectModule(key as string)"
        :class="['w-full text-left px-4 py-2 text-sm hover:bg-gray-100',
          store.currentModule === key ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700']">
        {{ mod.title }}
      </button>
      <!-- Section 子导航 -->
      <div v-if="mod && store.currentModule === key">
        <button v-for="sec in mod.sections" :key="sec.id"
          @click="selectSection(key as string, sec.id)"
          :class="['w-full text-left pl-8 pr-4 py-1 text-xs hover:bg-gray-50',
            store.currentSection === sec.id ? 'text-blue-600 font-medium' : 'text-gray-500']">
          {{ sec.id }} {{ sec.title }}
        </button>
      </div>
    </div>
  </nav>
</template>
```

- [ ] **Step 4: 创建 SectionTable 组件**

```vue
<!-- web/src/components/SectionTable.vue -->
<script setup lang="ts">
import { usePreviewStore } from '../stores/previewStore'
import type { Section } from '../types/preview'

const props = defineProps<{
  section: Section
  moduleKey: string
  taskId: string
  checkboxData: Record<string, boolean>
}>()

const store = usePreviewStore()

function isChecked(rowIndex: number): boolean {
  return props.checkboxData?.[String(rowIndex)] || false
}

function toggle(rowIndex: number) {
  const current = isChecked(rowIndex)
  store.toggleCheckbox(props.taskId, props.moduleKey, props.section.id, rowIndex, !current)
}
</script>

<template>
  <div class="mb-6">
    <h3 class="text-sm font-semibold text-gray-700 mb-2">{{ section.id }} {{ section.title }}</h3>
    <table v-if="section.columns && section.rows" class="w-full text-sm border-collapse border">
      <thead>
        <tr class="bg-gray-50">
          <th v-for="col in section.columns" :key="col" class="border px-3 py-2 text-left font-medium text-gray-600">
            {{ col }}
          </th>
          <th class="border px-3 py-2 w-12 text-center font-medium text-gray-600">确认</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, rowIdx) in section.rows" :key="rowIdx"
          class="hover:bg-blue-50 cursor-pointer"
          @click="$emit('select-row', { moduleKey, sectionId: section.id, rowIndex: rowIdx, row })">
          <td v-for="(cell, cellIdx) in row" :key="cellIdx" class="border px-3 py-2 text-gray-700">
            {{ cell }}
          </td>
          <td class="border px-3 py-2 text-center">
            <input type="checkbox" :checked="isChecked(rowIdx)" @click.stop="toggle(rowIdx)"
              class="w-4 h-4 text-blue-600 rounded" />
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="section.content" class="bg-gray-50 p-3 rounded text-sm text-gray-700">
      {{ section.content }}
    </div>
  </div>
</template>
```

- [ ] **Step 5: 实现 PreviewView**

```vue
<!-- web/src/views/PreviewView.vue -->
<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePreviewStore } from '../stores/previewStore'
import ModuleNav from '../components/ModuleNav.vue'
import SectionTable from '../components/SectionTable.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id as string
const store = usePreviewStore()

onMounted(() => store.loadPreview(taskId))

const modules = computed(() => store.data?.extracted_data?.modules || {})
const currentModuleData = computed(() => {
  const mod = modules.value[store.currentModule]
  return mod || null
})
const checkboxData = computed(() => store.data?.checkbox_data || {})

function getCheckboxForSection(sectionId: string) {
  return checkboxData.value[store.currentModule]?.[sectionId] || {}
}
</script>

<template>
  <div class="flex h-screen">
    <!-- 左侧导航 -->
    <ModuleNav :modules="modules" />

    <!-- 主内容 -->
    <div class="flex-1 overflow-y-auto p-6">
      <div class="flex items-center justify-between mb-6">
        <button @click="router.back()" class="text-sm text-blue-600 hover:underline">&larr; 返回</button>
        <div class="flex gap-2">
          <button class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm">提交修改</button>
          <button class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm">重新生成</button>
        </div>
      </div>

      <div v-if="store.loading" class="text-center text-gray-400 py-20">加载中...</div>

      <div v-else-if="currentModuleData">
        <h2 class="text-lg font-bold mb-4">{{ currentModuleData.title }}</h2>
        <SectionTable
          v-for="sec in currentModuleData.sections"
          :key="sec.id"
          :section="sec"
          :module-key="store.currentModule"
          :task-id="taskId"
          :checkbox-data="getCheckboxForSection(sec.id)"
          @select-row="() => {/* Phase 5 标注 */}"
        />
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/
git commit -m "feat(web): add interactive preview page with module nav, section tables, and checkboxes"
```

---

## Phase 5: 标注系统 + LLM 重提取

> 目标: 用户可对表格行添加标注，提交后 LLM 对照原文重新提取，结果自动更新。

### Task 5.1: 标注 CRUD API

**Files:**
- Create: `server/app/schemas/annotation.py`
- Create: `server/app/routers/annotations.py`
- Create: `server/tests/test_annotations.py`

- [ ] **Step 1: 创建 annotation schemas**

```python
# server/app/schemas/annotation.py
import datetime
from pydantic import BaseModel

class AnnotationCreate(BaseModel):
    module_key: str
    section_id: str
    row_index: int | None = None
    annotation_type: str = "correction"  # comment | correction | flag
    content: str

class AnnotationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    task_id: str
    user_id: int
    module_key: str
    section_id: str
    row_index: int | None
    annotation_type: str
    content: str
    status: str
    llm_response: str | None
    created_at: datetime.datetime

class AnnotationUpdate(BaseModel):
    content: str
```

- [ ] **Step 2: 实现 annotations 路由**

```python
# server/app/routers/annotations.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.annotation import Annotation
from server.app.schemas.annotation import AnnotationCreate, AnnotationResponse, AnnotationUpdate

router = APIRouter(prefix="/api/tasks", tags=["annotations"])

@router.post("/{task_id}/annotations", response_model=AnnotationResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation(task_id: str, body: AnnotationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ann = Annotation(
        task_id=task_id, user_id=user.id,
        module_key=body.module_key, section_id=body.section_id,
        row_index=body.row_index, annotation_type=body.annotation_type,
        content=body.content,
    )
    db.add(ann)
    await db.commit()
    await db.refresh(ann)
    return ann

@router.get("/{task_id}/annotations", response_model=list[AnnotationResponse])
async def list_annotations(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Annotation).where(Annotation.task_id == task_id).order_by(Annotation.created_at.desc()))
    return result.scalars().all()

@router.put("/{task_id}/annotations/{ann_id}", response_model=AnnotationResponse)
async def update_annotation(task_id: str, ann_id: int, body: AnnotationUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Annotation).where(Annotation.id == ann_id, Annotation.task_id == task_id, Annotation.user_id == user.id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404)
    ann.content = body.content
    await db.commit()
    await db.refresh(ann)
    return ann

@router.delete("/{task_id}/annotations/{ann_id}", status_code=204)
async def delete_annotation(task_id: str, ann_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Annotation).where(Annotation.id == ann_id, Annotation.task_id == task_id, Annotation.user_id == user.id))
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404)
    await db.delete(ann)
    await db.commit()
```

在 `server/app/main.py` 注册: `from server.app.routers import annotations; app.include_router(annotations.router)`

- [ ] **Step 3: 编写测试并验证**

```python
# server/tests/test_annotations.py
import pytest
import uuid
from server.app.models.task import Task

@pytest.fixture
async def completed_task(db_session, test_user):
    task = Task(id=uuid.uuid4(), user_id=test_user.id, filename="t.docx", file_path="/tmp/t.docx",
                status="completed", extracted_data={"modules": {}})
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task

@pytest.mark.asyncio
async def test_annotation_crud(client, test_user, completed_task):
    login = await client.post("/api/auth/login", json={"username": "testuser", "password": "testpass"})
    token = login.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # Create
    resp = await client.post(f"/api/tasks/{completed_task.id}/annotations", json={
        "module_key": "module_d", "section_id": "D3", "row_index": 1,
        "annotation_type": "correction", "content": "原文写的是5万不是1万"
    }, headers=h)
    assert resp.status_code == 201
    ann_id = resp.json()["id"]

    # List
    resp = await client.get(f"/api/tasks/{completed_task.id}/annotations", headers=h)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Update
    resp = await client.put(f"/api/tasks/{completed_task.id}/annotations/{ann_id}", json={"content": "修改后的内容"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["content"] == "修改后的内容"

    # Delete
    resp = await client.delete(f"/api/tasks/{completed_task.id}/annotations/{ann_id}", headers=h)
    assert resp.status_code == 204
```

Run: `cd server && python -m pytest tests/test_annotations.py -v`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add server/app/schemas/annotation.py server/app/routers/annotations.py server/tests/test_annotations.py server/app/main.py
git commit -m "feat(web): add annotation CRUD API with tests"
```

---

### Task 5.2: LLM 重提取任务

**Files:**
- Modify: `src/extractor/base.py` (添加 `reextract_with_annotations`)
- Create: `server/app/tasks/reextract_task.py`
- Create: `server/app/services/reextract_service.py`
- Modify: `server/app/routers/annotations.py` (添加 reextract endpoint)

- [ ] **Step 1: 在 src/extractor/base.py 中添加重提取函数**

```python
# 追加到 src/extractor/base.py 末尾

class ExtractError(Exception):
    """LLM 提取失败异常"""
    pass

def reextract_with_annotations(
    module_key: str,
    section_id: str,
    original_section: dict,
    relevant_paragraphs: list,
    annotations: list[dict],
    settings: dict | None = None,
) -> dict:
    """带用户标注的 LLM 重提取。"""
    import json as _json

    # 构建修改意见文本
    annotation_lines = []
    for ann in annotations:
        row_idx = ann.get("row_index", "")
        content = ann.get("content", "")
        cell = ""
        if row_idx is not None and original_section.get("rows"):
            row = original_section["rows"][row_idx] if row_idx < len(original_section["rows"]) else []
            cell = " | ".join(str(c) for c in row)
        annotation_lines.append(f"- 第{row_idx}行「{cell}」: {content}")

    para_text = "\n".join(
        p.get("text", p) if isinstance(p, dict) else str(p)
        for p in relevant_paragraphs
    )

    prompt = f"""你是招标文件分析专家。请根据用户的修改意见，对照原文重新提取以下内容。

## 原始提取结果
{_json.dumps(original_section, ensure_ascii=False, indent=2)}

## 用户修改意见
{chr(10).join(annotation_lines)}

## 对应原文段落
{para_text}

## 要求
1. 仔细对照原文，修正用户指出的问题
2. 保持与原始结果相同的 JSON 结构
3. 只修改用户指出的问题，其他内容保持不变"""

    messages = build_messages("你是招标文件分析专家。", prompt)
    result = call_qwen(messages, settings)
    if result is None:
        raise ExtractError(f"LLM 重提取失败: {module_key}/{section_id}")
    return result
```

- [ ] **Step 2: 实现 reextract Celery 任务**

```python
# server/app/tasks/reextract_task.py
import json
import os
import uuid as _uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.tasks.celery_app import celery_app
from server.app.config import settings
from server.app.models.task import Task
from server.app.models.annotation import Annotation

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)

@celery_app.task(bind=True, name="reextract_section")
def reextract_section(self, task_id: str, module_key: str, section_id: str, annotation_ids: list[int]):
    """根据用户标注重新提取指定 section。"""
    from src.extractor.base import reextract_with_annotations, ExtractError
    from src.config import load_settings
    from src.persistence import load_indexed

    self.update_state(state="PROGRESS", meta={"step": "reextracting", "detail": f"重提取 {section_id}...", "progress": 10})

    with Session(_sync_engine) as db:
        task = db.get(Task, _uuid.UUID(task_id))
        if not task or not task.extracted_data:
            return {"error": "Task or data not found"}

        # 获取原始 section
        modules = task.extracted_data.get("modules", {})
        module_data = modules.get(module_key, {})
        original_section = None
        for sec in module_data.get("sections", []):
            if sec.get("id") == section_id:
                original_section = sec
                break
        if not original_section:
            return {"error": f"Section {section_id} not found"}

        # 获取标注
        annotations = []
        for ann_id in annotation_ids:
            ann = db.get(Annotation, ann_id)
            if ann:
                annotations.append({
                    "row_index": ann.row_index,
                    "content": ann.content,
                    "annotation_type": ann.annotation_type,
                })
                ann.status = "submitted"
        db.commit()

    # 加载原文段落
    relevant_paragraphs = []
    if task.indexed_path and os.path.exists(task.indexed_path):
        indexed = load_indexed(task.indexed_path)
        relevant_paragraphs = indexed.get("tagged_paragraphs", [])

    try:
        api_settings = load_settings()
        new_section = reextract_with_annotations(
            module_key, section_id, original_section, relevant_paragraphs, annotations, api_settings
        )

        self.update_state(state="PROGRESS", meta={"step": "reextracting", "detail": f"合并 {section_id}...", "progress": 80})

        # 合并回 extracted_data
        with Session(_sync_engine) as db:
            task = db.get(Task, _uuid.UUID(task_id))
            extracted = dict(task.extracted_data)
            mod = extracted["modules"][module_key]
            for i, sec in enumerate(mod["sections"]):
                if sec.get("id") == section_id:
                    mod["sections"][i] = new_section
                    break
            task.extracted_data = extracted

            # 标注标记为 resolved
            for ann_id in annotation_ids:
                ann = db.get(Annotation, ann_id)
                if ann:
                    ann.status = "resolved"
                    ann.llm_response = json.dumps(new_section, ensure_ascii=False)
            db.commit()

        return {"status": "ok", "section_id": section_id}

    except ExtractError as e:
        with Session(_sync_engine) as db:
            for ann_id in annotation_ids:
                ann = db.get(Annotation, ann_id)
                if ann:
                    ann.status = "failed"
            db.commit()
        raise
```

- [ ] **Step 3: 添加 reextract API endpoint**

追加到 `server/app/routers/annotations.py`:

```python
from pydantic import BaseModel
from server.app.tasks.reextract_task import reextract_section

class ReextractRequest(BaseModel):
    module_key: str
    section_id: str
    annotation_ids: list[int]

@router.post("/{task_id}/reextract")
async def trigger_reextract(task_id: str, body: ReextractRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = reextract_section.delay(task_id, body.module_key, body.section_id, body.annotation_ids)
    # 记录 celery task id 到标注
    for ann_id in body.annotation_ids:
        r = await db.execute(select(Annotation).where(Annotation.id == ann_id))
        ann = r.scalar_one_or_none()
        if ann:
            ann.reextract_celery_id = result.id
    await db.commit()
    return {"celery_task_id": result.id}

@router.get("/{task_id}/reextract/{celery_task_id}/progress")
async def reextract_progress(task_id: str, celery_task_id: str, user: User = Depends(get_current_user)):
    """SSE 端点：重提取任务进度。"""
    import asyncio
    import json
    from fastapi.responses import StreamingResponse
    from celery.result import AsyncResult
    from server.app.tasks.celery_app import celery_app

    async def event_generator():
        while True:
            result = AsyncResult(celery_task_id, app=celery_app)
            if result.state == "PROGRESS":
                yield f"data: {json.dumps(result.info)}\n\n"
            elif result.state == "SUCCESS":
                yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                break
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': -1, 'step': 'failed', 'error': str(result.result)})}\n\n"
                break
            elif result.state == "PENDING":
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 4: Commit**

```bash
git add src/extractor/base.py server/app/tasks/reextract_task.py server/app/routers/annotations.py
git commit -m "feat(web): add LLM re-extraction with annotation context and SSE progress"
```

---

### Task 5.3: 前端标注组件

**Files:**
- Create: `web/src/types/annotation.ts`
- Create: `web/src/api/annotations.ts`
- Create: `web/src/composables/useAnnotation.ts`
- Create: `web/src/components/AnnotationPanel.vue`
- Create: `web/src/components/AnnotationBadge.vue`
- Modify: `web/src/views/PreviewView.vue`
- Modify: `web/src/components/SectionTable.vue`

- [ ] **Step 1: 创建类型和 API**

```typescript
// web/src/types/annotation.ts
export interface Annotation {
  id: number
  task_id: string
  user_id: number
  module_key: string
  section_id: string
  row_index: number | null
  annotation_type: string
  content: string
  status: string
  llm_response: string | null
  created_at: string
}
```

```typescript
// web/src/api/annotations.ts
import client from './client'
import type { Annotation } from '../types/annotation'

export const annotationsApi = {
  list: (taskId: string) => client.get<Annotation[]>(`/tasks/${taskId}/annotations`),
  create: (taskId: string, data: { module_key: string; section_id: string; row_index?: number; content: string; annotation_type?: string }) =>
    client.post<Annotation>(`/tasks/${taskId}/annotations`, data),
  update: (taskId: string, annId: number, content: string) =>
    client.put<Annotation>(`/tasks/${taskId}/annotations/${annId}`, { content }),
  delete: (taskId: string, annId: number) =>
    client.delete(`/tasks/${taskId}/annotations/${annId}`),
  reextract: (taskId: string, data: { module_key: string; section_id: string; annotation_ids: number[] }) =>
    client.post<{ celery_task_id: string }>(`/tasks/${taskId}/reextract`, data),
}
```

- [ ] **Step 2: 创建 useAnnotation composable**

```typescript
// web/src/composables/useAnnotation.ts
import { ref } from 'vue'
import { annotationsApi } from '../api/annotations'
import type { Annotation } from '../types/annotation'

export function useAnnotation(taskId: string) {
  const annotations = ref<Annotation[]>([])

  async function load() {
    const res = await annotationsApi.list(taskId)
    annotations.value = res.data
  }

  async function add(moduleKey: string, sectionId: string, rowIndex: number | null, content: string) {
    const res = await annotationsApi.create(taskId, {
      module_key: moduleKey, section_id: sectionId, row_index: rowIndex ?? undefined, content
    })
    annotations.value.unshift(res.data)
  }

  async function remove(annId: number) {
    await annotationsApi.delete(taskId, annId)
    annotations.value = annotations.value.filter(a => a.id !== annId)
  }

  function getForRow(moduleKey: string, sectionId: string, rowIndex: number) {
    return annotations.value.filter(a =>
      a.module_key === moduleKey && a.section_id === sectionId && a.row_index === rowIndex
    )
  }

  function getPendingBySection() {
    const grouped: Record<string, { module_key: string; section_id: string; ids: number[] }> = {}
    for (const ann of annotations.value) {
      if (ann.status !== 'pending') continue
      const key = `${ann.module_key}:${ann.section_id}`
      if (!grouped[key]) grouped[key] = { module_key: ann.module_key, section_id: ann.section_id, ids: [] }
      grouped[key].ids.push(ann.id)
    }
    return Object.values(grouped)
  }

  return { annotations, load, add, remove, getForRow, getPendingBySection }
}
```

- [ ] **Step 3: 创建 AnnotationPanel 组件**

```vue
<!-- web/src/components/AnnotationPanel.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { Annotation } from '../types/annotation'

const props = defineProps<{
  annotations: Annotation[]
  moduleKey: string
  sectionId: string
  rowIndex: number
  rowContent: string
}>()

const emit = defineEmits<{
  add: [content: string]
  remove: [annId: number]
}>()

const newContent = ref('')

function submit() {
  if (!newContent.value.trim()) return
  emit('add', newContent.value.trim())
  newContent.value = ''
}
</script>

<template>
  <div class="bg-gray-50 border rounded-lg p-4">
    <div class="text-sm font-medium text-gray-700 mb-2">
      第{{ rowIndex + 1 }}行「{{ rowContent }}」
    </div>
    <div class="space-y-2 mb-3">
      <div v-for="ann in annotations" :key="ann.id"
        class="flex items-start justify-between bg-white p-2 rounded border text-sm">
        <div>
          <span class="text-gray-500 text-xs">{{ ann.annotation_type }}</span>
          <p class="text-gray-700">{{ ann.content }}</p>
          <span v-if="ann.status === 'resolved'" class="text-green-500 text-xs">已处理</span>
          <span v-else-if="ann.status === 'failed'" class="text-red-500 text-xs">处理失败</span>
        </div>
        <button v-if="ann.status === 'pending'" @click="emit('remove', ann.id)" class="text-red-400 hover:text-red-600 text-xs">删除</button>
      </div>
    </div>
    <div class="flex gap-2">
      <input v-model="newContent" placeholder="添加标注..." @keyup.enter="submit"
        class="flex-1 px-3 py-1.5 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      <button @click="submit" class="px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">添加</button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: 创建 AnnotationBadge**

```vue
<!-- web/src/components/AnnotationBadge.vue -->
<script setup lang="ts">
defineProps<{ count: number }>()
</script>

<template>
  <span v-if="count > 0" class="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs bg-yellow-100 text-yellow-800">
    {{ count }}
  </span>
</template>
```

- [ ] **Step 5: 更新 SectionTable — 添加标注角标和行选择**

修改 `web/src/components/SectionTable.vue`，在 `<td>` 的勾选列中添加 `AnnotationBadge`：

```vue
<!-- 在 SectionTable.vue 的 <tr> 循环中，checkbox <td> 后追加标注角标 -->
<script setup lang="ts">
// 追加 prop:
// annotationCounts: Record<number, number>  — 每行的标注数

import AnnotationBadge from './AnnotationBadge.vue'
</script>

<!-- 在 <tbody> <tr> 中，checkbox <td> 旁追加: -->
<td class="border px-2 py-2 text-center">
  <AnnotationBadge :count="props.annotationCounts?.[rowIdx] || 0" />
</td>
```

同时为 `<tr>` 添加高亮选中态:
```vue
<tr v-for="(row, rowIdx) in section.rows" :key="rowIdx"
  :class="['hover:bg-blue-50 cursor-pointer', selectedRow === rowIdx ? 'bg-blue-100' : '']"
  @click="selectedRow = rowIdx; $emit('select-row', { moduleKey, sectionId: section.id, rowIndex: rowIdx, row })">
```

- [ ] **Step 6: 更新 PreviewView — 集成标注面板和提交/重新生成**

修改 `web/src/views/PreviewView.vue`：

```vue
<script setup lang="ts">
// 追加以下 imports 和逻辑:
import { ref } from 'vue'
import AnnotationPanel from '../components/AnnotationPanel.vue'
import { useAnnotation } from '../composables/useAnnotation'
import { annotationsApi } from '../api/annotations'
import client from '../api/client'

const taskId = route.params.id as string
const { annotations, load: loadAnnotations, add: addAnnotation, remove: removeAnnotation, getForRow, getPendingBySection } = useAnnotation(taskId)

const selectedRow = ref<{ moduleKey: string; sectionId: string; rowIndex: number; row: string[] } | null>(null)

onMounted(async () => {
  await store.loadPreview(taskId)
  await loadAnnotations()
})

function onSelectRow(data: { moduleKey: string; sectionId: string; rowIndex: number; row: string[] }) {
  selectedRow.value = data
}

function annotationCountsForSection(moduleKey: string, sectionId: string): Record<number, number> {
  const counts: Record<number, number> = {}
  for (const ann of annotations.value) {
    if (ann.module_key === moduleKey && ann.section_id === sectionId && ann.row_index != null) {
      counts[ann.row_index] = (counts[ann.row_index] || 0) + 1
    }
  }
  return counts
}

const submitting = ref(false)
async function submitAnnotations() {
  submitting.value = true
  try {
    const groups = getPendingBySection()
    for (const group of groups) {
      await annotationsApi.reextract(taskId, {
        module_key: group.module_key, section_id: group.section_id, annotation_ids: group.ids
      })
    }
    // 重新加载预览数据
    await store.loadPreview(taskId)
    await loadAnnotations()
  } finally {
    submitting.value = false
  }
}

const regenerating = ref(false)
async function regenerate() {
  regenerating.value = true
  try {
    await client.post(`/tasks/${taskId}/regenerate`)
    alert('文件已重新生成')
  } finally {
    regenerating.value = false
  }
}
</script>

<!-- template 中 "提交修改" 和 "重新生成" 按钮绑定: -->
<button @click="submitAnnotations" :disabled="submitting"
  class="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm disabled:opacity-50">
  {{ submitting ? '提交中...' : '提交修改' }}
</button>
<button @click="regenerate" :disabled="regenerating"
  class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm disabled:opacity-50">
  {{ regenerating ? '生成中...' : '重新生成' }}
</button>

<!-- SectionTable 添加 annotation-counts prop: -->
<SectionTable ... :annotation-counts="annotationCountsForSection(store.currentModule, sec.id)"
  @select-row="onSelectRow" />

<!-- 标注面板（在主内容区底部）: -->
<AnnotationPanel v-if="selectedRow"
  :annotations="getForRow(selectedRow.moduleKey, selectedRow.sectionId, selectedRow.rowIndex)"
  :module-key="selectedRow.moduleKey"
  :section-id="selectedRow.sectionId"
  :row-index="selectedRow.rowIndex"
  :row-content="selectedRow.row.join(' | ')"
  @add="(content) => addAnnotation(selectedRow!.moduleKey, selectedRow!.sectionId, selectedRow!.rowIndex, content)"
  @remove="removeAnnotation"
/>
```

- [ ] **Step 7: Commit**

```bash
git add web/src/ server/
git commit -m "feat(web): add annotation system with LLM re-extraction UI"
```

---

## Phase 6: 用户管理 + 安全加固 + 部署优化

> 目标: 管理员可管理用户，完善安全措施，生产级 Docker 配置。

### Task 6.1: Admin 用户管理 API

**Files:**
- Create: `server/app/routers/users.py`

- [ ] **Step 1: 实现用户管理路由**

```python
# server/app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import require_admin
from server.app.models.user import User
from server.app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    role: str = "user"

class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    password: str | None = None

@router.get("")
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role, "created_at": u.created_at} for u in users]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(username=body.username, password_hash=hash_password(body.password), display_name=body.display_name, role=body.role)
    db.add(user)
    await db.commit()
    return {"id": user.id, "username": user.username}

@router.put("/{user_id}")
async def update_user(user_id: int, body: UserUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)
    if body.display_name is not None: user.display_name = body.display_name
    if body.role is not None: user.role = body.role
    if body.password: user.password_hash = hash_password(body.password)
    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}

@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete admin")
    await db.delete(user)
    await db.commit()
```

在 `server/app/main.py` 注册: `from server.app.routers import users; app.include_router(users.router)`

- [ ] **Step 2: Commit**

```bash
git add server/app/routers/users.py server/app/main.py
git commit -m "feat(web): add admin user management API"
```

---

### Task 6.2: 前端用户管理页

**Files:**
- Modify: `web/src/views/AdminUsersView.vue`

- [ ] **Step 1: 实现 AdminUsersView**

```vue
<!-- web/src/views/AdminUsersView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import client from '../api/client'

const users = ref<any[]>([])
const showCreate = ref(false)
const form = ref({ username: '', password: '', display_name: '', role: 'user' })

async function loadUsers() {
  const res = await client.get('/users')
  users.value = res.data
}

async function createUser() {
  await client.post('/users', form.value)
  showCreate.value = false
  form.value = { username: '', password: '', display_name: '', role: 'user' }
  await loadUsers()
}

async function deleteUser(id: number) {
  if (!confirm('确认删除？')) return
  await client.delete(`/users/${id}`)
  await loadUsers()
}

onMounted(loadUsers)
</script>

<template>
  <DefaultLayout>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold">用户管理</h1>
      <button @click="showCreate = true" class="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700">创建用户</button>
    </div>

    <!-- 创建表单 -->
    <div v-if="showCreate" class="bg-white p-4 rounded-lg shadow mb-6 space-y-3">
      <input v-model="form.username" placeholder="用户名" class="w-full border rounded px-3 py-2 text-sm" />
      <input v-model="form.password" type="password" placeholder="密码" class="w-full border rounded px-3 py-2 text-sm" />
      <input v-model="form.display_name" placeholder="显示名称" class="w-full border rounded px-3 py-2 text-sm" />
      <select v-model="form.role" class="border rounded px-3 py-2 text-sm">
        <option value="user">普通用户</option>
        <option value="admin">管理员</option>
      </select>
      <div class="flex gap-2">
        <button @click="createUser" class="px-4 py-2 bg-green-600 text-white rounded text-sm">创建</button>
        <button @click="showCreate = false" class="px-4 py-2 border rounded text-sm">取消</button>
      </div>
    </div>

    <!-- 用户列表 -->
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50"><tr>
          <th class="px-4 py-3 text-left">用户名</th>
          <th class="px-4 py-3 text-left">显示名</th>
          <th class="px-4 py-3 text-left">角色</th>
          <th class="px-4 py-3 text-left">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" class="border-t">
            <td class="px-4 py-3">{{ u.username }}</td>
            <td class="px-4 py-3">{{ u.display_name }}</td>
            <td class="px-4 py-3">{{ u.role }}</td>
            <td class="px-4 py-3">
              <button v-if="u.role !== 'admin'" @click="deleteUser(u.id)" class="text-red-500 hover:underline text-sm">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </DefaultLayout>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add web/src/views/AdminUsersView.vue
git commit -m "feat(web): add admin user management UI"
```

---

### Task 6.3: 安全加固

**Files:**
- Modify: `server/app/main.py`

- [ ] **Step 1: 收紧 CORS + 添加限流中间件**

修改 `server/app/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict

# 简单内存限流
_rate_limits: dict[str, list[float]] = defaultdict(list)

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/api/tasks" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < 60]
            if len(_rate_limits[client_ip]) >= 10:
                from starlette.responses import JSONResponse
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            _rate_limits[client_ip].append(now)
        return await call_next(request)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:80"],  # 生产环境改为实际域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Commit**

```bash
git add server/app/main.py
git commit -m "feat(web): add rate limiting and tighten CORS"
```

---

### Task 6.4: 生产级 Docker 优化

**Files:**
- Modify: `server/Dockerfile` (multi-stage, non-root user)
- Modify: `docker-compose.yml` (添加 restart policy, resource limits)

- [ ] **Step 1: 优化后端 Dockerfile**

```dockerfile
# server/Dockerfile
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*
RUN useradd -m -r appuser

WORKDIR /app

COPY server/requirements.txt /app/server/requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r server/requirements.txt

COPY src/ /app/src/
COPY config/ /app/config/
COPY server/ /app/server/

USER appuser
ENV PYTHONPATH=/app
```

- [ ] **Step 2: 添加 restart policy 和 health check**

修改 `docker-compose.yml` 中所有服务添加:
```yaml
    restart: unless-stopped
```

为 api 添加 healthcheck:
```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      retries: 3
```

- [ ] **Step 3: Commit**

```bash
git add server/Dockerfile docker-compose.yml
git commit -m "feat(web): production Docker optimization with non-root user and health checks"
```

---

### Task 6.5: 最终集成测试 + 文档

**Files:**
- Create: `server/scripts/__init__.py`

- [ ] **Step 1: 运行全部后端测试**

```bash
cd server && python -m pytest tests/ -v
```
Expected: 所有测试通过

- [ ] **Step 2: 构建并启动完整 Docker 环境**

```bash
docker-compose build && docker-compose up -d
docker-compose exec api alembic -c server/alembic.ini upgrade head
docker-compose exec api python -m server.scripts.create_admin
```

- [ ] **Step 3: 手动验证完整流程**

1. 访问 `http://localhost` → 登录页
2. admin / admin123 登录 → 仪表板
3. 上传 .doc 文件 → 跳转任务详情 → 进度推送
4. 完成后 → 预览页面 → 浏览模块表格 → 勾选确认
5. 添加标注 → 提交修改 → LLM 重提取
6. 下载三份 .docx
7. 管理员页面 → 创建/删除用户

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(web): complete web platform - all 6 phases implemented"
git push origin master
```
