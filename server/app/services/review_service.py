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
    db: AsyncSession, tender_file: UploadFile, bid_task_id: str, user_id: int,
    review_mode: str = "fixed",
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
        review_mode=review_mode,
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
