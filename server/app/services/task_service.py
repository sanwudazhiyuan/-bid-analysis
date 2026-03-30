"""Business logic for task creation from file uploads."""

import os
import shutil
import uuid
from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.task import Task

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}


async def create_task_from_upload(db: AsyncSession, file: UploadFile, user_id: int) -> Task:
    # Ensure filename is properly decoded (handle latin-1 encoded Chinese filenames)
    filename = file.filename or ""
    try:
        filename = filename.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass  # already valid UTF-8
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    task_id = uuid.uuid4()
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", str(task_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as f:
        f.write(content)

    task = Task(
        id=task_id,
        user_id=user_id,
        filename=filename,
        file_path=file_path,
        file_size=len(content),
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_tasks(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> tuple[list, int]:
    query = select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc())
    count_query = select(func.count()).select_from(Task).where(Task.user_id == user_id)
    if status:
        query = query.where(Task.status == status)
        count_query = count_query.where(Task.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def get_task(db: AsyncSession, task_id: str, user_id: int) -> Task | None:
    import uuid as _uuid_mod  # noqa: PLC0415

    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_task(db: AsyncSession, task_id: str, user_id: int) -> bool:
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
