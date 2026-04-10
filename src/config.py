import os
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


def load_synonyms() -> dict:
    return _load_yaml("synonyms.yaml")


def load_tag_rules() -> dict:
    return _load_yaml("tag_rules.yaml")


def load_styles() -> dict:
    return _load_yaml("styles.yaml")


def load_module_descriptions() -> dict:
    return _load_yaml("module_descriptions.yaml")
