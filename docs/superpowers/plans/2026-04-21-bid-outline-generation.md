# 投标文件大纲生成 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用四层流水线（样例抽取 + 骨架信号抽取 + 目录合成 + docx 渲染）替换现有 `src/extractor/bid_format.py`，动态生成契合本份招标文件的多级投标文件大纲 docx。

**Architecture:** Layer 1（复用现有 bid_format.txt prompt）与 Layer 2（新增骨架信号抽取）并行执行，结果合流输入 Layer 3（单次 LLM 合成目录树），由 Layer 4 纯代码渲染为 docx。模块对外 key `bid_format` 保持不变；旧 fallback 路径清除；前端跳过人工标注入口。

**Tech Stack:** Python 3.11+, `openai` client (through `src.extractor.base.call_qwen`), `python-docx`, `concurrent.futures.ThreadPoolExecutor`, pytest, Vue 3 (前端最小改动)

**相关文档：** 设计 spec 位于 `docs/superpowers/specs/2026-04-21-bid-outline-generation-design.md`，实现前必读。

**重要偏离 spec 的决定：** spec 提到 `config/bid_format_keywords.json` 独立文件。实际实现改为在现有 `config/keyword_scores.yaml` 中**新增 `bid_format_skeleton` 模块键**，与 `bid_format` / `checklist` 等并列。理由：`keyword_scores.yaml` 是所有 extractor 共用的关键词得分配置，与 spec 要避开的 `anbiao_default_rules.json`（安标专用）是两回事；单独一个 json 会破坏现有 `load_keyword_scores()` 一处加载的约定。

---

## Chunk 1: Layer 2 骨架信号抽取（关键词、分批、抽取函数）

### Task 1: 在 keyword_scores.yaml 中加入 bid_format_skeleton 配置

**Files:**
- Modify: `config/keyword_scores.yaml`（追加 bid_format_skeleton 块）

**职责：** 为 Layer 2 过滤配置关键词得分表，覆盖设计 spec 中列出的 9 类关键词。

- [ ] **Step 1: 打开 config/keyword_scores.yaml，查看现有 bid_format / checklist 块的格式**

  已知文件 120 行附近是 `bid_format:` 块，134 行附近是 `checklist:` 块。读出两个块作为格式参考（字段：threshold / section_keywords / text_keywords / tag_keywords，每个 keyword bucket 下分 high / medium / low 三档）。

- [ ] **Step 2: 在 checklist 块之后追加 bid_format_skeleton 块**

  内容如下（照 spec 9 类关键词分配到 text_keywords 的三档）：

  ```yaml
  bid_format_skeleton:
    threshold: 3
    section_keywords:
      high:
        - 投标文件组成
        - 投标文件构成
        - 投标文件格式
        - 评分办法
        - 评审办法
        - 投标文件编制
      medium:
        - 资格要求
        - 投标文件
        - 资料清单
    text_keywords:
      high:
        - 投标文件组成
        - 投标文件构成
        - 投标文件应包括
        - 投标文件须包含
        - 投标文件由
        - 评分因素
        - 评审因素
        - 投标函
        - 授权委托书
        - 法定代表人身份证明
        - 开标一览表
        - 报价一览表
        - 偏离表
        - 偏离说明
      medium:
        - 应提供
        - 应提交
        - 须提供
        - 需提供
        - 附以下
        - 提交下列
        - 提交以下
        - 评分标准
        - 评审标准
        - 分值
        - 权重
        - 资质
        - 证书
        - 证明文件
        - 资格条件
        - 业绩
        - 财务报告
        - 审计报告
        - 承诺函
        - 声明函
        - 响应表
        - 响应一览表
        - 应答表
        - 技术偏离
        - 商务偏离
        - 项目经理简历
        - 服务团队
        - 投标保证金
      low:
        - 格式
        - 样式
        - 模板
        - 样例
        - 样表
        - 附件格式
        - 近三年
        - 近五年
        - 年度财务
        - 分年度
        - 包括但不限于
        - 以下各项
        - 下列文件
        - 分别为
        - 如下所示
    tag_keywords:
      medium:
        - 投标文件组成
        - 评分办法
  ```

- [ ] **Step 3: 验证 yaml 合法**

  运行：
  ```bash
  python -c "import yaml; yaml.safe_load(open('config/keyword_scores.yaml', encoding='utf-8'))"
  ```
  Expected: 无输出（yaml 合法）

- [ ] **Step 4: 验证 load_keyword_scores 能加载新键**

  运行：
  ```bash
  python -c "from src.config import load_keyword_scores; print('bid_format_skeleton' in load_keyword_scores())"
  ```
  Expected: `True`

- [ ] **Step 5: Commit**

  ```bash
  git add config/keyword_scores.yaml
  git commit -m "feat(bid-outline): add bid_format_skeleton keyword scores for Layer 2"
  ```

### Task 2: 编写 Layer 2 prompt（bid_format_skeleton.txt）

**Files:**
- Create: `config/prompts/bid_format_skeleton.txt`

**职责：** 定义 Layer 2 的 LLM 提取指令，输出 spec 第 143~199 行的 5 字段 JSON schema。

- [ ] **Step 1: 创建 config/prompts/bid_format_skeleton.txt**

  内容（完整）：

  ````text
  你是招标文件结构分析专家。请从以下招标文件段落中抽取 5 类"结构信号"，用于下游生成投标文件目录。

  ## 隐私保护规则
  投标文件中的个人隐私数据以占位符表示，保持原样输出即可。

  ## 抽取目标（5 类字段）

  ### ① composition_clause
  招标方是否明文规定了"投标文件由以下部分组成"。只要找到一句类似表述，就填 found=true 并按顺序列出 items；找不到则 found=false 且 items 为空数组。

  ### ② scoring_factors
  评分办法 / 评审办法中列出的得分因素（按 category=技术 / 商务 分类）。每条因素可以有 sub_items 递归嵌套，**没有子项时 sub_items 为空数组**。抽取因素名、权重/分值（若原文给出），不抽取评分细则文本（不要抽"提供 X 得 N 分"这种评分规则）。

  ### ③ material_enumerations
  招标方在条款中列出的具体材料清单，**保留每个具体条目**（不要聚合成大类）。典型模式：
  - "应提供以下资质证书：A、B、C..." → parent="资质证书", items=["A","B","C"]
  - "提供近三年财务报告" → 交给 dynamic_nodes 处理，不要放在 material_enumerations
  - parent_context 是 parent 的上级章节（如"资格证明文件"），用于消歧

  ### ④ format_templates
  招标文件提到的所有模板/样表名（投标函、授权委托书、开标一览表等）。has_sample=true 表示招标文件正文附有样例内容；has_sample=false 表示只点了名但没给样本。

  ### ⑤ dynamic_nodes
  需要投标人按**实际数据**展开的节点。关键识别模式：
  - "近 N 年..." → expansion_type=year_range, expansion_count_hint=N
  - "类似项目业绩按客户 / 按项目逐项列举" → expansion_type=customer_list
  - "以下各项 / 分别列明" 且数量由投标人决定 → expansion_type=item_list
  - 其他 → expansion_type=other

  ## 严格输出 JSON（顶层必须是一个对象，五个字段均为数组/对象）

  ```json
  {
    "composition_clause": {
      "found": true,
      "items": [
        {"order": 1, "title": "商务文件", "note": "投标函、报价表..."}
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
          }
        ]
      }
    ],
    "material_enumerations": [
      {
        "parent": "资质证书",
        "parent_context": "资格证明文件",
        "items": ["集成电路卡注册证书", "银联标识产品企业资质认证证书"],
        "source_para": 234
      }
    ],
    "format_templates": [
      {"title": "投标函", "has_sample": true},
      {"title": "授权委托书", "has_sample": false}
    ],
    "dynamic_nodes": [
      {
        "anchor": "类似项目业绩",
        "expansion_type": "customer_list",
        "expansion_hint": "按客户/项目逐项展开",
        "expansion_count_hint": null
      },
      {
        "anchor": "近三年财务报告",
        "expansion_type": "year_range",
        "expansion_hint": "按年度（近三年）逐年展开",
        "expansion_count_hint": 3
      }
    ]
  }
  ```

  ## 规则与注意事项

  1. **只抽结构信号**，不抽条款正文。例如不要抽"质量保证金 10%"这种合同条款数值
  2. **不做去重**：同一条目在多个段落出现就出现多次
  3. **五个顶层字段都必须存在**：没抽到的字段给空数组 / found=false
  4. 所有字符串使用双引号，JSON 合法可解析
  5. source_para 为段落 index（原文标注的 [N]），有就填，没有可省略字段
  6. **不要**在 JSON 外添加任何说明文字或 Markdown 代码块标记
  ````

- [ ] **Step 2: Commit**

  ```bash
  git add config/prompts/bid_format_skeleton.txt
  git commit -m "feat(bid-outline): add Layer 2 skeleton signal extraction prompt"
  ```

### Task 3: 新增按段落数分批助手 batch_by_count

**Files:**
- Modify: `src/extractor/base.py`（在 `batch_paragraphs` 函数后追加）
- Create: `src/extractor/tests/test_batch_by_count.py`

**职责：** Layer 2 不能复用 token 分批（段落大小差异会导致分批不均），需新增按段落数分批的工具，带 token 安全保底。

- [ ] **Step 1: 写失败测试**

  创建 `src/extractor/tests/test_batch_by_count.py`：

  ```python
  from src.models import TaggedParagraph
  from src.extractor.base import batch_by_count


  def _mk(index: int, text: str = "一段普通段落") -> TaggedParagraph:
      return TaggedParagraph(index=index, text=text, section_title=None,
                             table_data=None, tags=[])


  def test_batch_by_count_basic():
      paras = [_mk(i) for i in range(100)]
      batches = batch_by_count(paras, batch_size=40, token_safety_cap=100_000)
      assert len(batches) == 3
      assert [len(b) for b in batches] == [40, 40, 20]


  def test_batch_by_count_token_safety_splits_early():
      # 一个超长段落 + 若干普通段落；超长段占批后应立即切
      long_text = "x" * 250_000  # 超过 safety cap
      paras = [_mk(0, long_text)] + [_mk(i) for i in range(1, 10)]
      batches = batch_by_count(paras, batch_size=40, token_safety_cap=100_000)
      # 第一批至多含那一条超长段（或之后立即切）；断言不会把 10 个全挤到一批
      assert len(batches) >= 2


  def test_batch_by_count_empty_input():
      assert batch_by_count([], batch_size=40) == []
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_batch_by_count.py -v
  ```
  Expected: `ImportError: cannot import name 'batch_by_count' from 'src.extractor.base'`

- [ ] **Step 3: 在 base.py 的 batch_paragraphs 之后追加实现**

  ```python
  def batch_by_count(
      paragraphs: list[TaggedParagraph],
      batch_size: int = 40,
      token_safety_cap: int = 100_000,
  ) -> list[list[TaggedParagraph]]:
      """按段落数切批，token 超过安全上限时提前切。

      与 batch_paragraphs 区别：主轴是段落数，token 仅做保底。
      适用于已经被关键词过滤后的场景（段落数本身不大）。
      """
      if not paragraphs:
          return []

      batches: list[list[TaggedParagraph]] = []
      current: list[TaggedParagraph] = []
      current_tokens = 0

      for para in paragraphs:
          para_tokens = estimate_tokens(para.text)
          hits_count = len(current) >= batch_size
          hits_token = current and current_tokens + para_tokens > token_safety_cap

          if hits_count or hits_token:
              batches.append(current)
              current = [para]
              current_tokens = para_tokens
          else:
              current.append(para)
              current_tokens += para_tokens

      if current:
          batches.append(current)
      return batches
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_batch_by_count.py -v
  ```
  Expected: 三个测试全部 PASS

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/base.py src/extractor/tests/test_batch_by_count.py
  git commit -m "feat(bid-outline): add batch_by_count helper for paragraph-count batching"
  ```

### Task 4: 实现 Layer 2 骨架信号抽取主函数

**Files:**
- Create: `src/extractor/bid_outline.py`（首次创建，先写 Layer 2 部分；后续任务在此文件继续扩展）
- Create/Modify: `src/extractor/tests/test_bid_outline.py`

**职责：** 新建 `bid_outline.py`，实现 `_extract_skeleton_signals(tagged_paragraphs, settings, embeddings_map, module_embedding) -> dict | None`，含关键词过滤、分批、多批结果合并。

- [ ] **Step 1: 写失败测试（测骨架合并逻辑，不调真 LLM）**

  创建 `src/extractor/tests/test_bid_outline.py`：

  ```python
  from unittest.mock import patch
  from src.extractor.bid_outline import _merge_skeleton_batches


  def test_merge_skeleton_batches_concatenates_lists():
      b1 = {
          "composition_clause": {"found": True, "items": [{"order": 1, "title": "商务文件"}]},
          "scoring_factors": [{"category": "技术", "title": "能力A", "sub_items": []}],
          "material_enumerations": [{"parent": "资质", "items": ["A"]}],
          "format_templates": [{"title": "投标函", "has_sample": True}],
          "dynamic_nodes": [],
      }
      b2 = {
          "composition_clause": {"found": False, "items": []},
          "scoring_factors": [{"category": "商务", "title": "能力B", "sub_items": []}],
          "material_enumerations": [{"parent": "证明", "items": ["B"]}],
          "format_templates": [{"title": "授权书", "has_sample": False}],
          "dynamic_nodes": [{"anchor": "业绩", "expansion_type": "customer_list",
                              "expansion_hint": "按客户展开"}],
      }
      merged = _merge_skeleton_batches([b1, b2])
      # composition_clause：任一批次 found=True 就保留其 items
      assert merged["composition_clause"]["found"] is True
      assert merged["composition_clause"]["items"][0]["title"] == "商务文件"
      assert len(merged["scoring_factors"]) == 2
      assert len(merged["material_enumerations"]) == 2
      assert len(merged["format_templates"]) == 2
      assert len(merged["dynamic_nodes"]) == 1


  def test_merge_skeleton_batches_all_empty():
      merged = _merge_skeleton_batches([])
      assert merged["composition_clause"]["found"] is False
      assert merged["composition_clause"]["items"] == []
      assert merged["scoring_factors"] == []
      assert merged["material_enumerations"] == []
      assert merged["format_templates"] == []
      assert merged["dynamic_nodes"] == []


  def test_merge_skeleton_batches_ignores_none_entries():
      b1 = {
          "composition_clause": {"found": True, "items": [{"order": 1, "title": "X"}]},
          "scoring_factors": [], "material_enumerations": [],
          "format_templates": [], "dynamic_nodes": [],
      }
      merged = _merge_skeleton_batches([None, b1, None])
      assert merged["composition_clause"]["found"] is True
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```
  Expected: `ModuleNotFoundError: No module named 'src.extractor.bid_outline'`

- [ ] **Step 3: 创建 src/extractor/bid_outline.py 骨架 + _merge_skeleton_batches + _extract_skeleton_signals**

  ```python
  """bid_outline: 投标文件大纲生成模块（四层流水线）

  Layer 1: 格式样例抽取（沿用 bid_format.txt prompt）
  Layer 2: 骨架信号抽取（本模块新增）
  Layer 3: 目录合成
  Layer 4: docx 渲染
  """
  import logging
  from pathlib import Path

  from src.models import TaggedParagraph
  from src.extractor.base import (
      load_prompt_template,
      build_messages,
      build_input_text,
      call_qwen,
      batch_by_count,
  )
  from src.extractor.scoring import filter_paragraphs_by_score

  logger = logging.getLogger(__name__)

  _CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
  SKELETON_PROMPT_PATH = _CONFIG_DIR / "prompts" / "bid_format_skeleton.txt"

  BATCH_SIZE = 40
  TOKEN_SAFETY_CAP = 100_000
  MIN_FILTER_COUNT = 50


  _EMPTY_SKELETON = {
      "composition_clause": {"found": False, "items": []},
      "scoring_factors": [],
      "material_enumerations": [],
      "format_templates": [],
      "dynamic_nodes": [],
  }


  def _merge_skeleton_batches(batch_results: list[dict | None]) -> dict:
      """合并多批 Layer 2 输出为单份 JSON。

      - composition_clause：任一批 found=True 保留其 items（通常招标方只会写一处）
      - 其余 4 类：列表拼接，不做去重
      """
      merged = {
          "composition_clause": {"found": False, "items": []},
          "scoring_factors": [],
          "material_enumerations": [],
          "format_templates": [],
          "dynamic_nodes": [],
      }
      for b in batch_results:
          if not isinstance(b, dict):
              continue
          cc = b.get("composition_clause") or {}
          if cc.get("found") and not merged["composition_clause"]["found"]:
              merged["composition_clause"] = {
                  "found": True,
                  "items": list(cc.get("items", [])),
              }
          for k in ("scoring_factors", "material_enumerations",
                    "format_templates", "dynamic_nodes"):
              v = b.get(k)
              if isinstance(v, list):
                  merged[k].extend(v)
      return merged


  def _extract_skeleton_signals(
      tagged_paragraphs: list[TaggedParagraph],
      settings: dict | None = None,
      embeddings_map: dict[int, list[float]] | None = None,
      module_embedding: list[float] | None = None,
  ) -> dict | None:
      """Layer 2：关键词过滤 → 分批 → LLM 抽 5 类信号 → 合并。"""
      filtered, score_map = filter_paragraphs_by_score(
          tagged_paragraphs, "bid_format_skeleton",
          embeddings_map=embeddings_map,
          module_embedding=module_embedding,
          min_count=MIN_FILTER_COUNT,
      )
      if not filtered:
          logger.warning("bid_outline.layer2: 未筛选到相关段落")
          return dict(_EMPTY_SKELETON)  # 返回空骨架而非 None，交给主入口判断三重空信号

      logger.info("bid_outline.layer2: 筛选到 %d 个相关段落 (共 %d)",
                  len(filtered), len(tagged_paragraphs))

      system_prompt = load_prompt_template(str(SKELETON_PROMPT_PATH))
      batches = batch_by_count(filtered, batch_size=BATCH_SIZE,
                               token_safety_cap=TOKEN_SAFETY_CAP)

      batch_results: list[dict | None] = []
      for i, batch in enumerate(batches):
          batch_text = build_input_text(batch, score_map)
          messages = build_messages(system=system_prompt, user=batch_text)
          logger.debug("bid_outline.layer2: 调用第 %d/%d 批 (段落数=%d)",
                       i + 1, len(batches), len(batch))
          result = call_qwen(messages, settings)
          batch_results.append(result if isinstance(result, dict) else None)

      if all(r is None for r in batch_results):
          logger.error("bid_outline.layer2: 所有批次 LLM 返回均失败")
          return None

      return _merge_skeleton_batches(batch_results)
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```
  Expected: 三个测试全部 PASS

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement Layer 2 skeleton signal extraction"
  ```

---

## Chunk 2: Layer 3 目录合成（prompt、合成函数、样例绑定、编号）

### Task 5: 编写 Layer 3 prompt（bid_format_compose.txt）

**Files:**
- Create: `config/prompts/bid_format_compose.txt`

**职责：** 定义 Layer 3 目录合成指令：输入 Layer 1 template title 列表 + Layer 2 完整 JSON，输出多级目录树 JSON。

- [ ] **Step 1: 创建 config/prompts/bid_format_compose.txt**

  ````text
  你是投标文件目录架构师。请把下面提供的"格式样例 title 清单"和"骨架信号 JSON"合成为一个完整的多级投标文件目录树。

  ## 输入说明

  输入分两部分：
  1. **layer1_template_titles**：招标方已提供格式样例的条目 title 数组（如 ["投标函","开标一览表"]）
  2. **layer2_skeleton**：5 类结构信号，见下方 schema

  ## 输出 JSON schema（严格遵守）

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
        "dynamic_hint": null,
        "children": []
      }
    ]
  }
  ```

  字段约束：
  - `level`：1/2/3，**不要超过 3 级**
  - `source`：枚举 `composition_clause` / `scoring_factor` / `material_enumeration` / `format_template`
  - `has_sample`：布尔。仅当节点 title 能对应到 layer1_template_titles 中的某一条时为 true，否则 false
  - `dynamic`：布尔。仅当节点对应 layer2_skeleton.dynamic_nodes 中的 anchor 时为 true，并填 dynamic_hint 字段
  - `dynamic_hint`：dynamic=true 时填 expansion_hint 原文；否则为 null
  - `children`：子节点数组，叶子节点为空数组
  - **不要**填 number / 编号字段，编号由代码后处理生成

  ## 合成规则（按优先级）

  1. **顶层顺序**
     - 若 `composition_clause.found=true`：严格按 `items[*].order` 顺序生成 level=1 节点
     - 否则：按"格式样表类（layer1 + layer2.format_templates）→ 评审得分类（商务/技术 scoring_factors）→ 补充材料类（material_enumerations）"结构性原则生成
     - **不要**使用固定章节名模板

  2. **格式样表独立成节**
     - layer1_template_titles 每一条都独立成 level=1 节点，has_sample=true
     - layer2.format_templates 中未被 layer1 覆盖的条目也独立成 level=1 节点，has_sample=false
     - 不被其它信号吞并

  3. **技术/商务部分的 level 2/3**
     - 若某个 level=1 节点（如"技术部分"/"商务部分"）能对应到 scoring_factors 的某个 category，则把该 category 下的 factors 展开为 level=2 子节点
     - 若 factor 含 sub_items，按嵌套层级展开到 level=3（再深的层级合并到 level=3 的 title 中，不再细分）

  4. **资料枚举挂接**
     - 对每条 material_enumeration：
       * 优先按 parent 字符串在已生成的 level 1/2 节点中匹配（子串或归一化匹配）
       * 匹配到：items 展开为该节点下的 level 2 或 3 子节点
       * 匹配不到：按 parent_context 作为 level 1（如"资格证明文件"），parent 作为 level 2，items 作为 level 3
       * parent 可能出现多次：各自按所属 parent_context 独立挂接，不要合并

  5. **动态节点标记**
     - 对 dynamic_nodes 每一条，在目录树中查找 anchor 能匹配到的节点（子串匹配），匹配到则：
       * dynamic=true
       * dynamic_hint=expansion_hint 原文
     - 匹配不到：忽略该条，不追加孤立节点

  6. **保留重复**
     - 同一 title 若由多个信号或多个章节要求，按位置各自出现，**不做去重**

  ## 注意
  - 输出合法 JSON，字符串使用双引号
  - **不要**在 JSON 外添加任何说明或 Markdown 代码块标记
  - **不要**生成 number / 序号
  - level 最多到 3
  ````

- [ ] **Step 2: Commit**

  ```bash
  git add config/prompts/bid_format_compose.txt
  git commit -m "feat(bid-outline): add Layer 3 outline composition prompt"
  ```

### Task 6: 实现 Layer 3 目录合成函数

**Files:**
- Modify: `src/extractor/bid_outline.py`（追加 `_compose_outline_tree`）
- Modify: `src/extractor/tests/test_bid_outline.py`（追加测试）

**职责：** 实现 `_compose_outline_tree(layer1_result, layer2_result, settings) -> dict | None`。输入 Layer 1/2 结果，返回 spec 第 219~254 行的目录树 JSON（未带编号，未绑定样例）。

- [ ] **Step 1: 写失败测试（mock LLM 返回固定 JSON，验证输入组装 + 错误容忍）**

  追加到 `test_bid_outline.py`：

  ```python
  from unittest.mock import patch
  from src.extractor.bid_outline import _compose_outline_tree


  def test_compose_outline_tree_happy_path():
      layer1 = {"has_any_template": True, "templates": [
          {"title": "投标函", "type": "text", "content": "..."}
      ]}
      layer2 = {
          "composition_clause": {"found": True,
                                  "items": [{"order": 1, "title": "投标函"}]},
          "scoring_factors": [], "material_enumerations": [],
          "format_templates": [], "dynamic_nodes": [],
      }
      fake_tree = {
          "title": "投标文件",
          "nodes": [{"title": "投标函", "level": 1,
                     "source": "format_template",
                     "has_sample": True, "dynamic": False,
                     "dynamic_hint": None, "children": []}]
      }
      with patch("src.extractor.bid_outline.call_qwen", return_value=fake_tree):
          result = _compose_outline_tree(layer1, layer2, settings=None)
      assert result == fake_tree


  def test_compose_outline_tree_llm_returns_none():
      with patch("src.extractor.bid_outline.call_qwen", return_value=None):
          result = _compose_outline_tree(
              {"has_any_template": False, "templates": []},
              {"composition_clause": {"found": False, "items": []},
               "scoring_factors": [], "material_enumerations": [],
               "format_templates": [], "dynamic_nodes": []},
              settings=None,
          )
      assert result is None


  def test_compose_outline_tree_llm_returns_malformed():
      # LLM 返回非 dict 或 dict 缺 nodes
      with patch("src.extractor.bid_outline.call_qwen", return_value="not a dict"):
          assert _compose_outline_tree({}, {}, None) is None
      with patch("src.extractor.bid_outline.call_qwen", return_value={"foo": 1}):
          assert _compose_outline_tree({}, {}, None) is None
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```
  Expected: `ImportError: cannot import name '_compose_outline_tree'`

- [ ] **Step 3: 在 bid_outline.py 追加实现**

  ```python
  import json as _json

  COMPOSE_PROMPT_PATH = _CONFIG_DIR / "prompts" / "bid_format_compose.txt"


  def _compose_outline_tree(
      layer1_result: dict | None,
      layer2_result: dict | None,
      settings: dict | None,
  ) -> dict | None:
      """Layer 3：把 Layer 1 题目列表 + Layer 2 结构信号合成多级目录树。

      输出目录树 JSON（未编号，未绑定样例内容）。
      LLM 返回非 dict 或缺 nodes 字段时返回 None。
      """
      template_titles: list[str] = []
      if isinstance(layer1_result, dict) and layer1_result.get("has_any_template"):
          for t in layer1_result.get("templates") or []:
              if isinstance(t, dict) and t.get("title"):
                  template_titles.append(t["title"])

      if not isinstance(layer2_result, dict):
          layer2_result = dict(_EMPTY_SKELETON)

      payload = {
          "layer1_template_titles": template_titles,
          "layer2_skeleton": layer2_result,
      }

      system_prompt = load_prompt_template(str(COMPOSE_PROMPT_PATH))
      user_text = _json.dumps(payload, ensure_ascii=False, indent=2)
      messages = build_messages(system=system_prompt, user=user_text)

      result = call_qwen(messages, settings)
      if not isinstance(result, dict) or "nodes" not in result:
          logger.error("bid_outline.layer3: LLM 返回非法结构: %s", type(result))
          return None
      if "title" not in result:
          result["title"] = "投标文件"
      return result
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```
  Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement Layer 3 outline tree composition"
  ```

### Task 7: 样例内容绑定（模糊匹配）

**Files:**
- Modify: `src/extractor/bid_outline.py`（追加 `_bind_sample_content` + `_normalize_title` + `_edit_distance_le2`）
- Modify: `src/extractor/tests/test_bid_outline.py`

**职责：** 对 Layer 3 输出的目录树，按 spec 第 270~279 行的模糊匹配策略，把 Layer 1 `templates` 的实际样例内容绑定到 `has_sample=true` 节点的 `sample_content` 字段。

- [ ] **Step 1: 写失败测试**

  追加到 `test_bid_outline.py`：

  ```python
  from src.extractor.bid_outline import _bind_sample_content, _normalize_title


  def test_normalize_title_strips_suffix_words_and_spaces():
      assert _normalize_title("投标函 格式") == "投标函"
      assert _normalize_title("  投标函模板  ") == "投标函"
      assert _normalize_title("开标一览表") == "开标一览"
      assert _normalize_title("授权委托书样表") == "授权委托书"


  def test_bind_sample_content_exact_normalized_match():
      tree = {"nodes": [
          {"title": "投标函格式", "level": 1, "has_sample": True, "children": []}
      ]}
      layer1 = {"templates": [
          {"title": "投标函", "type": "text", "content": "TEMPLATE_CONTENT"}
      ]}
      _bind_sample_content(tree, layer1)
      assert tree["nodes"][0]["sample_content"] == {
          "type": "text", "content": "TEMPLATE_CONTENT"
      }


  def test_bind_sample_content_substring_match():
      tree = {"nodes": [
          {"title": "开标报价一览表", "level": 1, "has_sample": True, "children": []}
      ]}
      layer1 = {"templates": [
          {"title": "开标一览表", "type": "standard_table",
           "columns": ["A"], "rows": [["1"]]}
      ]}
      _bind_sample_content(tree, layer1)
      bound = tree["nodes"][0]["sample_content"]
      assert bound["type"] == "standard_table"
      assert bound["columns"] == ["A"]


  def test_bind_sample_content_no_match_leaves_none_and_keeps_has_sample():
      tree = {"nodes": [
          {"title": "完全不相关的标题XYZ", "level": 1, "has_sample": True, "children": []}
      ]}
      layer1 = {"templates": [
          {"title": "投标函", "type": "text", "content": "T"}
      ]}
      _bind_sample_content(tree, layer1)
      assert tree["nodes"][0]["sample_content"] is None
      assert tree["nodes"][0]["has_sample"] is True  # 标记保留


  def test_bind_sample_content_recurses_into_children():
      tree = {"nodes": [
          {"title": "附件", "level": 1, "has_sample": False, "children": [
              {"title": "投标函", "level": 2, "has_sample": True, "children": []}
          ]}
      ]}
      layer1 = {"templates": [
          {"title": "投标函", "type": "text", "content": "T"}
      ]}
      _bind_sample_content(tree, layer1)
      assert tree["nodes"][0]["children"][0]["sample_content"] is not None
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 3: 在 bid_outline.py 追加实现**

  ```python
  import re as _re

  _TITLE_SUFFIX_WORDS = ("格式", "模板", "样表", "样式", "表")


  def _normalize_title(title: str) -> str:
      """归一化：去空格、去尾部'格式/模板/样表/样式/表'等后缀词。"""
      t = (title or "").strip()
      t = _re.sub(r"\s+", "", t)
      # 循环剥离尾部后缀词（可能叠加，如"样表格式"）
      changed = True
      while changed:
          changed = False
          for sw in _TITLE_SUFFIX_WORDS:
              if t.endswith(sw) and len(t) > len(sw):
                  t = t[: -len(sw)]
                  changed = True
      return t


  def _edit_distance_le2(a: str, b: str) -> bool:
      """判定编辑距离 ≤ 2，不实际计算完整距离。"""
      la, lb = len(a), len(b)
      if abs(la - lb) > 2:
          return False
      # 简化：用朴素 DP（字符串长度有限）
      prev = list(range(lb + 1))
      for i in range(1, la + 1):
          cur = [i] + [0] * lb
          for j in range(1, lb + 1):
              cost = 0 if a[i - 1] == b[j - 1] else 1
              cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
          prev = cur
      return prev[lb] <= 2


  def _find_template_for_title(
      node_title: str, templates: list[dict]
  ) -> dict | None:
      """按精确归一化 → 子串 → 编辑距离 ≤2 顺序匹配模板。"""
      if not templates:
          return None
      target = _normalize_title(node_title)
      # 1. 精确归一化匹配
      for t in templates:
          if _normalize_title(t.get("title", "")) == target:
              return t
      # 2. 子串匹配（互相包含）
      for t in templates:
          tnorm = _normalize_title(t.get("title", ""))
          if tnorm and target and (tnorm in target or target in tnorm):
              return t
      # 3. 编辑距离 ≤ 2
      for t in templates:
          tnorm = _normalize_title(t.get("title", ""))
          if tnorm and _edit_distance_le2(tnorm, target):
              return t
      return None


  def _extract_sample_payload(template: dict) -> dict:
      """从 Layer 1 template 剥离出 sample_content 需要的字段。"""
      t = template.get("type", "text")
      if t == "standard_table":
          return {
              "type": "standard_table",
              "columns": template.get("columns", []),
              "rows": template.get("rows", []),
          }
      return {"type": "text", "content": template.get("content", "")}


  def _bind_sample_content(tree: dict, layer1_result: dict | None) -> None:
      """递归为 tree 中 has_sample=true 的节点绑定 sample_content。"""
      templates = []
      if isinstance(layer1_result, dict):
          templates = [t for t in (layer1_result.get("templates") or [])
                       if isinstance(t, dict)]

      def _walk(node: dict) -> None:
          if node.get("has_sample"):
              match = _find_template_for_title(node.get("title", ""), templates)
              if match:
                  node["sample_content"] = _extract_sample_payload(match)
              else:
                  node["sample_content"] = None
                  logger.warning(
                      "bid_outline.bind: has_sample=True 但未匹配到样例 title=%s",
                      node.get("title"),
                  )
          for child in node.get("children", []) or []:
              _walk(child)

      for n in tree.get("nodes", []) or []:
          _walk(n)
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement fuzzy sample content binding"
  ```

### Task 8: 编号后处理（中文数字 + 多级映射）

**Files:**
- Modify: `src/extractor/bid_outline.py`（追加 `_assign_numbering` + `_CN_NUMERALS`）
- Modify: `src/extractor/tests/test_bid_outline.py`

**职责：** 深度优先遍历目录树，为每个节点赋 `number` 字段。Level 1 用中文数字，Level 2/3 用阿拉伯数字（Level 2 的父级数字从中文 Level 1 映射得来）。

- [ ] **Step 1: 写失败测试**

  ```python
  from src.extractor.bid_outline import _assign_numbering, _cn_numeral


  def test_cn_numeral_1_to_20():
      expected = ["一","二","三","四","五","六","七","八","九","十",
                  "十一","十二","十三","十四","十五","十六","十七","十八","十九","二十"]
      for i, e in enumerate(expected, start=1):
          assert _cn_numeral(i) == e


  def test_cn_numeral_over_20_falls_back_to_arabic():
      assert _cn_numeral(21) == "21"
      assert _cn_numeral(99) == "99"


  def test_assign_numbering_three_level_tree():
      tree = {"nodes": [
          {"title": "附件", "level": 1, "children": [
              {"title": "资质证书", "level": 2, "children": [
                  {"title": "A证书", "level": 3, "children": []},
                  {"title": "B证书", "level": 3, "children": []},
              ]},
              {"title": "业绩", "level": 2, "children": []},
          ]},
          {"title": "技术部分", "level": 1, "children": [
              {"title": "质量方案", "level": 2, "children": []},
          ]},
      ]}
      _assign_numbering(tree)
      assert tree["nodes"][0]["number"] == "一、"
      assert tree["nodes"][0]["children"][0]["number"] == "1.1"
      assert tree["nodes"][0]["children"][0]["children"][0]["number"] == "1.1.1"
      assert tree["nodes"][0]["children"][0]["children"][1]["number"] == "1.1.2"
      assert tree["nodes"][0]["children"][1]["number"] == "1.2"
      assert tree["nodes"][1]["number"] == "二、"
      assert tree["nodes"][1]["children"][0]["number"] == "2.1"


  def test_assign_numbering_empty_tree():
      tree = {"nodes": []}
      _assign_numbering(tree)  # 不崩溃
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 3: 实现**

  ```python
  _CN_NUMERALS = [
      "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
      "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
  ]


  def _cn_numeral(n: int) -> str:
      """1~20 返回中文数字，超过返回阿拉伯数字字符串（罕见降级）。"""
      if 1 <= n <= 20:
          return _CN_NUMERALS[n - 1]
      return str(n)


  def _assign_numbering(tree: dict) -> None:
      """深度优先为 tree.nodes 每个节点赋 number 字段（原地修改）。"""
      for i, node in enumerate(tree.get("nodes", []) or [], start=1):
          node["number"] = f"{_cn_numeral(i)}、"
          _assign_sub(node, prefix=str(i))


  def _assign_sub(parent: dict, prefix: str) -> None:
      for j, child in enumerate(parent.get("children", []) or [], start=1):
          child["number"] = f"{prefix}.{j}"
          _assign_sub(child, prefix=f"{prefix}.{j}")
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement numbering post-processor with 1-20 Chinese numerals"
  ```

---

## Chunk 3: Layer 4 渲染、主入口、调用方接入、清理、前端

### Task 9: Layer 4 docx 渲染

**Files:**
- Modify: `src/extractor/bid_outline.py`（追加 `_render_docx`）
- Modify: `src/extractor/tests/test_bid_outline.py`

**职责：** 把已编号、已绑定样例的目录树渲染为 `.docx`。

规则回顾：
- Level 1/2/3 对应 Heading 1/2/3，标题文本为 `{number} {title}`
- 每个叶子节点下留一个空段落
- `has_sample=true` 且 `sample_content` 非空：嵌入正文（text 原样段落；standard_table 渲染为 Word 表格）
- `dynamic=true`：标题下插入红色斜体占位段落

- [ ] **Step 1: 写失败测试**

  ```python
  import io
  from docx import Document
  from src.extractor.bid_outline import _render_docx


  def _build_rendered(tree: dict) -> Document:
      buf = io.BytesIO()
      _render_docx(tree, buf)
      buf.seek(0)
      return Document(buf)


  def test_render_docx_writes_hierarchy_with_numbers():
      tree = {"title": "投标文件", "nodes": [
          {"number": "一、", "title": "附件", "level": 1,
           "has_sample": False, "dynamic": False, "children": [
               {"number": "1.1", "title": "资质", "level": 2,
                "has_sample": False, "dynamic": False, "children": [
                    {"number": "1.1.1", "title": "A证书", "level": 3,
                     "has_sample": False, "dynamic": False, "children": []}
                ]}
           ]}
      ]}
      doc = _build_rendered(tree)
      texts = [p.text for p in doc.paragraphs]
      assert "一、 附件" in texts
      assert "1.1 资质" in texts
      assert "1.1.1 A证书" in texts


  def test_render_docx_embeds_text_sample():
      tree = {"title": "投标文件", "nodes": [
          {"number": "一、", "title": "投标函", "level": 1,
           "has_sample": True, "dynamic": False,
           "sample_content": {"type": "text",
                              "content": "致：[采购人]\n我方..."},
           "children": []}
      ]}
      doc = _build_rendered(tree)
      combined = "\n".join(p.text for p in doc.paragraphs)
      assert "致：[采购人]" in combined
      assert "我方..." in combined


  def test_render_docx_embeds_table_sample():
      tree = {"title": "投标文件", "nodes": [
          {"number": "一、", "title": "开标一览表", "level": 1,
           "has_sample": True, "dynamic": False,
           "sample_content": {
               "type": "standard_table",
               "columns": ["项目", "金额"],
               "rows": [["A", "100"]],
           },
           "children": []}
      ]}
      doc = _build_rendered(tree)
      assert len(doc.tables) == 1
      tbl = doc.tables[0]
      assert tbl.rows[0].cells[0].text == "项目"
      assert tbl.rows[1].cells[1].text == "100"


  def test_render_docx_dynamic_node_inserts_red_italic_hint():
      tree = {"title": "投标文件", "nodes": [
          {"number": "九、", "title": "类似项目业绩一览表", "level": 1,
           "has_sample": False, "dynamic": True,
           "dynamic_hint": "按客户/项目逐项展开",
           "children": []}
      ]}
      doc = _build_rendered(tree)
      # 找到含 "⚠️" 的段落
      hint_paras = [p for p in doc.paragraphs if "⚠️" in p.text]
      assert len(hint_paras) == 1
      assert "按客户/项目逐项展开" in hint_paras[0].text
      # 颜色/斜体
      run = hint_paras[0].runs[0]
      assert run.italic is True
      from docx.shared import RGBColor
      assert run.font.color.rgb == RGBColor(0xFF, 0x00, 0x00)
  ```

- [ ] **Step 2: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 3: 在 bid_outline.py 追加实现**

  ```python
  from docx import Document as _DocxDocument
  from docx.shared import RGBColor as _RGBColor


  def _render_docx(tree: dict, output) -> None:
      """渲染目录树到 docx。

      output: 路径（str/Path）或可写 file-like。
      """
      doc = _DocxDocument()
      doc.add_heading(tree.get("title", "投标文件"), level=0)

      for node in tree.get("nodes", []) or []:
          _render_node(doc, node)

      doc.save(output)


  def _render_node(doc, node: dict) -> None:
      level = min(max(int(node.get("level", 1)), 1), 3)
      number = node.get("number", "")
      title = node.get("title", "")
      heading_text = f"{number} {title}".strip()
      doc.add_heading(heading_text, level=level)

      # 动态节点提示（样式：红字 + 斜体）
      if node.get("dynamic"):
          hint = node.get("dynamic_hint") or "此节需按实际情况展开"
          sample_n1 = f'"{number}.1 示例一"' if number else '"示例一"'
          sample_n2 = f'"{number}.2 示例二"' if number else '"示例二"'
          line = f"[⚠️ 此节需{hint}，例如 {sample_n1} / {sample_n2}]"
          p = doc.add_paragraph()
          run = p.add_run(line)
          run.italic = True
          run.font.color.rgb = _RGBColor(0xFF, 0x00, 0x00)

      # 样例嵌入
      sc = node.get("sample_content")
      if node.get("has_sample") and isinstance(sc, dict):
          if sc.get("type") == "standard_table":
              _add_table(doc, sc.get("columns", []), sc.get("rows", []))
          else:
              for line in (sc.get("content") or "").split("\n"):
                  doc.add_paragraph(line)

      # 叶子节点：留一个空段落作为填写空间
      children = node.get("children") or []
      if not children:
          doc.add_paragraph("")
      else:
          for child in children:
              _render_node(doc, child)


  def _add_table(doc, columns: list, rows: list) -> None:
      if not columns:
          return
      ncols = len(columns)
      tbl = doc.add_table(rows=1 + len(rows), cols=ncols)
      tbl.style = "Table Grid"
      for i, c in enumerate(columns):
          tbl.rows[0].cells[i].text = str(c)
      for ri, row in enumerate(rows, start=1):
          padded = list(row) + [""] * (ncols - len(row))
          for ci, cell in enumerate(padded[:ncols]):
              tbl.rows[ri].cells[ci].text = str(cell)
  ```

- [ ] **Step 4: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement Layer 4 docx rendering with dynamic hints and samples"
  ```

### Task 10: 主入口 extract_bid_outline（Layer 1/2 并行、三重空信号兜底、docx 输出路径）

**Files:**
- Modify: `src/extractor/bid_outline.py`
- Modify: `src/extractor/tests/test_bid_outline.py`

**职责：** 实现对外主入口 `extract_bid_outline(tagged_paragraphs, settings, embeddings_map, module_embedding, modules_context=None) -> dict | None`。

行为：
1. `ThreadPoolExecutor(max_workers=2)` 并行调度 Layer 1（复用现有 `bid_format._first_pass`）和 Layer 2（`_extract_skeleton_signals`）
2. Layer 1 异常 → warn 并视作 `has_any_template=False`
3. Layer 2 异常或返回 None → 整体返回 None
4. 三重空信号（Layer 1 templates=[] ∧ composition_clause.found=False ∧ scoring_factors=[] ∧ material_enumerations=[] ∧ format_templates=[]）→ 整体返回 None，log error
5. Layer 3 合成 → 失败返回 None
6. 绑定样例 → 编号 → 返回目录树 JSON（含 `title`/`nodes`/每节点 `number` 与可能的 `sample_content`）
7. **docx 落盘不在本函数内完成**：与现有 extractor 一样只返回结构化数据，docx 渲染由上游（`server/app/tasks/`）在需要落盘时调用 `_render_docx(tree, path_or_io)`。这样保持模块职责单一，也方便测试

- [ ] **Step 1: 确认现有 extractor 是否自己落盘（预期：否）**

  快速 grep 确认：

  ```bash
  grep -rn "doc.save\|Document()" src/extractor/*.py
  ```
  Expected: 只有本 task 新加入的 `_render_docx` 里有 `doc.save`；主入口函数无 `save` 调用，与 `extract_checklist` 等其它 extractor 一致。

- [ ] **Step 2: 写失败测试**

  ```python
  from unittest.mock import patch, MagicMock
  from src.extractor.bid_outline import extract_bid_outline


  def _dummy_para(i):
      from src.models import TaggedParagraph
      return TaggedParagraph(index=i, text=f"段落{i}", section_title=None,
                             table_data=None, tags=[])


  def test_extract_bid_outline_triple_empty_returns_none():
      paras = [_dummy_para(i) for i in range(10)]
      empty_layer1 = {"has_any_template": False, "templates": []}
      empty_layer2 = {
          "composition_clause": {"found": False, "items": []},
          "scoring_factors": [], "material_enumerations": [],
          "format_templates": [], "dynamic_nodes": [],
      }
      with patch("src.extractor.bid_outline._run_layer1", return_value=empty_layer1), \
           patch("src.extractor.bid_outline._extract_skeleton_signals",
                 return_value=empty_layer2):
          result = extract_bid_outline(paras, settings=None)
      assert result is None


  def test_extract_bid_outline_layer2_none_returns_none():
      paras = [_dummy_para(i) for i in range(10)]
      with patch("src.extractor.bid_outline._run_layer1",
                 return_value={"has_any_template": False, "templates": []}), \
           patch("src.extractor.bid_outline._extract_skeleton_signals",
                 return_value=None):
          result = extract_bid_outline(paras, settings=None)
      assert result is None


  def test_extract_bid_outline_happy_path_returns_tree_with_numbers():
      paras = [_dummy_para(i) for i in range(10)]
      layer1 = {"has_any_template": True, "templates": [
          {"title": "投标函", "type": "text", "content": "T"}
      ]}
      layer2 = {
          "composition_clause": {"found": True,
                                  "items": [{"order": 1, "title": "投标函"}]},
          "scoring_factors": [], "material_enumerations": [],
          "format_templates": [], "dynamic_nodes": [],
      }
      fake_tree = {"title": "投标文件", "nodes": [
          {"title": "投标函", "level": 1, "source": "format_template",
           "has_sample": True, "dynamic": False, "children": []}
      ]}
      with patch("src.extractor.bid_outline._run_layer1", return_value=layer1), \
           patch("src.extractor.bid_outline._extract_skeleton_signals",
                 return_value=layer2), \
           patch("src.extractor.bid_outline._compose_outline_tree",
                 return_value=fake_tree):
          result = extract_bid_outline(paras, settings=None)
      assert result is not None
      assert result["nodes"][0]["number"] == "一、"
      assert result["nodes"][0].get("sample_content") is not None  # 样例已绑定


  def test_extract_bid_outline_layer1_exception_continues():
      paras = [_dummy_para(i) for i in range(10)]
      layer2 = {
          "composition_clause": {"found": True,
                                  "items": [{"order": 1, "title": "投标函"}]},
          "scoring_factors": [{"category": "技术", "title": "X", "sub_items": []}],
          "material_enumerations": [],
          "format_templates": [], "dynamic_nodes": [],
      }
      fake_tree = {"title": "投标文件", "nodes": [
          {"title": "投标函", "level": 1, "has_sample": False,
           "dynamic": False, "children": []}
      ]}
      with patch("src.extractor.bid_outline._run_layer1",
                 side_effect=RuntimeError("layer1 boom")), \
           patch("src.extractor.bid_outline._extract_skeleton_signals",
                 return_value=layer2), \
           patch("src.extractor.bid_outline._compose_outline_tree",
                 return_value=fake_tree):
          result = extract_bid_outline(paras, settings=None)
      assert result is not None
      assert result["nodes"][0]["number"] == "一、"
  ```

- [ ] **Step 3: 运行测试确认失败**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 4: 实现主入口**

  在 `bid_outline.py` 追加：

  ```python
  from concurrent.futures import ThreadPoolExecutor


  def _run_layer1(
      tagged_paragraphs: list[TaggedParagraph],
      settings: dict | None,
      embeddings_map: dict[int, list[float]] | None,
      module_embedding: list[float] | None,
  ) -> dict:
      """Layer 1：复用现有 bid_format 的第一次 LLM 调用逻辑。

      返回统一 schema: {"has_any_template": bool, "templates": [...]}。
      失败不抛异常，返回空结构。
      """
      try:
          # 延迟 import 避免循环依赖
          from src.extractor.bid_format import _filter_paragraphs, _first_pass

          filtered, score_map = _filter_paragraphs(
              tagged_paragraphs,
              embeddings_map=embeddings_map,
              module_embedding=module_embedding,
          )
          if not filtered:
              return {"has_any_template": False, "templates": []}
          raw = _first_pass(filtered, score_map, settings)
          if not isinstance(raw, dict):
              return {"has_any_template": False, "templates": []}
          if raw.get("has_template") is False:
              return {"has_any_template": False, "templates": []}

          # 旧 schema 是 {"title": "...", "sections": [...]}，转成新 schema
          templates = _layer1_sections_to_templates(raw.get("sections", []))
          return {
              "has_any_template": len(templates) > 0,
              "templates": templates,
          }
      except Exception as e:
          logger.warning("bid_outline.layer1 失败: %s", e)
          return {"has_any_template": False, "templates": []}


  def _layer1_sections_to_templates(sections: list) -> list[dict]:
      """把旧 bid_format.txt 的 sections 结构展平为 templates 数组。"""
      out: list[dict] = []
      for s in sections or []:
          if not isinstance(s, dict):
              continue
          st = s.get("type")
          if st == "group":
              out.extend(_layer1_sections_to_templates(s.get("children", [])))
          elif st == "standard_table":
              out.append({
                  "title": s.get("title", ""),
                  "type": "standard_table",
                  "columns": s.get("columns", []),
                  "rows": s.get("rows", []),
              })
          else:
              out.append({
                  "title": s.get("title", ""),
                  "type": "text",
                  "content": s.get("content", ""),
              })
      return out


  def _is_triple_empty(layer1: dict, layer2: dict) -> bool:
      if layer1.get("templates"):
          return False
      cc = layer2.get("composition_clause") or {}
      if cc.get("found"):
          return False
      if layer2.get("scoring_factors"):
          return False
      if layer2.get("material_enumerations"):
          return False
      if layer2.get("format_templates"):
          return False
      return True


  def extract_bid_outline(
      tagged_paragraphs: list[TaggedParagraph],
      settings: dict | None = None,
      embeddings_map: dict[int, list[float]] | None = None,
      module_embedding: list[float] | None = None,
      modules_context: dict | None = None,  # 兼容旧签名，忽略
  ) -> dict | None:
      """四层流水线主入口。返回目录树 JSON 或 None（失败/空信号）。"""
      # Layer 1 和 Layer 2 并行
      with ThreadPoolExecutor(max_workers=2) as ex:
          fut_l1 = ex.submit(
              _run_layer1, tagged_paragraphs, settings,
              embeddings_map, module_embedding,
          )
          fut_l2 = ex.submit(
              _extract_skeleton_signals, tagged_paragraphs, settings,
              embeddings_map, module_embedding,
          )
          layer1 = fut_l1.result()
          layer2 = fut_l2.result()

      if layer2 is None:
          logger.error("bid_outline: Layer 2 返回 None，整体失败")
          return None

      if _is_triple_empty(layer1, layer2):
          logger.error("bid_outline: 三重空信号，无法生成大纲")
          return None

      # Layer 3
      tree = _compose_outline_tree(layer1, layer2, settings)
      if tree is None:
          logger.error("bid_outline: Layer 3 返回 None")
          return None

      # 样例绑定 + 编号
      _bind_sample_content(tree, layer1)
      _assign_numbering(tree)

      return tree
  ```

- [ ] **Step 5: 运行测试确认通过**

  ```bash
  python -m pytest src/extractor/tests/test_bid_outline.py -v
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add src/extractor/bid_outline.py src/extractor/tests/test_bid_outline.py
  git commit -m "feat(bid-outline): implement parallel orchestrator with triple-empty fallback"
  ```

### Task 11: 将 `bid_format` module key 指向新实现

**Files:**
- Modify: `src/extractor/extractor.py:19`（改注册表）

**职责：** 把 `bid_format` 的 factory 从 `bid_format.extract_bid_format` 改为 `bid_outline.extract_bid_outline`。

- [ ] **Step 1: 查看现有注册**

  ```bash
  grep -n "bid_format\|extract_" src/extractor/extractor.py | head -20
  ```

- [ ] **Step 2: 编辑 extractor.py 第 19 行**

  将 `"bid_format": ("src.extractor.bid_format", "extract_bid_format"),` 改为 `"bid_format": ("src.extractor.bid_outline", "extract_bid_outline"),`

- [ ] **Step 3: 快速冒烟**

  ```bash
  python -c "from src.extractor.extractor import MODULE_REGISTRY; print(MODULE_REGISTRY['bid_format'])"
  ```
  Expected: `('src.extractor.bid_outline', 'extract_bid_outline')` 或类似格式

  （若 extractor.py 的注册表变量名不是 `MODULE_REGISTRY`，依实际变量名调整）

- [ ] **Step 4: 运行已有 extractor 测试**

  ```bash
  python -m pytest src/extractor/tests/ -v -x
  ```
  Expected: 全部通过（含 bid_outline 测试和现有其它 extractor 测试）

- [ ] **Step 5: Commit**

  ```bash
  git add src/extractor/extractor.py
  git commit -m "feat(bid-outline): switch bid_format module key to new extract_bid_outline"
  ```

### Task 12: pipeline_task.py 移除 modules_context 依赖

**Files:**
- Modify: `server/app/tasks/pipeline_task.py:152~157`

**职责：** 原逻辑是"bid_format 依赖 phase1 的 modules_result，所以单独传 modules_context"。新实现不再需要，改为与 checklist 对称调度。

- [ ] **Step 1: 读取 pipeline_task.py 152~170 行确认上下文**

  ```bash
  sed -n '140,175p' server/app/tasks/pipeline_task.py
  ```

- [ ] **Step 2: 修改调用**

  将（大致形态）：
  ```python
  extra = {"modules_context": modules_result} if mk == "bid_format" else None
  phase2_futures[executor.submit(_extract_module, mk, extra)] = mk
  ```
  改为：
  ```python
  phase2_futures[executor.submit(_extract_module, mk, None)] = mk
  ```
  （如果 `_extract_module` 不支持 None 参数，改为对称的无 extra 调用；具体写法看该函数签名。）

- [ ] **Step 3: 冒烟（如有相关测试）**

  ```bash
  python -m pytest server/tests/ -v -k pipeline -x
  ```
  如果没有对应测试，跳过。

- [ ] **Step 4: Commit**

  ```bash
  git add server/app/tasks/pipeline_task.py
  git commit -m "refactor(bid-outline): drop modules_context wiring in pipeline_task"
  ```

### Task 13: 清理旧 fallback 资产

**Files:**
- Delete: `config/prompts/bid_format_fallback.txt`
- Delete: `src/extractor/tests/test_bid_format.py`（如存在）
- Modify: `src/extractor/bid_format.py`（删除 `_summarize_modules`、`_fallback_pass`、`FALLBACK_PROMPT_PATH` 及 `extract_bid_format` 中对 fallback 的调用；保留 `_filter_paragraphs` 和 `_first_pass` 供 `bid_outline._run_layer1` 复用）

**职责：** 移除 fallback 路径代码和资源。保留的 `bid_format.py` 退化为 Layer 1 的工具模块。

- [ ] **Step 1: 确认 test_bid_format.py 是否存在**

  ```bash
  ls src/extractor/tests/ | grep bid_format || echo "not found"
  ```

- [ ] **Step 2: 删除 fallback prompt**

  ```bash
  git rm config/prompts/bid_format_fallback.txt
  ```

- [ ] **Step 3: 删除旧测试（如存在）**

  ```bash
  [ -f src/extractor/tests/test_bid_format.py ] && git rm src/extractor/tests/test_bid_format.py || true
  ```

- [ ] **Step 4: 精简 src/extractor/bid_format.py**

  保留的内容：模块 docstring、imports、`PROMPT_PATH`、`_filter_paragraphs`、`_first_pass`。

  **删除**：`_summarize_modules`、`FALLBACK_PROMPT_PATH`、`_fallback_pass`、`extract_bid_format` 函数（整体删除，因为已被 `bid_outline.extract_bid_outline` 取代；`_run_layer1` 只需要 `_filter_paragraphs` 和 `_first_pass` 这两个助手）。

  修改完成后文件应保留两个公开助手（`_filter_paragraphs`、`_first_pass`），模块 docstring 更新为 "Layer 1 helpers for bid outline generation"。

- [ ] **Step 5: 运行测试确保没引用残留**

  ```bash
  python -m pytest src/extractor/tests/ -v -x
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add src/extractor/bid_format.py
  git commit -m "refactor(bid-outline): remove fallback path and summarize_modules dead code"
  ```

### Task 14: 前端改显示标签 + 跳过人工标注入口

**Files:**
- Modify: `web/src/components/ReviewStage.vue`（改第 28 行显示标签）
- Modify: `web/src/components/ReviewPreviewStage.vue` 和/或 `web/src/components/PreviewStage.vue`（对 bid_format 模块跳过人工标注 UI）

**职责：** UI 调整（不影响后端数据）。

- [ ] **Step 1: 修改 ReviewStage.vue 第 28 行**

  将 `bid_format: '投标文件格式'` 改为 `bid_format: '投标文件大纲'`。

- [ ] **Step 2: 查找前端标注入口**

  ```bash
  grep -n "bid_format\|annotations\|reextract" web/src/components/ReviewPreviewStage.vue web/src/components/PreviewStage.vue 2>/dev/null
  ```

  确定标注/重提取按钮位置，然后在其可见性条件上叠加 `module_key !== 'bid_format'`（或等价写法）。

  若前端暂时没有明确的 per-module 条件分支（例如所有模块共用同一套标注 UI），加一个 `const BID_OUTLINE_MODULE_KEY = 'bid_format'` 常量，在显示条件上 `v-if="moduleKey !== BID_OUTLINE_MODULE_KEY"` 包一层。

  **注意**：若无法在不深入前端状态管理的前提下完成此步，可先只改 Step 1 的显示标签，把 Step 2 抽为独立的前端任务（在单独 PR 处理）。

- [ ] **Step 3: 前端构建验证**

  ```bash
  cd web && npm run type-check 2>&1 | tail -20
  ```
  Expected: 无类型错误（或与改动前一致）

  （本地完整启动验证由人工过审）

- [ ] **Step 4: Commit**

  ```bash
  git add web/src/components/ReviewStage.vue web/src/components/ReviewPreviewStage.vue web/src/components/PreviewStage.vue 2>/dev/null
  git commit -m "feat(bid-outline): rename label to 投标文件大纲 and skip annotation UI"
  ```

### Task 15: 烟雾集成测试（真实样本）

**Files:**
- Create: `src/extractor/tests/test_bid_outline_smoke.py`（标记 `@pytest.mark.integration`）

**职责：** 用一份真实招标文件跑端到端，验证流程跑通、docx 能打开、结构大致对。不设断言通过率；人工过审。

- [ ] **Step 1: 定位一份真实招标文件**

  询问用户或从 `examples/` / 测试固件目录找一份已有的 .docx 招标文件。

  如项目中无可用样本，跳过本任务，改由用户在 PR-2 阶段人工验收。

- [ ] **Step 2: 写烟雾测试**

  ```python
  import os
  import pytest
  from pathlib import Path

  from src.parser.docx_parser import parse_docx  # 若入口名不同，按现有名改
  from src.extractor.bid_outline import extract_bid_outline, _render_docx


  @pytest.mark.integration
  @pytest.mark.skipif(
      not os.getenv("BID_OUTLINE_SAMPLE_DOCX"),
      reason="set BID_OUTLINE_SAMPLE_DOCX to a real tender .docx path"
  )
  def test_bid_outline_end_to_end(tmp_path):
      sample = Path(os.environ["BID_OUTLINE_SAMPLE_DOCX"])
      tagged = parse_docx(str(sample))
      tree = extract_bid_outline(tagged, settings=None)
      assert tree is not None, "三重空信号，无法生成；检查样本或关键词表"
      assert tree.get("nodes"), "目录为空"
      out = tmp_path / "out.docx"
      _render_docx(tree, str(out))
      assert out.exists() and out.stat().st_size > 0
  ```

- [ ] **Step 3: 运行（可选）**

  ```bash
  BID_OUTLINE_SAMPLE_DOCX=path/to/sample.docx python -m pytest src/extractor/tests/test_bid_outline_smoke.py -v
  ```
  Expected: PASS，`out.docx` 生成；人工打开肉眼过审。

- [ ] **Step 4: Commit**

  ```bash
  git add src/extractor/tests/test_bid_outline_smoke.py
  git commit -m "test(bid-outline): integration smoke test gated by env var"
  ```

---

## 完成判定

全部任务完成时：
- [ ] 所有 pytest 单测通过：`python -m pytest src/extractor/tests/ -v`
- [ ] `extract_bid_outline` 在 pipeline_task 被调度成功（手工 run 一次标准流水线任务）
- [ ] 前端 `投标文件大纲` 标签生效，`bid_format` 模块不再显示标注按钮
- [ ] 删除 `config/prompts/bid_format_fallback.txt` 和 `_summarize_modules`
- [ ] 生成的 docx 打开后：编号正确（中文 + 阿拉伯多级）、`dynamic=true` 节点有红色斜体提示、`has_sample=true` 节点嵌入了样表

## 开放问题（实现阶段可能触发追加 spec review）

- 若 Layer 2 prompt 输出的 `scoring_factors` 嵌套层级超过 3 级，合成 prompt 的第 3 条约束要求"再深的层级合并到 level=3 的 title 中，不再细分"——这条代码层面是靠 LLM 遵守，没有硬约束；PR-2 实测若频繁失败则追加代码后处理截断
- Layer 2 `BATCH_SIZE=40` 和 `min_count=50` 为拍脑袋值，PR-2 实测调整
- 前端 Task 14 Step 2 若改动面超预期（涉及状态机），建议拆成独立 PR
