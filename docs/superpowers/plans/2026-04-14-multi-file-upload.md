# 多文件上传支持 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持一个招标项目同时上传多份不同格式的招标文件（最多4份），分别解析后合并处理，前端展示文件列表供用户确认后再启动管线，同时修复 .doc/.pdf 文件预览失败问题。

**Architecture:** 采用"各文件独立解析后合并段落"的方案。引入 TaskFile 子表存储多文件信息，上传阶段逐个文件创建 TaskFile（Task 保持 pending），用户确认后触发管线，管线循环解析所有 TaskFile 合并段落再执行后续步骤。

**Tech Stack:** FastAPI + SQLAlchemy Async + Alembic + Celery + Vue 3 + Pinia

**Scope:** 本计划仅处理"多文件上传+解析+预览修复"。投标文件审查（ReviewTask）保持 1:1 关联，不改。

**Constraint:** 最多4份文件（前端拦截），第一个上传的为主文件，支持 .doc/.docx/.pdf 混合格式。

---

## Chunk 1: 后端 — 数据模型 + 迁移 + 服务 + 路由

### Task 1: 新增 TaskFile 模型

**Files:**
- Create: `server/app/models/task_file.py`
- Modify: `server/app/models/__init__.py`
- Modify: `server/app/models/task.py`

#### Step 1: 创建 TaskFile 模型文件

**File:** `server/app/models/task_file.py` (new)

```python
"""TaskFile ORM model — one-to-many relationship from Task."""

import uuid
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, func, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class TaskFile(Base):
    __tablename__ = "task_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    task = relationship("Task", back_populates="files")
```

- [ ] Write the file
- [ ] Commit

```bash
git add server/app/models/task_file.py
git commit -m "feat: add TaskFile model for multi-file uploads"
```

#### Step 2: 修改 Task 模型增加 files 关系

**File:** `server/app/models/task.py` — 在 `Task` 类中增加关系，在 `relationship` 下方添加：

```python
files = relationship("TaskFile", back_populates="task", cascade="all, delete-orphan",
                     order_by="TaskFile.sort_order")
```

- [ ] Add the `files` relationship to Task model
- [ ] Commit

```bash
git add server/app/models/task.py
git commit -m "feat: add files relationship to Task model"
```

#### Step 3: 导出 TaskFile

**File:** `server/app/models/__init__.py` — 修改 imports 和 `__all__`：

```python
from server.app.models.task_file import TaskFile  # new
__all__ = ["Base", "User", "Task", "TaskFile", "Annotation", "GeneratedFile", "ReviewTask"]
```

- [ ] Add TaskFile import and export
- [ ] Commit

```bash
git add server/app/models/__init__.py
git commit -m "feat: export TaskFile model"
```

### Task 2: 创建 Alembic 迁移

**Files:**
- Modify: `server/alembic/env.py`

#### Step 1: 注册 TaskFile 到 env.py

**File:** `server/alembic/env.py` — line 13-14，增加 import：

```python
from server.app.models import User, Task, TaskFile, Annotation, GeneratedFile  # noqa: F401
```

#### Step 2: 生成迁移

```bash
# 先 stamp 当前状态（因为没有迁移历史）
cd server && alembic stamp head

# 生成新迁移
alembic revision --autogenerate -m "add task_files table"
```

- [ ] Add TaskFile import to env.py
- [ ] Run `alembic stamp head` in `server/` directory
- [ ] Run `alembic revision --autogenerate -m "add task_files table"` in `server/` directory
- [ ] Verify generated migration file exists in `server/alembic/versions/`
- [ ] Commit

```bash
git add server/alembic/env.py server/alembic/versions/
git commit -m "feat: add alembic migration for task_files table"
```

### Task 3: 重构 Task Service — 拆分为两步

**Files:**
- Modify: `server/app/services/task_service.py`

**思路:**
- 保留 `create_task_from_upload` 的 Task 创建逻辑，改为接收**单个文件**，返回 Task 和 TaskFile
- 新增 `add_file_to_pending_task` — 给已有的 pending Task 追加文件
- 新增 `start_pending_task` — 用户确认后触发管线（dispatch Celery）
- 新增 `get_pending_files` — 获取 Task 下的所有 TaskFile 列表

#### Step 1: 写测试

**File:** `server/tests/test_multi_file_upload.py` (new)

```python
"""Tests for multi-file upload service functions."""
import pytest
from unittest.mock import MagicMock
from server.app.services.task_service import (
    create_task_from_upload,
    add_file_to_pending_task,
    start_pending_task,
    get_pending_files,
)


@pytest.mark.asyncio
async def test_create_first_file_creates_task_and_taskfile():
    mock_db = MagicMock()
    mock_file = MagicMock()
    mock_file.filename = "test.docx"
    mock_file.read = MagicMock(return_value=b"fake content")

    task = await create_task_from_upload(mock_db, mock_file, user_id=1)
    # Task should be pending, file_path should exist
    assert task.status == "pending"
    assert task.filename == "test.docx"
    mock_db.add.assert_called_once()
    await mock_db.commit()


@pytest.mark.asyncio
async def test_add_file_to_pending_task():
    from server.app.models.task import Task
    mock_db = MagicMock()
    task = Task(
        id="00000000-0000-0000-0000-000000000001",
        user_id=1,
        filename="first.docx",
        status="pending",
    )
    mock_file = MagicMock()
    mock_file.filename = "second.pdf"
    mock_file.read = MagicMock(return_value=b"fake pdf")

    result = await add_file_to_pending_task(mock_db, task.id, mock_file, user_id=1)
    assert result is not None
    assert result.filename == "second.pdf"
    assert result.is_primary is False


@pytest.mark.asyncio
async def test_add_file_exceeds_limit():
    from server.app.models.task import Task
    from server.app.services.task_service import MAX_FILES_PER_TASK
    mock_db = MagicMock()
    task = Task(
        id="00000000-0000-0000-0000-000000000001",
        user_id=1,
        filename="first.docx",
        status="pending",
    )
    # Simulate 4 existing files
    mock_db.execute = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 4
    mock_db.execute.return_value = count_result

    mock_file = MagicMock()
    mock_file.filename = "fifth.docx"

    with pytest.raises(Exception) as exc_info:
        await add_file_to_pending_task(mock_db, task.id, mock_file, user_id=1)
    assert "最多4份" in str(exc_info.value) or exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_pending_files():
    from server.app.models.task import Task
    mock_db = MagicMock()
    task = Task(
        id="00000000-0000-0000-0000-000000000001",
        user_id=1,
        filename="first.docx",
        status="pending",
    )
    files = await get_pending_files(mock_db, task.id, user_id=1)
    assert isinstance(files, list)
```

- [ ] Write the test file
- [ ] Commit

```bash
git add server/tests/test_multi_file_upload.py
git commit -m "test: add tests for multi-file upload service"
```

#### Step 2: 实现 service 函数

**File:** `server/app/services/task_service.py` — 完整重写：

```python
"""Business logic for task creation from file uploads."""

import os
import shutil
import uuid
from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.task import Task
from server.app.models.task_file import TaskFile

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}
MAX_FILES_PER_TASK = 4


async def create_task_from_upload(db: AsyncSession, file: UploadFile, user_id: int) -> Task:
    """创建第一个文件，生成 pending 状态的 Task 和对应的 TaskFile。"""
    task_id = uuid.uuid4()
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", str(task_id))
    os.makedirs(upload_dir, exist_ok=True)

    filename = _sanitize_filename(file.filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as f:
        f.write(content)

    task = Task(
        id=task_id,
        user_id=user_id,
        filename=filename,  # primary file name
        file_path=file_path,  # keep for backward compat with download endpoint
        file_size=len(content),
        status="pending",
    )
    db.add(task)

    # Also create TaskFile record
    task_file = TaskFile(
        id=uuid.uuid4(),
        task_id=task_id,
        filename=filename,
        file_path=file_path,
        file_size=len(content),
        is_primary=True,
        sort_order=0,
    )
    db.add(task_file)

    await db.commit()
    await db.refresh(task)
    return task


async def add_file_to_pending_task(db: AsyncSession, task_id: str, file: UploadFile, user_id: int) -> TaskFile:
    """给已有的 pending Task 追加文件。超过4份报错。"""
    task = await _get_user_task(db, task_id, user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "pending":
        raise HTTPException(status_code=400, detail="Task is not in pending status")

    # Check file count limit
    count_query = select(func.count()).select_from(TaskFile).where(TaskFile.task_id == task.id)
    count_result = await db.execute(count_query)
    current_count = count_result.scalar() or 0
    if current_count >= MAX_FILES_PER_TASK:
        raise HTTPException(status_code=400, detail=f"最多支持 {MAX_FILES_PER_TASK} 份文件")

    # Save file to disk
    filename = _sanitize_filename(file.filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    upload_dir = os.path.join(settings.DATA_DIR, "uploads", str(task.id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as f:
        f.write(content)

    task_file = TaskFile(
        id=uuid.uuid4(),
        task_id=task.id,
        filename=filename,
        file_path=file_path,
        file_size=len(content),
        is_primary=False,
        sort_order=current_count,
    )
    db.add(task_file)
    await db.commit()
    await db.refresh(task_file)
    return task_file


async def start_pending_task(db: AsyncSession, task_id: str, user_id: int) -> Task:
    """用户确认后，启动管线。将 Task 状态更新，返回 Task 对象。"""
    task = await _get_user_task(db, task_id, user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "pending":
        raise HTTPException(status_code=400, detail="Task is not in pending status")

    # Verify at least one file exists
    count_query = select(func.count()).select_from(TaskFile).where(TaskFile.task_id == task.id)
    count_result = await db.execute(count_query)
    file_count = count_result.scalar() or 0
    if file_count == 0:
        raise HTTPException(status_code=400, detail="No files uploaded")

    return task


async def get_pending_files(db: AsyncSession, task_id: str, user_id: int) -> list[dict]:
    """获取 Task 下所有 TaskFile 的列表信息。"""
    task = await _get_user_task(db, task_id, user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(TaskFile).where(TaskFile.task_id == task.id).order_by(TaskFile.sort_order)
    )
    files = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "filename": f.filename,
            "file_size": f.file_size,
            "is_primary": f.is_primary,
            "sort_order": f.sort_order,
        }
        for f in files
    ]


def _sanitize_filename(raw_name: str | None) -> str:
    """Decode latin-1 encoded Chinese filenames safely."""
    filename = raw_name or ""
    try:
        filename = filename.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return filename


async def _get_user_task(db: AsyncSession, task_id: str, user_id: int) -> Task | None:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_tasks(db, user_id, page, page_size, status=None, q=None):
    """Unchanged — list tasks with pagination."""
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


async def get_task(db, task_id, user_id):
    """Unchanged."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_task(db, task_id, user_id):
    """Unchanged — cascades to TaskFile via relationship."""
    task = await get_task(db, task_id, user_id)
    if not task:
        return False
    for dir_prefix in ["uploads", "intermediate", "output"]:
        dir_path = os.path.join(settings.DATA_DIR, dir_prefix, str(task_id))
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
    await db.delete(task)
    await db.commit()
    return True
```

- [ ] Write the service implementation
- [ ] Commit

```bash
git add server/app/services/task_service.py
git commit -m "feat: refactor task_service for multi-file uploads with confirm step"
```

### Task 4: 重构 Tasks Router — 新增 confirm 端点

**Files:**
- Modify: `server/app/routers/tasks.py`

#### Step 1: 写测试

**File:** `server/tests/test_multi_file_api.py` (new)

```python
"""API tests for multi-file upload endpoints."""
import pytest
from fastapi.testclient import TestClient
from server.app.main import app

client = TestClient(app)


def test_upload_first_file_creates_pending_task():
    """Upload a single .docx file should create a pending task."""
    # TODO: Requires auth token — skip for now, use integration testing
    pass


def test_confirm_pending_task_dispatches_pipeline():
    """Confirm endpoint should dispatch Celery pipeline."""
    pass


def test_add_file_to_nonexistent_task_returns_404():
    """Adding file to nonexistent task returns 404."""
    pass
```

- [ ] Write stub tests (fill in with auth when available)
- [ ] Commit

```bash
git add server/tests/test_multi_file_api.py
git commit -m "test: add stub tests for multi-file API endpoints"
```

#### Step 2: 修改路由

**File:** `server/app/routers/tasks.py` — 修改 `upload_and_create_task` 端点，新增 `add_file` 和 `confirm` 端点：

修改后的完整关键部分：

```python
# 修改 upload_and_create_task — 保持不变（仍为第一个文件上传）
# 新增 add_file 端点
@router.post("/{task_id}/files", status_code=status.HTTP_201_CREATED)
async def add_file(
    task_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """追加文件到 pending 状态的 Task（最多4份）。"""
    task_file = await add_file_to_pending_task(db, task_id, file, user.id)
    return {
        "id": str(task_file.id),
        "filename": task_file.filename,
        "file_size": task_file.file_size,
        "is_primary": task_file.is_primary,
    }

# 新增 get pending files 端点
@router.get("/{task_id}/files")
async def get_files(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取 Task 下所有已上传文件列表。"""
    files = await get_pending_files(db, task_id, user.id)
    return {"files": files}

# 新增 confirm 端点
@router.post("/{task_id}/confirm")
async def confirm_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户确认后启动分析管线。"""
    task = await start_pending_task(db, task_id, user.id)

    from server.app.tasks.pipeline_task import run_pipeline  # noqa: PLC0415
    celery_result = run_pipeline.delay(str(task.id))
    task.celery_task_id = celery_result.id
    task.status = "parsing"  # immediately start pipeline
    await db.commit()
    return {"task_id": str(task.id), "status": "parsing"}
```

需要更新的 imports:
```python
from server.app.services.task_service import (
    create_task_from_upload,
    add_file_to_pending_task,
    start_pending_task,
    get_pending_files,
    delete_task,
    get_task,
    get_tasks,
)
```

- [ ] Modify the router
- [ ] Commit

```bash
git add server/app/routers/tasks.py
git commit -m "feat: add /files and /confirm endpoints for multi-file upload workflow"
```

### Task 5: 修改 Pipeline Task — 多文件解析合并

**Files:**
- Modify: `server/app/tasks/pipeline_task.py`

#### Step 1: 修改解析阶段

**File:** `server/app/tasks/pipeline_task.py` — 修改 Layer 1 (Parse) 部分，从解析单个 `file_path` 改为循环解析所有 TaskFile：

```python
# 在 Layer 1 之前获取所有文件
from src.parser.unified import parse_documents

# 在 _get_task 之后：
files_to_parse = []
for tf in task.files:  # relationship ordered by sort_order
    files_to_parse.append(tf.file_path)

# Layer 1: Parse (0-10%)
self.update_state(
    state="PROGRESS",
    meta={"step": "parsing", "detail": f"解析 {len(files_to_parse)} 份文件...", "progress": 5},
)
all_paragraphs = parse_documents(files_to_parse)
```

- [ ] Modify pipeline_task.py — update import and Layer 1 parsing logic
- [ ] Commit

```bash
git add server/app/tasks/pipeline_task.py
git commit -m "feat: pipeline parses all TaskFiles and merges paragraphs"
```

### Task 6: 扩展 Parser — 多文件合并接口

**Files:**
- Modify: `src/parser/unified.py`
- Modify: `src/models.py`

#### Step 1: Paragraph 增加 source_file

**File:** `src/models.py` — 修改 `Paragraph` dataclass：

```python
@dataclass
class Paragraph:
    index: int
    text: str
    source_file: str = ""  # 新增：来自哪个源文件
    style: Optional[str] = None
    is_table: bool = False
    table_data: Optional[list] = None

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] Add `source_file` field to Paragraph
- [ ] Commit

```bash
git add src/models.py
git commit -m "feat: add source_file field to Paragraph for multi-file tracking"
```

#### Step 2: parse_documents 批量接口

**File:** `src/parser/unified.py` — 新增 `parse_documents` 函数：

```python
def parse_documents(file_paths: list[str]) -> list[Paragraph]:
    """依次解析多个文件，合并段落列表。
    
    每个段落增加 source_file 标记，后续管线无需修改。
    不支持的格式在对应文件上抛出 ValueError。
    """
    all_paragraphs: list[Paragraph] = []
    global_idx = 0
    
    for file_path in file_paths:
        filename = Path(file_path).name
        paragraphs = parse_document(file_path)
        for p in paragraphs:
            p.source_file = filename
            p.index = global_idx
            global_idx += 1
            all_paragraphs.append(p)
    
    return all_paragraphs
```

- [ ] Add `parse_documents` function
- [ ] Commit

```bash
git add src/parser/unified.py
git commit -m "feat: add parse_documents for batch multi-file parsing"
```

### Task 7: 修复预览 — 支持 .doc 和 .pdf

**Files:**
- Modify: `server/app/routers/files.py`

#### Step 1: 写测试

**File:** `server/tests/test_preview.py` — 已有的测试文件，查看并补充：

检查现有 `test_preview.py` 内容，确认是否已有覆盖。

- [ ] Review existing test_preview.py for gaps

#### Step 2: 修改 preview_file 端点

**File:** `server/app/routers/files.py` — 修改 `preview_file` 函数，根据文件扩展名分发到不同渲染器：

在 `_docx_to_html` 之后新增两个渲染函数：

```python
def _doc_to_html(file_path: str) -> str:
    """Convert a .doc file to HTML via LibreOffice temp conversion."""
    import tempfile
    from src.parser.doc_parser import _convert_doc_to_docx

    with tempfile.TemporaryDirectory() as tmp_dir:
        docx_path = _convert_doc_to_docx(file_path, tmp_dir)
        return _docx_to_html(docx_path)


def _pdf_to_html(file_path: str) -> str:
    """Convert a PDF file to simple HTML with text and tables."""
    try:
        import pdfplumber
    except ImportError:
        return "<p>pdfplumber 未安装，无法预览 PDF</p>"

    parts = []
    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            parts.append(f'<h2 style="color:#6b7280;font-size:12px;margin-top:20px">第 {page_num} 页</h2>')

            # Tables
            tables = page.extract_tables() or []
            for table in tables:
                if not table:
                    continue
                rows_html = []
                for i, row in enumerate(table):
                    cells = [f'<td style="padding:4px 8px;border:1px solid #d1d5db">{html.escape(cell or "")}</td>'
                             for cell in row]
                    rows_html.append(f'<tr>{"".join(cells)}</tr>')
                parts.append(
                    '<table style="border-collapse:collapse;width:100%;margin:8px 0;font-size:14px">'
                    + "".join(rows_html) + "</table>"
                )

            # Text
            text = page.extract_text() or ""
            if text.strip():
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        parts.append(f'<p style="margin:2px 0;font-size:14px">{html.escape(line)}</p>')

    return "\n".join(parts)
```

修改 `preview_file` 路由函数：

```python
@router.get("/{file_type}/{file_id}/preview")
async def preview_file(file_type, file_id, user, db):
    # ... 获取 file_path 和 fname 逻辑保持不变 ...

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        html_content = _docx_to_html(file_path)
    elif ext == ".doc":
        html_content = _doc_to_html(file_path)
    elif ext == ".pdf":
        html_content = _pdf_to_html(file_path)
    else:
        raise HTTPException(status_code=400, detail=f"不支持预览的文件类型: {ext}")

    return {"html": html_content, "filename": fname}
```

- [ ] Add `_doc_to_html` and `_pdf_to_html` functions
- [ ] Modify `preview_file` to dispatch by extension
- [ ] Commit

```bash
git add server/app/routers/files.py
git commit -m "fix: support .doc and .pdf file preview in files router"
```

---

## Chunk 2: 前端 — 多文件上传交互

### Task 8: 新增 API 封装

**Files:**
- Modify: `web/src/api/tasks.ts`
- Modify: `web/src/types/task.ts`

#### Step 1: 扩展 Task 类型

**File:** `web/src/types/task.ts` — 新增 TaskFile 类型和 Task 上的 files 字段：

```typescript
export interface TaskFile {
  id: string
  filename: string
  file_size: number | null
  is_primary: boolean
  sort_order: number
}

export interface Task {
  id: string
  filename: string
  file_size: number | null
  status: string
  current_step: string | null
  progress: number
  error_message: string | null
  extracted_data: Record<string, any> | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  files?: TaskFile[]  // 新增
}
```

- [ ] Add TaskFile interface and files field to Task
- [ ] Commit

```bash
git add web/src/types/task.ts
git commit -m "feat: add TaskFile type for frontend"
```

#### Step 2: 新增 API 方法

**File:** `web/src/api/tasks.ts` — 新增三个方法：

```typescript
export const tasksApi = {
  upload: (file: File) => { /* 不变 */ },
  uploadFile: (taskId: string, file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return client.post<TaskFile>(`/tasks/${taskId}/files`, form)
  },
  getFiles: (taskId: string) =>
    client.get<{ files: TaskFile[] }>(`/tasks/${taskId}/files`),
  confirm: (id: string) =>
    client.post<{ task_id: string; status: string }>(`/tasks/${id}/confirm`),
  // ... rest unchanged
}
```

- [ ] Add `uploadFile`, `getFiles`, `confirm` API methods
- [ ] Commit

```bash
git add web/src/api/tasks.ts
git commit -m "feat: add multi-file upload API methods"
```

### Task 9: 重写 UploadStage 组件

**Files:**
- Modify: `web/src/components/UploadStage.vue`

#### Step 1: 设计组件结构

组件状态：
```typescript
type UploadStageState = 'empty' | 'uploading' | 'ready' | 'confirming'
```

交互：
1. 空状态：拖拽/选择文件
2. 上传中：显示上传进度
3. 就绪状态：显示文件列表 + 继续添加按钮 + "开始解析"按钮
4. 确认后：进入 processing 阶段

最大文件数：4

#### Step 2: 写实现

**File:** `web/src/components/UploadStage.vue` — 完整重写：

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'
import { FileText, Plus, X, Play } from 'lucide-vue-next'
import { useAnalysisStore } from '../stores/analysisStore'
import { tasksApi } from '../api/tasks'
import type { TaskFile } from '../types/task'

const store = useAnalysisStore()
const dragging = ref(false)
const uploading = ref(false)
const fileList = ref<TaskFile[]>([])
const error = ref<string | null>(null)
const MAX_FILES = 4

const canUpload = computed(() => fileList.value.length < MAX_FILES)

function onDrop(e: DragEvent) {
  dragging.value = false
  const files = e.dataTransfer?.files
  if (files) uploadFiles(Array.from(files))
}

function onSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const files = input.files
  if (files) uploadFiles(Array.from(files))
}

function validateFile(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['doc', 'docx', 'pdf'].includes(ext || '')) {
    error.value = `${file.name}: 仅支持 .doc / .docx / .pdf 文件`
    return false
  }
  if (file.size > 500 * 1024 * 1024) {
    error.value = `${file.name}: 文件大小超过 500MB 限制`
    return false
  }
  return true
}

async function uploadFiles(files: File[]) {
  error.value = null

  for (const file of files) {
    if (!validateFile(file)) continue
    if (fileList.value.length >= MAX_FILES) {
      error.value = `最多上传 ${MAX_FILES} 份文件`
      break
    }

    uploading.value = true
    try {
      if (fileList.value.length === 0) {
        // First file: creates a new pending task
        const res = await tasksApi.upload(file)
        store.currentTaskId = res.data.id
        localStorage.setItem('current_task_id', res.data.id)
        fileList.value.push({
          id: res.data.id,  // task_id as reference
          filename: res.data.filename,
          file_size: res.data.file_size,
          is_primary: true,
          sort_order: 0,
        })
      } else {
        // Additional files: append to existing task
        const taskId = store.currentTaskId!
        const res = await tasksApi.uploadFile(taskId, file)
        fileList.value.push(res.data)
      }
    } catch (e: any) {
      error.value = e.response?.data?.detail || `${file.name} 上传失败`
    }
  }
  uploading.value = false
}

async function removeFile(index: number) {
  // Simple client-side removal. First file cannot be removed.
  if (index === 0) {
    error.value = '不能删除主文件'
    return
  }
  const removed = fileList.value.splice(index, 1)[0]
  // Update sort_order
  fileList.value.forEach((f, i) => f.sort_order = i)
}

async function startParsing() {
  error.value = null
  if (!store.currentTaskId || fileList.value.length === 0) return

  try {
    await tasksApi.confirm(store.currentTaskId)
    store.stage = 'processing'
    store.progress = 0
  } catch (e: any) {
    error.value = e.response?.data?.detail || '启动解析失败'
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="text-center max-w-lg w-full">
      <h1 class="text-xl font-semibold text-text-primary mb-2">招标文件深度解析</h1>
      <p class="text-text-muted text-sm mb-8">上传招标文件（最多4份），AI智能解析生成分析报告</p>

      <!-- Upload area -->
      <div
        v-if="canUpload"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        :class="[
          'border-2 border-dashed rounded-xl p-8 transition-colors cursor-pointer bg-surface mb-4',
          dragging ? 'border-primary bg-primary-light' : 'border-border hover:border-text-muted',
        ]"
      >
        <FileText class="size-10 text-text-muted mb-3 mx-auto" />
        <p class="text-text-secondary mb-1">拖拽文件到此处，或点击上传</p>
        <p class="text-text-muted text-xs mb-4">支持 .doc / .docx / .pdf，最多 {{ MAX_FILES }} 份</p>
        <label
          :class="[
            'inline-block px-6 py-2.5 rounded-lg text-white text-sm cursor-pointer transition-colors',
            uploading ? 'bg-primary/70' : 'bg-primary hover:bg-primary-hover',
          ]"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" multiple @change="onSelect" :disabled="uploading" />
        </label>
      </div>

      <!-- File list -->
      <div v-if="fileList.length > 0" class="bg-surface rounded-xl border border-border p-4 mb-4">
        <h3 class="text-sm font-medium text-text-primary mb-3">
          已上传文件 ({{ fileList.length }}/{{ MAX_FILES }})
        </h3>
        <ul class="space-y-2">
          <li
            v-for="(f, i) in fileList"
            :key="f.id"
            class="flex items-center justify-between px-3 py-2 rounded-lg bg-background"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-xs text-text-muted shrink-0">#{{ i + 1 }}</span>
              <span class="text-sm text-text-primary truncate" :title="f.filename">{{ f.filename }}</span>
              <span v-if="f.is_primary" class="text-xs px-1.5 py-0.5 rounded bg-info-light text-info-foreground shrink-0">主文件</span>
            </div>
            <button
              v-if="i > 0"
              @click="removeFile(i)"
              class="text-text-muted hover:text-danger shrink-0 ml-2"
              :disabled="uploading"
            >
              <X class="size-4" />
            </button>
          </li>
        </ul>
      </div>

      <!-- Start parsing button -->
      <div v-if="fileList.length > 0" class="flex gap-3 justify-center mb-4">
        <label
          v-if="canUpload"
          :class="[
            'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm cursor-pointer transition-colors',
            uploading ? 'bg-primary/70 text-white' : 'bg-primary hover:bg-primary-hover text-white',
          ]"
        >
          <Plus class="size-4" />
          继续添加
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" multiple @change="onSelect" :disabled="uploading" />
        </label>
        <button
          @click="startParsing"
          :class="[
            'inline-flex items-center gap-2 px-6 py-2 rounded-lg text-white text-sm transition-colors',
            uploading ? 'bg-success/70 cursor-not-allowed' : 'bg-success hover:bg-success-hover',
          ]"
          :disabled="uploading"
        >
          <Play class="size-4" />
          开始解析
        </button>
      </div>

      <p v-if="error" class="text-danger text-sm mt-4">{{ error }}</p>
    </div>
  </div>
</template>
```

- [ ] Rewrite UploadStage.vue with multi-file support
- [ ] Commit

```bash
git add web/src/components/UploadStage.vue
git commit -m "feat: rewrite UploadStage for multi-file upload with file list and confirm button"
```

### Task 10: 更新 analysisStore

**Files:**
- Modify: `web/src/stores/analysisStore.ts`

#### Step 1: 修改 store

**File:** `web/src/stores/analysisStore.ts` — 主要变更：
1. `startUpload` 现在只上传第一个文件，创建 pending task
2. 不再自动切换到 `processing` 阶段，保持在 `upload` 阶段等用户确认
3. 新增状态变量记录上传的文件列表

```typescript
export const useAnalysisStore = defineStore('analysis', () => {
  const stage = ref<AnalysisStage>('upload')
  const currentTaskId = ref<string | null>(localStorage.getItem('current_task_id'))
  const progress = ref(0)
  const currentStep = ref('')
  const extractedData = ref<Record<string, any> | null>(null)
  const error = ref<string | null>(null)
  const uploadedFiles = ref<TaskFile[]>([])  // 新增

  async function startUpload(file: File) {
    error.value = null
    try {
      const res = await tasksApi.upload(file)
      currentTaskId.value = res.data.id
      localStorage.setItem('current_task_id', res.data.id)
      // DON'T switch stage — stay on upload, wait for confirm
      progress.value = 0
      uploadedFiles.value = [{
        id: res.data.id,
        filename: res.data.filename,
        file_size: res.data.file_size,
        is_primary: true,
        sort_order: 0,
      }]
    } catch (e: any) {
      error.value = e.response?.data?.detail || '上传失败'
      throw e
    }
  }

  async function uploadAdditionalFile(file: File) {
    if (!currentTaskId.value) throw new Error('No active task')
    error.value = null
    try {
      const res = await tasksApi.uploadFile(currentTaskId.value, file)
      uploadedFiles.value.push(res.data)
    } catch (e: any) {
      error.value = e.response?.data?.detail || '上传失败'
      throw e
    }
  }

  async function removeUploadedFile(index: number) {
    if (index === 0) throw new Error('Cannot remove primary file')
    uploadedFiles.value.splice(index, 1)
    // Re-number sort_order
    uploadedFiles.value.forEach((f, i) => f.sort_order = i)
  }

  async function startParsing() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.confirm(currentTaskId.value)
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '启动解析失败'
    }
  }

  // ... handleProgressEvent, skipReview, etc. unchanged ...

  function resetToUpload() {
    stage.value = 'upload'
    currentTaskId.value = null
    progress.value = 0
    currentStep.value = ''
    extractedData.value = null
    error.value = null
    uploadedFiles.value = []
    localStorage.removeItem('current_task_id')
  }

  return {
    stage, currentTaskId, progress, currentStep, extractedData, error, uploadedFiles,
    startUpload, uploadAdditionalFile, removeUploadedFile, startParsing,
    handleProgressEvent, skipReview, submitAnnotations,
    loadTaskState, resetToUpload,
  }
})
```

- [ ] Modify analysisStore with multi-file state
- [ ] Commit

```bash
git add web/src/stores/analysisStore.ts
git commit -m "feat: update analysisStore for multi-file upload workflow"
```

### Task 11: 更新 TaskResponse schema（后端）

**Files:**
- Modify: `server/app/schemas/task.py`

#### Step 1: 添加 TaskFileResponse schema

**File:** `server/app/schemas/task.py` — 新增 TaskFileResponse 并在 TaskResponse 中添加 files 字段：

```python
class TaskFileResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    filename: str
    file_size: int | None
    is_primary: bool
    sort_order: int


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    filename: str
    file_size: int | None
    status: str
    current_step: str | None
    progress: int
    error_message: str | None
    extracted_data: dict | None = None
    files: list[TaskFileResponse] = []  # 新增
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
```

- [ ] Add TaskFileResponse and files field to TaskResponse
- [ ] Commit

```bash
git add server/app/schemas/task.py
git commit -m "feat: add TaskFileResponse schema and files to TaskResponse"
```

---

## Chunk 3: 集成测试与文件服务更新

### Task 12: 更新文件服务 — 兼容多文件

**Files:**
- Modify: `server/app/services/file_service.py`
- Modify: `server/app/routers/files.py`

#### Step 1: 更新 download_file 端点

对于多文件 Task，`/api/files/bid-documents/{task_id}/download` 应下载主文件（当前 `Task.file_path`）。如果有需要，新增端点下载特定文件。

**File:** `server/app/routers/files.py` — 下载端点保持现有逻辑不变（`Task.file_path` 仍指向主文件）。

#### Step 2: 更新文件列表服务

**File:** `server/app/services/file_service.py` — 在 `_list_bid_documents` 中增加文件数量显示：

```python
items = [
    {
        "id": str(t.id), "filename": t.filename, "file_size": t.file_size,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "task_name": t.filename, "status": t.status,
        "file_count": len(t.files) if hasattr(t, 'files') and t.files else 1,
    }
    for t in tasks
]
```

- [ ] Add file_count to bid documents list
- [ ] Commit

```bash
git add server/app/services/file_service.py
git commit -m "feat: add file_count to bid documents listing"
```

### Task 13: 集成测试

**Files:**
- Modify: `server/tests/test_pipeline.py` (查看现有)
- Modify: `server/tests/test_files.py` (查看现有)

#### Step 1: 验证现有测试不受影响

确保以下测试仍然通过：
- `test_pipeline.py` — 单文件 pipeline 流程
- `test_files.py` — 文件列表/下载/删除

#### Step 2: 新增多文件 pipeline 测试

**File:** `server/tests/test_multi_file_pipeline.py` (new)

```python
"""Integration test: multi-file upload + pipeline."""
import pytest

@pytest.mark.integration
async def test_multi_file_pipeline():
    """
    1. Upload first file → pending task created
    2. Upload second file → TaskFile added
    3. Confirm → pipeline dispatches
    4. Pipeline parses both files, merges paragraphs
    5. Extraction works on merged paragraphs
    """
    pass
```

- [ ] Add integration test stub
- [ ] Commit

```bash
git add server/tests/test_multi_file_pipeline.py
git commit -m "test: add multi-file pipeline integration test stub"
```

---

## Task 14: 最终验证

- [ ] 运行数据库迁移：`cd server && alembic upgrade head`
- [ ] 启动后端，验证 upload / confirm / files 端点
- [ ] 启动前端，测试完整上传流程：拖入2份文件 → 确认 → 解析
- [ ] 测试 .doc 文件预览
- [ ] 测试 .pdf 文件预览
- [ ] 测试超过4份文件时前端拦截
- [ ] 测试删除非主文件
- [ ] Commit

```bash
git commit -m "chore: verify multi-file upload flow end-to-end"
```

---

## 风险与注意事项

1. **向后兼容**: 现有已完成 Task 没有 `files` 关系，下载/列表端点通过 `Task.file_path` 兼容
2. **删除级联**: `Task.files` 使用 `cascade="all, delete-orphan"`，删除 Task 自动清理所有 TaskFile
3. **LibreOffice 依赖**: `.doc` 预览和解析都依赖 LibreOffice，如果未安装会降级到 olefile（解析）或报错（预览）
4. **PDF 预览质量**: 基于 pdfplumber 的文本提取，图片型 PDF 无法预览（和解析行为一致）
