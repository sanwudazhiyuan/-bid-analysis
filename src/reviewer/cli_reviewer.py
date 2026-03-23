"""CLI 交互式校对器（Layer 4 — 人工校对层）

逐模块展示 LLM 提取结果，用户可选择：
  [Y] 确认通过
  [e] 打开编辑器修改
  [n] 标记需重跑
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

from rich.console import Console
from rich.table import Table

console = Console()


def display_module(module_key: str, module_data: dict | None) -> None:
    """用 rich 渲染单个模块的表格预览。"""
    if module_data is None:
        console.print(f"\n[bold yellow]【{module_key}】无数据（跳过）[/bold yellow]")
        return

    if module_data.get("status") == "failed":
        error = module_data.get("error", "未知错误")
        console.print(
            f"\n[bold red]【{module_key}】提取失败: {error}[/bold red]"
        )
        return

    title = module_data.get("title", module_key)
    console.print(f"\n[bold cyan]{'═' * 60}[/bold cyan]")
    console.print(f"[bold cyan]  {title}[/bold cyan]")
    console.print(f"[bold cyan]{'═' * 60}[/bold cyan]")

    sections = module_data.get("sections", [])
    if not sections:
        console.print("  （无 sections 数据）")
        return

    for section in sections:
        section_title = section.get("title", section.get("id", ""))
        columns = section.get("columns", [])
        rows = section.get("rows", [])

        if section_title:
            console.print(f"\n  [bold]{section_title}[/bold]")

        if columns and rows:
            table = Table(show_header=True, header_style="bold magenta")
            for col in columns:
                table.add_column(str(col))
            for row in rows:
                table.add_row(*[str(cell) for cell in row])
            console.print(table)
        elif rows:
            for row in rows:
                console.print(f"  {row}")


def open_in_editor(json_data: dict) -> dict | None:
    """将 JSON 数据写入临时文件，打开编辑器让用户修改，读回并校验。

    Returns:
        修改后的 dict，如果 JSON 非法返回 None。
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="bid_review_",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(json_data, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name

    try:
        editor = os.environ.get("EDITOR", "notepad" if sys.platform == "win32" else "vi")
        subprocess.call([editor, tmp_path])

        with open(tmp_path, "r", encoding="utf-8") as f:
            content = f.read()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            console.print("[bold red]JSON 格式错误，编辑内容无效[/bold red]")
            return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def save_reviewed(data: dict, output_path: str) -> None:
    """保存校对后的结果为 JSON。"""
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    data["reviewed_at"] = datetime.now().isoformat(timespec="seconds")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    console.print(f"\n[green]校对结果已保存: {output_path}[/green]")


def review_all(extracted_json: dict) -> dict:
    """逐模块交互式校对。

    对每个模块：
    - 展示表格预览
    - 用户选择 [Y]确认 / [e]编辑 / [n]标记重跑

    Returns:
        校对后的完整 dict（含 reviewed_at 等元数据）。
    """
    result = {
        "schema_version": extracted_json.get("schema_version", "1.0"),
        "generated_at": extracted_json.get("generated_at", ""),
        "modules": {},
    }

    modules = extracted_json.get("modules", {})

    for key, module_data in modules.items():
        display_module(key, module_data)

        if module_data is None:
            result["modules"][key] = None
            # 对于 None 模块，提示用户并跳过
            choice = input("  此模块无数据，按回车跳过: ")
            continue

        if module_data.get("status") == "failed":
            result["modules"][key] = module_data
            choice = input("  此模块提取失败，按回车跳过: ")
            continue

        choice = input("  [Y]确认 / [e]编辑 / [n]标记重跑: ").strip().lower()

        if choice == "e":
            edited = open_in_editor(module_data)
            if edited is not None:
                result["modules"][key] = edited
                console.print("[green]  已更新模块数据[/green]")
            else:
                console.print("[yellow]  编辑无效，保留原始数据[/yellow]")
                result["modules"][key] = module_data
        elif choice == "n":
            result["modules"][key] = {**module_data, "needs_rerun": True}
            console.print("[yellow]  已标记为需重跑[/yellow]")
        else:
            # 默认通过（Y 或直接回车）
            result["modules"][key] = module_data

    return result
