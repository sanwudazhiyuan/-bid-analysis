# 审查进度条优化 + 投标文件混合索引 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为标书审查功能添加与标书解读一致的进度条 UI，并将投标文件索引从简单 TOC+LLM 替换为 5 层混合策略。

**Architecture:** 前端复用 `useSSE` composable + `ProcessingStage` 组件（参数化），后端对齐 6 步 step key；新建 `tender_rule_splitter.py` 实现 TOC→Style→关键词→编号→LLM 五层索引策略，置信度竞争选优。

**Tech Stack:** Vue 3 + TypeScript, Python 3.11, Celery, difflib, regex

---

## 文件变更清单

### 新建
- `src/reviewer/tender_rule_splitter.py` — 投标文件混合索引器（5 层策略）
- `src/reviewer/tests/test_tender_rule_splitter.py` — 索引器测试

### 修改
- `web/src/composables/useSSE.ts` — 支持自定义 URL 参数
- `web/src/components/ProcessingStage.vue` — 支持自定义步骤列表 prop
- `web/src/views/BidReviewView.vue` — 用 useSSE + ProcessingStage 替换内联 EventSource
- `web/src/stores/reviewStore.ts` — 添加 step 中文显示映射
- `server/app/tasks/review_task.py` — 替换索引逻辑 + 对齐 6 步 step key

---

## Chunk 1: 前端进度 UI 重构

### Task 1: useSSE — 支持自定义 URL

**Files:**
- Modify: `web/src/composables/useSSE.ts`
- Modify: `web/src/views/__tests__/BidAnalysisView.test.ts` (mock 签名兼容)

- [ ] **Step 1: 修改 useSSE 接受可选 URL 参数**

```typescript
// web/src/composables/useSSE.ts
import { ref, onUnmounted } from 'vue'
import type { ProgressEvent } from '../types/task'

export function useSSE(taskId: string, customUrl?: string) {
  const progress = ref<ProgressEvent | null>(null)
  const connected = ref(false)
  const done = ref(false)
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  let abortController: AbortController | null = null

  async function connect() {
    const token = localStorage.getItem('access_token')
    abortController = new AbortController()

    try {
      const url = customUrl || `/api/tasks/${taskId}/progress`
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: abortController.signal,
      })

      if (!response.ok || !response.body) {
        connected.value = false
        return
      }

      connected.value = true
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done: streamDone } = await reader.read()
        if (streamDone) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6)) as ProgressEvent
              progress.value = data
              if (data.step === 'completed' || data.step === 'failed') {
                done.value = true
                disconnect()
                return
              }
            } catch {}
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== 'AbortError') {
        connected.value = false
      }
    }
  }

  function disconnect() {
    abortController?.abort()
    connected.value = false
  }

  onUnmounted(disconnect)

  return { progress, connected, done, connect, disconnect }
}
```

变更点：函数签名新增 `customUrl?: string`，fetch URL 改为 `customUrl || \`/api/tasks/${taskId}/progress\``。

- [ ] **Step 2: 确认 BidAnalysisView 测试 mock 兼容**

现有 mock `useSSE: vi.fn(() => ({...}))` 不需要修改 — 新增参数是可选的，现有调用 `useSSE(taskId)` 不受影响。

Run: `cd web && npx vitest run src/views/__tests__/BidAnalysisView.test.ts --reporter=verbose`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/src/composables/useSSE.ts
git commit -m "refactor(useSSE): accept optional custom URL parameter"
```

---

### Task 2: ProcessingStage — 支持自定义步骤列表

**Files:**
- Modify: `web/src/components/ProcessingStage.vue`

- [ ] **Step 1: 添加可选 steps prop，内部 fallback 到默认列表**

```vue
<script setup lang="ts">
import { FileText } from 'lucide-vue-next'

const defaultSteps = [
  { key: 'parsing', label: '解析' },
  { key: 'indexing', label: '索引' },
  { key: 'extracting', label: '提取' },
  { key: 'generating', label: '生成' },
]

const props = defineProps<{
  filename: string
  progress: number
  step: string
  detail: string
  mode: 'processing' | 'reprocessing' | 'generating'
  error?: string | null
  customSteps?: Array<{ key: string; label: string }>
}>()

const emit = defineEmits<{
  retry: []
}>()

const steps = props.customSteps || defaultSteps

const modeLabels = {
  processing: '解析中',
  reprocessing: '修改中',
  generating: '生成中',
}

function stepStatus(stepKey: string) {
  const order = steps.map(s => s.key)
  const currentIdx = order.indexOf(props.step)
  const stepIdx = order.indexOf(stepKey)
  if (stepIdx < currentIdx) return 'done'
  if (stepIdx === currentIdx) return 'active'
  return 'pending'
}
</script>
```

template 部分不变 — 已使用 `steps` 变量渲染。

变更点：
1. 原 `const steps = [...]` 硬编码列表改名为 `defaultSteps`
2. 新增 prop `customSteps?: Array<{ key: string; label: string }>`
3. `const steps = props.customSteps || defaultSteps`

- [ ] **Step 2: 验证 BidAnalysisView 未受影响**

BidAnalysisView 使用 `<ProcessingStage>` 时不传 `customSteps`，将 fallback 到默认 4 步。

Run: `cd web && npx vitest run src/views/__tests__/BidAnalysisView.test.ts --reporter=verbose`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ProcessingStage.vue
git commit -m "refactor(ProcessingStage): accept optional customSteps prop"
```

---

### Task 3: BidReviewView — 使用 useSSE + ProcessingStage

**Files:**
- Modify: `web/src/views/BidReviewView.vue`
- Modify: `web/src/stores/reviewStore.ts`

- [ ] **Step 1: 在 reviewStore 中添加 step 显示名映射**

在 `web/src/stores/reviewStore.ts` 的 `handleProgressEvent` 上方添加映射：

```typescript
const REVIEW_STEP_LABELS: Record<string, string> = {
  indexing: '索引',
  extracting: '条款提取',
  p0_review: '废标审查',
  p1_review: '资格审查',
  p2_review: '评分审查',
  generating: '生成报告',
}
```

并在 `handleProgressEvent` 中使用：

```typescript
function handleProgressEvent(event: { progress: number; step: string; detail?: string; error?: string }) {
  progress.value = event.progress
  currentStep.value = event.step
  detail.value = event.detail || REVIEW_STEP_LABELS[event.step] || ''
  error.value = event.error || null

  if (event.step === 'completed') {
    stage.value = 'preview'
  } else if (event.step === 'failed') {
    error.value = event.error || '审查失败'
  }
}
```

- [ ] **Step 2: 重写 BidReviewView 使用 useSSE + ProcessingStage**

```vue
<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useReviewStore } from '../stores/reviewStore'
import { useSSE } from '../composables/useSSE'
import ReviewUploadStage from '../components/ReviewUploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const store = useReviewStore()

const reviewSteps = [
  { key: 'indexing', label: '索引' },
  { key: 'extracting', label: '条款提取' },
  { key: 'p0_review', label: '废标审查' },
  { key: 'p1_review', label: '资格审查' },
  { key: 'p2_review', label: '评分审查' },
  { key: 'generating', label: '生成报告' },
]

let sseInstance: ReturnType<typeof useSSE> | null = null

function connectSSE(reviewId: string) {
  if (sseInstance) sseInstance.disconnect()

  sseInstance = useSSE(reviewId, `/api/reviews/${reviewId}/progress`)

  watch(sseInstance.progress, (event) => {
    if (event) {
      store.handleProgressEvent(event)
    }
  })

  sseInstance.connect()
}

function disconnectSSE() {
  if (sseInstance) {
    sseInstance.disconnect()
    sseInstance = null
  }
}

watch(() => store.stage, (stage) => {
  if (stage === 'processing' && store.currentReviewId) {
    connectSSE(store.currentReviewId)
  } else if (stage !== 'processing') {
    disconnectSSE()
  }
}, { immediate: true })

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <!-- Upload stage -->
    <ReviewUploadStage v-if="store.stage === 'upload'" />

    <!-- Processing stage -->
    <ProcessingStage
      v-else-if="store.stage === 'processing'"
      :filename="'投标文件审查'"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.detail"
      mode="processing"
      :custom-steps="reviewSteps"
      :error="store.error"
      @retry="store.currentReviewId && connectSSE(store.currentReviewId)"
    />

    <!-- Preview stage -->
    <ReviewPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>
```

变更点：
1. 移除 `EventSource` 逻辑，改用 `useSSE` composable（fetch + Bearer header）
2. processing 阶段使用 `ProcessingStage` 组件，传入 `reviewSteps` 6 步
3. SSE URL 使用 `/api/reviews/${reviewId}/progress`（Bearer token 由 useSSE 自动添加）

- [ ] **Step 3: 验证构建通过**

Run: `cd web && npx vue-tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 4: Commit**

```bash
git add web/src/views/BidReviewView.vue web/src/stores/reviewStore.ts
git commit -m "feat(review): use ProcessingStage + useSSE for review progress UI"
```

---

## Chunk 2: 后端 step key 对齐

### Task 4: review_task.py — 对齐 6 步 step key

**Files:**
- Modify: `server/app/tasks/review_task.py`

- [ ] **Step 1: 修改 step key 以匹配 6 步进度**

将 `review_task.py` 中所有 `self.update_state()` 的 `step` 字段对齐到新 key：

| 代码位置 | 原 step | 新 step | 进度范围 |
|---------|---------|---------|---------|
| Step 1-2（解析/脱敏/提取图片/构建索引）| `indexing` | `indexing` | 0-10% |
| Step 3（提取条款 + 条款映射）| `reviewing` | `extracting` | 10-15% |
| Step 5（P0 逐条审查）| `reviewing` | `p0_review` | 15-60% |
| Step 6（P1 批量审查）| `reviewing` | `p1_review` | 60-85% |
| Step 7（P2 批量审查）| `reviewing` | `p2_review` | 85-95% |
| Step 8（生成报告）| `generating` | `generating` | 95-100% |

具体修改：

**Step 3（条款提取 + 映射）— 行 120-140：**

```python
            # Step 3: Extract clauses (10-15%)
            review.status = "reviewing"
            review.progress = 10
            review.current_step = "提取审查条款"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 10, "detail": "提取条款"})

            clauses = extract_review_clauses(extracted_data)
            project_context = extract_project_context(extracted_data)

            if not clauses:
                review.status = "completed"
                review.progress = 100
                review.review_summary = {"total": 0, "pass": 0, "fail": 0, "warning": 0, "critical_fails": 0}
                review.review_items = []
                db.commit()
                return {"status": "completed", "review_id": review_id, "clauses": 0}

            # Step 4: Chapter mapping (12-15%)
            self.update_state(state="PROGRESS", meta={"step": "extracting", "progress": 12, "detail": "条款映射"})
```

**Step 5（P0）— 行 143-154：**

```python
            # Step 5: P0 review (15-60%)
            review_items = []
            item_id = 0
            p0 = [c for c in clauses if c["severity"] == "critical"]
            for i, clause in enumerate(p0):
                progress = 15 + int(45 * i / max(len(p0), 1))
                review.progress = progress
                review.current_step = f"废标审查 [{i+1}/{len(p0)}]"
                db.commit()
                self.update_state(state="PROGRESS", meta={
                    "step": "p0_review", "progress": progress,
                    "detail": f"废标审查 [{i+1}/{len(p0)}]",
                })
```

**Step 6（P1）— 行 175-188：**

```python
            # Step 6: P1 batch review (60-85%)
            p1 = [c for c in clauses if c["severity"] == "major"]
            if p1:
                batch_size = 8
                for bi in range(0, len(p1), batch_size):
                    batch = p1[bi:bi + batch_size]
                    batch_progress = 60 + int(25 * bi / max(len(p1), 1))
                    review.progress = batch_progress
                    review.current_step = f"资格审查 [{bi+1}-{min(bi+batch_size, len(p1))}/{len(p1)}]"
                    db.commit()
                    self.update_state(state="PROGRESS", meta={
                        "step": "p1_review", "progress": batch_progress,
                        "detail": review.current_step,
                    })
```

**Step 7（P2）— 行 214-227：**

```python
            # Step 7: P2 batch review (85-95%)
            p2 = [c for c in clauses if c["severity"] == "minor"]
            if p2:
                batch_size = 8
                for bi in range(0, len(p2), batch_size):
                    batch = p2[bi:bi + batch_size]
                    batch_progress = 85 + int(10 * bi / max(len(p2), 1))
                    review.progress = batch_progress
                    review.current_step = f"评分审查 [{bi+1}-{min(bi+batch_size, len(p2))}/{len(p2)}]"
                    db.commit()
                    self.update_state(state="PROGRESS", meta={
                        "step": "p2_review", "progress": batch_progress,
                        "detail": review.current_step,
                    })
```

- [ ] **Step 2: Commit**

```bash
git add server/app/tasks/review_task.py
git commit -m "refactor(review-task): align step keys to 6-step progress scheme"
```

---

## Chunk 3: 投标文件混合索引器

### Task 5: 创建 tender_rule_splitter.py — 5 层策略

**Files:**
- Create: `src/reviewer/tender_rule_splitter.py`

- [ ] **Step 1: 创建 tender_rule_splitter.py**

```python
"""投标文件混合索引器：5 层策略识别章节结构

策略优先级（由高到低）：
1. 目录识别匹配（TOC detection）— 单独赛道，匹配成功直接采用
2. Style ID 层级分析 — 竞争赛道
3. 投标文件关键词匹配 — 竞争赛道
4. 编号正则 — 竞争赛道
5. LLM 兜底（当最高置信度 < 0.7 时启用）
"""

import re
import difflib
import logging
from collections import Counter

from src.models import Paragraph

logger = logging.getLogger(__name__)

# ========== TOC 正则 ==========
_TOC_LINE_RE = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节篇]|[\d]+(?:\.[\d]+)*)\s*"
    r"(.+?)"
    r"[\s.…·\-_]*(\d+)?\s*$"
)

# ========== 排除的通用 style ==========
_EXCLUDED_STYLES = {
    "normal", "body text", "body", "default paragraph font",
    "list paragraph", "no spacing", "annotation text",
    "header", "footer", "footnote text",
}

# ========== 投标文件关键词 ==========
_TENDER_KEYWORDS_L1 = [
    "投标函", "开标一览表", "法人授权委托书", "授权委托书",
    "报价表", "唱标表", "资格证明文件", "资格证明",
    "技术方案", "技术部分", "商务条款", "商务部分", "商务方案",
    "偏离表", "项目业绩", "售后服务方案", "售后服务",
    "投标保证金", "联合体协议", "投标文件格式",
]

_TENDER_KEYWORDS_L2 = [
    "营业执照", "财务报告", "审计报告", "纳税证明",
    "社保证明", "信用查询", "资质证书", "业绩证明",
    "人员资质", "类似项目", "获奖证明",
]

# ========== 编号正则（复用 rule_splitter.py 模式）==========
_RE_CHAPTER = re.compile(
    r"^第[一二三四五六七八九十百零]+[章节篇部]"
    r"|^第[一二三四五六七八九十百零]+部分"
)
_RE_ORDINAL = re.compile(r"^[一二三四五六七八九十]+[、\.\．]")
_RE_PAREN = re.compile(r"^（[一二三四五六七八九十]+）|^\([一二三四五六七八九十]+\)")

_MAX_HEADING_LEN = 80


# ========== 工具函数 ==========

def _parse_toc_level(prefix: str) -> int:
    if prefix.startswith("第"):
        return 1
    return prefix.count(".") + 1 if "." in prefix else 1


def _has_toc_style(para: Paragraph) -> bool:
    return bool(para.style and ("toc" in para.style.lower() or "目录" in para.style.lower()))


def _fuzzy_match(title: str, para_text: str, threshold: float = 0.7) -> bool:
    clean_title = title.strip()
    clean_para = para_text.strip()
    if clean_para.startswith(clean_title):
        return True
    ratio = difflib.SequenceMatcher(
        None, clean_title, clean_para[: len(clean_title) + 20]
    ).ratio()
    return ratio >= threshold


def compute_confidence(
    found_sections: int, total_paragraphs: int, assigned_paragraphs: int
) -> float:
    """置信度 = min(sections/6, 1.0) * (assigned/total)"""
    if total_paragraphs == 0 or found_sections == 0:
        return 0.0
    section_ratio = min(found_sections / 6.0, 1.0)
    coverage_ratio = assigned_paragraphs / total_paragraphs
    return round(section_ratio * coverage_ratio, 4)


def _count_assigned(paragraphs: list[Paragraph], sections: list[dict]) -> int:
    """计算被章节覆盖的段落数（从第一个章节标题到文档末尾）。"""
    if not sections:
        return 0
    first_start = min(s["start"] for s in sections)
    return len(paragraphs) - first_start


def _select_best_strategy(
    paragraphs: list[Paragraph],
    strategies: list[tuple[str, list[dict]]],
) -> tuple[list[dict], float, str]:
    """从多个策略中选择置信度最高的。"""
    best_sections: list[dict] = []
    best_confidence = 0.0
    best_name = ""

    for name, sections in strategies:
        if not sections:
            continue
        top_sections = [s for s in sections if s["level"] == 1]
        if not top_sections:
            top_sections = sections
        assigned = _count_assigned(paragraphs, sections)
        confidence = compute_confidence(len(top_sections), len(paragraphs), assigned)
        logger.debug("策略 %s: %d 章节, 置信度 %.4f", name, len(sections), confidence)
        if confidence > best_confidence:
            best_confidence = confidence
            best_sections = sections
            best_name = name

    return best_sections, best_confidence, best_name


def _sections_to_chapters(sections: list[dict], total_paragraphs: int) -> list[dict]:
    """将扁平 sections 转换为层级 chapters 格式（兼容 tender_indexer）。"""
    if not sections:
        return []

    sorted_secs = sorted(sections, key=lambda s: s["start"])

    # 计算 end_para
    for i, sec in enumerate(sorted_secs):
        if i + 1 < len(sorted_secs):
            sec["end"] = sorted_secs[i + 1]["start"] - 1
        else:
            sec["end"] = total_paragraphs - 1

    # 构建层级
    root_chapters: list[dict] = []
    current_parent: dict | None = None
    for sec in sorted_secs:
        ch = {
            "title": sec["title"],
            "level": sec["level"],
            "start_para": sec["start"],
            "end_para": sec["end"],
            "children": [],
        }
        if sec["level"] == 1:
            current_parent = ch
            root_chapters.append(ch)
        elif current_parent is not None:
            current_parent["children"].append(ch)
        else:
            root_chapters.append(ch)

    return root_chapters


# ========== 策略实现 ==========

def strategy_toc(paragraphs: list[Paragraph]) -> list[dict] | None:
    """策略 1：目录识别 + 模糊匹配定位正文段落。

    成功条件：匹配到 >= 3 个 TOC 条目。
    Returns None if no TOC detected.
    """
    scan_range = paragraphs[:80]

    # 子策略 A：TOC style 检测
    toc_entries: list[dict] = []
    for para in scan_range:
        if _has_toc_style(para) and para.text.strip() != "目录":
            m = _TOC_LINE_RE.match(para.text.strip())
            if m:
                prefix, title = m.group(1), m.group(2).strip()
                toc_entries.append({
                    "title": f"{prefix} {title}".strip(),
                    "level": _parse_toc_level(prefix),
                })
    if len(toc_entries) >= 3:
        return _match_toc_to_body(toc_entries, paragraphs)

    # 子策略 B："目录"标题后的连续条目
    toc_start = None
    for i, para in enumerate(scan_range):
        text = para.text.strip().replace(" ", "").replace("\u3000", "")
        if text in ("目录", "CONTENTS"):
            toc_start = i + 1
            break

    if toc_start is None:
        return None

    toc_entries = []
    consecutive_misses = 0
    for para in scan_range[toc_start:]:
        m = _TOC_LINE_RE.match(para.text.strip())
        if m:
            prefix, title = m.group(1), m.group(2).strip()
            toc_entries.append({
                "title": f"{prefix} {title}".strip(),
                "level": _parse_toc_level(prefix),
            })
            consecutive_misses = 0
        else:
            consecutive_misses += 1
            if consecutive_misses >= 3:
                break

    if len(toc_entries) >= 3:
        return _match_toc_to_body(toc_entries, paragraphs)

    return None


def _match_toc_to_body(
    toc_entries: list[dict], paragraphs: list[Paragraph]
) -> list[dict]:
    """将 TOC 条目模糊匹配到正文段落，返回 sections。"""
    sections: list[dict] = []
    for entry in toc_entries:
        for para in paragraphs:
            if _fuzzy_match(entry["title"], para.text):
                sections.append({
                    "title": entry["title"],
                    "start": para.index,
                    "level": entry["level"],
                })
                break
    return sections


def strategy_style(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 2：Style ID 频率分析。

    适用于 style 为数字 ID（如 '1','2','3'）的投标文档。
    按出现频率推断层级：最少 → level 1。
    """
    style_counter: Counter[str] = Counter()
    style_texts: dict[str, list[tuple[int, str]]] = {}

    for p in paragraphs:
        if not p.style:
            continue
        s = p.style.strip()
        if s.lower() in _EXCLUDED_STYLES:
            continue
        style_counter[s] += 1
        style_texts.setdefault(s, []).append((p.index, p.text))

    if not style_counter:
        return []

    total = len(paragraphs)

    # 过滤候选标题 style
    candidates: list[tuple[str, int]] = []
    for style, count in style_counter.items():
        if count >= total * 0.2:
            continue
        texts = style_texts[style]
        avg_len = sum(len(t) for _, t in texts) / len(texts) if texts else 0
        if avg_len >= 80:
            continue
        candidates.append((style, count))

    if not candidates:
        return []

    # 按频率升序：最少 → level 1
    candidates.sort(key=lambda x: x[1])

    style_to_level: dict[str, int] = {}
    for i, (style, _) in enumerate(candidates[:3]):
        style_to_level[style] = i + 1

    sections: list[dict] = []
    for p in paragraphs:
        if p.style and p.style.strip() in style_to_level:
            text = p.text.strip()
            if text and len(text) < 80:
                sections.append({
                    "title": text,
                    "start": p.index,
                    "level": style_to_level[p.style.strip()],
                })

    return sections


def strategy_keywords(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 3：投标文件关键词匹配。"""
    sections: list[dict] = []
    for p in paragraphs:
        text = p.text.strip()
        if len(text) > 80:
            continue

        matched = False
        for kw in _TENDER_KEYWORDS_L1:
            if kw in text:
                sections.append({"title": text, "start": p.index, "level": 1})
                matched = True
                break

        if not matched:
            for kw in _TENDER_KEYWORDS_L2:
                if kw in text:
                    sections.append({"title": text, "start": p.index, "level": 2})
                    break

    return sections


def strategy_numbering(paragraphs: list[Paragraph]) -> list[dict]:
    """策略 4：编号正则匹配。"""
    sections: list[dict] = []
    for p in paragraphs:
        text = p.text.strip()

        if _RE_CHAPTER.match(text):
            sections.append({"title": text, "start": p.index, "level": 1})
        elif _RE_ORDINAL.match(text) and len(text) < _MAX_HEADING_LEN:
            sections.append({"title": text, "start": p.index, "level": 2})
        elif _RE_PAREN.match(text) and len(text) < _MAX_HEADING_LEN:
            sections.append({"title": text, "start": p.index, "level": 3})

    return sections


# ========== 统一入口 ==========

LLM_FALLBACK_THRESHOLD = 0.7


def build_tender_index(
    paragraphs: list[Paragraph], api_settings: dict | None = None
) -> dict:
    """构建投标文件索引（5 层混合策略）。

    返回格式兼容现有 tender_indexer:
    {
        "toc_source": "document_toc"|"style_analysis"|"keywords"|"numbering"|"llm_generated",
        "confidence": float,
        "chapters": [{"title", "level", "start_para", "end_para", "children": [...]}]
    }
    """
    total = len(paragraphs)

    # 策略 1：目录识别（单独赛道，成功直接采用）
    toc_sections = strategy_toc(paragraphs)
    if toc_sections and len(toc_sections) >= 3:
        chapters = _sections_to_chapters(toc_sections, total)
        top = [s for s in toc_sections if s["level"] == 1] or toc_sections
        assigned = _count_assigned(paragraphs, toc_sections)
        confidence = compute_confidence(len(top), total, assigned)
        return {
            "toc_source": "document_toc",
            "confidence": confidence,
            "chapters": chapters,
        }

    # 策略 2-4：竞争赛道
    strategies = [
        ("style_analysis", strategy_style(paragraphs)),
        ("keywords", strategy_keywords(paragraphs)),
        ("numbering", strategy_numbering(paragraphs)),
    ]

    best_sections, best_confidence, best_name = _select_best_strategy(
        paragraphs, strategies
    )

    # 策略 5：LLM 兜底
    if best_confidence < LLM_FALLBACK_THRESHOLD and api_settings:
        logger.info(
            "最高置信度 %.2f < %.2f，启用 LLM 兜底",
            best_confidence, LLM_FALLBACK_THRESHOLD,
        )
        try:
            from src.reviewer.clause_mapper import llm_extract_toc
            from src.reviewer.tender_indexer import build_index_from_toc

            toc = llm_extract_toc(paragraphs, api_settings)
            if toc:
                index = build_index_from_toc(toc, paragraphs)
                index["toc_source"] = "llm_generated"
                index["confidence"] = 0.5
                return index
        except Exception as e:
            logger.warning("LLM 兜底索引失败: %s", e)

    # 使用最佳规则结果
    chapters = _sections_to_chapters(best_sections, total)
    return {
        "toc_source": best_name or "numbering",
        "confidence": best_confidence,
        "chapters": chapters,
    }
```

- [ ] **Step 2: Commit**

```bash
git add src/reviewer/tender_rule_splitter.py
git commit -m "feat(reviewer): add tender_rule_splitter with 5-layer hybrid indexing"
```

---

### Task 6: 索引器单元测试

**Files:**
- Create: `src/reviewer/tests/test_tender_rule_splitter.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for tender document hybrid indexer."""
from src.models import Paragraph
from src.reviewer.tender_rule_splitter import (
    strategy_toc,
    strategy_style,
    strategy_keywords,
    strategy_numbering,
    compute_confidence,
    build_tender_index,
    _sections_to_chapters,
    _count_assigned,
)


def _make_paras(texts: list[str], styles: list[str | None] | None = None) -> list[Paragraph]:
    if styles is None:
        styles = [None] * len(texts)
    return [Paragraph(index=i, text=t, style=s) for i, (t, s) in enumerate(zip(texts, styles))]


# ========== strategy_toc ==========

class TestStrategyToc:
    def test_toc_style_detection(self):
        """TOC style 段落被识别并匹配到正文。"""
        paras = _make_paras(
            ["目录", "第一章 投标函 ........ 1", "第二章 技术方案 ...... 5",
             "第三章 商务报价 ...... 10",
             # 正文
             "第一章 投标函", "致采购人", "第二章 技术方案", "本系统采用",
             "第三章 商务报价", "报价明细"],
            ["TOCHeading", "TOC1", "TOC1", "TOC1",
             None, None, None, None, None, None],
        )
        result = strategy_toc(paras)
        assert result is not None
        assert len(result) >= 3
        assert result[0]["title"] == "第一章 投标函"
        assert result[0]["start"] == 4  # 匹配到正文段落

    def test_toc_pattern_after_heading(self):
        """'目录'标题后的连续条目被识别。"""
        paras = _make_paras(
            ["目  录",
             "第一章 投标函 1", "第二章 授权委托书 3",
             "第三章 技术方案 5", "第四章 商务方案 12",
             # 正文
             "第一章 投标函", "内容A",
             "第二章 授权委托书", "内容B",
             "第三章 技术方案", "内容C",
             "第四章 商务方案", "内容D"]
        )
        result = strategy_toc(paras)
        assert result is not None
        assert len(result) >= 3

    def test_no_toc_returns_none(self):
        """无目录文档返回 None。"""
        paras = _make_paras([f"普通段落 {i}" for i in range(60)])
        result = strategy_toc(paras)
        assert result is None


# ========== strategy_style ==========

class TestStrategyStyle:
    def test_numeric_style_ids(self):
        """数字 style ID 按频率推断层级。"""
        texts = (
            ["章节标题A", "章节标题B"]  # style "1", 出现 2 次 → level 1
            + ["小节标题1", "小节标题2", "小节标题3"]  # style "2", 出现 3 次 → level 2
            + [f"正文段落 {i}" for i in range(20)]  # style None
        )
        styles: list[str | None] = (
            ["1", "1"]
            + ["2", "2", "2"]
            + [None] * 20
        )
        paras = _make_paras(texts, styles)
        result = strategy_style(paras)
        assert len(result) >= 2
        # style "1" 出现最少 → level 1
        level1 = [s for s in result if s["level"] == 1]
        assert len(level1) == 2

    def test_excludes_normal_style(self):
        """Normal style 被排除。"""
        paras = _make_paras(
            ["段落A", "段落B", "段落C"],
            ["Normal", "Normal", "Normal"],
        )
        result = strategy_style(paras)
        assert result == []

    def test_excludes_high_frequency_styles(self):
        """出现频率 >= 20% 的 style 被排除。"""
        texts = [f"段落 {i}" for i in range(10)]
        styles: list[str | None] = ["1"] * 3 + [None] * 7  # 3/10 = 30% >= 20%
        paras = _make_paras(texts, styles)
        result = strategy_style(paras)
        # style "1" should be excluded due to high frequency
        assert all(s["title"] != "段落 0" for s in result)


# ========== strategy_keywords ==========

class TestStrategyKeywords:
    def test_l1_keywords(self):
        """顶层关键词被识别为 level 1。"""
        paras = _make_paras([
            "一、投标函", "致采购人...",
            "二、技术方案", "本系统...",
            "三、商务方案", "报价...",
        ])
        result = strategy_keywords(paras)
        titles = [s["title"] for s in result]
        assert "一、投标函" in titles
        assert "二、技术方案" in titles
        assert all(s["level"] == 1 for s in result)

    def test_l2_keywords(self):
        """次级关键词被识别为 level 2。"""
        paras = _make_paras([
            "投标函", "内容...",
            "营业执照", "证照编号...",
            "资质证书", "证书编号...",
        ])
        result = strategy_keywords(paras)
        l2 = [s for s in result if s["level"] == 2]
        assert len(l2) >= 2

    def test_long_text_excluded(self):
        """超过 80 字符的段落不被识别为关键词标题。"""
        paras = _make_paras(["投标函" + "x" * 80])
        result = strategy_keywords(paras)
        assert result == []


# ========== strategy_numbering ==========

class TestStrategyNumbering:
    def test_chapter_numbering(self):
        """'第X章' 模式被识别为 level 1。"""
        paras = _make_paras(["第一章 总则", "内容", "第二章 技术要求", "内容"])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 1 for s in result)

    def test_ordinal_numbering(self):
        """'一、' 模式被识别为 level 2。"""
        paras = _make_paras(["一、概述", "二、范围", "正文内容" * 30])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 2 for s in result)

    def test_paren_numbering(self):
        """'（一）' 模式被识别为 level 3。"""
        paras = _make_paras(["（一）投标人资格", "（二）投标文件"])
        result = strategy_numbering(paras)
        assert len(result) == 2
        assert all(s["level"] == 3 for s in result)


# ========== compute_confidence ==========

class TestComputeConfidence:
    def test_basic(self):
        assert compute_confidence(6, 100, 90) == 0.9

    def test_capped_sections(self):
        """超过 6 个 sections 不增加置信度。"""
        assert compute_confidence(12, 100, 100) == 1.0

    def test_zero_paragraphs(self):
        assert compute_confidence(3, 0, 0) == 0.0


# ========== _sections_to_chapters ==========

class TestSectionsToChapters:
    def test_hierarchy(self):
        """level 2 成为前一个 level 1 的 children。"""
        sections = [
            {"title": "第一章", "start": 0, "level": 1},
            {"title": "1.1 小节", "start": 3, "level": 2},
            {"title": "第二章", "start": 5, "level": 1},
        ]
        chapters = _sections_to_chapters(sections, 10)
        assert len(chapters) == 2
        assert len(chapters[0]["children"]) == 1
        assert chapters[0]["children"][0]["title"] == "1.1 小节"
        assert chapters[0]["end_para"] == 4
        assert chapters[1]["end_para"] == 9


# ========== build_tender_index ==========

class TestBuildTenderIndex:
    def test_toc_takes_priority(self):
        """有目录时直接采用，不参与竞争。"""
        paras = _make_paras(
            ["目录",
             "第一章 投标函 1", "第二章 技术方案 3", "第三章 商务报价 5",
             "第一章 投标函", "内容A",
             "第二章 技术方案", "内容B",
             "第三章 商务报价", "内容C"],
        )
        result = build_tender_index(paras)
        assert result["toc_source"] == "document_toc"
        assert len(result["chapters"]) >= 3

    def test_keywords_fallback(self):
        """无目录时关键词策略生效。"""
        paras = _make_paras(
            ["投标函", "致采购人...", "承诺...",
             "技术方案", "系统架构...", "实施计划...",
             "商务方案", "报价明细...", "付款方式...",
             "售后服务方案", "服务承诺...", "维保...",
             "偏离表", "无偏离...", "确认...",
             "项目业绩", "业绩1...", "业绩2...",
             ] + [f"正文{i}" for i in range(30)]
        )
        result = build_tender_index(paras)
        assert result["toc_source"] in ("keywords", "numbering", "style_analysis")
        assert result["confidence"] > 0

    def test_returns_compatible_format(self):
        """返回格式兼容 get_chapter_text。"""
        paras = _make_paras(
            ["第一章 投标函", "内容A", "第二章 技术方案", "内容B"],
        )
        result = build_tender_index(paras)
        assert "toc_source" in result
        assert "confidence" in result
        assert "chapters" in result
        for ch in result["chapters"]:
            assert "title" in ch
            assert "start_para" in ch
            assert "end_para" in ch
            assert "children" in ch
```

- [ ] **Step 2: 运行测试**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/test_tender_rule_splitter.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/reviewer/tests/test_tender_rule_splitter.py
git commit -m "test(reviewer): add tests for tender_rule_splitter hybrid indexer"
```

---

### Task 7: review_task.py — 集成新索引器

**Files:**
- Modify: `server/app/tasks/review_task.py`

- [ ] **Step 1: 替换索引逻辑**

在 `review_task.py` 的 import 区域和 Step 2（构建索引）部分：

**替换 import（行 26-28）：**

移除：
```python
from src.reviewer.toc_detector import detect_toc
from src.reviewer.tender_indexer import build_index_from_toc, get_chapter_text
```

替换为：
```python
from src.reviewer.tender_rule_splitter import build_tender_index
from src.reviewer.tender_indexer import get_chapter_text
```

**替换 Step 2 索引逻辑（行 103-118）：**

移除：
```python
            toc = detect_toc(paragraphs)
            if toc:
                tender_index = build_index_from_toc(toc, paragraphs)
                tender_index["toc_source"] = "document_toc"
            else:
                logger.info("No TOC detected, using LLM to extract chapters")
                toc = llm_extract_toc(paragraphs, api_settings)
                tender_index = build_index_from_toc(toc, paragraphs)
                tender_index["toc_source"] = "llm_generated"
            review.tender_index = tender_index
```

替换为：
```python
            tender_index = build_tender_index(paragraphs, api_settings)
            logger.info(
                "Tender index built: source=%s, confidence=%.2f, chapters=%d",
                tender_index.get("toc_source"), tender_index.get("confidence", 0),
                len(tender_index.get("chapters", [])),
            )
            review.tender_index = tender_index
```

同时移除顶部不再使用的 import：`llm_extract_toc`（如果不再直接调用）。

检查 `llm_extract_toc` 是否在其他地方还被使用 — 它在 Step 4 `llm_map_clauses_to_chapters` 中仍需要，但那是从 `clause_mapper` 导入的独立函数，不受影响。`llm_extract_toc` 只在旧索引逻辑中直接调用，新逻辑中由 `build_tender_index` 内部按需调用。

最终 import 行：
```python
from src.reviewer.tender_rule_splitter import build_tender_index
from src.reviewer.tender_indexer import get_chapter_text
from src.reviewer.clause_extractor import extract_review_clauses, extract_project_context
from src.reviewer.clause_mapper import llm_map_clauses_to_chapters
```

- [ ] **Step 2: 运行集成测试**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_review_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: 运行所有 reviewer 测试**

Run: `cd /d/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest src/reviewer/tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add server/app/tasks/review_task.py
git commit -m "feat(review-task): integrate hybrid tender indexer + align 6-step progress keys"
```

---

## 验证清单

- [ ] 前端构建无错误：`cd web && npx vue-tsc --noEmit && npm run build`
- [ ] 后端单元测试全通过：`python -m pytest src/reviewer/tests/ -v`
- [ ] 后端集成测试全通过：`python -m pytest server/tests/test_review_integration.py -v`
- [ ] Docker 部署更新：重新构建镜像并重启服务
