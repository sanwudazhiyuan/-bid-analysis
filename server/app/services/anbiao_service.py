"""Business logic for anbiao (anonymous bid) review tasks."""
import os
import shutil
import uuid as _uuid

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.config import settings
from server.app.models.anbiao_review import AnbiaoReview

ALLOWED_EXT = {ext.lower() for ext in settings.ALLOWED_EXTENSIONS}


async def create_anbiao_review(
    db: AsyncSession,
    tender_file: UploadFile,
    user_id: int,
    rule_file: UploadFile | None = None,
    use_default_rules: bool = True,
) -> AnbiaoReview:
    """Create an anbiao review task: save files, create DB record."""
    # Validate tender file
    tender_filename = tender_file.filename or "unknown"
    try:
        tender_filename = tender_filename.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    _, ext = os.path.splitext(tender_filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    tender_content = await tender_file.read()
    if len(tender_content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (500MB)")

    review_id = _uuid.uuid4()
    review_dir = os.path.join(settings.DATA_DIR, "anbiao_reviews", str(review_id))
    os.makedirs(review_dir, exist_ok=True)

    tender_path = os.path.join(review_dir, tender_filename)
    with open(tender_path, "wb") as f:
        f.write(tender_content)

    # Save rule file if provided
    rule_path = None
    rule_name = None
    if rule_file and rule_file.filename:
        rule_name = rule_file.filename
        try:
            rule_name = rule_name.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        _, rule_ext = os.path.splitext(rule_name)
        if rule_ext.lower() not in ALLOWED_EXT:
            raise HTTPException(status_code=400, detail=f"规则文件不支持的类型: {rule_ext}")
        rule_content = await rule_file.read()
        rule_path = os.path.join(review_dir, f"rules_{rule_name}")
        with open(rule_path, "wb") as f:
            f.write(rule_content)

    review = AnbiaoReview(
        id=review_id,
        user_id=user_id,
        tender_file_path=tender_path,
        tender_file_name=tender_filename,
        rule_file_path=rule_path,
        rule_file_name=rule_name,
        use_default_rules=use_default_rules,
        status="pending",
        progress=0,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def get_anbiao_reviews(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20, q: str | None = None
):
    base = select(AnbiaoReview).where(AnbiaoReview.user_id == user_id)
    if q:
        base = base.where(AnbiaoReview.tender_file_name.ilike(f"%{q}%"))
    base = base.order_by(AnbiaoReview.created_at.desc())

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0
    result = await db.execute(base.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()
    return items, total


async def get_anbiao_review(db: AsyncSession, review_id: str, user_id: int) -> AnbiaoReview | None:
    try:
        rid = _uuid.UUID(review_id)
    except ValueError:
        return None
    result = await db.execute(
        select(AnbiaoReview).where(AnbiaoReview.id == rid, AnbiaoReview.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_anbiao_review(db: AsyncSession, review_id: str, user_id: int):
    review = await get_anbiao_review(db, review_id, user_id)
    if not review:
        raise HTTPException(status_code=404, detail="暗标审查任务不存在")
    review_dir = os.path.dirname(review.tender_file_path)
    if os.path.isdir(review_dir):
        shutil.rmtree(review_dir, ignore_errors=True)
    await db.delete(review)
    await db.commit()