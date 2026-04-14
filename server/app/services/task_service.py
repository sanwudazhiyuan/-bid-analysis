"""Business logic for task creation from file uploads."""

import os
import shutil
import uuid
from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
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

    # Also create TaskFile record for the primary file
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


async def remove_file_from_task(db: AsyncSession, task_id: str, file_id: str, user_id: int) -> dict:
    """从 pending Task 中删除一个文件。

    - 如果删除的是主文件且有其他文件 → 第2份晋升为主文件，更新 Task.file_path
    - 如果只剩这1份 → 删除整个 Task，返回 {"task_deleted": True}
    - 否则只删除 TaskFile 记录
    """
    task = await _get_user_task(db, task_id, user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "pending":
        raise HTTPException(status_code=400, detail="Task is not in pending status")

    file_uuid = uuid.UUID(file_id)
    result = await db.execute(select(TaskFile).where(TaskFile.id == file_uuid, TaskFile.task_id == task.id))
    tf = result.scalar_one_or_none()
    if not tf:
        raise HTTPException(status_code=404, detail="File not found")

    is_primary = tf.is_primary

    # Delete file from disk
    if tf.file_path and os.path.exists(tf.file_path):
        os.remove(tf.file_path)
    await db.delete(tf)
    await db.flush()

    if is_primary:
        # Promote the next file (sort_order=1 → becomes new primary)
        result = await db.execute(
            select(TaskFile)
            .where(TaskFile.task_id == task.id)
            .order_by(TaskFile.sort_order)
        )
        remaining = result.scalars().all()
        if not remaining:
            # No files left — delete the whole task
            for dir_prefix in ["uploads", "intermediate", "output"]:
                dir_path = os.path.join(settings.DATA_DIR, dir_prefix, str(task.id))
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
            await db.delete(task)
            await db.commit()
            return {"task_deleted": True}
        else:
            # Re-number sort_order and promote first remaining to primary
            for i, f in enumerate(remaining):
                f.sort_order = i
                f.is_primary = (i == 0)
                if i == 0:
                    task.filename = f.filename
                    task.file_path = f.file_path
                    task.file_size = f.file_size
            await db.commit()
            return {"task_deleted": False, "new_primary": remaining[0].filename}
    else:
        await db.commit()
        return {"task_deleted": False}


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
        select(Task).options(selectinload(Task.files)).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_tasks(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    q: str | None = None,
) -> tuple[list, int]:
    """Unchanged — list tasks with pagination."""
    query = select(Task).options(selectinload(Task.files)).where(Task.user_id == user_id).order_by(Task.created_at.desc())
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


async def get_task(db: AsyncSession, task_id: str, user_id: int) -> Task | None:
    """Unchanged."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).options(selectinload(Task.files)).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_task(db: AsyncSession, task_id: str, user_id: int) -> bool:
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
