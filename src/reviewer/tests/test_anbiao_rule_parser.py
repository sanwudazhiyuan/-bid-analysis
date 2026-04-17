"""Test anbiao rule parser utilities."""
from src.reviewer.anbiao_rule_parser import AnbiaoRule, load_default_rules, merge_rules


def test_load_default_rules():
    rules = load_default_rules()
    assert len(rules) >= 8
    assert all("rule_text" in r for r in rules)
    assert all(r["rule_type"] in ("format", "content") for r in rules)


def test_anbiao_rule_violation_level():
    mandatory = AnbiaoRule(rule_index=0, rule_text="test", rule_type="format", is_mandatory=True)
    advisory = AnbiaoRule(rule_index=1, rule_text="test", rule_type="content", is_mandatory=False)
    assert mandatory.violation_level == "fail"
    assert advisory.violation_level == "warning"


def test_merge_rules_project_overrides_default():
    project = [AnbiaoRule(rule_index=0, rule_text="自定义页码规则", rule_type="format", category="页码")]
    defaults = load_default_rules()
    merged = merge_rules(project, defaults)
    # 页码 category 被项目规则覆盖，不应出现默认的页码规则
    page_rules = [r for r in merged if r.category == "页码"]
    assert len(page_rules) == 1
    assert page_rules[0].rule_text == "自定义页码规则"


def test_merge_rules_default_supplements():
    project = [AnbiaoRule(rule_index=0, rule_text="test", rule_type="format", category="页码")]
    defaults = load_default_rules()
    merged = merge_rules(project, defaults)
    # 其他 category 的通用规则应被补充进来
    categories = {r.category for r in merged}
    assert "身份信息" in categories
    assert "图片使用" in categories