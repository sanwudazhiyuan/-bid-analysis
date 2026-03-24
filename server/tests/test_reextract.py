"""Tests for re-extraction with annotations."""
import pytest
from unittest.mock import patch, MagicMock


def test_reextract_with_annotations_calls_llm():
    """Test that reextract_with_annotations builds correct prompt and calls LLM."""
    from src.extractor.base import reextract_with_annotations, ExtractError

    original_section = {
        "id": "A1", "title": "项目名称", "type": "key_value_table",
        "columns": ["项目", "内容"],
        "rows": [["项目名称", "测试项目"], ["预算", "100万"]],
    }
    annotations = [
        {"row_index": 1, "content": "预算应该是200万不是100万", "annotation_type": "correction"},
    ]

    mock_result = dict(original_section)
    mock_result["rows"] = [["项目名称", "测试项目"], ["预算", "200万"]]

    with patch("src.extractor.base.call_qwen", return_value=mock_result) as mock_call:
        result = reextract_with_annotations("module_a", "A1", original_section, [], annotations, {"api": {}})
        assert result["rows"][1][1] == "200万"
        mock_call.assert_called_once()
        # Verify the prompt includes the annotation content
        messages = mock_call.call_args[0][0]
        user_msg = messages[-1]["content"]
        assert "预算应该是200万" in user_msg
        assert "100万" in user_msg


def test_reextract_with_annotations_raises_on_none():
    """Test that ExtractError is raised when LLM returns None."""
    from src.extractor.base import reextract_with_annotations, ExtractError

    with patch("src.extractor.base.call_qwen", return_value=None):
        with pytest.raises(ExtractError, match="LLM 重提取失败"):
            reextract_with_annotations("module_a", "A1", {"rows": []}, [], [{"row_index": 0, "content": "fix"}])


@pytest.mark.asyncio
async def test_reextract_endpoint_returns_celery_id(client, test_user, auth_headers, db_session):
    """Test that the reextract endpoint dispatches a Celery task."""
    import sys
    import uuid
    from server.app.models.task import Task

    task = Task(
        id=uuid.uuid4(), user_id=test_user.id, filename="t.docx",
        file_path="/tmp/t.docx", file_size=100, status="completed",
        extracted_data={"modules": {"module_a": {"title": "A", "sections": []}}},
    )
    db_session.add(task)
    await db_session.commit()

    # Mock the reextract_task module (same pattern as pipeline_task mock)
    fake_task = MagicMock()
    fake_task.delay.return_value = MagicMock(id="fake-reextract-celery-id")
    fake_module = MagicMock()
    fake_module.reextract_section = fake_task
    sys.modules["server.app.tasks.reextract_task"] = fake_module
    try:
        resp = await client.post(
            f"/api/tasks/{task.id}/reextract",
            json={"module_key": "module_a", "section_id": "A1", "annotation_ids": [1, 2]},
            headers=auth_headers,
        )
    finally:
        sys.modules.pop("server.app.tasks.reextract_task", None)

    assert resp.status_code == 200
    assert resp.json()["celery_task_id"] == "fake-reextract-celery-id"
    fake_task.delay.assert_called_once()
