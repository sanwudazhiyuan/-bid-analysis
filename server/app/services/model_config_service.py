"""ModelConfigService — DB-backed config management with Ollama discovery and yaml sync."""

import logging
import math
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

    # --- DB operations (async) --

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

    # --- DB operations (sync, for Celery) --

    @staticmethod
    def get_current_config_sync(db: Session) -> SystemConfig | None:
        return db.execute(select(SystemConfig).limit(1)).scalar_one_or_none()

    # --- Ollama queries --

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

    # --- Dynamic calculations --

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

    # --- Yaml sync --

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
        """Convert SystemConfig DB record to settings.yaml format.
        Cloud mode api_key is restored to ${DASHSCOPE_API_KEY} placeholder
        to prevent leaking the real key into the yaml file."""
        if config.mode == "cloud":
            cloud = config.cloud_config if config.cloud_config else {}
            # Replace resolved api_key with env var placeholder
            result = dict(cloud)
            if "api" in result:
                result["api"] = dict(result["api"])
                result["api"]["api_key"] = "${DASHSCOPE_API_KEY}"
            return result
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

    # --- haha-code hot update --

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

    # --- Startup initialization --

    @staticmethod
    async def initialize_on_startup(db: AsyncSession) -> None:
        """Ensure system_config has a record. If not, seed from current settings.yaml."""
        existing = await ModelConfigService.get_current_config_async(db)
        if existing:
            # Do NOT sync DB config back to yaml on startup — the yaml api_key
            # uses ${DASHSCOPE_API_KEY} placeholder while DB stores the resolved
            # value.  Writing it back would leak the real key into yaml.
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