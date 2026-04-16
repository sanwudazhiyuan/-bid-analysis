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

def parse_llm_json(raw: str) -> dict | list | None:
    """从 LLM 输出中提取 JSON。处理 markdown 代码块包裹、尾部多余文本、常见格式错误。"""
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 去除 <think>...</think> 思考过程标签
    # Iteratively strip thinking/reasoning tags (Ollama qwen3/DeepSeek-R1 etc.)
    # May have multiple blocks; strip until no more remain
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = text.strip()

    # 尝试提取 markdown 代码块中的 JSON
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()

    # 直接尝试解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 修复常见 LLM JSON 错误后重试
    fixed = _fix_common_json_errors(text)
    if fixed != text:
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

    # 尝试找到第一个 { 到最后一个 } 的范围
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            candidate = _fix_common_json_errors(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # 尝试截断修复：LLM 输出可能因 max_tokens 限制被截断
    # 导致 JSON 缺少闭合的引号/括号
    truncated = _fix_truncated_json(text)
    if truncated:
        try:
            return json.loads(truncated)
        except json.JSONDecodeError:
            truncated_fixed = _fix_common_json_errors(truncated)
            if truncated_fixed != truncated:
                try:
                    return json.loads(truncated_fixed)
                except json.JSONDecodeError:
                    pass

    # 截断恢复策略：找到最后一个完整对象边界 },
    # 截取到该边界后尝试截断修复（丢弃后面不完整的内容）
    if first_brace != -1:
        # 找到所有 }, 的位置（完整对象的结束 + 后续逗号表示还有内容）
        complete_boundaries = [m.end() for m in re.finditer(r'\}\s*,', text)]
        # 也尝试最后一个 } 的位置（如果存在）
        if last_brace > first_brace:
            complete_boundaries.append(last_brace + 1)

        # 从最远的边界开始回退尝试
        for boundary in sorted(complete_boundaries, reverse=True):
            if boundary <= first_brace:
                continue
            candidate = text[first_brace : boundary]
            truncated_candidate = _fix_truncated_json(candidate)
            if truncated_candidate:
                try:
                    return json.loads(truncated_candidate)
                except json.JSONDecodeError:
                    truncated_fixed = _fix_common_json_errors(truncated_candidate)
                    if truncated_fixed != truncated_candidate:
                        try:
                            return json.loads(truncated_fixed)
                        except json.JSONDecodeError:
                            pass

    # 尝试找到第一个 [ 到最后一个 ] 的范围（支持 JSON 数组）
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        candidate = text[first_bracket : last_bracket + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            candidate = _fix_common_json_errors(candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    logger.warning("parse_llm_json: failed to extract JSON, raw output: %s", raw[:1000])
    return None


def _fix_common_json_errors(text: str) -> str:
    """修复 LLM 常见的 JSON 格式错误。"""
    # 去除尾部多余逗号 (trailing commas): }, ] 前面的逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 修复单引号为双引号（仅在键值对场景）
    # 注意：只处理明显的 JSON key 单引号，避免误改内容
    text = re.sub(r"(?<=[\[{,])\s*'([^']+?)'\s*:", r' "\1":', text)
    # 去除控制字符（LLM 偶尔输出 \x00-\x1f）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _fix_truncated_json(text: str) -> str | None:
    """尝试修复因 LLM 输出截断导致的不完整 JSON。

    当 LLM 输出被 max_tokens 截断时，JSON 可能缺少：
    - 关闭的字符串引号 (如 "reason": "// a a a a a...)
    - 关闭的括号 } ]

    策略：先丢弃末尾不完整的键值对，再关闭未闭合的括号，使 JSON 可解析。
    """
    # 检测是否为截断场景：最后一个非空白字符不是 } 或 ]
    stripped = text.rstrip()
    if stripped and stripped[-1] in ('}', ']'):
        return None  # JSON 末尾看起来完整，不是截断问题

    result = text

    # Step 1: 丢弃末尾不完整的键值对（字符串值被截断）
    # 匹配: "key": "value_but_truncated（末尾缺少闭合引号）
    # 这里 result 还没有添加引号，所以正则能正确匹配不完整的字符串值
    result = re.sub(r',?\s*"[^"]*"\s*:\s*"[^"]*$', '', result)
    # 也处理 "key": bare_text 截断（没有引号包裹的值被截断）
    result = re.sub(r',?\s*"[^"]*"\s*:\s*\w[^,}\]]*$', '', result)
    # 处理整个对象被截断的情况：末尾是 { 但没有 }
    # e.g. ..., { "para_index": 102, "reason": "truncated...
    # 上面的 regex 已经移除了不完整的 KV，但可能还留有 { 开头
    result = re.sub(r',?\s*\{\s*$', '', result)

    # Step 2: 关闭未闭合的括号（在移除不完整内容后统计）
    open_braces = result.count('{') - result.count('}')
    open_brackets = result.count('[') - result.count(']')

    # 先关闭内层（数组），再关闭外层（对象）
    result += ']' * max(open_brackets, 0)
    result += '}' * max(open_braces, 0)

    # Step 3: 再次清理尾部逗号
    result = re.sub(r',\s*([}\]])', r'\1', result)

    return result


# ========== 输入文本构建 ==========

def build_input_text(
    paragraphs: list[TaggedParagraph],
    score_map: dict[int, int] | None = None,
) -> str:
    """将筛选后的段落拼接为 LLM 输入文本。

    表格段落（有 table_data）渲染为 markdown 表格格式，
    确保 LLM 能看到完整的表格内容而非仅表头摘要。

    Args:
        paragraphs: 筛选后的段落列表（按原文顺序排列）
        score_map: 段落得分映射 {para_index: score}，
            传入时在每个段落前标注相关度得分，引导模型优先关注高分段落。
            得分含义：关键词匹配的高=7, 中=4, 低=2，分数越高越相关。
            0 分表示向量语义补漏匹配（非关键词匹配）。
    """
    lines = []
    for tp in paragraphs:
        prefix = f"[{tp.index}]"
        if tp.section_title:
            prefix += f" [{tp.section_title}]"
        # 添加相关度得分标注
        if score_map is not None:
            score = score_map.get(tp.index, 0)
            if score > 0:
                prefix += f" ⭐相关度:{score}"

        if tp.table_data and len(tp.table_data) > 0:
            # 渲染为 markdown 表格
            lines.append(f"{prefix} **表格**")
            header = tp.table_data[0]
            num_cols = len(header)
            lines.append("| " + " | ".join(str(c) for c in header) + " |")
            lines.append("| " + " | ".join(["---"] * num_cols) + " |")
            for row in tp.table_data[1:]:
                padded = list(row) + [""] * (num_cols - len(row))
                lines.append("| " + " | ".join(str(c) for c in padded[:num_cols]) + " |")
        else:
            lines.append(f"{prefix} {tp.text}")

    return "\n".join(lines)


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
    """底层 API 调用，返回 LLM 原始文本响应。

    Ollama 处理策略（双端点回退）：
    1. 先用原生 /api/chat (format:"json" + think) — deepseek-r1/qwen3 有效
    2. 如果失败或 content 为空（gemma4 bug），回退到 /v1/chat/completions
       (think=False + response_format:json_object) — gemma4 有效
    """
    api_cfg = settings["api"]
    base_url = api_cfg["base_url"].lower()
    is_ollama = "/v1" in base_url and "dashscope" not in base_url and "aliyuncs" not in base_url

    if is_ollama:
        content = _ollama_dual_call(messages, api_cfg)
        return content

    # DashScope / 其他 OpenAI 兼容服务：使用标准端点
    client = OpenAI(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
        timeout=api_cfg.get("timeout", 300),
        max_retries=5,
    )
    kwargs: dict = dict(
        model=api_cfg["model"],
        messages=messages,
        temperature=api_cfg.get("temperature", 0.1),
        max_tokens=api_cfg.get("max_output_tokens", 65536),
    )
    if api_cfg.get("enable_thinking") is not None:
        kwargs["extra_body"] = {"enable_thinking": api_cfg["enable_thinking"]}
    if api_cfg.get("response_format_json", True):
        kwargs["response_format"] = {"type": "json_object"}
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception:
        if "response_format" in kwargs:
            kwargs.pop("response_format")
            response = client.chat.completions.create(**kwargs)
        else:
            raise
    return response.choices[0].message.content or ""


def _convert_multimodal_to_ollama_native(messages: list[dict]) -> list[dict]:
    """将 OpenAI 多模态消息格式转换为 Ollama /api/chat 格式。

    OpenAI 格式: content = [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]
    Ollama 格式: content = "文字内容", images = ["base64_string_without_data_uri_prefix"]

    返回转换后的消息列表。纯文本消息不做修改。
    """
    converted = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            text_parts = []
            image_base64s = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        # data:image/jpeg;base64,... → 提取纯 base64 部分
                        if url.startswith("data:"):
                            # 去掉 data:image/jpeg;base64, 前缀
                            base64_part = url.split(",", 1)
                            if len(base64_part) == 2:
                                image_base64s.append(base64_part[1])
            new_msg = {"role": msg.get("role", "user"), "content": "".join(text_parts)}
            if image_base64s:
                new_msg["images"] = image_base64s
            converted.append(new_msg)
        else:
            converted.append(msg)
    return converted


def _ollama_dual_call(messages: list[dict], api_cfg: dict) -> str:
    """Ollama 双端点回退：先原生 API，后 OpenAI 兼容端点。

    原生 /api/chat format:json 强制 JSON 输出，thinking 模型同时保留思考能力
    （思考在 thinking 字段返回，content 为纯 JSON）。
    如果原生 API 失败或 content 为空，回退到 OpenAI 兼容端点。

    多模态消息（含图片）自动转换为 Ollama 原生格式：
    OpenAI content:[{image_url}] → Ollama content:"text" + images:[base64]
    """
    import httpx as _httpx
    ollama_server = api_cfg["base_url"].rstrip("/").removesuffix("/v1")
    model = api_cfg["model"]
    max_tokens = api_cfg.get("max_output_tokens", 65536)
    temperature = api_cfg.get("temperature", 0.1)
    timeout = api_cfg.get("timeout", 300)

    # Strategy 1: 原生 /api/chat — format:json 强制 JSON 输出
    # 将 OpenAI 多模态格式转换为 Ollama 原生格式（images 字段）
    native_messages = _convert_multimodal_to_ollama_native(messages)
    payload = {
        "model": model,
        "messages": native_messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    want_think = api_cfg.get("think", True)
    if want_think:
        payload["think"] = True

    try:
        resp = _httpx.post(
            f"{ollama_server.rstrip('/')}/api/chat",
            json=payload, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        content = msg.get("content", "")
        if content.strip():
            return content
        # content 为空但有 thinking — 某些模型可能只输出思考内容
        thinking = msg.get("thinking", "")
        if thinking.strip():
            logger.info("Ollama native API: content empty, using thinking field")
            return thinking
    except Exception as e:
        logger.warning("Ollama native API failed (%s), falling back to OpenAI endpoint", e)

    # Strategy 2: OpenAI 兼容 /v1/chat/completions
    # think=False + response_format:json_object — 对 gemma4 有效
    client = OpenAI(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
        timeout=timeout,
        max_retries=3,
    )
    try:
        response = client.chat.completions.create(
            model=model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
            extra_body={"think": False},
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        if content.strip():
            return content
        msg = response.choices[0].message
        alt = getattr(msg, 'reasoning_content', None) or getattr(msg, 'reasoning', None) or ""
        if alt.strip():
            logger.warning("Ollama OpenAI fallback: empty content, using reasoning field")
            return alt
    except Exception as e2:
        # response_format 也失败了，不带 response_format 重试
        logger.warning("Ollama OpenAI fallback with response_format failed (%s), retrying without", e2)
        try:
            response = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            if content.strip():
                return content
        except Exception as e3:
            logger.error("All Ollama strategies failed: %s", e3)
            raise
    logger.error("Ollama: all strategies returned empty content")
    return ""

def call_qwen(messages: list[dict], settings: dict | None = None) -> dict | list | None:
    """调用 DashScope API 并解析返回的 JSON。

    当 LLM 返回非 JSON 时，将其回复追加到对话中，要求转为 JSON 再返回。
    若仍失败则重新发起完整请求。
    """
    if settings is None:
        settings = load_settings()

    max_retries = settings["api"].get("retry", 3)
    conv = list(messages)  # 工作副本，可追加纠正消息

    for attempt in range(max_retries):
        try:
            raw = _raw_api_call(conv, settings)
            logger.debug("LLM raw response (first 200 chars): %s", raw[:200] if raw else "")
            result = parse_llm_json(raw)
            if result is not None:
                return result

            # 非 JSON：追加 LLM 回复 + 严格纠正指令，让同一轮对话修正
            logger.warning("Attempt %d: LLM returned non-JSON response, asking to convert", attempt + 1)
            logger.debug("LLM non-JSON output: %s", raw[:500])
            conv.append({"role": "assistant", "content": raw})
            conv.append({
                "role": "user",
                "content": "格式错误。你的回复不是 JSON。请重新生成结果，严格遵守以下要求：\n"
                           "1. 只输出 JSON 对象，不要包含任何其他文字、解释、Markdown 标记\n"
                           "2. 不要输出 <think> 等思考标签\n"
                           "3. 确保 JSON 格式合法，键名和字符串值使用双引号",
            })

        except Exception as e:
            error_msg = str(e)
            logger.warning("Attempt %d failed: %s", attempt + 1, error_msg)
            # API 异常时重置对话，避免带着脏上下文重试
            conv = list(messages)
            if attempt < max_retries - 1:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s ...
                logger.info("Retrying in %ds...", wait)
                time.sleep(wait)

    logger.error("All %d attempts failed", max_retries)
    return None


# ========== 分批处理 ==========

def batch_paragraphs(
    paragraphs: list[TaggedParagraph], max_tokens: int | None = None, settings: dict | None = None
) -> list[list[TaggedParagraph]]:
    """将段落按 token 上限分批，尽量在章节边界断开。"""
    if not paragraphs:
        return []

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
