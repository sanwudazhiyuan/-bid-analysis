import os
from src.config import load_settings, load_synonyms, load_tag_rules, load_styles


def test_load_settings():
    settings = load_settings()
    assert settings["api"]["model"] == "qwen3.5-plus"
    assert settings["api"]["temperature"] == 0.1


def test_load_synonyms():
    synonyms = load_synonyms()
    assert "采购公告" in synonyms
    assert "招标公告" in synonyms["采购公告"]


def test_load_tag_rules():
    rules = load_tag_rules()
    assert "评分" in rules
    assert "得分" in rules["评分"]


def test_load_styles():
    styles = load_styles()
    assert styles["styles"]["heading1"]["font"] == "微软雅黑"


def test_api_key_loaded():
    """API key 应从配置文件或环境变量加载，不应为空"""
    settings = load_settings()
    api_key = settings["api"]["api_key"]
    assert api_key and len(api_key) > 0, "API key 不应为空"
