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
    """解析暗标规则文档为逐条规则列表。（详见 Chunk 2 Task 4 实现）"""
    raise NotImplementedError("Will be implemented in Task 4")