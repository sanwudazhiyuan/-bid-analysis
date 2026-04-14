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
    from server.app.models.task_file import TaskFile

    base = select(Task).where(Task.user_id == user_id)
    count_base = select(func.count()).select_from(Task).where(
        Task.user_id == user_id,
    )
    if q:
        base = base.where(Task.filename.ilike(f"%{q}%"))
        count_base = count_base.where(Task.filename.ilike(f"%{q}%"))

    total = (await db.execute(count_base)).scalar() or 0
    result = await db.execute(
        base.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    tasks = result.scalars().all()

    # Batch fetch file counts for all tasks
    task_ids = [t.id for t in tasks]
    file_counts = {}
    if task_ids:
        fc_result = await db.execute(
            select(TaskFile.task_id, func.count()).where(TaskFile.task_id.in_(task_ids)).group_by(TaskFile.task_id)
        )
        for tid, cnt in fc_result.all():
            file_counts[tid] = cnt

    items = [
        {
            "id": str(t.id), "filename": t.filename, "file_size": t.file_size,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "task_name": t.filename, "status": t.status,
            "file_count": file_counts.get(t.id, 1),
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
