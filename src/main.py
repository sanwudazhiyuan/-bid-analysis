"""招标文件分析工具 CLI 入口"""

import argparse
import sys
import os
from pathlib import Path


def cmd_analyze(args):
    """完整流程: 解析 → 索引 → 提取 → 校对 → 生成"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index
    from src.extractor.extractor import extract_all
    from src.config import load_settings
    from src.persistence import save_parsed, save_indexed, save_extracted, save_reviewed
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from src.logger import setup_logging

    logger = setup_logging("bid-analyzer")

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 — {file_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(file_path).stem

    # Layer 1: 解析
    logger.info("Layer 1: 解析文档 %s", file_path)
    paragraphs = parse_document(file_path)
    parsed_path = os.path.join(output_dir, f"{stem}_parsed.json")
    save_parsed(paragraphs, parsed_path)
    logger.info("解析完成: %d 段落 → %s", len(paragraphs), parsed_path)

    # Layer 2: 索引
    logger.info("Layer 2: 构建索引")
    index_result = build_index(paragraphs)
    indexed_path = os.path.join(output_dir, f"{stem}_indexed.json")
    save_indexed(index_result, indexed_path)
    logger.info("索引完成: 置信度=%.2f → %s", index_result["confidence"], indexed_path)

    # Layer 3: LLM 提取
    logger.info("Layer 3: LLM 结构化提取")
    settings = load_settings()
    extracted = extract_all(index_result["tagged_paragraphs"], settings)
    extracted_path = os.path.join(output_dir, f"{stem}_extracted.json")
    save_extracted(extracted, extracted_path)

    successful = sum(1 for v in extracted["modules"].values() if v is not None)
    logger.info("提取完成: %d/%d 模块成功 → %s", successful, len(extracted["modules"]), extracted_path)

    # Layer 4: 人工校对
    if not args.skip_review:
        from src.reviewer.cli_reviewer import review_all
        logger.info("Layer 4: 交互式校对")
        reviewed = review_all(extracted)
        reviewed_path = os.path.join(output_dir, f"{stem}_reviewed.json")
        save_reviewed(reviewed, reviewed_path)
        data_for_gen = reviewed
    else:
        logger.info("Layer 4: 跳过校对 (--skip-review)")
        data_for_gen = extracted

    # Layer 5: 生成文档
    logger.info("Layer 5: 生成 .docx 文档")
    render_report(data_for_gen, os.path.join(output_dir, f"{stem}_分析报告.docx"))
    render_format(data_for_gen, os.path.join(output_dir, f"{stem}_投标文件格式.docx"))
    render_checklist(data_for_gen, os.path.join(output_dir, f"{stem}_资料清单.docx"))

    logger.info("全部完成！输出目录: %s", output_dir)
    print(f"\n完成！输出目录: {output_dir}")


def cmd_parse(args):
    """仅解析 + 索引"""
    from src.parser.unified import parse_document
    from src.indexer.indexer import build_index
    from src.persistence import save_parsed, save_indexed
    from src.logger import setup_logging

    logger = setup_logging("bid-analyzer")

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 — {file_path}", file=sys.stderr)
        sys.exit(1)

    stem = Path(file_path).stem
    output = args.output or f"output/{stem}_indexed.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    paragraphs = parse_document(file_path)
    logger.info("解析完成: %d 段落", len(paragraphs))

    # Also save parsed
    parsed_path = output.replace("_indexed.json", "_parsed.json")
    save_parsed(paragraphs, parsed_path)

    index_result = build_index(paragraphs)
    save_indexed(index_result, output)
    logger.info("索引完成: 置信度=%.2f → %s", index_result["confidence"], output)
    print(f"索引完成 -> {output}")


def cmd_extract(args):
    """LLM 提取"""
    from src.persistence import load_indexed, save_extracted
    from src.extractor.extractor import extract_all
    from src.config import load_settings
    from src.logger import setup_logging

    logger = setup_logging("bid-analyzer")

    if not os.path.exists(args.indexed_json):
        print(f"错误: 文件不存在 — {args.indexed_json}", file=sys.stderr)
        sys.exit(1)

    index_result = load_indexed(args.indexed_json)
    settings = load_settings()

    # Support --module for single module extraction
    if args.module:
        from src.extractor.extractor import _MODULE_REGISTRY
        import importlib
        if args.module not in _MODULE_REGISTRY:
            print(f"错误: 未知模块 {args.module}，可用: {list(_MODULE_REGISTRY.keys())}", file=sys.stderr)
            sys.exit(1)
        module_path, func_name = _MODULE_REGISTRY[args.module]
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)
        result = func(index_result["tagged_paragraphs"], settings)
        print(f"模块 {args.module}: {'成功' if result else '失败'}")
        # When extracting single module, we still produce the full structure
        extracted = {"schema_version": "1.0", "modules": {args.module: result}}
    else:
        extracted = extract_all(index_result["tagged_paragraphs"], settings)

    output = args.output or args.indexed_json.replace("_indexed.json", "_extracted.json")
    save_extracted(extracted, output)
    print(f"提取完成 -> {output}")


def cmd_review(args):
    """交互式校对"""
    from src.persistence import load_extracted, save_reviewed
    from src.reviewer.cli_reviewer import review_all
    from src.logger import setup_logging

    logger = setup_logging("bid-analyzer")

    if not os.path.exists(args.extracted_json):
        print(f"错误: 文件不存在 — {args.extracted_json}", file=sys.stderr)
        sys.exit(1)

    extracted = load_extracted(args.extracted_json)
    reviewed = review_all(extracted)

    output = args.output or args.extracted_json.replace("_extracted.json", "_reviewed.json")
    save_reviewed(reviewed, output)
    print(f"校对完成 -> {output}")


def cmd_generate(args):
    """生成 .docx"""
    import json
    from src.generator.report_gen import render_report
    from src.generator.format_gen import render_format
    from src.generator.checklist_gen import render_checklist
    from src.logger import setup_logging

    logger = setup_logging("bid-analyzer")

    json_path = args.reviewed_json
    if not os.path.exists(json_path):
        print(f"错误: 文件不存在 — {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    stem = Path(json_path).stem.replace("_reviewed", "").replace("_extracted", "")

    render_report(data, os.path.join(output_dir, f"{stem}_分析报告.docx"))
    render_format(data, os.path.join(output_dir, f"{stem}_投标文件格式.docx"))
    render_checklist(data, os.path.join(output_dir, f"{stem}_资料清单.docx"))

    print(f"文档生成完成 -> {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        prog="bid-analyzer",
        description="招标文件智能解读工具",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="完整分析流程")
    p_analyze.add_argument("file", help="招标文件路径 (.doc/.docx/.pdf)")
    p_analyze.add_argument("--skip-review", action="store_true", help="跳过人工校对")
    p_analyze.add_argument("--output-dir", default="output", help="输出目录 (默认: output/)")
    p_analyze.set_defaults(func=cmd_analyze)

    # parse
    p_parse = subparsers.add_parser("parse", help="仅解析 + 索引")
    p_parse.add_argument("file", help="招标文件路径")
    p_parse.add_argument("--output", help="输出 JSON 路径")
    p_parse.set_defaults(func=cmd_parse)

    # extract
    p_extract = subparsers.add_parser("extract", help="LLM 结构化提取")
    p_extract.add_argument("indexed_json", help="索引结果 JSON 路径")
    p_extract.add_argument("--module", help="仅提取指定模块 (如 module_a)")
    p_extract.add_argument("--output", help="输出 JSON 路径")
    p_extract.set_defaults(func=cmd_extract)

    # review
    p_review = subparsers.add_parser("review", help="交互式人工校对")
    p_review.add_argument("extracted_json", help="提取结果 JSON 路径")
    p_review.add_argument("--output", help="输出 JSON 路径")
    p_review.set_defaults(func=cmd_review)

    # generate
    p_generate = subparsers.add_parser("generate", help="生成 .docx 文档")
    p_generate.add_argument("reviewed_json", help="校对/提取结果 JSON 路径")
    p_generate.add_argument("--output-dir", default="output", help="输出目录")
    p_generate.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
