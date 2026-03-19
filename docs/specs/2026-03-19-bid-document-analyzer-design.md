# 招标文件智能解读系统 — 设计文档

> 日期：2026-03-19
> 状态：已通过评审（v2）

---

## 1. 项目概述

### 1.1 目标

构建一个招标文件智能解读工具，自动从招标文件中提取结构化信息，经人工校对后生成三份标准 .docx 文档：

1. **分析报告** — 对招标文件的全面结构化拆解（项目信息、资格要求、评分标准、废标风险、投标文件要求、开评定标流程等）
2. **投标文件格式** — 投标文件的框架模板（投标函、开标一览表、法人证明、授权委托书、承诺函、偏离表等）
3. **资料清单** — 投标所需提交的全部材料清单（资格审查、报价、加分项、其他资料）

### 1.2 约束条件

| 约束 | 说明 |
|------|------|
| 输入格式 | .doc / .docx / .pdf |
| 输出格式 | 全部 .docx |
| LLM 服务 | 阿里云通义千问（Qwen）系列，通过 DashScope API 调用 |
| 交付路线 | 第一阶段 CLI 脚本（自用）→ 第二阶段 Web 应用（交付非技术团队） |
| 工作模式 | 半自动：LLM 生成草稿 → 人工校对修正 → 生成终版文档 |
| 文档篇幅 | 可能超过 100 页，需分段处理 |

### 1.3 核心设计原则

- **动态结构**：分析报告的大标题固定（A/B/C/D/E/F/G），小标题和表格结构由 LLM 根据每份招标文件的实际内容动态生成
- **鲁棒解析**：不同招标文件的章节命名、编号风格、有无目录均不同，采用"规则 + LLM 双层"切分策略
- **中间产物结构化**：所有提取结果以 JSON 形式存储，方便校对、调试和后续 Web 化

---

## 2. 系统架构

### 2.1 五层 Pipeline

```
输入：招标文件（.doc / .docx / .pdf）
        ↓
  ┌─────────────────────────┐
  │  Layer 1: 文档解析层     │  → List[Paragraph]
  └─────────┬───────────────┘
            ↓
  ┌─────────────────────────┐
  │  Layer 2: 分段索引层     │  → List[TaggedParagraph]
  └─────────┬───────────────┘
            ↓
  ┌─────────────────────────┐
  │  Layer 3: LLM 提取层     │  → 结构化 JSON
  └─────────┬───────────────┘
            ↓
  ┌─────────────────────────┐
  │  Layer 4: 人工校对层     │  → 校对后 JSON
  └─────────┬───────────────┘
            ↓
  ┌─────────────────────────┐
  │  Layer 5: 文档生成层     │  → 3 份 .docx
  └─────────────────────────┘
```

### 2.2 数据流

每一层的输入输出都持久化到磁盘（output/ 目录），支持：
- 断点续跑（某层失败后从上一层输出重新开始）
- 单模块重跑（只重新提取某个模块）
- 校对后重新生成（不需要重新调 LLM）

---

## 3. 各层详细设计

### 3.1 Layer 1: 文档解析层

**职责**：将三种格式的招标文件统一转换为 `List[Paragraph]` 结构。

**统一数据结构**：

```python
@dataclass
class Paragraph:
    index: int            # 段落序号
    text: str             # 段落文本
    style: str | None     # Word 样式名（如 "Heading 1"），PDF 无此信息
    is_table: bool        # 是否为表格内容
    table_data: list | None  # 表格数据（二维列表）
```

**各格式解析策略**：

| 格式 | 库 | 策略 |
|------|-----|------|
| .docx | python-docx | 直接读取段落和表格，保留样式信息 |
| .doc | LibreOffice headless → python-docx | 先用 `soffice --headless --convert-to docx` 转为 .docx，再用 python-docx 解析。这是最可靠的 .doc 解析方式，能正确保留表格、样式和中文编码 |
| .pdf | pdfplumber | 提取文本和表格，通过字号/加粗推断标题层级 |

**.doc 解析的降级策略**：

```
.doc 文件
    ↓
[首选] LibreOffice headless 转 .docx → python-docx 解析
    ↓ (LibreOffice 未安装或转换失败)
[降级] olefile 读取 WordDocument 流 → 提取纯文本（丢失表格结构）
    ↓ (仍然失败)
[最终降级] 提示用户手动转存为 .docx 或 .pdf
```

**系统依赖**：需安装 LibreOffice（用于 .doc → .docx 转换）。安装后 `soffice` 命令须在 PATH 中可用。

**编码处理**：使用 `charset-normalizer` 库检测文件编码，处理政府文档中常见的 GBK/GB2312/GB18030 编码问题。

**统一接口**：

```python
def parse_document(file_path: str) -> list[Paragraph]:
    """根据扩展名自动选择解析器，返回统一的段落列表"""
```

### 3.2 Layer 2: 分段索引层

**职责**：将段落列表切分为带语义标签的段落池，供提取层按需检索。

**输出数据结构**：

```python
@dataclass
class TaggedParagraph:
    index: int
    text: str
    section_title: str | None   # 所属章节标题
    section_level: int          # 章节层级（1=大章, 2=节, 3=小节）
    tags: list[str]             # 语义标签，如 ["评分", "报价", "经济"]
    table_data: list | None
```

**双层切分策略**：

**第一层：规则解析（4种策略并行评分，综合决策）**

| 策略 | 方法 | 适用场景 |
|------|------|---------|
| A. Word 样式 | 解析 Heading 1/2/3 样式 | .docx 且正确使用了样式 |
| B. 编号模式 | 正则匹配 `第X章`、`一、`、`1.1`、`（一）` 等 | 大多数文档 |
| C. 关键词匹配 | 同义词组匹配（见下表） | 所有文档，作为补充 |
| D. 目录解析 | 解析文档开头的目录结构 | 有目录的文档 |

**关键词同义词组**（config/synonyms.yaml）：

```yaml
采购公告: ["采购公告", "招标公告", "比选公告", "邀请函"]
供应商须知: ["供应商须知", "投标人须知", "投标须知", "注意事项"]
评标办法: ["评标办法", "评审办法", "评分标准", "评分办法", "评标方法", "评标细则"]
合同条款: ["合同条款", "合同格式", "合同范本", "协议条款"]
技术要求: ["技术商务要求", "技术要求", "技术规格", "技术规范", "项目需求", "服务要求"]
投标格式: ["投标文件格式", "投标格式", "响应文件格式", "投标文件组成"]
```

**规则置信度评分**：

```python
# 置信度 = 识别到的章节数 / 预期最少章节数（6个大章）× 覆盖率
# 覆盖率 = 被分配到章节的段落数 / 总段落数
confidence = (found_sections / 6) * (assigned_paragraphs / total_paragraphs)
```

- `confidence >= 0.7`：直接使用规则切分结果
- `confidence < 0.7`：触发 LLM 兜底

**第二层：LLM 兜底（规则置信度 < 0.7 时触发）**

将文档前 2000 字 + 规则解析结果一并送给 Qwen：

```
Prompt: 以下是一份招标文件的开头部分和初步章节解析结果。
请验证并补充章节结构，输出 JSON 格式：
[{"title": "...", "level": 1, "start_paragraph": N}, ...]
```

**语义标签打标**：

基于章节标题和段落内容关键词，为每段打上语义标签：

```yaml
tag_rules:
  评分: ["评分", "得分", "扣分", "加分", "分值", "权重", "评审因素"]
  资格: ["资格", "资质", "认证", "证书", "营业执照", "禁止情形"]
  报价: ["报价", "报价表", "开标一览表", "单价", "总价", "限价", "预算"]
  风险: ["废标", "无效标", "否决", "不予受理", "不合格"]
  流程: ["开标", "评标", "定标", "签订合同", "投产"]
  格式: ["投标文件格式", "签字盖章", "密封", "装订", "份数"]
  材料: ["证明材料", "复印件", "扫描件", "加盖公章", "提供"]
```

### 3.3 Layer 3: LLM 提取层

**职责**：逐模块调用 Qwen，从段落池中提取结构化信息。

**提取模块列表**：

| 模块 | 对应报告章节 | 提取来源标签 |
|------|-------------|-------------|
| module_a | A. 项目基本信息 | 采购公告、供应商须知 |
| module_b | B. 资格与合规 | 资格、材料 |
| module_c | C. 技术评分 | 评分、报价 |
| module_d | D. 合同与商务条款 | 合同条款、商务要求 |
| module_e | E. 无效标与废标项 | 风险、资格、格式 |
| module_f | F. 投标文件要求 | 格式、材料 |
| module_g | G. 开评定标流程 | 流程 |
| bid_format | 投标文件格式 | 格式、材料 |
| checklist | 资料清单 | 材料、资格 |

> **关于模块 D**：招标文件通常包含"合同条款及格式"章节（如本示例的第四章），包含付款方式、违约责任、知识产权、保密条款等。模块 D 负责提取这些合同与商务条款要点。

**每个模块的调用流程**：

```
1. 从段落池中筛选匹配标签的段落
2. 计算 token 数（使用字符数 × 0.6 估算中文 token，偏保守）
3. 判断上下文策略（qwen3.5-plus 支持 1M token 上下文）：
   - 总 token < 128K → 单次调用（最低价格档）
   - 128K ≤ 总 token < 900K → 仍可单次调用，但价格较高，优先精简输入
   - 总 token ≥ 900K → 分批处理（极少出现，预留安全余量）
4. 调用 Qwen，Prompt = 模块模板 + few-shot 示例 + 相关段落
5. 解析 LLM 输出的 JSON
6. 校验 JSON 结构完整性，缺失则重试（最多 3 次）
```

**成本优化策略**：

由于 qwen3.5-plus 采用阶梯计价（128K 以上价格翻倍），优先控制每次调用的输入在 128K 以内：
- 每个模块只送入**相关标签**的段落，而非全文
- 对于 100 页招标文件（约 60K-80K token），单模块通常只需 5K-20K token 的相关段落
- 正常情况下所有模块调用均在最低价格档（0.8元/百万 token）

**分批处理规则**（极端长文档降级方案）：

- 按章节/小节边界切分，不在表格中间断开
- 每批 ≤ 120K token（保持在最低价格档内）
- 每批独立提取，输出带 section id
- 合并策略：按 section id 去重，同一 id 出现在多批时取最后一批的结果

**LLM 输出格式 — 自描述结构化 JSON**：

**JSON 整体结构**（每份文档一个 JSON 文件）：

```json
{
  "schema_version": "1.0",
  "source_file": "招标文件.docx",
  "generated_at": "2026-03-19T10:30:00",
  "modules": {
    "module_a": { ... },
    "module_b": { ... },
    ...
  }
}
```

> `schema_version` 用于中间文件的版本管理。加载已保存的 JSON 时检查版本号，不兼容时提示用户重新提取。

**每个模块输出格式**：

```json
{
  "title": "A. 项目基本信息",
  "sections": [
    {
      "id": "A1",
      "title": "子章节标题（由LLM根据内容决定）",
      "type": "key_value_table",
      "columns": ["项目要素", "内容"],
      "rows": [["项目名称", "..."], ["采购编号", "..."]],
      "source": [12, 13, 14]
    }
  ]
}
```

**section 字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 唯一标识，格式 `^[A-G]\d+(\.\d+)*$`，如 "A1"、"C2.1" |
| title | string | 是 | 子章节标题 |
| type | enum | 是 | `key_value_table` / `standard_table` / `text` / `parent` |
| columns | string[] | type=table时 | 表格列名 |
| rows | string[][] | type=table时 | 表格数据行 |
| content | string | type=text时 | 文本内容 |
| sections | section[] | type=parent时 | 子章节列表（最大嵌套深度：3层，对应 Heading 2/3/4） |
| source | int[] | 否 | 来源段落索引，用于人工校对时溯源 |

支持的 section type：

| type | 说明 | 示例 |
|------|------|------|
| key_value_table | 两列键值对表格 | A1 项目基本信息、A2 采购方信息 |
| standard_table | 多列标准表格 | A5 采购内容、B1.4 专业资质、C2 评分标准 |
| text | 纯文本段落 | 补充说明、证明材料要求描述 |
| parent | 包含子章节的父节（最多嵌套3层） | C2 报价评分标准（下含 C2.1/C2.2/C2.3） |

**Prompt 设计策略**：

每个模块的 Prompt 由三部分组成：

```
[角色指令]
你是招标文件分析专家，请从以下招标文件内容中提取 {模块名称} 相关信息。

[输出格式说明 + JSON Schema]
输出严格 JSON 格式，结构如下：...
你需要根据文档实际内容决定子章节的数量、标题和表格列结构。

[Few-shot 示例]
以下是一个示例输入和输出（基于重庆农商银行信用卡制递卡项目）：
输入：...
输出：...

[实际输入]
请分析以下内容：
{相关段落文本}
```

**Qwen API 调用配置**：

统一使用 `qwen3.5-plus` 模型（无需区分长短文本模型，该模型原生支持 1M token 上下文）。

```yaml
api:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3.5-plus"        # 统一模型，1M上下文，性价比高
  temperature: 0.1              # 低温度，确保输出稳定
  max_output_tokens: 65536      # 模型最大输出 65K token
  enable_thinking: false        # 关闭思考模式，节省 token，输出更稳定
  retry: 3
  timeout: 120
```

**qwen3.5-plus 模型规格**：

| 参数 | 值 |
|------|-----|
| 模型 ID | `qwen3.5-plus` |
| 上下文窗口 | 1,000,000 token |
| 最大输入（非思考模式） | 991,808 token |
| 最大输出 | 65,536 token |
| 支持输入 | 文本、图像、视频 |
| API 兼容 | OpenAI 兼容接口 |

**价格**（阶梯计费，中国内地）：

| 输入 token 区间 | 输入价格（元/百万） | 输出价格（元/百万） |
|----------------|--------------------|--------------------|
| 0 - 128K | 0.8 | 4.8 |
| 128K - 256K | 2 | 12 |
| 256K - 1M | 4 | 24 |

### 3.4 Layer 4: 人工校对层

**职责**：展示 LLM 提取结果，供用户逐模块审核修正。

**CLI 阶段交互流程**：

```
$ python -m src.main analyze 招标文件.docx

[解析完成] 共 326 个段落，识别 6 个章节
[提取中] A.项目基本信息... 完成
[提取中] B.资格与合规... 完成
...

=== 校对模式 ===

[模块 A: 项目基本信息]
┌─────────────┬──────────────────────────────┐
│ A1. 项目基本信息                              │
├─────────────┼──────────────────────────────┤
│ 项目名称     │ 重庆农村商业银行2025-2026年...  │
│ 采购编号     │ SFG2500080606A               │
│ ...         │ ...                          │
└─────────────┴──────────────────────────────┘

该模块是否正确？[Y/n/e(编辑)]
> e
请输入要修改的字段（格式: A1.字段名=新值，输入 done 结束）：
> A1.采购方式=公开招标
> done

[模块 B: 资格与合规]
...
```

**CLI 校对策略**：

校对分两个粒度：
- **模块级**：逐模块展示表格预览，用户选择 `[Y] 通过 / [n] 拒绝（重跑该模块） / [e] 编辑`
- **编辑模式**：选择 `[e]` 后，自动用系统默认编辑器（`$EDITOR` 或 `notepad`）打开该模块的 JSON 片段，用户修改保存后自动重新加载并校验 JSON 格式合法性

> 这比自定义命令行编辑语法更灵活，也为后续 Web 前端的表单编辑奠定基础。

**中间文件**：

- `output/{filename}_extracted.json` — LLM 原始提取结果
- `output/{filename}_reviewed.json` — 校对后的结果

### 3.5 Layer 5: 文档生成层

**职责**：将校对后的结构化 JSON 动态渲染为 .docx 文件。

**核心组件**：

**TableBuilder — 通用表格构建器**：

```python
class TableBuilder:
    def build_key_value_table(self, columns, rows, doc) -> Table:
        """生成两列键值对表格（左列加粗灰底）"""

    def build_standard_table(self, columns, rows, doc) -> Table:
        """生成多列标准表格（首行表头加粗灰底）"""
```

**StyleManager — 样式管理器**：

从 `config/styles.yaml` 读取样式配置：

```yaml
styles:
  heading1:
    font: "微软雅黑"
    size: 16
    bold: true
    color: "#1a5276"
  heading2:
    font: "微软雅黑"
    size: 14
    bold: true
    color: "#2471a3"
  heading3:
    font: "微软雅黑"
    size: 12
    bold: true
  body:
    font: "宋体"
    size: 10.5
  table_header:
    font: "微软雅黑"
    size: 10
    bold: true
    bg_color: "#f2f3f4"
  table_body:
    font: "宋体"
    size: 10
```

**动态渲染逻辑**：

```python
def render_report(data: dict, output_path: str):
    doc = Document()
    # 设置页面和默认样式

    for module_key in ["module_a", "module_b", "module_c",
                       "module_d", "module_e", "module_f", "module_g"]:
        module = data[module_key]
        doc.add_heading(module["title"], level=1)
        render_sections(doc, module["sections"], level=2)

    doc.save(output_path)

def render_sections(doc, sections, level):
    for section in sections:
        doc.add_heading(section["title"], level=level)

        if section["type"] == "parent":
            render_sections(doc, section["sections"], level + 1)
        elif section["type"] == "text":
            doc.add_paragraph(section["content"])
        elif section["type"] in ("key_value_table", "standard_table"):
            table_builder.build(section, doc)
```

**三份文档的生成**：

| 文档 | 数据来源 | 特点 |
|------|---------|------|
| 分析报告 | module_a ~ module_g | 动态标题 + 动态表格 |
| 投标文件格式 | bid_format 提取结果 | 包含模板文本框和占位符 |
| 资料清单 | checklist 提取结果 | 分类表格 + 说明列 |

**投标文件格式生成详细说明**：

LLM 从招标文件中提取投标文件的组成结构（通常在"投标文件格式"章节），输出：
- 各部分的名称和顺序（投标函、开标一览表、法人证明等）
- 每部分的模板文本（固定措辞）
- 需要填写的占位字段（用 `___` 标注）
- 表格结构（如报价表的列名、行名）

生成器 `format_gen.py` 按顺序写入各部分，每部分包含：标题 + 模板正文 + 占位表格。参考示例文档 `示例文档/投标文件格式.docx` 的排版风格。

**资料清单生成详细说明**：

LLM 从招标文件全文中汇总所有需要提交的证明材料，按类别分组输出：
- 资格审查材料（营业执照、信用查询截图、资质认证等）
- 投标报价材料（各项报价明细）
- 客观加分项材料（案例合同、灾备证明、认证证书等）
- 其他材料（法人证明、委托书、样卡等）

每条材料包含：材料名称、材料内容描述、具体要求说明。生成器 `checklist_gen.py` 按分类生成多个表格（三列：资料名称 | 资料内容 | 说明）。参考示例文档 `示例文档/资料清单.docx` 的结构。

---

## 4. 项目目录结构

```
招标文件解读/
├── .venv/
├── config/
│   ├── settings.yaml         # API 配置（base_url, api_key, model）
│   ├── synonyms.yaml         # 章节关键词同义词组
│   ├── tag_rules.yaml        # 语义标签规则
│   ├── styles.yaml           # .docx 输出样式配置
│   └── prompts/              # 每个提取模块的 Prompt 模板
│       ├── module_a.txt
│       ├── module_b.txt
│       ├── module_c.txt
│       ├── module_d.txt
│       ├── module_e.txt
│       ├── module_f.txt
│       ├── module_g.txt
│       ├── bid_format.txt
│       └── checklist.txt
├── src/
│   ├── __init__.py
│   ├── main.py               # CLI 入口（argparse）
│   ├── parser/                # Layer 1: 文档解析
│   │   ├── __init__.py
│   │   ├── doc_parser.py     # .doc 解析（LibreOffice 转换 + 降级策略）
│   │   ├── docx_parser.py    # .docx 解析（python-docx）
│   │   ├── pdf_parser.py     # .pdf 解析（pdfplumber）
│   │   └── unified.py        # 统一接口 parse_document()
│   ├── indexer/               # Layer 2: 分段索引
│   │   ├── __init__.py
│   │   ├── rule_splitter.py  # 规则切分（样式/编号/关键词/目录）
│   │   ├── llm_splitter.py   # LLM 兜底切分
│   │   └── tagger.py         # 段落语义标签
│   ├── extractor/             # Layer 3: LLM 提取
│   │   ├── __init__.py
│   │   ├── base.py           # 基类：Qwen 调用、重试、JSON 解析
│   │   ├── module_a.py       # A. 项目基本信息
│   │   ├── module_b.py       # B. 资格与合规
│   │   ├── module_c.py       # C. 技术评分
│   │   ├── module_d.py       # D. 合同与商务条款
│   │   ├── module_e.py       # E. 无效标与废标项
│   │   ├── module_f.py       # F. 投标文件要求
│   │   ├── module_g.py       # G. 开评定标流程
│   │   ├── bid_format.py     # 投标文件格式提取
│   │   └── checklist.py      # 资料清单提取
│   ├── reviewer/              # Layer 4: 人工校对
│   │   ├── __init__.py
│   │   └── cli_reviewer.py   # CLI 交互校对
│   └── generator/             # Layer 5: 文档生成
│       ├── __init__.py
│       ├── report_gen.py     # 分析报告 → .docx（动态渲染）
│       ├── format_gen.py     # 投标文件格式 → .docx
│       ├── checklist_gen.py  # 资料清单 → .docx
│       ├── table_builder.py  # 通用表格构建器
│       └── style_manager.py  # 样式管理
├── output/                    # 运行输出目录
├── tests/
├── requirements.txt
└── README.md
```

---

## 5. 错误处理与日志

### 5.1 错误处理策略

采用**模块级 best-effort** 策略：单个模块失败不阻塞整个 Pipeline。

| 场景 | 处理方式 |
|------|---------|
| 文档解析失败（Layer 1） | 致命错误，终止流程，提示用户检查文件格式 |
| 规则切分置信度低 + LLM 兜底也失败 | 降级为"全文不分段"模式，将全部段落送入提取层 |
| 单个模块 LLM 调用 3 次重试均失败 | 跳过该模块，在输出 JSON 中标记 `"status": "failed"`，继续其他模块 |
| LLM 返回非法 JSON | 尝试修复（截断尾部、补全括号），修复失败则重试 |
| DashScope API 限流（429） | 指数退避重试（2s → 4s → 8s），最多 3 次 |
| 生成 .docx 时某模块数据缺失 | 在文档中插入红色提示文字"[此模块提取失败，请手动补充]" |

### 5.2 日志

使用 Python `logging` 模块 + `rich` 的 RichHandler：

- **控制台**：INFO 级别，显示进度和关键状态
- **文件日志**：DEBUG 级别，写入 `output/{filename}.log`，包含完整 Prompt、LLM 响应、token 用量

### 5.3 成本估算

预估每份招标文件（100 页）使用 qwen3.5-plus 的 API 成本：

| 项目 | 估算 |
|------|------|
| 文档总 token | ~60K-80K |
| 每模块输入 token | ~5K-20K（仅相关段落） |
| 每模块输出 token | ~1K-3K |
| LLM 调用次数 | 9-11 次（9个提取模块 + 可能的索引兜底/重试） |
| 总输入 token | ~120K（全部模块累计，均在 128K 最低价格档内） |
| 总输出 token | ~20K |
| **预计单次费用** | **输入 ~0.10 元 + 输出 ~0.10 元 ≈ 0.2 元/份** |

---

## 6. 依赖清单

### Python 依赖

```
# 文档解析
python-docx>=1.1.0
olefile>=0.47             # .doc 降级解析
pdfplumber>=0.11.0
charset-normalizer>=3.0   # 编码检测（处理 GBK/GB2312 文档）

# LLM 调用（DashScope 兼容 OpenAI 接口）
openai>=1.0.0

# 配置与工具
pyyaml>=6.0
rich>=13.0                # CLI 表格展示与交互

# 开发依赖
pytest>=8.0
```

### 系统依赖

| 依赖 | 用途 | 安装方式 |
|------|------|---------|
| LibreOffice | .doc → .docx 转换 | Windows: 安装 LibreOffice，确保 `soffice` 在 PATH 中 |

所有 Python 依赖通过阿里云镜像安装：`pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`

---

## 7. CLI 使用方式

```bash
# 完整流程（解析 → 提取 → 校对 → 生成）
python -m src.main analyze path/to/招标文件.docx

# 分步执行
python -m src.main parse path/to/招标文件.docx           # 仅解析+索引
python -m src.main extract output/parsed.json            # 仅LLM提取
python -m src.main review output/extracted.json           # 人工校对
python -m src.main generate output/reviewed.json          # 生成.docx

# 重跑单个模块
python -m src.main extract output/parsed.json --module module_c
```

---

## 8. 后续扩展（第二阶段）

第二阶段将在 CLI 基础上增加 Web 前端，供非技术团队使用：

- 前端：文件上传 → 进度展示 → 表单化校对界面 → 下载 .docx
- 后端：将 CLI 的五层 Pipeline 封装为 API
- 结构化 JSON 中间产物天然支持前后端分离

第二阶段不在本次设计范围内，但当前架构已为此预留扩展点：
- 所有层通过 JSON 文件通信，可直接替换为 API 请求/响应
- 校对层接口可从 CLI 切换为 Web 表单
- 样式配置外置，前端可提供样式自定义
