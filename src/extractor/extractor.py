"""提取层统一入口：依次调用 9 个模块，汇总结果。"""
import importlib
import logging
from datetime import datetime

from src.models import TaggedParagraph

logger = logging.getLogger(__name__)

# 模块注册表：key -> (导入路径, 函数名)
_MODULE_REGISTRY = {
    "module_a": ("src.extractor.module_a", "extract_module_a"),
    "module_b": ("src.extractor.module_b", "extract_module_b"),
    "module_c": ("src.extractor.module_c", "extract_module_c"),
    "module_d": ("src.extractor.module_d", "extract_module_d"),
    "module_e": ("src.extractor.module_e", "extract_module_e"),
    "module_f": ("src.extractor.module_f", "extract_module_f"),
    "module_g": ("src.extractor.module_g", "extract_module_g"),
    "bid_format": ("src.extractor.bid_outline", "extract_bid_outline"),
    "checklist": ("src.extractor.checklist", "extract_checklist"),
}


def extract_all(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embeddings: dict[str, list[float]] | None = None,
) -> dict:
    """依次调用全部 9 个提取模块，汇总结果。

    失败的模块标记为 None 而非导致整体崩溃。

    Returns:
        {
            "schema_version": "1.0",
            "generated_at": "2026-03-20T10:30:00",
            "modules": {
                "module_a": {...} | None,
                "module_b": {...} | None,
                ...
            }
        }
    """
    modules = {}

    for key, (module_path, func_name) in _MODULE_REGISTRY.items():
        logger.info("提取模块: %s", key)
        try:
            mod = importlib.import_module(module_path)
            func = getattr(mod, func_name)
            module_emb = module_embeddings.get(key) if module_embeddings else None
            kwargs = dict(
                embeddings_map=embeddings_map,
                module_embedding=module_emb,
            )
            result = func(tagged_paragraphs, settings, **kwargs)
            modules[key] = result
            status = "成功" if result is not None else "返回 None"
            logger.info("模块 %s: %s", key, status)
        except Exception as e:
            logger.error("模块 %s 失败: %s", key, e)
            modules[key] = None

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "modules": modules,
    }


def extract_single_module(
    module_key: str,
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embeddings: dict[str, list[float]] | None = None,
    modules_context: dict | None = None,
) -> dict | None:
    """提取单个模块，供 Web Celery Worker 调用。"""
    if module_key not in _MODULE_REGISTRY:
        raise ValueError(f"Unknown module: {module_key}")
    mod_path, func_name = _MODULE_REGISTRY[module_key]
    mod = importlib.import_module(mod_path)
    func = getattr(mod, func_name)
    module_emb = module_embeddings.get(module_key) if module_embeddings else None
    kwargs = dict(
        embeddings_map=embeddings_map,
        module_embedding=module_emb,
    )
    return func(tagged_paragraphs, settings, **kwargs)
