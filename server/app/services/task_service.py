"""Business logic for task creation from file uploads."""

import os
import uuid
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.task import Task

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}


async def create_task_from_upload(db: AsyncSession, file: UploadFile, user_id: int) -> Task:
    _, ext = os.path.splitext(file.filename or "")
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (50MB)")

    task_id = uuid.uuid4()
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", str(task_id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    task = Task(
        id=task_id,
        user_id=user_id,
        filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task
