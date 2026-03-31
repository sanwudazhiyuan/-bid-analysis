"""Tests for chapter tree builder."""


def test_build_single_level():
    """只有 level-1 节点的扁平文档。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章 投标函", "start": 0, "level": 1},
        {"title": "第二章 技术方案", "start": 10, "level": 1},
        {"title": "第三章 商务报价", "start": 20, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=30)

    assert len(tree) == 3
    assert tree[0]["title"] == "第一章 投标函"
    assert tree[0]["path"] == "/第一章 投标函"
    assert tree[0]["start_para"] == 0
    assert tree[0]["end_para"] == 9
    assert tree[0]["is_leaf"] is True
    assert tree[0]["para_count"] == 10
    assert tree[2]["end_para"] == 29


def test_build_nested_two_levels():
    """2 层嵌套：level-1 下有 level-2 子节点。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章 投标函", "start": 0, "level": 1},
        {"title": "1.1 投标函内容", "start": 2, "level": 2},
        {"title": "1.2 授权委托书", "start": 8, "level": 2},
        {"title": "第二章 技术方案", "start": 15, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=30)

    assert len(tree) == 2
    ch1 = tree[0]
    assert ch1["is_leaf"] is False
    assert len(ch1["children"]) == 2
    assert ch1["children"][0]["path"] == "/第一章 投标函/1.1 投标函内容"
    assert ch1["children"][0]["is_leaf"] is True
    assert ch1["children"][1]["path"] == "/第一章 投标函/1.2 授权委托书"


def test_build_four_levels():
    """4 层嵌套树。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "一、概述", "start": 2, "level": 2},
        {"title": "（一）背景", "start": 3, "level": 3},
        {"title": "1.1.1 详情", "start": 4, "level": 4},
        {"title": "第二章", "start": 10, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=20)

    ch1 = tree[0]
    assert ch1["is_leaf"] is False
    child_l2 = ch1["children"][0]
    assert child_l2["title"] == "一、概述"
    child_l3 = child_l2["children"][0]
    assert child_l3["title"] == "（一）背景"
    child_l4 = child_l3["children"][0]
    assert child_l4["title"] == "1.1.1 详情"
    assert child_l4["path"] == "/第一章/一、概述/（一）背景/1.1.1 详情"
    assert child_l4["is_leaf"] is True


def test_needs_split_large_leaf():
    """叶子节点段落数超 1200 标记 needs_split=True。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=2000)

    assert tree[0]["is_leaf"] is True
    assert tree[0]["needs_split"] is True
    assert tree[0]["para_count"] == 2000


def test_needs_split_small_leaf():
    """叶子节点段落数 <= 1200 不标记 needs_split。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=100)

    assert tree[0]["needs_split"] is False


def test_collect_all_paths():
    """collect_all_paths 返回扁平 path 列表。"""
    from src.reviewer.chapter_tree import build_chapter_tree, collect_all_paths

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "1.1 概述", "start": 2, "level": 2},
        {"title": "第二章", "start": 10, "level": 1},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=20)
    paths = collect_all_paths(tree)

    assert "/第一章" in paths
    assert "/第一章/1.1 概述" in paths
    assert "/第二章" in paths
    assert len(paths) == 3


def test_empty_sections():
    """空输入返回空列表。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    assert build_chapter_tree([], total_paragraphs=100) == []


def test_siblings_same_level():
    """同级兄弟节点 end_para 正确切分。"""
    from src.reviewer.chapter_tree import build_chapter_tree

    sections = [
        {"title": "第一章", "start": 0, "level": 1},
        {"title": "1.1", "start": 2, "level": 2},
        {"title": "1.2", "start": 5, "level": 2},
        {"title": "1.3", "start": 8, "level": 2},
    ]
    tree = build_chapter_tree(sections, total_paragraphs=12)

    ch1 = tree[0]
    assert len(ch1["children"]) == 3
    assert ch1["children"][0]["end_para"] == 4
    assert ch1["children"][1]["end_para"] == 7
    assert ch1["children"][2]["end_para"] == 11
