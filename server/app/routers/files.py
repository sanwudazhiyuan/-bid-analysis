# server/app/routers/files.py
"""Router for file management — list, download, preview, delete."""
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile
from server.app.services.file_service import list_files, FILE_TYPE_MAP

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("")
async def list_files_endpoint(
    file_type: str = Query(..., description="bid-documents|reports|formats|checklists"),
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type not in FILE_TYPE_MAP:
        raise HTTPException(status_code=400, detail=f"Invalid file_type: {file_type}")
    items, total = await list_files(db, user.id, file_type, page, page_size, q)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{file_type}/{file_id}/download")
async def download_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type == "bid-documents":
        task = await _get_user_task(db, file_id, user.id)
        if not task or not os.path.exists(task.file_path):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(task.file_path, filename=task.filename)
    else:
        gf = await _get_user_generated_file(db, file_id, user.id)
        if not gf or not os.path.exists(gf.file_path):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(
            gf.file_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=os.path.basename(gf.file_path),
        )


@router.get("/{file_type}/{file_id}/preview")
async def preview_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return HTML preview of a generated .docx file."""
    if file_type == "bid-documents":
        raise HTTPException(status_code=501, detail="Preview not supported for uploaded files")

    gf = await _get_user_generated_file(db, file_id, user.id)
    if not gf or not os.path.exists(gf.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    from docx import Document
    doc = Document(gf.file_path)
    html_parts = []
    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        if "Heading" in style:
            level = style.replace("Heading ", "").strip() or "3"
            html_parts.append(f"<h{level}>{para.text}</h{level}>")
        else:
            html_parts.append(f"<p>{para.text}</p>")
    for table in doc.tables:
        html_parts.append("<table border='1' style='border-collapse:collapse;width:100%'>")
        for row in table.rows:
            html_parts.append("<tr>")
            for cell in row.cells:
                html_parts.append(f"<td style='padding:4px 8px'>{cell.text}</td>")
            html_parts.append("</tr>")
        html_parts.append("</table>")

    return {"html": "\n".join(html_parts), "filename": os.path.basename(gf.file_path)}


@router.delete("/{file_type}/{file_id}", status_code=204)
async def delete_file(
    file_type: str, file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file_type == "bid-documents":
        raise HTTPException(status_code=403, detail="Cannot delete uploaded bid documents directly")

    gf = await _get_user_generated_file(db, file_id, user.id)
    if not gf:
        raise HTTPException(status_code=404, detail="File not found")

    if os.path.exists(gf.file_path):
        os.remove(gf.file_path)
    await db.delete(gf)
    await db.commit()


async def _get_user_task(db: AsyncSession, task_id: str, user_id: int):
    import uuid as _uuid
    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        return None
    result = await db.execute(
        select(Task).where(Task.id == task_uuid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_user_generated_file(db: AsyncSession, file_id: str, user_id: int):
    try:
        fid = int(file_id)
    except ValueError:
        return None
    result = await db.execute(
        select(GeneratedFile)
        .join(Task, GeneratedFile.task_id == Task.id)
        .where(GeneratedFile.id == fid, Task.user_id == user_id)
    )
    return result.scalar_one_or_none()
