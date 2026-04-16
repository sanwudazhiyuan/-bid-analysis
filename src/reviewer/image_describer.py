"""图片预描述：用 qwen3.5-flash 视觉模型为投标图片生成文字描述。

在 folder_builder 阶段调用，将描述嵌入 MD 文件，让 haha-code 智能体
只读文本即可获取图片信息，彻底绕过 Anthropic 兼容端点的图片限制。
"""
import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

logger = logging.getLogger(__name__)

# 视觉模型配置
VISION_MODEL = "qwen3.5-flash"
VISION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VISION_MAX_TOKENS = 4096
BATCH_SIZE = 4  # 每批 4 张图片
MAX_WORKERS = 8  # 8 并发

_IMAGE_DESC_SYSTEM = """你是投标文件图片分析专家。请详细描述每张图片内容，重点关注：
1. 图片类型：营业执照、资质证书、业绩合同、授权书、盖章文件、技术参数表、报价表、财务报表、审计报告等
2. 关键信息：证书编号、有效期、公司名称、资质等级、金额、日期等
3. 盖章情况：是否有公章/法人章/骑缝章，是否清晰可辨
4. 表格数据：如有表格，列出关键数值和指标
5. **跨页判断**：如果图片仅是标题页、目录页、封面页（如"2024 年财务报告""审计报告"仅有标题而无正文数据），请在描述末尾追加标注："[仅标题页，详细内容应在后续页面]"。如果只是封面或标题但后续有目录/目录页，也要注明。

请返回 JSON 格式，为每张图片生成 50-150 字的中文描述。"""

_IMAGE_DESC_USER_TEMPLATE = """请描述以下 {count} 张图片的内容。

返回 JSON 格式，必须严格遵循以下结构：
```json
{{
  "images": [
    {{"index": 1, "description": "第一张图片的描述"}},
    {{"index": 2, "description": "第二张图片的描述"}}
  ]
}}
```

注意：
- 必须返回标准 JSON 格式
- 按图片顺序给出描述，index 从 1 开始
- 每张图片描述 50-150 字
- 重点关注证书内容、盖章情况、关键数据"""


def _encode_image_base64(file_path: str) -> str | None:
    """将图片文件编码为 base64 data URI。"""
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("utf-8")
        ext = file_path.lower().split(".")[-1]
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff", "tif": "image/tiff"}
        mime = mime_map.get(ext, "image/jpeg")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning("图片编码失败 %s: %s", file_path, e)
        return None


def _describe_batch(
    api_key: str,
    image_paths: list[str],
    base_url: str | None = None,
    model: str | None = None,
) -> list[str]:
    """用视觉模型描述一批图片（最多 4 张）。

    Args:
        api_key: API Key
        image_paths: 图片路径列表
        base_url: API base_url (默认使用 DashScope 视觉端点)
        model: 模型名 (默认使用 qwen3.5-flash)

    Returns:
        每张图片的描述文本列表
    """
    content_parts = [
        {"type": "text", "text": _IMAGE_DESC_USER_TEMPLATE.format(count=len(image_paths))}
    ]

    for path in image_paths:
        data_uri = _encode_image_base64(path)
        if data_uri:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": data_uri},
            })

    effective_base_url = base_url or VISION_BASE_URL
    effective_model = model or VISION_MODEL
    logger.info("image_describer: effective_base_url=%s, effective_model=%s, base_url_arg=%s, model_arg=%s", effective_base_url, effective_model, base_url, model)
    is_ollama = "/v1" in effective_base_url and "dashscope" not in effective_base_url and "aliyuncs" not in effective_base_url
    # 本地模式增加 max_tokens，避免 JSON 被截断
    effective_max_tokens = 8192 if is_ollama else VISION_MAX_TOKENS

    vision_messages = [
        {"role": "system", "content": _IMAGE_DESC_SYSTEM},
        {"role": "user", "content": content_parts},
    ]

    # Ollama 和 DashScope 都通过 OpenAI 兼容端点传图
    # Ollama 必须用 think=False（gemma4 等模型的 bug：think=True 时 content 为空）
    # + response_format:json_object（Ollama 端点 think=False 时可正常使用）
    client = OpenAI(
        base_url=effective_base_url,
        api_key=api_key,
        timeout=120,
        max_retries=3,
    )
    create_kwargs = dict(
        model=effective_model,
        messages=vision_messages,
        max_tokens=effective_max_tokens,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    if is_ollama:
        create_kwargs["extra_body"] = {"think": False}

    response = client.chat.completions.create(**create_kwargs)
    raw = response.choices[0].message.content or ""
    # Ollama gemma4 bug 回退：content 为空时从 reasoning 字段提取
    if not raw.strip() and is_ollama:
        msg = response.choices[0].message
        alt = getattr(msg, 'reasoning_content', None) or getattr(msg, 'reasoning', None) or ""
        if alt.strip():
            logger.warning("Ollama vision: empty content, falling back to reasoning field")
            raw = alt

    descriptions = _parse_batch_response(raw, len(image_paths))
    return descriptions


def _repair_truncated_json(text: str) -> str:
    """尝试修复被截断的 JSON 字符串。

    当 max_tokens 不够时，模型输出可能被截断，导致 JSON 不完整。
    例如：{"images": [{"index": 1, "description": "这是一张...
    策略：逐步回退到最近的合法 JSON 边界。
    """
    # 尝试补齐未关闭的字符串和对象
    repaired = text.rstrip()
    # 统计未关闭的大括号/方括号
    open_braces = repaired.count("{") - repaired.count("}")
    open_brackets = repaired.count("[") - repaired.count("]")
    # 找最后一个完整的 } 或 ] 之后，然后补齐外层
    for _ in range(3):
        try:
            json.loads(repaired)
            return repaired  # 已经是合法 JSON
        except json.JSONDecodeError:
            pass
        # 尝试在最后一个 } 处截断并补齐
        last_brace = repaired.rfind("}")
        if last_brace > 0:
            repaired = repaired[:last_brace + 1]
            # 补齐外层括号
            open_braces = repaired.count("{") - repaired.count("}")
            open_brackets = repaired.count("[") - repaired.count("]")
            repaired += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
        else:
            # 完全没有 }，整个 JSON 都被截断了，返回空结构
            return '{"images": []}'
    return text


def _parse_batch_response(raw: str, count: int) -> list[str]:
    """解析模型返回的 JSON，提取每张图片的描述。"""
    text = raw.strip()
    # 去除思考过程标签（Ollama qwen3 等思考模型）
    import re
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = text.strip()
    # 去除 markdown 代码块标记
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        items = data.get("images", [])
        # 按 index 排序
        items.sort(key=lambda x: x.get("index", 0))
        descriptions = [item.get("description", "") for item in items[:count]]
        # 补齐缺失的
        while len(descriptions) < count:
            descriptions.append("[未返回描述]")
        return descriptions
    except json.JSONDecodeError as e:
        logger.warning("JSON 解析失败，尝试修复截断 JSON: %s, 原始内容前200字: %s", e, raw[:200])
        # 尝试修复截断的 JSON
        repaired = _repair_truncated_json(text)
        try:
            data = json.loads(repaired)
            items = data.get("images", [])
            items.sort(key=lambda x: x.get("index", 0))
            descriptions = [item.get("description", "") for item in items[:count]]
            while len(descriptions) < count:
                descriptions.append("[未返回描述]")
            logger.info("截断 JSON 修复成功，恢复 %d/%d 条描述", len([d for d in descriptions if d != "[未返回描述]"]), count)
            return descriptions
        except json.JSONDecodeError:
            logger.warning("截断 JSON 修复失败，原始内容前200字: %s", raw[:200])
            return ["[描述解析失败]" for _ in range(count)]
    except (KeyError, AttributeError) as e:
        logger.warning("JSON 结构异常: %s, 原始内容: %s", e, raw[:200])
        return ["[描述解析失败]" for _ in range(count)]


def describe_images(
    api_key: str,
    images: list[dict],
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """为所有图片生成文字描述。

    Args:
        api_key: API Key (DashScope 或 Ollama)
        images: [{filename, path, near_para_index}] 列表
        base_url: 视觉模型 API base_url (默认使用 DashScope 端点)
        model: 视觉模型名 (默认使用 qwen3.5-flash)

    Returns:
        {filename: description} 映射
    """
    if not images:
        return {}

    # 本地模式降低并发数和批次大小
    effective_base_url = base_url or VISION_BASE_URL
    is_local = "/v1" in effective_base_url and "dashscope" not in effective_base_url
    effective_max_workers = 2 if is_local else MAX_WORKERS
    effective_batch_size = 2 if is_local else BATCH_SIZE

    # 按批次分组
    batches = []
    for i in range(0, len(images), effective_batch_size):
        batch = images[i:i + effective_batch_size]
        batches.append(batch)

    descriptions: dict[str, str] = {}

    def _process_batch(batch: list[dict]) -> dict[str, str]:
        paths = [img["path"] for img in batch if img.get("path")]
        labels = [img["filename"] for img in batch if img.get("path")]
        if not paths:
            return {}
        try:
            batch_descs = _describe_batch(api_key, paths, base_url=base_url, model=model)
            return dict(zip(labels, batch_descs))
        except Exception as e:
            logger.warning("图片描述失败 (%s 张): %s", len(labels), e)
            return {label: f"[图片描述失败: {e}]" for label in labels}

    with ThreadPoolExecutor(max_workers=effective_max_workers) as executor:
        futures = {executor.submit(_process_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                batch_result = future.result()
                descriptions.update(batch_result)
            except Exception as e:
                labels = [img["filename"] for img in batch]
                for label in labels:
                    descriptions[label] = f"[图片描述失败: {e}]"

    logger.info(
        "图片描述完成: %d/%d 张",
        len(descriptions),
        len(images),
    )
    return descriptions
