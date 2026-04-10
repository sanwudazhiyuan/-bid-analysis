"""中间结果持久化：JSON 序列化/反序列化各层输出"""

import json
import os
from datetime import datetime
from src.models import Paragraph, TaggedParagraph

CURRENT_SCHEMA_VERSION = "1.0"


def _check_version(data: dict, path: str):
    """检查 schema_version，不兼容时抛出 ValueError 提示用户重新提取"""
    version = data.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"文件 {path} 的 schema_version={version}，"
            f"当前版本={CURRENT_SCHEMA_VERSION}，请重新运行对应阶段"
        )


def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def save_parsed(paragraphs: list[Paragraph], path: str):
    """保存 Layer 1 解析结果"""
    _ensure_dir(path)
    data = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "paragraphs": [p.to_dict() for p in paragraphs],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_parsed(path: str) -> list[Paragraph]:
    """加载 Layer 1 解析结果"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    return [Paragraph(**p) for p in data["paragraphs"]]


def save_indexed(index_result: dict, path: str):
    """保存 Layer 2 索引结果"""
    _ensure_dir(path)
    data = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "confidence": index_result["confidence"],
        "sections": index_result["sections"],
        "tagged_paragraphs": [tp.to_dict() for tp in index_result["tagged_paragraphs"]],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_indexed(path: str) -> dict:
    """加载 Layer 2 索引结果"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    tagged = [TaggedParagraph(**tp) for tp in data["tagged_paragraphs"]]
    return {
        "confidence": data["confidence"],
        "sections": data["sections"],
        "tagged_paragraphs": tagged,
    }


def save_extracted(extracted: dict, path: str):
    """保存 Layer 3 提取结果"""
    _ensure_dir(path)
    extracted["generated_at"] = datetime.now().isoformat()
    if "schema_version" not in extracted:
        extracted["schema_version"] = CURRENT_SCHEMA_VERSION
    with open(path, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)


def load_extracted(path: str) -> dict:
    """加载 Layer 3 提取结果"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    return data


def save_reviewed(reviewed: dict, path: str):
    """保存 Layer 4 校对结果"""
    _ensure_dir(path)
    reviewed["reviewed_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reviewed, f, ensure_ascii=False, indent=2)


def load_reviewed(path: str) -> dict:
    """加载 Layer 4 校对结果"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    return data
