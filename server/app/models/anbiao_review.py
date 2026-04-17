"""AnbiaoReview ORM model for anonymous bid review."""
import datetime
import uuid as _uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class AnbiaoReview(Base):
    __tablename__ = "anbiao_reviews"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    rule_file_path: Mapped[str | None] = mapped_column(String(1000))
    rule_file_name: Mapped[str | None] = mapped_column(String(500))
    tender_file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    tender_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    use_default_rules: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(200))

    parsed_rules: Mapped[dict | None] = mapped_column(JSONB)
    format_results: Mapped[list | None] = mapped_column(JSONB)
    content_results: Mapped[list | None] = mapped_column(JSONB)
    review_summary: Mapped[dict | None] = mapped_column(JSONB)
    annotated_file_path: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    user = relationship("User")