import os
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_yaml(filename: str) -> dict:
    with open(CONFIG_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings() -> dict:
    settings = _load_yaml("settings.yaml")
    # 替换环境变量占位符
    api_key = settings["api"].get("api_key", "")
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        settings["api"]["api_key"] = os.environ.get(env_var, "")
    return settings


def load_synonyms() -> dict:
    return _load_yaml("synonyms.yaml")


def load_tag_rules() -> dict:
    return _load_yaml("tag_rules.yaml")


def load_styles() -> dict:
    return _load_yaml("styles.yaml")
