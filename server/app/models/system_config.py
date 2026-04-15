"""SystemConfig ORM model — single-row table storing global model configuration."""

import datetime
from sqlalchemy import Integer, String, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from server.app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="cloud")  # "cloud" | "local"
    cloud_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    local_llm_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    local_embedding_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    local_haha_code_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)