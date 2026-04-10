"""Tests for folder_builder: generating tender file folder structure."""
import os

import pytest

from src.models import Paragraph
from src.reviewer.folder_builder import (
    _sanitize_filename,
    _build_leaf_md,
    _build_toc_md,
    build_tender_folder,
)


class TestSanitizeFilename:
    def test_normal_title(self):
        assert _sanitize_filename("投标函") == "投标函"

    def test_special_chars(self):
        assert _sanitize_filename("第一章/招标: 公告") == "第一章_招标_ 公告"

    def test_dots_preserved_in_numbers(self):
        assert _sanitize_filename("1.1 资格要求") == "1.1 资格要求"

    def test_empty_string(self):
        assert _sanitize_filename("") == "_"


class TestBuildLeafMd:
    def test_basic_paragraphs(self):
        paragraphs = [
            Paragraph(index=10, text="投标人应当具有独立法人资格"),
            Paragraph(index=11, text="投标人须提供营业执照"),
        ]
        md = _build_leaf_md("1.1 资格要求", paragraphs, {}, {})
        assert "# 1.1 资格要求" in md
        assert "[P10]" in md
        assert "[P11]" in md
        assert "投标人应当具有独立法人资格" in md

    def test_with_image_descriptions(self):
        paragraphs = [
            Paragraph(index=20, text="企业资质证明"),
        ]
        image_descs = {20: ["图片描述：营业执照，有效期2025-2030"]}
        md = _build_leaf_md("资质", paragraphs, image_descs, {})
        assert "[P20]" in md
        assert "> [图片描述] 图片描述：营业执照" in md

    def test_with_image_fallback(self):
        paragraphs = [
            Paragraph(index=20, text="企业资质证明"),
        ]
        image_files = {20: ["cert.png"]}
        md = _build_leaf_md("资质", paragraphs, {}, image_files, images_rel_prefix="images")
        assert "[P20]" in md
        assert "![图片](images/cert.png)" in md

    def test_with_both_description_and_files(self):
        paragraphs = [
            Paragraph(index=20, text="企业资质证明"),
        ]
        image_descs = {20: ["营业执照，有效期2025-2030"]}
        image_files = {20: ["cert.png"]}
        md = _build_leaf_md("资质", paragraphs, image_descs, image_files, images_rel_prefix="images")
        assert "[P20]" in md
        assert "> [图片描述] 营业执照" in md
        assert "![图片](images/cert.png)" in md
        # 描述在图片引用之前
        desc_pos = md.index("[图片描述]")
        img_pos = md.index("![图片]")
        assert desc_pos < img_pos

    def test_empty_paragraphs(self):
        md = _build_leaf_md("空章节", [], {}, {})
        assert "# 空章节" in md

    def test_table_rendering(self):
        paragraphs = [
            Paragraph(index=59, text="序号 | 内容 | 投标单价（元/张） | 备注", is_table=True, table_data=[
                ["序号", "内容", "投标单价（元/张）", "备注"],
                ["1", "借记国产80K芯片双界面IC卡", "1.80", "最高限价3.2元/张"],
                ["2", "个人化服务", "0.50", ""],
            ]),
        ]
        md = _build_leaf_md("报价一览表", paragraphs, {}, {})
        assert "[P59]" in md
        assert "**表格**" in md
        # 检查 Markdown 表格格式
        assert "| 序号 | 内容 | 投标单价（元/张） | 备注 |" in md
        assert "| --- | --- | --- | --- |" in md
        assert "| 1 | 借记国产80K芯片双界面IC卡 | 1.80 | 最高限价3.2元/张 |" in md
        assert "| 2 | 个人化服务 | 0.50 |  |" in md


class TestBuildTocMd:
    def test_basic_toc(self):
        chapters = [
            {
                "title": "第一章 投标函", "start_para": 0, "end_para": 14,
                "children": [], "level": 1,
            },
            {
                "title": "第二章 商务部分", "start_para": 15, "end_para": 50,
                "level": 1,
                "children": [
                    {"title": "2.1 企业资质", "start_para": 15, "end_para": 30,
                     "children": [], "level": 2},
                    {"title": "2.2 业绩证明", "start_para": 31, "end_para": 50,
                     "children": [], "level": 2},
                ],
            },
        ]
        md = _build_toc_md(chapters)
        assert "# 投标文件目录" in md
        assert "第一章 投标函" in md
        assert "2.1 企业资质" in md
        assert "P15-P30" in md


class TestBuildTenderFolder:
    def test_creates_folder_structure(self, tmp_path):
        paragraphs = [Paragraph(index=i, text=f"段落内容{i}") for i in range(20)]
        tender_index = {
            "chapters": [
                {
                    "title": "第一章 投标函", "level": 1,
                    "start_para": 0, "end_para": 9,
                    "children": [],
                },
                {
                    "title": "第二章 商务部分", "level": 1,
                    "start_para": 10, "end_para": 19,
                    "children": [
                        {"title": "2.1 企业资质", "level": 2,
                         "start_para": 10, "end_para": 14, "children": []},
                        {"title": "2.2 业绩证明", "level": 2,
                         "start_para": 15, "end_para": 19, "children": []},
                    ],
                },
            ],
        }
        output_dir = str(tmp_path / "tender_folder")

        build_tender_folder(paragraphs, tender_index, {}, {}, {}, [], output_dir)

        assert os.path.isfile(os.path.join(output_dir, "_目录.md"))
        assert os.path.isfile(os.path.join(output_dir, "第一章 投标函.md"))
        assert os.path.isdir(os.path.join(output_dir, "第二章 商务部分"))
        assert os.path.isfile(os.path.join(output_dir, "第二章 商务部分", "2.1 企业资质.md"))
        assert os.path.isfile(os.path.join(output_dir, "第二章 商务部分", "2.2 业绩证明.md"))

        with open(os.path.join(output_dir, "第一章 投标函.md"), encoding="utf-8") as f:
            content = f.read()
        assert "[P0]" in content
        assert "[P9]" in content
        assert "段落内容0" in content

    def test_with_images_and_descriptions(self, tmp_path):
        paragraphs = [Paragraph(index=0, text="资质证明")]
        tender_index = {
            "chapters": [
                {"title": "资质", "level": 1, "start_para": 0, "end_para": 0, "children": []},
            ],
        }
        # 创建假图片
        src_img_dir = tmp_path / "src_images"
        src_img_dir.mkdir()
        (src_img_dir / "cert.png").write_bytes(b"fake png")

        extracted_images = [
            {"filename": "cert.png", "near_para_index": 0, "path": str(src_img_dir / "cert.png")}
        ]
        image_descriptions = {"cert.png": "营业执照，统一社会信用代码：xxx"}
        image_para_map = {0: ["营业执照，统一社会信用代码：xxx"]}
        image_para_files = {0: ["cert.png"]}
        output_dir = str(tmp_path / "tender_folder")

        build_tender_folder(
            paragraphs, tender_index,
            image_descriptions, image_para_map, image_para_files,
            extracted_images, output_dir,
        )

        # 图片文件压缩后保留在 images/ 目录（fallback，扩展名统一为 .jpg）
        assert os.path.isfile(os.path.join(output_dir, "images", "cert.jpg"))

        with open(os.path.join(output_dir, "资质.md"), encoding="utf-8") as f:
            content = f.read()
        # 既有描述也有引用（文件名映射为 .jpg）
        assert "> [图片描述] 营业执照" in content
        assert "![图片](images/cert.jpg)" in content

    def test_parent_intro_paragraphs(self, tmp_path):
        """父节点有直属段落（不被子节点覆盖）时，应生成 _概述.md"""
        paragraphs = [Paragraph(index=i, text=f"段落{i}") for i in range(20)]
        tender_index = {
            "chapters": [
                {
                    "title": "第二章", "level": 1,
                    "start_para": 0, "end_para": 19,
                    "children": [
                        {"title": "2.1 子节点", "level": 2,
                         "start_para": 5, "end_para": 19, "children": []},
                    ],
                },
            ],
        }
        output_dir = str(tmp_path / "tender_folder")
        build_tender_folder(paragraphs, tender_index, {}, {}, {}, [], output_dir)

        intro_path = os.path.join(output_dir, "第二章", "_概述.md")
        assert os.path.isfile(intro_path)
        with open(intro_path, encoding="utf-8") as f:
            content = f.read()
        assert "[P0]" in content
        assert "[P4]" in content
