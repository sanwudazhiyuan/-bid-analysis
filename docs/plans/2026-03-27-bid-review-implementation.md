# 标书审查功能实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"标书审查"功能，用户上传投标文件后系统自动与已解析的招标要求逐条核对，生成带 Word 原生批注的审查报告。

**Architecture:** 新增 `ReviewTask` 数据模型独立于现有 `Task` 表。审查核心逻辑放在 `src/reviewer/` 目录下（信息脱敏、图片提取、TOC 检测、条款提取、LLM 核对、docx 批注生成）。上传投标文件后先执行 PII 脱敏（姓名、电话、身份证等）并提取文档中的图片供审阅。后端通过新的 `/api/reviews` 路由和 `run_review` Celery 任务驱动。前端新增 `BidReviewView`（三阶段状态机）和 `ReviewResultsView`。

**Tech Stack:** Python 3.11, FastAPI, Celery, SQLAlchemy (asyncpg), python-docx + lxml, Vue 3 + TypeScript + Pinia + Tailwind CSS v4, Vitest

**Spec:** `docs/specs/2026-03-27-bid-review-design.md`

---

## Chunk 1: 基础设施（数据模型 + 配置 + API 框架）

### Task 1: 上传大小限制调整

**Files:**
- Modify: `server/app/config.py:16`
- Modify: `server/app/services/task_service.py:29`
- Modify: `web/nginx.conf:7`

- [ ] **Step 1: 修改 config.py 中的 MAX_UPLOAD_SIZE**

```python
# server/app/config.py line 16
MAX_UPLOAD_SIZE: int = 500 * 1024 * 1024  # 500MB
```

- [ ] **Step 2: 修改 task_service.py 中的错误消息**

```python
# server/app/services/task_service.py line 29
raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")
```

- [ ] **Step 3: 修改 nginx.conf 中的 client_max_body_size**

```nginx
# web/nginx.conf line 7
client_max_body_size 500m;
```

- [ ] **Step 4: Commit**

```bash
git add server/app/config.py server/app/services/task_service.py web/nginx.conf
git commit -m "chore: increase upload size limit to 500MB for tender files"
```

---

### Task 2: ReviewTask 数据模型

**Files:**
- Create: `server/app/models/review_task.py`
- Modify: `server/app/models/__init__.py:7-9` (导出 ReviewTask 确保表创建)
- Modify: `server/app/main.py:1` (import 触发表创建)
- Test: `server/tests/test_review_model.py`

- [ ] **Step 1: 编写 ReviewTask 模型测试**

```python
# server/tests/test_review_model.py
import uuid
import pytest
from server.app.models.review_task import ReviewTask


def test_review_task_fields():
    """ReviewTask has all required fields."""
    rt = ReviewTask(
        id=uuid.uuid4(),
        user_id=1,
        bid_task_id=uuid.uuid4(),
        tender_filename="投标文件.docx",
        tender_file_path="/data/reviews/test/投标文件.docx",
        version=1,
        status="pending",
        progress=0,
    )
    assert rt.status == "pending"
    assert rt.version == 1
    assert rt.review_summary is None
    assert rt.review_items is None
    assert rt.annotated_file_path is None


def test_review_task_default_values():
    """Optional fields default to None."""
    rt = ReviewTask(
        id=uuid.uuid4(),
        user_id=1,
        bid_task_id=uuid.uuid4(),
        tender_filename="test.docx",
        tender_file_path="/tmp/test.docx",
        version=1,
        status="pending",
        progress=0,
    )
    assert rt.current_step is None
    assert rt.error_message is None
    assert rt.celery_task_id is None
    assert rt.tender_index is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && python -m pytest tests/test_review_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.app.models.review_task'`

- [ ] **Step 3: 实现 ReviewTask 模型**

```python
# server/app/models/review_task.py
"""ReviewTask ORM model for bid document review."""
import datetime
import uuid as _uuid

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    bid_task_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    tender_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    tender_file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(200))

    review_summary: Mapped[dict | None] = mapped_column(JSONB)
    review_items: Mapped[list | None] = mapped_column(JSONB)
    tender_index: Mapped[dict | None] = mapped_column(JSONB)

    annotated_file_path: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, onupdate=func.now())

    user = relationship("User")
    bid_task = relationship("Task")

    __table_args__ = (
        UniqueConstraint(
            "bid_task_id", "tender_filename", "version",
            name="uq_review_version",
        ),
    )
```

- [ ] **Step 4: 在 `__init__.py` 和 main.py 中导入模型确保表创建**

在 `server/app/models/__init__.py` 中添加 ReviewTask 导出：

```python
# server/app/models/__init__.py
"""导出 Base + 所有 ORM 模型。"""

from server.app.database import Base
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.annotation import Annotation
from server.app.models.generated_file import GeneratedFile
from server.app.models.review_task import ReviewTask

__all__ = ["Base", "User", "Task", "Annotation", "GeneratedFile", "ReviewTask"]
```

在 `server/app/main.py` 的 import 区域末尾添加：

```python
# server/app/main.py — 在现有 import 行之后添加
import server.app.models.review_task  # noqa: F401 — ensure table is created
```

同时更新 `server/tests/conftest.py` 第 19 行导入：

```python
from server.app.models import User, Task, Annotation, GeneratedFile, ReviewTask  # noqa: F401
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd server && python -m pytest tests/test_review_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/app/models/review_task.py server/tests/test_review_model.py server/app/main.py
git commit -m "feat(model): add ReviewTask ORM model with version constraint"
```

---

### Task 3: 审查 API 路由框架 + review_service

**Files:**
- Create: `server/app/routers/reviews.py`
- Create: `server/app/services/review_service.py`
- Modify: `server/app/main.py:11,47` (注册路由)
- Modify: `server/app/routers/tasks.py:27-36` (添加 q 搜索参数)
- Test: `server/tests/test_reviews_api.py`

- [ ] **Step 1: 编写 API 测试**

```python
# server/tests/test_reviews_api.py
"""Tests for /api/reviews endpoints — uses conftest fixtures (client, db_session, auth_headers)."""
import uuid
import pytest

from server.app.models.task import Task

pytestmark = pytest.mark.asyncio


async def test_create_review_missing_bid_task(client, auth_headers):
    """POST /api/reviews with invalid bid_task_id returns 404."""
    resp = await client.post(
        "/api/reviews",
        data={"bid_task_id": str(uuid.uuid4())},
        files={"tender_file": ("投标.docx", b"dummy", "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_list_reviews_empty(client, auth_headers):
    """GET /api/reviews returns empty list when no reviews exist."""
    resp = await client.get("/api/reviews", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_delete_review_not_found(client, auth_headers):
    """DELETE /api/reviews/{id} returns 404 for non-existent review."""
    resp = await client.delete(
        f"/api/reviews/{uuid.uuid4()}", headers=auth_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd server && python -m pytest tests/test_reviews_api.py -v`
Expected: FAIL — 404 on all routes (router not registered)

- [ ] **Step 3: 实现 review_service.py**

```python
# server/app/services/review_service.py
"""Business logic for bid document review tasks."""
import os
import shutil
import uuid as _uuid

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.task import Task
from server.app.models.review_task import ReviewTask

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}


async def create_review(
    db: AsyncSession, tender_file: UploadFile, bid_task_id: str, user_id: int
) -> ReviewTask:
    """Create a review task: validate bid_task, save file, compute version."""
    # Validate bid_task
    try:
        task_uuid = _uuid.UUID(bid_task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid bid_task_id")

    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    bid_task = result.scalar_one_or_none()
    if not bid_task:
        raise HTTPException(status_code=404, detail="招标任务不存在")

    # Validate file
    filename = tender_file.filename or "unknown"
    try:
        filename = filename.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await tender_file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    # Compute version
    version_result = await db.execute(
        select(func.coalesce(func.max(ReviewTask.version), 0)).where(
            ReviewTask.bid_task_id == task_uuid,
            ReviewTask.tender_filename == filename,
        )
    )
    version = version_result.scalar() + 1

    # Save file
    review_id = _uuid.uuid4()
    review_dir = os.path.join(settings.DATA_DIR, "reviews", str(review_id))
    os.makedirs(review_dir, exist_ok=True)
    file_path = os.path.join(review_dir, filename)
    with open(file_path, "wb") as f:
        f.write(content)

    review = ReviewTask(
        id=review_id,
        user_id=user_id,
        bid_task_id=task_uuid,
        tender_filename=filename,
        tender_file_path=file_path,
        version=version,
        status="pending",
        progress=0,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def get_reviews(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20, q: str | None = None
):
    """List review tasks for user, latest version per (bid_task_id, tender_filename)."""
    base = select(ReviewTask).where(ReviewTask.user_id == user_id)
    if q:
        base = base.where(ReviewTask.tender_filename.ilike(f"%{q}%"))
    base = base.order_by(ReviewTask.created_at.desc())

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    result = await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return items, total


async def get_review(db: AsyncSession, review_id: str, user_id: int) -> ReviewTask | None:
    try:
        rid = _uuid.UUID(review_id)
    except ValueError:
        return None
    result = await db.execute(
        select(ReviewTask).where(ReviewTask.id == rid, ReviewTask.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_review(db: AsyncSession, review_id: str, user_id: int):
    review = await get_review(db, review_id, user_id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")
    # Clean up files
    review_dir = os.path.dirname(review.tender_file_path)
    if os.path.isdir(review_dir):
        shutil.rmtree(review_dir, ignore_errors=True)
    await db.delete(review)
    await db.commit()
```

- [ ] **Step 4: 实现 reviews.py 路由**

```python
# server/app/routers/reviews.py
"""Router for bid document review — create, list, detail, delete, progress, preview, download."""
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.services.review_service import (
    create_review, get_reviews, get_review, delete_review,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    tender_file: UploadFile = File(...),
    bid_task_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_review(db, tender_file, bid_task_id, user.id)
    # TODO: dispatch run_review Celery task here (Task 8)
    return {"id": str(review.id), "status": review.status, "version": review.version}


@router.get("")
async def list_reviews_endpoint(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await get_reviews(db, user.id, page, page_size, q)
    # Eager-load bid_task for each item
    for r in items:
        await db.refresh(r, ["bid_task"])
    return {
        "items": [
            {
                "id": str(r.id),
                "bid_task_id": str(r.bid_task_id),
                "bid_filename": r.bid_task.filename if r.bid_task else "",
                "tender_filename": r.tender_filename,
                "version": r.version,
                "status": r.status,
                "review_summary": r.review_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{review_id}")
async def get_review_endpoint(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")
    # Eager-load bid_task for filename
    await db.refresh(review, ["bid_task"])
    return {
        "id": str(review.id),
        "bid_task_id": str(review.bid_task_id),
        "bid_filename": review.bid_task.filename if review.bid_task else "",
        "tender_filename": review.tender_filename,
        "version": review.version,
        "status": review.status,
        "progress": review.progress,
        "review_summary": review.review_summary,
        "review_items": review.review_items,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


@router.delete("/{review_id}", status_code=204)
async def delete_review_endpoint(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_review(db, review_id, user.id)


@router.get("/{review_id}/download")
async def download_review(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await get_review(db, review_id, user.id)
    if not review or not review.annotated_file_path or not os.path.exists(review.annotated_file_path):
        raise HTTPException(status_code=404, detail="审查报告不存在")
    return FileResponse(
        review.annotated_file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"审查报告_{review.tender_filename}",
    )
```

- [ ] **Step 5: 注册路由到 main.py**

```python
# server/app/main.py line 11 — 添加 reviews 导入
from server.app.routers import auth, tasks, download, preview, annotations, users, files, reviews

# server/app/main.py line 47 之后添加
app.include_router(reviews.router)
```

- [ ] **Step 6: 给 tasks list 添加 q 搜索参数（供审查上传页使用）**

在 `server/app/routers/tasks.py` 的 `list_tasks` 函数签名中添加 `q` 参数：

```python
# server/app/routers/tasks.py line 27-36
@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await get_tasks(db, user.id, page, page_size, status, q)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)
```

同时在 `server/app/services/task_service.py` 的 `get_tasks` 函数中添加 `q` 参数支持（注意 `count_query` 也要加过滤）：

```python
# server/app/services/task_service.py — 替换整个 get_tasks 函数
async def get_tasks(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
) -> tuple[list, int]:
    query = select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc())
    count_query = select(func.count()).select_from(Task).where(Task.user_id == user_id)
    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)
    if q:
        query = query.where(Task.filename.ilike(f"%{q}%"))
        count_query = count_query.where(Task.filename.ilike(f"%{q}%"))
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd server && python -m pytest tests/test_reviews_api.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add server/app/routers/reviews.py server/app/services/review_service.py \
  server/tests/test_reviews_api.py server/app/main.py \
  server/app/routers/tasks.py server/app/services/task_service.py
git commit -m "feat(api): add /api/reviews CRUD endpoints + task search"
```

---

## Chunk 2: 审查核心模块（TOC 检测 + 条款提取 + 索引构建）

### Task 4: TOC 检测器

**Files:**
- Create: `src/reviewer/__init__.py`
- Create: `src/reviewer/toc_detector.py`
- Test: `src/reviewer/tests/__init__.py`
- Test: `src/reviewer/tests/test_toc_detector.py`

- [ ] **Step 1: 编写 TOC 检测测试**

```python
# src/reviewer/tests/test_toc_detector.py
"""Tests for TOC detection in tender documents."""
from src.models import Paragraph
from src.reviewer.toc_detector import detect_toc


def test_detect_toc_with_toc_style():
    """Paragraphs with TOC style are detected as table of contents."""
    paras = [
        Paragraph(index=0, text="目录", style="TOCHeading"),
        Paragraph(index=1, text="第一章 投标函 ........ 1", style="TOC1"),
        Paragraph(index=2, text="第二章 技术方案 ...... 5", style="TOC1"),
        Paragraph(index=3, text="2.1 系统架构 ........ 6", style="TOC2"),
        Paragraph(index=4, text="第三章 商务报价 ...... 10", style="TOC1"),
    ] + [Paragraph(index=i + 5, text=f"正文段落{i}") for i in range(50)]
    result = detect_toc(paras)
    assert result is not None
    assert len(result) >= 3
    assert result[0]["title"] == "第一章 投标函"
    assert result[0]["level"] == 1


def test_detect_toc_with_pattern_matching():
    """Lines matching '第X章 title ... page' pattern are detected."""
    paras = [
        Paragraph(index=0, text="目  录"),
        Paragraph(index=1, text="第一章 投标函 1"),
        Paragraph(index=2, text="第二章 授权委托书 3"),
        Paragraph(index=3, text="第三章 技术方案 5"),
        Paragraph(index=4, text="第四章 商务方案 12"),
        Paragraph(index=5, text="第五章 服务承诺 18"),
    ] + [Paragraph(index=i + 6, text=f"正文{i}") for i in range(50)]
    result = detect_toc(paras)
    assert result is not None
    assert len(result) == 5


def test_detect_toc_none_when_no_toc():
    """Returns None when document has no detectable TOC."""
    paras = [Paragraph(index=i, text=f"这是一段普通文本 {i}") for i in range(60)]
    result = detect_toc(paras)
    assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_toc_detector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 toc_detector.py**

```python
# src/reviewer/__init__.py
# (empty)

# src/reviewer/tests/__init__.py
# (empty)

# src/reviewer/toc_detector.py
"""Detect and extract Table of Contents from tender documents."""
import re
from src.models import Paragraph

# TOC line pattern: "第X章 标题 ... 页码" or "X.X 标题 ... 页码"
_TOC_LINE_RE = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节篇]|[\d]+(?:\.[\d]+)*)\s*"
    r"(.+?)"
    r"[\s.…·\-_]*(\d+)?\s*$"
)

def _parse_level(prefix: str) -> int:
    """Determine heading level from prefix. '第X章'→1, 'X.X'→dot count."""
    if prefix.startswith("第"):
        return 1
    return prefix.count(".") + 1 if "." in prefix else 1


def _has_toc_style(para: Paragraph) -> bool:
    return bool(para.style and ("toc" in para.style.lower() or "目录" in para.style.lower()))


def detect_toc(paragraphs: list[Paragraph]) -> list[dict] | None:
    """Detect and extract TOC entries from the first 50 paragraphs.

    Returns list of {title, level, page_hint} or None if no TOC found.
    """
    scan_range = paragraphs[:50]
    if not scan_range:
        return None

    # Strategy 1: TOC styles
    toc_entries = []
    for para in scan_range:
        if _has_toc_style(para) and para.text.strip() != "目录":
            m = _TOC_LINE_RE.match(para.text.strip())
            if m:
                prefix, title, page = m.group(1), m.group(2).strip(), m.group(3)
                toc_entries.append({
                    "title": f"{prefix} {title}".strip(),
                    "level": _parse_level(prefix),
                    "page_hint": int(page) if page else None,
                })
    if len(toc_entries) >= 3:
        return toc_entries

    # Strategy 2: Pattern matching after a "目录" heading
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
            prefix, title, page = m.group(1), m.group(2).strip(), m.group(3)
            toc_entries.append({
                "title": f"{prefix} {title}".strip(),
                "level": _parse_level(prefix),
                "page_hint": int(page) if page else None,
            })
            consecutive_misses = 0
        else:
            consecutive_misses += 1
            if consecutive_misses >= 3:
                break

    return toc_entries if len(toc_entries) >= 5 else None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_toc_detector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/
git commit -m "feat(reviewer): add TOC detector for tender documents"
```

---

### Task 5: 投标文件索引构建器

**Files:**
- Create: `src/reviewer/tender_indexer.py`
- Test: `src/reviewer/tests/test_tender_indexer.py`

- [ ] **Step 1: 编写索引构建测试**

```python
# src/reviewer/tests/test_tender_indexer.py
"""Tests for tender document indexing."""
from src.models import Paragraph
from src.reviewer.tender_indexer import build_index_from_toc, get_chapter_text


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t) for i, t in enumerate(texts)]


def test_build_index_basic():
    """TOC entries are matched to paragraphs by fuzzy title matching."""
    paras = _make_paras([
        "第一章 投标函",
        "致采购人：...",
        "我方承诺...",
        "第二章 技术方案",
        "2.1 系统架构",
        "本系统采用...",
        "2.2 实施计划",
        "按照以下步骤...",
        "第三章 商务报价",
        "报价明细如下...",
    ])
    toc = [
        {"title": "第一章 投标函", "level": 1, "page_hint": None},
        {"title": "第二章 技术方案", "level": 1, "page_hint": None},
        {"title": "第三章 商务报价", "level": 1, "page_hint": None},
    ]
    index = build_index_from_toc(toc, paras)
    assert len(index["chapters"]) == 3
    assert index["chapters"][0]["start_para"] == 0
    assert index["chapters"][0]["end_para"] == 2
    assert index["chapters"][1]["start_para"] == 3
    assert index["chapters"][2]["start_para"] == 8


def test_get_chapter_text():
    """get_chapter_text returns text for specified chapters."""
    paras = _make_paras(["章节标题", "段落A", "段落B", "另一章", "段落C"])
    index = {
        "chapters": [
            {"title": "第一章", "level": 1, "start_para": 0, "end_para": 2, "children": []},
            {"title": "第二章", "level": 1, "start_para": 3, "end_para": 4, "children": []},
        ]
    }
    text = get_chapter_text(paras, index, ["第一章"])
    assert "段落A" in text
    assert "段落B" in text
    assert "段落C" not in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_tender_indexer.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 tender_indexer.py**

```python
# src/reviewer/tender_indexer.py
"""Build chapter index from TOC entries + paragraphs."""
import difflib
from src.models import Paragraph


def _fuzzy_match(title: str, para_text: str, threshold: float = 0.7) -> bool:
    """Check if paragraph text starts with or closely matches the TOC title."""
    # Exact prefix match
    clean_title = title.strip()
    clean_para = para_text.strip()
    if clean_para.startswith(clean_title):
        return True
    # Fuzzy match on the shorter of the two
    ratio = difflib.SequenceMatcher(None, clean_title, clean_para[:len(clean_title) + 20]).ratio()
    return ratio >= threshold


def build_index_from_toc(toc_entries: list[dict], paragraphs: list[Paragraph]) -> dict:
    """Map TOC entries to paragraph ranges using fuzzy title matching.

    Returns tender_index structure with chapters and their paragraph ranges.
    """
    chapters = []
    matched_positions = []

    for entry in toc_entries:
        title = entry["title"]
        level = entry.get("level", 1)
        # Search paragraphs for matching title
        for para in paragraphs:
            if _fuzzy_match(title, para.text):
                matched_positions.append({
                    "title": title,
                    "level": level,
                    "start_para": para.index,
                    "children": [],
                })
                break

    # Compute end_para for each chapter
    for i, ch in enumerate(matched_positions):
        if i + 1 < len(matched_positions):
            ch["end_para"] = matched_positions[i + 1]["start_para"] - 1
        else:
            ch["end_para"] = len(paragraphs) - 1

    # Build hierarchy (level 2+ becomes children of previous level 1)
    root_chapters = []
    current_parent = None
    for ch in matched_positions:
        if ch["level"] == 1:
            current_parent = ch
            root_chapters.append(ch)
        elif current_parent is not None:
            current_parent["children"].append(ch)
        else:
            root_chapters.append(ch)

    return {"chapters": root_chapters}


def get_chapter_text(
    paragraphs: list[Paragraph],
    tender_index: dict,
    chapter_titles: list[str],
) -> str:
    """Get concatenated text for specified chapters (by title match)."""
    lines = []
    all_chapters = []
    for ch in tender_index.get("chapters", []):
        all_chapters.append(ch)
        all_chapters.extend(ch.get("children", []))

    for ch in all_chapters:
        if any(ch["title"] in t or t in ch["title"] for t in chapter_titles):
            start = ch["start_para"]
            end = ch["end_para"]
            for para in paragraphs:
                if start <= para.index <= end:
                    lines.append(f"[{para.index}] {para.text}")

    return "\n".join(lines) if lines else ""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_tender_indexer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/tender_indexer.py src/reviewer/tests/test_tender_indexer.py
git commit -m "feat(reviewer): add tender document indexer with fuzzy matching"
```

---

### Task 6: 条款提取器

**Files:**
- Create: `src/reviewer/clause_extractor.py`
- Test: `src/reviewer/tests/test_clause_extractor.py`

- [ ] **Step 1: 编写条款提取测试**

```python
# src/reviewer/tests/test_clause_extractor.py
"""Tests for clause extraction from extracted_data."""
from src.reviewer.clause_extractor import extract_review_clauses, extract_project_context


def _make_extracted_data():
    return {
        "schema_version": "1.0",
        "modules": {
            "module_a": {
                "sections": [{
                    "id": "info", "type": "table", "title": "项目基本信息",
                    "columns": ["字段", "内容"],
                    "rows": [
                        ["项目名称", "某银行IC卡采购"],
                        ["预算金额", "100万元"],
                    ],
                }]
            },
            "module_e": {
                "sections": [{
                    "id": "risks", "type": "table", "title": "废标风险",
                    "columns": ["序号", "风险项", "原文依据", "来源章节"],
                    "rows": [
                        ["1", "未按要求密封", "投标文件未密封的作废标处理", "投标须知"],
                        ["2", "未缴纳保证金", "未按时缴纳保证金", "投标须知"],
                    ],
                }]
            },
            "module_b": {
                "sections": [{
                    "id": "quals", "type": "table", "title": "资格条件",
                    "columns": ["序号", "条件", "依据"],
                    "rows": [["1", "具有独立法人资格", "资格要求"]],
                }]
            },
            "module_f": {
                "sections": [{
                    "id": "format", "type": "table", "title": "编制要求",
                    "columns": ["序号", "要求内容", "依据"],
                    "rows": [["1", "投标文件须双面打印", "投标须知"]],
                }]
            },
            "module_c": {
                "sections": [{
                    "id": "scoring", "type": "table", "title": "评分标准",
                    "columns": ["序号", "评分项", "分值"],
                    "rows": [["1", "技术方案", "30"]],
                }]
            },
        },
    }


def test_extract_clauses_module_e():
    """P0 clauses from module_e are extracted with severity=critical."""
    clauses = extract_review_clauses(_make_extracted_data())
    critical = [c for c in clauses if c["severity"] == "critical"]
    assert len(critical) == 2
    assert "未按要求密封" in critical[0]["clause_text"]
    assert critical[0]["source_module"] == "module_e"


def test_extract_clauses_module_b():
    """P1 clauses from module_b are extracted with severity=major."""
    clauses = extract_review_clauses(_make_extracted_data())
    major = [c for c in clauses if c["severity"] == "major"]
    assert len(major) >= 2  # module_b + module_f
    assert any(c["source_module"] == "module_b" for c in major)
    assert any(c["source_module"] == "module_f" for c in major)


def test_extract_clauses_module_c():
    """P2 clauses from module_c are extracted with severity=minor."""
    clauses = extract_review_clauses(_make_extracted_data())
    minor = [c for c in clauses if c["severity"] == "minor"]
    assert len(minor) >= 1
    assert minor[0]["source_module"] == "module_c"


def test_extract_clauses_ordering():
    """Clauses are ordered by priority: critical → major → minor."""
    clauses = extract_review_clauses(_make_extracted_data())
    severities = [c["severity"] for c in clauses]
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s])


def test_extract_project_context():
    """Project context is extracted from module_a."""
    ctx = extract_project_context(_make_extracted_data())
    assert "某银行IC卡采购" in ctx
    assert "100万元" in ctx
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_clause_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 clause_extractor.py**

```python
# src/reviewer/clause_extractor.py
"""Extract review clauses from bid analysis extracted_data."""


def _find_column(columns: list[str], *keywords: str) -> int | None:
    """Find column index by keyword match."""
    for i, col in enumerate(columns):
        for kw in keywords:
            if kw in col:
                return i
    return None


def _extract_module_clauses(
    modules: dict, module_key: str, severity: str,
    text_cols: tuple[str, ...] = ("风险项", "条件", "要求", "内容"),
    basis_cols: tuple[str, ...] = ("原文依据", "依据", "说明"),
) -> list[dict]:
    """Extract clauses from a module's sections."""
    clauses = []
    module = modules.get(module_key, {})
    if not module:
        return clauses

    for section in module.get("sections", []):
        columns = section.get("columns", [])
        text_idx = None
        for col_name in text_cols:
            text_idx = _find_column(columns, col_name)
            if text_idx is not None:
                break
        basis_idx = None
        for col_name in basis_cols:
            basis_idx = _find_column(columns, col_name)
            if basis_idx is not None:
                break

        for i, row in enumerate(section.get("rows", [])):
            clause_text = row[text_idx] if text_idx is not None and text_idx < len(row) else ""
            basis_text = row[basis_idx] if basis_idx is not None and basis_idx < len(row) else ""
            if not clause_text:
                continue
            clauses.append({
                "source_module": module_key,
                "clause_index": i,
                "clause_text": clause_text,
                "basis_text": basis_text,
                "severity": severity,
            })
    return clauses


def extract_review_clauses(extracted_data: dict) -> list[dict]:
    """Extract all review clauses from extracted_data, ordered by priority."""
    modules = extracted_data.get("modules", {})
    clauses = []
    # P0: 废标条款
    clauses.extend(_extract_module_clauses(modules, "module_e", "critical"))
    # P1: 资格条件 + 编制要求
    clauses.extend(_extract_module_clauses(modules, "module_b", "major"))
    clauses.extend(_extract_module_clauses(modules, "module_f", "major"))
    # P2: 技术评分
    clauses.extend(_extract_module_clauses(modules, "module_c", "minor"))
    return clauses


def extract_project_context(extracted_data: dict) -> str:
    """Extract project context from module_a for use in review prompts."""
    modules = extracted_data.get("modules", {})
    module_a = modules.get("module_a", {})
    if not module_a:
        return ""

    lines = []
    for section in module_a.get("sections", []):
        rows = section.get("rows", [])
        for row in rows:
            if len(row) >= 2:
                lines.append(f"{row[0]}: {row[1]}")
            elif len(row) == 1:
                lines.append(row[0])
    return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_clause_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/clause_extractor.py src/reviewer/tests/test_clause_extractor.py
git commit -m "feat(reviewer): add clause extractor from extracted_data"
```

---

### Task 6b: 信息脱敏模块

**Files:**
- Create: `src/reviewer/desensitizer.py`
- Test: `src/reviewer/tests/test_desensitizer.py`

- [ ] **Step 1: 编写脱敏器测试**

```python
# src/reviewer/tests/test_desensitizer.py
"""Tests for PII desensitization in tender documents."""
from src.models import Paragraph
from src.reviewer.desensitizer import desensitize_paragraphs


def _make_paras(texts: list[str]) -> list[Paragraph]:
    return [Paragraph(index=i, text=t, style=None) for i, t in enumerate(texts)]


def test_phone_number_masked():
    """Mobile phone numbers are replaced with numbered placeholders."""
    paras = _make_paras(["联系人电话：13812345678，备用：13987654321"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[电话_1]" in result[0].text
    assert "[电话_2]" in result[0].text
    assert "13812345678" not in result[0].text
    assert mapping["[电话_1]"] == "13812345678"
    assert mapping["[电话_2]"] == "13987654321"


def test_id_card_masked():
    """18-digit ID card numbers with valid dates are masked."""
    paras = _make_paras(["身份证号：110101199003074518"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[身份证_1]" in result[0].text
    assert "110101199003074518" not in result[0].text


def test_id_card_with_x_suffix():
    """ID cards ending with X are masked."""
    paras = _make_paras(["身份证：32010619880215371X"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[身份证_1]" in result[0].text
    assert "32010619880215371X" not in result[0].text


def test_id_card_invalid_date_not_masked():
    """18-digit numbers with invalid dates are NOT matched as ID cards."""
    # Month 13 is invalid
    paras = _make_paras(["编号：110101199013074518"])
    result, _ = desensitize_paragraphs(paras)
    # Should not be masked as ID card (invalid month 13)
    assert "[身份证_1]" not in result[0].text


def test_email_masked():
    """Email addresses are masked."""
    paras = _make_paras(["请发送至 zhangsan@example.com 或 lisi@company.cn"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[邮箱_1]" in result[0].text
    assert "[邮箱_2]" in result[0].text
    assert "zhangsan@example.com" not in result[0].text


def test_bank_account_masked():
    """16-19 digit bank account numbers are masked."""
    paras = _make_paras(["开户账号：6222021234567890123"])
    result, mapping = desensitize_paragraphs(paras)
    assert "[银行账号_1]" in result[0].text
    assert "6222021234567890123" not in result[0].text


def test_name_in_context_masked():
    """Names following context keywords (联系人、项目经理 etc.) are masked."""
    paras = _make_paras([
        "项目经理：张三",
        "联系人：李四  电话：13800001111",
        "法定代表人：王五",
    ])
    result, mapping = desensitize_paragraphs(paras)
    assert "张三" not in result[0].text
    assert "[姓名_1]" in result[0].text
    assert "李四" not in result[1].text
    assert "[姓名_2]" in result[1].text
    assert "王五" not in result[2].text


def test_table_data_desensitized():
    """PII in table cells is also desensitized."""
    para = Paragraph(
        index=0, text="联系方式", style=None,
        is_table=True,
        table_data=[
            ["联系人", "张三"],
            ["电话", "13812345678"],
            ["邮箱", "zs@test.com"],
        ],
    )
    result, mapping = desensitize_paragraphs([para])
    flat = str(result[0].table_data)
    assert "张三" not in flat
    assert "13812345678" not in flat
    assert "zs@test.com" not in flat


def test_table_keyword_as_substring():
    """Cross-cell name detection works when keyword is a substring of cell text."""
    para = Paragraph(
        index=0, text="人员信息", style=None,
        is_table=True,
        table_data=[
            ["项目联系人", "赵六"],
            ["职务", "经理"],
        ],
    )
    result, mapping = desensitize_paragraphs([para])
    flat = str(result[0].table_data)
    assert "赵六" not in flat
    assert "[姓名_1]" in flat


def test_no_pii_unchanged():
    """Text without PII is not modified."""
    paras = _make_paras(["投标文件须双面打印并装订成册", "技术方案不少于30页"])
    result, mapping = desensitize_paragraphs(paras)
    assert result[0].text == "投标文件须双面打印并装订成册"
    assert result[1].text == "技术方案不少于30页"
    assert len(mapping) == 0


def test_same_value_gets_same_placeholder():
    """Identical PII values reuse the same placeholder."""
    paras = _make_paras(["电话13812345678", "再次确认13812345678"])
    result, mapping = desensitize_paragraphs(paras)
    assert result[0].text.count("[电话_1]") == 1
    assert result[1].text.count("[电话_1]") == 1
    assert len([k for k in mapping if k.startswith("[电话_")]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_desensitizer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 desensitizer.py**

```python
# src/reviewer/desensitizer.py
"""PII desensitization for tender documents.

Detects and masks personal information (phone numbers, ID cards, emails,
bank accounts, names in context) before LLM review to protect privacy.
"""
import re
from dataclasses import replace
from src.models import Paragraph


# ── Regex patterns ──────────────────────────────────────────────────
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# ID card: region(6) + birth(8: YYYYMMDD) + seq(3) + check(1)
_ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")

# Context-based name detection: keyword + delimiter + 2-4 Chinese chars
_NAME_CONTEXT_RE = re.compile(
    r"(?:联系人|项目经理|项目负责人|法定代表人|授权代表|负责人|经办人|签字人|投标人代表)"
    r"[：:\s]*"
    r"([\u4e00-\u9fff]{2,4})"
)

# Ordered by specificity: ID card before bank account (18 digits vs 16-19)
_PATTERNS = [
    ("身份证", _ID_CARD_RE),
    ("电话", _PHONE_RE),
    ("邮箱", _EMAIL_RE),
    ("银行账号", _BANK_RE),
]


class _PlaceholderRegistry:
    """Tracks PII values → placeholders, deduplicating identical values."""

    def __init__(self):
        self._value_to_placeholder: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self.mapping: dict[str, str] = {}  # placeholder → original

    def get_placeholder(self, category: str, value: str) -> str:
        if value in self._value_to_placeholder:
            return self._value_to_placeholder[value]
        count = self._counters.get(category, 0) + 1
        self._counters[category] = count
        placeholder = f"[{category}_{count}]"
        self._value_to_placeholder[value] = placeholder
        self.mapping[placeholder] = value
        return placeholder


def _desensitize_text(text: str, registry: _PlaceholderRegistry) -> str:
    """Apply all PII patterns to a single text string."""
    # 1. Context-based names first (most specific)
    for m in list(_NAME_CONTEXT_RE.finditer(text)):
        name = m.group(1)
        placeholder = registry.get_placeholder("姓名", name)
        text = text.replace(name, placeholder, 1)

    # 2. Regex-based patterns
    for category, pattern in _PATTERNS:
        for m in list(pattern.finditer(text)):
            value = m.group(0)
            # Skip if value was already replaced by a prior pattern
            if value not in text:
                continue
            placeholder = registry.get_placeholder(category, value)
            text = text.replace(value, placeholder, 1)

    return text


# Keywords that indicate the *next* cell in a table row contains a name
_NAME_KEYWORDS = {"联系人", "项目经理", "项目负责人", "法定代表人", "授权代表",
                  "负责人", "经办人", "签字人", "投标人代表"}

# Standalone Chinese name pattern (2-4 chars, used only for table cells with keyword context)
_STANDALONE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")


def _desensitize_table_row(row: list[str], registry: _PlaceholderRegistry) -> list[str]:
    """Desensitize a table row with cross-cell name detection.

    In tables, keywords like "联系人" and the name "张三" are often in adjacent cells.
    First pass: detect keyword cells and mask the adjacent name cell.
    Second pass: apply standard regex patterns to each cell.
    """
    new_row = list(row)

    # Cross-cell name detection: if cell[i] contains a keyword, check cell[i+1] for a name
    for i in range(len(new_row) - 1):
        cell_text = new_row[i].strip()
        if any(kw in cell_text for kw in _NAME_KEYWORDS):
            next_cell = new_row[i + 1].strip()
            if _STANDALONE_NAME_RE.match(next_cell):
                placeholder = registry.get_placeholder("姓名", next_cell)
                new_row[i + 1] = new_row[i + 1].replace(next_cell, placeholder, 1)

    # Standard desensitization on each cell
    new_row = [_desensitize_text(cell, registry) for cell in new_row]
    return new_row


def desensitize_paragraphs(
    paragraphs: list[Paragraph],
) -> tuple[list[Paragraph], dict[str, str]]:
    """Desensitize PII in all paragraphs.

    Returns:
        - New list of Paragraph objects with PII replaced by placeholders
        - Mapping dict: {placeholder: original_value}
    """
    registry = _PlaceholderRegistry()
    result = []

    for para in paragraphs:
        new_text = _desensitize_text(para.text, registry)

        new_table_data = None
        if para.table_data:
            new_table_data = [
                _desensitize_table_row(row, registry)
                for row in para.table_data
            ]

        result.append(replace(para, text=new_text, table_data=new_table_data))

    return result, registry.mapping
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_desensitizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/desensitizer.py src/reviewer/tests/test_desensitizer.py
git commit -m "feat(reviewer): add PII desensitizer for tender documents"
```

---

### Task 6c: 图片提取模块

**Files:**
- Create: `src/reviewer/image_extractor.py`
- Test: `src/reviewer/tests/test_image_extractor.py`

- [ ] **Step 1: 编写图片提取测试**

```python
# src/reviewer/tests/test_image_extractor.py
"""Tests for image extraction from docx/PDF files."""
import os
import tempfile
import pytest
from docx import Document
from docx.shared import Inches

from src.reviewer.image_extractor import extract_images


@pytest.fixture
def docx_with_image(tmp_path):
    """Create a docx file with an embedded image for testing."""
    doc = Document()
    doc.add_paragraph("第一章 投标函")
    # Create a minimal 1x1 PNG for testing
    import struct, zlib
    def make_png():
        """Generate a minimal 1x1 red PNG."""
        raw = b"\x00\xff\x00\x00"  # filter + RGB
        compressed = zlib.compress(raw)
        def chunk(ctype, data):
            c = ctype + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", compressed)
            + chunk(b"IEND", b"")
        )
    png_path = tmp_path / "test.png"
    png_path.write_bytes(make_png())
    doc.add_picture(str(png_path), width=Inches(2))
    doc.add_paragraph("资质证书如上图所示")
    doc.add_paragraph("第二章 技术方案")
    docx_path = tmp_path / "test_with_image.docx"
    doc.save(str(docx_path))
    return str(docx_path)


def test_extract_images_from_docx(docx_with_image, tmp_path):
    """Images are extracted from docx and saved to output dir."""
    output_dir = str(tmp_path / "images")
    images = extract_images(docx_with_image, output_dir)
    assert len(images) >= 1
    assert images[0]["filename"].endswith(".png") or images[0]["filename"].endswith(".jpeg")
    assert os.path.exists(images[0]["path"])
    # Image-only paragraph is deferred to next text paragraph "资质证书如上图所示"
    # which is index 1 (after "第一章 投标函" at index 0, skipping the empty image paragraph)
    assert images[0]["near_para_index"] == 1


def test_extract_images_no_images(tmp_path):
    """Docx without images returns empty list."""
    doc = Document()
    doc.add_paragraph("纯文本段落")
    docx_path = str(tmp_path / "no_image.docx")
    doc.save(docx_path)
    output_dir = str(tmp_path / "images")
    images = extract_images(docx_path, output_dir)
    assert images == []


def test_extract_images_from_pdf(tmp_path):
    """PDF image extraction returns a list (may be empty without pymupdf)."""
    # This is a graceful-degradation test: if pymupdf is not installed,
    # the function should return [] without raising.
    pdf_path = str(tmp_path / "test.pdf")
    # Create a minimal PDF (no images)
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
                b"xref\n0 4\n0000000000 65535 f \n"
                b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
                b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF")
    output_dir = str(tmp_path / "images")
    images = extract_images(pdf_path, output_dir)
    assert isinstance(images, list)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_image_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 image_extractor.py**

```python
# src/reviewer/image_extractor.py
"""Extract embedded images from docx and PDF files.

Returns metadata about each image: filename, saved path, and approximate
paragraph position for cross-referencing in the preview UI.
"""
import os
import logging
from zipfile import ZipFile

logger = logging.getLogger(__name__)

_MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".tif": "image/tiff",
}


def extract_images(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from a document file.

    Args:
        file_path: Path to the docx or PDF file.
        output_dir: Directory to save extracted images.

    Returns:
        List of dicts: [{filename, path, near_para_index, content_type}]
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return _extract_from_docx(file_path, output_dir)
    elif ext == ".pdf":
        return _extract_from_pdf(file_path, output_dir)
    return []


def _extract_from_docx(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from docx by reading the media/ directory in the zip.

    Also parses document.xml.rels to map images to paragraph positions.
    """
    os.makedirs(output_dir, exist_ok=True)
    images = []

    try:
        with ZipFile(file_path, "r") as zf:
            media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
            if not media_files:
                return []

            # Build rId → media filename mapping from rels
            rid_to_media = {}
            rels_path = "word/_rels/document.xml.rels"
            if rels_path in zf.namelist():
                from lxml import etree
                rels_xml = etree.fromstring(zf.read(rels_path))
                for rel in rels_xml:
                    target = rel.get("Target", "")
                    rid = rel.get("Id", "")
                    if "media/" in target:
                        rid_to_media[rid] = target.split("/")[-1]

            # Find paragraph positions of images via document.xml
            para_image_map = {}  # media_filename → para_index
            if "word/document.xml" in zf.namelist():
                from lxml import etree
                doc_xml = etree.fromstring(zf.read("word/document.xml"))
                ns = {
                    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
                    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
                }
                # Iterate only body-level children (matching parse_docx behavior)
                # parse_docx skips empty paragraphs (no run text) — they get no index.
                # For image-only paragraphs (no text but has image), we associate the
                # image with the NEXT text paragraph's index (para_idx), so the image
                # displays next to the first paragraph after it.
                body = doc_xml.find(f"{{{ns['w']}}}body")
                w_p = f"{{{ns['w']}}}p"
                w_tbl = f"{{{ns['w']}}}tbl"
                w_r = f"{{{ns['w']}}}r"
                w_t = f"{{{ns['w']}}}t"
                para_idx = 0
                pending_images = []  # images from text-empty paragraphs
                if body is not None:
                    for child in body:
                        if child.tag == w_p:
                            # Check text content (matching parse_docx lines 28-34)
                            runs_text = []
                            for r in child.findall(w_r):
                                t = r.find(w_t)
                                if t is not None and t.text:
                                    runs_text.append(t.text)
                            has_text = bool("".join(runs_text).strip())

                            # Check if this paragraph contains an image
                            blip_elems = child.findall(".//a:blip", ns)
                            found_images = []
                            for blip in blip_elems:
                                embed = blip.get(f"{{{ns['r']}}}embed")
                                if embed and embed in rid_to_media:
                                    found_images.append(rid_to_media[embed])

                            if has_text:
                                # Flush pending images from previous empty paragraphs
                                for media_fn in pending_images:
                                    para_image_map[media_fn] = para_idx
                                pending_images.clear()
                                # Assign current paragraph's images
                                for media_fn in found_images:
                                    para_image_map[media_fn] = para_idx
                                para_idx += 1
                            else:
                                # Image-only paragraph: defer to next text paragraph
                                pending_images.extend(found_images)
                        elif child.tag == w_tbl:
                            # Flush pending images into this table's index
                            for media_fn in pending_images:
                                para_image_map[media_fn] = para_idx
                            pending_images.clear()
                            # Table images
                            blip_elems = child.findall(".//a:blip", ns)
                            for blip in blip_elems:
                                embed = blip.get(f"{{{ns['r']}}}embed")
                                if embed and embed in rid_to_media:
                                    para_image_map[rid_to_media[embed]] = para_idx
                            para_idx += 1
                    # Handle trailing pending images (assign to last index)
                    if pending_images and para_idx > 0:
                        for media_fn in pending_images:
                            para_image_map[media_fn] = para_idx - 1

            # Extract each media file
            for media_path in media_files:
                filename = os.path.basename(media_path)
                # Skip non-image files (e.g., .emf, .wmf are usually decorative)
                ext_lower = os.path.splitext(filename)[1].lower()
                if ext_lower not in _MIME_TYPES:
                    continue

                out_path = os.path.join(output_dir, filename)
                with open(out_path, "wb") as f:
                    f.write(zf.read(media_path))

                content_type = _MIME_TYPES[ext_lower]

                images.append({
                    "filename": filename,
                    "path": out_path,
                    "near_para_index": para_image_map.get(filename),
                    "content_type": content_type,
                })

    except Exception as e:
        logger.warning("Failed to extract images from docx: %s", e)

    return images


def _extract_from_pdf(file_path: str, output_dir: str) -> list[dict]:
    """Extract images from PDF using pymupdf (fitz) if available."""
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.info("pymupdf not installed, skipping PDF image extraction")
        return []

    os.makedirs(output_dir, exist_ok=True)
    images = []

    try:
        doc = fitz.open(file_path)
        img_index = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    ext = base_image["ext"]
                    dot_ext = f".{ext}"
                    if dot_ext not in _MIME_TYPES:
                        continue
                    filename = f"page{page_num+1}_img{img_index}.{ext}"
                    out_path = os.path.join(output_dir, filename)
                    with open(out_path, "wb") as f:
                        f.write(base_image["image"])
                    content_type = _MIME_TYPES[dot_ext]
                    images.append({
                        "filename": filename,
                        "path": out_path,
                        "near_para_index": None,  # PDF images lack precise paragraph mapping
                        "content_type": content_type,
                        "page": page_num + 1,
                    })
                    img_index += 1
                except Exception:
                    continue
        doc.close()
    except Exception as e:
        logger.warning("Failed to extract images from PDF: %s", e)

    return images
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_image_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/image_extractor.py src/reviewer/tests/test_image_extractor.py
git commit -m "feat(reviewer): add image extraction from docx/PDF for review"
```

---

## Chunk 3: LLM 审查核对模块

### Task 7: 条款-章节映射器 + LLM 核对器

**Files:**
- Modify: `src/extractor/base.py` (parse_llm_json 增加 JSON 数组支持)
- Create: `src/reviewer/clause_mapper.py`
- Create: `src/reviewer/reviewer.py`
- Create: `config/prompts/review_toc.txt`
- Create: `config/prompts/review_mapping.txt`
- Create: `config/prompts/review_clause.txt`
- Create: `config/prompts/review_batch.txt`
- Test: `src/reviewer/tests/test_reviewer.py`

- [ ] **Step 0: 修改 `src/extractor/base.py` 的 `parse_llm_json` 增加 JSON 数组支持**

`call_qwen` 返回 `dict | None`，但 `llm_map_clauses_to_chapters` 和 `llm_review_batch` 期望 LLM 返回 JSON 数组。`parse_llm_json` 的 fallback 只查找 `{...}`，不支持 `[...]`。需要增加数组支持：

```python
# src/extractor/base.py — 在 parse_llm_json 函数的 "{" fallback 之后添加 "[" fallback
# 在现有的 first_brace / last_brace 逻辑之后添加：
first_bracket = text.find("[")
last_bracket = text.rfind("]")
if first_bracket != -1 and last_bracket > first_bracket:
    try:
        return json.loads(text[first_bracket : last_bracket + 1])
    except json.JSONDecodeError:
        pass
```

同时更新 `call_qwen` 的返回类型注解为 `dict | list | None`。

- [ ] **Step 1: 创建 prompt 模板文件**

```text
# config/prompts/review_toc.txt
你是文档结构分析专家。请分析以下投标文件片段，提取所有章节标题及其层级。
返回 JSON 格式：{"chapters": [{"title": "章节标题", "level": 1, "first_sentence": "该章节第一句话"}]}
注意：
1. 只提取章节结构，不需要总结内容
2. level 1 为最高层级（如"第一章"），level 2 为子章节（如"1.1"）
3. first_sentence 是该章节正文的第一句话，用于后续定位
```

```text
# config/prompts/review_mapping.txt
你是招标审查专家。请将以下审查条款映射到投标文件的章节。

## 审查条款
{clauses}

## 投标文件目录
{chapters}

请返回 JSON 格式：
[{{"clause_index": 0, "relevant_chapters": ["章节标题1", "章节标题2"]}}]

每个条款可以映射到 1-3 个最相关的章节。如果无法确定，返回空数组。
```

```text
# config/prompts/review_clause.txt
你是招标文件审查专家。请审查投标文件是否符合以下招标要求。

## 隐私保护规则（必须遵守）
投标文件中的个人隐私数据已被脱敏处理，以 [姓名_N]、[电话_N]、[身份证_N]、[邮箱_N]、[银行账号_N] 等占位符表示。
- 你的回复中**禁止**填充、还原、猜测任何脱敏占位符的真实内容
- 引用原文时保持占位符原样输出
- 如果条款审查涉及人员资质或联系方式，只需判断"是否提供了相关信息"，无需关注具体内容
- 包含图片的位置以 [图片: filename] 标记，存在该标记即视为已提供扫描件/证书

## 项目背景
{project_context}

## 审查条款
条款内容：{clause_text}
原文依据：{basis_text}
严重程度：{severity}

## 投标文件相关内容
{tender_text}

请判断投标文件是否符合该条款要求，返回 JSON 格式：
{{
  "result": "pass" 或 "fail" 或 "warning",
  "confidence": 0-100 的整数,
  "reason": "具体判断依据和说明",
  "locations": [{{"para_index": 段落编号, "text_snippet": "相关原文片段"}}]
}}

判断标准：
- pass: 投标文件明确符合该条款要求
- fail: 投标文件明确不符合或缺失相关内容
- warning: 投标文件部分符合或表述模糊，需人工确认
- confidence 反映你对判断结果的确信程度
```

```text
# config/prompts/review_batch.txt
你是招标文件审查专家。请批量审查投标文件是否符合以下多条招标要求。

## 隐私保护规则（必须遵守）
投标文件中的个人隐私数据已被脱敏处理，以 [姓名_N]、[电话_N]、[身份证_N]、[邮箱_N]、[银行账号_N] 等占位符表示。
- 你的回复中**禁止**填充、还原、猜测任何脱敏占位符的真实内容
- 引用原文时保持占位符原样输出
- 如果条款审查涉及人员资质或联系方式，只需判断"是否提供了相关信息"，无需关注具体内容
- 包含图片的位置以 [图片: filename] 标记，存在该标记即视为已提供扫描件/证书

## 项目背景
{project_context}

## 审查条款列表
{clauses_json}

## 投标文件相关内容
{tender_text}

请逐条审查，返回 JSON 数组：
[
  {{
    "clause_index": 条款编号,
    "result": "pass" 或 "fail" 或 "warning",
    "confidence": 0-100,
    "reason": "判断依据",
    "locations": [{{"para_index": 段落编号, "text_snippet": "原文片段"}}]
  }}
]
```

- [ ] **Step 2: 实现 clause_mapper.py**

```python
# src/reviewer/clause_mapper.py
"""Map review clauses to tender document chapters via LLM."""
import logging
from pathlib import Path

from src.extractor.base import call_qwen, build_messages

logger = logging.getLogger(__name__)

_MAPPING_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_mapping.txt"
_TOC_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_toc.txt"


def llm_extract_toc(paragraphs, api_settings: dict | None = None) -> list[dict]:
    """Use LLM to extract TOC when document TOC is not detected."""
    system_prompt = _TOC_PROMPT_PATH.read_text(encoding="utf-8")
    # Build text in batches of ~30k tokens
    all_chapters = []
    text_lines = [f"[{p.index}] {p.text}" for p in paragraphs]
    full_text = "\n".join(text_lines)

    # Simple batching by character count (~30k tokens ≈ 50k chars for Chinese)
    batch_size = 50000
    for start in range(0, len(full_text), batch_size):
        batch_text = full_text[start:start + batch_size]
        messages = build_messages(system=system_prompt, user=batch_text)
        result = call_qwen(messages, api_settings)
        if result and "chapters" in result:
            all_chapters.extend(result["chapters"])

    # Deduplicate by title
    seen = set()
    unique = []
    for ch in all_chapters:
        title = ch.get("title", "")
        if title not in seen:
            seen.add(title)
            unique.append(ch)

    return unique


def llm_map_clauses_to_chapters(
    clauses: list[dict], tender_index: dict, api_settings: dict | None = None
) -> dict[int, list[str]]:
    """Map clause indices to relevant chapter titles via LLM.

    Returns: {clause_index: [chapter_title, ...]}
    """
    chapter_titles = [ch["title"] for ch in tender_index.get("chapters", [])]
    for ch in tender_index.get("chapters", []):
        for child in ch.get("children", []):
            chapter_titles.append(child["title"])

    clauses_text = "\n".join(
        f"[{c['clause_index']}] [{c['severity']}] {c['clause_text']}"
        for c in clauses
    )
    chapters_text = "\n".join(f"- {t}" for t in chapter_titles)

    prompt_template = _MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{clauses}", clauses_text).replace("{chapters}", chapters_text)

    messages = build_messages(system="你是招标审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    mapping = {}
    if isinstance(result, list):
        for item in result:
            idx = item.get("clause_index")
            chapters = item.get("relevant_chapters", [])
            if idx is not None:
                mapping[idx] = chapters
    elif isinstance(result, dict) and "mappings" in result:
        for item in result["mappings"]:
            idx = item.get("clause_index")
            chapters = item.get("relevant_chapters", [])
            if idx is not None:
                mapping[idx] = chapters

    return mapping
```

- [ ] **Step 3: 实现 reviewer.py**

```python
# src/reviewer/reviewer.py
"""LLM-based clause review: single and batch modes."""
import json
import logging
from pathlib import Path

from src.extractor.base import call_qwen, build_messages

logger = logging.getLogger(__name__)

_CLAUSE_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_clause.txt"
_BATCH_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompts" / "review_batch.txt"


def llm_review_clause(
    clause: dict,
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> dict:
    """Review a single clause against tender text. Returns review item dict."""
    prompt_template = _CLAUSE_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clause_text}", clause.get("clause_text", ""))
        .replace("{basis_text}", clause.get("basis_text", ""))
        .replace("{severity}", clause.get("severity", ""))
        .replace("{tender_text}", tender_text)
    )

    messages = build_messages(system="你是招标文件审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not result:
        return _error_item(clause)

    # Normalize locations format
    locations = result.get("locations", [])
    normalized_locations = []
    for loc in locations:
        if isinstance(loc, dict):
            normalized_locations.append({
                "para_index": loc.get("para_index"),
                "text_snippet": loc.get("text_snippet", ""),
            })

    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": result.get("result", "error"),
        "confidence": int(result.get("confidence", 0)),
        "reason": result.get("reason", ""),
        "severity": clause["severity"],
        "tender_locations": _build_tender_locations(normalized_locations, clause),
    }


def llm_review_batch(
    clauses: list[dict],
    tender_text: str,
    project_context: str,
    api_settings: dict | None = None,
) -> list[dict]:
    """Review multiple clauses in one LLM call. Returns list of review items."""
    prompt_template = _BATCH_PROMPT_PATH.read_text(encoding="utf-8")
    clauses_json = json.dumps(
        [{"clause_index": c["clause_index"], "clause_text": c["clause_text"],
          "basis_text": c.get("basis_text", ""), "severity": c["severity"]}
         for c in clauses],
        ensure_ascii=False, indent=2,
    )
    prompt = (
        prompt_template
        .replace("{project_context}", project_context)
        .replace("{clauses_json}", clauses_json)
        .replace("{tender_text}", tender_text)
    )

    messages = build_messages(system="你是招标文件审查专家。", user=prompt)
    result = call_qwen(messages, api_settings)

    if not isinstance(result, list):
        # Fallback: mark all as error
        return [_error_item(c) for c in clauses]

    # Map results by clause_index
    result_map = {r.get("clause_index"): r for r in result if isinstance(r, dict)}
    items = []
    for clause in clauses:
        r = result_map.get(clause["clause_index"])
        if r:
            # Normalize locations (same validation as single-clause path)
            raw_locations = r.get("locations", [])
            locations = [
                {"para_index": loc.get("para_index"), "text_snippet": loc.get("text_snippet", "")}
                for loc in raw_locations if isinstance(loc, dict)
            ]
            items.append({
                "source_module": clause["source_module"],
                "clause_index": clause["clause_index"],
                "clause_text": clause["clause_text"],
                "result": r.get("result", "error"),
                "confidence": int(r.get("confidence", 0)),
                "reason": r.get("reason", ""),
                "severity": clause["severity"],
                "tender_locations": _build_tender_locations(locations, clause),
            })
        else:
            items.append(_error_item(clause))
    return items


def _error_item(clause: dict) -> dict:
    return {
        "source_module": clause["source_module"],
        "clause_index": clause["clause_index"],
        "clause_text": clause["clause_text"],
        "result": "error",
        "confidence": 0,
        "reason": "LLM 调用失败",
        "severity": clause["severity"],
        "tender_locations": [],
    }


def _build_tender_locations(locations: list[dict], clause: dict) -> list[dict]:
    """Build tender_locations from LLM response locations."""
    if not locations:
        return []
    return [{
        "chapter": "",
        "para_indices": [loc["para_index"] for loc in locations if loc.get("para_index") is not None],
        "text_snippet": locations[0].get("text_snippet", "") if locations else "",
    }]


def compute_summary(review_items: list[dict]) -> dict:
    """Compute review summary statistics."""
    total = len(review_items)
    pass_count = sum(1 for r in review_items if r["result"] == "pass")
    fail_count = sum(1 for r in review_items if r["result"] == "fail")
    warning_count = sum(1 for r in review_items if r["result"] == "warning")
    error_count = sum(1 for r in review_items if r["result"] == "error")
    critical_fails = sum(1 for r in review_items if r["result"] == "fail" and r["severity"] == "critical")
    confidences = [r["confidence"] for r in review_items if r["confidence"] > 0]
    avg_confidence = round(sum(confidences) / len(confidences) / 100, 2) if confidences else 0

    by_severity = {}
    for sev in ("critical", "major", "minor"):
        items = [r for r in review_items if r["severity"] == sev]
        by_severity[sev] = {
            "total": len(items),
            "pass": sum(1 for r in items if r["result"] == "pass"),
            "fail": sum(1 for r in items if r["result"] == "fail"),
            "warning": sum(1 for r in items if r["result"] == "warning"),
        }

    return {
        "total": total,
        "pass": pass_count,
        "fail": fail_count,
        "warning": warning_count,
        "error": error_count,
        "critical_fails": critical_fails,
        "avg_confidence": avg_confidence,
        "by_severity": by_severity,
    }
```

- [ ] **Step 4: 编写核对器测试**

```python
# src/reviewer/tests/test_reviewer.py
"""Tests for reviewer compute_summary."""
from src.reviewer.reviewer import compute_summary


def test_compute_summary():
    items = [
        {"result": "pass", "confidence": 90, "severity": "critical"},
        {"result": "fail", "confidence": 85, "severity": "critical"},
        {"result": "warning", "confidence": 60, "severity": "major"},
        {"result": "pass", "confidence": 95, "severity": "minor"},
    ]
    summary = compute_summary(items)
    assert summary["total"] == 4
    assert summary["pass"] == 2
    assert summary["fail"] == 1
    assert summary["warning"] == 1
    assert summary["critical_fails"] == 1
    assert summary["by_severity"]["critical"]["total"] == 2
    assert summary["by_severity"]["major"]["warning"] == 1
    # avg_confidence is 0-1 scale: (90+85+60+95)/4/100 = 0.83
    assert summary["avg_confidence"] == 0.83
```

- [ ] **Step 5: 运行测试**

Run: `python -m pytest src/reviewer/tests/test_reviewer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/extractor/base.py src/reviewer/clause_mapper.py src/reviewer/reviewer.py \
  src/reviewer/tests/test_reviewer.py \
  config/prompts/review_toc.txt config/prompts/review_mapping.txt \
  config/prompts/review_clause.txt config/prompts/review_batch.txt
git commit -m "feat(reviewer): add LLM clause mapper, reviewer, prompt templates, and JSON array parsing"
```

---

## Chunk 4: docx 批注生成器 + Celery 任务

### Task 8: docx 批注生成器

**Files:**
- Create: `src/reviewer/docx_annotator.py`
- Test: `src/reviewer/tests/test_docx_annotator.py`

- [ ] **Step 1: 编写 docx 批注测试**

```python
# src/reviewer/tests/test_docx_annotator.py
"""Tests for docx annotation generator."""
import os
import tempfile
from docx import Document
from src.reviewer.docx_annotator import generate_review_docx


def _create_test_docx(path: str):
    """Create a minimal test docx file."""
    doc = Document()
    doc.add_paragraph("第一章 投标函")
    doc.add_paragraph("致采购人：我方承诺按照招标文件要求提交投标文件。")
    doc.add_paragraph("第二章 技术方案")
    doc.add_paragraph("本系统采用分布式架构，具有高可用性。")
    doc.save(path)


def test_generate_review_docx_creates_file():
    """generate_review_docx produces a valid docx file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "投标文件.docx")
        _create_test_docx(tender_path)

        review_items = [
            {
                "id": 0,
                "clause_index": 0,
                "source_module": "module_e",
                "clause_text": "投标文件须密封",
                "result": "fail",
                "confidence": 92,
                "reason": "未找到密封说明",
                "severity": "critical",
                "tender_locations": [{"chapter": "", "para_indices": [1], "text_snippet": ""}],
            }
        ]
        summary = {"total": 1, "pass": 0, "fail": 1, "warning": 0, "critical_fails": 1}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="招标文件.docx",
            output_dir=tmpdir,
        )

        assert os.path.exists(output_path)
        assert output_path.endswith(".docx")
        # Verify it's a valid docx
        doc = Document(output_path)
        assert len(doc.paragraphs) > 0


def test_generate_review_docx_has_summary_table():
    """Generated docx includes a summary table at the beginning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "test.docx")
        _create_test_docx(tender_path)

        review_items = [{
            "id": 0, "clause_index": 0, "source_module": "module_e", "clause_text": "条款1",
            "result": "pass", "confidence": 90, "reason": "符合要求",
            "severity": "critical", "tender_locations": [],
        }]
        summary = {"total": 1, "pass": 1, "fail": 0, "warning": 0, "critical_fails": 0}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="test.docx", output_dir=tmpdir,
        )
        doc = Document(output_path)
        # Should have at least 1 table (summary table)
        assert len(doc.tables) >= 1


def test_generate_review_docx_has_word_comments():
    """Generated docx contains Word native comments for fail/warning items."""
    from zipfile import ZipFile

    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "投标文件.docx")
        _create_test_docx(tender_path)

        review_items = [
            {
                "id": 0, "clause_index": 0, "source_module": "module_e",
                "clause_text": "投标文件须密封", "result": "fail",
                "confidence": 92, "reason": "未找到密封说明",
                "severity": "critical",
                "tender_locations": [{"chapter": "", "para_indices": [1], "text_snippet": ""}],
            }
        ]
        summary = {"total": 1, "pass": 0, "fail": 1, "warning": 0, "critical_fails": 1}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="招标文件.docx", output_dir=tmpdir,
        )
        # Verify comments.xml exists in the docx zip
        with ZipFile(output_path) as z:
            assert "word/comments.xml" in z.namelist()
            comments_xml = z.read("word/comments.xml").decode("utf-8")
            assert "未找到密封说明" in comments_xml
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/reviewer/tests/test_docx_annotator.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 docx_annotator.py**

```python
# src/reviewer/docx_annotator.py
"""Generate annotated docx with summary table + highlights + Word comments."""
import os
import datetime
from lxml import etree
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Word XML namespaces
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
COMMENTS_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"

NSMAP = {"w": W_NS, "r": R_NS}


def _result_symbol(result: str) -> str:
    return {"pass": "✓", "fail": "✗", "warning": "⚠", "error": "?"}.get(result, "?")


def _result_color(result: str) -> RGBColor:
    return {
        "pass": RGBColor(0x22, 0x8B, 0x22),
        "fail": RGBColor(0xCC, 0x00, 0x00),
        "warning": RGBColor(0xFF, 0x8C, 0x00),
    }.get(result, RGBColor(0x80, 0x80, 0x80))


def _add_summary_section(doc: Document, review_items: list[dict], summary: dict,
                         bid_filename: str, tender_filename: str):
    """Insert summary header and table at the beginning of the document."""
    # Title
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("投标文件审查报告")
    run.bold = True
    run.font.size = Pt(18)

    # Meta info
    meta = doc.add_paragraph()
    meta.add_run(f"招标项目: {bid_filename}").font.size = Pt(10)
    meta.add_run("\n")
    meta.add_run(f"投标文件: {tender_filename}").font.size = Pt(10)
    meta.add_run("\n")
    meta.add_run(f"审查时间: {datetime.date.today().isoformat()}").font.size = Pt(10)

    # Stats
    stats = doc.add_paragraph()
    stats_text = f"共{summary['total']}条 | 通过{summary['pass']} | 不合规{summary['fail']} | 警告{summary['warning']}"
    if summary.get("critical_fails", 0) > 0:
        stats_text += f" | 废标风险: {summary['critical_fails']}条"
    stats.add_run(stats_text).font.size = Pt(10)

    # Summary table
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    headers = ["序号", "条款", "结果", "置信度", "说明"]
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(9)

    for idx, item in enumerate(review_items):
        row = table.add_row()
        row.cells[0].text = str(idx + 1)
        row.cells[1].text = item.get("clause_text", "")[:50]
        row.cells[2].text = _result_symbol(item.get("result", ""))
        row.cells[3].text = f"{item.get('confidence', 0)}%"
        row.cells[4].text = item.get("reason", "")[:80]
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)

    # Separator
    doc.add_paragraph("─" * 60)
    doc.add_paragraph()


class _CommentManager:
    """Manages Word comments XML in a docx document."""

    def __init__(self, doc: Document):
        self.doc = doc
        self._comments_element = None
        self._next_id = 0
        self._setup_comments_part()

    def _setup_comments_part(self):
        """Create or get the comments XML part in the docx package."""
        # Create comments XML root
        self._comments_element = etree.Element(f"{{{W_NS}}}comments", nsmap=NSMAP)

        # Add as a part to the document
        from docx.opc.part import Part
        from docx.opc.packuri import PackURI

        comments_xml = etree.tostring(self._comments_element, xml_declaration=True, encoding="UTF-8")
        part_name = PackURI("/word/comments.xml")

        doc_part = self.doc.part
        comments_part = Part(part_name, COMMENTS_CT, comments_xml, doc_part.package)
        doc_part.relate_to(comments_part, COMMENTS_REL)
        self._comments_part = comments_part

    def add_comment(self, para_element, comment_text: str, author: str = "AI审查") -> int:
        """Add a Word comment to a paragraph. Returns comment ID."""
        comment_id = str(self._next_id)
        self._next_id += 1

        # Add comment to comments.xml
        comment_elem = etree.SubElement(self._comments_element, f"{{{W_NS}}}comment")
        comment_elem.set(f"{{{W_NS}}}id", comment_id)
        comment_elem.set(f"{{{W_NS}}}author", author)
        comment_elem.set(f"{{{W_NS}}}date", datetime.datetime.now().isoformat())

        # Comment body paragraph
        cp = etree.SubElement(comment_elem, f"{{{W_NS}}}p")
        cr = etree.SubElement(cp, f"{{{W_NS}}}r")
        ct = etree.SubElement(cr, f"{{{W_NS}}}t")
        ct.text = comment_text

        # Insert commentRangeStart at beginning of paragraph
        range_start = etree.Element(f"{{{W_NS}}}commentRangeStart")
        range_start.set(f"{{{W_NS}}}id", comment_id)
        para_element.insert(0, range_start)

        # Insert commentRangeEnd + commentReference at end
        range_end = etree.SubElement(para_element, f"{{{W_NS}}}commentRangeEnd")
        range_end.set(f"{{{W_NS}}}id", comment_id)

        ref_run = etree.SubElement(para_element, f"{{{W_NS}}}r")
        ref_rpr = etree.SubElement(ref_run, f"{{{W_NS}}}rPr")
        ref_style = etree.SubElement(ref_rpr, f"{{{W_NS}}}rStyle")
        ref_style.set(f"{{{W_NS}}}val", "CommentReference")
        comment_ref = etree.SubElement(ref_run, f"{{{W_NS}}}commentReference")
        comment_ref.set(f"{{{W_NS}}}id", comment_id)

        # Update the comments part content
        self._comments_part._blob = etree.tostring(
            self._comments_element, xml_declaration=True, encoding="UTF-8"
        )

        return int(comment_id)


def _highlight_paragraph(para, color: str = "yellow"):
    """Add highlight to all runs in a paragraph."""
    from docx.oxml.ns import qn
    for run in para.findall(qn("w:r")):
        rpr = run.find(qn("w:rPr"))
        if rpr is None:
            rpr = etree.SubElement(run, qn("w:rPr"))
            run.insert(0, rpr)
        highlight = rpr.find(qn("w:highlight"))
        if highlight is None:
            highlight = etree.SubElement(rpr, qn("w:highlight"))
        highlight.set(qn("w:val"), color)


def generate_review_docx(
    tender_file_path: str,
    review_items: list[dict],
    summary: dict,
    bid_filename: str = "",
    output_dir: str | None = None,
) -> str:
    """Generate annotated review docx with summary table + highlights + comments.

    Returns path to the generated docx file.
    """
    # Open tender file
    doc = Document(tender_file_path)

    # Build para_index → review_items mapping
    para_review_map: dict[int, list[dict]] = {}
    for item in review_items:
        if item["result"] in ("fail", "warning"):
            for loc in item.get("tender_locations", []):
                for pi in loc.get("para_indices", []):
                    para_review_map.setdefault(pi, []).append(item)

    # Add comments
    comment_mgr = _CommentManager(doc)

    # Get all paragraph elements from body
    from docx.oxml.ns import qn
    body = doc.element.body
    para_elements = body.findall(qn("w:p"))

    para_idx = 0
    for pe in para_elements:
        if para_idx in para_review_map:
            items = para_review_map[para_idx]
            # Highlight
            highlight_color = "red" if any(i["result"] == "fail" for i in items) else "yellow"
            _highlight_paragraph(pe, highlight_color)
            # Add comment for first item
            for item in items:
                severity_label = {"critical": "废标条款", "major": "资格/编制要求", "minor": "评标标准"}.get(
                    item["severity"], "审查项"
                )
                comment_text = (
                    f"[{severity_label} #{item.get('clause_index', '')}] "
                    f"置信度: {item.get('confidence', 0)}%\n"
                    f"判定: {_result_symbol(item['result'])} {{'pass': '合规', 'fail': '不合规', 'warning': '需注意', 'error': '错误'}.get(item['result'], item['result'])}\n"
                    f"条款: {item.get('clause_text', '')}\n"
                    f"原因: {item.get('reason', '')}"
                )
                comment_mgr.add_comment(pe, comment_text)
        para_idx += 1

    # Insert summary at beginning: build in main doc, then move to front
    original_count = len(list(body))
    tender_basename = os.path.basename(tender_file_path)
    _add_summary_section(doc, review_items, summary, bid_filename, tender_basename)

    # Move newly added summary elements (appended at end) to position 0
    new_elements = list(body)[original_count:]
    for i, elem in enumerate(new_elements):
        body.remove(elem)
        body.insert(i, elem)

    # Save
    if output_dir is None:
        output_dir = os.path.dirname(tender_file_path)
    tender_basename = os.path.basename(tender_file_path)
    output_filename = f"审查报告_{tender_basename}"
    output_path = os.path.join(output_dir, output_filename)
    doc.save(output_path)
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/reviewer/tests/test_docx_annotator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/reviewer/docx_annotator.py src/reviewer/tests/test_docx_annotator.py
git commit -m "feat(reviewer): add docx annotator with Word comments + summary table"
```

---

### Task 9: run_review Celery 任务

**Files:**
- Create: `server/app/tasks/review_task.py`
- Modify: `server/app/routers/reviews.py:28-30` (dispatch task)

- [ ] **Step 1: 实现 review_task.py**

```python
# server/app/tasks/review_task.py
"""Celery task: run bid document review pipeline."""
import logging
import time
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="run_review")
def run_review(self, review_id: str):
    """Main review pipeline: parse → desensitize → extract images → index → map → review → generate docx."""
    from server.app.models.review_task import ReviewTask
    from server.app.models.task import Task
    from src.parser.unified import parse_document
    from src.reviewer.desensitizer import desensitize_paragraphs
    from src.reviewer.image_extractor import extract_images
    from src.reviewer.toc_detector import detect_toc
    from src.reviewer.tender_indexer import build_index_from_toc
    from src.reviewer.clause_extractor import extract_review_clauses, extract_project_context
    from src.reviewer.clause_mapper import llm_map_clauses_to_chapters, llm_extract_toc
    from src.reviewer.reviewer import llm_review_clause, llm_review_batch, compute_summary
    from src.reviewer.docx_annotator import generate_review_docx
    from src.config import load_settings

    api_settings = load_settings()

    with Session(_sync_engine) as db:
        review = db.get(ReviewTask, _uuid.UUID(review_id))
        if not review:
            return {"error": "Review task not found"}

        bid_task = db.get(Task, review.bid_task_id)
        if not bid_task:
            review.status = "failed"
            review.error_message = "关联的招标任务不存在"
            db.commit()
            return {"error": "Bid task not found"}

        try:
            # Ensure bid analysis is complete
            _ensure_bid_complete(bid_task, db)
            extracted_data = bid_task.extracted_data
            if not extracted_data:
                raise ValueError("招标文件尚未完成解析")

            # Step 1: Parse tender file (0-5%)
            review.status = "indexing"
            review.progress = 0
            review.current_step = "解析投标文件"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 0, "detail": "解析投标文件"})

            paragraphs = parse_document(review.tender_file_path)

            # Step 1b: Desensitize PII (2-3%)
            review.progress = 2
            review.current_step = "信息脱敏"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 2, "detail": "信息脱敏"})

            paragraphs, pii_mapping = desensitize_paragraphs(paragraphs)
            logger.info("PII desensitization: %d items masked", len(pii_mapping))

            # Step 1c: Extract images (3-5%)
            review.progress = 3
            review.current_step = "提取图片"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 3, "detail": "提取图片"})

            import os
            images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
            extracted_images = extract_images(review.tender_file_path, images_dir)
            logger.info("Extracted %d images from tender document", len(extracted_images))

            # Inject image markers into paragraphs for LLM awareness
            # Build index→list_position map (para.index may not equal list position)
            index_to_pos = {p.index: pos for pos, p in enumerate(paragraphs)}

            image_by_para = {}
            for img in extracted_images:
                pi = img.get("near_para_index")
                if pi is not None:
                    image_by_para.setdefault(pi, []).append(img["filename"])

            from dataclasses import replace as dc_replace
            for pi, filenames in image_by_para.items():
                pos = index_to_pos.get(pi)
                if pos is not None:
                    marker = " ".join(f"[图片: {fn}]" for fn in filenames)
                    paragraphs[pos] = dc_replace(
                        paragraphs[pos],
                        text=paragraphs[pos].text + f" {marker}",
                    )

            # Step 2: Build index (5-10%)
            review.progress = 5
            review.current_step = "构建索引"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "indexing", "progress": 5, "detail": "构建索引"})

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

            # Step 3: Extract clauses (10-15%)
            review.status = "reviewing"
            review.progress = 10
            review.current_step = "提取审查条款"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "reviewing", "progress": 10, "detail": "提取条款"})

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
            self.update_state(state="PROGRESS", meta={"step": "reviewing", "progress": 12, "detail": "条款映射"})
            chapter_mapping = llm_map_clauses_to_chapters(clauses, tender_index, api_settings)

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
                    "step": "reviewing", "progress": progress,
                    "detail": f"废标审查 [{i+1}/{len(p0)}]",
                })

                chapters = chapter_mapping.get(clause["clause_index"], [])
                from src.reviewer.tender_indexer import get_chapter_text
                relevant_text = get_chapter_text(paragraphs, tender_index, chapters)
                if not relevant_text:
                    # Fallback: use all text (truncated)
                    relevant_text = "\n".join(f"[{p.index}] {p.text}" for p in paragraphs[:200])

                try:
                    result = llm_review_clause(clause, relevant_text, project_context, api_settings)
                    result["id"] = item_id
                    review_items.append(result)
                except Exception as e:
                    logger.error("P0 review failed for clause %d: %s", clause["clause_index"], e)
                    review_items.append({
                        "id": item_id, "source_module": clause["source_module"],
                        "clause_index": clause["clause_index"], "clause_text": clause["clause_text"],
                        "result": "error", "confidence": 0, "reason": f"LLM 调用失败: {e}",
                        "severity": clause["severity"], "tender_locations": [],
                    })
                item_id += 1

            # Step 6: P1 batch review (60-85%)
            p1 = [c for c in clauses if c["severity"] == "major"]
            if p1:
                batch_size = 8
                for bi in range(0, len(p1), batch_size):
                    batch = p1[bi:bi + batch_size]
                    batch_progress = 60 + int(25 * bi / max(len(p1), 1))
                    review.progress = batch_progress
                    review.current_step = f"资格/编制审查 [{bi+1}-{min(bi+batch_size, len(p1))}/{len(p1)}]"
                    db.commit()
                    self.update_state(state="PROGRESS", meta={
                        "step": "reviewing", "progress": batch_progress,
                        "detail": review.current_step,
                    })

                    # Collect relevant text for all clauses in batch
                    all_chapters = set()
                    for c in batch:
                        all_chapters.update(chapter_mapping.get(c["clause_index"], []))
                    relevant_text = get_chapter_text(paragraphs, tender_index, list(all_chapters))
                    if not relevant_text:
                        relevant_text = "\n".join(f"[{p.index}] {p.text}" for p in paragraphs[:200])

                    try:
                        results = llm_review_batch(batch, relevant_text, project_context, api_settings)
                        for r in results:
                            r["id"] = item_id
                            review_items.append(r)
                            item_id += 1
                    except Exception as e:
                        logger.error("P1 batch review failed: %s", e)
                        for c in batch:
                            review_items.append({
                                "id": item_id, "source_module": c["source_module"],
                                "clause_index": c["clause_index"], "clause_text": c["clause_text"],
                                "result": "error", "confidence": 0, "reason": f"LLM 调用失败: {e}",
                                "severity": c["severity"], "tender_locations": [],
                            })
                            item_id += 1

            # Step 7: P2 batch review (85-95%)
            p2 = [c for c in clauses if c["severity"] == "minor"]
            if p2:
                batch_size = 8
                for bi in range(0, len(p2), batch_size):
                    batch = p2[bi:bi + batch_size]
                    batch_progress = 85 + int(10 * bi / max(len(p2), 1))
                    review.progress = batch_progress
                    review.current_step = f"评标审查 [{bi+1}-{min(bi+batch_size, len(p2))}/{len(p2)}]"
                    db.commit()
                    self.update_state(state="PROGRESS", meta={
                        "step": "reviewing", "progress": batch_progress,
                        "detail": review.current_step,
                    })

                    all_chapters = set()
                    for c in batch:
                        all_chapters.update(chapter_mapping.get(c["clause_index"], []))
                    relevant_text = get_chapter_text(paragraphs, tender_index, list(all_chapters))
                    if not relevant_text:
                        relevant_text = "\n".join(f"[{p.index}] {p.text}" for p in paragraphs[:200])

                    try:
                        results = llm_review_batch(batch, relevant_text, project_context, api_settings)
                        for r in results:
                            r["id"] = item_id
                            review_items.append(r)
                            item_id += 1
                    except Exception as e:
                        logger.error("P2 batch review failed: %s", e)
                        for c in batch:
                            review_items.append({
                                "id": item_id, "source_module": c["source_module"],
                                "clause_index": c["clause_index"], "clause_text": c["clause_text"],
                                "result": "error", "confidence": 0, "reason": f"LLM 调用失败: {e}",
                                "severity": c["severity"], "tender_locations": [],
                            })
                            item_id += 1

            # Step 8: Generate docx (95-100%)
            review.progress = 95
            review.current_step = "生成审查报告"
            db.commit()
            self.update_state(state="PROGRESS", meta={"step": "generating", "progress": 95, "detail": "生成报告"})

            summary = compute_summary(review_items)
            import os
            output_dir = os.path.dirname(review.tender_file_path)
            annotated_path = generate_review_docx(
                review.tender_file_path, review_items, summary,
                bid_filename=bid_task.filename, output_dir=output_dir,
            )

            # Store images metadata in summary for preview API
            summary["extracted_images"] = [
                {"filename": img["filename"], "near_para_index": img.get("near_para_index"),
                 "content_type": img.get("content_type", "")}
                for img in extracted_images
            ]
            summary["pii_masked_count"] = len(pii_mapping)

            review.review_summary = summary
            review.review_items = review_items
            review.annotated_file_path = annotated_path
            review.status = "completed"
            review.progress = 100
            review.current_step = None
            db.commit()

            return {"status": "completed", "review_id": review_id}

        except Exception as e:
            logger.error("Review task failed: %s", e, exc_info=True)
            review.status = "failed"
            review.error_message = str(e)
            db.commit()
            return {"error": str(e)}


def _ensure_bid_complete(bid_task, db: Session):
    """Ensure bid analysis is complete. Wait or trigger generation if needed.

    Handles all states: completed, failed, review, pending/parsing/indexing/extracting/generating.
    """
    if bid_task.status == "completed":
        return

    if bid_task.status == "failed":
        raise ValueError("招标文件解析失败，请重新上传")

    if bid_task.status == "review":
        # Skip review, trigger generation directly
        from server.app.tasks.generate_task import run_generate
        result = run_generate.delay(str(bid_task.id))
        bid_task.celery_task_id = result.id
        bid_task.status = "generating"
        db.commit()

    # Wait for completion (max 30 minutes)
    # Handles: pending, parsing, indexing, extracting, generating, review (after pipeline)
    max_wait = 1800
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        db.refresh(bid_task)
        if bid_task.status == "completed":
            return
        if bid_task.status == "failed":
            raise ValueError("招标文件解析失败")
        if bid_task.status == "review":
            # Pipeline finished, now trigger generation (skip human review)
            from server.app.tasks.generate_task import run_generate
            result = run_generate.delay(str(bid_task.id))
            bid_task.celery_task_id = result.id
            bid_task.status = "generating"
            db.commit()

    raise TimeoutError("等待招标文件解析超时（30分钟）")
```

- [ ] **Step 2: 在 reviews.py 路由中派发 Celery 任务**

```python
# server/app/routers/reviews.py — 修改 create_review_endpoint 函数
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    tender_file: UploadFile = File(...),
    bid_task_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_review(db, tender_file, bid_task_id, user.id)
    # Dispatch Celery task
    from server.app.tasks.review_task import run_review
    celery_result = run_review.delay(str(review.id))
    review.celery_task_id = celery_result.id
    await db.commit()
    return {"id": str(review.id), "status": review.status, "version": review.version}
```

- [ ] **Step 3: 添加 SSE 进度端点到 reviews.py**

```python
# server/app/routers/reviews.py — 在 delete_review_endpoint 之后添加

@router.get("/{review_id}/progress")
async def review_progress(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for review task progress."""
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    celery_task_id = review.celery_task_id

    async def event_generator():
        nonlocal celery_task_id
        from celery.result import AsyncResult
        import asyncio
        import json

        while True:
            if not celery_task_id:
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
                await asyncio.sleep(2)
                await db.refresh(review)
                celery_task_id = review.celery_task_id
                continue

            result = AsyncResult(celery_task_id)
            if result.state == "PROGRESS":
                meta = result.info or {}
                yield f"data: {json.dumps(meta)}\n\n"
            elif result.state == "SUCCESS":
                await db.refresh(review)
                if review.status == "completed":
                    yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                    return
                elif review.status == "failed":
                    yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': review.error_message})}\n\n"
                    return
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': str(result.info)})}\n\n"
                return

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

需要在文件顶部 import 添加 `StreamingResponse`：

```python
from fastapi.responses import FileResponse, StreamingResponse
```

- [ ] **Step 4: Commit**

```bash
git add server/app/tasks/review_task.py server/app/routers/reviews.py
git commit -m "feat(review): add run_review Celery task + SSE progress endpoint"
```

---

## Chunk 5: 前端实现

### Task 10: API 客户端 + 状态管理

**Files:**
- Create: `web/src/api/reviews.ts`
- Create: `web/src/stores/reviewStore.ts`

- [ ] **Step 1: 实现 reviews API 客户端**

```typescript
// web/src/api/reviews.ts
import client from './client'

export interface ReviewItem {
  id: number
  source_module: string
  clause_index: number
  clause_text: string
  result: 'pass' | 'fail' | 'warning' | 'error'
  confidence: number
  reason: string
  severity: 'critical' | 'major' | 'minor'
  tender_locations: Array<{
    chapter: string
    para_indices: number[]
    text_snippet: string
  }>
}

export interface ReviewSummary {
  total: number
  pass: number
  fail: number
  warning: number
  critical_fails: number
  avg_confidence: number
  by_severity?: Record<string, { total: number; pass: number; fail: number; warning: number }>
}

export interface ReviewTask {
  id: string
  bid_task_id: string
  bid_filename: string
  tender_filename: string
  version: number
  status: string
  progress: number
  review_summary: ReviewSummary | null
  review_items: ReviewItem[] | null
  created_at: string
}

export const reviewsApi = {
  create(bidTaskId: string, tenderFile: File) {
    const form = new FormData()
    form.append('bid_task_id', bidTaskId)
    form.append('tender_file', tenderFile)
    return client.post<{ id: string; status: string; version: number }>('/reviews', form)
  },
  list(page = 1, pageSize = 20, q?: string) {
    return client.get('/reviews', { params: { page, page_size: pageSize, q } })
  },
  get(id: string) {
    return client.get<ReviewTask>(`/reviews/${id}`)
  },
  delete(id: string) {
    return client.delete(`/reviews/${id}`)
  },
  preview(id: string) {
    return client.get<{ tender_html: string; review_items: ReviewItem[]; summary: ReviewSummary }>(
      `/reviews/${id}/preview`
    )
  },
  download(id: string) {
    return client.get(`/reviews/${id}/download`, { responseType: 'blob' })
  },
}
```

- [ ] **Step 2: 实现 reviewStore**

```typescript
// web/src/stores/reviewStore.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { reviewsApi } from '../api/reviews'
import type { ReviewSummary, ReviewItem } from '../api/reviews'

export type ReviewStage = 'upload' | 'processing' | 'preview'

export const useReviewStore = defineStore('review', () => {
  const stage = ref<ReviewStage>('upload')
  const selectedBidTask = ref<{ id: string; filename: string } | null>(null)
  const currentReviewId = ref<string | null>(null)
  const progress = ref(0)
  const currentStep = ref('')
  const detail = ref('')
  const reviewSummary = ref<ReviewSummary | null>(null)
  const reviewItems = ref<ReviewItem[]>([])
  const error = ref<string | null>(null)

  async function startReview(bidTaskId: string, tenderFile: File) {
    error.value = null
    try {
      const res = await reviewsApi.create(bidTaskId, tenderFile)
      currentReviewId.value = res.data.id
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建审查任务失败'
      throw e
    }
  }

  function handleProgressEvent(event: { progress: number; step: string; detail?: string; error?: string }) {
    progress.value = event.progress
    currentStep.value = event.step
    detail.value = event.detail || ''
    error.value = event.error || null

    if (event.step === 'completed') {
      stage.value = 'preview'
    } else if (event.step === 'failed') {
      error.value = event.error || '审查失败'
    }
  }

  async function loadReviewResult(reviewId?: string) {
    const id = reviewId || currentReviewId.value
    if (!id) return
    currentReviewId.value = id
    try {
      const res = await reviewsApi.get(id)
      reviewSummary.value = res.data.review_summary
      reviewItems.value = res.data.review_items || []
      if (res.data.status === 'completed') {
        stage.value = 'preview'
      }
    } catch {
      error.value = '加载审查结果失败'
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    selectedBidTask.value = null
    currentReviewId.value = null
    progress.value = 0
    currentStep.value = ''
    detail.value = ''
    reviewSummary.value = null
    reviewItems.value = []
    error.value = null
  }

  return {
    stage, selectedBidTask, currentReviewId, progress, currentStep, detail,
    reviewSummary, reviewItems, error,
    startReview, handleProgressEvent, loadReviewResult, resetToUpload,
  }
})
```

- [ ] **Step 3: Commit**

```bash
git add web/src/api/reviews.ts web/src/stores/reviewStore.ts
git commit -m "feat(frontend): add reviews API client and reviewStore"
```

---

### Task 11: 导航栏 + 路由更新

**Files:**
- Modify: `web/src/components/AppSidebar.vue:2-3,8-14`
- Modify: `web/src/router/index.ts:13-37`

- [ ] **Step 1: 更新 AppSidebar.vue**

在 import 行添加新图标：
```typescript
import { PenLine, FolderOpen, BarChart3, Ruler, ClipboardList, ShieldCheck, FileCheck } from 'lucide-vue-next'
```

更新 navItems：
```typescript
const navItems = [
  { path: '/', label: '招标解读', icon: PenLine, group: 'main' },
  { path: '/bid-review', label: '标书审查', icon: ShieldCheck, group: 'main' },
  { path: '/files/bid-documents', label: '招标文件', icon: FolderOpen, group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: BarChart3, group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: Ruler, group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: ClipboardList, group: 'files' },
  { path: '/review-results', label: '审查结果', icon: FileCheck, group: 'files' },
]
```

- [ ] **Step 2: 更新 router/index.ts**

在 SidebarLayout children 中新增路由：

```typescript
{
  path: 'bid-review',
  name: 'bid-review',
  component: () => import('../views/BidReviewView.vue'),
},
{
  path: 'review-results',
  name: 'review-results',
  component: () => import('../views/ReviewResultsView.vue'),
},
{
  path: 'review-results/:id',
  name: 'review-detail',
  component: () => import('../views/ReviewDetailView.vue'),
  props: true,
},
```

- [ ] **Step 3: Commit**

```bash
git add web/src/components/AppSidebar.vue web/src/router/index.ts
git commit -m "feat(nav): add bid review and review results to sidebar + router"
```

---

### Task 12: BidReviewView + ReviewUploadStage

**Files:**
- Create: `web/src/views/BidReviewView.vue`
- Create: `web/src/components/ReviewUploadStage.vue`

- [ ] **Step 1: 实现 ReviewUploadStage.vue**

```vue
<!-- web/src/components/ReviewUploadStage.vue -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { Search, Upload, ShieldCheck } from 'lucide-vue-next'
import client from '../api/client'
import { useReviewStore } from '../stores/reviewStore'

const reviewStore = useReviewStore()

// --- Bid task search ---
const searchQuery = ref('')
const searchResults = ref<Array<{ id: string; filename: string; status: string }>>([])
const searching = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchQuery, (q) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!q.trim()) { searchResults.value = []; return }
  debounceTimer = setTimeout(() => searchBidTasks(q), 300)
})

async function searchBidTasks(q: string) {
  searching.value = true
  try {
    const res = await client.get('/tasks', { params: { status: 'completed', q, page_size: 5 } })
    searchResults.value = res.data.items || []
  } catch { searchResults.value = [] }
  finally { searching.value = false }
}

function selectBidTask(task: { id: string; filename: string }) {
  reviewStore.selectedBidTask = task
  searchQuery.value = task.filename
  searchResults.value = []
}

// --- Tender file upload ---
const tenderFile = ref<File | null>(null)
const dragOver = ref(false)

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file && (file.name.endsWith('.docx') || file.name.endsWith('.doc'))) {
    tenderFile.value = file
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) tenderFile.value = input.files[0]
}

// --- Start review ---
const submitting = ref(false)

async function startReview() {
  if (!reviewStore.selectedBidTask || !tenderFile.value) return
  submitting.value = true
  try {
    await reviewStore.startReview(reviewStore.selectedBidTask.id, tenderFile.value)
  } catch { /* error shown via store */ }
  finally { submitting.value = false }
}
</script>

<template>
  <div class="max-w-2xl mx-auto py-8 space-y-6">
    <h2 class="text-xl font-semibold text-text-primary">标书审查</h2>

    <!-- Bid task search -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">选择招标文件</label>
      <div class="relative">
        <Search class="absolute left-3 top-2.5 size-4 text-text-muted" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索已解析的招标文件..."
          class="w-full pl-10 pr-4 py-2 border border-border rounded-lg bg-surface text-sm"
        />
        <div v-if="searchResults.length" class="absolute z-10 w-full mt-1 bg-surface border border-border rounded-lg shadow-lg">
          <button
            v-for="task in searchResults" :key="task.id"
            class="w-full px-4 py-2 text-sm text-left hover:bg-background"
            @click="selectBidTask(task)"
          >{{ task.filename }}</button>
        </div>
      </div>
      <div v-if="reviewStore.selectedBidTask" class="text-xs text-success">
        已选择: {{ reviewStore.selectedBidTask.filename }}
      </div>
    </div>

    <!-- Tender file upload -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">上传投标文件</label>
      <div
        class="border-2 border-dashed rounded-lg p-8 text-center transition-colors"
        :class="dragOver ? 'border-success bg-success/5' : 'border-border'"
        @dragover.prevent="dragOver = true"
        @dragleave="dragOver = false"
        @drop.prevent="handleDrop"
      >
        <Upload class="size-8 mx-auto text-text-muted mb-2" />
        <p class="text-sm text-text-muted">拖拽投标文件到此处，或
          <label class="text-success cursor-pointer hover:underline">
            点击选择
            <input type="file" accept=".docx,.doc" class="hidden" @change="handleFileSelect" />
          </label>
        </p>
        <p v-if="tenderFile" class="mt-2 text-sm text-text-primary">{{ tenderFile.name }}</p>
      </div>
    </div>

    <!-- Error -->
    <p v-if="reviewStore.error" class="text-sm text-danger">{{ reviewStore.error }}</p>

    <!-- Start button -->
    <button
      :disabled="!reviewStore.selectedBidTask || !tenderFile || submitting"
      class="w-full py-3 bg-success text-white rounded-lg font-medium disabled:opacity-50 flex items-center justify-center gap-2"
      @click="startReview"
    >
      <ShieldCheck class="size-5" />
      {{ submitting ? '提交中...' : '开始审查' }}
    </button>
  </div>
</template>
```

- [ ] **Step 2: 实现 BidReviewView.vue**

```vue
<!-- web/src/views/BidReviewView.vue -->
<script setup lang="ts">
import { onUnmounted, watch } from 'vue'
import { useReviewStore } from '../stores/reviewStore'
import ReviewUploadStage from '../components/ReviewUploadStage.vue'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const store = useReviewStore()

// SSE connection for processing stage
let eventSource: EventSource | null = null

watch(() => store.stage, (stage) => {
  if (stage === 'processing' && store.currentReviewId) {
    connectSSE(store.currentReviewId)
  } else {
    disconnectSSE()
  }
})

function connectSSE(reviewId: string) {
  disconnectSSE()
  const token = localStorage.getItem('token')
  eventSource = new EventSource(
    `/api/reviews/${reviewId}/progress?token=${token}`
  )
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      store.handleProgressEvent(data)
    } catch { /* ignore parse errors */ }
  }
  eventSource.onerror = () => {
    disconnectSSE()
  }
}

function disconnectSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

onUnmounted(() => disconnectSSE())
</script>

<template>
  <div class="h-full">
    <!-- Upload stage -->
    <ReviewUploadStage v-if="store.stage === 'upload'" />

    <!-- Processing stage -->
    <div v-else-if="store.stage === 'processing'" class="flex flex-col items-center justify-center h-full gap-4">
      <div class="w-64 bg-background rounded-full h-3 overflow-hidden">
        <div
          class="h-full bg-success transition-all duration-300 rounded-full"
          :style="{ width: `${store.progress}%` }"
        />
      </div>
      <p class="text-sm text-text-secondary">{{ store.currentStep || '准备中...' }}</p>
      <p v-if="store.detail" class="text-xs text-text-muted">{{ store.detail }}</p>
      <p v-if="store.error" class="text-sm text-danger">{{ store.error }}</p>
    </div>

    <!-- Preview stage -->
    <ReviewPreviewStage v-else-if="store.stage === 'preview'" />
  </div>
</template>
```

- [ ] **Step 3: 确认构建通过**

Run: `cd web && npx vue-tsc --noEmit`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/views/BidReviewView.vue web/src/components/ReviewUploadStage.vue
git commit -m "feat(frontend): add BidReviewView with upload stage"
```

---

### Task 13: ReviewPreviewStage + ReviewResultsView

**Files:**
- Create: `web/src/components/ReviewPreviewStage.vue`
- Create: `web/src/views/ReviewResultsView.vue`
- Create: `web/src/views/ReviewDetailView.vue`

- [ ] **Step 1: 实现 ReviewPreviewStage.vue**

```vue
<!-- web/src/components/ReviewPreviewStage.vue -->
<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { Download, RotateCcw } from 'lucide-vue-next'
import { useReviewStore } from '../stores/reviewStore'
import { reviewsApi } from '../api/reviews'
import type { ReviewItem, ReviewSummary } from '../api/reviews'

const store = useReviewStore()
const tenderHtml = ref('')
const reviewItems = ref<ReviewItem[]>([])
const summary = ref<ReviewSummary | null>(null)
const loading = ref(true)
const activeItemId = ref<number | null>(null)

const leftPanel = ref<HTMLElement | null>(null)
const rightPanel = ref<HTMLElement | null>(null)

onMounted(async () => {
  if (!store.currentReviewId) return
  try {
    const res = await reviewsApi.preview(store.currentReviewId)
    tenderHtml.value = res.data.tender_html
    reviewItems.value = res.data.review_items
    summary.value = res.data.summary
  } catch { /* error */ }
  finally { loading.value = false }
})

// Click highlight → scroll to annotation
function onHighlightClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('[data-review-id]')
  if (!target) return
  const ids = target.getAttribute('data-review-id')?.split(' ').map(Number).filter(Boolean) || []
  if (ids.length > 0) {
    activeItemId.value = ids[0]
    nextTick(() => {
      const el = rightPanel.value?.querySelector(`[data-annotation-id="${ids[0]}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }
}

// Click annotation → scroll to highlight
function scrollToHighlight(itemId: number) {
  activeItemId.value = itemId
  const el = leftPanel.value?.querySelector(`[data-review-id~="${itemId}"]`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function downloadReport() {
  if (!store.currentReviewId) return
  const res = await reviewsApi.download(store.currentReviewId)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `审查报告.docx`
  a.click()
  URL.revokeObjectURL(url)
}

function resultColor(result: string) {
  return { pass: 'text-success', fail: 'text-danger', warning: 'text-warning' }[result] || 'text-text-muted'
}
function resultLabel(result: string) {
  return { pass: '合规', fail: '不合规', warning: '需注意', error: '错误' }[result] || result
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Summary bar -->
    <div v-if="summary" class="px-4 py-3 bg-surface border-b border-border flex items-center gap-4 text-sm">
      <span>共{{ summary.total }}条</span>
      <span class="text-success">通过{{ summary.pass }}</span>
      <span class="text-danger">不合规{{ summary.fail }}</span>
      <span class="text-warning">警告{{ summary.warning }}</span>
      <span v-if="summary.critical_fails" class="text-danger font-medium">废标风险: {{ summary.critical_fails }}条</span>
    </div>

    <!-- Main split view -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left: tender HTML -->
      <div ref="leftPanel" class="w-1/2 overflow-auto p-4 border-r border-border" @click="onHighlightClick">
        <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
        <div v-else class="prose max-w-none" v-html="tenderHtml" />
      </div>

      <!-- Right: annotations -->
      <div ref="rightPanel" class="w-1/2 overflow-auto p-4 space-y-3">
        <div
          v-for="item in reviewItems.filter(i => i.result !== 'pass')"
          :key="item.id"
          :data-annotation-id="item.id"
          class="p-3 rounded-lg border cursor-pointer transition-colors"
          :class="activeItemId === item.id ? 'border-success bg-success/5' : 'border-border'"
          @click="scrollToHighlight(item.id)"
        >
          <div class="flex items-center gap-2 mb-1">
            <span :class="resultColor(item.result)" class="text-sm font-medium">{{ resultLabel(item.result) }}</span>
            <span class="text-xs text-text-muted">置信度 {{ item.confidence }}%</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-background text-text-muted">{{ item.severity }}</span>
          </div>
          <p class="text-sm text-text-primary">{{ item.clause_text }}</p>
          <p class="text-xs text-text-muted mt-1">{{ item.reason }}</p>
        </div>
      </div>
    </div>

    <!-- Bottom bar -->
    <div class="px-4 py-3 bg-surface border-t border-border flex justify-between items-center">
      <button class="text-sm text-text-muted hover:text-text-secondary flex items-center gap-1" @click="store.resetToUpload()">
        <RotateCcw class="size-4" /> 新建审查
      </button>
      <button class="px-4 py-2 bg-success text-white rounded-lg text-sm flex items-center gap-1" @click="downloadReport">
        <Download class="size-4" /> 下载审查报告
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 实现 ReviewResultsView.vue**

```vue
<!-- web/src/views/ReviewResultsView.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Trash2, Download, Eye } from 'lucide-vue-next'
import { reviewsApi } from '../api/reviews'
import type { ReviewTask } from '../api/reviews'

const router = useRouter()
const items = ref<ReviewTask[]>([])
const total = ref(0)
const page = ref(1)
const searchQuery = ref('')
const loading = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => loadReviews())
watch(page, () => loadReviews())
watch(searchQuery, (q) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => { page.value = 1; loadReviews() }, 300)
})

async function loadReviews() {
  loading.value = true
  try {
    const res = await reviewsApi.list(page.value, 20, searchQuery.value || undefined)
    items.value = res.data.items
    total.value = res.data.total
  } catch { /* ignore */ }
  finally { loading.value = false }
}

function viewDetail(id: string) {
  router.push({ name: 'review-detail', params: { id } })
}

async function downloadReview(id: string) {
  const res = await reviewsApi.download(id)
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url; a.download = '审查报告.docx'; a.click()
  URL.revokeObjectURL(url)
}

async function deleteReview(id: string) {
  if (!confirm('确定删除此审查记录？')) return
  await reviewsApi.delete(id)
  loadReviews()
}

function resultSummaryText(r: ReviewTask) {
  if (!r.review_summary) return '处理中'
  const s = r.review_summary
  return `通过${s.pass} 不合规${s.fail} 警告${s.warning}`
}
</script>

<template>
  <div class="p-6 space-y-4">
    <div class="flex items-center justify-between">
      <h1 class="text-lg font-semibold text-text-primary">审查结果</h1>
      <div class="relative w-64">
        <Search class="absolute left-3 top-2.5 size-4 text-text-muted" />
        <input v-model="searchQuery" placeholder="搜索..." class="w-full pl-10 pr-4 py-2 border border-border rounded-lg text-sm" />
      </div>
    </div>

    <div v-if="loading" class="text-center text-text-muted py-12">加载中...</div>
    <div v-else class="space-y-2">
      <div
        v-for="item in items" :key="item.id"
        class="bg-surface border border-border rounded-lg px-4 py-3 flex items-center gap-3"
      >
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium text-text-primary truncate">{{ item.bid_filename }} → {{ item.tender_filename }}</div>
          <div class="text-xs text-text-muted mt-0.5">
            版本{{ item.version }} · {{ item.created_at }} · {{ resultSummaryText(item) }}
          </div>
        </div>
        <div class="flex gap-1.5">
          <button class="px-2.5 py-1.5 text-xs border border-border rounded-md hover:bg-background" @click="viewDetail(item.id)">
            <Eye class="size-3.5" />
          </button>
          <button class="px-2.5 py-1.5 text-xs border border-border rounded-md hover:bg-background" @click="downloadReview(item.id)">
            <Download class="size-3.5" />
          </button>
          <button class="px-2.5 py-1.5 text-xs border border-danger/30 rounded-md text-danger hover:bg-danger-light" @click="deleteReview(item.id)">
            <Trash2 class="size-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="total > 20" class="flex justify-center gap-2">
      <button :disabled="page <= 1" class="px-3 py-1 text-sm border rounded" @click="page--">上一页</button>
      <span class="px-3 py-1 text-sm">{{ page }} / {{ Math.ceil(total / 20) }}</span>
      <button :disabled="page >= Math.ceil(total / 20)" class="px-3 py-1 text-sm border rounded" @click="page++">下一页</button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 实现 ReviewDetailView.vue**

```vue
<!-- web/src/views/ReviewDetailView.vue -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useReviewStore } from '../stores/reviewStore'
import ReviewPreviewStage from '../components/ReviewPreviewStage.vue'

const route = useRoute()
const store = useReviewStore()

onMounted(async () => {
  const reviewId = route.params.id as string
  await store.loadReviewResult(reviewId)
})
</script>

<template>
  <ReviewPreviewStage v-if="store.stage === 'preview'" />
  <div v-else class="text-center text-text-muted py-12">加载审查结果...</div>
</template>
```

- [ ] **Step 4: 确认构建通过**

Run: `cd web && npx vue-tsc --noEmit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ReviewPreviewStage.vue \
  web/src/views/ReviewResultsView.vue web/src/views/ReviewDetailView.vue
git commit -m "feat(frontend): add review preview stage and results view"
```

---

## Chunk 6: 预览 API + 集成测试 + 部署

### Task 14: 预览 API 端点 + 图片服务

**Files:**
- Modify: `server/app/routers/reviews.py` (添加 preview 端点 + 图片服务端点)

- [ ] **Step 1: 添加 preview 端点**

```python
# server/app/routers/reviews.py — 在 download endpoint 之后添加

@router.get("/{review_id}/preview")
async def preview_review(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return HTML preview with data-review-id attributes on highlighted paragraphs."""
    review = await get_review(db, review_id, user.id)
    if not review or review.status != "completed":
        raise HTTPException(status_code=404, detail="审查结果不存在")

    # Build para_index → review item mapping
    para_review_map: dict[int, list[dict]] = {}
    for item in (review.review_items or []):
        if item.get("result") in ("fail", "warning"):
            for loc in item.get("tender_locations", []):
                for pi in loc.get("para_indices", []):
                    para_review_map.setdefault(pi, []).append(item)

    # Generate HTML with data-review-id attributes
    from server.app.routers.files import _para_to_html, _table_to_html
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(review.tender_file_path)
    body = doc.element.body
    parts = []          # list of (html_str, element_index) tuples
    element_idx = 0     # matches parse_docx body-level element index
    para_idx = 0
    table_idx = 0

    for child in body:
        if child.tag == qn("w:p"):
            if para_idx < len(doc.paragraphs):
                html_str = _para_to_html(doc.paragraphs[para_idx])
                if html_str and element_idx in para_review_map:
                    items = para_review_map[element_idx]
                    # Space-separated IDs for CSS ~= selector: [data-review-id~="3"]
                    review_ids = " ".join(str(item["id"]) for item in items)
                    result = "fail" if any(i["result"] == "fail" for i in items) else "warning"
                    css_class = f"review-highlight review-{result}"
                    # Inject data-review-id and CSS class (styles defined in frontend)
                    html_str = html_str.replace(
                        "<p", f'<p data-review-id="{review_ids}" class="{css_class}"', 1
                    )
                if html_str:
                    parts.append((html_str, element_idx))
                para_idx += 1
            element_idx += 1
        elif child.tag == qn("w:tbl"):
            if table_idx < len(doc.tables):
                parts.append((_table_to_html(doc.tables[table_idx]), element_idx))
                table_idx += 1
            element_idx += 1

    # Build image map: para_index → image filenames for inline display
    summary = review.review_summary or {}
    extracted_images = summary.get("extracted_images", [])
    para_image_map: dict[int, list[str]] = {}
    for img in extracted_images:
        pi = img.get("near_para_index")
        if pi is not None:
            para_image_map.setdefault(pi, []).append(img["filename"])

    # Inject <img> tags after elements that contain images
    from html import escape as html_escape
    final_parts = []
    for html_part, elem_idx in parts:
        final_parts.append(html_part)
        if elem_idx in para_image_map:
            for fn in para_image_map[elem_idx]:
                safe_fn = html_escape(fn)
                final_parts.append(
                    f'<div class="review-image" data-para-index="{elem_idx}">'
                    f'<img src="/api/reviews/{review_id}/images/{safe_fn}" '
                    f'alt="{safe_fn}" loading="lazy" />'
                    f'</div>'
                )

    return {
        "tender_html": "\n".join(final_parts),
        "review_items": review.review_items or [],
        "summary": summary,
    }
```

- [ ] **Step 2: 添加图片服务端点**

```python
# server/app/routers/reviews.py — 在 preview endpoint 之后添加

@router.get("/{review_id}/images/{filename}")
async def serve_review_image(
    review_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve an extracted image from a review task."""
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    import os
    images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
    image_path = os.path.join(images_dir, filename)

    # Security: ensure filename doesn't escape the images directory
    if not os.path.realpath(image_path).startswith(os.path.realpath(images_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")

    content_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")

    return FileResponse(image_path, media_type=content_type)
```

- [ ] **Step 3: Commit**

```bash
git add server/app/routers/reviews.py
git commit -m "feat(api): add review preview endpoint with images + annotation injection"
```

---

### Task 15: 集成测试

**Files:**
- Create: `server/tests/test_review_integration.py`

- [ ] **Step 1: 编写集成测试**

```python
# server/tests/test_review_integration.py
"""Integration tests for the review feature — mock LLM calls."""
import uuid
import os
import pytest
from unittest.mock import patch, MagicMock
from docx import Document

from server.app.models.task import Task
from server.app.models.review_task import ReviewTask

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def completed_task(db_session, test_user, tmp_path):
    """A completed bid task with extracted_data."""
    fpath = tmp_path / "招标文件.docx"
    doc = Document()
    doc.add_paragraph("测试招标文件内容")
    doc.save(str(fpath))
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id,
        filename="招标文件.docx", file_path=str(fpath),
        file_size=1000, status="completed",
        extracted_data={
            "schema_version": "1.0",
            "modules": {
                "module_e": {
                    "sections": [{"id": "risks", "type": "table", "title": "废标风险",
                                  "columns": ["序号", "风险项", "依据"],
                                  "rows": [["1", "未密封", "投标须知"]]}]
                },
            },
        },
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.fixture
def tender_docx(tmp_path):
    """A minimal tender docx for upload."""
    fpath = tmp_path / "投标文件.docx"
    doc = Document()
    doc.add_paragraph("第一章 投标函")
    doc.add_paragraph("我方承诺按照招标文件要求提交投标文件。")
    doc.save(str(fpath))
    return fpath


async def test_create_review(client, auth_headers, completed_task, tender_docx):
    """POST /api/reviews creates a review task."""
    with open(tender_docx, "rb") as f:
        resp = await client.post(
            "/api/reviews",
            data={"bid_task_id": str(completed_task.id)},
            files={"tender_file": ("投标文件.docx", f, "application/octet-stream")},
            headers=auth_headers,
        )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["version"] == 1


async def test_list_reviews_after_create(client, auth_headers, completed_task, tender_docx):
    """GET /api/reviews returns created reviews."""
    with open(tender_docx, "rb") as f:
        await client.post(
            "/api/reviews",
            data={"bid_task_id": str(completed_task.id)},
            files={"tender_file": ("投标文件.docx", f, "application/octet-stream")},
            headers=auth_headers,
        )
    resp = await client.get("/api/reviews", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_delete_review_cleanup(client, auth_headers, completed_task, tender_docx):
    """DELETE /api/reviews/{id} removes files and DB record."""
    with open(tender_docx, "rb") as f:
        create_resp = await client.post(
            "/api/reviews",
            data={"bid_task_id": str(completed_task.id)},
            files={"tender_file": ("投标文件.docx", f, "application/octet-stream")},
            headers=auth_headers,
        )
    review_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/reviews/{review_id}", headers=auth_headers)
    assert del_resp.status_code == 204
    # Verify it's gone
    get_resp = await client.get(f"/api/reviews/{review_id}", headers=auth_headers)
    assert get_resp.status_code == 404
```

- [ ] **Step 2: 运行全部测试**

Run: `cd server && python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_review_integration.py
git commit -m "test: add review integration tests"
```

---

### Task 16: Docker 部署更新

**Files:**
- Modify: `docker-compose.yml` (添加 reviews volume 映射)

- [ ] **Step 1: 确认 volume 映射正确**

`docker-compose.yml` 中 `filedata:/data` 已经覆盖了 `/data/reviews/` 路径，无需额外配置。

确认 `server/Dockerfile` 不需要修改（`src/reviewer/` 和 `config/prompts/` 通过 volume 映射直接可用）。

- [ ] **Step 2: 重新构建并部署**

```bash
docker compose build api worker nginx
docker compose up -d
```

- [ ] **Step 3: 验证表创建**

```bash
docker compose exec postgres bash -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt review_tasks"'
```
Expected: review_tasks 表存在

- [ ] **Step 4: 验证完成**

部署验证不需要代码更改，无需额外 commit。如有任何配置调整，按需单独 commit。
