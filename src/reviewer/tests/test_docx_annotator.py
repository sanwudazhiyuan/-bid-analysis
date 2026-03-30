"""Tests for docx annotation generator."""
import os
import tempfile
from docx import Document
from src.reviewer.docx_annotator import generate_review_docx


def _create_test_docx(path: str):
    """Create a minimal test docx file."""
    doc = Document()
    doc.add_paragraph("第一章 投标函")
    doc.add_paragraph("致采购人：我方承诺按照招标文件要求提交投标文件。")
    doc.add_paragraph("第二章 技术方案")
    doc.add_paragraph("本系统采用分布式架构，具有高可用性。")
    doc.save(path)


def test_generate_review_docx_creates_file():
    """generate_review_docx produces a valid docx file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "投标文件.docx")
        _create_test_docx(tender_path)

        review_items = [
            {
                "id": 0,
                "clause_index": 0,
                "source_module": "module_e",
                "clause_text": "投标文件须密封",
                "result": "fail",
                "confidence": 92,
                "reason": "未找到密封说明",
                "severity": "critical",
                "tender_locations": [{"chapter": "", "para_indices": [1], "text_snippet": ""}],
            }
        ]
        summary = {"total": 1, "pass": 0, "fail": 1, "warning": 0, "critical_fails": 1}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="招标文件.docx",
            output_dir=tmpdir,
        )

        assert os.path.exists(output_path)
        assert output_path.endswith(".docx")
        # Verify it's a valid docx
        doc = Document(output_path)
        assert len(doc.paragraphs) > 0


def test_generate_review_docx_has_summary_table():
    """Generated docx includes a summary table at the beginning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "test.docx")
        _create_test_docx(tender_path)

        review_items = [{
            "id": 0, "clause_index": 0, "source_module": "module_e", "clause_text": "条款1",
            "result": "pass", "confidence": 90, "reason": "符合要求",
            "severity": "critical", "tender_locations": [],
        }]
        summary = {"total": 1, "pass": 1, "fail": 0, "warning": 0, "critical_fails": 0}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="test.docx", output_dir=tmpdir,
        )
        doc = Document(output_path)
        # Should have at least 1 table (summary table)
        assert len(doc.tables) >= 1


def test_generate_review_docx_has_word_comments():
    """Generated docx contains Word native comments for fail/warning items."""
    from zipfile import ZipFile

    with tempfile.TemporaryDirectory() as tmpdir:
        tender_path = os.path.join(tmpdir, "投标文件.docx")
        _create_test_docx(tender_path)

        review_items = [
            {
                "id": 0, "clause_index": 0, "source_module": "module_e",
                "clause_text": "投标文件须密封", "result": "fail",
                "confidence": 92, "reason": "未找到密封说明",
                "severity": "critical",
                "tender_locations": [{"chapter": "", "para_indices": [1], "text_snippet": ""}],
            }
        ]
        summary = {"total": 1, "pass": 0, "fail": 1, "warning": 0, "critical_fails": 1}

        output_path = generate_review_docx(
            tender_path, review_items, summary,
            bid_filename="招标文件.docx", output_dir=tmpdir,
        )
        # Verify comments.xml exists in the docx zip
        with ZipFile(output_path) as z:
            assert "word/comments.xml" in z.namelist()
            comments_xml = z.read("word/comments.xml").decode("utf-8")
            assert "未找到密封说明" in comments_xml
