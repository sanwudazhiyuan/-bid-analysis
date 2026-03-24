"""Router for annotation CRUD on task sections."""
import uuid as _uuid_mod

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.annotation import Annotation
from server.app.schemas.annotation import AnnotationCreate, AnnotationResponse, AnnotationUpdate

router = APIRouter(prefix="/api/tasks", tags=["annotations"])


@router.post("/{task_id}/annotations", response_model=AnnotationResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation(
    task_id: str, body: AnnotationCreate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")
    ann = Annotation(
        task_id=task_uuid, user_id=user.id,
        module_key=body.module_key, section_id=body.section_id,
        row_index=body.row_index, annotation_type=body.annotation_type,
        content=body.content,
    )
    db.add(ann)
    await db.commit()
    await db.refresh(ann)
    return ann


@router.get("/{task_id}/annotations", response_model=list[AnnotationResponse])
async def list_annotations(
    task_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404)
    result = await db.execute(
        select(Annotation).where(Annotation.task_id == task_uuid).order_by(Annotation.created_at.desc())
    )
    return result.scalars().all()


@router.put("/{task_id}/annotations/{ann_id}", response_model=AnnotationResponse)
async def update_annotation(
    task_id: str, ann_id: int, body: AnnotationUpdate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Annotation).where(Annotation.id == ann_id, Annotation.user_id == user.id)
    )
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404)
    ann.content = body.content
    await db.commit()
    await db.refresh(ann)
    return ann


@router.delete("/{task_id}/annotations/{ann_id}", status_code=204)
async def delete_annotation(
    task_id: str, ann_id: int,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Annotation).where(Annotation.id == ann_id, Annotation.user_id == user.id)
    )
    ann = result.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404)
    await db.delete(ann)
    await db.commit()
