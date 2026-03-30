"""Router for bid document review — create, list, detail, delete, progress, preview, download."""
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.database import get_db
from server.app.deps import get_current_user
from server.app.models.user import User
from server.app.services.review_service import (
    create_review, get_reviews, get_review, delete_review,
)

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    tender_file: UploadFile = File(...),
    bid_task_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_review(db, tender_file, bid_task_id, user.id)
    # TODO: dispatch run_review Celery task here (Task 9)
    return {"id": str(review.id), "status": review.status, "version": review.version}


@router.get("")
async def list_reviews_endpoint(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await get_reviews(db, user.id, page, page_size, q)
    # Eager-load bid_task for each item
    for r in items:
        await db.refresh(r, ["bid_task"])
    return {
        "items": [
            {
                "id": str(r.id),
                "bid_task_id": str(r.bid_task_id),
                "bid_filename": r.bid_task.filename if r.bid_task else "",
                "tender_filename": r.tender_filename,
                "version": r.version,
                "status": r.status,
                "review_summary": r.review_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{review_id}")
async def get_review_endpoint(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")
    # Eager-load bid_task for filename
    await db.refresh(review, ["bid_task"])
    return {
        "id": str(review.id),
        "bid_task_id": str(review.bid_task_id),
        "bid_filename": review.bid_task.filename if review.bid_task else "",
        "tender_filename": review.tender_filename,
        "version": review.version,
        "status": review.status,
        "progress": review.progress,
        "review_summary": review.review_summary,
        "review_items": review.review_items,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


@router.delete("/{review_id}", status_code=204)
async def delete_review_endpoint(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_review(db, review_id, user.id)


@router.get("/{review_id}/download")
async def download_review(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await get_review(db, review_id, user.id)
    if not review or not review.annotated_file_path or not os.path.exists(review.annotated_file_path):
        raise HTTPException(status_code=404, detail="审查报告不存在")
    return FileResponse(
        review.annotated_file_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"审查报告_{review.tender_filename}",
    )
