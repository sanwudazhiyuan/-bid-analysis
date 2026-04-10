# 招标文件智能解读系统 — 分阶段实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个从招标文件中自动提取结构化信息并生成三份 .docx 报告的 CLI 工具

**Architecture:** 五层 Pipeline（文档解析 → 分段索引 → LLM 提取 → 人工校对 → 文档生成），每层输入输出持久化为 JSON，支持断点续跑

**Tech Stack:** Python 3.11+, python-docx, pdfplumber, olefile, openai (DashScope 兼容), qwen3.5-plus, rich, pyyaml

**Spec:** `docs/specs/2026-03-19-bid-document-analyzer-design.md`

**测试用例文档:**
- 招标原文件: `（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc`
- 测试文档目录（解析效果验证）: `测试文档/` — 包含 7 个 .docx 招标文件
- 示例输出参考: `示例文档/` — 投标文件格式.docx、资料清单.docx、分析报告 PDF

---

## 阶段总览

| 阶段 | 名称 | 核心交付物 | 验收标准 | 预计工作量 |
|------|------|-----------|---------|-----------|
| P1 | 项目脚手架 + 数据模型 | 项目结构、配置、数据类 | pytest 通过，config 可加载 | 小 |
| P2 | 文档解析层（Layer 1） | .docx / .doc / .pdf 解析器 | 三种格式均能解析为 Paragraph 列表 | 中 |
| P3 | 分段索引层（Layer 2） | 规则切分 + 语义标签 | 示例文档切分出 ≥5 个章节，置信度 ≥0.7 | 中 |
| P4 | LLM 基础设施 + 首个提取模块 | Qwen API 封装 + module_a | 成功调用 API 并返回合法 JSON | 中 |
| P5 | 全部提取模块（Layer 3） | 9 个提取模块 + LLM 兜底索引 | 每个模块对示例文档输出合法 JSON | 大 |
| P6 | 人工校对层（Layer 4） | CLI 校对交互 | 能展示、通过、编辑、重跑模块 | 小 |
| P7 | 文档生成层（Layer 5） | 三份 .docx 生成器 | 输出文档结构与示例文档一致 | 中 |
| P8 | 端到端集成 + CLI 入口 | main.py 完整流程 | 一条命令完成全流程 | 小 |

---

## Phase 1: 项目脚手架 + 数据模型

**目标:** 搭建项目结构、配置文件、核心数据类，确保开发环境就绪。

### Task 1.1: 项目初始化

**Files:**
- Create: `src/__init__.py`
- Create: `src/parser/__init__.py`
- Create: `src/indexer/__init__.py`
- Create: `src/extractor/__init__.py`
- Create: `src/reviewer/__init__.py`
- Create: `src/generator/__init__.py`
- Create: `tests/__init__.py`
- Create: `requirements.txt`

- [ ] **Step 1: 创建项目目录结构**

```bash
cd d:/BaiduSyncdisk/标书项目/招标文件解读
mkdir -p src/parser src/indexer src/extractor src/reviewer src/generator tests config/prompts output
```

- [ ] **Step 2: 创建所有 `__init__.py`**

为 `src/`、`src/parser/`、`src/indexer/`、`src/extractor/`、`src/reviewer/`、`src/generator/`、`tests/` 各创建空的 `__init__.py`。

- [ ] **Step 3: 创建 `requirements.txt`**

```
python-docx>=1.1.0
olefile>=0.47
pdfplumber>=0.11.0
charset-normalizer>=3.0
openai>=1.0.0
pyyaml>=6.0
rich>=13.0
pytest>=8.0
```

- [ ] **Step 4: 安装依赖**

```bash
source .venv/Scripts/activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

- [ ] **Step 5: 验证安装**

```bash
python -c "import docx, pdfplumber, olefile, openai, yaml, rich; print('All imports OK')"
```

- [ ] **Step 6: Commit**

```bash
git init
git add -A
git commit -m "chore: project scaffolding and dependencies"
```

### Task 1.2: 核心数据模型

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 编写数据模型测试**

```python
# tests/test_models.py
from src.models import Paragraph, TaggedParagraph

def test_paragraph_creation():
    p = Paragraph(index=0, text="测试段落", style="Heading 1", is_table=False, table_data=None)
    assert p.index == 0
    assert p.text == "测试段落"
    assert p.style == "Heading 1"

def test_paragraph_table():
    p = Paragraph(index=1, text="", style=None, is_table=True, table_data=[["a", "b"], ["c", "d"]])
    assert p.is_table is True
    assert len(p.table_data) == 2

def test_tagged_paragraph():
    tp = TaggedParagraph(index=0, text="评分标准", section_title="第三章", section_level=1, tags=["评分"], table_data=None)
    assert "评分" in tp.tags
    assert tp.section_level == 1

def test_paragraph_to_dict():
    p = Paragraph(index=0, text="测试", style=None, is_table=False, table_data=None)
    d = p.to_dict()
    assert d["index"] == 0
    assert d["text"] == "测试"

def test_tagged_paragraph_to_dict():
    tp = TaggedParagraph(index=0, text="测试", section_title="章节", section_level=1, tags=["资格"], table_data=None)
    d = tp.to_dict()
    assert d["tags"] == ["资格"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 3: 实现数据模型**

```python
# src/models.py
from dataclasses import dataclass, field, asdict
from typing import Optional

@dataclass
class Paragraph:
    index: int
    text: str
    style: Optional[str] = None
    is_table: bool = False
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class TaggedParagraph:
    index: int
    text: str
    section_title: Optional[str] = None
    section_level: int = 0
    tags: list[str] = field(default_factory=list)
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_models.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat: add core data models (Paragraph, TaggedParagraph)"
```

### Task 1.3: 配置文件

**Files:**
- Create: `config/settings.yaml`
- Create: `config/synonyms.yaml`
- Create: `config/tag_rules.yaml`
- Create: `config/styles.yaml`
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 创建 `config/settings.yaml`**

```yaml
api:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "${DASHSCOPE_API_KEY}"  # 从环境变量读取
  model: "qwen3.5-plus"
  temperature: 0.1
  max_output_tokens: 65536
  enable_thinking: false
  retry: 3
  timeout: 120

output:
  dir: "output"

logging:
  console_level: "INFO"
  file_level: "DEBUG"
```

- [ ] **Step 2: 创建 `config/synonyms.yaml`**

```yaml
采购公告: ["采购公告", "招标公告", "比选公告", "邀请函"]
供应商须知: ["供应商须知", "投标人须知", "投标须知", "注意事项"]
评标办法: ["评标办法", "评审办法", "评分标准", "评分办法", "评标方法", "评标细则"]
合同条款: ["合同条款", "合同格式", "合同范本", "协议条款"]
技术要求: ["技术商务要求", "技术要求", "技术规格", "技术规范", "项目需求", "服务要求"]
投标格式: ["投标文件格式", "投标格式", "响应文件格式", "投标文件组成"]
```

- [ ] **Step 3: 创建 `config/tag_rules.yaml`**

```yaml
评分: ["评分", "得分", "扣分", "加分", "分值", "权重", "评审因素"]
资格: ["资格", "资质", "认证", "证书", "营业执照", "禁止情形"]
报价: ["报价", "报价表", "开标一览表", "单价", "总价", "限价", "预算"]
风险: ["废标", "无效标", "否决", "不予受理", "不合格"]
流程: ["开标", "评标", "定标", "签订合同", "投产"]
格式: ["投标文件格式", "签字盖章", "密封", "装订", "份数"]
材料: ["证明材料", "复印件", "扫描件", "加盖公章", "提供"]
合同: ["合同条款", "付款", "违约", "保密", "知识产权", "履约"]
```

- [ ] **Step 4: 创建 `config/styles.yaml`**

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

- [ ] **Step 5: 编写配置加载测试**

```python
# tests/test_config.py
import os
from src.config import load_settings, load_synonyms, load_tag_rules, load_styles

def test_load_settings():
    settings = load_settings()
    assert settings["api"]["model"] == "qwen3.5-plus"
    assert settings["api"]["temperature"] == 0.1

def test_load_synonyms():
    synonyms = load_synonyms()
    assert "采购公告" in synonyms
    assert "招标公告" in synonyms["采购公告"]

def test_load_tag_rules():
    rules = load_tag_rules()
    assert "评分" in rules
    assert "得分" in rules["评分"]

def test_load_styles():
    styles = load_styles()
    assert styles["styles"]["heading1"]["font"] == "微软雅黑"

def test_api_key_from_env():
    os.environ["DASHSCOPE_API_KEY"] = "test-key-123"
    settings = load_settings()
    assert settings["api"]["api_key"] == "test-key-123"
    del os.environ["DASHSCOPE_API_KEY"]
```

- [ ] **Step 6: 运行测试确认失败**

```bash
pytest tests/test_config.py -v
```

- [ ] **Step 7: 实现配置加载**

```python
# src/config.py
import os
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"

def _load_yaml(filename: str) -> dict:
    with open(CONFIG_DIR / filename, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_settings() -> dict:
    settings = _load_yaml("settings.yaml")
    # 替换环境变量占位符
    api_key = settings["api"].get("api_key", "")
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        settings["api"]["api_key"] = os.environ.get(env_var, "")
    return settings

def load_synonyms() -> dict:
    return _load_yaml("synonyms.yaml")

def load_tag_rules() -> dict:
    return _load_yaml("tag_rules.yaml")

def load_styles() -> dict:
    return _load_yaml("styles.yaml")
```

- [ ] **Step 8: 运行测试确认通过**

```bash
pytest tests/test_config.py -v
```
Expected: 5 passed

- [ ] **Step 9: Commit**

```bash
git add config/ src/config.py tests/test_config.py
git commit -m "feat: add config files and config loader"
```

### Task 1.4: 日志基础设施

**Files:**
- Create: `src/logger.py`
- Create: `tests/test_logger.py`

- [ ] **Step 1: 编写日志测试**

```python
# tests/test_logger.py
import logging
from src.logger import setup_logging

def test_setup_logging_returns_logger():
    logger = setup_logging("test_doc")
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.DEBUG

def test_log_file_created(tmp_path):
    logger = setup_logging("test_doc", log_dir=str(tmp_path))
    logger.info("test message")
    log_files = list(tmp_path.glob("*.log"))
    assert len(log_files) == 1
```

- [ ] **Step 2: 实现日志模块**

```python
# src/logger.py
import logging
from pathlib import Path
from rich.logging import RichHandler

def setup_logging(doc_name: str, log_dir: str = "output") -> logging.Logger:
    logger = logging.getLogger(f"bid_analyzer.{doc_name}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console: INFO via rich
    console = RichHandler(level=logging.INFO, show_path=False)
    logger.addHandler(console)

    # File: DEBUG
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        Path(log_dir) / f"{doc_name}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    return logger
```

- [ ] **Step 3: 运行测试，Commit**

### Phase 1 验收测试

```bash
pytest tests/ -v
```
Expected: 12 tests passed（5 models + 5 config + 2 logger）

---

## Phase 2: 文档解析层（Layer 1）

**目标:** 实现三种格式（.docx / .doc / .pdf）的解析，统一输出 `List[Paragraph]`。

**测试策略:** 使用项目中已有的真实招标文件进行测试，验证段落数量、表格识别、中文内容完整性。

### Task 2.1: .docx 解析器

**Files:**
- Create: `src/parser/docx_parser.py`
- Create: `tests/test_docx_parser.py`

- [ ] **Step 1: 编写 .docx 解析测试**

```python
# tests/test_docx_parser.py
import glob
import pytest
from src.parser.docx_parser import parse_docx
from src.models import Paragraph

# 测试文档目录下的全部 .docx 文件
TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))

def test_parse_docx_returns_paragraphs():
    """使用测试文档测试 .docx 解析"""
    result = parse_docx("测试文档/招标公告.docx")
    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(p, Paragraph) for p in result)

def test_parse_docx_has_tables():
    result = parse_docx("测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx")
    tables = [p for p in result if p.is_table]
    assert len(tables) > 0

def test_parse_docx_preserves_style_info():
    """验证样式字段被正确填充（即使值为 None，字段应存在）"""
    result = parse_docx("测试文档/招标公告.docx")
    for p in result:
        assert hasattr(p, "style")  # 字段必须存在

def test_parse_docx_table_data():
    result = parse_docx("测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx")
    tables = [p for p in result if p.is_table and p.table_data]
    if tables:
        first_table = tables[0]
        assert isinstance(first_table.table_data, list)
        assert isinstance(first_table.table_data[0], list)

@pytest.mark.parametrize("docx_path", TEST_DOCX_FILES, ids=lambda p: p.split("/")[-1].split("\\")[-1])
def test_parse_all_test_documents(docx_path):
    """对 测试文档/ 下每个 .docx 验证：可解析、有段落、有中文"""
    result = parse_docx(docx_path)
    assert isinstance(result, list), f"{docx_path} 返回类型错误"
    assert len(result) > 0, f"{docx_path} 解析后段落数为0"
    texts = [p.text for p in result if p.text.strip()]
    assert len(texts) > 0, f"{docx_path} 无有效文本"
    # 招标文件必定包含中文
    has_chinese = any(any('\u4e00' <= c <= '\u9fff' for c in t) for t in texts)
    assert has_chinese, f"{docx_path} 未检测到中文内容"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_docx_parser.py -v
```

- [ ] **Step 3: 实现 .docx 解析器**

```python
# src/parser/docx_parser.py
from docx import Document
from src.models import Paragraph

def parse_docx(file_path: str) -> list[Paragraph]:
    doc = Document(file_path)
    paragraphs = []
    idx = 0

    # 解析正文段落
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name if para.style else None
        paragraphs.append(Paragraph(
            index=idx,
            text=text,
            style=style_name,
            is_table=False,
            table_data=None,
        ))
        idx += 1

    # 解析表格
    for table in doc.tables:
        rows_data = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows_data.append(cells)
        if rows_data:
            # 用第一行作为表格摘要文本
            summary = " | ".join(rows_data[0]) if rows_data else ""
            paragraphs.append(Paragraph(
                index=idx,
                text=summary,
                style=None,
                is_table=True,
                table_data=rows_data,
            ))
            idx += 1

    return paragraphs
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_docx_parser.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parser/docx_parser.py tests/test_docx_parser.py
git commit -m "feat: implement .docx parser"
```

### Task 2.2: .doc 解析器（LibreOffice 转换）

**Files:**
- Create: `src/parser/doc_parser.py`
- Create: `tests/test_doc_parser.py`

- [ ] **Step 1: 编写 .doc 解析测试**

```python
# tests/test_doc_parser.py
import pytest
from src.parser.doc_parser import parse_doc, check_libreoffice
from src.models import Paragraph

@pytest.fixture
def doc_file():
    return "（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc"

def test_libreoffice_available():
    """检查 LibreOffice 是否已安装"""
    available = check_libreoffice()
    if not available:
        pytest.skip("LibreOffice not installed")

def test_parse_doc_returns_paragraphs(doc_file):
    result = parse_doc(doc_file)
    assert isinstance(result, list)
    assert len(result) > 50  # 招标文件应有大量段落

def test_parse_doc_has_chinese_text(doc_file):
    result = parse_doc(doc_file)
    texts = [p.text for p in result if p.text.strip()]
    assert any("采购" in t for t in texts)
    assert any("投标" in t for t in texts)

def test_parse_doc_has_tables(doc_file):
    result = parse_doc(doc_file)
    tables = [p for p in result if p.is_table]
    assert len(tables) > 0  # 招标文件一定有表格
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 .doc 解析器**

核心逻辑：
1. 检查 LibreOffice 是否可用（`shutil.which("soffice")`）
2. 调用 `soffice --headless --convert-to docx` 转换到临时目录
3. 用 `docx_parser.parse_docx()` 解析转换后的 .docx
4. 清理临时文件
5. 降级：如果 LibreOffice 不可用，尝试 olefile 提取纯文本
6. 降级路径中使用 `charset_normalizer.detect()` 检测文本编码（处理 GBK/GB2312）

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_doc_parser.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parser/doc_parser.py tests/test_doc_parser.py
git commit -m "feat: implement .doc parser with LibreOffice conversion"
```

### Task 2.3: PDF 解析器

**Files:**
- Create: `src/parser/pdf_parser.py`
- Create: `tests/test_pdf_parser.py`

- [ ] **Step 1: 创建一个测试用 PDF**

由于现有示例 PDF 是图片格式，需要先准备一个文本型 PDF 用于单元测试。测试中可以将 .docx 示例文档另存为 PDF，或编写一个 fixture 用 reportlab 生成简单的测试 PDF。

也可以在测试中使用条件跳过：如果 PDF 无法提取文本则跳过部分测试。

- [ ] **Step 2: 编写 PDF 解析测试**

```python
# tests/test_pdf_parser.py
from src.parser.pdf_parser import parse_pdf
from src.models import Paragraph

def test_parse_pdf_returns_list():
    """基本功能测试 — 使用一个有文字的 PDF"""
    # 注意：如果仅有图片PDF则此测试可能段落为空
    result = parse_pdf("示例文档/DeepAnalysis_Analysis_20260319.pdf")
    assert isinstance(result, list)

def test_parse_pdf_table_extraction():
    """如果 PDF 有可提取的表格"""
    result = parse_pdf("示例文档/DeepAnalysis_Analysis_20260319.pdf")
    # 该PDF可能是图片格式，表格提取可能为空，这里仅检查不抛异常
    assert isinstance(result, list)
```

- [ ] **Step 3: 实现 PDF 解析器**

核心逻辑：
1. 用 pdfplumber 打开 PDF
2. 逐页提取文本和表格
3. 通过字号/加粗推断标题层级（如果字体信息可用）
4. 返回 `List[Paragraph]`

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add src/parser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDF parser"
```

### Task 2.4: 统一解析接口

**Files:**
- Create: `src/parser/unified.py`
- Create: `tests/test_unified_parser.py`

- [ ] **Step 1: 编写统一接口测试**

```python
# tests/test_unified_parser.py
import glob
import pytest
from src.parser.unified import parse_document

TEST_DOCX_FILES = sorted(glob.glob("测试文档/*.docx"))

def test_parse_docx():
    result = parse_document("测试文档/招标公告.docx")
    assert len(result) > 0

def test_parse_doc():
    result = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    assert len(result) > 0

def test_parse_unsupported_format():
    with pytest.raises(ValueError, match="不支持的文件格式"):
        parse_document("test.txt")

@pytest.mark.parametrize("docx_path", TEST_DOCX_FILES, ids=lambda p: p.split("/")[-1].split("\\")[-1])
def test_unified_parse_all_test_documents(docx_path):
    """统一接口对 测试文档/ 下每个文件均能成功解析"""
    result = parse_document(docx_path)
    assert len(result) > 0, f"{docx_path} 解析后段落数为0"
```

- [ ] **Step 2: 实现统一接口**

```python
# src/parser/unified.py
from pathlib import Path
from src.models import Paragraph
from src.parser.docx_parser import parse_docx
from src.parser.doc_parser import parse_doc
from src.parser.pdf_parser import parse_pdf

def parse_document(file_path: str) -> list[Paragraph]:
    ext = Path(file_path).suffix.lower()
    if ext == ".docx":
        return parse_docx(file_path)
    elif ext == ".doc":
        return parse_doc(file_path)
    elif ext == ".pdf":
        return parse_pdf(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")
```

- [ ] **Step 3: 运行全部 Layer 1 测试**

```bash
pytest tests/test_docx_parser.py tests/test_doc_parser.py tests/test_pdf_parser.py tests/test_unified_parser.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/parser/unified.py tests/test_unified_parser.py
git commit -m "feat: unified document parser interface"
```

### Task 2.5: 中间结果持久化（Layer 1 输出）

**Files:**
- Create: `src/persistence.py`
- Create: `tests/test_persistence.py`

- [ ] **Step 1: 编写持久化测试**

```python
# tests/test_persistence.py
import json
import pytest
from src.models import Paragraph
from src.persistence import (
    save_parsed, load_parsed,
    save_extracted, load_extracted,
    save_reviewed, load_reviewed,
)

def test_save_and_load_parsed(tmp_path):
    paragraphs = [
        Paragraph(0, "测试段落", style="Heading 1", is_table=False, table_data=None),
        Paragraph(1, "表格", style=None, is_table=True, table_data=[["a", "b"]]),
    ]
    path = str(tmp_path / "test_parsed.json")
    save_parsed(paragraphs, path)
    loaded = load_parsed(path)
    assert len(loaded) == 2
    assert loaded[0].text == "测试段落"
    assert loaded[1].is_table is True
    assert loaded[1].table_data == [["a", "b"]]

def test_load_rejects_incompatible_version(tmp_path):
    """schema_version 不匹配时应抛出 ValueError"""
    path = str(tmp_path / "old.json")
    with open(path, "w") as f:
        json.dump({"schema_version": "0.1", "paragraphs": []}, f)
    with pytest.raises(ValueError, match="schema_version"):
        load_parsed(path)

def test_save_and_load_extracted(tmp_path):
    data = {
        "schema_version": "1.0",
        "modules": {"module_a": {"title": "A. 项目概况", "sections": []}}
    }
    path = str(tmp_path / "extracted.json")
    save_extracted(data, path)
    loaded = load_extracted(path)
    assert "module_a" in loaded["modules"]
    assert "generated_at" in loaded

def test_save_and_load_reviewed(tmp_path):
    data = {
        "schema_version": "1.0",
        "modules": {"module_a": {"title": "A. 项目概况", "sections": []}}
    }
    path = str(tmp_path / "reviewed.json")
    save_reviewed(data, path)
    loaded = load_reviewed(path)
    assert "reviewed_at" in loaded
```

- [ ] **Step 2: 实现持久化模块**

```python
# src/persistence.py
import json
from datetime import datetime
from src.models import Paragraph, TaggedParagraph

def save_parsed(paragraphs: list[Paragraph], path: str):
    data = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "paragraphs": [p.to_dict() for p in paragraphs],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

CURRENT_SCHEMA_VERSION = "1.0"

def _check_version(data: dict, path: str):
    """检查 schema_version，不兼容时抛出 ValueError 提示用户重新提取"""
    version = data.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"文件 {path} 的 schema_version={version}，"
            f"当前版本={CURRENT_SCHEMA_VERSION}，请重新运行对应阶段"
        )

def load_parsed(path: str) -> list[Paragraph]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    return [Paragraph(**p) for p in data["paragraphs"]]

def save_indexed(index_result: dict, path: str):
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
    reviewed["reviewed_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reviewed, f, ensure_ascii=False, indent=2)

def load_reviewed(path: str) -> dict:
    """加载 Layer 4 校对结果"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _check_version(data, path)
    return data
```

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: Commit**

```bash
git add src/persistence.py tests/test_persistence.py
git commit -m "feat: add JSON persistence for parsed and indexed results"
```

### Phase 2 验收测试

**验收标准：**
1. **测试文档全量通过**：`测试文档/` 目录下全部 7 个 .docx 文件均能成功解析为 `List[Paragraph]`，段落数 > 0，包含中文内容
2. `.doc 解析`：`parse_document("（8）...项目.doc")` 返回 >50 个段落，包含表格和中文
3. 三种格式的输出均为 `List[Paragraph]`，字段完整
4. 错误格式抛出 `ValueError`
5. `save_parsed` / `load_parsed` 能正确序列化/反序列化，中文无乱码

**测试文档清单（必须全部通过）：**
- `测试文档/【招标文件】中国建设银行天津市分行社保卡便携式即时制卡机项目（发布版）.docx`
- `测试文档/【招标文件】甘肃银行借记IC空白卡及个人化外包服务采购项目-终稿.docx`
- `测试文档/分散采购比选文件（社保卡移动制卡机具采购）.docx`
- `测试文档/招标公告.docx`
- `测试文档/招标文件-2025-A-01-044-信用卡制卡工艺及寄送项目（二次招标）.docx`
- `测试文档/普洱市人民医院医保刷脸终端设备采购（单一来源）.docx`
- `测试文档/河北省农村信用社联合社智慧银行等自助设备入围项目交流公告.docx`

```bash
pytest tests/ -v -k "parser or unified or persistence"
```

---

## Phase 3: 分段索引层（Layer 2）

**目标:** 将 `List[Paragraph]` 切分为带章节归属和语义标签的 `List[TaggedParagraph]`。

**测试策略:** 使用 Phase 2 的真实解析结果，验证章节数量、标签准确性、置信度计算。

### Task 3.1: 规则切分器

**Files:**
- Create: `src/indexer/rule_splitter.py`
- Create: `tests/test_rule_splitter.py`

- [ ] **Step 1: 编写规则切分测试**

测试四种策略：Word 样式、编号模式、关键词匹配、目录解析。
重点测试：
- 编号模式正则能匹配 "第一章"、"第二章"、"一、"、"1.1"、"（一）" 等
- 关键词匹配能识别 "采购公告"、"评标办法" 等（含同义词）
- 置信度计算逻辑正确

```python
# tests/test_rule_splitter.py
from src.models import Paragraph
from src.indexer.rule_splitter import (
    split_by_numbering,
    split_by_keywords,
    compute_confidence,
    rule_split,
)

def test_split_by_numbering_chinese():
    paragraphs = [
        Paragraph(0, "第一章 采购公告", style=None, is_table=False, table_data=None),
        Paragraph(1, "内容段落1", style=None, is_table=False, table_data=None),
        Paragraph(2, "第二章 供应商须知", style=None, is_table=False, table_data=None),
        Paragraph(3, "内容段落2", style=None, is_table=False, table_data=None),
    ]
    sections = split_by_numbering(paragraphs)
    assert len(sections) == 2
    assert sections[0]["title"] == "第一章 采购公告"

def test_split_by_keywords():
    paragraphs = [
        Paragraph(0, "采购公告", style=None, is_table=False, table_data=None),
        Paragraph(1, "xxx", style=None, is_table=False, table_data=None),
        Paragraph(2, "评标办法", style=None, is_table=False, table_data=None),
    ]
    sections = split_by_keywords(paragraphs)
    assert len(sections) >= 2

def test_confidence_calculation():
    score = compute_confidence(found_sections=5, total_paragraphs=100, assigned_paragraphs=90)
    assert 0 <= score <= 1
    assert score > 0.7

def test_confidence_low_when_few_sections():
    score = compute_confidence(found_sections=1, total_paragraphs=100, assigned_paragraphs=20)
    assert score < 0.7

def test_rule_split_on_real_document():
    """使用真实文档测试完整规则切分"""
    from src.parser.unified import parse_document
    paragraphs = parse_document("示例文档/投标文件格式.docx")
    result = rule_split(paragraphs)
    assert result["confidence"] > 0, "真实文档置信度应大于0"
    assert len(result["sections"]) >= 2, "投标文件格式至少应有2个章节"
    # 验证每个 section 有必要字段
    for sec in result["sections"]:
        assert "title" in sec
        assert "start" in sec
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现规则切分器**

核心实现：
- `split_by_style(paragraphs)` — 解析 Heading 样式
- `split_by_numbering(paragraphs)` — 正则匹配 `第[一二三四五六七八九十]+章`、`\d+\.\d+` 等
- `split_by_keywords(paragraphs)` — 基于 synonyms.yaml 匹配
- `split_by_toc(paragraphs)` — 检测目录区域并解析
- `compute_confidence(found, total, assigned)` — 置信度公式
- `rule_split(paragraphs)` — 运行4种策略，取置信度最高的

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

### Task 3.2: 语义标签打标器

**Files:**
- Create: `src/indexer/tagger.py`
- Create: `tests/test_tagger.py`

- [ ] **Step 1: 编写标签测试**

```python
# tests/test_tagger.py
from src.models import Paragraph, TaggedParagraph
from src.indexer.tagger import tag_paragraphs

def test_tag_scoring_content():
    paragraphs = [
        Paragraph(0, "评分标准如下，满分100分", style=None, is_table=False, table_data=None),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("评标办法", 1)})
    assert "评分" in tagged[0].tags

def test_tag_qualification_content():
    paragraphs = [
        Paragraph(0, "供应商须提供有效营业执照", style=None, is_table=False, table_data=None),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("供应商须知", 1)})
    assert "资格" in tagged[0].tags

def test_multiple_tags():
    paragraphs = [
        Paragraph(0, "投标保证金不符合要求的，否决投标", style=None, is_table=False, table_data=None),
    ]
    tagged = tag_paragraphs(paragraphs, section_assignments={0: ("供应商须知", 1)})
    assert "风险" in tagged[0].tags or "报价" in tagged[0].tags
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现标签打标器**

核心逻辑：
1. 加载 `config/tag_rules.yaml`
2. 对每个段落，扫描文本中是否包含各标签的关键词
3. 匹配到的标签加入 `tags` 列表
4. 同时考虑所属章节标题（如属于"评标办法"章节的段落自动加"评分"标签）

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

### Task 3.3: 索引层集成（rule_split + tagger）

**Files:**
- Create: `src/indexer/indexer.py`（索引层统一入口）
- Create: `tests/test_indexer_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_indexer_integration.py
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

def test_index_real_docx():
    paragraphs = parse_document("示例文档/投标文件格式.docx")
    index_result = build_index(paragraphs)
    assert index_result["confidence"] >= 0
    tagged = index_result["tagged_paragraphs"]
    assert len(tagged) > 0
    # 至少部分段落应被打标
    tagged_with_tags = [tp for tp in tagged if tp.tags]
    assert len(tagged_with_tags) > 0
```

- [ ] **Step 2: 实现索引层入口**

```python
# src/indexer/indexer.py
from src.models import Paragraph, TaggedParagraph
from src.indexer.rule_splitter import rule_split
from src.indexer.tagger import tag_paragraphs

def build_index(paragraphs: list[Paragraph]) -> dict:
    split_result = rule_split(paragraphs)
    section_assignments = split_result["assignments"]  # {para_index: (section_title, level)}
    tagged = tag_paragraphs(paragraphs, section_assignments)
    return {
        "confidence": split_result["confidence"],
        "sections": split_result["sections"],
        "tagged_paragraphs": tagged,
    }
```

- [ ] **Step 3: 运行全部 Layer 2 测试**

```bash
pytest tests/ -v -k "splitter or tagger or indexer"
```

- [ ] **Step 4: Commit**

### Phase 3 验收测试

**验收标准：**
1. 对示例 .docx 文件，规则切分能识别出章节结构
2. 对真实 .doc 招标文件（转换后），能识别出 ≥5 个大章节
3. 语义标签覆盖："评分"、"资格"、"报价"、"风险"、"格式"标签均有段落命中
4. 置信度计算输出合理数值

```bash
pytest tests/ -v -k "splitter or tagger or indexer"
```

**手动验证（可选）：** 编写一个临时脚本打印索引结果，肉眼确认章节切分是否合理。

---

## Phase 4: LLM 基础设施 + 首个提取模块

**目标:** 封装 Qwen API 调用逻辑，实现第一个提取模块（module_a）验证端到端 LLM 调用。

**测试策略:** 使用真实 API 调用（需配置 DASHSCOPE_API_KEY 环境变量）。提供 mock 测试用于 CI 环境。

### Task 4.1: LLM 基础调用封装

**Files:**
- Create: `src/extractor/base.py`
- Create: `tests/test_extractor_base.py`

- [ ] **Step 1: 编写基础调用测试**

测试要点：
- token 数估算（字符数 × 0.6）
- JSON 解析（正常 JSON、带 markdown 代码块的 JSON、非法 JSON 修复）
- 重试逻辑（mock API 失败场景）

```python
# tests/test_extractor_base.py
from src.extractor.base import estimate_tokens, parse_llm_json, build_messages

def test_estimate_tokens_chinese():
    text = "这是一段中文测试文本"
    tokens = estimate_tokens(text)
    assert tokens == int(len(text) * 0.6)

def test_parse_llm_json_normal():
    raw = '{"title": "A. 项目信息", "sections": []}'
    result = parse_llm_json(raw)
    assert result["title"] == "A. 项目信息"

def test_parse_llm_json_with_markdown():
    raw = '```json\n{"title": "test"}\n```'
    result = parse_llm_json(raw)
    assert result["title"] == "test"

def test_parse_llm_json_invalid():
    raw = 'not json at all'
    result = parse_llm_json(raw)
    assert result is None

def test_build_messages():
    msgs = build_messages(system="你是专家", user="提取信息")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
```

- [ ] **Step 2: 实现基础调用封装**

`src/extractor/base.py` 包含：
- `estimate_tokens(text)` — 中文 token 估算
- `parse_llm_json(raw_text)` — 从 LLM 输出中提取 JSON（处理 markdown 包裹、尾部截断等）
- `build_messages(system, user)` — 构建 OpenAI 格式消息
- `call_qwen(messages, settings)` — 调用 DashScope API，含重试和限流处理
- `load_prompt_template(module_name)` — 加载 prompt 模板文件
- `batch_paragraphs(paragraphs, max_tokens=120000)` — 将段落按章节边界分批，每批 ≤ max_tokens
- `merge_batch_results(results)` — 按 section id 合并多批结果（同 id 取最后一批）

额外测试（添加到 `tests/test_extractor_base.py`）：

```python
def test_batch_paragraphs_splits_correctly():
    # 构造超长段落列表
    from src.models import TaggedParagraph
    large_paras = [
        TaggedParagraph(i, "x" * 1000, section_title=f"第{i//10}章", section_level=1, tags=[], table_data=None)
        for i in range(200)
    ]
    batches = batch_paragraphs(large_paras, max_tokens=50000)
    assert len(batches) > 1
    # 验证不在表格/章节中间断开
    for batch in batches:
        assert estimate_tokens("".join(p.text for p in batch)) <= 50000

def test_merge_batch_results():
    r1 = {"sections": [{"id": "A1", "title": "v1"}, {"id": "A2", "title": "v1"}]}
    r2 = {"sections": [{"id": "A1", "title": "v2"}]}  # A1 被更新
    merged = merge_batch_results([r1, r2])
    a1 = [s for s in merged["sections"] if s["id"] == "A1"][0]
    assert a1["title"] == "v2"  # 取最后一批

from unittest.mock import patch, MagicMock
import time

def test_rate_limit_retry():
    """验证 429 限流时使用指数退避重试"""
    mock_response = MagicMock()
    mock_response.status_code = 429
    with patch("src.extractor.base._raw_api_call") as mock_call:
        mock_call.side_effect = [
            Exception("Rate limit"),  # 第1次失败
            Exception("Rate limit"),  # 第2次失败
            {"title": "OK", "sections": []},  # 第3次成功
        ]
        # 此测试验证最终能返回结果（具体退避时间由 mock 跳过）
```

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: Commit**

### Task 4.2: Prompt 模板 + module_a 提取

**Files:**
- Create: `config/prompts/module_a.txt`
- Create: `src/extractor/module_a.py`
- Create: `tests/test_module_a.py`

- [ ] **Step 1: 编写 module_a 的 prompt 模板**

`config/prompts/module_a.txt`：包含角色指令、JSON Schema 说明、few-shot 示例（基于重庆农商行示例）。

- [ ] **Step 2: 编写 module_a 测试**

```python
# tests/test_module_a.py
import pytest
import os
from src.extractor.module_a import extract_module_a
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

@pytest.fixture
def indexed_doc():
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    return build_index(paragraphs)

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_extract_module_a(indexed_doc):
    result = extract_module_a(indexed_doc["tagged_paragraphs"])
    assert result is not None
    assert result["title"].startswith("A")
    assert len(result["sections"]) > 0

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_a_has_project_name(indexed_doc):
    result = extract_module_a(indexed_doc["tagged_paragraphs"])
    # 应该能提取到项目名称
    all_text = str(result)
    assert "重庆" in all_text or "信用卡" in all_text

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_a_json_schema(indexed_doc):
    result = extract_module_a(indexed_doc["tagged_paragraphs"])
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")
```

- [ ] **Step 3: 实现 module_a 提取逻辑**

核心流程：
1. 从 `tagged_paragraphs` 中筛选标签含"采购公告"或"资格"的段落
2. 加载 `config/prompts/module_a.txt` 模板
3. 拼接 prompt + 段落文本
4. 调用 `call_qwen()`
5. 解析返回的 JSON

- [ ] **Step 4: 运行测试（需设置环境变量）**

```bash
export DASHSCOPE_API_KEY=your-key-here
pytest tests/test_module_a.py -v
```

- [ ] **Step 5: Commit**

### Phase 4 验收测试

**验收标准：**
1. `call_qwen()` 能成功调用 DashScope API
2. `parse_llm_json()` 能正确处理正常 JSON 和 markdown 包裹的 JSON
3. `extract_module_a()` 对真实招标文件返回合法的结构化 JSON
4. 返回的 JSON 包含项目名称、采购编号等关键信息

```bash
# 无需 API Key 的测试
pytest tests/test_extractor_base.py -v

# 需要 API Key 的测试
DASHSCOPE_API_KEY=xxx pytest tests/test_module_a.py -v
```

---

## Phase 5: 全部提取模块（Layer 3）

**目标:** 实现剩余 8 个提取模块 + LLM 兜底索引。

**测试策略:** 每个模块对真实文档测试，验证 JSON 合法性和关键内容覆盖。

### Task 5.1 ~ 5.2: module_b, module_d

每个模块遵循相同模式：

1. 编写 prompt 模板（`config/prompts/module_X.txt`）
2. 编写测试（验证 JSON schema + 关键内容）
3. 实现提取逻辑
4. 运行测试
5. Commit

**简单模块列表与关键验证点：**

| 模块 | 关键验证内容 |
|------|-------------|
| module_b | 包含"营业执照"、"禁止情形"等资格要求 |
| module_d | 包含合同条款要点（付款、违约等） |

### Task 5.3: module_c — 评标办法与评分标准

module_c 是最复杂的模块之一，需要精确提取评分表结构（多层嵌套的评分项及其分值）。

**Files:**
- Create: `config/prompts/module_c.txt`
- Create: `src/extractor/module_c.py`
- Create: `tests/test_module_c.py`

- [ ] **Step 1: 编写 module_c 的 prompt 模板**

`config/prompts/module_c.txt` 核心要点：

```text
你是招标文件分析专家。请从以下招标文件内容中提取【评标办法与评分标准】。

## 提取要求
1. 识别评标方法类型（综合评分法/最低价法/性价比法等）
2. 提取评分大类及其权重（如：报价分、商务分、技术分）
3. 提取每个评分大类下的细分评分项，包括：
   - 评分项名称
   - 分值/权重
   - 评分标准描述（如何得分、扣分规则）
4. 如果存在价格评分公式，完整提取公式内容

## 输出 JSON 格式
{
  "title": "C. 评标办法与评分标准",
  "sections": [
    {
      "id": "C1",
      "title": "评标方法",
      "type": "key_value_table",
      "columns": ["项目", "内容"],
      "rows": [
        ["评标方法", "综合评分法"],
        ["价格权重", "70%"],
        ["商务权重", "20%"],
        ["技术权重", "10%"]
      ]
    },
    {
      "id": "C2",
      "title": "评分细则",
      "type": "standard_table",
      "columns": ["评分项", "分值", "评分标准"],
      "rows": [
        ["报价得分", "70分", "最低价÷投标价×70"],
        ["营业执照年限", "5分", "≥5年得5分，3-5年得3分，<3年得1分"],
        ...
      ]
    },
    {
      "id": "C3",
      "title": "价格评分公式",
      "type": "text",
      "content": "价格得分 = (评标基准价 / 投标报价) × 价格权重 × 100"
    }
  ]
}

## 注意事项
- 评分表可能跨多页，以表格或正文形式出现，请完整提取
- 如果存在"评标办法"和"评分表"两个独立章节，需要合并
- 分值加总应与总分一致（通常为100分），如有偏差请标注
```

- [ ] **Step 2: 编写 module_c 测试**

```python
# tests/test_module_c.py
import pytest
import os
from src.extractor.module_c import extract_module_c
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

@pytest.fixture
def indexed_doc():
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    return build_index(paragraphs)

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_c_json_schema(indexed_doc):
    result = extract_module_c(indexed_doc["tagged_paragraphs"])
    assert result is not None
    assert result["title"].startswith("C")
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_c_has_scoring_breakdown(indexed_doc):
    """评分标准必须包含报价/商务/技术三大类及其权重"""
    result = extract_module_c(indexed_doc["tagged_paragraphs"])
    all_text = str(result).lower()
    # 示例文档评分构成：报价70%、商务20%、技术10%
    assert "70" in all_text, "应包含报价权重70%"
    assert "20" in all_text, "应包含商务权重20%"
    assert "10" in all_text, "应包含技术权重10%"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_c_has_detail_items(indexed_doc):
    """应提取出多条评分细则，不只是大类"""
    result = extract_module_c(indexed_doc["tagged_paragraphs"])
    total_rows = 0
    for section in result["sections"]:
        if section["type"] in ("standard_table", "key_value_table"):
            total_rows += len(section.get("rows", []))
    assert total_rows >= 5, f"评分细则应至少有5条，实际: {total_rows}"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_c_price_formula(indexed_doc):
    """如果存在价格评分公式，应完整提取"""
    result = extract_module_c(indexed_doc["tagged_paragraphs"])
    all_text = str(result)
    # 价格公式通常含"评标基准价"或"投标报价"
    has_formula = "基准价" in all_text or "投标报价" in all_text or "价格得分" in all_text
    assert has_formula, "应提取价格评分公式"
```

- [ ] **Step 3: 实现 module_c 提取逻辑**

核心流程：
1. 从 `tagged_paragraphs` 中筛选标签含"评标"、"评分"、"评审"的段落
2. 加载 `config/prompts/module_c.txt` 模板
3. 拼接 prompt + 段落文本（评分表可能跨多个章节，需合并"评标办法"和"评分表"章节）
4. 调用 `call_qwen()`
5. 解析返回的 JSON，校验分值加总

- [ ] **Step 4: 运行测试**

```bash
DASHSCOPE_API_KEY=xxx pytest tests/test_module_c.py -v
```

- [ ] **Step 5: Commit**

### Task 5.4: module_e — 废标/无效标风险提示

module_e 需要从全文中识别散落的废标条款并评估风险等级，是另一个高复杂度模块。

**Files:**
- Create: `config/prompts/module_e.txt`
- Create: `src/extractor/module_e.py`
- Create: `tests/test_module_e.py`

- [ ] **Step 1: 编写 module_e 的 prompt 模板**

`config/prompts/module_e.txt` 核心要点：

```text
你是招标文件分析专家。请从以下招标文件内容中提取【废标/无效标风险提示】。

## 提取要求
1. 识别所有可能导致投标无效或废标的条款
2. 风险项来源包括但不限于：
   - 明确标注"否则视为无效投标"的条款
   - 资格条件中的硬性要求（如必须提供原件）
   - 文件格式/密封/递交时间等程序性要求
   - 评分标准中的"不得分"或"扣除全部分数"条款
3. 为每个风险项评估风险等级：
   - 高：直接导致废标/无效标
   - 中：可能导致重大扣分（≥10分）
   - 低：可能导致少量扣分（<10分）
4. 标注每条风险来源的原文位置（章节号或关键词）

## 输出 JSON 格式
{
  "title": "E. 废标/无效标风险提示",
  "sections": [
    {
      "id": "E1",
      "title": "高风险项（直接废标）",
      "type": "standard_table",
      "columns": ["序号", "风险项", "原文依据", "来源章节"],
      "rows": [
        ["1", "投标文件未按要求密封", "未按规定密封的投标文件将被拒绝", "第三章"],
        ["2", "未在截止时间前递交", "逾期送达的投标文件恕不接受", "第一章"],
        ...
      ]
    },
    {
      "id": "E2",
      "title": "中风险项（重大扣分）",
      "type": "standard_table",
      "columns": ["序号", "风险项", "影响分值", "原文依据"],
      "rows": [...]
    }
  ]
}

## 注意事项
- 废标条款通常散落在文档各处（投标须知、评分标准、资格条件等），需要全文扫描
- 注意区分"必须"/"应当"（硬性）和"可以"/"建议"（软性）的措辞差异
- 同一风险项如果在多处提及，合并为一条并列出所有来源
```

- [ ] **Step 2: 编写 module_e 测试**

```python
# tests/test_module_e.py
import pytest
import os
from src.extractor.module_e import extract_module_e
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

@pytest.fixture
def indexed_doc():
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    return build_index(paragraphs)

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_e_json_schema(indexed_doc):
    result = extract_module_e(indexed_doc["tagged_paragraphs"])
    assert result is not None
    assert result["title"].startswith("E")
    for section in result["sections"]:
        assert "id" in section
        assert "type" in section
        assert section["type"] in ("key_value_table", "standard_table", "text", "parent")

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_e_has_risk_levels(indexed_doc):
    """风险项应按高/中/低分级"""
    result = extract_module_e(indexed_doc["tagged_paragraphs"])
    all_text = str(result)
    assert "高风险" in all_text or "高" in all_text, "应包含高风险分类"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_e_has_source_reference(indexed_doc):
    """每个风险项应有原文依据或来源章节"""
    result = extract_module_e(indexed_doc["tagged_paragraphs"])
    for section in result["sections"]:
        if section["type"] == "standard_table" and len(section.get("rows", [])) > 0:
            cols = section["columns"]
            # 应存在"原文依据"或"来源章节"列
            has_source_col = any("依据" in c or "来源" in c or "章节" in c for c in cols)
            assert has_source_col, f"表格应包含来源依据列，实际列: {cols}"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_e_minimum_risk_items(indexed_doc):
    """至少应识别出3条风险项"""
    result = extract_module_e(indexed_doc["tagged_paragraphs"])
    total_rows = 0
    for section in result["sections"]:
        if section["type"] == "standard_table":
            total_rows += len(section.get("rows", []))
    assert total_rows >= 3, f"应至少识别3条风险项，实际: {total_rows}"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_module_e_covers_multiple_sources(indexed_doc):
    """风险项应来自文档多个章节，不只是一个章节"""
    result = extract_module_e(indexed_doc["tagged_paragraphs"])
    sources = set()
    for section in result["sections"]:
        if section["type"] == "standard_table":
            for row in section.get("rows", []):
                # 最后一列通常是来源章节
                if len(row) > 0:
                    sources.add(row[-1])
    assert len(sources) >= 2, f"风险来源应覆盖多个章节，实际来源: {sources}"
```

- [ ] **Step 3: 实现 module_e 提取逻辑**

核心流程：
1. module_e 需要扫描全文（不仅限于特定章节），因为废标条款散落各处
2. 从 `tagged_paragraphs` 中提取全部段落文本（或筛选含"废标"、"无效"、"否则"、"必须"等关键词的段落 + 上下文）
3. 加载 `config/prompts/module_e.txt` 模板
4. 调用 `call_qwen()`
5. 解析返回的 JSON

注意：module_e 的输入范围比其他模块大（可能需要全文），如果总 token 超限则使用 `batch_paragraphs()` 分批处理后合并。

- [ ] **Step 4: 运行测试**

```bash
DASHSCOPE_API_KEY=xxx pytest tests/test_module_e.py -v
```

- [ ] **Step 5: Commit**

### Task 5.5 ~ 5.6: module_f, module_g

每个模块遵循相同模式（prompt → test → implement → verify → commit）：

| 模块 | 关键验证内容 |
|------|-------------|
| module_f | 包含文件组成、份数、密封等要求 |
| module_g | 包含开标流程步骤和定标规则 |

### Task 5.7: bid_format — 投标文件格式提取

bid_format 驱动独立的 .docx 交付物（投标文件格式模板），需要完整提取各表格模板结构。

**Files:**
- Create: `config/prompts/bid_format.txt`
- Create: `src/extractor/bid_format.py`
- Create: `tests/test_bid_format.py`

- [ ] **Step 1: 编写 bid_format 的 prompt 模板**

`config/prompts/bid_format.txt` 核心要点：

```text
你是招标文件分析专家。请从以下招标文件内容中提取【投标文件格式模板】。

## 提取要求
1. 识别招标文件中要求的投标文件组成部分（如投标函、报价表、开标一览表等）
2. 对每个模板部分，提取：
   - 模板名称
   - 表格结构（列名、行数）
   - 需要填写的字段说明
   - 格式要求（如"加盖公章"、"法人签字"）
3. 保持模板顺序与招标文件一致

## 输出 JSON 格式
{
  "title": "投标文件格式",
  "sections": [
    {
      "id": "BF1",
      "title": "投标函",
      "type": "text",
      "content": "致：[采购人名称]\n我方响应贵方...[投标函全文模板]"
    },
    {
      "id": "BF2",
      "title": "开标一览表",
      "type": "standard_table",
      "columns": ["项目名称", "投标报价（万元）", "服务期限", "备注"],
      "rows": [["[待填写]", "[待填写]", "[待填写]", ""]]
    },
    {
      "id": "BF3",
      "title": "法定代表人身份证明书",
      "type": "text",
      "content": "兹证明[姓名]系[公司名称]的法定代表人..."
    }
  ]
}

## 注意事项
- 投标文件格式通常在招标文件最后一章或附件中
- 如果模板包含表格，完整提取列名和示例行
- 保留占位符（如"[公司名称]"、"[日期]"）
```

- [ ] **Step 2: 编写 bid_format 测试**

```python
# tests/test_bid_format.py
import pytest
import os
from src.extractor.bid_format import extract_bid_format
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

@pytest.fixture
def indexed_doc():
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    return build_index(paragraphs)

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_bid_format_json_schema(indexed_doc):
    result = extract_bid_format(indexed_doc["tagged_paragraphs"])
    assert result is not None
    assert "sections" in result
    for section in result["sections"]:
        assert "id" in section
        assert "title" in section
        assert "type" in section

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_bid_format_has_key_templates(indexed_doc):
    """应包含投标函、报价表等关键模板"""
    result = extract_bid_format(indexed_doc["tagged_paragraphs"])
    all_titles = [s["title"] for s in result["sections"]]
    all_text = " ".join(all_titles)
    assert "投标函" in all_text, "应包含投标函模板"
    has_price = "报价" in all_text or "一览表" in all_text or "开标" in all_text
    assert has_price, f"应包含报价相关模板，实际: {all_titles}"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_bid_format_minimum_sections(indexed_doc):
    """至少应提取3个模板部分"""
    result = extract_bid_format(indexed_doc["tagged_paragraphs"])
    assert len(result["sections"]) >= 3, f"应至少有3个模板，实际: {len(result['sections'])}"
```

- [ ] **Step 3: 实现 bid_format 提取逻辑**

核心流程：
1. 从 `tagged_paragraphs` 中筛选标签含"投标文件格式"、"投标函"的段落（通常在文档最后一章）
2. 加载 prompt 模板，调用 `call_qwen()`
3. 解析返回的 JSON

- [ ] **Step 4: 运行测试，Commit**

### Task 5.8: checklist — 资料清单提取

checklist 驱动独立的 .docx 交付物（资料清单），需要按类别提取所需材料。

**Files:**
- Create: `config/prompts/checklist.txt`
- Create: `src/extractor/checklist.py`
- Create: `tests/test_checklist.py`

- [ ] **Step 1: 编写 checklist 的 prompt 模板**

`config/prompts/checklist.txt` 核心要点：

```text
你是招标文件分析专家。请从以下招标文件内容中提取【投标所需资料清单】。

## 提取要求
1. 汇总招标文件中要求投标人提供的全部材料
2. 按类别组织（如：资格证明类、技术方案类、商务报价类、其他类）
3. 每项材料需包含：
   - 资料名称
   - 资料内容/说明（需要提供什么）
   - 特殊要求（原件/复印件、加盖公章、有效期等）
4. 标注来源（哪个章节/条款提到的）

## 输出 JSON 格式
{
  "title": "投标所需资料清单",
  "sections": [
    {
      "id": "CL1",
      "title": "资格证明类材料",
      "type": "standard_table",
      "columns": ["序号", "资料名称", "资料内容", "要求说明"],
      "rows": [
        ["1", "营业执照", "提供有效期内的营业执照副本", "加盖公章的复印件"],
        ["2", "法人身份证", "法定代表人身份证", "正反面复印件加盖公章"],
        ...
      ]
    },
    {
      "id": "CL2",
      "title": "技术方案类材料",
      "type": "standard_table",
      "columns": ["序号", "资料名称", "资料内容", "要求说明"],
      "rows": [...]
    },
    {
      "id": "CL3",
      "title": "商务报价类材料",
      "type": "standard_table",
      "columns": ["序号", "资料名称", "资料内容", "要求说明"],
      "rows": [...]
    },
    {
      "id": "CL4",
      "title": "其他材料",
      "type": "standard_table",
      "columns": ["序号", "资料名称", "资料内容", "要求说明"],
      "rows": [...]
    }
  ]
}

## 注意事项
- 所需材料可能分散在招标文件多个章节中（资格条件、评分标准、投标文件组成等），需全文扫描
- 区分"必须提供"和"可选提供"的材料
- 如果评分标准中有"提供XX得X分"，对应材料也应加入清单
```

- [ ] **Step 2: 编写 checklist 测试**

```python
# tests/test_checklist.py
import pytest
import os
from src.extractor.checklist import extract_checklist
from src.parser.unified import parse_document
from src.indexer.indexer import build_index

@pytest.fixture
def indexed_doc():
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    return build_index(paragraphs)

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_checklist_json_schema(indexed_doc):
    result = extract_checklist(indexed_doc["tagged_paragraphs"])
    assert result is not None
    assert "sections" in result
    for section in result["sections"]:
        assert "id" in section
        assert "type" in section
        assert section["type"] == "standard_table"
        assert "columns" in section
        assert "rows" in section

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_checklist_has_categories(indexed_doc):
    """至少应有4个分类"""
    result = extract_checklist(indexed_doc["tagged_paragraphs"])
    assert len(result["sections"]) >= 4, f"应至少有4个资料类别，实际: {len(result['sections'])}"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_checklist_has_common_materials(indexed_doc):
    """应包含常见的资质材料"""
    result = extract_checklist(indexed_doc["tagged_paragraphs"])
    all_text = str(result)
    assert "营业执照" in all_text, "应包含营业执照"

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_checklist_minimum_items(indexed_doc):
    """总材料项数应 ≥ 10"""
    result = extract_checklist(indexed_doc["tagged_paragraphs"])
    total_rows = sum(len(s.get("rows", [])) for s in result["sections"])
    assert total_rows >= 10, f"资料清单应至少有10项，实际: {total_rows}"
```

- [ ] **Step 3: 实现 checklist 提取逻辑**

核心流程：
1. checklist 需要全文扫描（材料要求散落各处），与 module_e 类似
2. 从 `tagged_paragraphs` 中提取全部段落（或筛选含"提供"、"提交"、"资质"、"证明"、"材料"的段落 + 上下文）
3. 加载 prompt 模板，调用 `call_qwen()`
4. 解析返回的 JSON

- [ ] **Step 4: 运行测试，Commit**

### Task 5.9: LLM 兜底索引

**Files:**
- Create: `src/indexer/llm_splitter.py`
- Create: `tests/test_llm_splitter.py`

- [ ] **Step 1: 编写 LLM 索引测试**

测试当规则切分置信度 < 0.7 时，LLM 兜底能输出合理的章节结构。

- [ ] **Step 2: 实现 LLM 兜底索引**

将文档前 2000 字 + 规则切分结果送给 Qwen，让其输出章节结构 JSON。

- [ ] **Step 3: 集成到 `build_index()` 中**

在 `src/indexer/indexer.py` 的 `build_index()` 中添加：如果 `confidence < 0.7`，调用 `llm_split()`。

- [ ] **Step 4: 运行测试，Commit**

### Task 5.10: 提取层集成

**Files:**
- Create: `src/extractor/extractor.py`（提取层统一入口）
- Create: `tests/test_extractor_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_extractor_integration.py
def test_extract_all_modules(indexed_doc):
    result = extract_all(indexed_doc["tagged_paragraphs"])
    assert "schema_version" in result
    assert "modules" in result
    for key in ["module_a", "module_b", "module_c", "module_d",
                "module_e", "module_f", "module_g", "bid_format", "checklist"]:
        assert key in result["modules"]
```

- [ ] **Step 2: 实现统一提取入口**

`extract_all()` 依次调用 9 个模块，失败的模块标记 `"status": "failed"`。

- [ ] **Step 3: Commit**

### Phase 5 验收测试

**验收标准：**
1. 全部 9 个模块对真实招标文件均返回合法 JSON
2. 每个模块包含预期的关键内容（见上表）
3. 整体 JSON 符合 schema_version 1.0 格式
4. 失败模块被正确标记而非导致整体崩溃

```bash
DASHSCOPE_API_KEY=xxx pytest tests/ -v -k "module_ or extractor"
```

**人工验证：** 打印完整 JSON，对比示例分析报告 PDF，检查提取内容的完整性和准确性。

---

## Phase 6: 人工校对层（Layer 4）

**目标:** 实现 CLI 交互式校对流程。

### Task 6.1: CLI 校对器

**Files:**
- Create: `src/reviewer/cli_reviewer.py`
- Create: `tests/test_cli_reviewer.py`

- [ ] **Step 1: 编写校对器测试**

测试要点：
- 模块展示格式化（rich 表格渲染）
- JSON 保存和加载
- 编辑器调用逻辑（mock `subprocess.call`）
- 校验 JSON 合法性

- [ ] **Step 2: 实现 CLI 校对器**

核心功能：
- `display_module(module_data)` — 用 rich 渲染表格预览
- `review_all(extracted_json)` — 逐模块循环：展示 → 确认/编辑/重跑
- `open_in_editor(json_data)` — 写入临时文件，调用 `$EDITOR` 或 `notepad`，读回并校验
- `save_reviewed(data, output_path)` — 保存校对结果

- [ ] **Step 3: 运行测试，Commit**

### Phase 6 验收测试

**验收标准：**
1. `review_all()` 能正确显示每个模块的表格预览
2. 选择 `[Y]` 直接通过，`[e]` 打开编辑器，`[n]` 标记需重跑
3. 编辑后的 JSON 自动校验格式合法性
4. 最终保存 `_reviewed.json` 文件

**手动测试：** 用 Phase 5 的真实提取结果运行校对流程，确认交互体验。

---

## Phase 7: 文档生成层（Layer 5）

**目标:** 将校对后的 JSON 渲染为三份 .docx 文件。

### Task 7.1: 样式管理器

**Files:**
- Create: `src/generator/style_manager.py`
- Create: `tests/test_style_manager.py`

- [ ] **Step 1: 编写样式测试**

验证能从 config/styles.yaml 加载样式并应用到 python-docx 文档。

- [ ] **Step 2: 实现样式管理器**

- [ ] **Step 3: Commit**

### Task 7.2: 通用表格构建器

**Files:**
- Create: `src/generator/table_builder.py`
- Create: `tests/test_table_builder.py`

- [ ] **Step 1: 编写表格构建测试**

```python
# tests/test_table_builder.py
from docx import Document
from src.generator.table_builder import TableBuilder

def test_build_key_value_table():
    doc = Document()
    builder = TableBuilder()
    section = {
        "type": "key_value_table",
        "columns": ["项目", "内容"],
        "rows": [["项目名称", "测试项目"], ["采购编号", "TEST001"]],
    }
    builder.build(section, doc)
    assert len(doc.tables) == 1
    assert doc.tables[0].rows[0].cells[0].text == "项目"

def test_build_standard_table():
    doc = Document()
    builder = TableBuilder()
    section = {
        "type": "standard_table",
        "columns": ["序号", "要求", "说明"],
        "rows": [["1", "营业执照", "提供复印件"]],
    }
    builder.build(section, doc)
    assert len(doc.tables) == 1
    assert len(doc.tables[0].columns) == 3
```

- [ ] **Step 2: 实现表格构建器**

- [ ] **Step 3: Commit**

### Task 7.3: 分析报告生成器

**Files:**
- Create: `src/generator/report_gen.py`
- Create: `tests/test_report_gen.py`

- [ ] **Step 1: 编写报告生成测试**

使用构造的 JSON 数据测试生成逻辑。验证：
- 输出 .docx 文件可打开
- 包含所有模块的大标题
- 表格数量与 JSON 中的 section 数量一致

```python
# tests/test_report_gen.py
import os
from docx import Document
from src.generator.report_gen import render_report

def test_render_report_basic(tmp_path):
    data = {
        "schema_version": "1.0",
        "modules": {
            "module_a": {
                "title": "A. 项目概况",
                "sections": [
                    {
                        "id": "A1", "title": "基本信息", "type": "key_value_table",
                        "columns": ["项目", "内容"],
                        "rows": [["项目名称", "测试项目"], ["采购编号", "TEST001"]]
                    }
                ]
            }
        }
    }
    out = str(tmp_path / "report.docx")
    render_report(data, out)
    assert os.path.exists(out)
    doc = Document(out)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "A. 项目概况" in full_text
    assert len(doc.tables) >= 1
```

- [ ] **Step 2: 编写失败模块占位测试**

验证当某个模块状态为 `"failed"` 时，报告中渲染红色占位文本而非崩溃。

```python
# tests/test_report_gen.py (追加)
from docx.shared import RGBColor

def test_render_report_failed_module_placeholder(tmp_path):
    """失败模块应渲染红色占位文本，不应导致生成器崩溃"""
    data = {
        "schema_version": "1.0",
        "modules": {
            "module_a": {
                "title": "A. 项目概况",
                "sections": [
                    {
                        "id": "A1", "title": "基本信息", "type": "key_value_table",
                        "columns": ["项目", "内容"],
                        "rows": [["项目名称", "测试项目"]]
                    }
                ]
            },
            "module_c": {
                "status": "failed",
                "error": "LLM 返回非法 JSON"
            }
        }
    }
    out = str(tmp_path / "report_with_failure.docx")
    render_report(data, out)
    assert os.path.exists(out)

    doc = Document(out)
    full_text = "\n".join(p.text for p in doc.paragraphs)
    # 应该包含失败占位文本
    assert "提取失败" in full_text or "failed" in full_text.lower()

    # 验证占位文本为红色
    found_red = False
    for para in doc.paragraphs:
        for run in para.runs:
            if ("提取失败" in run.text or "failed" in run.text.lower()):
                if run.font.color.rgb == RGBColor(0xFF, 0x00, 0x00):
                    found_red = True
    assert found_red, "失败模块的占位文本应为红色"
```

- [ ] **Step 3: 实现动态渲染逻辑**

核心：`render_report(data, output_path)` + 递归 `render_sections(doc, sections, level)`

失败模块处理逻辑：
```python
# src/generator/report_gen.py (关键片段)
from docx.shared import RGBColor

def render_report(data, output_path):
    doc = Document()
    for module_key, module_data in data["modules"].items():
        if module_data.get("status") == "failed":
            # 渲染红色占位段落
            para = doc.add_paragraph()
            run = para.add_run(f"[{module_key} 提取失败: {module_data.get('error', '未知错误')}]")
            run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
            continue
        # 正常渲染模块...
        render_sections(doc, module_data.get("sections", []), level=2)
    doc.save(output_path)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_report_gen.py -v
```

- [ ] **Step 5: Commit**

### Task 7.4: 投标文件格式生成器

**Files:**
- Create: `src/generator/format_gen.py`
- Create: `tests/test_format_gen.py`

- [ ] **Step 1: 编写测试，验证生成的 .docx 包含投标函、报价表等部分**
- [ ] **Step 2: 实现生成器**
- [ ] **Step 3: Commit**

### Task 7.5: 资料清单生成器

**Files:**
- Create: `src/generator/checklist_gen.py`
- Create: `tests/test_checklist_gen.py`

- [ ] **Step 1: 编写测试，验证生成的 .docx 包含分类表格**
- [ ] **Step 2: 实现生成器**
- [ ] **Step 3: Commit**

### Phase 7 验收测试

**验收标准：**
1. 分析报告 .docx 包含 A-G 全部大标题，子标题和表格动态生成
2. 投标文件格式 .docx 包含投标函、报价表等模板结构
3. 资料清单 .docx 包含分类材料表格
4. 所有 .docx 可在 WPS/Word 中正常打开，中文显示正确
5. 表格样式（字体、颜色、边框）符合 styles.yaml 配置

**人工验证：** 打开生成的三份 .docx 文件，与示例文档对比，检查排版和内容完整性。

---

## Phase 8: 端到端集成 + CLI 入口

**目标:** 将五层 Pipeline 串联，实现 `python -m src.main analyze` 一条命令完成全流程。

### Task 8.1: CLI 入口

**Files:**
- Create: `src/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: 编写 CLI 测试**

```python
# tests/test_main.py
import subprocess

def test_cli_help():
    result = subprocess.run(
        ["python", "-m", "src.main", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "analyze" in result.stdout

def test_cli_parse_only():
    result = subprocess.run(
        ["python", "-m", "src.main", "parse", "示例文档/投标文件格式.docx"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
```

- [ ] **Step 2: 实现 CLI 入口**

使用 `argparse` 实现子命令：
- `analyze` — 完整流程
- `parse` — 仅解析 + 索引
- `extract` — 仅 LLM 提取（支持 `--module` 参数）
- `review` — 人工校对
- `generate` — 生成 .docx

- [ ] **Step 3: 运行测试确认通过**

- [ ] **Step 4: Commit**

### Task 8.2: 端到端集成测试

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: 编写端到端测试**

```python
# tests/test_e2e.py
import os
import pytest

@pytest.mark.skipif(not os.environ.get("DASHSCOPE_API_KEY"), reason="需要 API Key")
def test_full_pipeline_docx():
    """测试完整流程：解析 → 索引 → 提取 → 生成（跳过校对）"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index
    from src.extractor.extractor import extract_all
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist

    # Layer 1: 解析
    paragraphs = parse_document("（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc")
    assert len(paragraphs) > 50

    # Layer 2: 索引
    index_result = build_index(paragraphs)
    assert index_result["confidence"] > 0

    # Layer 3: 提取
    extracted = extract_all(index_result["tagged_paragraphs"])
    assert "modules" in extracted
    successful = [k for k, v in extracted["modules"].items()
                  if v.get("status") != "failed"]
    assert len(successful) >= 7  # 至少 7 个模块成功

    # Layer 5: 生成（跳过 Layer 4 校对）
    render_report(extracted, "output/test_分析报告.docx")
    render_format(extracted, "output/test_投标文件格式.docx")
    render_checklist(extracted, "output/test_资料清单.docx")

    assert os.path.exists("output/test_分析报告.docx")
    assert os.path.exists("output/test_投标文件格式.docx")
    assert os.path.exists("output/test_资料清单.docx")
```

- [ ] **Step 2: 运行端到端测试**

```bash
DASHSCOPE_API_KEY=xxx pytest tests/test_e2e.py -v -s
```

- [ ] **Step 3: Commit**

### Phase 8 验收测试

**最终验收标准：**

1. **功能完整性**
   - `python -m src.main analyze xxx.doc` 一条命令完成全流程
   - 分步命令（parse/extract/review/generate）均可独立运行
   - `--module` 参数支持单模块重跑

2. **输出质量**（人工验证）
   - 分析报告：对比示例 PDF，模块 A-G 内容完整，表格结构合理
   - 投标文件格式：对比示例 .docx，包含所有模板部分
   - 资料清单：对比示例 .docx，材料分类完整

3. **鲁棒性**
   - .doc / .docx / .pdf 三种格式均能处理
   - 单模块失败不影响其他模块
   - 非法 JSON 能自动修复或重试

4. **可维护性**
   - 全部测试通过：`pytest tests/ -v`
   - 中间 JSON 可查看和手动编辑
   - Prompt 模板外置，可独立调优

---

## 日志与调试

整个开发过程中，每个阶段完成后应执行：

```bash
# 运行该阶段所有测试
pytest tests/ -v -k "<phase_keyword>"

# 运行全部测试确保无回归
pytest tests/ -v
```

对于需要 API Key 的测试（P4/P5/P8），使用 `@pytest.mark.skipif` 标记，确保无 Key 时其他测试仍可运行。
