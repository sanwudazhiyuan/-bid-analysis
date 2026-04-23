"""暗标规则解析：拆分文档为逐条规则、LLM 分类、与通用规则合并。"""
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "config" / "anbiao_default_rules.json"
_CLASSIFY_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "anbiao_rule_classify.txt"


@dataclass
class AnbiaoRule:
    rule_index: int
    rule_text: str
    rule_type: str           # "format" | "content"
    source_section: str = ""
    is_mandatory: bool = True
    category: str = ""

    @property
    def violation_level(self) -> str:
        return "fail" if self.is_mandatory else "warning"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["violation_level"] = self.violation_level
        return d


def load_default_rules() -> list[dict]:
    """加载通用暗标规则配置。"""
    with open(_DEFAULT_RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_rules(
    project_rules: list[AnbiaoRule],
    default_rules: list[dict],
) -> list[AnbiaoRule]:
    """合并项目规则和通用规则。项目规则覆盖同 category 的通用规则。"""
    project_categories = {r.category for r in project_rules if r.category}

    merged = list(project_rules)
    next_index = max((r.rule_index for r in project_rules), default=0) + 1

    for dr in default_rules:
        if dr.get("category") in project_categories:
            continue
        merged.append(AnbiaoRule(
            rule_index=next_index,
            rule_text=dr["rule_text"],
            rule_type=dr["rule_type"],
            source_section="通用规则",
            is_mandatory=dr.get("is_mandatory", True),
            category=dr.get("category", ""),
        ))
        next_index += 1

    return merged


def parse_anbiao_rules(file_path: str, api_settings: dict) -> list[AnbiaoRule]:
    """解析暗标规则文档为逐条规则列表。

    流程：
    1. unified.py 解析文档
    2. 拼接全文给 LLM 分类
    3. LLM 分类每条规则（format/content/mandatory/category）
    4. 过滤物理世界规则
    """
    from src.parser.unified import parse_document
    from src.extractor.base import call_qwen, build_messages

    paragraphs = parse_document(file_path)
    if not paragraphs:
        logger.warning("暗标规则文档解析为空: %s", file_path)
        return []

    # 拼接全文给 LLM 分类
    rules_text = "\n".join(f"[{p.index}] {p.text}" for p in paragraphs if p.text.strip())

    prompt_template = _CLASSIFY_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{rules_text}", rules_text)
    messages = build_messages(system="你是暗标规则分析专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not isinstance(result, list):
        logger.error("LLM 规则分类返回格式错误: %s", type(result))
        return []

    rules = []
    for idx, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        # 过滤物理世界规则
        if item.get("is_physical", False):
            continue
        rules.append(AnbiaoRule(
            rule_index=idx,
            rule_text=item.get("rule_text", ""),
            rule_type=item.get("rule_type", "content"),
            source_section=item.get("source_section", "项目规则"),
            is_mandatory=item.get("is_mandatory", True),
            category=item.get("category", ""),
        ))

    logger.info("暗标规则解析: %d 条规则（已过滤物理世界规则）", len(rules))
    return rules