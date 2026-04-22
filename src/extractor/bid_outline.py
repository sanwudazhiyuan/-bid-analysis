"""bid_outline: 投标文件大纲生成模块（四层流水线）

Layer 1: 格式样例抽取（沿用 config/prompts/bid_format.txt，复用 bid_format._first_pass）
Layer 2: 骨架信号抽取（本模块新增）
Layer 3: 目录合成（单次 LLM 调用）
Layer 4: docx 渲染（纯代码，无 LLM）

对外入口：`extract_bid_outline(tagged_paragraphs, settings, embeddings_map,
module_embedding, modules_context=None) -> dict | None`。
"""
import json as _json
import logging
from pathlib import Path

from src.models import TaggedParagraph
from src.extractor.base import (
    load_prompt_template,
    build_messages,
    build_input_text,
    call_qwen,
    batch_by_count,
)
from src.extractor.scoring import filter_paragraphs_by_score

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
SKELETON_PROMPT_PATH = _CONFIG_DIR / "prompts" / "bid_format_skeleton.txt"
COMPOSE_PROMPT_PATH = _CONFIG_DIR / "prompts" / "bid_format_compose.txt"

BATCH_SIZE = 40
TOKEN_SAFETY_CAP = 100_000
MIN_FILTER_COUNT = 50


def _empty_skeleton() -> dict:
    """返回一份新的空骨架结构（每次返回独立 dict 避免共享）。"""
    return {
        "composition_clause": {"found": False, "items": []},
        "scoring_factors": [],
        "material_enumerations": [],
        "format_templates": [],
        "dynamic_nodes": [],
    }


def _merge_skeleton_batches(batch_results: list) -> dict:
    """合并多批 Layer 2 输出为单份 JSON。

    - composition_clause：首个 found=True 的批次获胜，保留其 items（通常招标方只写一处）
    - 其余 4 类：列表拼接，**不做去重**
    - 非 dict / None 的条目跳过
    """
    merged = _empty_skeleton()
    for b in batch_results:
        if not isinstance(b, dict):
            continue
        cc = b.get("composition_clause") or {}
        if cc.get("found") and not merged["composition_clause"]["found"]:
            merged["composition_clause"] = {
                "found": True,
                "items": list(cc.get("items") or []),
            }
        for k in ("scoring_factors", "material_enumerations",
                  "format_templates", "dynamic_nodes"):
            v = b.get(k)
            if isinstance(v, list):
                merged[k].extend(v)
    return merged


def _extract_skeleton_signals(
    tagged_paragraphs: list[TaggedParagraph],
    settings: dict | None = None,
    embeddings_map: dict[int, list[float]] | None = None,
    module_embedding: list[float] | None = None,
) -> dict | None:
    """Layer 2：关键词过滤 → 按段落数分批 → LLM 抽 5 类信号 → 合并。

    返回：
    - 正常：合并后的骨架 dict（5 个字段都存在）
    - 过滤后段落为空：返回空骨架（不视为失败，交主入口做三重空判定）
    - 全部批次 LLM 都失败：返回 None
    """
    filtered, score_map = filter_paragraphs_by_score(
        tagged_paragraphs, "bid_format_skeleton",
        embeddings_map=embeddings_map,
        module_embedding=module_embedding,
        min_count=MIN_FILTER_COUNT,
    )
    if not filtered:
        logger.warning("bid_outline.layer2: 未筛选到相关段落")
        return _empty_skeleton()

    logger.info("bid_outline.layer2: 筛选到 %d 个相关段落 (共 %d)",
                len(filtered), len(tagged_paragraphs))

    system_prompt = load_prompt_template(str(SKELETON_PROMPT_PATH))
    batches = batch_by_count(filtered, batch_size=BATCH_SIZE,
                             token_safety_cap=TOKEN_SAFETY_CAP)

    batch_results: list = []
    for i, batch in enumerate(batches):
        batch_text = build_input_text(batch, score_map)
        messages = build_messages(system=system_prompt, user=batch_text)
        logger.debug("bid_outline.layer2: 调用第 %d/%d 批 (段落数=%d)",
                     i + 1, len(batches), len(batch))
        result = call_qwen(messages, settings)
        batch_results.append(result if isinstance(result, dict) else None)

    if all(r is None for r in batch_results):
        logger.error("bid_outline.layer2: 所有批次 LLM 返回均失败")
        return None

    return _merge_skeleton_batches(batch_results)


# ========== Layer 3：目录合成 ==========

def _compose_outline_tree(
    layer1_result: dict | None,
    layer2_result: dict | None,
    settings: dict | None,
) -> dict | None:
    """Layer 3：输入 Layer 1 样例 title 列表 + Layer 2 结构信号，输出多级目录树。

    输出未编号、未绑定 sample_content。LLM 返回非 dict 或缺 `nodes` 返回 None。
    """
    template_titles: list[str] = []
    if isinstance(layer1_result, dict) and layer1_result.get("has_any_template"):
        for t in layer1_result.get("templates") or []:
            if isinstance(t, dict) and t.get("title"):
                template_titles.append(t["title"])

    safe_layer2 = layer2_result if isinstance(layer2_result, dict) else _empty_skeleton()

    payload = {
        "layer1_template_titles": template_titles,
        "layer2_skeleton": safe_layer2,
    }

    system_prompt = load_prompt_template(str(COMPOSE_PROMPT_PATH))
    user_text = _json.dumps(payload, ensure_ascii=False, indent=2)
    messages = build_messages(system=system_prompt, user=user_text)

    result = call_qwen(messages, settings)
    if not isinstance(result, dict) or "nodes" not in result:
        logger.error("bid_outline.layer3: LLM 返回非法结构: %s", type(result).__name__)
        return None
    if "title" not in result:
        result["title"] = "投标文件"
    return result
