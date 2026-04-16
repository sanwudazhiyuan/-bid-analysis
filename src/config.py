import os
import logging
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    with open(CONFIG_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict，override 中的值覆盖 base。"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_settings() -> dict:
    settings = _load_yaml("settings.yaml")
    # 加载本地配置覆盖（不入 git）
    local_path = CONFIG_DIR / "settings.local.yaml"
    if local_path.exists():
        local = _load_yaml("settings.local.yaml")
        if local:
            settings = _deep_merge(settings, local)
    # 替换环境变量占位符
    api_key = settings["api"].get("api_key", "")
    if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        settings["api"]["api_key"] = os.environ.get(env_var, "")
    return settings


def load_settings_from_dict(config_dict: dict) -> dict:
    """Load settings from a pre-built dict (e.g., from DB), skipping yaml file read.
    Used by Celery worker which reads config from DB, not yaml."""
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


def load_synonyms() -> dict:
    return _load_yaml("synonyms.yaml")


def load_tag_rules() -> dict:
    return _load_yaml("tag_rules.yaml")


def load_styles() -> dict:
    return _load_yaml("styles.yaml")


def load_module_descriptions() -> dict:
    return _load_yaml("module_descriptions.yaml")


def load_keyword_scores() -> dict:
    """加载关键词得分制配置。"""
    return _load_yaml("keyword_scores.yaml")
