import subprocess
import sys

def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "analyze" in result.stdout

def test_cli_analyze_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "analyze", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

def test_cli_parse_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "parse", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

def test_cli_extract_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "extract", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--module" in result.stdout or "module" in result.stdout

def test_cli_review_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "review", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

def test_cli_generate_help():
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "generate", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

def test_cli_missing_file():
    """不存在的文件应返回非零退出码"""
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "analyze", "nonexistent_file.doc"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
