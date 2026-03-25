# server/tests/test_files.py
"""Tests for file management API (/api/files)."""
import uuid
import pytest
import pytest_asyncio

from server.app.models.task import Task
from server.app.models.generated_file import GeneratedFile


@pytest_asyncio.fixture
async def completed_task(db_session, test_user, tmp_path):
    task_id = uuid.uuid4()
    task = Task(
        id=task_id, user_id=test_user.id, filename="招标文件.docx",
        file_path=str(tmp_path / "招标文件.docx"), file_size=1024,
        status="completed", progress=100,
    )
    (tmp_path / "招标文件.docx").write_text("dummy")
    db_session.add(task)

    # Add generated files
    for ftype in ("report", "format", "checklist"):
        fpath = tmp_path / f"test_{ftype}.docx"
        fpath.write_text("dummy docx content")
        gf = GeneratedFile(
            task_id=task_id, file_type=ftype,
            file_path=str(fpath), file_size=100,
        )
        db_session.add(gf)

    await db_session.commit()
    await db_session.refresh(task)
    return task


class TestFilesList:
    @pytest.mark.asyncio
    async def test_list_bid_documents(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=bid-documents", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["filename"] == "招标文件.docx"

    @pytest.mark.asyncio
    async def test_list_reports(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=reports", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_with_search(self, client, auth_headers, completed_task):
        resp = await client.get("/api/files?file_type=bid-documents&q=招标", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = await client.get("/api/files?file_type=bid-documents&q=不存在", headers=auth_headers)
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_requires_file_type(self, client, auth_headers):
        resp = await client.get("/api/files", headers=auth_headers)
        assert resp.status_code == 422  # missing required query param


class TestFilesDownload:
    @pytest.mark.asyncio
    async def test_download_generated(self, client, auth_headers, completed_task, db_session):
        from sqlalchemy import select
        result = await db_session.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == completed_task.id,
                GeneratedFile.file_type == "report",
            )
        )
        gf = result.scalar_one()
        resp = await client.get(f"/api/files/reports/{gf.id}/download", headers=auth_headers)
        assert resp.status_code == 200


class TestFilesDelete:
    @pytest.mark.asyncio
    async def test_delete_generated(self, client, auth_headers, completed_task, db_session):
        from sqlalchemy import select
        result = await db_session.execute(
            select(GeneratedFile).where(
                GeneratedFile.task_id == completed_task.id,
                GeneratedFile.file_type == "report",
            )
        )
        gf = result.scalar_one()
        resp = await client.delete(f"/api/files/reports/{gf.id}", headers=auth_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_bid_document_forbidden(self, client, auth_headers, completed_task):
        resp = await client.delete(
            f"/api/files/bid-documents/{completed_task.id}", headers=auth_headers
        )
        assert resp.status_code == 403
