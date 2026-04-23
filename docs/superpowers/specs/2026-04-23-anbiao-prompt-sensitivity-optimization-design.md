# 暗标审核提示词敏感度优化 · 设计文档

- **日期**: 2026-04-23
- **分支**: feat/anbiao-review
- **状态**: Draft
- **相关文件**:
  - [config/prompts/anbiao_content_review.txt](../../../config/prompts/anbiao_content_review.txt)
  - [config/prompts/anbiao_content_review_conclude.txt](../../../config/prompts/anbiao_content_review_conclude.txt)
  - [src/reviewer/anbiao_reviewer.py](../../../src/reviewer/anbiao_reviewer.py)
  - [src/models.py](../../../src/models.py)
  - [src/reviewer/tests/test_anbiao_reviewer.py](../../../src/reviewer/tests/test_anbiao_reviewer.py)

## 1. 背景与问题

当前暗标内容审核的提示词过于敏感：一旦文本中出现与企业、产品、客户、人员相关的描述，模型就倾向于标注为违规，缺乏"该信息是否真正会暴露投标人身份"这一关键判断维度。实际反馈中已观察到以下误报类型：

- **A. 泛指性描述**："我司服务过多家大型银行"等含企业描述但不含唯一标识的表述被标注。
- **B. 行业/技术术语**："基于 ISO9001 体系"、"采用华为云"、"Spring Boot"等通用产品/标准被误判为身份暴露。
- **C. 脱敏后的客户名称**："某国有商业银行"、"华东地区某城商行"等规则明确允许的脱敏表述仍被标注。
- **D. 已打码的图片/证书**：图片内容已遮盖，模型仍按"出现了证书"误报。
- **E. 第三方名称**：招标方名称、友商名称、合作伙伴名称被当作投标人身份暴露。
- **F. 我司自研产品脱敏后**："我司自研的\*\*\*平台"等已脱敏产品名仍被标注。
- **G. 投机性质疑**：模型使用"可能暗示"、"建议核实"、"虽已脱敏但仍建议"等兜底语，对明显合规的内容提出没有具体反推路径的怀疑。

核心症结是：模型把"信息出现"等同于"信息暴露身份"，且在不确定时倾向于投机性质疑而非放过。

## 2. 目标与非目标

### 2.1 目标

- 显著降低误报率，尤其消除 G 类投机性质疑。
- 对不确定的边界情况给出**分级结果**（fail / suspect），而不是二选一硬判。
- 在提示词层面强化"可识别性"作为核心判据，不依赖模型隐含直觉。
- 保留召回能力：真正暴露身份的内容仍须被标为 fail。

### 2.2 非目标

- **不**引入两阶段独立 LLM 调用（成本与延迟考量，仍按现有批次流水线）。
- **不**重构暗标审核的整体架构（批次切分、并发、DB 模型保持现状）。
- **不**改动 advisory/mandatory 的规则分类本身。

## 3. 设计概览

采用 **B + D 组合**：

- **D（规则差异化判据）**：在提示词中加入"可识别性测试"作为最高准则，并对每类规则给出明确的"算/不算违规"判据与正反例。
- **B（分级输出）**：将候选项的严重度从"按规则 mandatory/advisory 一刀切"改为**按候选项自判**，引入 `fail` 与 `suspect` 两档；`suspect` 设高门槛，并通过强制 `identification_path` 字段消除投机性质疑。

## 4. 详细设计

### 4.1 可识别性测试（Identifiability Test）

在 `anbiao_content_review.txt` 顶部加入最高准则：

> 判断是否违规的唯一标准不是"是否提及了企业/产品/客户/人员"，而是：
> **一个完全不了解投标人的评审专家，仅凭这段内容，能否唯一反推出投标人是谁？**
> - 能唯一反推 → 违规
> - 不能唯一反推（信息太泛、已脱敏、通用名词/行业术语、第三方主体）→ 不违规

### 4.2 分类判据与正反例

在提示词中为每一类规则给出二元判据：

**① 身份信息类（mandatory）**
- 算违规：公司全称/简称/英文名、logo、邮箱域名、公司电话、具体人名、身份证号、可辨识公章、含编号的资质证书、未打码人员照片。
- 不算违规：「我司」「本公司」「项目组」等通用自称；无姓名的角色/资历描述（"项目经理 10 年经验/PMP 认证"）；通用标准/第三方产品（ISO9001、Spring Boot、华为云）；脱敏占位符（\*\*\*、×××、###）。

**② 客户名称类（mandatory）**
- 算违规：出现具体客户全称或可识别简称。
- 不算违规：脱敏表述（"某国有商业银行"、"华东地区某城商行"、"某头部券商"）。

**③ 我司自研产品**
- 算违规：产品名未脱敏且在市场上可被唯一关联到我司。
- 不算违规：已脱敏的产品名（"我司自研的\*\*\*平台"）；通用功能描述（"自研的消息中间件"）。

**④ 第三方主体**
- 一律不算违规：招标方名称、友商名称、合作伙伴名称、通用技术产品名。

**⑤ 图片/证书（advisory）**
- 判据只看图片中可见的文字/图形是否暴露投标人身份。已打码/遮盖 → 不违规；未打码 → 标 `suspect`。

**⑥ 业绩案例（advisory）**
- 客户名与我司标识均已脱敏 → 不违规；未脱敏 → 标 `suspect`。

### 4.3 `suspect` 准入标准

`suspect` 必须满足以下三条之一，否则应归为 pass（即不进入 candidates）：

1. **具体信息路径未确认**：能指出一条具体的身份反推路径，但无法判断该路径是否生效（如"XX 中心"是通用部门还是我司特有机构不明）。
2. **脱敏充分性存疑**：明显做了脱敏处理，但脱敏粒度是否足够需人工判断（如"某头部城商行，资产规模约 X 万亿"）。
3. **图片/公章可辨识度存疑**：图片虽已打码，但残留轮廓/部分文字仍可能被识别。

### 4.4 投机性质疑负面清单（硬规则）

提示词中明确禁止以下输出，遇到此类表述应自动归为 pass：

- ❌ "可能暗示特定合作关系"——没有具体暗示路径就是没有。
- ❌ "建议核实是否需要进一步脱敏"——审查者的职责是判定，不是建议核实。
- ❌ "虽已脱敏，但仍建议..."——已脱敏即已合规，不再质疑。
- ❌ "该描述较为具体，有可能..."——主观猜测。
- ❌ 任何以"可能/或许/恐怕/建议/似乎"开头的质疑。

**硬规则**：若无法给出**具体、可论证的反推路径**（"根据 X 信息可以推断出 Y 投标人，因为 Z"），则不得标注为 suspect。

### 4.5 候选项结构变更

候选项 schema 新增 `severity` 与 `identification_path`：

```json
{
  "para_index": 12,
  "text_snippet": "服务过某头部券商...",
  "severity": "fail" | "suspect",
  "rule_category": "客户名称",
  "identification_path": "具体说明：从什么信息→如何反推→指向哪类主体。写不出具体路径则不得标注此项。",
  "reason": "一句话结论"
}
```

`identification_path` 是**写作强制**：它逼模型必须写出具体路径，否则应放弃标注。这是对抗投机质疑最有效的手段。

### 4.6 Conclude 阶段聚合规则

修改 `anbiao_content_review_conclude.txt`：

| 批次候选结果 | 最终 result |
|---|---|
| 存在候选 severity=fail | `fail` |
| 无 fail 但存在候选 severity=suspect | `warning`（提醒人工核查） |
| 全部 pass / 无候选 | `pass` |

advisory 规则的候选项一律落到 `suspect`，不会升级为 `fail`。

**术语约定**：本方案涉及两套字段，避免实现时混淆：

- `candidate.severity` ∈ `{fail, suspect}`：**候选级**，由 LLM 按 4.3/4.4 判定。
- `result` ∈ `{pass, fail, warning}`：**最终结论**，由 conclude 按上表从候选聚合得出。
- `AnbiaoRuleResult.severity` ∈ `{critical, minor}`：**规则级严重度**，由候选聚合得出（见 5.2），与 `rule.is_mandatory` 无直接一一对应关系（advisory 强制 minor 封顶；mandatory 若全部候选为 suspect 也应输出 minor）。

conclude prompt 的 summary 字段保留现状输出（不删除，但不作为判定依据）。

## 5. 代码改动范围

### 5.1 提示词（主要工作量）

- 改 [config/prompts/anbiao_content_review.txt](../../../config/prompts/anbiao_content_review.txt)：
  - 顶部加入 4.1 可识别性测试。
  - `candidates` 结构加入 `severity` 与 `identification_path` 字段。
  - 加入 4.2 分类判据与正反例。
  - 加入 4.3 suspect 准入标准、4.4 投机性质疑负面清单。
  - 移除旧的"mandatory/advisory → fail/warning"一刀切映射说明（改由候选项自判）。

- 改 [config/prompts/anbiao_content_review_conclude.txt](../../../config/prompts/anbiao_content_review_conclude.txt)：
  - 聚合规则按 4.6 调整。
  - advisory 规则的候选项只能是 suspect。

### 5.2 Python 后端

- [src/reviewer/anbiao_reviewer.py:196-212](../../../src/reviewer/anbiao_reviewer.py#L196) `_format_chapter_results`：在格式化每个候选项时透传 `severity` 与 `identification_path` 到 conclude 提示词输入文本（例如："- 段落{N} [{severity}]: {reason} | 路径: {identification_path}"）。
- [src/reviewer/anbiao_reviewer.py:533](../../../src/reviewer/anbiao_reviewer.py#L533) 与 [:565](../../../src/reviewer/anbiao_reviewer.py#L565) 最终 severity 聚合：
  - 由"按规则 `is_mandatory` 一刀切"改为按候选项聚合：存在 `fail` → critical；全为 `suspect` → minor；无候选 → pass。
  - advisory 规则强制 minor 封顶，不允许升级为 critical。
- [src/reviewer/anbiao_reviewer.py:547-555](../../../src/reviewer/anbiao_reviewer.py#L547) `tender_locations` 构造：将候选级 severity 带入 location（新增字段或写入 `reason` 前缀）。

### 5.3 数据模型

当前暗标候选项在 `anbiao_reviewer.py` 中以 `dict` 形式流转，`src/models.py` 中**无**对应的 pydantic 模型（已确认）。本方案采取**最小侵入**方案：

- **候选项**：保持 dict 形式，新增键 `severity`、`identification_path`、`rule_category`，均为可选字符串，契约在提示词与 `_format_chapter_results` 中对齐，不新增 pydantic 模型。
- **`tender_locations`**：若 [src/models.py](../../../src/models.py) 存在对应模型，添加可选字段 `severity: Literal["fail", "suspect"] | None`；若仍为 dict，则仅约定键名。实现阶段按实际情况选择。
- 数据库层不新增列；历史记录无新字段时前端按"未知等级"回退显示。

`rule_category` 取值约定为 4.2 中的六类字符串（`身份信息` / `客户名称` / `我司自研产品` / `第三方主体` / `图片证书` / `业绩案例`），非必填，由 LLM 输出作为可读性辅助，不参与后端逻辑分支。

### 5.4 前端（本次范围外）

前端双色展示（fail 红 / suspect 黄）**不在本次实现范围**，留作后续独立任务。本次只保证后端字段透出到 API 响应即可（字段可选，前端不读不影响渲染）。

### 5.5 兼容性

- 旧审查记录无 `severity` 字段 → 回退按 `rule.is_mandatory` 映射，保持当前行为。
- schema 字段全部可选，无破坏性变更。

## 6. 测试策略

### 6.1 误报回归用例（新增，核心资产）

在 [src/reviewer/tests/test_anbiao_reviewer.py](../../../src/reviewer/tests/test_anbiao_reviewer.py) 增加 fixture，覆盖 A–G 场景，断言这些**不应**出现在 candidates 里：

- A：泛指性描述（"我司服务过多家大型银行"）。
- B：行业/技术术语（"基于 ISO9001 体系"、"采用华为云"）。
- C：脱敏后的客户名称（"某头部城商行"）。
- D：已打码的证书图片。
- E：第三方名称（招标方名称、合作伙伴）。
- F：脱敏后的我司自研产品（"我司自研的\*\*\*平台"）。
- G：投机性质疑触发样本（"提及与特定方（虽已脱敏）的合作开发方案"）。

### 6.2 正例保留

保留既有 fail 用例，确认真正暴露身份的内容仍被标为 `fail`，未出现漏报回退。

### 6.3 手动 diff 对比

在真实标书样本（至少 3 份历史已审核标书）上跑新旧提示词，人工对比候选数差异与误报率。粗略目标：**A–G 误报场景在样本中的误报数量下降 ≥ 70%，且无新增漏报**。仅作为发布前一次性验证，非 CI 门槛。

## 7. 风险与缓解

- **召回下降**：强化"可识别性"可能使某些边界违规被漏报。缓解：6.1 的回归用例只测误报，不测召回；召回由 6.2 的既有正例保障；上线前 6.3 手动 diff 可发现明显漏报。
- **模型不遵守 `identification_path` 强制**：模型可能伪造路径以绕过。缓解：提示词中明确"写不出具体路径则不得标注"并给出反例。后处理阶段的禁用词检测（自动将含"可能/或许/建议"的候选降级为 pass）**留作后续优化**，本次不实现。
- **advisory 规则输出混乱**：若模型忽略"advisory 只能 suspect"规则输出了 fail，conclude 阶段会错误升级。缓解：Python 后端在聚合时对 advisory 规则强制 minor 封顶（5.2 已覆盖）。

## 8. 交付物清单

- `anbiao_content_review.txt` 重写版。
- `anbiao_content_review_conclude.txt` 聚合规则更新版。
- `anbiao_reviewer.py` 三处透传/聚合改动。
- `models.py` 可选字段新增。
- 新增误报回归测试用例（A–G）。
- （可选）前端双色标签。
