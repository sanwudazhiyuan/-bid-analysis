"""ReviewTask ORM model for bid document review."""
import datetime
import uuid as _uuid

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    bid_task_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    tender_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    tender_file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    review_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(200))

    review_summary: Mapped[dict | None] = mapped_column(JSONB)
    review_items: Mapped[list | None] = mapped_column(JSONB)
    tender_index: Mapped[dict | None] = mapped_column(JSONB)

    annotated_file_path: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, onupdate=func.now())

    user = relationship("User")
    bid_task = relationship("Task")

    __table_args__ = (
        UniqueConstraint(
            "bid_task_id", "tender_filename", "version",
            name="uq_review_version",
        ),
    )
