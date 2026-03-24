"""Router for preview data and checkbox management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.services.preview_service import get_preview_data, update_checkbox

router = APIRouter(prefix="/api/tasks", tags=["preview"])


class CheckboxUpdate(BaseModel):
    module_key: str
    section_id: str
    row_index: int
    checked: bool


@router.get("/{task_id}/preview")
async def preview(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await get_preview_data(db, task_id, user.id)
    if not data:
        raise HTTPException(status_code=404, detail="No preview data")
    return data


@router.put("/{task_id}/preview/checkbox")
async def toggle_checkbox(
    task_id: str,
    body: CheckboxUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await update_checkbox(
        db, task_id, user.id,
        body.module_key, body.section_id, body.row_index, body.checked,
    )
    if not ok:
        raise HTTPException(status_code=404)
    return {"status": "ok"}
