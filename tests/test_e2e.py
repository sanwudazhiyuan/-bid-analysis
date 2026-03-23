"""端到端集成测试 — 需要 API Key 才能运行"""

import os
import json
import pytest


@pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="需要 DASHSCOPE_API_KEY 环境变量",
)
class TestFullPipeline:
    """完整流程测试：解析 → 索引 → 提取 → 生成（跳过校对）"""

    def test_full_pipeline_docx(self, tmp_path):
        from src.parser.unified import parse_document
        from src.indexer.indexer import build_index
        from src.extractor.extractor import extract_all
        from src.config import load_settings
        from src.generator.report_gen import render_report
        from src.generator.format_gen import render_format
        from src.generator.checklist_gen import render_checklist

        # Use the actual bid document in the project root
        doc_path = "（8）20250530（拟发2）2025-2026年信用卡外包制递卡采购项目.doc"
        if not os.path.exists(doc_path):
            pytest.skip("测试文档不存在")

        # Layer 1: 解析
        paragraphs = parse_document(doc_path)
        assert len(paragraphs) > 50

        # Layer 2: 索引
        index_result = build_index(paragraphs)
        assert index_result["confidence"] > 0
        assert len(index_result["tagged_paragraphs"]) > 0

        # Layer 3: 提取
        settings = load_settings()
        extracted = extract_all(index_result["tagged_paragraphs"], settings)
        assert "modules" in extracted
        successful = [
            k for k, v in extracted["modules"].items()
            if v is not None
        ]
        assert len(successful) >= 7, f"仅 {len(successful)} 个模块成功: {successful}"

        # Layer 5: 生成（跳过 Layer 4 校对）
        report_path = str(tmp_path / "分析报告.docx")
        format_path = str(tmp_path / "投标文件格式.docx")
        checklist_path = str(tmp_path / "资料清单.docx")

        render_report(extracted, report_path)
        render_format(extracted, format_path)
        render_checklist(extracted, checklist_path)

        assert os.path.exists(report_path)
        assert os.path.exists(format_path)
        assert os.path.exists(checklist_path)

        # Verify files are valid docx (non-empty)
        assert os.path.getsize(report_path) > 1000
        assert os.path.getsize(format_path) > 1000
        assert os.path.getsize(checklist_path) > 1000


class TestPipelineWithoutAPI:
    """不需要 API Key 的管道测试 — 验证各层可正确串联"""

    def test_parse_and_index_pipeline(self, tmp_path):
        """解析 + 索引可以在无 API 情况下运行"""
        from src.parser.unified import parse_document
        from src.indexer.indexer import build_index
        from src.persistence import save_parsed, save_indexed, load_indexed

        # Find any test document
        test_docs_dir = "测试文档"
        if not os.path.exists(test_docs_dir):
            pytest.skip("测试文档目录不存在")

        docx_files = [f for f in os.listdir(test_docs_dir) if f.endswith(".docx")]
        if not docx_files:
            pytest.skip("无 .docx 测试文档")

        doc_path = os.path.join(test_docs_dir, docx_files[0])

        # Parse
        paragraphs = parse_document(doc_path)
        assert len(paragraphs) > 0

        # Save parsed
        parsed_path = str(tmp_path / "parsed.json")
        save_parsed(paragraphs, parsed_path)
        assert os.path.exists(parsed_path)

        # Index
        index_result = build_index(paragraphs)
        assert "tagged_paragraphs" in index_result
        assert "sections" in index_result

        # Save indexed
        indexed_path = str(tmp_path / "indexed.json")
        save_indexed(index_result, indexed_path)
        assert os.path.exists(indexed_path)

        # Load and verify roundtrip
        loaded = load_indexed(indexed_path)
        assert len(loaded["tagged_paragraphs"]) == len(index_result["tagged_paragraphs"])

    def test_generate_from_mock_data(self, tmp_path):
        """用模拟数据测试生成层"""
        from src.generator.report_gen import render_report
        from src.generator.format_gen import render_format
        from src.generator.checklist_gen import render_checklist

        mock_data = {
            "schema_version": "1.0",
            "modules": {
                "module_a": {
                    "title": "A. 项目概况",
                    "sections": [
                        {
                            "id": "A1",
                            "title": "基本信息",
                            "type": "key_value_table",
                            "columns": ["项目", "内容"],
                            "rows": [
                                ["项目名称", "E2E测试项目"],
                                ["采购编号", "E2E-001"],
                            ],
                        }
                    ],
                },
                "bid_format": {
                    "title": "投标文件格式",
                    "sections": [
                        {
                            "id": "BF1",
                            "title": "投标函",
                            "type": "template",
                            "content": "致：采购人\n根据贵方招标文件要求...",
                        }
                    ],
                },
                "checklist": {
                    "title": "资料清单",
                    "sections": [
                        {
                            "id": "CL1",
                            "title": "资格证明材料",
                            "type": "standard_table",
                            "columns": ["序号", "材料", "要求"],
                            "rows": [["1", "营业执照", "复印件"]],
                        }
                    ],
                },
            },
        }

        report_path = str(tmp_path / "report.docx")
        format_path = str(tmp_path / "format.docx")
        checklist_path = str(tmp_path / "checklist.docx")

        render_report(mock_data, report_path)
        render_format(mock_data, format_path)
        render_checklist(mock_data, checklist_path)

        assert os.path.exists(report_path)
        assert os.path.exists(format_path)
        assert os.path.exists(checklist_path)
