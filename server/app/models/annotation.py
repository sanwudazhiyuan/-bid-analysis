"""Annotation ORM model."""

import datetime

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.app.database import Base


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    module_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(20), nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)
    annotation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    llm_response: Mapped[str | None] = mapped_column(Text)
    reextract_celery_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    task = relationship("Task", back_populates="annotations")
