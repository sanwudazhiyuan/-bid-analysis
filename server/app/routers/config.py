"""Admin config endpoints — CRUD, Ollama discovery, connection test."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import require_admin
from server.app.models.user import User
from server.app.schemas.config import (
    SystemConfigUpdate, SystemConfigResponse,
)
from server.app.services.model_config_service import ModelConfigService

logger = logging.getLogger(__name__)

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