# 前端界面重构实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 header+内容区布局重构为侧边导航栏+状态驱动的招标解读工作流，新增文件管理四栏和人工审核阶段。

**Architecture:** 前端用 Vue 3 侧边栏布局替代顶部 header，招标解读页用状态机驱动6个阶段（upload→processing→review→reprocessing→generating→preview）。后端拆分 pipeline_task 为 parse+extract 和 generate 两个 Celery task，中间插入 review 暂停点。新增文件管理 API（GET/DELETE/preview）和批量重提取端点。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Tailwind CSS, FastAPI + SQLAlchemy async, Celery + Redis, python-docx (docx→HTML preview)

**Design Spec:** `docs/specs/2026-03-24-frontend-redesign-design.md`

---

## Chunk 1: 后端 — Pipeline 拆分与新增端点

### Task 1: 拆分 pipeline_task — 提取后暂停，新增 run_generate task

**Files:**
- Modify: `server/app/tasks/pipeline_task.py` (整个文件)
- Create: `server/app/tasks/generate_task.py`
- Modify: `server/app/tasks/celery_app.py:15-18`
- Test: `server/tests/test_pipeline_split.py`

- [ ] **Step 1: Write failing test for pipeline stopping at review**

```python
# server/tests/test_pipeline_split.py
"""Tests for pipeline split: run_pipeline stops at review, run_generate completes."""
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock

from server.app.models.task import Task


@pytest.fixture
def mock_pipeline_deps():
    """Mock all external pipeline dependencies."""
    with (
        patch("src.parser.unified.parse_document") as mock_parse,
        patch("src.indexer.indexer.build_index") as mock_index,
        patch("src.extractor.extractor.extract_single_module") as mock_extract,
        patch("src.persistence.save_parsed") as mock_sp,
        patch("src.persistence.save_indexed") as mock_si,
        patch("src.persistence.save_extracted") as mock_se,
        patch("src.config.load_settings") as mock_settings,
    ):
        mock_parse.return_value = [{"index": 0, "text": "test", "style": "body"}]
        mock_index.return_value = {"tagged_paragraphs": [], "sections": [], "confidence": 0.9}
        mock_extract.return_value = {"sections": [{"id": "s1", "title": "test"}]}
        mock_settings.return_value = MagicMock()
        yield {
            "parse": mock_parse,
            "index": mock_index,
            "extract": mock_extract,
        }


@pytest.fixture
def mock_generate_deps():
    """Mock all generation dependencies."""
    with (
        patch("src.generator.report_gen.render_report") as mock_report,
        patch("src.generator.format_gen.render_format") as mock_format,
        patch("src.generator.checklist_gen.render_checklist") as mock_checklist,
    ):
        # Create dummy output files
        def create_file(data, path):
            import os
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("dummy")

        mock_report.side_effect = create_file
        mock_format.side_effect = create_file
        mock_checklist.side_effect = create_file
        yield {
            "report": mock_report,
            "format": mock_format,
            "checklist": mock_checklist,
        }


class TestPipelineSplit:
    """run_pipeline should stop at review status after extraction."""

    def test_pipeline_stops_at_review(self, tmp_path, mock_pipeline_deps):
        """After extraction, task.status should be 'review' and pipeline returns."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from server.app.database import Base
        from server.app.models.task import Task
        from server.app.models.user import User
        from server.app.models.generated_file import GeneratedFile
        from server.app.models.annotation import Annotation
        from server.app.security import hash_password

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        task_id = uuid.uuid4()
        with Session(engine) as db:
            user = User(username="test", password_hash=hash_password("pass"), role="user")
            db.add(user)
            db.flush()
            task = Task(
                id=task_id, user_id=user.id, filename="test.docx",
                file_path=str(tmp_path / "test.docx"), status="pending",
            )
            # Create a dummy file
            (tmp_path / "test.docx").write_text("dummy")
            db.add(task)
            db.commit()

        with (
            patch("server.app.tasks.pipeline_task._sync_engine", engine),
            patch("server.app.tasks.pipeline_task.settings") as mock_s,
        ):
            mock_s.DATA_DIR = str(tmp_path / "data")

            from server.app.tasks.pipeline_task import run_pipeline
            # Mock self (celery task context)
            mock_self = MagicMock()
            run_pipeline.__wrapped__(mock_self, str(task_id))

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == "review"
            assert task.progress == 90
            assert task.extracted_data is not None
            # Should NOT have generated files
            from sqlalchemy import select
            result = db.execute(select(GeneratedFile).where(GeneratedFile.task_id == task_id))
            assert result.scalars().all() == []


class TestRunGenerate:
    """run_generate should produce 3 files and set status=completed."""

    def test_generate_completes(self, tmp_path, mock_generate_deps):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from server.app.database import Base
        from server.app.models.task import Task
        from server.app.models.user import User
        from server.app.models.generated_file import GeneratedFile
        from server.app.models.annotation import Annotation
        from server.app.security import hash_password

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        task_id = uuid.uuid4()
        with Session(engine) as db:
            user = User(username="test", password_hash=hash_password("pass"), role="user")
            db.add(user)
            db.flush()
            task = Task(
                id=task_id, user_id=user.id, filename="test.docx",
                file_path=str(tmp_path / "test.docx"), status="review",
                progress=90,
                extracted_data={"schema_version": "1.0", "modules": {"module_a": {}}},
            )
            db.add(task)
            db.commit()

        with (
            patch("server.app.tasks.generate_task._sync_engine", engine),
            patch("server.app.tasks.generate_task.settings") as mock_s,
        ):
            mock_s.DATA_DIR = str(tmp_path / "data")

            from server.app.tasks.generate_task import run_generate
            mock_self = MagicMock()
            run_generate.__wrapped__(mock_self, str(task_id))

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == "completed"
            assert task.progress == 100
            assert task.completed_at is not None
            from sqlalchemy import select
            result = db.execute(select(GeneratedFile).where(GeneratedFile.task_id == task_id))
            files = result.scalars().all()
            assert len(files) == 3
            types = {f.file_type for f in files}
            assert types == {"report", "format", "checklist"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_pipeline_split.py -v`
Expected: FAIL — `run_pipeline` still runs generation; `generate_task` module does not exist.

- [ ] **Step 3: Modify pipeline_task.py — stop at review after extraction**

Replace the generation section in `server/app/tasks/pipeline_task.py`. After extraction completes:

```python
# Replace everything from "# Layer 4: Generate" to end of try block with:

        # Pipeline stops here — user reviews before generation
        self.update_state(
            state="PROGRESS",
            meta={"step": "review", "detail": "等待人工审核...", "progress": 90},
        )

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "review"
            task.progress = 90
            db.commit()

        return {"status": "review", "task_id": task_id}
```

- [ ] **Step 4: Create generate_task.py**

```python
# server/app/tasks/generate_task.py
"""Celery task: run document generation stage (after human review)."""
import datetime
import os
import uuid as _uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


def _get_task(db: Session, task_id: str):
    from server.app.models.task import Task
    return db.get(Task, _uuid.UUID(task_id))


@celery_app.task(bind=True, name="run_generate")
def run_generate(self, task_id: str):
    """生成三份输出文档。"""
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist

    with Session(_sync_engine) as db:
        task = _get_task(db, task_id)
        if not task or not task.extracted_data:
            return {"error": "Task or extracted data not found"}
        extracted = task.extracted_data
        filename = task.filename
        task.status = "generating"
        db.commit()

    output_dir = os.path.join(settings.DATA_DIR, "output", task_id)
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(filename)[0]

    try:
        self.update_state(
            state="PROGRESS",
            meta={"step": "generating", "detail": "生成分析报告...", "progress": 92},
        )
        report_path = os.path.join(output_dir, f"{stem}_分析报告.docx")
        render_report(extracted, report_path)

        self.update_state(
            state="PROGRESS",
            meta={"step": "generating", "detail": "生成投标文件格式...", "progress": 95},
        )
        format_path = os.path.join(output_dir, f"{stem}_投标文件格式.docx")
        render_format(extracted, format_path)

        self.update_state(
            state="PROGRESS",
            meta={"step": "generating", "detail": "生成资料清单...", "progress": 98},
        )
        checklist_path = os.path.join(output_dir, f"{stem}_资料清单.docx")
        render_checklist(extracted, checklist_path)

        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.datetime.now()

            from server.app.models.generated_file import GeneratedFile
            for ftype, fpath in [
                ("report", report_path),
                ("format", format_path),
                ("checklist", checklist_path),
            ]:
                size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
                db.add(GeneratedFile(
                    task_id=_uuid.UUID(task_id),
                    file_type=ftype,
                    file_path=fpath,
                    file_size=size,
                ))
            db.commit()

        return {"status": "completed", "task_id": task_id}

    except Exception as e:
        with Session(_sync_engine) as db:
            task = _get_task(db, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
        raise
```

- [ ] **Step 5: Update celery_app.py — include new task modules**

In `server/app/tasks/celery_app.py`, update the include list:

```python
celery_app.conf.include = [
    "server.app.tasks.pipeline_task",
    "server.app.tasks.reextract_task",
    "server.app.tasks.generate_task",
    "server.app.tasks.bulk_reextract_task",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_pipeline_split.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/app/tasks/pipeline_task.py server/app/tasks/generate_task.py server/app/tasks/celery_app.py server/tests/test_pipeline_split.py
git commit -m "feat: split pipeline into parse+extract and generate stages with review pause point"
```

---

### Task 2: 新增 continue、parsed、bulk-reextract 端点

**Files:**
- Modify: `server/app/routers/tasks.py`
- Create: `server/app/tasks/bulk_reextract_task.py`
- Test: `server/tests/test_continue_and_reextract.py`

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_continue_and_reextract.py
"""Tests for /continue, /parsed, /bulk-reextract endpoints."""
import json
import os
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock

from server.app.models.task import Task
from server.app.models.annotation import Annotation


@pytest_asyncio.fixture
async def review_task(db_session, test_user, tmp_path):
    """Task in review status with extracted_data and parsed file."""
    task_id = uuid.uuid4()
    parsed_dir = tmp_path / "intermediate" / str(task_id)
    parsed_dir.mkdir(parents=True)
    parsed_path = str(parsed_dir / "parsed.json")
    with open(parsed_path, "w", encoding="utf-8") as f:
        json.dump([{"index": 0, "text": "项目简介", "style": "heading1"}], f, ensure_ascii=False)

    task = Task(
        id=task_id, user_id=test_user.id, filename="test.docx",
        file_path="/data/uploads/test.docx", status="review", progress=90,
        extracted_data={"schema_version": "1.0", "modules": {"module_a": {"sections": []}}},
        parsed_path=parsed_path,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestContinueEndpoint:
    @pytest.mark.asyncio
    async def test_continue_from_review(self, client, auth_headers, review_task):
        """POST /api/tasks/{id}/continue should dispatch generate task and set status=generating."""
        with patch("server.app.routers.tasks.run_generate") as mock_gen:
            mock_gen.delay.return_value = MagicMock(id="celery-gen-123")
            resp = await client.post(
                f"/api/tasks/{review_task.id}/continue", headers=auth_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "generating"
        mock_gen.delay.assert_called_once_with(str(review_task.id))

    @pytest.mark.asyncio
    async def test_continue_wrong_status(self, client, auth_headers, review_task, db_session):
        """Should return 409 if task is not in review status."""
        review_task.status = "processing"
        await db_session.commit()
        resp = await client.post(
            f"/api/tasks/{review_task.id}/continue", headers=auth_headers
        )
        assert resp.status_code == 409


class TestParsedEndpoint:
    @pytest.mark.asyncio
    async def test_get_parsed(self, client, auth_headers, review_task):
        """GET /api/tasks/{id}/parsed should return paragraphs."""
        resp = await client.get(
            f"/api/tasks/{review_task.id}/parsed", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "paragraphs" in data
        assert len(data["paragraphs"]) == 1
        assert data["paragraphs"][0]["text"] == "项目简介"

    @pytest.mark.asyncio
    async def test_parsed_no_file(self, client, auth_headers, review_task, db_session):
        """Should return 404 if parsed file doesn't exist."""
        review_task.parsed_path = "/nonexistent/parsed.json"
        await db_session.commit()
        resp = await client.get(
            f"/api/tasks/{review_task.id}/parsed", headers=auth_headers
        )
        assert resp.status_code == 404


class TestBulkReextractEndpoint:
    @pytest.mark.asyncio
    async def test_bulk_reextract(self, client, auth_headers, review_task, db_session):
        """POST /api/tasks/{id}/bulk-reextract should dispatch task for pending annotations."""
        ann = Annotation(
            task_id=review_task.id, user_id=1, module_key="module_a",
            section_id="module_a", content="请补充详情", status="pending",
        )
        db_session.add(ann)
        await db_session.commit()

        with patch("server.app.routers.tasks.run_bulk_reextract") as mock_re:
            mock_re.delay.return_value = MagicMock(id="celery-re-456")
            resp = await client.post(
                f"/api/tasks/{review_task.id}/bulk-reextract", headers=auth_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reprocessing"
        assert "module_a" in data["modules"]

    @pytest.mark.asyncio
    async def test_bulk_reextract_no_annotations(self, client, auth_headers, review_task):
        """Should return 400 if no pending annotations."""
        resp = await client.post(
            f"/api/tasks/{review_task.id}/bulk-reextract", headers=auth_headers
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_continue_and_reextract.py -v`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 3: Add endpoints to tasks.py**

Add to `server/app/routers/tasks.py`:

```python
@router.post("/{task_id}/continue")
async def continue_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger generation stage after human review."""
    task = await get_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "review":
        raise HTTPException(status_code=409, detail=f"Task status is '{task.status}', expected 'review'")

    from server.app.tasks.generate_task import run_generate
    celery_result = run_generate.delay(str(task.id))
    task.celery_task_id = celery_result.id
    task.status = "generating"
    await db.commit()
    return {"task_id": str(task.id), "status": "generating"}


@router.get("/{task_id}/parsed")
async def get_parsed(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return parsed paragraphs for review UI left panel."""
    task = await get_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.parsed_path or not os.path.exists(task.parsed_path):
        raise HTTPException(status_code=404, detail="Parsed data not found")

    import json as _json
    with open(task.parsed_path, "r", encoding="utf-8") as f:
        paragraphs = _json.load(f)
    return {"paragraphs": paragraphs}


@router.post("/{task_id}/bulk-reextract")
async def bulk_reextract(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk re-extract all modules with pending annotations."""
    task = await get_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "review":
        raise HTTPException(status_code=409, detail=f"Task status is '{task.status}', expected 'review'")

    from server.app.models.annotation import Annotation
    result = await db.execute(
        select(Annotation).where(
            Annotation.task_id == task.id, Annotation.status == "pending"
        )
    )
    pending = result.scalars().all()
    if not pending:
        raise HTTPException(status_code=400, detail="No pending annotations to process")

    modules = list({a.module_key for a in pending})

    from server.app.tasks.bulk_reextract_task import run_bulk_reextract
    celery_result = run_bulk_reextract.delay(str(task.id))
    task.celery_task_id = celery_result.id
    task.status = "reprocessing"
    await db.commit()
    return {"task_id": str(task.id), "status": "reprocessing", "modules": modules}
```

Add `import os` at top of file if not already present.

- [ ] **Step 4: Create bulk_reextract_task.py**

```python
# server/app/tasks/bulk_reextract_task.py
"""Celery task: bulk re-extract modules with pending annotations."""
import json
import os
import uuid as _uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from server.app.config import settings
from server.app.tasks.celery_app import celery_app

_sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url)


@celery_app.task(bind=True, name="run_bulk_reextract")
def run_bulk_reextract(self, task_id: str):
    """批量重提取所有有 pending 批注的模块。"""
    from src.extractor.base import reextract_with_annotations
    from src.config import load_settings
    from src.persistence import load_indexed
    from server.app.models.task import Task
    from server.app.models.annotation import Annotation

    with Session(_sync_engine) as db:
        task = db.get(Task, _uuid.UUID(task_id))
        if not task or not task.extracted_data:
            return {"error": "Task or data not found"}

        pending = db.execute(
            select(Annotation).where(
                Annotation.task_id == task.id, Annotation.status == "pending"
            )
        ).scalars().all()

        # Group by module_key
        modules_to_reextract = {}
        for ann in pending:
            modules_to_reextract.setdefault(ann.module_key, []).append(ann)

        indexed_path = task.indexed_path
        extracted = dict(task.extracted_data)

    # Load indexed paragraphs
    relevant_paragraphs = []
    if indexed_path and os.path.exists(indexed_path):
        indexed = load_indexed(indexed_path)
        relevant_paragraphs = indexed.get("tagged_paragraphs", [])

    api_settings = load_settings()
    module_keys = list(modules_to_reextract.keys())

    for i, module_key in enumerate(module_keys):
        progress = 10 + int(80 * i / len(module_keys))
        self.update_state(
            state="PROGRESS",
            meta={"step": "reprocessing", "detail": f"重提取 {module_key}...", "progress": progress},
        )

        anns = modules_to_reextract[module_key]
        module_data = extracted.get("modules", {}).get(module_key, {})

        # Build annotation list for the extractor
        ann_data = [{"content": a.content, "annotation_type": a.annotation_type} for a in anns]

        try:
            # Re-extract entire module with annotation context
            from src.extractor.extractor import extract_single_module
            new_module = extract_single_module(module_key, relevant_paragraphs, api_settings, annotations=ann_data)
            extracted["modules"][module_key] = new_module
        except Exception:
            # On failure, keep original module data
            pass

        # Mark annotations as resolved
        with Session(_sync_engine) as db:
            for ann in anns:
                db_ann = db.get(Annotation, ann.id)
                if db_ann:
                    db_ann.status = "resolved"
            db.commit()

    # Save updated extracted_data and set status back to review
    with Session(_sync_engine) as db:
        task = db.get(Task, _uuid.UUID(task_id))
        task.extracted_data = extracted
        task.status = "review"
        task.progress = 90

        # Also save to disk
        extracted_path = task.extracted_path
        if extracted_path:
            os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
            with open(extracted_path, "w", encoding="utf-8") as f:
                json.dump(extracted, f, ensure_ascii=False, indent=2)

        db.commit()

    return {"status": "review", "task_id": task_id, "modules": module_keys}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_continue_and_reextract.py -v`
Expected: PASS

- [ ] **Step 6: Run all existing tests to ensure no regressions**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/ -v --tb=short`
Expected: All pass (some pipeline tests may need updating due to pipeline_task changes)

- [ ] **Step 7: Commit**

```bash
git add server/app/routers/tasks.py server/app/tasks/bulk_reextract_task.py server/tests/test_continue_and_reextract.py
git commit -m "feat: add continue, parsed, bulk-reextract API endpoints"
```

---

### Task 3: SSE 端点修改 — 支持 review 状态检测

**Files:**
- Modify: `server/app/routers/tasks.py:56-110` (task_progress endpoint)
- Test: `server/tests/test_sse_review.py`

- [ ] **Step 1: Write failing test**

```python
# server/tests/test_sse_review.py
"""Tests for SSE endpoint handling review/generating status transitions."""
import json
import uuid
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, PropertyMock

from server.app.models.task import Task


@pytest_asyncio.fixture
async def review_task_with_celery(db_session, test_user):
    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="test.docx",
        file_path="/data/test.docx", status="review", progress=90,
        celery_task_id="celery-done-123",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestSSEReviewStatus:
    @pytest.mark.asyncio
    async def test_sse_returns_review_when_celery_success_and_status_review(
        self, client, auth_headers, review_task_with_celery
    ):
        """When Celery task is SUCCESS but DB status is 'review', SSE should send step='review'."""
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"

        with patch("server.app.routers.tasks.AsyncResult", return_value=mock_result):
            resp = await client.get(
                f"/api/tasks/{review_task_with_celery.id}/progress",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data: ")]
        assert len(data_lines) >= 1
        last = json.loads(data_lines[-1].replace("data: ", ""))
        assert last["step"] == "review"
        assert last["progress"] == 90

    @pytest.mark.asyncio
    async def test_sse_follows_new_celery_task_when_generating(
        self, client, auth_headers, review_task_with_celery, db_session
    ):
        """When Celery SUCCESS but DB status is 'generating' with new celery_task_id, SSE should follow new task."""
        review_task_with_celery.status = "generating"
        review_task_with_celery.celery_task_id = "celery-gen-456"
        await db_session.commit()

        mock_old = MagicMock()
        mock_old.state = "SUCCESS"
        mock_new = MagicMock()
        mock_new.state = "PROGRESS"
        mock_new.info = {"step": "generating", "progress": 95, "detail": "生成报告..."}

        call_count = 0
        def mock_async_result(task_id, app=None):
            nonlocal call_count
            call_count += 1
            if task_id == "celery-done-123":
                return mock_old
            return mock_new

        with patch("server.app.routers.tasks.AsyncResult", side_effect=mock_async_result):
            resp = await client.get(
                f"/api/tasks/{review_task_with_celery.id}/progress",
                headers=auth_headers,
            )

        assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_sse_review.py -v`
Expected: FAIL — SSE sends `step='completed'` when Celery is SUCCESS.

- [ ] **Step 3: Modify SSE endpoint**

Replace the `event_generator` function in `task_progress` endpoint in `server/app/routers/tasks.py`:

```python
    async def event_generator():
        nonlocal celery_task_id
        if not celery_task_id:
            yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            return

        from celery.result import AsyncResult
        from server.app.tasks.celery_app import celery_app as _celery_app
        from server.app.models.task import Task as TaskModel

        while True:
            celery_result = AsyncResult(celery_task_id, app=_celery_app)
            if celery_result.state == "PROGRESS":
                yield f"data: {json.dumps(celery_result.info)}\n\n"
            elif celery_result.state == "SUCCESS":
                # Check DB status — pipeline may have stopped at 'review'
                result = await db.execute(
                    select(TaskModel).where(TaskModel.id == task_uuid)
                )
                db_task = result.scalar_one_or_none()
                if db_task and db_task.status == "review":
                    yield f"data: {json.dumps({'progress': 90, 'step': 'review'})}\n\n"
                elif db_task and db_task.status in ("generating", "reprocessing"):
                    # New celery task was dispatched, follow it
                    new_id = db_task.celery_task_id
                    if new_id and new_id != celery_task_id:
                        celery_task_id = new_id
                        await asyncio.sleep(1)
                        continue
                    yield f"data: {json.dumps({'progress': db_task.progress, 'step': db_task.status})}\n\n"
                else:
                    yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                break
            elif celery_result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': -1, 'step': 'failed', 'error': str(celery_result.result)})}\n\n"
                break
            else:
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            await asyncio.sleep(1)
```

Note: Uses `nonlocal celery_task_id` to allow reassignment when following a new Celery task.

- [ ] **Step 4: Run tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_sse_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/routers/tasks.py server/tests/test_sse_review.py
git commit -m "feat: SSE endpoint detects review status after Celery SUCCESS"
```

---

### Task 4: 文件管理 API — files router

**Files:**
- Create: `server/app/routers/files.py`
- Create: `server/app/services/file_service.py`
- Modify: `server/app/main.py:11,46` (import + include files router)
- Test: `server/tests/test_files.py`

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_files.py
"""Tests for file management API (/api/files)."""
import uuid
import pytest
import pytest_asyncio

from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile


@pytest_asyncio.fixture
async def completed_task(db_session, test_user, tmp_path):
    task_id = uuid.uuid4()
    task = Task(
        id=task_id, user_id=test_user.id, filename="招标文件.docx",
        file_path=str(tmp_path / "招标文件.docx"), file_size=1024,
        status="completed", progress=100,
    )
    (tmp_path / "招标文件.docx").write_text("dummy")
    db_session.add(task)

    # Add generated files
    for ftype in ("report", "format", "checklist"):
        fpath = tmp_path / f"test_{ftype}.docx"
        fpath.write_text("dummy docx content")
        gf = GeneratedFile(
            task_id=task_id, file_type=ftype,
            file_path=str(fpath), file_size=100,
        )
        db_session.add(gf)

    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestFilesList:
    @pytest.mark.asyncio
    async def test_list_bid_documents(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=bid-documents", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["filename"] == "招标文件.docx"

    @pytest.mark.asyncio
    async def test_list_reports(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=reports", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_with_search(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=bid-documents&q=招标", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = await client.get("/api/files?file_type=bid-documents&q=不存在", headers=auth_headers)
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_requires_file_type(self, client, auth_headers):
        resp = await client.get("/api/files", headers=auth_headers)
        assert resp.status_code == 422  # missing required query param


class TestFilesDownload:
    @pytest.mark.asyncio
    async def test_download_generated(self, client, auth_headers, completed_task, db_session):
        from sqlalchemy import select
        result = await db_session.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == completed_task.id,
                GeneratedFile.file_type == "report",
            )
        )
        gf = result.scalar_one()
        resp = await client.get(f"/api/files/reports/{gf.id}/download", headers=auth_headers)
        assert resp.status_code == 200


class TestFilesDelete:
    @pytest.mark.asyncio
    async def test_delete_generated(self, client, auth_headers, completed_task, db_session):
        from sqlalchemy import select
        result = await db_session.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == completed_task.id,
                GeneratedFile.file_type == "report",
            )
        )
        gf = result.scalar_one()
        resp = await client.delete(f"/api/files/reports/{gf.id}", headers=auth_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_bid_document_forbidden(self, client, auth_headers, completed_task):
        resp = await client.delete(
            f"/api/files/bid-documents/{completed_task.id}", headers=auth_headers
        )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_files.py -v`
Expected: FAIL — `/api/files` routes don't exist.

- [ ] **Step 3: Create file_service.py**

```python
# server/app/services/file_service.py
"""Business logic for file management (list, download, delete)."""
import os

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile

FILE_TYPE_MAP = {
    "bid-documents": None,  # source: tasks table
    "reports": "report",
    "formats": "format",
    "checklists": "checklist",
}


async def list_files(
    db: AsyncSession, user_id: int, file_type: str,
    page: int = 1, page_size: int = 20, q: str | None = None,
) -> tuple[list[dict], int]:
    """List files by type with pagination and search."""
    if file_type == "bid-documents":
        return await _list_bid_documents(db, user_id, page, page_size, q)
    else:
        db_type = FILE_TYPE_MAP.get(file_type)
        if not db_type:
            return [], 0
        return await _list_generated_files(db, user_id, db_type, page, page_size, q)


async def _list_bid_documents(db, user_id, page, page_size, q):
    base = select(Task).where(Task.user_id == user_id, Task.status == "completed")
    count_base = select(func.count()).select_from(Task).where(
        Task.user_id == user_id, Task.status == "completed"
    )
    if q:
        base = base.where(Task.filename.ilike(f"%{q}%"))
        count_base = count_base.where(Task.filename.ilike(f"%{q}%"))

    total = (await db.execute(count_base)).scalar() or 0
    result = await db.execute(
        base.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    tasks = result.scalars().all()
    items = [
        {
            "id": str(t.id), "filename": t.filename, "file_size": t.file_size,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "task_name": t.filename,
        }
        for t in tasks
    ]
    return items, total


async def _list_generated_files(db, user_id, db_type, page, page_size, q):
    base = (
        select(GeneratedFile)
        .join(Task, GeneratedFile.task_id == Task.id)
        .where(Task.user_id == user_id, GeneratedFile.file_type == db_type)
    )
    count_base = (
        select(func.count())
        .select_from(GeneratedFile)
        .join(Task, GeneratedFile.task_id == Task.id)
        .where(Task.user_id == user_id, GeneratedFile.file_type == db_type)
    )
    if q:
        base = base.where(Task.filename.ilike(f"%{q}%"))
        count_base = count_base.where(Task.filename.ilike(f"%{q}%"))

    total = (await db.execute(count_base)).scalar() or 0
    result = await db.execute(
        base.order_by(GeneratedFile.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    files = result.scalars().all()

    items = []
    for gf in files:
        # Eagerly load task name
        task_result = await db.execute(select(Task.filename).where(Task.id == gf.task_id))
        task_name = task_result.scalar() or ""
        items.append({
            "id": gf.id, "filename": os.path.basename(gf.file_path),
            "file_size": gf.file_size,
            "created_at": gf.created_at.isoformat() if gf.created_at else None,
            "task_name": task_name,
        })
    return items, total
```

- [ ] **Step 4: Create files.py router**

```python
# server/app/routers/files.py
"""Router for file management — list, download, preview, delete."""
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile
from server.app.services.file_service import list_files, FILE_TYPE_MAP

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("")
async def list_files_endpoint(
    file_type: str = Query(..., description="bid-documents|reports|formats|checklists"),
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type not in FILE_TYPE_MAP:
        raise HTTPException(status_code=400, detail=f"Invalid file_type: {file_type}")
    items, total = await list_files(db, user.id, file_type, page, page_size, q)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{file_type}/{file_id}/download")
async def download_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type == "bid-documents":
        task = await _get_user_task(db, file_id, user.id)
        if not task or not os.path.exists(task.file_path):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(task.file_path, filename=task.filename)
    else:
        gf = await _get_user_generated_file(db, file_id, user.id)
        if not gf or not os.path.exists(gf.file_path):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(
            gf.file_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=os.path.basename(gf.file_path),
        )


@router.get("/{file_type}/{file_id}/preview")
async def preview_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return HTML preview of a generated .docx file."""
    if file_type == "bid-documents":
        raise HTTPException(status_code=501, detail="Preview not supported for uploaded files")

    gf = await _get_user_generated_file(db, file_id, user.id)
    if not gf or not os.path.exists(gf.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    from docx import Document
    doc = Document(gf.file_path)
    html_parts = []
    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        if "Heading" in style:
            level = style.replace("Heading ", "").strip() or "3"
            html_parts.append(f"<h{level}>{para.text}</h{level}>")
        else:
            html_parts.append(f"<p>{para.text}</p>")
    for table in doc.tables:
        html_parts.append("<table border='1' style='border-collapse:collapse;width:100%'>")
        for row in table.rows:
            html_parts.append("<tr>")
            for cell in row.cells:
                html_parts.append(f"<td style='padding:4px 8px'>{cell.text}</td>")
            html_parts.append("</tr>")
        html_parts.append("</table>")

    return {"html": "\n".join(html_parts), "filename": os.path.basename(gf.file_path)}


@router.delete("/{file_type}/{file_id}", status_code=204)
async def delete_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type == "bid-documents":
        raise HTTPException(status_code=403, detail="Cannot delete uploaded bid documents directly")

    gf = await _get_user_generated_file(db, file_id, user.id)
    if not gf:
        raise HTTPException(status_code=404, detail="File not found")

    if os.path.exists(gf.file_path):
        os.remove(gf.file_path)
    await db.delete(gf)
    await db.commit()


async def _get_user_task(db: AsyncSession, task_id: str, user_id: int):
    import uuid as _uuid
    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_user_generated_file(db: AsyncSession, file_id: str, user_id: int):
    try:
        fid = int(file_id)
    except ValueError:
        return None
    result = await db.execute(
        select(GeneratedFile)
        .join(Task, GeneratedFile.task_id == Task.id)
        .where(GeneratedFile.id == fid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 5: Register files router in main.py**

Add to `server/app/main.py`:
```python
from server.app.routers import auth, tasks, download, preview, annotations, users, files
# ...
app.include_router(files.router)
```

- [ ] **Step 6: Run tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/test_files.py -v`
Expected: PASS

- [ ] **Step 7: Run all backend tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add server/app/routers/files.py server/app/services/file_service.py server/app/main.py server/tests/test_files.py
git commit -m "feat: add file management API for listing, downloading, previewing, and deleting files"
```

---

## Chunk 2: 前端 — 布局重构与侧边栏

### Task 5: 创建 AppSidebar 和 SidebarLayout

**Files:**
- Create: `web/src/components/AppSidebar.vue`
- Create: `web/src/components/UserMenu.vue`
- Create: `web/src/layouts/SidebarLayout.vue`
- Test: `web/src/components/__tests__/AppSidebar.test.ts`

> **前端测试说明**: 前端组件测试使用 Vitest + @vue/test-utils。如果项目未安装测试依赖，需先安装：
> `npm install -D vitest @vue/test-utils @vitejs/plugin-vue jsdom`
> 并在 `vite.config.ts` 中添加 test 配置。

- [ ] **Step 1: Check and setup frontend test infrastructure**

检查 `web/package.json` 是否已包含 vitest。如果没有：

```bash
cd d:/BaiduSyncdisk/标书项目/招标文件解读/web
npm install -D vitest @vue/test-utils @vitejs/plugin-vue jsdom happy-dom
```

在 `web/vitest.config.ts` 创建（如果不存在）：
```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
```

在 `web/package.json` 的 scripts 中添加（如果不存在）：
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 2: Write failing test for AppSidebar**

```typescript
// web/src/components/__tests__/AppSidebar.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/files/bid-documents', component: { template: '<div />' } },
    { path: '/files/reports', component: { template: '<div />' } },
    { path: '/files/formats', component: { template: '<div />' } },
    { path: '/files/checklists', component: { template: '<div />' } },
    { path: '/admin/users', component: { template: '<div />' } },
  ],
})

function mountSidebar(userOverride = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  // Set up auth store with user
  const { useAuthStore } = require('../../stores/authStore')
  const auth = useAuthStore()
  auth.user = { id: 1, username: 'testuser', display_name: 'Test', role: 'user', ...userOverride }
  auth.accessToken = 'fake-token'

  return mount(AppSidebar, {
    global: { plugins: [pinia, router] },
  })
}

describe('AppSidebar', () => {
  beforeEach(async () => {
    await router.push('/')
    await router.isReady()
  })

  it('renders 5 navigation items', () => {
    const wrapper = mountSidebar()
    const navItems = wrapper.findAll('[data-testid="nav-item"]')
    expect(navItems.length).toBe(5)
  })

  it('highlights active route', async () => {
    await router.push('/files/reports')
    const wrapper = mountSidebar()
    const active = wrapper.find('[data-testid="nav-item"].active')
    expect(active.exists()).toBe(true)
    expect(active.text()).toContain('解析报告')
  })

  it('shows user info at bottom', () => {
    const wrapper = mountSidebar({ username: 'admin', display_name: 'Admin' })
    expect(wrapper.text()).toContain('admin')
  })

  it('shows admin menu item for admin users', async () => {
    const wrapper = mountSidebar({ role: 'admin' })
    await wrapper.find('[data-testid="user-avatar"]').trigger('click')
    expect(wrapper.text()).toContain('用户管理')
  })

  it('hides admin menu item for regular users', async () => {
    const wrapper = mountSidebar({ role: 'user' })
    await wrapper.find('[data-testid="user-avatar"]').trigger('click')
    expect(wrapper.text()).not.toContain('用户管理')
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/AppSidebar.test.ts`
Expected: FAIL — component doesn't exist.

- [ ] **Step 4: Create UserMenu.vue**

```vue
<!-- web/src/components/UserMenu.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const auth = useAuthStore()
const router = useRouter()
const showMenu = ref(false)

function toggleMenu() {
  showMenu.value = !showMenu.value
}

function goToUserManagement() {
  showMenu.value = false
  router.push('/admin/users')
}

function logout() {
  showMenu.value = false
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="relative">
    <div
      data-testid="user-avatar"
      class="flex items-center gap-2 cursor-pointer hover:bg-gray-100 rounded-lg p-2 transition-colors"
      @click="toggleMenu"
    >
      <div class="w-8 h-8 bg-purple-600 rounded-full flex items-center justify-center text-white text-sm font-medium">
        {{ (auth.user?.display_name || auth.user?.username || '?')[0].toUpperCase() }}
      </div>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-medium text-gray-800 truncate">{{ auth.user?.display_name || auth.user?.username }}</div>
        <div class="text-xs text-gray-400">{{ auth.user?.role === 'admin' ? '管理员' : '用户' }}</div>
      </div>
      <span class="text-gray-400 text-xs">{{ showMenu ? '▴' : '▾' }}</span>
    </div>

    <div
      v-if="showMenu"
      class="absolute bottom-full left-0 right-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50"
    >
      <button
        v-if="auth.isAdmin"
        class="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        @click="goToUserManagement"
      >
        👤 用户管理
      </button>
      <button
        class="w-full text-left px-3 py-2 text-sm text-red-500 hover:bg-gray-50 transition-colors"
        @click="logout"
      >
        🚪 退出登录
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 5: Create AppSidebar.vue**

```vue
<!-- web/src/components/AppSidebar.vue -->
<script setup lang="ts">
import { useRoute } from 'vue-router'
import UserMenu from './UserMenu.vue'

const route = useRoute()

const navItems = [
  { path: '/', label: '招标解读', icon: '📝', group: 'main' },
  { path: '/files/bid-documents', label: '招标文件', icon: '📁', group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: '📊', group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: '📐', group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: '📋', group: 'files' },
]

function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <aside class="w-[200px] min-w-[200px] bg-white border-r border-gray-200 flex flex-col h-screen">
    <!-- Logo -->
    <div class="px-4 py-4 font-bold text-gray-800 text-base">
      📋 招标分析系统
    </div>

    <!-- Navigation -->
    <nav class="flex-1 flex flex-col">
      <!-- Main: 招标解读 -->
      <router-link
        v-for="item in navItems.filter(n => n.group === 'main')"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
          isActive(item.path)
            ? 'bg-purple-50 text-purple-700 font-medium border-l-[3px] border-purple-600'
            : 'text-gray-600 hover:bg-gray-50 border-l-[3px] border-transparent'
        ]"
      >
        <span>{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>

      <!-- Divider -->
      <div class="h-px bg-gray-200 mx-4 my-3"></div>

      <!-- Section label -->
      <div class="px-4 pb-1 text-xs text-gray-400">文档管理</div>

      <!-- File management items -->
      <router-link
        v-for="item in navItems.filter(n => n.group === 'files')"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
          isActive(item.path)
            ? 'bg-purple-50 text-purple-700 font-medium border-l-[3px] border-purple-600'
            : 'text-gray-600 hover:bg-gray-50 border-l-[3px] border-transparent'
        ]"
      >
        <span>{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <!-- User menu at bottom -->
    <div class="border-t border-gray-200 p-3">
      <UserMenu />
    </div>
  </aside>
</template>
```

- [ ] **Step 6: Create SidebarLayout.vue**

```vue
<!-- web/src/layouts/SidebarLayout.vue -->
<script setup lang="ts">
import AppSidebar from '../components/AppSidebar.vue'
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <AppSidebar />
    <main class="flex-1 overflow-auto bg-gray-50">
      <router-view />
    </main>
  </div>
</template>
```

- [ ] **Step 7: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/AppSidebar.test.ts`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add web/src/components/AppSidebar.vue web/src/components/UserMenu.vue web/src/layouts/SidebarLayout.vue web/src/components/__tests__/AppSidebar.test.ts web/vitest.config.ts
git commit -m "feat: add sidebar layout with navigation and user menu"
```

---

### Task 6: 更新路由配置

**Files:**
- Modify: `web/src/router/index.ts`
- Test: `web/src/router/__tests__/router.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/router/__tests__/router.test.ts
import { describe, it, expect } from 'vitest'
import router from '../index'

describe('Router', () => {
  it('has all required routes', () => {
    const paths = router.getRoutes().map(r => r.path)
    expect(paths).toContain('/login')
    expect(paths).toContain('/')
    expect(paths).toContain('/files/:fileType')
    expect(paths).toContain('/files/:fileType/:id/preview')
    expect(paths).toContain('/admin/users')
  })

  it('default route is bid analysis', () => {
    const route = router.getRoutes().find(r => r.path === '/')
    expect(route).toBeDefined()
    expect(route?.name).toBe('bid-analysis')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/router/__tests__/router.test.ts`
Expected: FAIL — routes don't match new design.

- [ ] **Step 3: Update router/index.ts**

```typescript
// web/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
  },
  {
    path: '/',
    component: () => import('../layouts/SidebarLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'bid-analysis',
        component: () => import('../views/BidAnalysisView.vue'),
      },
      {
        path: 'files/:fileType',
        name: 'file-manager',
        component: () => import('../views/FileManagerView.vue'),
        props: true,
      },
      {
        path: 'files/:fileType/:id/preview',
        name: 'file-preview',
        component: () => import('../views/FilePreviewView.vue'),
        props: true,
      },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('../views/AdminUsersView.vue'),
        meta: { requiresAdmin: true },
      },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) return { name: 'login' }
  // Nested routes inherit parent meta
  if (to.matched.some(r => r.meta.requiresAuth) && !token) return { name: 'login' }
})

export default router
```

- [ ] **Step 4: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/router/__tests__/router.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/router/index.ts web/src/router/__tests__/router.test.ts
git commit -m "feat: update router with sidebar layout and new file management routes"
```

---

## Chunk 3: 前端 — 招标解读状态机与各阶段组件

### Task 7: 创建 analysisStore 状态管理

**Files:**
- Create: `web/src/stores/analysisStore.ts`
- Create: `web/src/api/files.ts`
- Modify: `web/src/api/tasks.ts` (新增 continue, parsed, bulkReextract)
- Test: `web/src/stores/__tests__/analysisStore.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/stores/__tests__/analysisStore.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAnalysisStore } from '../analysisStore'

vi.mock('../../api/tasks', () => ({
  tasksApi: {
    upload: vi.fn().mockResolvedValue({ data: { id: 'task-123', status: 'pending' } }),
    get: vi.fn().mockResolvedValue({ data: { id: 'task-123', status: 'review', progress: 90, extracted_data: {} } }),
    continue: vi.fn().mockResolvedValue({ data: { status: 'generating' } }),
    bulkReextract: vi.fn().mockResolvedValue({ data: { status: 'reprocessing', modules: ['module_a'] } }),
  },
}))

describe('analysisStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('starts in upload stage', () => {
    const store = useAnalysisStore()
    expect(store.stage).toBe('upload')
    expect(store.currentTaskId).toBeNull()
  })

  it('transitions to processing after upload', async () => {
    const store = useAnalysisStore()
    await store.startUpload(new File(['test'], 'test.docx'))
    expect(store.stage).toBe('processing')
    expect(store.currentTaskId).toBe('task-123')
  })

  it('persists taskId to localStorage', async () => {
    const store = useAnalysisStore()
    await store.startUpload(new File(['test'], 'test.docx'))
    expect(localStorage.getItem('current_task_id')).toBe('task-123')
  })

  it('resets to upload stage', () => {
    const store = useAnalysisStore()
    store.stage = 'preview'
    store.currentTaskId = 'task-123'
    store.resetToUpload()
    expect(store.stage).toBe('upload')
    expect(store.currentTaskId).toBeNull()
    expect(localStorage.getItem('current_task_id')).toBeNull()
  })

  it('handles SSE review event', () => {
    const store = useAnalysisStore()
    store.stage = 'processing'
    store.handleProgressEvent({ step: 'review', progress: 90 })
    expect(store.stage).toBe('review')
  })

  it('handles SSE completed event', () => {
    const store = useAnalysisStore()
    store.stage = 'generating'
    store.handleProgressEvent({ step: 'completed', progress: 100 })
    expect(store.stage).toBe('preview')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/stores/__tests__/analysisStore.test.ts`
Expected: FAIL

- [ ] **Step 3: Update tasks.ts API**

```typescript
// web/src/api/tasks.ts
import client from './client'
import type { Task } from '../types/task'

export const tasksApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    return client.post<Task>('/tasks', form)
  },
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    client.get('/tasks', { params }),
  get: (id: string) => client.get<Task>(`/tasks/${id}`),
  delete: (id: string) => client.delete(`/tasks/${id}`),
  continue: (id: string) => client.post<{ task_id: string; status: string }>(`/tasks/${id}/continue`),
  parsed: (id: string) => client.get<{ paragraphs: Array<{ index: number; text: string; style: string }> }>(`/tasks/${id}/parsed`),
  bulkReextract: (id: string) => client.post<{ task_id: string; status: string; modules: string[] }>(`/tasks/${id}/bulk-reextract`),
}
```

- [ ] **Step 4: Create files.ts API**

```typescript
// web/src/api/files.ts
import client from './client'

export interface FileItem {
  id: string | number
  filename: string
  file_size: number | null
  created_at: string | null
  task_name: string
}

export interface FileListResponse {
  items: FileItem[]
  total: number
  page: number
  page_size: number
}

export const filesApi = {
  list: (fileType: string, params?: { page?: number; page_size?: number; q?: string }) =>
    client.get<FileListResponse>('/files', { params: { file_type: fileType, ...params } }),
  download: (fileType: string, id: string | number) =>
    client.get(`/files/${fileType}/${id}/download`, { responseType: 'blob' }),
  preview: (fileType: string, id: string | number) =>
    client.get<{ html: string; filename: string }>(`/files/${fileType}/${id}/preview`),
  delete: (fileType: string, id: string | number) =>
    client.delete(`/files/${fileType}/${id}`),
}
```

- [ ] **Step 5: Create analysisStore.ts**

```typescript
// web/src/stores/analysisStore.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tasksApi } from '../api/tasks'
import type { ProgressEvent } from '../types/task'

export type AnalysisStage = 'upload' | 'processing' | 'review' | 'reprocessing' | 'generating' | 'preview'

export const useAnalysisStore = defineStore('analysis', () => {
  const stage = ref<AnalysisStage>('upload')
  const currentTaskId = ref<string | null>(localStorage.getItem('current_task_id'))
  const progress = ref(0)
  const currentStep = ref('')
  const extractedData = ref<Record<string, any> | null>(null)
  const error = ref<string | null>(null)

  async function startUpload(file: File) {
    error.value = null
    try {
      const res = await tasksApi.upload(file)
      currentTaskId.value = res.data.id
      localStorage.setItem('current_task_id', res.data.id)
      stage.value = 'processing'
      progress.value = 0
    } catch (e: any) {
      error.value = e.response?.data?.detail || '上传失败'
      throw e
    }
  }

  function handleProgressEvent(event: ProgressEvent) {
    progress.value = event.progress
    currentStep.value = event.step
    error.value = event.error || null

    if (event.step === 'review') {
      stage.value = 'review'
    } else if (event.step === 'completed') {
      stage.value = 'preview'
    } else if (event.step === 'failed') {
      // Stay in current stage, show error
      error.value = event.error || '处理失败'
    }
  }

  async function skipReview() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.continue(currentTaskId.value)
      stage.value = 'generating'
      progress.value = 90
    } catch (e: any) {
      error.value = e.response?.data?.detail || '操作失败'
    }
  }

  async function submitAnnotations() {
    if (!currentTaskId.value) return
    error.value = null
    try {
      await tasksApi.bulkReextract(currentTaskId.value)
      stage.value = 'reprocessing'
    } catch (e: any) {
      error.value = e.response?.data?.detail || '提交失败'
    }
  }

  async function loadTaskState() {
    if (!currentTaskId.value) return
    try {
      const res = await tasksApi.get(currentTaskId.value)
      const task = res.data
      extractedData.value = (task as any).extracted_data || null
      progress.value = task.progress

      const statusMap: Record<string, AnalysisStage> = {
        review: 'review',
        generating: 'generating',
        reprocessing: 'reprocessing',
        completed: 'preview',
      }
      stage.value = statusMap[task.status] || 'processing'
    } catch {
      resetToUpload()
    }
  }

  function resetToUpload() {
    stage.value = 'upload'
    currentTaskId.value = null
    progress.value = 0
    currentStep.value = ''
    extractedData.value = null
    error.value = null
    localStorage.removeItem('current_task_id')
  }

  return {
    stage, currentTaskId, progress, currentStep, extractedData, error,
    startUpload, handleProgressEvent, skipReview, submitAnnotations,
    loadTaskState, resetToUpload,
  }
})
```

- [ ] **Step 6: Run tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/stores/__tests__/analysisStore.test.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/stores/analysisStore.ts web/src/api/tasks.ts web/src/api/files.ts web/src/stores/__tests__/analysisStore.test.ts
git commit -m "feat: add analysis store with state machine and file management API"
```

---

### Task 8: 创建 UploadStage 组件

**Files:**
- Create: `web/src/components/UploadStage.vue`
- Test: `web/src/components/__tests__/UploadStage.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/components/__tests__/UploadStage.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import UploadStage from '../UploadStage.vue'

vi.mock('../../stores/analysisStore', () => ({
  useAnalysisStore: vi.fn(() => ({
    startUpload: vi.fn(),
    error: null,
  })),
}))

describe('UploadStage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders upload area with drag-and-drop', () => {
    const wrapper = mount(UploadStage)
    expect(wrapper.text()).toContain('招标文件深度解析')
    expect(wrapper.text()).toContain('.doc / .docx / .pdf')
  })

  it('has a file input accepting correct types', () => {
    const wrapper = mount(UploadStage)
    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    expect(input.attributes('accept')).toBe('.doc,.docx,.pdf')
  })

  it('shows error message when present', async () => {
    const { useAnalysisStore } = await import('../../stores/analysisStore')
    vi.mocked(useAnalysisStore).mockReturnValue({
      startUpload: vi.fn(),
      error: '文件格式不支持',
    } as any)

    const wrapper = mount(UploadStage)
    expect(wrapper.text()).toContain('文件格式不支持')
  })
})
```

- [ ] **Step 2: Create UploadStage.vue**

```vue
<!-- web/src/components/UploadStage.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useAnalysisStore } from '../stores/analysisStore'

const store = useAnalysisStore()
const dragging = ref(false)
const uploading = ref(false)

function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadFile(file)
}

function onSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) uploadFile(file)
}

async function uploadFile(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!['doc', 'docx', 'pdf'].includes(ext || '')) {
    store.error = '仅支持 .doc / .docx / .pdf 文件'
    return
  }
  uploading.value = true
  try {
    await store.startUpload(file)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="text-center max-w-lg">
      <h1 class="text-xl font-semibold text-gray-800 mb-2">招标文件深度解析</h1>
      <p class="text-gray-500 text-sm mb-8">上传招标文件，AI智能解析生成分析报告</p>

      <div
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop.prevent="onDrop"
        :class="[
          'border-2 border-dashed rounded-xl p-12 transition-colors cursor-pointer bg-white',
          dragging ? 'border-purple-500 bg-purple-50' : 'border-gray-300 hover:border-gray-400',
        ]"
      >
        <div class="text-4xl mb-3">📄</div>
        <p class="text-gray-600 mb-1">拖拽文件到此处，或点击上传</p>
        <p class="text-gray-400 text-xs mb-4">支持 .doc / .docx / .pdf 格式</p>
        <label
          :class="[
            'inline-block px-6 py-2.5 rounded-lg text-white text-sm cursor-pointer transition-colors',
            uploading ? 'bg-purple-400' : 'bg-purple-600 hover:bg-purple-700',
          ]"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input type="file" class="hidden" accept=".doc,.docx,.pdf" @change="onSelect" :disabled="uploading" />
        </label>
      </div>

      <p v-if="store.error" class="text-red-500 text-sm mt-4">{{ store.error }}</p>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/UploadStage.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/components/UploadStage.vue web/src/components/__tests__/UploadStage.test.ts
git commit -m "feat: add UploadStage component for bid analysis workflow"
```

---

### Task 9: 创建 ProcessingStage 组件

**Files:**
- Create: `web/src/components/ProcessingStage.vue`
- Test: `web/src/components/__tests__/ProcessingStage.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/components/__tests__/ProcessingStage.test.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProcessingStage from '../ProcessingStage.vue'

describe('ProcessingStage', () => {
  it('renders progress bar', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 45, step: 'extracting', detail: '提取模块C', mode: 'processing' },
    })
    expect(wrapper.text()).toContain('test.docx')
    expect(wrapper.text()).toContain('45%')
  })

  it('shows step indicators', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 45, step: 'extracting', detail: '', mode: 'processing' },
    })
    expect(wrapper.text()).toContain('解析')
    expect(wrapper.text()).toContain('索引')
    expect(wrapper.text()).toContain('提取')
    expect(wrapper.text()).toContain('生成')
  })

  it('displays reprocessing mode text', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 50, step: 'reprocessing', detail: '重提取 module_a', mode: 'reprocessing' },
    })
    expect(wrapper.text()).toContain('重提取')
  })

  it('displays generating mode text', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: 95, step: 'generating', detail: '生成分析报告', mode: 'generating' },
    })
    expect(wrapper.text()).toContain('生成')
  })

  it('shows error message and retry button', () => {
    const wrapper = mount(ProcessingStage, {
      props: { filename: 'test.docx', progress: -1, step: 'failed', detail: '', mode: 'processing', error: 'API timeout' },
    })
    expect(wrapper.text()).toContain('API timeout')
  })
})
```

- [ ] **Step 2: Create ProcessingStage.vue**

```vue
<!-- web/src/components/ProcessingStage.vue -->
<script setup lang="ts">
const props = defineProps<{
  filename: string
  progress: number
  step: string
  detail: string
  mode: 'processing' | 'reprocessing' | 'generating'
  error?: string | null
}>()

const emit = defineEmits<{
  retry: []
}>()

const steps = [
  { key: 'parsing', label: '解析' },
  { key: 'indexing', label: '索引' },
  { key: 'extracting', label: '提取' },
  { key: 'generating', label: '生成' },
]

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

<template>
  <div class="flex flex-col items-center justify-center min-h-[60vh] px-6">
    <div class="w-full max-w-lg bg-white rounded-xl border border-gray-200 p-6">
      <!-- Header -->
      <div class="flex items-center gap-2 mb-4">
        <span class="text-sm text-gray-800">📄 {{ filename }}</span>
        <span class="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700">{{ modeLabels[mode] }}</span>
      </div>

      <!-- Progress bar -->
      <div class="bg-gray-200 rounded-full h-2 mb-2">
        <div
          class="bg-gradient-to-r from-purple-600 to-purple-400 h-full rounded-full transition-all duration-300"
          :style="{ width: `${Math.max(0, progress)}%` }"
        />
      </div>

      <div class="flex justify-between text-xs text-gray-400 mb-4">
        <span>{{ detail || step }}</span>
        <span>{{ Math.max(0, progress) }}%</span>
      </div>

      <!-- Step indicators (processing mode only) -->
      <div v-if="mode === 'processing'" class="flex gap-2 mt-4">
        <div
          v-for="s in steps"
          :key="s.key"
          :class="[
            'text-xs px-3 py-1 rounded',
            stepStatus(s.key) === 'done' ? 'bg-green-100 text-green-700' :
            stepStatus(s.key) === 'active' ? 'bg-amber-100 text-amber-700' :
            'bg-gray-100 text-gray-400'
          ]"
        >
          {{ stepStatus(s.key) === 'done' ? '✓' : stepStatus(s.key) === 'active' ? '⟳' : '○' }}
          {{ s.label }}
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" class="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
        <p class="text-sm text-red-600">{{ error }}</p>
        <button
          class="mt-2 text-sm text-red-600 underline hover:text-red-800"
          @click="emit('retry')"
        >
          重试
        </button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/ProcessingStage.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/components/ProcessingStage.vue web/src/components/__tests__/ProcessingStage.test.ts
git commit -m "feat: add ProcessingStage component with progress bar and step indicators"
```

---

### Task 10: 创建 ReviewStage 组件

**Files:**
- Create: `web/src/components/ReviewStage.vue`
- Test: `web/src/components/__tests__/ReviewStage.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/components/__tests__/ReviewStage.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReviewStage from '../ReviewStage.vue'

const mockExtracted = {
  schema_version: '1.0',
  modules: {
    module_a: {
      sections: [{ id: 's1', title: '基本信息', rows: [{ label: '项目名称', value: '测试项目' }] }],
    },
    module_b: {
      sections: [{ id: 's2', title: '资格要求', rows: [{ label: '要求1', value: '具有独立法人资格' }] }],
    },
  },
}

const mockParagraphs = [
  { index: 0, text: '一、项目简介', style: 'heading1' },
  { index: 1, text: '项目名称：测试项目', style: 'body' },
]

describe('ReviewStage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders module tabs', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('基本信息')
    expect(wrapper.text()).toContain('资格要求')
  })

  it('renders table data for active module', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('项目名称')
    expect(wrapper.text()).toContain('测试项目')
  })

  it('shows original text in left panel', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('一、项目简介')
  })

  it('has skip and submit buttons', () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    expect(wrapper.text()).toContain('跳过人工审核')
    expect(wrapper.text()).toContain('提交修改')
  })

  it('emits skip event', async () => {
    const wrapper = mount(ReviewStage, {
      props: { extractedData: mockExtracted, paragraphs: mockParagraphs, annotations: [], taskId: 'task-1' },
    })
    await wrapper.find('[data-testid="skip-review"]').trigger('click')
    expect(wrapper.emitted('skip')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Create ReviewStage.vue**

```vue
<!-- web/src/components/ReviewStage.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Annotation } from '../types/annotation'

const props = defineProps<{
  extractedData: Record<string, any>
  paragraphs: Array<{ index: number; text: string; style: string }>
  annotations: Annotation[]
  taskId: string
}>()

const emit = defineEmits<{
  skip: []
  submit: []
  addAnnotation: [moduleKey: string, content: string]
  removeAnnotation: [annId: number]
}>()

const moduleKeys = computed(() => Object.keys(props.extractedData?.modules || {}))
const activeModule = ref(moduleKeys.value[0] || '')
const showAnnotationInput = ref<string | null>(null)
const annotationText = ref('')

const MODULE_LABELS: Record<string, string> = {
  module_a: 'A 基本信息', module_b: 'B 资格要求', module_c: 'C 评标办法',
  module_d: 'D 废标条款', module_e: 'E 投标要求', module_f: 'F 合同条款',
  module_g: 'G 其他', bid_format: '投标文件格式', checklist: '资料清单',
}

const currentModuleData = computed(() => {
  return props.extractedData?.modules?.[activeModule.value] || {}
})

const moduleAnnotations = computed(() => {
  return props.annotations.filter(a => a.module_key === activeModule.value && a.status === 'pending')
})

const pendingCount = computed(() => {
  return props.annotations.filter(a => a.status === 'pending').length
})

function hasAnnotations(key: string) {
  return props.annotations.some(a => a.module_key === key && a.status === 'pending')
}

function startAnnotation(moduleKey: string) {
  showAnnotationInput.value = moduleKey
  annotationText.value = ''
}

function submitAnnotation() {
  if (annotationText.value.trim() && showAnnotationInput.value) {
    emit('addAnnotation', showAnnotationInput.value, annotationText.value.trim())
    annotationText.value = ''
    showAnnotationInput.value = null
  }
}
</script>

<template>
  <div class="flex h-full">
    <!-- Left panel: original text (1/3) -->
    <div class="w-1/3 border-r border-gray-200 bg-gray-50 flex flex-col">
      <div class="px-3 py-2.5 border-b border-gray-200 bg-white text-sm font-medium text-gray-500">
        📄 招标原文
      </div>
      <div class="flex-1 overflow-y-auto p-3 text-sm text-gray-600 leading-relaxed">
        <p
          v-for="p in paragraphs"
          :key="p.index"
          :class="p.style?.includes('heading') ? 'font-semibold text-gray-800 mt-3 mb-1' : 'mb-1 text-gray-500'"
        >
          {{ p.text }}
        </p>
      </div>
    </div>

    <!-- Right panel: extracted data (2/3) -->
    <div class="flex-1 flex flex-col">
      <!-- Module tabs -->
      <div class="flex border-b border-gray-200 bg-white overflow-x-auto">
        <button
          v-for="key in moduleKeys"
          :key="key"
          @click="activeModule = key"
          :class="[
            'px-4 py-2.5 text-sm whitespace-nowrap relative transition-colors',
            activeModule === key
              ? 'border-b-2 border-purple-600 text-purple-700 font-medium'
              : 'text-gray-400 hover:text-gray-600'
          ]"
        >
          {{ MODULE_LABELS[key] || key }}
          <span
            v-if="hasAnnotations(key)"
            class="absolute top-1.5 right-1 w-1.5 h-1.5 bg-amber-500 rounded-full"
          />
        </button>
      </div>

      <!-- Content area -->
      <div class="flex-1 overflow-y-auto p-4 bg-gray-50">
        <!-- Module table -->
        <div
          :class="[
            'bg-white rounded-lg overflow-hidden mb-4',
            moduleAnnotations.length > 0
              ? 'border border-amber-400 shadow-sm'
              : 'border border-gray-200'
          ]"
        >
          <!-- Table header for annotated modules -->
          <div
            v-if="moduleAnnotations.length > 0"
            class="px-3 py-2 bg-amber-50 flex items-center justify-between"
          >
            <span class="text-sm font-medium text-amber-800">
              📋 {{ MODULE_LABELS[activeModule] || activeModule }}
            </span>
            <span class="text-xs bg-amber-500 text-white px-2 py-0.5 rounded-full">
              {{ moduleAnnotations.length }}条批注
            </span>
          </div>

          <!-- Table content -->
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50">
                <th class="px-3 py-2 text-left text-gray-500 font-medium border-b border-gray-200 w-[30%]">字段</th>
                <th class="px-3 py-2 text-left text-gray-500 font-medium border-b border-gray-200">内容</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="currentModuleData?.sections">
                <template v-for="section in currentModuleData.sections" :key="section.id">
                  <tr v-for="(row, ri) in (section.rows || [])" :key="ri" class="border-b border-gray-100">
                    <td class="px-3 py-2 text-gray-700 font-medium">{{ row.label || row.key || '' }}</td>
                    <td class="px-3 py-2 text-gray-600">{{ row.value || '' }}</td>
                  </tr>
                </template>
              </template>
              <!-- Fallback: render as key-value if no sections -->
              <template v-else>
                <tr v-for="(value, key) in currentModuleData" :key="key" class="border-b border-gray-100">
                  <td class="px-3 py-2 text-gray-700 font-medium">{{ key }}</td>
                  <td class="px-3 py-2 text-gray-600">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Annotations for this module -->
          <div v-if="moduleAnnotations.length > 0" class="border-t border-amber-200 bg-amber-50 p-3">
            <div
              v-for="ann in moduleAnnotations"
              :key="ann.id"
              class="flex gap-2 items-start mb-2 last:mb-0"
            >
              <div class="w-5 h-5 bg-amber-500 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0 mt-0.5">
                {{ ann.user_id }}
              </div>
              <div class="flex-1">
                <div class="text-xs text-amber-700">{{ ann.created_at }}</div>
                <div class="text-sm text-amber-900">{{ ann.content }}</div>
              </div>
              <button
                class="text-amber-600 hover:text-amber-800 text-sm"
                @click="emit('removeAnnotation', ann.id)"
              >✕</button>
            </div>
          </div>

          <!-- Annotation input -->
          <div v-if="showAnnotationInput === activeModule" class="border-t border-gray-200 p-3">
            <textarea
              v-model="annotationText"
              placeholder="输入修改意见..."
              class="w-full border border-gray-300 rounded-lg p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-purple-500"
              rows="3"
            />
            <div class="flex justify-end gap-2 mt-2">
              <button
                class="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700"
                @click="showAnnotationInput = null"
              >取消</button>
              <button
                class="px-3 py-1.5 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700"
                @click="submitAnnotation"
              >添加批注</button>
            </div>
          </div>

          <!-- Add annotation button -->
          <div class="border-t border-gray-200 p-2 flex justify-end">
            <button
              class="px-3 py-1.5 text-xs text-gray-500 border border-gray-300 rounded-md hover:bg-gray-50"
              @click="startAnnotation(activeModule)"
            >
              ✏️ {{ moduleAnnotations.length > 0 ? '追加批注' : '对此表批注' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Bottom action bar -->
      <div class="border-t border-gray-200 px-4 py-3 flex items-center justify-between bg-white">
        <span class="text-xs text-gray-400">
          共 {{ moduleKeys.length }} 个模块，{{ pendingCount }} 条待处理批注
        </span>
        <div class="flex gap-2">
          <button
            data-testid="skip-review"
            class="px-5 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
            @click="emit('skip')"
          >跳过人工审核</button>
          <button
            class="px-5 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-purple-300"
            :disabled="pendingCount === 0"
            @click="emit('submit')"
          >提交修改 ({{ pendingCount }}条批注)</button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/ReviewStage.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/components/ReviewStage.vue web/src/components/__tests__/ReviewStage.test.ts
git commit -m "feat: add ReviewStage component with module tabs and table-level annotations"
```

---

### Task 11: 创建 PreviewStage 组件

**Files:**
- Create: `web/src/components/PreviewStage.vue`
- Test: `web/src/components/__tests__/PreviewStage.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/components/__tests__/PreviewStage.test.ts
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import PreviewStage from '../PreviewStage.vue'

vi.mock('../../api/tasks', () => ({
  tasksApi: { get: vi.fn() },
}))

describe('PreviewStage', () => {
  it('renders three file tabs', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('分析报告')
    expect(wrapper.text()).toContain('投标文件格式')
    expect(wrapper.text()).toContain('资料清单')
  })

  it('has download and download-all buttons', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('下载当前')
    expect(wrapper.text()).toContain('全部下载')
  })

  it('has new analysis button', () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    expect(wrapper.text()).toContain('开始新的解读')
  })

  it('emits reset event on new analysis click', async () => {
    const wrapper = mount(PreviewStage, {
      props: { taskId: 'task-1', filename: 'test.docx' },
    })
    await wrapper.find('[data-testid="new-analysis"]').trigger('click')
    expect(wrapper.emitted('reset')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Create PreviewStage.vue**

```vue
<!-- web/src/components/PreviewStage.vue -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import client from '../api/client'

const props = defineProps<{
  taskId: string
  filename: string
}>()

const emit = defineEmits<{ reset: [] }>()

const tabs = [
  { key: 'report', label: '📊 分析报告', icon: '📊' },
  { key: 'format', label: '📐 投标文件格式', icon: '📐' },
  { key: 'checklist', label: '📋 资料清单', icon: '📋' },
]

const activeTab = ref('report')
const previewHtml = ref('')
const loading = ref(false)

watch(activeTab, loadPreview, { immediate: true })

async function loadPreview() {
  loading.value = true
  try {
    const res = await client.get(`/files/${activeTab.value}s/${props.taskId}/preview`)
    previewHtml.value = res.data.html || ''
  } catch {
    previewHtml.value = '<p class="text-gray-400">预览加载失败</p>'
  } finally {
    loading.value = false
  }
}

function downloadFile(fileType: string) {
  const link = document.createElement('a')
  link.href = `/api/tasks/${props.taskId}/download/${fileType}`
  link.download = ''
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function downloadAll() {
  for (const tab of tabs) {
    downloadFile(tab.key)
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tab bar -->
    <div class="flex border-b border-gray-200 bg-white">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        @click="activeTab = tab.key"
        :class="[
          'px-5 py-2.5 text-sm transition-colors',
          activeTab === tab.key
            ? 'border-b-2 border-emerald-500 text-emerald-600 font-medium'
            : 'text-gray-400 hover:text-gray-600'
        ]"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Preview area -->
    <div class="flex-1 overflow-auto p-6 bg-white">
      <div v-if="loading" class="text-center text-gray-400 py-12">加载中...</div>
      <div v-else class="prose max-w-none" v-html="previewHtml" />
    </div>

    <!-- Bottom bar -->
    <div class="border-t border-gray-200 px-4 py-3 flex items-center justify-between bg-white">
      <span class="text-xs text-gray-400">
        {{ filename }}
      </span>
      <div class="flex gap-2">
        <button
          class="px-4 py-2 text-sm border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
          @click="downloadFile(activeTab)"
        >⬇ 下载当前</button>
        <button
          class="px-4 py-2 text-sm bg-emerald-500 text-white rounded-lg hover:bg-emerald-600"
          @click="downloadAll"
        >⬇ 全部下载</button>
      </div>
    </div>

    <!-- New analysis -->
    <div class="px-4 pb-3 flex justify-end bg-white">
      <button
        data-testid="new-analysis"
        class="text-sm text-gray-500 hover:text-gray-700"
        @click="emit('reset')"
      >
        开始新的解读 →
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/components/__tests__/PreviewStage.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/components/PreviewStage.vue web/src/components/__tests__/PreviewStage.test.ts
git commit -m "feat: add PreviewStage component with tab switching and download buttons"
```

---

### Task 12: 创建 BidAnalysisView 主视图

**Files:**
- Create: `web/src/views/BidAnalysisView.vue`
- Test: `web/src/views/__tests__/BidAnalysisView.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/views/__tests__/BidAnalysisView.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BidAnalysisView from '../BidAnalysisView.vue'

vi.mock('../../api/tasks', () => ({
  tasksApi: {
    upload: vi.fn(),
    get: vi.fn().mockResolvedValue({ data: { id: 'task-1', status: 'pending' } }),
    parsed: vi.fn().mockResolvedValue({ data: { paragraphs: [] } }),
    continue: vi.fn(),
    bulkReextract: vi.fn(),
  },
}))

vi.mock('../../api/annotations', () => ({
  annotationsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}))

describe('BidAnalysisView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('shows upload stage by default', () => {
    const wrapper = mount(BidAnalysisView)
    expect(wrapper.text()).toContain('招标文件深度解析')
  })

  it('transitions to processing stage', async () => {
    const wrapper = mount(BidAnalysisView)
    const { useAnalysisStore } = await import('../../stores/analysisStore')
    const store = useAnalysisStore()
    store.stage = 'processing'
    store.currentTaskId = 'task-1'
    await wrapper.vm.$nextTick()
    // ProcessingStage should be rendered
    expect(wrapper.findComponent({ name: 'ProcessingStage' }).exists() || wrapper.text().includes('解析中')).toBe(true)
  })
})
```

- [ ] **Step 2: Create BidAnalysisView.vue**

```vue
<!-- web/src/views/BidAnalysisView.vue -->
<script setup lang="ts">
import { onMounted, watch, ref } from 'vue'
import { useAnalysisStore } from '../stores/analysisStore'
import { useSSE } from '../composables/useSSE'
import { useAnnotation } from '../composables/useAnnotation'
import { tasksApi } from '../api/tasks'
import UploadStage from '../components/UploadStage.vue'
import ProcessingStage from '../components/ProcessingStage.vue'
import ReviewStage from '../components/ReviewStage.vue'
import PreviewStage from '../components/PreviewStage.vue'

const store = useAnalysisStore()
const paragraphs = ref<Array<{ index: number; text: string; style: string }>>([])
const filename = ref('')

let sseInstance: ReturnType<typeof useSSE> | null = null

// Restore state on mount
onMounted(async () => {
  if (store.currentTaskId) {
    await store.loadTaskState()
    if (store.currentTaskId) {
      await loadTaskDetails()
      if (['processing', 'generating', 'reprocessing'].includes(store.stage)) {
        connectSSE()
      }
    }
  }
})

async function loadTaskDetails() {
  if (!store.currentTaskId) return
  try {
    const res = await tasksApi.get(store.currentTaskId)
    filename.value = res.data.filename
    store.extractedData = (res.data as any).extracted_data || null
  } catch {
    // ignore
  }
}

function connectSSE() {
  if (!store.currentTaskId) return
  if (sseInstance) sseInstance.disconnect()

  sseInstance = useSSE(store.currentTaskId)
  watch(() => sseInstance!.progress.value, (event) => {
    if (event) {
      store.handleProgressEvent(event)

      // When entering review, load additional data
      if (event.step === 'review') {
        loadReviewData()
      }
    }
  })
  sseInstance.connect()
}

async function loadReviewData() {
  if (!store.currentTaskId) return
  try {
    const [taskRes, parsedRes] = await Promise.all([
      tasksApi.get(store.currentTaskId),
      tasksApi.parsed(store.currentTaskId),
    ])
    store.extractedData = (taskRes.data as any).extracted_data || null
    paragraphs.value = parsedRes.data.paragraphs
    filename.value = taskRes.data.filename
  } catch {
    // ignore
  }
}

// Watch stage changes to manage SSE connection
watch(() => store.stage, (newStage) => {
  if (['processing', 'generating', 'reprocessing'].includes(newStage)) {
    connectSSE()
  }
})

// Annotation composable (only used in review)
const annotationRef = ref<ReturnType<typeof useAnnotation> | null>(null)

watch(() => store.stage, async (stage) => {
  if (stage === 'review' && store.currentTaskId) {
    annotationRef.value = useAnnotation(store.currentTaskId)
    await annotationRef.value.load()
  }
})

async function handleAddAnnotation(moduleKey: string, content: string) {
  if (annotationRef.value) {
    await annotationRef.value.add(moduleKey, moduleKey, null, content)
  }
}

async function handleRemoveAnnotation(annId: number) {
  if (annotationRef.value) {
    await annotationRef.value.remove(annId)
  }
}

async function handleSkipReview() {
  await store.skipReview()
}

async function handleSubmitAnnotations() {
  await store.submitAnnotations()
}

function handleReset() {
  if (sseInstance) sseInstance.disconnect()
  store.resetToUpload()
}
</script>

<template>
  <div class="h-full">
    <!-- Upload stage -->
    <UploadStage v-if="store.stage === 'upload'" />

    <!-- Processing / Generating / Reprocessing stages -->
    <ProcessingStage
      v-else-if="['processing', 'generating', 'reprocessing'].includes(store.stage)"
      :filename="filename"
      :progress="store.progress"
      :step="store.currentStep"
      :detail="store.currentStep"
      :mode="store.stage as 'processing' | 'generating' | 'reprocessing'"
      :error="store.error"
      @retry="connectSSE"
    />

    <!-- Review stage -->
    <ReviewStage
      v-else-if="store.stage === 'review' && store.extractedData"
      :extracted-data="store.extractedData"
      :paragraphs="paragraphs"
      :annotations="annotationRef?.annotations.value || []"
      :task-id="store.currentTaskId!"
      @skip="handleSkipReview"
      @submit="handleSubmitAnnotations"
      @add-annotation="handleAddAnnotation"
      @remove-annotation="handleRemoveAnnotation"
    />

    <!-- Preview stage -->
    <PreviewStage
      v-else-if="store.stage === 'preview' && store.currentTaskId"
      :task-id="store.currentTaskId"
      :filename="filename"
      @reset="handleReset"
    />
  </div>
</template>
```

- [ ] **Step 3: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/views/__tests__/BidAnalysisView.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add web/src/views/BidAnalysisView.vue web/src/views/__tests__/BidAnalysisView.test.ts
git commit -m "feat: add BidAnalysisView with state machine driving 6 workflow stages"
```

---

## Chunk 4: 前端 — 文件管理视图 + 集成测试

### Task 13: 创建 FileManagerView 和 FilePreviewView

**Files:**
- Create: `web/src/views/FileManagerView.vue`
- Create: `web/src/views/FilePreviewView.vue`
- Create: `web/src/components/FileCard.vue`
- Test: `web/src/views/__tests__/FileManagerView.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
// web/src/views/__tests__/FileManagerView.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import FileManagerView from '../FileManagerView.vue'

vi.mock('../../api/files', () => ({
  filesApi: {
    list: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: '1', filename: '招标文件.docx', file_size: 1024, created_at: '2026-03-24', task_name: '招标文件' },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    }),
    delete: vi.fn().mockResolvedValue({}),
  },
}))

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/files/:fileType', component: FileManagerView, props: true },
    { path: '/files/:fileType/:id/preview', component: { template: '<div />' } },
  ],
})

describe('FileManagerView', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.push('/files/bid-documents')
    await router.isReady()
  })

  it('renders file list', async () => {
    const wrapper = mount(FileManagerView, {
      props: { fileType: 'bid-documents' },
      global: { plugins: [createPinia(), router] },
    })
    await new Promise(r => setTimeout(r, 100)) // wait for async load
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('招标文件')
  })

  it('renders search input', () => {
    const wrapper = mount(FileManagerView, {
      props: { fileType: 'bid-documents' },
      global: { plugins: [createPinia(), router] },
    })
    expect(wrapper.find('input[placeholder*="搜索"]').exists()).toBe(true)
  })
})
```

- [ ] **Step 2: Create FileCard.vue**

```vue
<!-- web/src/components/FileCard.vue -->
<script setup lang="ts">
import type { FileItem } from '../api/files'

defineProps<{
  file: FileItem
  fileType: string
  icon: string
}>()

const emit = defineEmits<{
  preview: [id: string | number]
  download: [id: string | number]
  delete: [id: string | number]
}>()

function formatSize(bytes: number | null) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div class="bg-white border border-gray-200 rounded-lg px-4 py-3.5 flex items-center gap-3 hover:shadow-sm transition-shadow">
    <div class="w-10 h-10 bg-purple-50 rounded-lg flex items-center justify-center text-lg flex-shrink-0">
      {{ icon }}
    </div>
    <div class="flex-1 min-w-0">
      <div class="text-sm font-medium text-gray-800 truncate">{{ file.filename }}</div>
      <div class="text-xs text-gray-400 mt-0.5">
        {{ formatSize(file.file_size) }} · {{ file.created_at }} · 来源任务: {{ file.task_name }}
      </div>
    </div>
    <div class="flex gap-1.5 flex-shrink-0">
      <button
        v-if="fileType !== 'bid-documents'"
        class="px-2.5 py-1.5 text-xs border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50"
        @click="emit('preview', file.id)"
      >👁 预览</button>
      <button
        class="px-2.5 py-1.5 text-xs border border-gray-300 rounded-md text-gray-500 hover:bg-gray-50"
        @click="emit('download', file.id)"
      >⬇ 下载</button>
      <button
        v-if="fileType !== 'bid-documents'"
        class="px-2.5 py-1.5 text-xs border border-red-200 rounded-md text-red-500 hover:bg-red-50"
        @click="emit('delete', file.id)"
      >🗑</button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Create FileManagerView.vue**

```vue
<!-- web/src/views/FileManagerView.vue -->
<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { filesApi, type FileItem } from '../api/files'
import FileCard from '../components/FileCard.vue'

const props = defineProps<{ fileType: string }>()
const router = useRouter()

const items = ref<FileItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const searchQuery = ref('')
const loading = ref(false)

const typeConfig: Record<string, { title: string; icon: string }> = {
  'bid-documents': { title: '招标文件', icon: '📁' },
  reports: { title: '解析报告', icon: '📊' },
  formats: { title: '文件格式', icon: '📐' },
  checklists: { title: '资料清单', icon: '📋' },
}

const config = computed(() => typeConfig[props.fileType] || { title: props.fileType, icon: '📄' })

async function loadFiles() {
  loading.value = true
  try {
    const res = await filesApi.list(props.fileType, {
      page: page.value,
      page_size: pageSize,
      q: searchQuery.value || undefined,
    })
    items.value = res.data.items
    total.value = res.data.total
  } catch {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

watch(() => props.fileType, () => { page.value = 1; loadFiles() })
watch(page, loadFiles)
onMounted(loadFiles)

let searchTimeout: ReturnType<typeof setTimeout>
function onSearch() {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => { page.value = 1; loadFiles() }, 300)
}

function handlePreview(id: string | number) {
  router.push(`/files/${props.fileType}/${id}/preview`)
}

async function handleDownload(id: string | number) {
  try {
    const res = await filesApi.download(props.fileType, id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // ignore
  }
}

async function handleDelete(id: string | number) {
  if (!confirm('确定删除此文件？')) return
  try {
    await filesApi.delete(props.fileType, id)
    await loadFiles()
  } catch {
    // ignore
  }
}

const totalPages = computed(() => Math.ceil(total.value / pageSize))
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <div class="px-6 py-4 bg-white border-b border-gray-200 flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold text-gray-800">{{ config.title }}</h1>
        <p class="text-xs text-gray-400 mt-0.5">共 {{ total }} 个文件</p>
      </div>
      <input
        v-model="searchQuery"
        @input="onSearch"
        class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-52"
        placeholder="🔍 搜索文件名..."
      />
    </div>

    <!-- File list -->
    <div class="flex-1 overflow-y-auto p-6">
      <div v-if="loading" class="text-center text-gray-400 py-12">加载中...</div>
      <div v-else-if="items.length === 0" class="text-center py-16">
        <div class="border border-dashed border-gray-300 rounded-lg p-8 text-gray-400 text-sm">
          暂无文件，请在「招标解读」中上传并完成解析
        </div>
      </div>
      <div v-else class="space-y-2.5">
        <FileCard
          v-for="file in items"
          :key="file.id"
          :file="file"
          :file-type="fileType"
          :icon="config.icon"
          @preview="handlePreview"
          @download="handleDownload"
          @delete="handleDelete"
        />
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="px-6 py-3 border-t border-gray-200 bg-white flex items-center justify-between">
      <span class="text-xs text-gray-400">显示 {{ (page - 1) * pageSize + 1 }}-{{ Math.min(page * pageSize, total) }} 共 {{ total }} 条</span>
      <div class="flex gap-1">
        <button
          class="px-2.5 py-1 text-xs border border-gray-300 rounded text-gray-500 disabled:opacity-50"
          :disabled="page <= 1"
          @click="page--"
        >上一页</button>
        <button
          v-for="p in totalPages"
          :key="p"
          :class="['px-2.5 py-1 text-xs rounded', p === page ? 'bg-purple-600 text-white' : 'border border-gray-300 text-gray-500']"
          @click="page = p"
        >{{ p }}</button>
        <button
          class="px-2.5 py-1 text-xs border border-gray-300 rounded text-gray-500 disabled:opacity-50"
          :disabled="page >= totalPages"
          @click="page++"
        >下一页</button>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Create FilePreviewView.vue**

```vue
<!-- web/src/views/FilePreviewView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { filesApi } from '../api/files'

const props = defineProps<{ fileType: string; id: string }>()
const router = useRouter()

const html = ref('')
const filename = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await filesApi.preview(props.fileType, props.id)
    html.value = res.data.html
    filename.value = res.data.filename
  } catch {
    html.value = '<p class="text-red-500">预览加载失败</p>'
  } finally {
    loading.value = false
  }
})

function goBack() {
  router.push(`/files/${props.fileType}`)
}

async function download() {
  try {
    const res = await filesApi.download(props.fileType, props.id)
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename.value
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    // ignore
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <div class="px-6 py-3 bg-white border-b border-gray-200 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button class="text-gray-400 hover:text-gray-600" @click="goBack">← 返回</button>
        <span class="text-sm text-gray-800 font-medium">{{ filename }}</span>
      </div>
      <button
        class="px-4 py-1.5 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700"
        @click="download"
      >⬇ 下载</button>
    </div>
    <div class="flex-1 overflow-auto p-8 bg-white">
      <div v-if="loading" class="text-center text-gray-400 py-12">加载中...</div>
      <div v-else class="prose max-w-none" v-html="html" />
    </div>
  </div>
</template>
```

- [ ] **Step 5: Run test**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run src/views/__tests__/FileManagerView.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/views/FileManagerView.vue web/src/views/FilePreviewView.vue web/src/components/FileCard.vue web/src/views/__tests__/FileManagerView.test.ts
git commit -m "feat: add FileManagerView with search, pagination, preview, and delete"
```

---

### Task 14: 清理旧文件 + 最终集成

**Files:**
- Delete: `web/src/layouts/DefaultLayout.vue`
- Delete: `web/src/views/DashboardView.vue`
- Delete: `web/src/views/TaskDetailView.vue`
- Delete: `web/src/components/TaskList.vue`
- Modify: `web/src/types/task.ts` (add extracted_data to Task type)

- [ ] **Step 1: Update Task type to include extracted_data**

In `web/src/types/task.ts`:

```typescript
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
}
```

- [ ] **Step 2: Delete old files**

```bash
rm web/src/layouts/DefaultLayout.vue
rm web/src/views/DashboardView.vue
rm web/src/views/TaskDetailView.vue
rm web/src/components/TaskList.vue
```

- [ ] **Step 3: Run all frontend tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npx vitest run`
Expected: All pass

- [ ] **Step 4: Build frontend to verify no compilation errors**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读/web && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Run all backend tests**

Run: `cd d:/BaiduSyncdisk/标书项目/招标文件解读 && python -m pytest server/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: complete frontend redesign — sidebar layout, bid analysis workflow, file management"
```

---

## 测试策略总结

### 后端测试（pytest + async SQLite）

| 测试文件 | 覆盖内容 | 测试数量 |
|---------|----------|---------|
| `test_pipeline_split.py` | pipeline 在 review 暂停, run_generate 完成 | 2 |
| `test_continue_and_reextract.py` | /continue, /parsed, /bulk-reextract 端点 | 5 |
| `test_sse_review.py` | SSE 对 review 状态的正确响应 | 1 |
| `test_files.py` | 文件列表、下载、删除、权限控制 | 5 |
| **新增小计** | | **13** |

### 前端测试（Vitest + @vue/test-utils）

| 测试文件 | 覆盖内容 | 测试数量 |
|---------|----------|---------|
| `AppSidebar.test.ts` | 导航项渲染、高亮、用户菜单 | 5 |
| `router.test.ts` | 路由配置验证 | 2 |
| `analysisStore.test.ts` | 状态机转换、localStorage 持久化 | 6 |
| `UploadStage.test.ts` | 上传区域渲染、文件类型校验 | 3 |
| `ProcessingStage.test.ts` | 进度条、步骤指示器、错误展示 | 5 |
| `ReviewStage.test.ts` | 模块 Tab、表格、批注、按钮 | 5 |
| `PreviewStage.test.ts` | 文件 Tab、下载按钮、重置 | 4 |
| `BidAnalysisView.test.ts` | 状态驱动视图切换 | 2 |
| `FileManagerView.test.ts` | 文件列表、搜索 | 2 |
| **新增小计** | | **34** |

### 总计新增测试: 47 个
