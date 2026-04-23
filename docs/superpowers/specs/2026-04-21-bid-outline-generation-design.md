# 投标文件大纲生成模块设计

日期：2026-04-21
作者：zhiyuan.hong
模块 key：`bid_format`（保留）

## 背景与问题

现有 [src/extractor/bid_format.py](../../../src/extractor/bid_format.py) 采用"两次调用 + 默认结构 fallback"策略：

1. 第一次 LLM 调用判断招标文件是否直接给出格式样例，有则按样例构建 docx
2. 没有样例时，走 [config/prompts/bid_format_fallback.txt](../../../config/prompts/bid_format_fallback.txt) 的**固定默认结构**填充 module_a~g 的 section 标题

两个问题：

- **固定默认结构不适用**：实际招标文件章节差异巨大。样本 1 顶层 8 章，技术部分 8.1~8.10；样本 2 顶层 13 章，资格证明文件下有三级细化到具体证书名（集成电路卡注册证书、银联标识产品企业资质认证证书等 7 种）、按年度拆分财务报告、按银行逐项列举业绩（16 家）。任何预设模板都会和真实招标文件严重错位。
- **下游聚合粒度不匹配**：[checklist.py](../../../src/extractor/checklist.py) 输出按资格/技术/商务/其他四大类聚合，无法支撑"资质证书下按具体证书名展开"这种枚举级目录。module_a~g 的 section 粒度也是话题级，同样聚合掉了枚举信号。

## 目标

针对**招标文件没有直接给出完整格式样例**的情况，动态生成契合本份招标文件实际要求的多级投标文件目录骨架，输出为 .docx 文档供人工填充正文。

不追求覆盖率指标，产物以人工过审为准。

## 非目标

- 不自动生成正文内容（仅骨架 + 空段落）
- 不自动展开"按投标人实际数据分项"的节点（如业绩按客户数展开），只做提示
- 不替换 checklist 或 module_a~g 的现有职责
- 不引入人工标注/编辑循环（`bid_format` 的 `reextract_with_annotations` 不接入新流水线）

## 方案总览

四层流水线，**所有招标文件均走完整流程**：

```
招标原文 tagged_paragraphs
    │
    ├──────────────┬──────────────┐
    ▼              ▼
Layer 1          Layer 2
格式样例抽取      骨架信号抽取（全文扫描）
（沿用现有        关键词 + 向量过滤 →
 bid_format.txt） 按段落数分批 →
                 LLM 抽 5 类结构信号
    │              │
    └──────┬───────┘
           ▼
Layer 3 · 目录合成（单次 LLM 调用）
    输入：Layer 1 格式样例 + Layer 2 结构信号
    输出：多级目录树 JSON（节点携带样例内容引用）
           │
           ▼
Layer 4 · docx 渲染（纯渲染，无 LLM）
    目录树 → 三级标题 + 空段落 +
    has_sample 节点嵌入 Layer 1 样例 +
    dynamic 节点红字提示
           │
           ▼
交付：投标文件大纲.docx
```

设计原则：

1. **Layer 1 与 Layer 2 并行协作**，不是互斥分支：Layer 1 抽"招标方给了哪些样例、样例内容是什么"，Layer 2 抽"招标方规定投标书有哪些章节/条目"。两者合起来才能构建完整目录
2. **Layer 2 独立自足**，不依赖 a~g / checklist 的下游聚合结果，避免粒度错配
3. **两次 LLM 调用分工明确**：Layer 1/2 做抽取，Layer 3 做结构合成
4. **中间 JSON 为单一数据契约**：Layer 1 JSON + Layer 2 JSON → Layer 3 JSON，均结构化可调试
5. **顶层顺序完全数据驱动**，不使用固定章节名模板

## Layer 1 · 格式样例抽取

复用现有 [bid_format.py](../../../src/extractor/bid_format.py) 的第一次 LLM 调用逻辑和 [config/prompts/bid_format.txt](../../../config/prompts/bid_format.txt) 提示词。职责：把招标文件里直接给出的格式样例（投标函模板、报价表格式、授权委托书格式等）抽出来。

### 输出

```json
{
  "has_any_template": true,
  "templates": [
    {
      "title": "投标函",
      "type": "text",
      "content": "致：[采购人名称]\n我方响应贵方...[投标函全文模板]"
    },
    {
      "title": "开标一览表",
      "type": "standard_table",
      "columns": ["项目名称", "投标报价（万元）", "服务期限", "备注"],
      "rows": [["[待填写]", "[待填写]", "[待填写]", ""]]
    }
  ]
}
```

- `has_any_template: false` 时 `templates` 为空数组
- `title` 将作为 Layer 3 目录节点匹配的锚点
- 多模板按招标文件中出现顺序保留

### 与 Layer 2 的关系

- 并行执行，都从 `tagged_paragraphs` 输入（可并发调用 LLM 以减少总耗时）
- Layer 1 只关心"样例是否存在及样例内容"，不关心章节结构
- Layer 2 的 `format_templates` 字段仍保留，用于兜底识别"招标方提到了但 Layer 1 没成功抽出样例"的模板（Layer 3 合成时以 Layer 1 实际抽出的样例为权威来源）

## Layer 2 · 骨架信号抽取

### 职责

从招标原文中抽出 5 类结构信号，组装成一份结构化 JSON 供 Layer 3 使用。

### 候选段落过滤

- 用 `filter_paragraphs_by_score(tagged_paragraphs, "bid_format_skeleton", ...)` 做关键词打分 + 向量语义补漏
- 必须传 `module_embedding` 开启向量兜底
- `min_count` 设 50~80，宽召回，宁错勿漏
- 关键词配置**独立成文件** `config/bid_format_keywords.json`（不并入 `anbiao_default_rules.json`，后者是安标模块专用），按类别分组：

| 类别 | 示例关键词 |
|---|---|
| 组成条款 | `投标文件组成`、`投标文件构成`、`投标文件应包括`、`投标文件须包含`、`投标文件由.*组成` |
| 固定章节名 | `投标函`、`法定代表人身份证明`、`授权委托书`、`开标一览表`、`报价一览表`、`投标保证金`、`项目经理简历表`、`服务团队情况` |
| 响应/偏离表 | `响应表`、`响应一览表`、`应答表`、`偏离表`、`偏离说明`、`技术偏离`、`商务偏离` |
| 提交动词 | `应提供`、`应提交`、`须提供`、`需提供`、`附以下`、`提交下列`、`提交以下` |
| 格式样式 | `格式`、`样式`、`模板`、`样例`、`样表`、`附件格式` |
| 评分因素 | `评分因素`、`评审因素`、`评分标准`、`评审标准`、`分值`、`权重` |
| 材料类 | `资质`、`证书`、`证明文件`、`资格条件`、`业绩`、`财务报告`、`审计报告`、`承诺函`、`声明函` |
| 时间枚举触发 | `近三年`、`近五年`、`近.*年度`、`年度财务`、`分年度` |
| 枚举触发 | `包括但不限于`、`以下各项`、`下列文件`、`分别为`、`如下所示` |

关键词列表为"宽召回"草稿，上线后根据漏召实际情况在配置文件中迭代。

### 分批策略

**按段落数分批，辅以 token 安全上限**。

- `BATCH_SIZE = 40` 段/批（后续实测调）
- `TOKEN_SAFETY_CAP = 100_000`（防单批含大表格意外超窗）
- 新增助手函数 `batch_by_count()`，不复用 `batch_paragraphs()`

理由：Layer 2 过滤后段落数有限，按段落数切分更均衡、更可控、便于调参；token 上限仅作保底。

### Prompt 与输出 schema

新建 [config/prompts/bid_format_skeleton.txt](../../../config/prompts/bid_format_skeleton.txt)，要求每批输出：

```json
{
  "composition_clause": {
    "found": true,
    "items": [
      {"order": 1, "title": "商务文件", "note": "包括投标函、报价表..."}
    ]
  },
  "scoring_factors": [
    {
      "category": "技术",
      "title": "应对灾害防御能力",
      "weight": "10分",
      "sub_items": [
        {
          "title": "业务连续性计划",
          "sub_items": [
            {"title": "国内两个个人化分中心管理", "sub_items": []}
          ]
        },
        {"title": "疫情期间稳定供货方案", "sub_items": []}
      ]
    }
  ],
  "material_enumerations": [
    {"parent": "资质证书", "parent_context": "资格证明文件",
     "items": ["集成电路卡注册证书", "银联标识产品企业资质认证证书"],
     "source_para": 234}
  ],
  "format_templates": [
    {"title": "投标函", "has_sample": true},
    {"title": "授权委托书", "has_sample": false}
  ],
  "dynamic_nodes": [
    {"anchor": "类似项目业绩", "expansion_type": "customer_list",
     "expansion_hint": "按客户/项目逐项展开"},
    {"anchor": "财务报告", "expansion_type": "year_range",
     "expansion_hint": "按年度（近三年）逐年展开",
     "expansion_count_hint": 3}
  ]
}
```

五个字段语义：

- `composition_clause`：招标方明文规定的投标文件顶层构成（若招标文件有写）
- `scoring_factors`：评分办法中的评审因素，按 `category`（技术/商务）分类。`sub_items` 为**递归嵌套结构**（每项含 `title` + `sub_items` 子列表），支持三级及以上细分（覆盖样本 2 的 12.x → 12.x.y 三级场景）
- `material_enumerations`：资料枚举清单，保留每个具体条目。`parent` 为直接挂接锚点（如"资质证书"），`parent_context` 为其所属上级章节上下文（如"资格证明文件"），用于 Layer 3 在多个同名 parent 存在时消歧
- `format_templates`：招标文件是否给出模板样表的清单，`has_sample=true` 的条目 Layer 4 将嵌入样表
- `dynamic_nodes`：需投标人按实际数据展开的节点提示
  - `expansion_type`：`year_range`（按年度）/ `customer_list`（按客户/项目）/ `item_list`（按具体项目）/ `other`
  - `expansion_count_hint`：已知展开数量时填入（如"近三年"→3），未知填 null
  - `expansion_hint`：人类可读的展开说明

**不抽取评分细则文本**（如"提供 XX 得 N 分"），只抽结构；细则对目录生成无直接用。

**不做去重**：重复条目原样保留（同一材料招标方要求在多章节出现的情况真实存在，如样本 1 的"响应分项报价表"同时出现在三和五）。

### 结果合并

多批返回的 JSON 按字段拼接（列表 append），形成单份 Layer 2 JSON。

## Layer 3 · 目录合成

### 职责

单次 LLM 调用，输入 Layer 1 + Layer 2 的合并 JSON，输出多级目录树 JSON。

Layer 1 的样例内容不直接塞进 prompt（避免占用 token），而是传入样例的 `title` 列表即可；目录树中 `has_sample=true` 的节点由代码后处理把 Layer 1 抽出的样例内容绑定到节点上，Layer 4 渲染时直接嵌入。

### 输出 schema

```json
{
  "title": "投标文件",
  "nodes": [
    {
      "title": "投标函",
      "level": 1,
      "source": "format_template",
      "has_sample": true,
      "dynamic": false,
      "children": []
    },
    {
      "title": "投标人资格证明文件",
      "level": 1,
      "source": "composition_clause",
      "children": [
        {
          "title": "资质证书",
          "level": 2,
          "children": [
            {"title": "集成电路卡注册证书", "level": 3},
            {"title": "银联标识产品企业资质认证证书", "level": 3}
          ]
        },
        {
          "title": "近三年财务报告",
          "level": 2,
          "dynamic": true,
          "dynamic_hint": "按年度（近三年）逐年展开",
          "children": []
        }
      ]
    }
  ]
}
```

**不在 LLM 输出中包含编号**，编号由代码后处理生成（见下）。

### Prompt 指令核心原则

新建 [config/prompts/bid_format_compose.txt](../../../config/prompts/bid_format_compose.txt)，输入包含 Layer 1 的 `templates` title 列表 + Layer 2 完整 JSON，要求：

1. **顶层顺序优先级**：`composition_clause.items` 存在时按其顺序；若缺失，按"格式样表类 → 评审得分类（商务/技术）→ 补充材料类"的结构性原则拼接，不使用固定章节名
2. **技术/商务部分二级目录**：从 `scoring_factors` 对应 `category` 的因素逐条生成
3. **资料枚举挂接**：`material_enumerations.parent` 作为挂接锚点匹配上级节点；匹配不到时作为所属顶层章节的新子节点
4. **格式样表独立成节**：Layer 1 `templates` 每一条都独立成节、标记 `has_sample=true`；Layer 2 `format_templates` 中 Layer 1 未覆盖的条目也独立成节但 `has_sample=false`
5. **动态节点标记**：`dynamic_nodes.anchor` 匹配到对应节点后打 `dynamic=true` + `dynamic_hint`
6. **保留重复**：同一条目若由多个信号或多个章节要求，按位置各自出现，不做去重

### 样例内容绑定（代码后处理）

LLM 输出的目录树中 `has_sample=true` 节点由代码按 `title` 从 Layer 1 `templates` 数组查找对应样例内容，绑定到节点的 `sample_content` 字段，供 Layer 4 渲染使用。

**匹配策略**（容忍 LLM 对 title 的同义改写，如"投标函"→"投标函格式"）：

1. 精确匹配：归一化（去空格、去"格式/模板/样表/表"等后缀词）后相等
2. 子串匹配：Layer 1 title 的归一化形式是目录节点 title 归一化形式的子串，或反之
3. 编辑距离兜底：阈值 ≤2（避免过度泛化）
4. 全部失败：保留 `has_sample=true` 标记但 `sample_content=None`，Layer 4 渲染时**不嵌入样例**、照常输出空段落，日志 warn

### 异常与兜底

- **Layer 1 失败/超时**：记录 warn，视作 `has_any_template=false` 继续执行
- **Layer 2 失败**：整体失败，返回 `None`，调用方按现有模块失败路径处理
- **LLM 输出 `source` 为未知枚举值**：代码按非关键元数据处理（不影响渲染），日志 warn
- **LLM 输出 `dynamic_nodes.anchor` 在目录树中匹配不到**：代码忽略该条，日志 warn（不追加孤立节点）
- **三重空信号**（Layer 1 无样例 + Layer 2 `composition_clause.found=false` + `scoring_factors`/`material_enumerations` 均为空）：
  - 视为抽取失败，整体返回 `None`
  - 不生成"空白兜底骨架 docx"以避免误导用户（与本设计"不使用固定模板"原则一致）
  - 调用方收到 None 后展示错误提示，引导用户手工确认招标文件内容

### 编号后处理

纯代码生成，深度优先遍历 `nodes` 树，按兄弟节点出现顺序赋编号：

- Level 1：中文数字 + 顿号，支持 1~20
  - 映射表：`一、二、三、四、五、六、七、八、九、十、十一、十二、十三、十四、十五、十六、十七、十八、十九、二十`
  - 超过 20 的极端情况（罕见）降级为阿拉伯数字加顿号（如 `21、`）
- Level 2：`{父级阿拉伯序号}.{本级序号}`，如 `6.1`、`6.2`
  - 父级编号从 Level 1 的中文映射回阿拉伯（"十三" → 13）
- Level 3：`{L2 编号}.{序号}`，如 `6.2.1`、`6.2.2`
- **重复标题不加后缀**：按样本 1 的实际情况，"三、响应分项报价表"和"五、响应分项报价表"即使标题重复、编号不同也直接并列，不做区分后缀（招标方原样要求如此）

## Layer 4 · docx 渲染

### 基本规则

- Level 1 → Word `Heading 1`，前缀"一、"
- Level 2 → Word `Heading 2`，前缀"1.1"
- Level 3 → Word `Heading 3`，前缀"1.1.1"
- 每个叶子节点下留一个空段落作为正文填写空间
- `has_sample=true` 的节点：节点正文位置嵌入 Layer 1 抽取并由 Layer 3 后处理绑定的 `sample_content`（文本原样渲染，`standard_table` 类型渲染为 Word 表格）
- `has_sample=false` 或非 format 来源节点：仅标题 + 空段落

### 动态节点提示

`dynamic=true` 的节点，标题下插入一段红色斜体占位段落，例如：

```
[⚠️ 此节需按实际业绩逐项展开为 N 个子标题，例如 "9.1 客户A" / "9.2 客户B"]
```

- 颜色 `FF0000`，斜体
- 内容模板：`[⚠️ 此节需{dynamic_hint}，例如 "{编号}.1 示例一" / "{编号}.2 示例二"]`
- 人工写完该节后整段删除

### 实现

沿用项目现有 `python-docx` 依赖（同 [src/reviewer/docx_annotator.py](../../../src/reviewer/docx_annotator.py)）。不新增依赖。

## 模块结构与文件变更

### 新增文件

- `src/extractor/bid_outline.py`（新实现，内部细分四层的助手函数）
- `config/prompts/bid_format_skeleton.txt`（Layer 2 prompt）
- `config/prompts/bid_format_compose.txt`（Layer 3 prompt）
- `config/bid_format_keywords.json`（独立关键词配置，不并入 anbiao_default_rules.json）
- `src/extractor/tests/test_bid_outline.py`（新测试文件）

### 修改文件

- [src/extractor/extractor.py](../../../src/extractor/extractor.py)：将 `bid_format` 的实现指向新 `bid_outline.extract_bid_outline`
- [server/app/tasks/review_task.py](../../../server/app/tasks/review_task.py) 及 [server/app/services/review_preview.py](../../../server/app/services/review_preview.py)：如引用 `extract_bid_format`，同步改为 `extract_bid_outline`（module key `bid_format` 不变）
- [src/extractor/scoring.py](../../../src/extractor/scoring.py)（如需）：让 `filter_paragraphs_by_score` 从独立关键词配置加载 `bid_format_skeleton` 组
- [web/src/components/ReviewStage.vue](../../../web/src/components/ReviewStage.vue)：显示标签改为"投标文件大纲"
- [web/src/components/ReviewPreviewStage.vue](../../../web/src/components/ReviewPreviewStage.vue) 和 [web/src/components/PreviewStage.vue](../../../web/src/components/PreviewStage.vue)：对 `bid_format` module 条件分支跳过人工标注入口

### 删除文件

- [config/prompts/bid_format_fallback.txt](../../../config/prompts/bid_format_fallback.txt)
- [src/extractor/bid_format.py](../../../src/extractor/bid_format.py) 中的 `_summarize_modules` 函数
- [src/extractor/tests/test_bid_format.py](../../../src/extractor/tests/test_bid_format.py)（如存在旧测试）

### 保留文件

- [config/prompts/bid_format.txt](../../../config/prompts/bid_format.txt)（Layer 1 短路路径仍用）

### 接口契约

- 对外 module key 保持 `bid_format`，前端、数据库、路由不需要改 key
- 新入口函数 `extract_bid_outline(tagged_paragraphs, settings, embeddings_map, module_embedding, ...)`，签名与原 `extract_bid_format` 兼容（modules_context 参数不再使用，可保留以兼容调用方但内部忽略）

## 测试策略

### 单元测试

- `_extract_skeleton_signals`：给定典型段落输入，验证 5 类字段的结构正确
- `_compose_outline_tree`：对已知 Layer 2 JSON 输入验证树形合成
- `_generate_numbering`：对 3 级树验证编号生成正确（中文数字 → 阿拉伯 → 三级）
- `_render_docx`：验证 `dynamic=true` 节点正确插入红字占位，`has_sample=true` 节点正确嵌入样表

### 集成测试

用两份真实招标文件样本跑端到端流程，生成 docx 作为烟雾测试验证流程跑通。不设覆盖率硬指标，产物由人工过审决定是否可用。

## 落地顺序

拆为四个 PR 逐步合入：

1. **PR-1**：后端新模块 + prompts + 关键词配置，保留旧 `extract_bid_format` 为回退入口
2. **PR-2**：切换主入口到 `extract_bid_outline`，用两份真实样本验证
3. **PR-3**：前端移除 `bid_format` 的人工标注 UI 入口 + 改显示标签
4. **PR-4**：清理旧 fallback prompt 和 `_summarize_modules` 死代码

## 开放问题

- 关键词表为草稿，实际漏召情况需在 PR-2 阶段用真实样本复核调整
- `BATCH_SIZE = 40` 为拍脑袋值，需在 PR-2 阶段用真实样本确认
- Layer 3 prompt 的合成规则可能需要根据真实样本的输出质量迭代调整
