"""Tests for multi-file upload service functions."""
import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from server.app.services.task_service import (
    create_task_from_upload,
    add_file_to_pending_task,
    start_pending_task,
    get_pending_files,
    MAX_FILES_PER_TASK,
    _sanitize_filename,
)


@pytest.mark.asyncio
async def test_create_first_file_creates_task_and_taskfile():
    """Upload first file should create a pending Task and a TaskFile with is_primary=True."""
    mock_db = AsyncMock()
    mock_file = MagicMock()
    mock_file.filename = "test.docx"
    mock_file.read = AsyncMock(return_value=b"fake content")

    task = await create_task_from_upload(mock_db, mock_file, user_id=1)
    assert task.status == "pending"
    assert task.filename == "test.docx"
    # Should have called db.add twice: once for Task, once for TaskFile
    assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_add_file_exceeds_limit_raises():
    """Adding a 5th file should raise HTTPException."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.status = "pending"

    count_result = MagicMock()
    count_result.scalar.return_value = MAX_FILES_PER_TASK  # Already at limit

    mock_file = MagicMock()
    mock_file.filename = "fifth.docx"

    with patch("server.app.services.task_service._get_user_task", return_value=mock_task):
        mock_db.execute = AsyncMock(return_value=count_result)

        with pytest.raises(HTTPException) as exc_info:
            await add_file_to_pending_task(mock_db, str(task_id), mock_file, user_id=1)
        assert exc_info.value.status_code == 400
        assert "最多支持" in exc_info.value.detail


@pytest.mark.asyncio
async def test_add_file_to_non_pending_task_raises():
    """Adding file to non-pending task should raise HTTPException."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.status = "completed"

    mock_file = MagicMock()
    mock_file.filename = "extra.docx"

    with patch("server.app.services.task_service._get_user_task", return_value=mock_task):
        with pytest.raises(HTTPException) as exc_info:
            await add_file_to_pending_task(mock_db, str(task_id), mock_file, user_id=1)
        assert exc_info.value.status_code == 400
        assert "not in pending" in exc_info.value.detail


@pytest.mark.asyncio
async def test_start_pending_task_returns_task():
    """Confirm should return the task if it's pending with files."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.status = "pending"

    count_result = MagicMock()
    count_result.scalar.return_value = 2

    with patch("server.app.services.task_service._get_user_task", return_value=mock_task):
        mock_db.execute = AsyncMock(return_value=count_result)
        result = await start_pending_task(mock_db, str(task_id), user_id=1)
        assert result.status == "pending"


@pytest.mark.asyncio
async def test_start_pending_task_no_files_raises():
    """Confirm should raise if task has no files."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id
    mock_task.status = "pending"

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    with patch("server.app.services.task_service._get_user_task", return_value=mock_task):
        mock_db.execute = AsyncMock(return_value=count_result)

        with pytest.raises(HTTPException) as exc_info:
            await start_pending_task(mock_db, str(task_id), user_id=1)
        assert exc_info.value.status_code == 400
        assert "No files" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_pending_files_returns_list():
    """get_pending_files should return list of file info dicts."""
    mock_db = AsyncMock()
    task_id = uuid.uuid4()

    mock_task = MagicMock()
    mock_task.id = task_id

    mock_f1 = MagicMock()
    mock_f1.id = uuid.uuid4()
    mock_f1.filename = "main.docx"
    mock_f1.file_size = 1000
    mock_f1.is_primary = True
    mock_f1.sort_order = 0

    mock_f2 = MagicMock()
    mock_f2.id = uuid.uuid4()
    mock_f2.filename = "appendix.pdf"
    mock_f2.file_size = 2000
    mock_f2.is_primary = False
    mock_f2.sort_order = 1

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_f1, mock_f2]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    with patch("server.app.services.task_service._get_user_task", return_value=mock_task):
        mock_db.execute = AsyncMock(return_value=mock_result)
        files = await get_pending_files(mock_db, str(task_id), user_id=1)
        assert len(files) == 2
        assert files[0]["is_primary"] is True
        assert files[1]["is_primary"] is False


def test_sanitize_filename_chinese():
    """Chinese filenames encoded as latin-1 should be decoded correctly."""
    # Simulate a filename that was latin-1 encoded
    raw = "招标文件.docx".encode("utf-8").decode("latin-1")
    result = _sanitize_filename(raw)
    assert result == "招标文件.docx"


def test_sanitize_filename_already_utf8():
    """Already valid UTF-8 filenames should pass through unchanged."""
    result = _sanitize_filename("simple.docx")
    assert result == "simple.docx"
