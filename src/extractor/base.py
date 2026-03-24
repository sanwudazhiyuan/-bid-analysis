"""LLM 基础调用封装 — token 估算、JSON 解析、消息构建、API 调用、分批与合并"""
import json
import re
import time
import logging
from pathlib import Path
from openai import OpenAI

from src.config import load_settings
from src.models import TaggedParagraph

logger = logging.getLogger(__name__)


# ========== Token 估算 ==========

def estimate_tokens(text: str) -> int:
    """估算文本 token 数。中文按字符数 × 0.6，其他按字符数 / 4。"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    if chinese_chars > len(text) * 0.3:
        return int(len(text) * 0.6)
    else:
        return max(len(text) // 4, 1)


# ========== JSON 解析 ==========

def parse_llm_json(raw: str) -> dict | None:
    """从 LLM 输出中提取 JSON。处理 markdown 代码块包裹、尾部多余文本。"""
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 尝试提取 markdown 代码块中的 JSON
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()

    # 直接尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试找到第一个 { 到最后一个 } 的范围
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    return None


# ========== 消息构建 ==========

def build_messages(system: str, user: str) -> list[dict]:
    """构建 OpenAI 格式的消息列表。"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ========== Prompt 模板 ==========

def load_prompt_template(path: str) -> str:
    """加载 prompt 模板文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ========== API 调用 ==========

def _raw_api_call(messages: list[dict], settings: dict) -> str:
    """底层 API 调用，返回 LLM 原始文本响应。"""
    api_cfg = settings["api"]
    client = OpenAI(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
    )
    response = client.chat.completions.create(
        model=api_cfg["model"],
        messages=messages,
        temperature=api_cfg.get("temperature", 0.1),
        max_tokens=api_cfg.get("max_output_tokens", 65536),
    )
    return response.choices[0].message.content


def call_qwen(messages: list[dict], settings: dict | None = None) -> dict | None:
    """调用 DashScope API 并解析返回的 JSON。含重试和限流处理。"""
    if settings is None:
        settings = load_settings()

    max_retries = settings["api"].get("retry", 3)
    for attempt in range(max_retries):
        try:
            raw = _raw_api_call(messages, settings)
            logger.debug("LLM raw response (first 200 chars): %s", raw[:200] if raw else "")
            result = parse_llm_json(raw)
            if result is not None:
                return result
            logger.warning("Attempt %d: LLM returned non-JSON response", attempt + 1)
        except Exception as e:
            error_msg = str(e)
            logger.warning("Attempt %d failed: %s", attempt + 1, error_msg)
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.info("Retrying in %ds...", wait)
                time.sleep(wait)

    logger.error("All %d attempts failed", max_retries)
    return None


# ========== 分批处理 ==========

def batch_paragraphs(
    paragraphs: list[TaggedParagraph], max_tokens: int = 120000
) -> list[list[TaggedParagraph]]:
    """将段落按 token 上限分批，尽量在章节边界断开。"""
    if not paragraphs:
        return []

    batches = []
    current_batch = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para.text)

        if current_batch and current_tokens + para_tokens > max_tokens:
            # 超限，在章节边界断开
            batches.append(current_batch)
            current_batch = [para]
            current_tokens = para_tokens
        else:
            current_batch.append(para)
            current_tokens += para_tokens

    if current_batch:
        batches.append(current_batch)

    return batches


# ========== 结果合并 ==========

def merge_batch_results(results: list[dict]) -> dict:
    """合并多批提取结果。同 id 的 section 取最后一批的版本。"""
    if not results:
        return {"sections": []}

    seen = {}  # id -> section dict
    order = []  # 保持顺序

    for r in results:
        for section in r.get("sections", []):
            sid = section.get("id")
            if sid in seen:
                seen[sid] = section
            else:
                seen[sid] = section
                order.append(sid)

    merged_sections = [seen[sid] for sid in order]
    return {"sections": merged_sections}


# ========== 带标注的重提取 ==========

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

    annotation_lines = []
    for ann in annotations:
        row_idx = ann.get("row_index", "")
        content = ann.get("content", "")
        cell = ""
        if row_idx is not None and original_section.get("rows"):
            rows = original_section["rows"]
            row = rows[row_idx] if isinstance(row_idx, int) and row_idx < len(rows) else []
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
