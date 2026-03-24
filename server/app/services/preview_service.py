"""Preview service: fetch extracted data and manage checkbox state."""
import uuid as _uuid_mod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.models.task import Task


async def get_preview_data(db: AsyncSession, task_id: str, user_id: int) -> dict | None:
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(select(Task).where(Task.id == task_uuid, Task.user_id == user_id))
    task = result.scalar_one_or_none()
    if not task or not task.extracted_data:
        return None
    return {
        "extracted_data": task.extracted_data,
        "checkbox_data": task.checkbox_data or {},
    }


async def update_checkbox(
    db: AsyncSession, task_id: str, user_id: int,
    module_key: str, section_id: str, row_index: int, checked: bool,
) -> bool:
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        return False
    result = await db.execute(select(Task).where(Task.id == task_uuid, Task.user_id == user_id))
    task = result.scalar_one_or_none()
    if not task:
        return False
    cb = dict(task.checkbox_data or {})
    cb.setdefault(module_key, {}).setdefault(section_id, {})[str(row_index)] = checked
    task.checkbox_data = cb
    await db.commit()
    return True
