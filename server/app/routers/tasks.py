"""Router for task management — file upload and task listing."""

import asyncio
import json
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.schemas.task import TaskListResponse, TaskResponse
from server.app.services.task_service import (
    create_task_from_upload,
    delete_task,
    get_task,
    get_tasks,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await get_tasks(db, user.id, page, page_size, status)
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def upload_and_create_task(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await create_task_from_upload(db, file, user.id)

    # Lazy import avoids Redis connection errors when the module is loaded in
    # test environments that have no broker available.
    from server.app.tasks.pipeline_task import run_pipeline  # noqa: PLC0415

    celery_result = run_pipeline.delay(str(task.id))
    task.celery_task_id = celery_result.id
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}/progress")
async def task_progress(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint: stream Celery task progress from Redis.

    Returns immediately when celery_task_id is None (task not yet dispatched).
    Streams PROGRESS / SUCCESS / FAILURE states while the task is running.
    """
    import uuid as _uuid  # noqa: PLC0415
    from server.app.models.task import Task  # noqa: PLC0415

    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    celery_task_id = task.celery_task_id

    async def event_generator():
        if not celery_task_id:
            yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            return

        # Lazy imports keep Redis out of the module-load path so unit tests
        # that have no broker available can still import this module safely.
        from celery.result import AsyncResult  # noqa: PLC0415
        from server.app.tasks.celery_app import celery_app  # noqa: PLC0415

        while True:
            celery_result = AsyncResult(celery_task_id, app=celery_app)
            if celery_result.state == "PROGRESS":
                yield f"data: {json.dumps(celery_result.info)}\n\n"
            elif celery_result.state == "SUCCESS":
                yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                break
            elif celery_result.state == "FAILURE":
                yield (
                    f"data: {json.dumps({'progress': -1, 'step': 'failed', 'error': str(celery_result.result)})}\n\n"
                )
                break
            else:  # PENDING or STARTED or unknown
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_detail(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await get_task(db, task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/{task_id}", status_code=204)
async def remove_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_task(db, task_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


@router.post("/{task_id}/continue")
async def continue_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch run_generate for a task in review status."""
    from server.app.models.task import Task  # noqa: PLC0415

    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "review":
        raise HTTPException(status_code=409, detail=f"Task is not in review status (current: {task.status})")

    from server.app.tasks.generate_task import run_generate  # noqa: PLC0415

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
    """Return parsed paragraphs from disk."""
    from server.app.models.task import Task  # noqa: PLC0415

    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not task.parsed_path or not os.path.exists(task.parsed_path):
        raise HTTPException(status_code=404, detail="Parsed file not found")

    with open(task.parsed_path, "r", encoding="utf-8") as f:
        paragraphs = json.load(f)

    return {"paragraphs": paragraphs}


@router.post("/{task_id}/bulk-reextract")
async def bulk_reextract(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch run_bulk_reextract for modules with pending annotations."""
    from server.app.models.task import Task  # noqa: PLC0415
    from server.app.models.annotation import Annotation  # noqa: PLC0415

    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "review":
        raise HTTPException(status_code=409, detail=f"Task is not in review status (current: {task.status})")

    ann_result = await db.execute(
        select(Annotation).where(
            Annotation.task_id == task_uuid,
            Annotation.status == "pending",
        )
    )
    annotations = ann_result.scalars().all()

    if not annotations:
        raise HTTPException(status_code=400, detail="No pending annotations found")

    modules = list({ann.module_key for ann in annotations})

    from server.app.tasks.bulk_reextract_task import run_bulk_reextract  # noqa: PLC0415

    celery_result = run_bulk_reextract.delay(str(task.id))
    task.celery_task_id = celery_result.id
    task.status = "reprocessing"
    await db.commit()

    return {"task_id": str(task.id), "status": "reprocessing", "modules": modules}
