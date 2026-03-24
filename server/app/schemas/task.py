"""Pydantic schemas for Task responses."""

import datetime
import uuid
from pydantic import BaseModel


class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    filename: str
    file_size: int | None
    status: str
    current_step: str | None
    progress: int
    error_message: str | None
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    page_size: int
