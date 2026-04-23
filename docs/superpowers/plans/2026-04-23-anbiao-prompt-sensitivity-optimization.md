# 暗标审核提示词敏感度优化 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过重写暗标内容审核提示词（引入"可识别性测试"+分级输出 + `identification_path` 强制路径）与同步调整聚合逻辑，显著降低 A–G 类误报。

**Architecture:**
- 两份提示词重写（`anbiao_content_review.txt` / `anbiao_content_review_conclude.txt`）。
- 候选项 schema 新增 `severity` (`fail`/`suspect`)、`identification_path`、`rule_category`，以 dict 键方式流转，不新增 pydantic 模型。
- `_format_chapter_results` 透传新字段给 conclude；最终结果聚合由"按规则 `is_mandatory` 一刀切"改为"按候选 severity 聚合 + advisory 规则 minor 封顶"。

**Tech Stack:** Python 3 / pytest / 纯文本 prompt 模板。

**Spec:** [docs/superpowers/specs/2026-04-23-anbiao-prompt-sensitivity-optimization-design.md](../specs/2026-04-23-anbiao-prompt-sensitivity-optimization-design.md)

**范围外：** 前端双色展示、禁用词后处理降级、pydantic 模型化。

---

## Chunk 1: 提示词重写

### Task 1: 重写 anbiao_content_review.txt

**Files:**
- Modify: `config/prompts/anbiao_content_review.txt`（全文重写）

- [ ] **Step 1: 读取当前提示词**

Run: `cat config/prompts/anbiao_content_review.txt`
记录当前占位符：`{rule_text}`、`{severity_level}`、`{chapter_title}`、`{tender_text}` 必须保留。

- [ ] **Step 2: 全文替换为新版提示词**

按以下结构重写文件内容：

```
你是暗标内容审查专家。请检查以下投标文件段落内容是否违反暗标规则。

## 最高准则：可识别性测试（Identifiability Test）
判断是否违规的唯一标准不是"是否提及了企业/产品/客户/人员"，而是：
"一个完全不了解投标人的评审专家，仅凭这段内容，能否唯一反推出投标人是谁？"
- 能唯一反推 → 违规
- 不能唯一反推（信息太泛、已脱敏、通用名词/行业术语、第三方主体）→ 不违规

"我司"是通用自称，不暴露任何投标人身份，不违规。

## 当前审查规则
{rule_text}

## 规则严重等级（仅用于 advisory 规则的封顶约束）
{severity_level}
- mandatory：候选项可以是 fail 或 suspect
- advisory：候选项只能是 suspect（不允许输出 fail）

## 当前批次
{chapter_title}

## 投标文件段落内容
{tender_text}

## 分类判据（正反例）

### ① 身份信息类
- ✅ 算违规：公司全称/简称/英文名、logo、邮箱域名、公司电话、具体人名、身份证号、可辨识公章、含编号的资质证书、未打码人员照片。
- ❌ 不算违规：「我司」「本公司」「项目组」等通用自称；无姓名的角色/资历描述（如"项目经理10年经验/PMP认证"）；通用标准/第三方产品（如 ISO9001、Spring Boot、华为云）；脱敏占位符（***、×××、###）。

### ② 客户名称类
- ✅ 算违规：出现具体客户全称或可识别简称（如"工商银行总行"、"招行深圳分行"）。
- ❌ 不算违规：脱敏表述（如"某国有商业银行"、"华东地区某城商行"、"某头部券商"）。

### ③ 我司自研产品
- ✅ 算违规：产品名未脱敏且在市场上可被唯一关联到我司。
- ❌ 不算违规：已脱敏的产品名（如"我司自研的***平台"）；通用功能描述（如"自研的消息中间件"）。

### ④ 第三方主体
- ❌ 一律不算违规：招标方名称、友商名称、合作伙伴名称、通用技术产品名。

### ⑤ 图片/证书（advisory）
- 只看图片中可见的文字/图形是否暴露投标人身份。已打码/遮盖 → 不违规；未打码 → suspect。

### ⑥ 业绩案例（advisory）
- 客户名与我司标识均已脱敏 → 不违规；未脱敏 → suspect。

## severity 判定规则

- `fail`：明确违反可识别性测试，身份可被唯一反推（仅 mandatory 规则可用）。
- `suspect`：**必须满足以下三条之一，否则不得标注**：
  1. 能指出一条具体的身份反推路径，但无法确认该路径是否生效（如"XX 中心"是否为我司特有机构不明）。
  2. 明显做了脱敏，但脱敏粒度是否足够需人工判断（如"某头部城商行，资产规模约 X 万亿"）。
  3. 图片虽已打码，但残留轮廓/部分文字仍可能被识别。

## ⛔ 禁止的"投机性质疑"（违反以下任一模式则不得标注）

- ❌ "可能暗示特定合作关系"——没有具体暗示路径就是没有。
- ❌ "建议核实是否需要进一步脱敏"——审查者的职责是判定，不是建议核实。
- ❌ "虽已脱敏，但仍建议..."——已脱敏即已合规，不再质疑。
- ❌ "该描述较为具体，有可能..."——主观猜测。
- ❌ 以"可能/或许/恐怕/建议/似乎"开头的质疑。

**硬规则**：若无法写出具体、可论证的 `identification_path`（"根据 X 信息可以推断出 Y 投标人，因为 Z"），则不得标注该项。

## 输出格式

请扫描上述段落内容，找出所有违反规则的位置。输出 JSON：
```json
{
  "candidates": [
    {
      "para_index": 段落编号（[N] 中的数字）,
      "text_snippet": "违规文本片段或图片ID（20字以内）",
      "severity": "fail" 或 "suspect",
      "rule_category": "身份信息" | "客户名称" | "我司自研产品" | "第三方主体" | "图片证书" | "业绩案例",
      "identification_path": "具体反推路径：从什么信息→如何反推→指向哪类主体。若只能写'可能/或许/建议'，则不得输出此候选",
      "reason": "一句话结论"
    }
  ],
  "summary": "本批次审查摘要"
}
```

## 注意
- para_index 必须是文本中 [N] 标记的实际数字。每个段落（文字、图片、表格）都有独立的 [N]。
- 对于图片标记 [图片: xxx]，文本中保留"[图片: image1.png]"及"以下是图片ID=image1.png的图片内容："提示，可据此确定图片与 ID 的对应关系。
- 图片审查特别注意：公司名称、Logo、品牌标识、人员姓名、地址等。已打码的证书/合同/条例不算违规。
- 脱敏占位符（***、×××、###）替换的内容不算暴露。
- 表格【表格】若含公司名称/Logo 等，标注表格的 para_index。
- advisory 规则的候选项 severity 必须为 suspect，不得为 fail。
- 本批次无违规 → candidates 返回空数组。
```

- [ ] **Step 3: 保留占位符校验**

逐个占位符断言存在（避免 `grep -c` 行数口径歧义）：

Run:
```bash
for p in '{rule_text}' '{severity_level}' '{chapter_title}' '{tender_text}'; do
  grep -q "$p" config/prompts/anbiao_content_review.txt || echo "MISSING: $p"
done
```
Expected: 无任何 `MISSING:` 输出。

- [ ] **Step 4: 提交**

```bash
git add config/prompts/anbiao_content_review.txt
git commit -m "feat(anbiao): rewrite content review prompt with identifiability test and severity tiers"
```

---

### Task 2: 重写 anbiao_content_review_conclude.txt

**Files:**
- Modify: `config/prompts/anbiao_content_review_conclude.txt`（全文重写）

- [ ] **Step 1: 全文替换**

```
你是暗标内容审查专家，需综合各批次审查结果做出最终判定。

## 审查规则
{rule_text}

## 严重等级（封顶约束）
{severity_level}
- mandatory：result 可为 pass / warning / fail
- advisory：result 只能为 pass 或 warning（不允许 fail）

## 各批次审查结果
{chapter_results_text}

## 聚合判定规则

- 任一批次存在 severity=fail 的候选 → result = fail（advisory 规则除外，封顶为 warning）
- 无 fail，但存在 severity=suspect 的候选 → result = warning（提醒人工核查）
- 全部 pass 或无候选 → result = pass

## 输出格式
```json
{
  "result": "pass" 或 "fail" 或 "warning",
  "confidence": 0-100,
  "reason": "一句话概括判定依据"
}
```

## 注意
- 不要重复列出具体违规位置（由批次候选带出）。
- advisory 规则即使存在 fail 候选也输出 warning（防御性处理）。
- reason 必须基于批次候选的 identification_path 做出总结，不要使用"可能/或许/建议"等投机表述。
```

- [ ] **Step 2: 占位符校验**

Run:
```bash
for p in '{rule_text}' '{severity_level}' '{chapter_results_text}'; do
  grep -q "$p" config/prompts/anbiao_content_review_conclude.txt || echo "MISSING: $p"
done
```
Expected: 无任何 `MISSING:` 输出。

- [ ] **Step 3: 提交**

```bash
git add config/prompts/anbiao_content_review_conclude.txt
git commit -m "feat(anbiao): update conclude prompt to aggregate from candidate severity"
```

---

## Chunk 2: Python 后端改动

### Task 3: `_format_chapter_results` 透传新字段

**Files:**
- Modify: `src/reviewer/anbiao_reviewer.py:196-212`
- Test: `src/reviewer/tests/test_anbiao_reviewer.py`

- [ ] **Step 1: 写失败测试**

在 `test_anbiao_reviewer.py` 追加：

```python
def test_format_chapter_results_passes_severity_and_path():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    chapter_results = [{
        "chapter_title": "第一章",
        "candidates": [{
            "para_index": 5,
            "severity": "suspect",
            "identification_path": "从证书编号可反查到公司",
            "reason": "证书编号可识别",
        }],
        "summary": "发现1处可疑",
    }]
    text = _format_chapter_results(chapter_results)
    assert "[suspect]" in text
    assert "从证书编号可反查到公司" in text
    assert "段落5" in text
    assert "证书编号可识别" in text


def test_format_chapter_results_omits_missing_fields_gracefully():
    from src.reviewer.anbiao_reviewer import _format_chapter_results
    chapter_results = [{
        "chapter_title": "第二章",
        "candidates": [{"para_index": 3, "reason": "历史记录无新字段"}],
        "summary": "",
    }]
    text = _format_chapter_results(chapter_results)
    assert "段落3" in text
    assert "历史记录无新字段" in text
```

- [ ] **Step 2: 运行，确认失败**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py::test_format_chapter_results_passes_severity_and_path -v`
Expected: FAIL（当前函数不输出 severity/path）。

- [ ] **Step 3: 修改 `_format_chapter_results`**

将 `src/reviewer/anbiao_reviewer.py` 的 `_format_chapter_results` 函数替换为：

```python
def _format_chapter_results(chapter_results: list[dict]) -> str:
    """将逐章节审核结果格式化为综合判定 prompt 的输入文本。"""
    lines: list[str] = []
    for cr in chapter_results:
        lines.append(f"### 章节：{cr['chapter_title']}")
        candidates = cr.get("candidates") or []
        if candidates:
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                sev = c.get("severity")
                sev_tag = f" [{sev}]" if sev else ""
                reason = c.get("reason", "")
                path = c.get("identification_path", "")
                line = f"- 段落{c.get('para_index', '?')}{sev_tag}: {reason}"
                if path:
                    line += f" | 路径: {path}"
                lines.append(line)
        else:
            lines.append("（无违规内容）")
        summary = cr.get("summary", "")
        if summary:
            lines.append(f"摘要: {summary}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py::test_format_chapter_results_passes_severity_and_path src/reviewer/tests/test_anbiao_reviewer.py::test_format_chapter_results_omits_missing_fields_gracefully -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/reviewer/anbiao_reviewer.py src/reviewer/tests/test_anbiao_reviewer.py
git commit -m "feat(anbiao): pass severity and identification_path into conclude prompt"
```

---

### Task 4: 按候选 severity 聚合最终结果

**Files:**
- Modify: `src/reviewer/anbiao_reviewer.py:509-568`（两处 severity 赋值 + tender_locations）
- Test: `src/reviewer/tests/test_anbiao_reviewer.py`

- [ ] **Step 1: 写失败测试**

在 `test_anbiao_reviewer.py` 追加纯函数单测——抽取聚合逻辑到 helper 便于测试：

```python
def test_compute_rule_severity_fail_candidate_is_critical():
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "fail"}, {"severity": "suspect"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "critical"


def test_compute_rule_severity_all_suspect_is_minor():
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "suspect"}, {"severity": "suspect"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "minor"


def test_compute_rule_severity_advisory_capped_at_minor():
    """advisory 规则即使收到 fail 候选也封顶 minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "fail"}]
    assert _compute_rule_severity(candidates, is_mandatory=False) == "minor"


def test_compute_rule_severity_no_candidates_falls_back_to_rule_default():
    """无候选项时按规则默认：mandatory→critical，advisory→minor（仅作为结果对象的 severity 字段填充）。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    assert _compute_rule_severity([], is_mandatory=True) == "critical"
    assert _compute_rule_severity([], is_mandatory=False) == "minor"


def test_compute_rule_severity_legacy_candidates_without_severity_field():
    """历史候选无 severity 字段 → 回退按 is_mandatory（保持旧行为）。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"para_index": 1, "reason": "old"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "critical"
    assert _compute_rule_severity(candidates, is_mandatory=False) == "minor"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py -k compute_rule_severity -v`
Expected: FAIL（函数未定义）。

- [ ] **Step 3: 新增 `_compute_rule_severity` helper**

在 `src/reviewer/anbiao_reviewer.py` 的 `_format_chapter_results` 之后添加：

```python
def _compute_rule_severity(candidates: list[dict], is_mandatory: bool) -> str:
    """按候选项 severity 聚合规则级严重度。

    - advisory 规则：一律封顶 minor（即使模型错误输出 fail 候选也不升级）。
    - mandatory 规则：
      - 任一候选 severity==fail → critical
      - 全部 suspect → minor
      - 无候选 → critical（规则默认）
      - 候选无 severity 字段（历史数据）→ 按 is_mandatory 回退（保持旧行为）
    """
    if not is_mandatory:
        return "minor"
    if not candidates:
        return "critical"
    has_severity_field = any("severity" in c for c in candidates if isinstance(c, dict))
    if not has_severity_field:
        return "critical"
    has_fail = any(
        isinstance(c, dict) and c.get("severity") == "fail"
        for c in candidates
    )
    return "critical" if has_fail else "minor"
```

- [ ] **Step 4: 运行 helper 测试确认通过**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py -k compute_rule_severity -v`
Expected: PASS（5 个）。

- [ ] **Step 5: 在聚合调用处替换硬编码**

修改 `src/reviewer/anbiao_reviewer.py`：

- 第 533 行附近（LLM 失败分支）：
  ```python
  # 替换前:
  "severity": "critical" if rule.is_mandatory else "minor",
  # 替换后:
  "severity": _compute_rule_severity(all_candidates, rule.is_mandatory),
  ```

- 第 565 行附近（正常分支）：
  ```python
  # 替换前:
  "severity": "critical" if rule.is_mandatory else "minor",
  # 替换后:
  "severity": _compute_rule_severity(all_candidates, rule.is_mandatory),
  ```

- [ ] **Step 6: tender_locations 带出候选级 severity**

修改第 547-555 行附近：

```python
# 替换前:
para_indices = [c["para_index"] for c in all_candidates]
per_para_reasons = {c["para_index"]: c.get("reason", "") for c in all_candidates}
tender_locations = [{
    "batch_id": "all_candidates",
    "path": "accumulated",
    "global_para_indices": para_indices,
    "text_snippet": all_candidates[0].get("text_snippet", "") if all_candidates else "",
    "per_para_reasons": per_para_reasons,
}] if all_candidates else []

# 替换后:
para_indices = [c["para_index"] for c in all_candidates]
per_para_reasons = {c["para_index"]: c.get("reason", "") for c in all_candidates}
per_para_severity = {
    c["para_index"]: c.get("severity")
    for c in all_candidates if c.get("severity")
}
per_para_path = {
    c["para_index"]: c.get("identification_path")
    for c in all_candidates if c.get("identification_path")
}
tender_locations = [{
    "batch_id": "all_candidates",
    "path": "accumulated",
    "global_para_indices": para_indices,
    "text_snippet": all_candidates[0].get("text_snippet", "") if all_candidates else "",
    "per_para_reasons": per_para_reasons,
    "per_para_severity": per_para_severity,
    "per_para_identification_path": per_para_path,
}] if all_candidates else []
```

- [ ] **Step 7: 跑全量暗标测试套件确认无回归**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py -v`
Expected: 全部 PASS（含新增与既有）。

- [ ] **Step 8: 提交**

```bash
git add src/reviewer/anbiao_reviewer.py src/reviewer/tests/test_anbiao_reviewer.py
git commit -m "feat(anbiao): aggregate rule severity from candidate severity with advisory cap"
```

---

## Chunk 3: 误报回归测试与发布验证

### Task 5: A–G 误报回归 fixtures

**Files:**
- Test: `src/reviewer/tests/test_anbiao_reviewer.py`

**说明**：这些测试不调用真实 LLM（会伪造 LLM 响应），目的是锁定**聚合链路**不会因为历史数据缺失字段而回退为全部 critical，也锁定候选为 suspect 时最终 severity = minor。真正"提示词效果"的 A–G 验证在 Task 6 手动 diff 中完成。

- [ ] **Step 1: 写测试**

追加到 `test_anbiao_reviewer.py`（此处只做聚合链路的单元覆盖；端到端 LLM mock 若工程已有统一工具再另行补，避免引入新 mocking 方案）：

```python
# A–G 场景归档：以候选字典形式表达模型"应当"输出的样子，
# 用 _compute_rule_severity 验证聚合链路表现符合 spec §4.6。

def test_scenario_A_generic_mention_should_produce_no_candidate():
    """泛指性描述，模型不应产出候选，聚合落 critical 但无 tender_locations。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    # mandatory 规则 + 无候选 → critical（作为结果对象填充值，tender_locations 为空）
    assert _compute_rule_severity([], is_mandatory=True) == "critical"


def test_scenario_C_desensitized_client_name_is_suspect_at_worst():
    """脱敏客户名如被误判，也应是 suspect，聚合落 minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{
        "severity": "suspect",
        "identification_path": "'某头部城商行'+资产规模数据可能唯一指向某家",
    }]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "minor"


def test_scenario_E_third_party_name_must_not_be_fail():
    """第三方名称不得产生 fail 候选；即使误判为 suspect 也应落 minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "suspect", "identification_path": "招标方名称—但属第三方"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "minor"


def test_scenario_F_desensitized_own_product_suspect_caps_minor():
    """我司自研产品脱敏后若被标 suspect，不应升级 critical。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "suspect", "identification_path": "***脱敏名—需人工确认脱敏粒度"}]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "minor"


def test_scenario_advisory_rule_never_critical():
    """advisory 规则即使收到 fail 候选（模型违反提示词），也要封顶 minor。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{"severity": "fail", "identification_path": "模型错误升级"}]
    assert _compute_rule_severity(candidates, is_mandatory=False) == "minor"


def test_scenario_real_fail_candidate_produces_critical():
    """真正的 fail 候选（如公司全称）应聚合为 critical。"""
    from src.reviewer.anbiao_reviewer import _compute_rule_severity
    candidates = [{
        "severity": "fail",
        "identification_path": "公司全称'XX科技有限公司'可唯一识别投标人",
    }]
    assert _compute_rule_severity(candidates, is_mandatory=True) == "critical"
```

- [ ] **Step 2: 运行**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py -k scenario -v`
Expected: 6 PASS。

- [ ] **Step 3: 跑全量确认无回归**

Run: `pytest src/reviewer/tests/test_anbiao_reviewer.py -v`
Expected: 全部 PASS。

- [ ] **Step 4: 提交**

```bash
git add src/reviewer/tests/test_anbiao_reviewer.py
git commit -m "test(anbiao): add A-G false-positive regression coverage at aggregation layer"
```

---

### Task 6: 发布前手动 diff 验证（非 CI）

**说明**：此任务为人工操作，不自动化。目标：确认新提示词在 3 份历史已审核标书上将 A–G 误报数量下降 ≥ 70% 且无新增漏报（spec §6.3）。

- [ ] **Step 1: 选取样本**

选择至少 3 份近期已人工审核过的真实投标文件（含各类误报历史），记录旧审核结果的 candidates 数量与类别分布。

- [ ] **Step 2: 在新提示词下重跑**

用新版提示词对同样的 3 份文件走一遍暗标内容审核（直接调用 `run_anbiao_content_review` 相关入口即可）。

- [ ] **Step 3: 对比评估**

按规则分类汇总新旧结果，填一张对比表：

| 规则类别 | 旧 candidates | 新 candidates | 消除的误报 | 新增漏报 |
|---|---|---|---|---|
| 身份信息 | ... | ... | ... | ... |
| ... | | | | |

通过标准：**A–G 场景误报数量下降 ≥ 70% 且无新增漏报**。

- [ ] **Step 4: 如未达标，回到 Task 1 调整提示词**

常见调节点：
- 正反例不够贴合实际场景 → 补充来自 Step 3 中仍误报的样本。
- `suspect` 仍被滥用 → 强化 4.4 禁止清单。
- 出现漏报 → 反向检查 `identification_path` 是否被模型错误"写不出路径"而漏报真实违规，适当放宽。

- [ ] **Step 5: 通过后更新 spec 记录评估结果（可选）**

在 spec 末尾追加"§9 发布评估"章节，贴上对比表与通过情况。

---

## 完成标准

- [ ] Chunk 1 两份提示词重写完成并提交。
- [ ] Chunk 2 `_format_chapter_results` 透传、`_compute_rule_severity` 聚合、`tender_locations` 扩展三处完成，全部单测通过。
- [ ] Chunk 3 A–G 聚合链路回归测试通过；人工 diff 达到 ≥ 70% 降误报目标。
- [ ] `pytest src/reviewer/tests/test_anbiao_reviewer.py` 全部 PASS，无新警告。
