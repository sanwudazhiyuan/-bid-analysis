"""Router for task management — file upload and task listing."""

from fastapi import APIRouter, Depends, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.schemas.task import TaskResponse
from server.app.services.task_service import create_task_from_upload

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
