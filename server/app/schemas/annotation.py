"""Annotation request/response schemas."""
import datetime
import uuid
from pydantic import BaseModel, field_serializer


class AnnotationCreate(BaseModel):
    module_key: str
    section_id: str
    row_index: int | None = None
    annotation_type: str = "correction"
    content: str


class AnnotationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    task_id: uuid.UUID
    user_id: int
    module_key: str
    section_id: str
    row_index: int | None
    annotation_type: str
    content: str
    status: str
    llm_response: str | None
    created_at: datetime.datetime

    @field_serializer("task_id")
    def serialize_task_id(self, v: uuid.UUID) -> str:
        return str(v)


class AnnotationUpdate(BaseModel):
    content: str
