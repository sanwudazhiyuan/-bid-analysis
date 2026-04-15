# Ollama Local Model Switching Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin config UI and backend infrastructure to switch between cloud (DashScope) and local (Ollama) models, with context-length-aware batching for local mode.

**Architecture:** Database-backed `ModelConfigService` as single source of truth, syncing to `settings.yaml` for backward compatibility. Frontend admin page at `/admin/config` with Ollama model auto-discovery. haha-code receives hot config updates via `/config` POST endpoint writing to `.env`. All batching parameters (max_tokens, batch_size) dynamically computed from model context_length.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Vue 3 + Tailwind v4 (frontend), Celery (async tasks), Ollama REST API (model discovery), Bun (haha-code server)

---

## File Structure

### New Files
- `server/app/models/system_config.py` — SystemConfig ORM model
- `server/app/schemas/config.py` — Pydantic schemas for config API
- `server/app/services/model_config_service.py` — Config CRUD + Ollama queries + sync
- `server/app/routers/config.py` — Admin config REST endpoints
- `web/src/views/AdminConfigView.vue` — Admin config page
- `web/src/api/config.ts` — Config API client module

### Modified Files
- `server/app/models/__init__.py` — Register SystemConfig model
- `server/app/models/task.py` — Add `needs_reindex` boolean field
- `server/app/main.py` — Startup: init config from DB, mount config router
- `src/config.py` — Add `load_settings_from_dict()` function for DB→yaml sync
- `src/extractor/base.py` — `batch_paragraphs()` max_tokens from dynamic config
- `src/extractor/embedding.py` — `_call_embedding_api()` base_url fallback, dynamic batch_size
- `src/reviewer/tender_indexer.py` — Dynamic `MAX_CHARS_PER_BATCH` from context_length
- `haha-code/server.ts` — Add `/config` POST endpoint, write `.env` on update
- `web/src/router/index.ts` — Add `/admin/config` route
- `web/src/components/AppSidebar.vue` — Add admin nav section for admin users

---

## Chunk 1: Database Model & Service Layer

### Task 1: SystemConfig ORM Model

**Files:**
- Create: `server/app/models/system_config.py`
- Modify: `server/app/models/__init__.py`

- [ ] **Step 1: Create SystemConfig model**

```python
# server/app/models/system_config.py
"""SystemConfig ORM model — single-row table storing global model configuration."""

import datetime
from sqlalchemy import Integer, String, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from server.app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="cloud")  # "cloud" | "local"
    cloud_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    local_llm_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    local_embedding_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    local_haha_code_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
```

- [ ] **Step 2: Register model in `__init__.py`**

Add `from server.app.models.system_config import SystemConfig` to `server/app/models/__init__.py` (after existing imports around line 7).

- [ ] **Step 3: Verify table creation on startup**

Run: `docker-compose up -d server` and check logs for `system_config` table creation (lifespan creates all tables via `Base.metadata.create_all`).

- [ ] **Step 4: Commit**

```bash
git add server/app/models/system_config.py server/app/models/__init__.py
git commit -m "feat: add SystemConfig ORM model for model configuration storage"
```

---

### Task 1b: Add `needs_reindex` field to Task model

**Files:**
- Modify: `server/app/models/task.py`

- [ ] **Step 1: Add `needs_reindex` boolean column**

Add after line 33 (`completed_at`) in `server/app/models/task.py`:

```python
    needs_reindex: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
```

Also add the `Boolean` import to the SQLAlchemy import line (line 6):
```python
from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey, Boolean, func
```

- [ ] **Step 2: Verify table gets new column on startup**

Run: `docker-compose up -d server` and check that `needs_reindex` column is created (via `Base.metadata.create_all` which adds missing columns for new deployments; for existing databases, a manual `ALTER TABLE tasks ADD COLUMN needs_reindex BOOLEAN DEFAULT false;` may be needed).

- [ ] **Step 3: Commit**

```bash
git add server/app/models/task.py
git commit -m "feat: add needs_reindex boolean field to Task model for embedding dimension change detection"
```

---

### Task 2: Pydantic Schemas for Config API

**Files:**
- Create: `server/app/schemas/config.py`

- [ ] **Step 1: Create config schemas**

```python
# server/app/schemas/config.py
"""Pydantic schemas for system config API."""

from pydantic import BaseModel


class OllamaLlmConfig(BaseModel):
    server_url: str = "http://10.165.25.39:11434"
    model_name: str = ""
    context_length: int | None = None
    context_length_manual: bool = False
    temperature: float = 0.1
    max_output_tokens: int = 8192
    retry: int = 3
    timeout: int = 600


class OllamaEmbeddingConfig(BaseModel):
    server_url: str = "http://10.165.44.28:11434"
    model_name: str = ""
    context_length: int | None = None
    context_length_manual: bool = False
    dimensions: int | None = None
    dimensions_manual: bool = False
    batch_size: int | None = None


class OllamaHahaCodeConfig(BaseModel):
    anthropic_base_url: str = ""
    anthropic_model: str = ""
    anthropic_sonnet_model: str = ""
    anthropic_haiku_model: str = ""
    anthropic_auth_token: str = "ollama"


class CloudConfig(BaseModel):
    api: dict = {}
    embedding: dict = {}
    haha_code: dict = {}


class SystemConfigUpdate(BaseModel):
    mode: str  # "cloud" | "local"
    cloud_config: CloudConfig | None = None
    local_llm_config: OllamaLlmConfig | None = None
    local_embedding_config: OllamaEmbeddingConfig | None = None
    local_haha_code_config: OllamaHahaCodeConfig | None = None


class SystemConfigResponse(BaseModel):
    mode: str
    cloud_config: CloudConfig
    local_llm_config: OllamaLlmConfig | None
    local_embedding_config: OllamaEmbeddingConfig | None
    local_haha_code_config: OllamaHahaCodeConfig | None
    updated_at: str | None
    updated_by: int | None


class OllamaModelInfo(BaseModel):
    name: str
    context_length: int | None = None
    dimensions: int | None = None


class OllamaConnectionTest(BaseModel):
    server_url: str
    model_name: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add server/app/schemas/config.py
git commit -m "feat: add Pydantic schemas for system config API"
```

---

### Task 3: ModelConfigService — Core CRUD + Ollama Queries

**Files:**
- Create: `server/app/services/model_config_service.py`

- [ ] **Step 1: Create ModelConfigService**

```python
# server/app/services/model_config_service.py
"""ModelConfigService — DB-backed config management with Ollama discovery and yaml sync."""

import json
import logging
import math
import os
from pathlib import Path

import httpx
import yaml
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from server.app.models.system_config import SystemConfig
from server.app.config import settings

logger = logging.getLogger(__name__)

SAFETY_MARGIN_TOKENS = 1500
SAFETY_MARGIN_EMBEDDING = 200
AVG_TEXT_LENGTH = 500
MAX_EMBEDDING_BATCH = 50
CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


class ModelConfigService:
    """Service for managing model configuration. Works with both async (FastAPI) and sync (Celery) sessions."""

    # --- DB operations (async) ---

    @staticmethod
    async def get_current_config_async(db: AsyncSession) -> SystemConfig | None:
        result = await db.execute(select(SystemConfig).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    async def save_config_async(db: AsyncSession, config_data: dict, user_id: int) -> SystemConfig:
        existing = await ModelConfigService.get_current_config_async(db)
        # Check embedding dimension change — if changed, mark all tasks as needs_reindex
        old_dimensions = None
        new_dimensions = None
        if existing and existing.local_embedding_config:
            old_dimensions = existing.local_embedding_config.get("dimensions")
        if config_data.get("local_embedding_config"):
            new_dimensions = config_data["local_embedding_config"].get("dimensions")
        if old_dimensions and new_dimensions and old_dimensions != new_dimensions:
            from server.app.models.task import Task
            await db.execute(Task.__table__.update().values(needs_reindex=True))

        if existing:
            existing.mode = config_data["mode"]
            existing.cloud_config = config_data.get("cloud_config", existing.cloud_config)
            existing.local_llm_config = config_data.get("local_llm_config")
            existing.local_embedding_config = config_data.get("local_embedding_config")
            existing.local_haha_code_config = config_data.get("local_haha_code_config")
            existing.updated_by = user_id
            await db.flush()
            return existing
        else:
            new_config = SystemConfig(
                mode=config_data["mode"],
                cloud_config=config_data.get("cloud_config", {}),
                local_llm_config=config_data.get("local_llm_config"),
                local_embedding_config=config_data.get("local_embedding_config"),
                local_haha_code_config=config_data.get("local_haha_code_config"),
                updated_by=user_id,
            )
            db.add(new_config)
            await db.flush()
            return new_config

    # --- DB operations (sync, for Celery) ---

    @staticmethod
    def get_current_config_sync(db: Session) -> SystemConfig | None:
        return db.execute(select(SystemConfig).limit(1)).scalar_one_or_none()

    # --- Ollama queries ---

    @staticmethod
    async def query_ollama_models(server_url: str) -> list[str]:
        """Call Ollama /api/tags to get installed model names."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{server_url.rstrip('/')}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error("Failed to query Ollama models from %s: %s", server_url, e)
            return []

    @staticmethod
    async def query_ollama_model_info(server_url: str, model_name: str) -> dict | None:
        """Call Ollama /api/show to get model details (context_length, etc)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{server_url.rstrip('/')}/api/show", json={"name": model_name})
                resp.raise_for_status()
                data = resp.json()
                # Extract context_length from model_info
                model_info = data.get("model_info", {})
                context_length = None
                dimensions = None
                for key, value in model_info.items():
                    if "context_length" in key:
                        try:
                            context_length = int(value)
                        except (ValueError, TypeError):
                            pass
                    if "embedding_dim" in key or "dimensions" in key:
                        try:
                            dimensions = int(value)
                        except (ValueError, TypeError):
                            pass
                return {"context_length": context_length, "dimensions": dimensions}
        except Exception as e:
            logger.error("Failed to query Ollama model info for %s: %s", model_name, e)
            return None

    @staticmethod
    async def test_ollama_connection(server_url: str, model_name: str | None = None) -> dict:
        """Test Ollama server connectivity. Optionally test a specific model."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{server_url.rstrip('/')}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                if model_name and model_name not in models:
                    return {"connected": True, "model_available": False, "models": models}
                return {"connected": True, "model_available": True if model_name else None, "models": models}
        except Exception as e:
            return {"connected": False, "error": str(e), "models": []}

    # --- Dynamic calculations ---

    @staticmethod
    def calculate_max_input_tokens(context_length: int, max_output_tokens: int) -> int:
        """Calculate max input tokens available for context after subtracting output and safety margin."""
        return context_length - max_output_tokens - SAFETY_MARGIN_TOKENS

    @staticmethod
    def calculate_embedding_batch_size(context_length: int | None, avg_text_length: int = AVG_TEXT_LENGTH) -> int:
        """Dynamically compute embedding batch_size from context_length."""
        if context_length is None:
            return 10  # conservative default
        available = context_length - SAFETY_MARGIN_EMBEDDING
        batch_size = max(1, min(MAX_EMBEDDING_BATCH, math.floor(available / avg_text_length)))
        return batch_size

    # --- Yaml sync ---

    @staticmethod
    def sync_to_yaml(config: SystemConfig) -> None:
        """Write current config to settings.yaml and clear settings.local.yaml."""
        yaml_data = ModelConfigService.build_yaml_dict(config)
        settings_path = CONFIG_DIR / "settings.yaml"
        with open(settings_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True)

        # Clear settings.local.yaml to prevent override conflicts
        local_path = CONFIG_DIR / "settings.local.yaml"
        if local_path.exists():
            local_path.write_text("", encoding="utf-8")

    @staticmethod
    def build_yaml_dict(config: SystemConfig) -> dict:
        """Convert SystemConfig DB record to settings.yaml format."""
        if config.mode == "cloud":
            return config.cloud_config if config.cloud_config else {}
        # Local mode
        llm = config.local_llm_config or {}
        emb = config.local_embedding_config or {}
        return {
            "api": {
                "base_url": llm.get("server_url", "").rstrip("/") + "/v1",
                "api_key": "ollama",
                "model": llm.get("model_name", ""),
                "temperature": llm.get("temperature", 0.1),
                "max_output_tokens": llm.get("max_output_tokens", 8192),
                "context_length": llm.get("context_length"),
                "enable_thinking": False,
                "retry": llm.get("retry", 3),
                "timeout": llm.get("timeout", 600),
            },
            "embedding": {
                "base_url": emb.get("server_url", "").rstrip("/") + "/v1",
                "model": emb.get("model_name", ""),
                "dimensions": emb.get("dimensions", 1024),
                "batch_size": ModelConfigService.calculate_embedding_batch_size(emb.get("context_length")),
                "context_length": emb.get("context_length"),
                "max_workers": 4,
                "similarity_threshold": 0.5,
            },
        }

    # --- haha-code hot update ---

    @staticmethod
    async def notify_haha_code(config: SystemConfig) -> bool:
        """Send config update to haha-code /config endpoint."""
        haha_url = settings.HAHA_CODE_URL
        if config.mode == "cloud":
            payload = {
                "mode": "cloud",
                "anthropic_base_url": config.cloud_config.get("haha_code", {}).get("anthropic_base_url", ""),
                "anthropic_auth_token": config.cloud_config.get("haha_code", {}).get("anthropic_auth_token", ""),
                "anthropic_model": config.cloud_config.get("haha_code", {}).get("anthropic_model", ""),
                "anthropic_sonnet_model": config.cloud_config.get("haha_code", {}).get("anthropic_sonnet_model", ""),
                "anthropic_haiku_model": config.cloud_config.get("haha_code", {}).get("anthropic_haiku_model", ""),
            }
        else:
            haha = config.local_haha_code_config or {}
            payload = {
                "mode": "local",
                "anthropic_base_url": haha.get("anthropic_base_url", ""),
                "anthropic_auth_token": haha.get("anthropic_auth_token", "ollama"),
                "anthropic_model": haha.get("anthropic_model", ""),
                "anthropic_sonnet_model": haha.get("anthropic_sonnet_model", ""),
                "anthropic_haiku_model": haha.get("anthropic_haiku_model", ""),
            }
        try:
            # Retry up to 3 times with short delay
            for attempt in range(3):
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(f"{haha_url}/config", json=payload)
                        resp.raise_for_status()
                        logger.info("haha-code config update successful (attempt %d)", attempt + 1)
                        return True
                except httpx.ConnectError:
                    if attempt < 2:
                        await asyncio.sleep(2)
                        continue
                    raise
        except Exception as e:
            logger.error("Failed to notify haha-code after 3 retries: %s", e)
            # Do NOT rollback — DB is authoritative, haha-code will catch up on next task start
            return False

    # --- Startup initialization ---

    @staticmethod
    async def initialize_on_startup(db: AsyncSession) -> None:
        """Ensure system_config has a record. If not, seed from current settings.yaml."""
        existing = await ModelConfigService.get_current_config_async(db)
        if existing:
            # Sync DB config to yaml (ensure consistency)
            ModelConfigService.sync_to_yaml(existing)
            return

        # No record exists — seed from current settings.yaml + haha-code .env
        from src.config import load_settings
        current_settings = load_settings()
        haha_env_path = Path(__file__).parent.parent.parent.parent / "haha-code" / ".env"
        haha_code_config = {}
        if haha_env_path.exists():
            for line in haha_env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ANTHROPIC_") and "=" in line:
                    key, value = line.split("=", 1)
                    haha_key = key.lower().replace("anthropic_", "")
                    haha_code_config[haha_key] = value

        new_config = SystemConfig(
            mode="cloud",
            cloud_config={
                "api": current_settings.get("api", {}),
                "embedding": current_settings.get("embedding", {}),
                "haha_code": haha_code_config,
            },
        )
        db.add(new_config)
        await db.flush()
        logger.info("Initialized system_config from settings.yaml")
```

- [ ] **Step 2: Commit**

```bash
git add server/app/services/model_config_service.py
git commit -m "feat: add ModelConfigService with Ollama discovery, yaml sync, and haha-code notification"
```

---

### Task 4: Config REST Router

**Files:**
- Create: `server/app/routers/config.py`
- Modify: `server/app/main.py` — mount router + startup init

- [ ] **Step 1: Create config router**

```python
# server/app/routers/config.py
"""Admin config endpoints — CRUD, Ollama discovery, connection test."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import require_admin
from server.app.models.user import User
from server.app.models.system_config import SystemConfig
from server.app.schemas.config import (
    SystemConfigUpdate, SystemConfigResponse, OllamaConnectionTest,
)
from server.app.services.model_config_service import ModelConfigService

router = APIRouter(prefix="/api/admin/config", tags=["config"])


@router.get("", response_model=SystemConfigResponse)
async def get_config(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    config = await ModelConfigService.get_current_config_async(db)
    if not config:
        raise HTTPException(status_code=404, detail="No config found")
    return SystemConfigResponse(
        mode=config.mode,
        cloud_config=config.cloud_config,
        local_llm_config=config.local_llm_config,
        local_embedding_config=config.local_embedding_config,
        local_haha_code_config=config.local_haha_code_config,
        updated_at=str(config.updated_at) if config.updated_at else None,
        updated_by=config.updated_by,
    )


@router.put("", response_model=SystemConfigResponse)
async def update_config(
    body: SystemConfigUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    config_data = body.model_dump()
    config = await ModelConfigService.save_config_async(db, config_data, admin.id)
    await db.commit()

    # Side effects: sync yaml, notify haha-code (best-effort, no rollback)
    ModelConfigService.sync_to_yaml(config)
    haha_ok = await ModelConfigService.notify_haha_code(config)
    if not haha_ok:
        logger.warning("haha-code notification failed — config saved to DB but haha-code will use stale config until restart")

    # Refresh from DB for response
    await db.refresh(config)
    return SystemConfigResponse(
        mode=config.mode,
        cloud_config=config.cloud_config,
        local_llm_config=config.local_llm_config,
        local_embedding_config=config.local_embedding_config,
        local_haha_code_config=config.local_haha_code_config,
        updated_at=str(config.updated_at) if config.updated_at else None,
        updated_by=config.updated_by,
    )


@router.get("/ollama/models")
async def list_ollama_models(server_url: str, admin: User = Depends(require_admin)):
    models = await ModelConfigService.query_ollama_models(server_url)
    if not models:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama server at {server_url}")
    return {"models": models}


@router.get("/ollama/info")
async def get_ollama_model_info(server_url: str, model: str, admin: User = Depends(require_admin)):
    info = await ModelConfigService.query_ollama_model_info(server_url, model)
    if info is None:
        raise HTTPException(status_code=503, detail=f"Cannot get info for model {model} at {server_url}")
    return info


@router.get("/ollama/test")
async def test_ollama_connection(server_url: str, model: str | None = None, admin: User = Depends(require_admin)):
    return await ModelConfigService.test_ollama_connection(server_url, model)
```

- [ ] **Step 2: Mount router and add startup init in `server/app/main.py`**

In `server/app/main.py`, add the config router import and mount it (around line 43, before the existing router mounts):

```python
from server.app.routers import config as config_router
# ...
app.include_router(config_router.router)
```

In the `lifespan` function (around line 20), after `Base.metadata.create_all`, add config initialization:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize system_config from settings.yaml if not exists
    async with async_session_factory() as db:
        from server.app.services.model_config_service import ModelConfigService
        await ModelConfigService.initialize_on_startup(db)
        await db.commit()

    yield
```

- [ ] **Step 3: Test API endpoints manually**

Start server: `docker-compose up -d server`

Test: `curl -H "Authorization: Bearer <admin_token>" http://localhost:8000/api/admin/config`
Expected: 200 with current cloud config

- [ ] **Step 4: Commit**

```bash
git add server/app/routers/config.py server/app/main.py
git commit -m "feat: add admin config REST endpoints and startup initialization"
```

---

## Chunk 2: Backend Core Logic Updates

### Task 5: Update src/config.py — Add DB-aware settings loading

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Add `load_settings_from_dict()` function and DB-aware `load_settings()`**

```python
# src/config.py — add after existing load_settings() function (around line 37)

def load_settings_from_dict(config_dict: dict) -> dict:
    """Load settings from a pre-built dict (e.g., from DB), skipping yaml file read.
    Used by Celery worker which reads config from DB, not yaml."""
    # Still replace env var placeholders if any
    api_key = config_dict.get("api", {}).get("api_key", "")
    if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        config_dict["api"]["api_key"] = os.environ.get(env_var, "")
    return config_dict


def load_settings_from_db() -> dict | None:
    """Load current config from system_config DB table using sync SQLAlchemy.
    Returns None if no config record exists (fallback to yaml)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from server.app.models.system_config import SystemConfig
    from server.app.config import settings as server_settings

    try:
        sync_url = server_settings.DATABASE_URL.replace("+asyncpg", "")
        engine = create_engine(sync_url)
        with Session(engine) as db:
            config = db.execute(select(SystemConfig).limit(1)).scalar_one_or_none()
            if config:
                from server.app.services.model_config_service import ModelConfigService
                return load_settings_from_dict(ModelConfigService.build_yaml_dict(config))
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to load config from DB: %s, falling back to yaml", e)
    return None
```

- [ ] **Step 2: Update review_task.py to use DB-first config loading**

In `server/app/tasks/review_task.py`, change line 39 from:
```python
api_settings = load_settings()
```
to:
```python
from src.config import load_settings, load_settings_from_db
api_settings = load_settings_from_db() or load_settings()
```

- [ ] **Step 3: Commit**

```bash
git add src/config.py server/app/tasks/review_task.py
git commit -m "feat: add DB-aware settings loading for Celery workers"
```

---

### Task 6: Update batch_paragraphs() with dynamic max_tokens

**Files:**
- Modify: `src/extractor/base.py:234-260`

- [ ] **Step 1: Modify `batch_paragraphs()` to accept settings dict for dynamic max_tokens**

Change function signature from:
```python
def batch_paragraphs(paragraphs: list[TaggedParagraph], max_tokens: int = 120000) -> list[list[TaggedParagraph]]:
```
to:
```python
def batch_paragraphs(paragraphs: list[TaggedParagraph], max_tokens: int | None = None, settings: dict | None = None) -> list[list[TaggedParagraph]]:
```

Add logic inside the function (before the main loop) to compute max_tokens from settings if not explicitly provided:
```python
if max_tokens is None:
    if settings and "api" in settings:
        context_length = settings["api"].get("context_length")
        max_output_tokens = settings["api"].get("max_output_tokens", 65536)
        if context_length:
            max_tokens = context_length - max_output_tokens - 1500  # safety_margin
        else:
            max_tokens = 120000  # cloud default
    else:
        max_tokens = 120000
```

- [ ] **Step 2: Verify existing callers still work**

The default `max_tokens=120000` is preserved when no settings passed, so all existing callers work unchanged. Search for all callers of `batch_paragraphs` to verify:

```bash
grep -rn "batch_paragraphs" src/
```

- [ ] **Step 3: Commit**

```bash
git add src/extractor/base.py
git commit -m "feat: batch_paragraphs() now computes max_tokens from settings context_length"
```

---

### Task 7: Update embedding.py — base_url fallback + dynamic batch_size

**Files:**
- Modify: `src/extractor/embedding.py:39-57, 60-68`

- [ ] **Step 1: Modify `_call_embedding_api()` to use embedding-specific base_url with fallback**

Change lines 46-48 from:
```python
client = OpenAI(
    base_url=api_cfg["base_url"],
    api_key=api_cfg["api_key"],
```
to:
```python
emb_base_url = emb_cfg.get("base_url") or api_cfg["base_url"]
emb_api_key = emb_cfg.get("api_key") or api_cfg["api_key"]
client = OpenAI(
    base_url=emb_base_url,
    api_key=emb_api_key,
```

- [ ] **Step 2: Modify `compute_paragraph_embeddings()` to compute batch_size dynamically**

Change line 68 from:
```python
batch_size = emb_cfg.get("batch_size", _DEFAULT_BATCH_SIZE)
```
to:
```python
emb_context_length = emb_cfg.get("context_length")
if emb_cfg.get("batch_size"):
    batch_size = emb_cfg["batch_size"]
elif emb_context_length:
    from server.app.services.model_config_service import ModelConfigService
    batch_size = ModelConfigService.calculate_embedding_batch_size(emb_context_length)
else:
    batch_size = _DEFAULT_BATCH_SIZE
```

- [ ] **Step 3: Commit**

```bash
git add src/extractor/embedding.py
git commit -m "feat: embedding base_url fallback and dynamic batch_size from context_length"
```

---

### Task 8: Update tender_indexer.py — dynamic MAX_CHARS_PER_BATCH

**Files:**
- Modify: `src/reviewer/tender_indexer.py:89-90, 147-148`

- [ ] **Step 1: Change constants to functions that accept settings**

Replace line 89-90:
```python
LEAF_SPLIT_THRESHOLD = 1200
MAX_CHARS_PER_BATCH = 30000
```
with:
```python
LEAF_SPLIT_THRESHOLD = 1200

def get_max_chars_per_batch(settings: dict | None = None) -> int:
    """Calculate max chars per batch from context_length in settings.
    Approximate conversion: 1 token ≈ 1.5 chars for Chinese text."""
    if settings and settings.get("api", {}).get("context_length"):
        max_input_tokens = settings["api"]["context_length"] - settings["api"].get("max_output_tokens", 8192) - 1500
        return max(2000, int(max_input_tokens * 1.5))  # token→char conversion
    return 30000  # cloud default
```

- [ ] **Step 2: Update caller at line 148**

Change:
```python
sub_batches = _split_by_char_count(node_paras, MAX_CHARS_PER_BATCH)
```
to:
```python
sub_batches = _split_by_char_count(node_paras, get_max_chars_per_batch(mapping_settings))
```

Note: `mapping_settings` is already available in the scope where this is called (inside `get_text_for_clause()` which receives `settings`).

- [ ] **Step 3: Commit**

```bash
git add src/reviewer/tender_indexer.py
git commit -m "feat: dynamic MAX_CHARS_PER_BATCH from context_length in tender_indexer"
```

---

## Chunk 3: haha-code Hot Config Update

### Task 9: Add /config endpoint to haha-code

**Files:**
- Modify: `haha-code/server.ts`

- [ ] **Step 1: Add config endpoint and .env writer**

Add near the top of `haha-code/server.ts` (after line 8, before `interface ReviewRequest`):

```typescript
// Dynamic config — can be updated via /config endpoint
const dynamicConfig = {
  ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL || "",
  ANTHROPIC_AUTH_TOKEN: process.env.ANTHROPIC_AUTH_TOKEN || "",
  ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL || "",
  ANTHROPIC_DEFAULT_SONNET_MODEL: process.env.ANTHROPIC_DEFAULT_SONNET_MODEL || "",
  ANTHROPIC_DEFAULT_HAIKU_MODEL: process.env.ANTHROPIC_DEFAULT_HAIKU_MODEL || "",
};

interface ConfigUpdate {
  mode: string;
  anthropic_base_url?: string;
  anthropic_auth_token?: string;
  anthropic_model?: string;
  anthropic_sonnet_model?: string;
  anthropic_haiku_model?: string;
}

function writeConfigToEnv(config: ConfigUpdate): void {
  // Update memory mapping
  if (config.anthropic_base_url) dynamicConfig.ANTHROPIC_BASE_URL = config.anthropic_base_url;
  if (config.anthropic_auth_token) dynamicConfig.ANTHROPIC_AUTH_TOKEN = config.anthropic_auth_token;
  if (config.anthropic_model) dynamicConfig.ANTHROPIC_MODEL = config.anthropic_model;
  if (config.anthropic_sonnet_model) dynamicConfig.ANTHROPIC_DEFAULT_SONNET_MODEL = config.anthropic_sonnet_model;
  if (config.anthropic_haiku_model) dynamicConfig.ANTHROPIC_DEFAULT_HAIKU_MODEL = config.anthropic_haiku_model;

  // Write to .env file for Bun.spawn subprocesses (they read via --env-file=.env)
  const envPath = join(ROOT_DIR, ".env");
  const envLines: string[] = [];
  for (const [key, value] of Object.entries(dynamicConfig)) {
    envLines.push(`${key}=${value}`);
  }
  // Preserve non-ANTHROPIC env vars
  try {
    const existingEnv = Bun.file(envPath).text();
    // We'll write synchronously since this is infrequent
  } catch {}
  // Write all env vars (ANTHROPIC ones updated, others preserved)
  const fullEnv: Record<string, string> = { ...process.env };
  for (const [key, value] of Object.entries(dynamicConfig)) {
    fullEnv[key] = value;
  }
  const envContent = Object.entries(fullEnv)
    .filter(([k]) => k.startsWith("ANTHROPIC_") || k === "API_TIMEOUT_MS" || k === "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" || k === "DISABLE_TELEMETRY" || k === "HAHA_CODE_PORT" || k === "REVIEW_TIMEOUT_MS")
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");
  Bun.write(envPath, envContent + "\n");

  // Update process.env so current server process also uses new config
  for (const [key, value] of Object.entries(dynamicConfig)) {
    process.env[key] = value;
  }

  console.log("[haha-code] Config updated:", JSON.stringify(config));
}
```

- [ ] **Step 2: Add /config route handler**

In the `fetch()` handler (around line 238, after the `/health` handler), add:

```typescript
    // Config update endpoint
    if (url.pathname === "/config" && req.method === "POST") {
      try {
        const config = await req.json() as ConfigUpdate;
        writeConfigToEnv(config);
        return Response.json({ status: "ok", config: dynamicConfig });
      } catch (e: any) {
        return Response.json({ error: `Config update failed: ${e.message}` }, { status: 500 });
      }
    }

    // Config query endpoint
    if (url.pathname === "/config" && req.method === "GET") {
      return Response.json(dynamicConfig);
    }
```

- [ ] **Step 3: Update Bun.spawn calls to use dynamicConfig + process.env**

In the `Bun.spawn()` call (line 292), the `env` parameter already uses `{ ...process.env }`. Since we update `process.env` in `writeConfigToEnv`, this is already correct — no change needed.

- [ ] **Step 4: Test /config endpoint**

```bash
curl -X POST http://localhost:3000/config -H "Content-Type: application/json" -d '{"mode":"local","anthropic_base_url":"http://10.165.25.39:11434/v1","anthropic_auth_token":"ollama","anthropic_model":"qwen2.5:14b","anthropic_sonnet_model":"qwen2.5:14b","anthropic_haiku_model":"qwen2.5:7b"}'
```

Expected: `{ "status": "ok", "config": { ... } }`

- [ ] **Step 5: Commit**

```bash
git add haha-code/server.ts
git commit -m "feat: haha-code /config endpoint for hot model config updates"
```

---

## Chunk 4: Frontend — Admin Config Page

### Task 10: Config API client module

**Files:**
- Create: `web/src/api/config.ts`

- [ ] **Step 1: Create config API module**

```typescript
// web/src/api/config.ts
import client from './client'

export interface OllamaLlmConfig {
  server_url: string
  model_name: string
  context_length: number | null
  context_length_manual: boolean
  temperature: number
  max_output_tokens: number
  retry: number
  timeout: number
}

export interface OllamaEmbeddingConfig {
  server_url: string
  model_name: string
  context_length: number | null
  context_length_manual: boolean
  dimensions: number | null
  dimensions_manual: boolean
  batch_size: number | null
}

export interface OllamaHahaCodeConfig {
  anthropic_base_url: string
  anthropic_model: string
  anthropic_sonnet_model: string
  anthropic_haiku_model: string
  anthropic_auth_token: string
}

export interface CloudConfig {
  api: Record<string, any>
  embedding: Record<string, any>
  haha_code: Record<string, any>
}

export interface SystemConfig {
  mode: string
  cloud_config: CloudConfig
  local_llm_config: OllamaLlmConfig | null
  local_embedding_config: OllamaEmbeddingConfig | null
  local_haha_code_config: OllamaHahaCodeConfig | null
  updated_at: string | null
  updated_by: number | null
}

export const configApi = {
  getConfig: () => client.get<SystemConfig>('/admin/config'),

  updateConfig: (data: Partial<SystemConfig>) => client.put<SystemConfig>('/admin/config', data),

  listOllamaModels: (serverUrl: string) =>
    client.get<{ models: string[] }>('/admin/config/ollama/models', { params: { server_url: serverUrl } }),

  getOllamaModelInfo: (serverUrl: string, model: string) =>
    client.get<{ context_length: number | null; dimensions: number | null }>('/admin/config/ollama/info', {
      params: { server_url: serverUrl, model },
    }),

  testOllamaConnection: (serverUrl: string, model?: string) =>
    client.get<{ connected: boolean; models: string[]; error?: string }>('/admin/config/ollama/test', {
      params: { server_url: serverUrl, model },
    }),
}
```

- [ ] **Step 2: Commit**

```bash
git add web/src/api/config.ts
git commit -m "feat: add frontend config API client module"
```

---

### Task 11: Admin Config View Page

**Files:**
- Create: `web/src/views/AdminConfigView.vue`

- [ ] **Step 1: Create the admin config page**

This is a large component. Key sections:

```vue
<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { configApi, type SystemConfig, type OllamaLlmConfig, type OllamaEmbeddingConfig, type OllamaHahaCodeConfig } from '../api/config'
import { useAuthStore } from '../stores/authStore'

const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const config = reactive<SystemConfig>({
  mode: 'cloud',
  cloud_config: { api: {}, embedding: {}, haha_code: {} },
  local_llm_config: null,
  local_embedding_config: null,
  local_haha_code_config: null,
  updated_at: null,
  updated_by: null,
})

// LLM state
const llmServerUrl = ref('http://10.165.25.39:11434')
const llmModels = ref<string[]>([])
const llmConnected = ref<'unknown' | 'connected' | 'error'>('unknown')
const llmModelInfoLoading = ref(false)

// Embedding state
const embServerUrl = ref('http://10.165.44.28:11434')
const embModels = ref<string[]>([])
const embConnected = ref<'unknown' | 'connected' | 'error'>('unknown')

// Dimension change warning
const dimensionWarning = ref(false)

async function loadConfig() {
  loading.value = true
  try {
    const res = await configApi.getConfig()
    Object.assign(config, res.data)
    // Sync local refs from config
    if (config.local_llm_config) {
      llmServerUrl.value = config.local_llm_config.server_url
    }
    if (config.local_embedding_config) {
      embServerUrl.value = config.local_embedding_config.server_url
    }
  } finally {
    loading.value = false
  }
}

async function testLlmConnection() {
  llmConnected.value = 'unknown'
  try {
    const res = await configApi.testOllamaConnection(llmServerUrl.value)
    if (res.data.connected) {
      llmConnected.value = 'connected'
      llmModels.value = res.data.models
    } else {
      llmConnected.value = 'error'
    }
  } catch {
    llmConnected.value = 'error'
  }
}

async function testEmbConnection() {
  embConnected.value = 'unknown'
  try {
    const res = await configApi.testOllamaConnection(embServerUrl.value)
    if (res.data.connected) {
      embConnected.value = 'connected'
      embModels.value = res.data.models
    } else {
      embConnected.value = 'error'
    }
  } catch {
    embConnected.value = 'error'
  }
}

async function onLlmModelChange(modelName: string) {
  llmModelInfoLoading.value = true
  try {
    const res = await configApi.getOllamaModelInfo(llmServerUrl.value, modelName)
    if (config.local_llm_config) {
      if (res.data.context_length) {
        config.local_llm_config.context_length = res.data.context_length
        config.local_llm_config.context_length_manual = false
      }
    }
    // Also update haha-code config when LLM model changes
    if (config.local_haha_code_config) {
      const base = llmServerUrl.value.replace(/\/+$/, '') + '/v1'
      config.local_haha_code_config.anthropic_base_url = base
      config.local_haha_code_config.anthropic_model = modelName
      config.local_haha_code_config.anthropic_sonnet_model = modelName
    }
  } finally {
    llmModelInfoLoading.value = false
  }
}

async function onEmbModelChange(modelName: string) {
  try {
    const res = await configApi.getOllamaModelInfo(embServerUrl.value, modelName)
    if (config.local_embedding_config) {
      if (res.data.context_length) {
        config.local_embedding_config.context_length = res.data.context_length
        config.local_embedding_config.context_length_manual = false
      }
      if (res.data.dimensions) {
        // Check dimension change
        const oldDim = config.local_embedding_config.dimensions
        if (oldDim && oldDim !== res.data.dimensions) {
          dimensionWarning.value = true
        }
        config.local_embedding_config.dimensions = res.data.dimensions
        config.local_embedding_config.dimensions_manual = false
      }
      // Recalculate batch_size
      if (config.local_embedding_config.context_length) {
        const available = config.local_embedding_config.context_length - 200
        config.local_embedding_config.batch_size = Math.max(1, Math.min(50, Math.floor(available / 500)))
      }
    }
  } catch {}
}

async function saveConfig() {
  if (dimensionWarning.value) {
    if (!confirm('嵌入维度变更将导致所有已有索引失效，需要重新解析和索引所有招标文件。是否继续？')) {
      return
    }
  }
  saving.value = true
  try {
    await configApi.updateConfig(config)
    dimensionWarning.value = false
    alert('配置已生效')
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold">模型配置</h1>
    </div>

    <!-- Mode Switch -->
    <div class="bg-surface p-4 rounded-lg shadow mb-6">
      <div class="text-xs text-text-muted uppercase mb-3">运行模式</div>
      <div class="flex gap-4">
        <button
          @click="config.mode = 'cloud'"
          :class="config.mode === 'cloud' ? 'bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium' : 'border border-border px-4 py-2 rounded-md text-sm text-text-secondary'"
        >云端模式 (DashScope)</button>
        <button
          @click="config.mode = 'local'"
          :class="config.mode === 'local' ? 'bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium' : 'border border-border px-4 py-2 rounded-md text-sm text-text-secondary'"
        >本地模式 (Ollama)</button>
      </div>
    </div>

    <!-- Cloud mode summary (shown when cloud) -->
    <div v-if="config.mode === 'cloud'" class="bg-surface p-4 rounded-lg shadow mb-6">
      <div class="text-xs text-text-muted uppercase mb-3">当前云端配置</div>
      <div class="text-sm text-text-secondary space-y-1">
        <p>LLM 模型: {{ config.cloud_config?.api?.model || '-' }}</p>
        <p>Embedding 模型: {{ config.cloud_config?.embedding?.model || '-' }}</p>
        <p>API 地址: {{ config.cloud_config?.api?.base_url || '-' }}</p>
      </div>
    </div>

    <!-- Local mode config blocks (shown when local) -->
    <template v-if="config.mode === 'local'">
      <!-- LLM Config -->
      <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
        <div class="text-xs text-text-muted uppercase">LLM 大语言模型</div>
        <div class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">服务器地址</span>
          <input v-model="llmServerUrl" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="http://10.165.25.39:11434" />
          <button @click="testLlmConnection" class="px-3 py-2 bg-primary text-primary-foreground rounded text-sm">连接测试</button>
          <span v-if="llmConnected === 'connected'" class="text-sm text-success">✓ 已连接</span>
          <span v-if="llmConnected === 'error'" class="text-sm text-danger">✗ 连接失败</span>
        </div>
        <div v-if="llmModels.length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">模型选择</span>
          <select v-model="config.local_llm_config!.model_name" @change="onLlmModelChange(config.local_llm_config!.model_name)" class="flex-1 border rounded px-3 py-2 text-sm">
            <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div v-if="config.local_llm_config?.context_length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">上下文长度</span>
          <span class="text-sm text-success">{{ config.local_llm_config.context_length }} (自动获取)</span>
        </div>
        <div v-if="!config.local_llm_config?.context_length && config.mode === 'local'" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">上下文长度</span>
          <input type="number" v-model="config.local_llm_config!.context_length" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="手动填写" />
          <span class="text-xs text-warning">手动设定</span>
        </div>
        <div class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">最大输出 Tokens</span>
          <input type="number" v-model="config.local_llm_config!.max_output_tokens" class="flex-1 border rounded px-3 py-2 text-sm" />
        </div>
        <div class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">Temperature</span>
          <input type="number" v-model="config.local_llm_config!.temperature" step="0.1" class="flex-1 border rounded px-3 py-2 text-sm" />
        </div>
      </div>

      <!-- Embedding Config -->
      <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
        <div class="text-xs text-text-muted uppercase">Embedding 嵌入模型</div>
        <div class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">服务器地址</span>
          <input v-model="embServerUrl" class="flex-1 border rounded px-3 py-2 text-sm" placeholder="http://10.165.44.28:11434" />
          <button @click="testEmbConnection" class="px-3 py-2 bg-primary text-primary-foreground rounded text-sm">连接测试</button>
          <span v-if="embConnected === 'connected'" class="text-sm text-success">✓ 已连接</span>
          <span v-if="embConnected === 'error'" class="text-sm text-danger">✗ 连接失败</span>
        </div>
        <div v-if="embModels.length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">模型选择</span>
          <select v-model="config.local_embedding_config!.model_name" @change="onEmbModelChange(config.local_embedding_config!.model_name)" class="flex-1 border rounded px-3 py-2 text-sm">
            <option v-for="m in embModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div v-if="config.local_embedding_config?.context_length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">上下文长度</span>
          <span class="text-sm text-success">{{ config.local_embedding_config.context_length }} (自动获取)</span>
        </div>
        <div v-if="!config.local_embedding_config?.context_length && config.mode === 'local'" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">上下文长度</span>
          <input type="number" v-model="config.local_embedding_config!.context_length" class="flex-1 border rounded px-3 py-2 text-sm" />
          <span class="text-xs text-warning">手动设定</span>
        </div>
        <div v-if="config.local_embedding_config?.dimensions" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">嵌入维度</span>
          <span class="text-sm text-success">{{ config.local_embedding_config.dimensions }} (自动获取)</span>
        </div>
        <div v-if="!config.local_embedding_config?.dimensions && config.mode === 'local'" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">嵌入维度</span>
          <input type="number" v-model="config.local_embedding_config!.dimensions" class="flex-1 border rounded px-3 py-2 text-sm" />
          <span class="text-xs text-warning">手动设定</span>
        </div>
        <div v-if="config.local_embedding_config?.batch_size" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-24">Batch Size</span>
          <span class="text-sm text-success">{{ config.local_embedding_config.batch_size }} (动态计算)</span>
        </div>
      </div>

      <!-- Smart Review Config -->
      <div class="bg-surface p-4 rounded-lg shadow mb-6 space-y-3">
        <div class="text-xs text-text-muted uppercase">Smart Review (haha-code)</div>
        <div class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-28">Anthropic 端点</span>
          <span class="text-sm">{{ config.local_haha_code_config?.anthropic_base_url || '-' }}</span>
        </div>
        <div v-if="llmModels.length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-28">Sonnet 模型</span>
          <select v-model="config.local_haha_code_config!.anthropic_sonnet_model" class="flex-1 border rounded px-3 py-2 text-sm">
            <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
          </select>
          <span class="text-xs text-text-muted">主力审评模型</span>
        </div>
        <div v-if="llmModels.length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-28">Haiku 模型</span>
          <select v-model="config.local_haha_code_config!.anthropic_haiku_model" class="flex-1 border rounded px-3 py-2 text-sm">
            <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
          </select>
          <span class="text-xs text-text-muted">轻量快速模型</span>
        </div>
        <div v-if="llmModels.length" class="flex gap-3 items-center">
          <span class="text-sm text-text-secondary w-28">默认模型</span>
          <select v-model="config.local_haha_code_config!.anthropic_model" class="flex-1 border rounded px-3 py-2 text-sm">
            <option v-for="m in llmModels" :key="m" :value="m">{{ m }}</option>
          </select>
          <span class="text-xs text-text-muted">haha-code 主模型</span>
        </div>
      </div>

      <!-- Dimension change warning -->
      <div v-if="dimensionWarning" class="bg-warning-light border border-warning p-3 rounded-lg mb-6">
        <span class="text-sm text-warning-foreground">⚠ 嵌入维度变更将导致所有已有索引失效，需要重新解析和索引所有招标文件。</span>
      </div>
    </template>

    <!-- Save button -->
    <div class="text-center">
      <button @click="saveConfig" :disabled="saving" class="px-6 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium">
        {{ saving ? '保存中...' : '保存配置' }}
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add web/src/views/AdminConfigView.vue
git commit -m "feat: add admin model config page with Ollama discovery and dimension warnings"
```

---

### Task 12: Route & Sidebar Integration

**Files:**
- Modify: `web/src/router/index.ts`
- Modify: `web/src/components/AppSidebar.vue`

- [ ] **Step 1: Add /admin/config route**

In `web/src/router/index.ts`, add after the `admin-users` route (around line 52):

```typescript
{
  path: 'admin/config',
  name: 'admin-config',
  component: () => import('../views/AdminConfigView.vue'),
  meta: { requiresAdmin: true },
},
```

- [ ] **Step 2: Add admin section to sidebar (conditional for admin users)**

In `web/src/components/AppSidebar.vue`, add admin nav items and conditional rendering:

1. Add `Settings` icon import:
```typescript
import { PenLine, FolderOpen, BarChart3, Ruler, ClipboardList, ShieldCheck, FileCheck, Users, Settings } from 'lucide-vue-next'
```

2. Add `useAuthStore` import:
```typescript
import { useAuthStore } from '../stores/authStore'
```

3. Add admin nav items array:
```typescript
const authStore = useAuthStore()

const adminItems = [
  { path: '/admin/users', label: '用户管理', icon: Users },
  { path: '/admin/config', label: '模型配置', icon: Settings },
]
```

4. Add admin section in template (after the "文档管理" section, before the UserMenu):
```vue
<template v-if="authStore.isAdmin">
  <div class="h-px bg-border mx-4 my-3"></div>
  <div class="px-4 pb-1 text-xs text-text-muted">管理</div>

  <router-link
    v-for="item in adminItems"
    :key="item.path"
    :to="item.path"
    :class="[
      'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
      isActive(item.path)
        ? 'active bg-primary-light text-primary font-medium border-l-[3px] border-primary'
        : 'text-text-secondary hover:bg-background border-l-[3px] border-transparent'
    ]"
  >
    <component :is="item.icon" class="size-4" />
    <span>{{ item.label }}</span>
  </router-link>
</template>
```

- [ ] **Step 3: Verify page loads**

Open `/admin/config` in browser as admin user. Expect: config page with mode switch and cloud config summary.

- [ ] **Step 4: Commit**

```bash
git add web/src/router/index.ts web/src/components/AppSidebar.vue
git commit -m "feat: add admin/config route and sidebar admin section"
```

---

## Chunk 5: Integration Testing & Edge Cases

### Task 13: End-to-end flow verification

- [ ] **Step 1: Start all services**

```bash
docker-compose up -d
```

- [ ] **Step 2: Verify cloud mode works**

- Login as admin
- Navigate to /admin/config
- Verify cloud config is displayed correctly
- Create a review task → verify it uses cloud DashScope model

- [ ] **Step 3: Switch to local mode**

- On /admin/config, select "本地模式"
- Enter LLM server: http://10.165.25.39:11434 → click 连接测试
- Select a model → verify context_length auto-fills
- Enter Embedding server: http://10.165.44.28:11434 → click 连接测试
- Select a model → verify dimensions auto-fills
- Save → verify success message

- [ ] **Step 4: Verify haha-code received config update**

```bash
curl http://localhost:3000/config
```

Expected: JSON with local Ollama URLs

- [ ] **Step 5: Verify settings.yaml was updated**

```bash
cat config/settings.yaml
```

Expected: YAML with Ollama URLs and local model names

- [ ] **Step 6: Verify settings.local.yaml was cleared**

```bash
cat config/settings.local.yaml
```

Expected: empty file

- [ ] **Step 7: Create a review task in local mode**

- Create a new review task → verify it uses local Ollama model
- Monitor logs for API call destination

- [ ] **Step 8: Switch back to cloud mode**

- On /admin/config, select "云端模式"
- Save → verify cloud config restored
- Verify settings.yaml restored to DashScope config

- [ ] **Step 9: Commit any integration fixes**

```bash
git add -A
git commit -m "fix: integration test fixes for Ollama model switching"
```

---

### Task 14: Edge case — dimension change warning flow

- [ ] **Step 1: Test dimension change detection**

- Switch to local mode with embedding model A (dimensions 1024)
- Save → verify no warning
- Switch embedding model to model B (different dimensions)
- Verify warning appears in UI
- Confirm → verify config saves with reindex flag

- [ ] **Step 2: Test context_length manual fallback**

- Enter an Ollama server URL that is unreachable
- Click 连接测试 → verify error shown
- Select model manually → verify manual input fields appear for context_length and dimensions

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "fix: edge case handling for dimension warnings and manual config fallback"
```