# 智能审核模式 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增智能审核模式，通过 haha-code 智能体自主导航投标文件文件夹结构进行条款审查，与现有固定审核并行共存。

**Architecture:** Server 端将投标文件按章节树生成文件夹（叶子节点为带段落索引的 MD 文件 + 图片），haha-code 作为独立 Docker 服务暴露 HTTP `/review` 端点，Celery worker 逐条款并发调用。两种审核模式输出格式一致，下游批注和展示无需修改。

**Tech Stack:** Python (FastAPI/Celery), Bun (haha-code HTTP 服务), Docker, Vue 3

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/reviewer/folder_builder.py` | 新建 | 将章节树 + 段落转为磁盘文件夹结构 |
| `src/reviewer/tests/test_folder_builder.py` | 新建 | folder_builder 单元测试 |
| `src/reviewer/smart_reviewer.py` | 新建 | 调用 haha-code HTTP 服务的客户端 |
| `src/reviewer/tests/test_smart_reviewer.py` | 新建 | smart_reviewer 单元测试 |
| `haha-code/server.ts` | 新建 | Bun HTTP 服务封装 |
| `haha-code/skills/bid-review.md` | 新建 | 审查 skill 文件 |
| `haha-code/Dockerfile` | 新建 | Docker 构建文件 |
| `server/app/models/review_task.py` | 修改 | 新增 review_mode 字段 |
| `server/app/services/review_service.py` | 修改 | 接收 review_mode 参数 |
| `server/app/routers/reviews.py` | 修改 | 传递 review_mode |
| `server/app/tasks/review_task.py` | 修改 | 新增 smart 审核分支 |
| `server/app/config.py` | 修改 | 新增 HAHA_CODE_URL 配置 |
| `docker-compose.yml` | 修改 | 新增 haha-code 服务 |
| `web/src/api/reviews.ts` | 修改 | 传递 review_mode |
| `web/src/stores/reviewStore.ts` | 修改 | 存储 review_mode |
| `web/src/components/ReviewUploadStage.vue` | 修改 | 新增模式选择 UI |

---

## Chunk 1: 文件夹生成器

### Task 1: folder_builder — 核心文件夹生成

**Files:**
- Create: `src/reviewer/folder_builder.py`
- Create: `src/reviewer/tests/test_folder_builder.py`

- [ ] **Step 1: 写 test_sanitize_filename 测试**

```python
# src/reviewer/tests/test_folder_builder.py
import pytest
from src.reviewer.folder_builder import _sanitize_filename


class TestSanitizeFilename:
    def test_normal_title(self):
        assert _sanitize_filename("投标函") == "投标函"

    def test_special_chars(self):
        assert _sanitize_filename("第一章/招标: 公告") == "第一章_招标_ 公告"

    def test_dots_preserved_in_numbers(self):
        assert _sanitize_filename("1.1 资格要求") == "1.1 资格要求"

    def test_empty_string(self):
        assert _sanitize_filename("") == "_"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_folder_builder.py::TestSanitizeFilename -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 实现 _sanitize_filename**

```python
# src/reviewer/folder_builder.py
"""将投标文件章节树 + 段落生成为磁盘文件夹结构，供 haha-code 智能体读取。"""
import os
import re
import shutil
import logging

from src.models import Paragraph

logger = logging.getLogger(__name__)

_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name: str) -> str:
    """清理文件/文件夹名称中的不安全字符。"""
    if not name:
        return "_"
    return _UNSAFE_RE.sub("_", name)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_folder_builder.py::TestSanitizeFilename -v`
Expected: PASS

- [ ] **Step 5: 写 test_build_leaf_md 测试**

```python
# src/reviewer/tests/test_folder_builder.py（追加）
from src.reviewer.folder_builder import _build_leaf_md
from src.models import Paragraph


class TestBuildLeafMd:
    def test_basic_paragraphs(self):
        paragraphs = [
            Paragraph(index=10, text="投标人应当具有独立法人资格"),
            Paragraph(index=11, text="投标人须提供营业执照"),
        ]
        md = _build_leaf_md("1.1 资格要求", paragraphs, [])
        assert "# 1.1 资格要求" in md
        assert "[P10]" in md
        assert "[P11]" in md
        assert "投标人应当具有独立法人资格" in md

    def test_with_images(self):
        paragraphs = [
            Paragraph(index=20, text="企业资质证明"),
        ]
        images = [{"filename": "img001.png", "near_para_index": 20, "path": "/tmp/img001.png"}]
        md = _build_leaf_md("资质", paragraphs, images, images_rel_prefix="../../images")
        assert "![图片](../../images/img001.png)" in md
        assert "[P20]" in md

    def test_empty_paragraphs(self):
        md = _build_leaf_md("空章节", [], [])
        assert "# 空章节" in md
```

- [ ] **Step 6: 实现 _build_leaf_md**

```python
# src/reviewer/folder_builder.py（追加）

def _build_leaf_md(
    title: str,
    paragraphs: list[Paragraph],
    images: list[dict],
    images_rel_prefix: str = "images",
) -> str:
    """为叶子节点生成 Markdown 内容。

    每个段落以 [Pxxx] 标记，图片以 ![图片](<prefix>/xxx.png) 引用。
    images_rel_prefix 是从当前 MD 文件到根目录 images/ 的相对路径。
    """
    lines = [f"# {title}", ""]

    # 图片按 near_para_index 分组
    image_by_para: dict[int, list[str]] = {}
    for img in images:
        pi = img.get("near_para_index")
        if pi is not None:
            image_by_para.setdefault(pi, []).append(img["filename"])

    for p in paragraphs:
        lines.append(f"[P{p.index}] {p.text}")
        # 在段落后插入该段落关联的图片
        for fn in image_by_para.get(p.index, []):
            lines.append(f"![图片]({images_rel_prefix}/{fn})")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_folder_builder.py::TestBuildLeafMd -v`
Expected: PASS

- [ ] **Step 8: 写 test_build_toc_md 测试**

```python
# src/reviewer/tests/test_folder_builder.py（追加）
from src.reviewer.folder_builder import _build_toc_md


class TestBuildTocMd:
    def test_basic_toc(self):
        chapters = [
            {
                "title": "第一章 投标函", "start_para": 0, "end_para": 14,
                "children": [], "level": 1,
            },
            {
                "title": "第二章 商务部分", "start_para": 15, "end_para": 50,
                "level": 1,
                "children": [
                    {"title": "2.1 企业资质", "start_para": 15, "end_para": 30,
                     "children": [], "level": 2},
                    {"title": "2.2 业绩证明", "start_para": 31, "end_para": 50,
                     "children": [], "level": 2},
                ],
            },
        ]
        md = _build_toc_md(chapters)
        assert "# 投标文件目录" in md
        assert "第一章 投标函" in md
        assert "2.1 企业资质" in md
        assert "P15-P30" in md
```

- [ ] **Step 9: 实现 _build_toc_md**

```python
# src/reviewer/folder_builder.py（追加）

def _build_toc_md(chapters: list[dict]) -> str:
    """生成目录文件内容。"""
    lines = ["# 投标文件目录", ""]

    def _walk(nodes: list[dict], depth: int = 0):
        indent = "  " * depth
        for node in nodes:
            title = node["title"]
            children = node.get("children", [])
            start = node.get("start_para", 0)
            end = node.get("end_para", 0)
            if children:
                lines.append(f"{indent}- {_sanitize_filename(title)}/")
                _walk(children, depth + 1)
            else:
                lines.append(f"{indent}- {_sanitize_filename(title)}.md (P{start}-P{end})")

    _walk(chapters)
    return "\n".join(lines)
```

- [ ] **Step 10: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_folder_builder.py::TestBuildTocMd -v`
Expected: PASS

- [ ] **Step 11: 写 test_build_tender_folder 集成测试**

```python
# src/reviewer/tests/test_folder_builder.py（追加）
import tempfile
from src.reviewer.folder_builder import build_tender_folder


class TestBuildTenderFolder:
    def test_creates_folder_structure(self, tmp_path):
        paragraphs = [Paragraph(index=i, text=f"段落内容{i}") for i in range(20)]
        tender_index = {
            "chapters": [
                {
                    "title": "第一章 投标函", "level": 1,
                    "start_para": 0, "end_para": 9,
                    "children": [],
                },
                {
                    "title": "第二章 商务部分", "level": 1,
                    "start_para": 10, "end_para": 19,
                    "children": [
                        {"title": "2.1 企业资质", "level": 2,
                         "start_para": 10, "end_para": 14, "children": []},
                        {"title": "2.2 业绩证明", "level": 2,
                         "start_para": 15, "end_para": 19, "children": []},
                    ],
                },
            ],
        }
        output_dir = str(tmp_path / "tender_folder")

        build_tender_folder(paragraphs, tender_index, [], output_dir)

        # 验证目录结构
        assert os.path.isfile(os.path.join(output_dir, "_目录.md"))
        assert os.path.isfile(os.path.join(output_dir, "第一章 投标函.md"))
        assert os.path.isdir(os.path.join(output_dir, "第二章 商务部分"))
        assert os.path.isfile(os.path.join(output_dir, "第二章 商务部分", "2.1 企业资质.md"))
        assert os.path.isfile(os.path.join(output_dir, "第二章 商务部分", "2.2 业绩证明.md"))

        # 验证 MD 内容
        with open(os.path.join(output_dir, "第一章 投标函.md"), encoding="utf-8") as f:
            content = f.read()
        assert "[P0]" in content
        assert "[P9]" in content
        assert "段落内容0" in content

    def test_with_images(self, tmp_path):
        paragraphs = [Paragraph(index=0, text="资质证明")]
        tender_index = {
            "chapters": [
                {"title": "资质", "level": 1, "start_para": 0, "end_para": 0, "children": []},
            ],
        }
        # 创建假图片
        src_img_dir = tmp_path / "src_images"
        src_img_dir.mkdir()
        (src_img_dir / "cert.png").write_bytes(b"fake png")

        images = [{"filename": "cert.png", "near_para_index": 0, "path": str(src_img_dir / "cert.png")}]
        output_dir = str(tmp_path / "tender_folder")

        build_tender_folder(paragraphs, tender_index, images, output_dir)

        # 图片统一复制到根目录 images/
        assert os.path.isfile(os.path.join(output_dir, "images", "cert.png"))
        with open(os.path.join(output_dir, "资质.md"), encoding="utf-8") as f:
            content = f.read()
        assert "![图片](images/cert.png)" in content

    def test_parent_intro_paragraphs(self, tmp_path):
        """父节点有直属段落（不被子节点覆盖）时，应生成 _概述.md"""
        paragraphs = [Paragraph(index=i, text=f"段落{i}") for i in range(20)]
        tender_index = {
            "chapters": [
                {
                    "title": "第二章", "level": 1,
                    "start_para": 0, "end_para": 19,
                    "children": [
                        {"title": "2.1 子节点", "level": 2,
                         "start_para": 5, "end_para": 19, "children": []},
                    ],
                },
            ],
        }
        output_dir = str(tmp_path / "tender_folder")
        build_tender_folder(paragraphs, tender_index, [], output_dir)

        # P0-P4 不属于任何子节点，应写入 _概述.md
        intro_path = os.path.join(output_dir, "第二章", "_概述.md")
        assert os.path.isfile(intro_path)
        with open(intro_path, encoding="utf-8") as f:
            content = f.read()
        assert "[P0]" in content
        assert "[P4]" in content
```

- [ ] **Step 12: 实现 build_tender_folder**

```python
# src/reviewer/folder_builder.py（追加）

def build_tender_folder(
    paragraphs: list[Paragraph],
    tender_index: dict,
    extracted_images: list[dict],
    output_dir: str,
) -> str:
    """将投标文件按章节树生成文件夹结构。

    图片统一存放在 output_dir/images/，MD 中用相对路径引用。
    父节点如果有子节点未覆盖的段落，生成 _概述.md。

    Args:
        paragraphs: 投标文件段落列表
        tender_index: 章节树（含 chapters）
        extracted_images: 已提取的图片信息 [{filename, path, near_para_index}]
        output_dir: 输出根目录

    Returns:
        输出目录路径
    """
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    chapters = tender_index.get("chapters", [])

    # 图片按 near_para_index 分组
    image_by_para: dict[int, list[dict]] = {}
    for img in extracted_images:
        pi = img.get("near_para_index")
        if pi is not None:
            image_by_para.setdefault(pi, []).append(img)

    # 统一复制所有图片到 output_dir/images/
    if extracted_images:
        img_root = os.path.join(output_dir, "images")
        os.makedirs(img_root, exist_ok=True)
        for img in extracted_images:
            src = img.get("path", "")
            if src and os.path.isfile(src):
                dst = os.path.join(img_root, img["filename"])
                shutil.copy2(src, dst)

    def _images_rel_prefix(depth: int) -> str:
        """根据 MD 文件所在深度计算到根 images/ 的相对路径。"""
        if depth == 0:
            return "images"
        return "/".join([".."] * depth) + "/images"

    # 递归生成文件夹
    def _write_node(node: dict, parent_dir: str, depth: int = 0):
        title = node["title"]
        safe_title = _sanitize_filename(title)
        children = node.get("children", [])
        start = node.get("start_para", 0)
        end = node.get("end_para", 0)

        if children:
            # 非叶子：创建子目录
            node_dir = os.path.join(parent_dir, safe_title)
            os.makedirs(node_dir, exist_ok=True)

            # 检查父节点是否有子节点未覆盖的段落
            children_start = min(c.get("start_para", 0) for c in children)
            if start < children_start:
                intro_paras = [p for p in paragraphs if start <= p.index < children_start]
                if intro_paras:
                    intro_images = []
                    for p in intro_paras:
                        intro_images.extend(image_by_para.get(p.index, []))
                    prefix = _images_rel_prefix(depth + 1)
                    md = _build_leaf_md(f"{title} 概述", intro_paras, intro_images, prefix)
                    with open(os.path.join(node_dir, "_概述.md"), "w", encoding="utf-8") as f:
                        f.write(md)

            for child in children:
                _write_node(child, node_dir, depth + 1)
        else:
            # 叶子：生成 MD 文件
            node_paras = [p for p in paragraphs if start <= p.index <= end]
            node_images = []
            for p in node_paras:
                node_images.extend(image_by_para.get(p.index, []))

            prefix = _images_rel_prefix(depth)
            md_content = _build_leaf_md(title, node_paras, node_images, prefix)
            md_path = os.path.join(parent_dir, f"{safe_title}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

    for chapter in chapters:
        _write_node(chapter, output_dir, depth=0)

    # 生成目录文件
    toc_content = _build_toc_md(chapters)
    with open(os.path.join(output_dir, "_目录.md"), "w", encoding="utf-8") as f:
        f.write(toc_content)

    logger.info("Tender folder built at %s with %d chapters", output_dir, len(chapters))
    return output_dir
```

- [ ] **Step 13: 运行全部 folder_builder 测试**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_folder_builder.py -v`
Expected: ALL PASS

- [ ] **Step 14: Commit**

```bash
git add src/reviewer/folder_builder.py src/reviewer/tests/test_folder_builder.py
git commit -m "feat(smart-review): add folder_builder to generate tender file folder structure"
```

---

## Chunk 2: haha-code 审核 Skill + HTTP 服务

### Task 2: 创建审核 Skill

**Files:**
- Create: `haha-code/skills/bid-review.md`

- [ ] **Step 1: 创建 bid-review.md skill 文件**

```markdown
---
name: bid-review
description: 审查投标文件条款合规性。根据给定条款，自主浏览投标文件文件夹，阅读相关章节和图片，判定是否满足要求。
---

# 投标文件条款审查

## 你的角色
你是资深招标审查专家。你需要审查一份投标文件是否满足某个招标条款的要求。

## 输入
你会收到：
1. **条款信息**：clause_text（条款内容）、basis_text（条款依据）、severity（严重等级：critical/major/minor）
2. **项目背景**：project_context
3. **文件夹路径**：投标文件已按章节结构组织为文件夹

## 审查流程

### 第一步：浏览目录结构
使用 Read 工具阅读文件夹根目录的 `_目录.md`，了解投标文件的整体结构和各章节的段落范围。
文件夹根目录下有一个 `images/` 子目录，包含所有从投标文件中提取的图片。

### 第二步：定位相关章节
根据条款内容，判断哪些章节可能包含相关内容。

**注意**：
- 不要仅凭文件名猜测，要实际打开文件阅读
- 一个条款可能涉及多个章节，要全面搜索
- 如果第一个查看的章节没有相关内容，继续查看其他章节

### 第三步：深入阅读
逐一阅读相关章节的 MD 文件，重点关注：

1. **段落标记**：记住每个段落的 `[Pxxx]` 标记，这是你定位问题的唯一依据
2. **图片审查（最高优先级）**：
   - 遇到 `![图片](images/xxx.png)` 或 `![图片](../images/xxx.png)` 时，**必须**使用 Read 工具读取该图片文件（图片统一位于文件夹根目录的 `images/` 下）
   - 图片中经常包含：营业执照、资质证书、业绩合同、授权书、盖章承诺函、报价表、技术参数表等关键审查内容
   - **绝对不能跳过任何图片** — 跳过图片会导致严重的审查遗漏
   - 审查图片时注意：证书是否在有效期内、盖章是否齐全、内容是否与条款要求一致
3. **表格内容**：仔细核对表格中的数据是否满足条款的量化要求

### 第四步：综合判定
基于所有阅读的文本和图片内容，对条款做出判定。

## 输出格式

**严格只返回以下 JSON，前后不要添加任何其他文字、解释或思考过程：**

```json
{
  "result": "pass 或 fail 或 warning",
  "confidence": 85,
  "reason": "判定理由，简明扼要说明依据",
  "locations": [
    {
      "para_index": 123,
      "text_snippet": "该段落中的关键文本片段（20字以内）",
      "reason": "该段落存在问题的具体原因"
    }
  ]
}
```

## 判定标准

| 判定 | 条件 | confidence |
|------|------|------------|
| **pass** | 投标文件完全满足该条款要求，有明确依据 | >= 80 |
| **fail** | 投标文件明确不满足该条款要求，有具体的缺失或违规 | >= 60 |
| **warning** | 无法确定是否满足：信息模糊、部分满足、需人工确认 | 任意 |

## 重要规则

1. **图片是审查的最重要依据之一**，必须逐一查看，绝不可跳过
2. `locations` 中的 `para_index` 必须是你实际阅读到的 `[Pxxx]` 中的数字
3. 如果整个文件夹中找不到与条款相关的内容，result 为 `"warning"`，reason 说明未找到相关内容
4. 不要凭推测判定 `"pass"`，必须找到实际文本或图片依据
5. 只输出 JSON，不要输出任何思考过程、解释或多余文字
6. `locations` 数组可以为空（当 result 为 pass 且没有需要标注的段落时）
7. 当 result 为 fail 时，`locations` 必须至少包含一个条目，指出问题所在
```

- [ ] **Step 2: Commit**

```bash
git add haha-code/skills/bid-review.md
git commit -m "feat(smart-review): add bid-review skill for haha-code agent"
```

### Task 3: haha-code HTTP 服务

**Files:**
- Create: `haha-code/server.ts`

- [ ] **Step 1: 创建 server.ts**

```typescript
// haha-code/server.ts
import { $ } from "bun";
import { join } from "path";

const PORT = parseInt(process.env.HAHA_CODE_PORT || "3000", 10);
const ROOT_DIR = import.meta.dir;
const CLI_PATH = join(ROOT_DIR, "src", "entrypoints", "cli.tsx");
const SKILL_PATH = join(ROOT_DIR, "skills", "bid-review.md");
const REVIEW_TIMEOUT = parseInt(process.env.REVIEW_TIMEOUT_MS || "300000", 10); // 5 min

interface ReviewRequest {
  clause: {
    clause_index: number;
    clause_text: string;
    basis_text: string;
    severity: string;
    source_module: string;
  };
  folder_path: string;
  project_context: string;
}

interface ReviewResult {
  result: "pass" | "fail" | "warning" | "error";
  confidence: number;
  reason: string;
  locations: Array<{
    para_index: number;
    text_snippet: string;
    reason: string;
  }>;
}

function buildPrompt(req: ReviewRequest): string {
  return `请按照 bid-review skill 的流程审查以下条款。

## 条款信息
- 条款内容：${req.clause.clause_text}
- 条款依据：${req.clause.basis_text}
- 严重等级：${req.clause.severity}

## 项目背景
${req.project_context}

## 投标文件位置
文件夹路径：${req.folder_path}
请先阅读 ${req.folder_path}/_目录.md 了解文件结构，然后自主浏览相关章节进行审查。

重要提醒：遇到图片必须使用 Read 工具查看图片内容，图片中包含关键审查信息。

请严格按照 skill 中定义的 JSON 格式输出结果，不要输出任何其他文字。`;
}

function parseResult(stdout: string): ReviewResult {
  // 尝试从输出中提取 JSON
  const jsonMatch = stdout.match(/\{[\s\S]*"result"[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      return {
        result: parsed.result || "error",
        confidence: parseInt(parsed.confidence) || 0,
        reason: parsed.reason || "",
        locations: Array.isArray(parsed.locations) ? parsed.locations : [],
      };
    } catch {}
  }
  return {
    result: "error",
    confidence: 0,
    reason: `智能体输出解析失败: ${stdout.slice(0, 200)}`,
    locations: [],
  };
}

const server = Bun.serve({
  port: PORT,
  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);

    // Health check
    if (url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }

    // Review endpoint
    if (url.pathname === "/review" && req.method === "POST") {
      try {
        const body: ReviewRequest = await req.json();

        if (!body.clause || !body.folder_path) {
          return Response.json({ error: "Missing clause or folder_path" }, { status: 400 });
        }

        const prompt = buildPrompt(body);

        // 调用 haha-code CLI
        const proc = Bun.spawn(
          [
            "bun", "--env-file=.env", CLI_PATH,
            "-p", prompt,
            "--add-dir", body.folder_path,
            "--allowedTools", "Read Glob Grep",
            "--system-prompt", `你是资深招标审查专家。请使用工具阅读投标文件文件夹中的内容进行审查。遇到图片（.png/.jpg等）必须使用 Read 工具查看。`,
          ],
          {
            cwd: ROOT_DIR,
            stdout: "pipe",
            stderr: "pipe",
            env: { ...process.env },
          }
        );

        // 超时控制
        const timeout = setTimeout(() => {
          proc.kill();
        }, REVIEW_TIMEOUT);

        const stdout = await new Response(proc.stdout).text();
        const stderr = await new Response(proc.stderr).text();
        clearTimeout(timeout);

        const exitCode = await proc.exited;

        if (exitCode !== 0) {
          console.error(`CLI exited with code ${exitCode}: ${stderr.slice(0, 500)}`);
          return Response.json({
            result: "error",
            confidence: 0,
            reason: `智能体执行失败 (exit ${exitCode})`,
            locations: [],
          });
        }

        const result = parseResult(stdout);
        return Response.json(result);
      } catch (e: any) {
        console.error("Review error:", e);
        return Response.json({
          result: "error",
          confidence: 0,
          reason: `服务内部错误: ${e.message}`,
          locations: [],
        }, { status: 500 });
      }
    }

    return Response.json({ error: "Not found" }, { status: 404 });
  },
});

console.log(`haha-code review server listening on port ${PORT}`);
```

- [ ] **Step 2: 本地测试 HTTP 服务启动**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读/haha-code && export PATH="$HOME/.bun/bin:$PATH" && bun --env-file=.env server.ts &`
Wait 3 seconds, then:
Run: `curl http://localhost:3000/health`
Expected: `{"status":"ok"}`

Kill the background process after testing.

- [ ] **Step 3: Commit**

```bash
git add haha-code/server.ts
git commit -m "feat(smart-review): add haha-code HTTP review server"
```

### Task 4: haha-code Dockerfile

**Files:**
- Create: `haha-code/Dockerfile`

- [ ] **Step 1: 创建 Dockerfile**

```dockerfile
FROM oven/bun:1 AS base

# Install curl for healthcheck and git (required by haha-code)
RUN apt-get update && apt-get install -y --no-install-recommends curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY haha-code/package.json haha-code/bunfig.toml ./
RUN bun install

# Copy source
COPY haha-code/ ./

# Copy .env from example
RUN cp .env.example .env

EXPOSE 3000

CMD ["bun", "run", "server.ts"]
```

- [ ] **Step 2: Commit**

```bash
git add haha-code/Dockerfile
git commit -m "feat(smart-review): add haha-code Dockerfile"
```

---

## Chunk 3: smart_reviewer 客户端 + Server 端改动

### Task 5: smart_reviewer HTTP 客户端

**Files:**
- Create: `src/reviewer/smart_reviewer.py`
- Create: `src/reviewer/tests/test_smart_reviewer.py`

- [ ] **Step 1: 写 test_call_smart_review 测试**

```python
# src/reviewer/tests/test_smart_reviewer.py
import json
import pytest
from unittest.mock import patch, MagicMock

from src.reviewer.smart_reviewer import call_smart_review


class TestCallSmartReview:
    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "pass",
            "confidence": 90,
            "reason": "满足要求",
            "locations": [],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        clause = {
            "clause_index": 1,
            "clause_text": "须提供营业执照",
            "basis_text": "资格要求",
            "severity": "critical",
            "source_module": "module_c",
        }
        result = call_smart_review(clause, "/data/tender_folder", "测试项目")

        assert result["result"] == "pass"
        assert result["confidence"] == 90
        assert result["source_module"] == "module_c"
        assert result["clause_index"] == 1

    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_http_error(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        clause = {
            "clause_index": 2,
            "clause_text": "测试条款",
            "basis_text": "",
            "severity": "minor",
            "source_module": "module_a",
        }
        result = call_smart_review(clause, "/data/folder", "项目")

        assert result["result"] == "error"
        assert result["clause_index"] == 2
        assert "Connection refused" in result["reason"]

    @patch("src.reviewer.smart_reviewer.httpx.post")
    def test_timeout(self, mock_post):
        import httpx
        mock_post.side_effect = httpx.TimeoutException("timeout")

        clause = {
            "clause_index": 3,
            "clause_text": "超时条款",
            "basis_text": "",
            "severity": "major",
            "source_module": "module_b",
        }
        result = call_smart_review(clause, "/data/folder", "项目")

        assert result["result"] == "error"
        assert "超时" in result["reason"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_smart_reviewer.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 实现 smart_reviewer.py**

```python
# src/reviewer/smart_reviewer.py
"""HTTP 客户端：调用 haha-code 智能审核服务。"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

HAHA_CODE_URL = os.environ.get("HAHA_CODE_URL", "http://haha-code:3000")
REVIEW_TIMEOUT = int(os.environ.get("SMART_REVIEW_TIMEOUT", "360"))  # 6 min


def call_smart_review(
    clause: dict,
    folder_path: str,
    project_context: str,
) -> dict:
    """调用 haha-code 智能审核服务审查单个条款。

    返回格式与 llm_review_clause 一致的 review item dict。
    """
    url = f"{HAHA_CODE_URL}/review"
    payload = {
        "clause": {
            "clause_index": clause["clause_index"],
            "clause_text": clause.get("clause_text", ""),
            "basis_text": clause.get("basis_text", ""),
            "severity": clause.get("severity", "minor"),
            "source_module": clause.get("source_module", ""),
        },
        "folder_path": folder_path,
        "project_context": project_context,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=REVIEW_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        logger.error("Smart review timeout for clause %d", clause["clause_index"])
        return _error_item(clause, "智能审核超时")
    except Exception as e:
        logger.error("Smart review failed for clause %d: %s", clause["clause_index"], e)
        return _error_item(clause, f"智能审核调用失败: {e}")

    # 规范化为统一的 review item 格式
    locations = data.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict) and loc.get("para_index") is not None:
            normalized_locations.append({
                "para_index": loc["para_index"],
                "text_snippet": loc.get("text_snippet", ""),
                "reason": loc.get("reason", ""),
            })

    # 构建 tender_locations（与固定审核格式一致）
    tender_locations = []
    if normalized_locations:
        per_para_reasons = {loc["para_index"]: loc.get("reason", "") for loc in normalized_locations}
        tender_locations.append({
            "chapter": "",
            "para_indices": [loc["para_index"] for loc in normalized_locations],
            "text_snippet": normalized_locations[0].get("text_snippet", ""),
            "per_para_reasons": per_para_reasons,
        })

    return {
        "source_module": clause.get("source_module", ""),
        "clause_index": clause["clause_index"],
        "clause_text": clause.get("clause_text", ""),
        "result": data.get("result", "error"),
        "confidence": int(data.get("confidence", 0)),
        "reason": data.get("reason", ""),
        "severity": clause.get("severity", "minor"),
        "tender_locations": tender_locations,
    }


def _error_item(clause: dict, reason: str) -> dict:
    return {
        "source_module": clause.get("source_module", ""),
        "clause_index": clause["clause_index"],
        "clause_text": clause.get("clause_text", ""),
        "result": "error",
        "confidence": 0,
        "reason": reason,
        "severity": clause.get("severity", "minor"),
        "tender_locations": [],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_smart_reviewer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/smart_reviewer.py src/reviewer/tests/test_smart_reviewer.py
git commit -m "feat(smart-review): add smart_reviewer HTTP client"
```

### Task 6: Server 配置 + 模型字段

**Files:**
- Modify: `server/app/config.py`
- Modify: `server/app/models/review_task.py`

- [ ] **Step 1: 在 config.py 添加 HAHA_CODE_URL**

在 `server/app/config.py` 的 `Settings` 类中，在 `ALLOWED_EXTENSIONS` 行之后添加：

```python
    HAHA_CODE_URL: str = "http://haha-code:3000"
```

- [ ] **Step 2: 在 ReviewTask 模型添加 review_mode 字段**

在 `server/app/models/review_task.py` 中，在 `status` 字段之后添加：

```python
    review_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
```

- [ ] **Step 3: Commit**

```bash
git add server/app/config.py server/app/models/review_task.py
git commit -m "feat(smart-review): add HAHA_CODE_URL config and review_mode field"
```

### Task 7: review_service + router 传递 review_mode

**Files:**
- Modify: `server/app/services/review_service.py`
- Modify: `server/app/routers/reviews.py`

- [ ] **Step 1: 修改 create_review 接收 review_mode**

在 `server/app/services/review_service.py` 的 `create_review` 函数签名中添加 `review_mode: str = "fixed"` 参数：

```python
async def create_review(
    db: AsyncSession, tender_file: UploadFile, bid_task_id: str, user_id: int,
    review_mode: str = "fixed",
) -> ReviewTask:
```

在创建 `ReviewTask` 对象处添加 `review_mode=review_mode`：

```python
    review = ReviewTask(
        id=review_id,
        user_id=user_id,
        bid_task_id=task_uuid,
        tender_filename=filename,
        tender_file_path=file_path,
        version=version,
        status="pending",
        progress=0,
        review_mode=review_mode,
    )
```

- [ ] **Step 2: 修改 router 接收并传递 review_mode**

在 `server/app/routers/reviews.py` 的 `create_review_endpoint` 中，添加 `review_mode` 表单字段：

```python
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    tender_file: UploadFile = File(...),
    bid_task_id: str = Form(...),
    review_mode: str = Form("fixed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_review(db, tender_file, bid_task_id, user.id, review_mode=review_mode)
```

在 list_reviews_endpoint 的返回项中添加 `review_mode`：

```python
                "review_mode": r.review_mode,
```

在 get_review_endpoint 的返回中添加 `review_mode`：

```python
        "review_mode": review.review_mode,
```

- [ ] **Step 3: Commit**

```bash
git add server/app/services/review_service.py server/app/routers/reviews.py
git commit -m "feat(smart-review): pass review_mode through service and router"
```

### Task 8: review_task.py 添加 smart 审核分支

**Files:**
- Modify: `server/app/tasks/review_task.py`

- [ ] **Step 1: 在 run_review 中读取 review_mode 并分支**

在 `server/app/tasks/review_task.py` 中，在 `run_review` 函数内：

1. 读取 `review.review_mode`（在获取 review 对象后）
2. Step 4 的条款映射处添加分支判断
3. Step 5 的审查流程添加 smart 分支

在 try 块开头（获取 review 对象后）添加读取：

```python
            review_mode = review.review_mode or "fixed"
```

将 Step 4（章节映射）和 Step 5（审查）用 `if review_mode == "smart":` 分支。在 `from src.reviewer.reviewer import (` 导入块下方添加条件导入：

在 `# Step 3: Extract clauses` 之后、`# Step 4: Chapter mapping` 之前插入 smart 分支：

```python
            if review_mode == "smart":
                # Smart mode: 生成文件夹 + 调用 haha-code
                from src.reviewer.folder_builder import build_tender_folder
                from src.reviewer.smart_reviewer import call_smart_review

                # 生成文件夹
                import os as _os
                tender_folder = _os.path.join(
                    _os.path.dirname(review.tender_file_path), "tender_folder"
                )
                review.progress = 13
                review.current_step = "生成文件夹结构"
                db.commit()
                self.update_state(state="PROGRESS", meta={
                    "step": "extracting", "progress": 13, "detail": "生成文件夹结构",
                })

                build_tender_folder(paragraphs, tender_index, extracted_images, tender_folder)

                # 逐条款并发调用 haha-code
                from concurrent.futures import ThreadPoolExecutor, as_completed

                all_clauses = sorted(
                    clauses,
                    key=lambda c: {"critical": 0, "major": 1, "minor": 2}.get(c["severity"], 9),
                )
                clause_progress_start = 15
                clause_progress_end = 95
                MAX_SMART_WORKERS = 4

                results_by_index: dict[int, dict] = {}
                futures = {}

                with ThreadPoolExecutor(max_workers=MAX_SMART_WORKERS) as executor:
                    for clause in all_clauses:
                        future = executor.submit(
                            call_smart_review, clause, tender_folder, project_context,
                        )
                        futures[future] = clause

                    completed = 0
                    for future in as_completed(futures):
                        clause = futures[future]
                        completed += 1
                        prog = clause_progress_start + int(
                            (clause_progress_end - clause_progress_start) * completed / max(len(all_clauses), 1)
                        )
                        review.progress = prog
                        review.current_step = f"智能审查 [{completed}/{len(all_clauses)}]"
                        db.commit()
                        self.update_state(state="PROGRESS", meta={
                            "step": "reviewing", "progress": prog,
                            "detail": review.current_step,
                        })

                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error("Smart review error for clause %d: %s", clause["clause_index"], e)
                            result = {
                                "source_module": clause["source_module"],
                                "clause_index": clause["clause_index"],
                                "clause_text": clause["clause_text"],
                                "result": "error", "confidence": 0,
                                "reason": f"智能审查异常: {e}",
                                "severity": clause["severity"], "tender_locations": [],
                            }
                        results_by_index[clause["clause_index"]] = result

                # 组装结果
                review_items = []
                for item_id, clause in enumerate(all_clauses):
                    result = results_by_index.get(clause["clause_index"], {
                        "source_module": clause["source_module"],
                        "clause_index": clause["clause_index"],
                        "clause_text": clause["clause_text"],
                        "result": "error", "confidence": 0,
                        "reason": "未获得审查结果",
                        "severity": clause["severity"], "tender_locations": [],
                    })
                    result["id"] = item_id
                    review_items.append(result)

            else:
                # Fixed mode: 原有固定审核流程
```

需要将原有 Step 4-7 的代码放入 `else` 分支中（即原有的 clause_mapping + _review_single_clause 逻辑）。

Step 8（生成 docx）以后的代码保持不变，两种模式共享。

- [ ] **Step 2: 运行服务确认无语法错误**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -c "from server.app.tasks.review_task import run_review; print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: Commit**

```bash
git add server/app/tasks/review_task.py
git commit -m "feat(smart-review): add smart review branch in review_task"
```

---

## Chunk 4: Docker 集成 + 前端改动

### Task 9: docker-compose 集成

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: 在 docker-compose.yml 中添加 haha-code 服务**

在 `nginx` 服务之前添加 `haha-code` 服务：

```yaml
  haha-code:
    build:
      context: .
      dockerfile: haha-code/Dockerfile
    restart: unless-stopped
    environment:
      ANTHROPIC_AUTH_TOKEN: ${DASHSCOPE_API_KEY:-}
      ANTHROPIC_BASE_URL: https://dashscope.aliyuncs.com/apps/anthropic
      ANTHROPIC_DEFAULT_HAIKU_MODEL: qwen3.5-flash
      ANTHROPIC_DEFAULT_OPUS_MODEL: qwen3.6-plus
      ANTHROPIC_DEFAULT_SONNET_MODEL: qwen3.5-plus
      ANTHROPIC_MODEL: qwen3.6-plus
      API_TIMEOUT_MS: "3000000"
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
      DISABLE_TELEMETRY: "1"
    volumes:
      - filedata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 10s
      retries: 5
```

在 `worker` 服务的 `environment` 中添加：

```yaml
      HAHA_CODE_URL: http://haha-code:3000
```

在 `worker` 服务的 `depends_on` 中添加：

```yaml
      haha-code: { condition: service_healthy }
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(smart-review): add haha-code service to docker-compose"
```

### Task 10: 前端 — API 层 + Store

**Files:**
- Modify: `web/src/api/reviews.ts`
- Modify: `web/src/stores/reviewStore.ts`

- [ ] **Step 1: 修改 reviews.ts 传递 review_mode**

在 `web/src/api/reviews.ts` 中修改 `create` 方法：

```typescript
  create(bidTaskId: string, tenderFile: File, reviewMode: string = 'fixed') {
    const form = new FormData()
    form.append('bid_task_id', bidTaskId)
    form.append('tender_file', tenderFile)
    form.append('review_mode', reviewMode)
    return client.post<{ id: string; status: string; version: number }>('/reviews', form)
  },
```

- [ ] **Step 2: 修改 reviewStore.ts 存储 review_mode**

在 `web/src/stores/reviewStore.ts` 中：

在 `error` ref 之后添加：
```typescript
  const reviewMode = ref<string>('fixed')
```

修改 `startReview` 方法签名和调用：
```typescript
  async function startReview(bidTaskId: string, tenderFile: File, mode: string = 'fixed') {
    error.value = null
    try {
      const res = await reviewsApi.create(bidTaskId, tenderFile, mode)
      currentReviewId.value = res.data.id
      localStorage.setItem('current_review_id', res.data.id)
      reviewMode.value = mode
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建审查任务失败'
      throw e
    }
  }
```

在 `resetToUpload` 中添加：
```typescript
    reviewMode.value = 'fixed'
```

在 return 对象中添加 `reviewMode`：
```typescript
  return {
    stage, selectedBidTask, currentReviewId, progress, currentStep, detail,
    reviewSummary, reviewItems, error, reviewMode,
    startReview, handleProgressEvent, loadReviewResult, loadReviewState, resetToUpload,
  }
```

- [ ] **Step 3: Commit**

```bash
git add web/src/api/reviews.ts web/src/stores/reviewStore.ts
git commit -m "feat(smart-review): add review_mode to frontend API and store"
```

### Task 11: 前端 — 上传界面添加模式选择

**Files:**
- Modify: `web/src/components/ReviewUploadStage.vue`

- [ ] **Step 1: 在 ReviewUploadStage.vue 添加模式选择**

在 `<script setup>` 中，在 `submitting` ref 之前添加：

```typescript
// --- Review mode ---
const reviewMode = ref<'fixed' | 'smart'>('fixed')
```

修改 `startReview` 函数调用，传入 reviewMode：

```typescript
async function startReview() {
  if (!reviewStore.selectedBidTask || !tenderFile.value) return
  submitting.value = true
  try {
    await reviewStore.startReview(reviewStore.selectedBidTask.id, tenderFile.value, reviewMode.value)
  } catch { /* error shown via store */ }
  finally { submitting.value = false }
}
```

在 template 中，在 `<!-- Error -->` 之前添加模式选择 UI：

```html
    <!-- Review mode -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">审核模式</label>
      <div class="flex gap-3">
        <label
          class="flex-1 flex items-center gap-3 p-3 border rounded-lg cursor-pointer transition-colors"
          :class="reviewMode === 'fixed' ? 'border-success bg-success/5' : 'border-border'"
        >
          <input v-model="reviewMode" type="radio" value="fixed" class="accent-success" />
          <div>
            <p class="text-sm font-medium text-text-primary">固定审核</p>
            <p class="text-xs text-text-muted">基于条款映射的标准审核流程，速度快</p>
          </div>
        </label>
        <label
          class="flex-1 flex items-center gap-3 p-3 border rounded-lg cursor-pointer transition-colors"
          :class="reviewMode === 'smart' ? 'border-success bg-success/5' : 'border-border'"
        >
          <input v-model="reviewMode" type="radio" value="smart" class="accent-success" />
          <div>
            <p class="text-sm font-medium text-text-primary">智能审核</p>
            <p class="text-xs text-text-muted">AI 智能体自主浏览审查，精度高但耗时较长</p>
          </div>
        </label>
      </div>
    </div>
```

- [ ] **Step 2: 验证前端构建**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读/web && npm run build 2>&1 | tail -5`
Expected: 构建成功，无错误

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ReviewUploadStage.vue
git commit -m "feat(smart-review): add review mode selector in upload UI"
```

### Task 12: 数据库迁移

- [ ] **Step 1: 生成并执行 review_mode 字段迁移**

由于项目使用 `Base.metadata.create_all` 自动建表（无 Alembic versions），需要手动添加列。在 Docker 中执行：

```bash
docker compose exec postgres psql -U biduser -d bid_analyzer -c "
  ALTER TABLE review_tasks ADD COLUMN IF NOT EXISTS review_mode VARCHAR(20) NOT NULL DEFAULT 'fixed';
"
```

- [ ] **Step 2: 验证字段已添加**

```bash
docker compose exec postgres psql -U biduser -d bid_analyzer -c "\d review_tasks" | grep review_mode
```

Expected: 输出包含 `review_mode | character varying(20) | not null | 'fixed'`

---

## Chunk 5: 集成测试 + 部署验证

### Task 13: 构建并启动 haha-code 服务

- [ ] **Step 1: 构建 haha-code 镜像**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && docker compose build haha-code`
Expected: 构建成功

- [ ] **Step 2: 启动全部服务**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && docker compose up -d`
Expected: 所有服务正常启动

- [ ] **Step 3: 验证 haha-code 健康检查**

Run: `docker compose exec worker curl -s http://haha-code:3000/health`
Expected: `{"status":"ok"}`

- [ ] **Step 4: 验证 worker 能访问 haha-code**

Run: `docker compose logs haha-code | tail -5`
Expected: 包含 `listening on port 3000`

### Task 14: 端到端测试

- [ ] **Step 1: 通过 API 创建 smart 审核任务**

使用现有的已完成的招标任务 ID，上传投标文件并选择 smart 模式：

```bash
# 先登录获取 token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 查找已完成的招标任务
curl -s http://localhost:8000/api/tasks?status=completed \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -20
```

- [ ] **Step 2: 观察审核进度**

通过 SSE 或查看 worker 日志观察智能审核进度：

```bash
docker compose logs -f worker 2>&1 | grep -i "smart\|haha\|智能"
```

Expected: 日志显示逐条款调用 haha-code 服务并获得返回结果

- [ ] **Step 3: 验证结果格式一致**

审核完成后检查结果：
```bash
curl -s http://localhost:8000/api/reviews/{review_id} \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

Expected: `review_items` 数组中每个条目包含 `result`, `confidence`, `reason`, `tender_locations` 等标准字段

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "feat(smart-review): complete smart review mode integration"
```
