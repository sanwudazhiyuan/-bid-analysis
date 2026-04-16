"""Router for bid document review — create, list, detail, delete, progress, preview, download."""
import logging
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
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    tender_file: UploadFile = File(...),
    bid_task_id: str = Form(...),
    review_mode: str = Form("fixed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    review = await create_review(db, tender_file, bid_task_id, user.id, review_mode=review_mode)
    # 撤销当前用户所有进行中的 Celery 任务，避免与新任务互相干扰
    from server.app.services.celery_utils import revoke_user_active_tasks  # noqa: PLC0415
    revoked = revoke_user_active_tasks(user.id)
    logger.info("Revoked %d active Celery tasks for user %d before starting new review", revoked, user.id)
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
                "review_mode": r.review_mode,
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
        "review_mode": review.review_mode,
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


@router.get("/{review_id}/preview")
async def preview_review(
    review_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return HTML preview with data-review-id attributes on highlighted paragraphs."""
    review = await get_review(db, review_id, user.id)
    if not review or review.status != "completed":
        raise HTTPException(status_code=404, detail="审查结果不存在")

    summary = review.review_summary or {}

    # Prefer pre-rendered HTML written at review completion time.
    preview_path = summary.get("preview_html_path")
    tender_html: str | None = None
    if preview_path and os.path.exists(preview_path):
        try:
            with open(preview_path, "r", encoding="utf-8") as f:
                tender_html = f.read()
        except Exception:
            tender_html = None

    # Fallback: render on demand for reviews completed before this change.
    if tender_html is None:
        from server.app.services.review_preview import build_preview_html
        tender_html = build_preview_html(
            review.tender_file_path,
            review.review_items or [],
            summary.get("extracted_images", []),
            review_id,
        )

    return {
        "tender_html": tender_html,
        "review_items": review.review_items or [],
        "summary": summary,
    }


@router.get("/{review_id}/images/{filename}")
async def serve_review_image(
    review_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve an extracted image from a review task."""
    review = await get_review(db, review_id, user.id)
    if not review:
        raise HTTPException(status_code=404, detail="审查任务不存在")

    images_dir = os.path.join(os.path.dirname(review.tender_file_path), "images")
    image_path = os.path.join(images_dir, filename)

    # Security: ensure filename doesn't escape the images directory
    if not os.path.realpath(image_path).startswith(os.path.realpath(images_dir)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")

    content_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp",
    }.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")

    return FileResponse(image_path, media_type=content_type)
