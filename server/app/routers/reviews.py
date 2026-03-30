"""Router for bid document review — create, list, detail, delete, progress, preview, download."""
import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse, StreamingResponse
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
    # Dispatch Celery task
    from server.app.tasks.review_task import run_review
    celery_result = run_review.delay(str(review.id))
    review.celery_task_id = celery_result.id
    await db.commit()
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


@router.get("/{review_id}/progress")
async def review_progress(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for review task progress."""
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    celery_task_id = review.celery_task_id

    async def event_generator():
        nonlocal celery_task_id
        from celery.result import AsyncResult
        import asyncio
        import json

        while True:
            if not celery_task_id:
                yield f"data: {json.dumps({'progress': 0, 'step': 'pending'})}\n\n"
                await asyncio.sleep(2)
                await db.refresh(review)
                celery_task_id = review.celery_task_id
                continue

            result = AsyncResult(celery_task_id)
            if result.state == "PROGRESS":
                meta = result.info or {}
                yield f"data: {json.dumps(meta)}\n\n"
            elif result.state == "SUCCESS":
                await db.refresh(review)
                if review.status == "completed":
                    yield f"data: {json.dumps({'progress': 100, 'step': 'completed'})}\n\n"
                    return
                elif review.status == "failed":
                    yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': review.error_message})}\n\n"
                    return
            elif result.state == "FAILURE":
                yield f"data: {json.dumps({'progress': 0, 'step': 'failed', 'error': str(result.info)})}\n\n"
                return

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
