import uuid
import pytest
from server.app.models.review_task import ReviewTask


def test_review_task_fields():
    """ReviewTask has all required fields."""
    rt = ReviewTask(
        id=uuid.uuid4(),
        user_id=1,
        bid_task_id=uuid.uuid4(),
        tender_filename="投标文件.docx",
        tender_file_path="/data/reviews/test/投标文件.docx",
        version=1,
        status="pending",
        progress=0,
    )
    assert rt.status == "pending"
    assert rt.version == 1
    assert rt.review_summary is None
    assert rt.review_items is None
    assert rt.annotated_file_path is None


def test_review_task_default_values():
    """Optional fields default to None."""
    rt = ReviewTask(
        id=uuid.uuid4(),
        user_id=1,
        bid_task_id=uuid.uuid4(),
        tender_filename="test.docx",
        tender_file_path="/tmp/test.docx",
        version=1,
        status="pending",
        progress=0,
    )
    assert rt.current_step is None
    assert rt.error_message is None
    assert rt.celery_task_id is None
    assert rt.tender_index is None
