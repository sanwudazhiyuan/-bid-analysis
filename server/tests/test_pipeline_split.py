"""Tests for pipeline split: run_pipeline stops at review, run_generate completes."""
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

# Register SQLite type compilers for PG-specific types (UUID, JSONB) used in models
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):
    return "VARCHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


from server.app.models.task import Task  # noqa: E402


def _load_pipeline_task_with_sqlite():
    """Import pipeline_task module, replacing the DB engine with a sqlite one.

    The module runs `_sync_engine = create_engine(pg_url)` at import time.
    We ensure psycopg2 is not needed by first evicting the module from
    sys.modules and then patching settings.DATABASE_URL before re-importing.
    """
    sys.modules.pop("server.app.tasks.pipeline_task", None)
    mock_settings = MagicMock()
    mock_settings.DATABASE_URL = "sqlite:///:memory:"
    mock_settings.DATA_DIR = "/tmp"
    with patch("server.app.config.settings", mock_settings):
        import server.app.tasks.pipeline_task as mod
    return mod


def _load_generate_task_with_sqlite():
    """Same approach for generate_task."""
    sys.modules.pop("server.app.tasks.generate_task", None)
    mock_settings = MagicMock()
    mock_settings.DATABASE_URL = "sqlite:///:memory:"
    mock_settings.DATA_DIR = "/tmp"
    with patch("server.app.config.settings", mock_settings):
        import server.app.tasks.generate_task as mod
    return mod


@pytest.fixture
def mock_pipeline_deps():
    """Mock all external pipeline dependencies."""
    with (
        patch("src.parser.unified.parse_document") as mock_parse,
        patch("src.indexer.indexer.build_index") as mock_index,
        patch("src.extractor.extractor.extract_single_module") as mock_extract,
        patch("src.persistence.save_parsed") as mock_sp,
        patch("src.persistence.save_indexed") as mock_si,
        patch("src.persistence.save_extracted") as mock_se,
        patch("src.config.load_settings") as mock_settings,
    ):
        mock_parse.return_value = [{"index": 0, "text": "test", "style": "body"}]
        mock_index.return_value = {"tagged_paragraphs": [], "sections": [], "confidence": 0.9}
        mock_extract.return_value = {"sections": [{"id": "s1", "title": "test"}]}
        mock_settings.return_value = MagicMock()
        yield {"parse": mock_parse, "index": mock_index, "extract": mock_extract}


@pytest.fixture
def mock_generate_deps():
    """Mock all generation dependencies."""
    with (
        patch("src.generator.report_gen.render_report") as mock_report,
        patch("src.generator.format_gen.render_format") as mock_format,
        patch("src.generator.checklist_gen.render_checklist") as mock_checklist,
    ):
        def create_file(data, path):
            import os
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("dummy")
        mock_report.side_effect = create_file
        mock_format.side_effect = create_file
        mock_checklist.side_effect = create_file
        yield {"report": mock_report, "format": mock_format, "checklist": mock_checklist}


class TestPipelineSplit:
    """run_pipeline should stop at review status after extraction."""

    def test_pipeline_stops_at_review(self, tmp_path, mock_pipeline_deps):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from server.app.database import Base
        from server.app.models.task import Task
        from server.app.models.user import User
        from server.app.models.generated_file import GeneratedFile
        from server.app.security import hash_password

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        task_id = uuid.uuid4()
        with Session(engine) as db:
            user = User(username="test", password_hash=hash_password("pass"), role="user")
            db.add(user)
            db.flush()
            task = Task(id=task_id, user_id=user.id, filename="test.docx",
                       file_path=str(tmp_path / "test.docx"), status="pending")
            (tmp_path / "test.docx").write_text("dummy")
            db.add(task)
            db.commit()

        pipeline_mod = _load_pipeline_task_with_sqlite()
        with (
            patch.object(pipeline_mod, "_sync_engine", engine),
            patch.object(pipeline_mod, "settings") as mock_s,
            patch.object(pipeline_mod.run_pipeline, "update_state"),
        ):
            mock_s.DATA_DIR = str(tmp_path / "data")
            pipeline_mod.run_pipeline.__wrapped__(str(task_id))

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == "review"
            assert task.progress == 90
            assert task.extracted_data is not None
            result = db.execute(select(GeneratedFile).where(GeneratedFile.task_id == task_id))
            assert result.scalars().all() == []


class TestRunGenerate:
    """run_generate should produce 3 files and set status=completed."""

    def test_generate_completes(self, tmp_path, mock_generate_deps):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from server.app.database import Base
        from server.app.models.task import Task
        from server.app.models.user import User
        from server.app.models.generated_file import GeneratedFile
        from server.app.security import hash_password

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        task_id = uuid.uuid4()
        with Session(engine) as db:
            user = User(username="test", password_hash=hash_password("pass"), role="user")
            db.add(user)
            db.flush()
            task = Task(id=task_id, user_id=user.id, filename="test.docx",
                       file_path=str(tmp_path / "test.docx"), status="review", progress=90,
                       extracted_data={"schema_version": "1.0", "modules": {"module_a": {}}})
            db.add(task)
            db.commit()

        gen_mod = _load_generate_task_with_sqlite()
        with (
            patch.object(gen_mod, "_sync_engine", engine),
            patch.object(gen_mod, "settings") as mock_s,
            patch.object(gen_mod.run_generate, "update_state"),
        ):
            mock_s.DATA_DIR = str(tmp_path / "data")
            gen_mod.run_generate.__wrapped__(str(task_id))

        with Session(engine) as db:
            task = db.get(Task, task_id)
            assert task.status == "completed"
            assert task.progress == 100
            assert task.completed_at is not None
            result = db.execute(select(GeneratedFile).where(GeneratedFile.task_id == task_id))
            files = result.scalars().all()
            assert len(files) == 3
            types = {f.file_type for f in files}
            assert types == {"report", "format", "checklist"}
