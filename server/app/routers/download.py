"""Router for file download and document regeneration."""
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile

router = APIRouter(prefix="/api/tasks", tags=["download"])


@router.get("/{task_id}/download/{file_type}")
async def download_file(
    task_id: str, file_type: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if file_type not in ("report", "format", "checklist"):
        raise HTTPException(status_code=400, detail="Invalid file type")

    import uuid as _uuid_mod
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    task_result = await db.execute(select(Task).where(Task.id == task_uuid, Task.user_id == user.id))
    if not task_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(
        select(GeneratedFile).where(
            GeneratedFile.task_id == task_uuid, GeneratedFile.file_type == file_type,
        ).order_by(GeneratedFile.version.desc())
    )
    gf = result.scalar_one_or_none()
    if not gf or not os.path.exists(gf.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        gf.file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=os.path.basename(gf.file_path),
    )


@router.post("/{task_id}/regenerate")
async def regenerate_files(
    task_id: str,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """根据最新 extracted_data 重新生成三份 .docx"""
    import uuid as _uuid_mod
    try:
        task_uuid = _uuid_mod.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(select(Task).where(Task.id == task_uuid, Task.user_id == user.id))
    task = result.scalar_one_or_none()
    if not task or not task.extracted_data:
        raise HTTPException(status_code=404, detail="Task not found or no data")

    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from server.app.config import settings

    output_dir = os.path.join(settings.DATA_DIR, "output", str(task_id))
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(task.filename)[0]

    extracted = task.extracted_data
    paths = {
        "report": os.path.join(output_dir, f"{stem}_分析报告.docx"),
        "format": os.path.join(output_dir, f"{stem}_投标文件格式.docx"),
        "checklist": os.path.join(output_dir, f"{stem}_资料清单.docx"),
    }

    render_report(extracted, paths["report"])
    render_format(extracted, paths["format"])
    render_checklist(extracted, paths["checklist"])

    for ftype, fpath in paths.items():
        result = await db.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == task_uuid, GeneratedFile.file_type == ftype
            ).order_by(GeneratedFile.version.desc())
        )
        existing = result.scalar_one_or_none()
        new_version = (existing.version + 1) if existing else 1
        db.add(GeneratedFile(
            task_id=task_uuid, file_type=ftype, file_path=fpath,
            file_size=os.path.getsize(fpath), version=new_version,
        ))
    await db.commit()

    return {"status": "ok", "message": "文件已重新生成"}
