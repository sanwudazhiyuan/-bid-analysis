"""图片预描述：用 qwen3.5-flash 视觉模型为投标图片生成文字描述。

在 folder_builder 阶段调用，将描述嵌入 MD 文件，让 haha-code 智能体
只读文本即可获取图片信息，彻底绕过 Anthropic 兼容端点的图片限制。
"""
import base64
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

logger = logging.getLogger(__name__)

# 视觉模型配置
VISION_MODEL = "qwen3.5-flash"
VISION_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VISION_MAX_TOKENS = 2048
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
) -> list[str]:
    """用视觉模型描述一批图片（最多 4 张）。

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

    client = OpenAI(
        base_url=VISION_BASE_URL,
        api_key=api_key,
        timeout=120,
        max_retries=3,
    )

    messages = [
        {"role": "system", "content": _IMAGE_DESC_SYSTEM},
        {"role": "user", "content": content_parts},
    ]

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=messages,
        max_tokens=VISION_MAX_TOKENS,
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    descriptions = _parse_batch_response(raw, len(image_paths))
    return descriptions


def _parse_batch_response(raw: str, count: int) -> list[str]:
    """解析模型返回的 JSON，提取每张图片的描述。"""
    # 去除 markdown 代码块标记
    text = raw.strip()
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
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        logger.warning("JSON 解析失败: %s, 原始内容: %s", e, raw[:200])
        return ["[描述解析失败]" for _ in range(count)]


def describe_images(
    api_key: str,
    images: list[dict],
) -> dict[str, str]:
    """为所有图片生成文字描述。

    Args:
        api_key: DashScope API Key
        images: [{filename, path, near_para_index}] 列表

    Returns:
        {filename: description} 映射
    """
    if not images:
        return {}

    # 按批次分组
    batches = []
    for i in range(0, len(images), BATCH_SIZE):
        batch = images[i:i + BATCH_SIZE]
        batches.append(batch)

    descriptions: dict[str, str] = {}

    def _process_batch(batch: list[dict]) -> dict[str, str]:
        paths = [img["path"] for img in batch if img.get("path")]
        labels = [img["filename"] for img in batch if img.get("path")]
        if not paths:
            return {}
        try:
            batch_descs = _describe_batch(api_key, paths)
            return dict(zip(labels, batch_descs))
        except Exception as e:
            logger.warning("图片描述失败 (%s 张): %s", len(labels), e)
            return {label: f"[图片描述失败: {e}]" for label in labels}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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
