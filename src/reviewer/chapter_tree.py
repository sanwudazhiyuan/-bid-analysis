"""任意深度章节树构建算法。

从扁平 sections（含 title, start, level）构建嵌套章节树，
支持任意层级深度、path 赋值、叶子拆分标记。
"""

from dataclasses import dataclass, field

LEAF_SPLIT_THRESHOLD = 1200  # 段落数阈值（约 30 页）


@dataclass
class _Section:
    title: str
    start: int
    level: int
    end: int = 0
    para_count: int = 0
    children: list["_Section"] = field(default_factory=list)
    _path: str = ""


def build_chapter_tree(
    sections: list[dict], total_paragraphs: int
) -> list[dict]:
    """从扁平 sections 构建任意深度章节树。

    Args:
        sections: [{title, start, level}] 已按 start 升序排序
        total_paragraphs: 文档总段落数

    Returns:
        嵌套章节树列表，每个节点含 title, path, level, start_para, end_para,
        para_count, is_leaf, needs_split, children
    """
    if not sections:
        return []

    nodes = [
        _Section(title=s["title"], start=s["start"], level=s["level"])
        for s in sorted(sections, key=lambda s: s["start"])
    ]

    # Step 1: 计算 end_para
    for i, node in enumerate(nodes):
        if i + 1 < len(nodes):
            node.end = nodes[i + 1].start - 1
        else:
            node.end = total_paragraphs - 1

    # Step 2: 用栈构建层级关系
    stack: list[_Section] = []
    root: list[_Section] = []

    for node in nodes:
        while stack and stack[-1].level >= node.level:
            stack.pop()

        if not stack:
            root.append(node)
        else:
            stack[-1].children.append(node)

        stack.append(node)

    # Step 3: 赋值 path
    def assign_paths(nodes: list[_Section], parent_path: str = "") -> None:
        for n in nodes:
            n._path = f"{parent_path}/{n.title}"
            assign_paths(n.children, n._path)

    assign_paths(root)

    # Step 4: 递归 finalize — 计算 para_count、is_leaf、needs_split
    def finalize(n: _Section) -> dict:
        if not n.children:
            n.para_count = n.end - n.start + 1
            is_leaf = True
        else:
            children_dicts = [finalize(c) for c in n.children]
            n.para_count = sum(c.para_count for c in n.children)
            is_leaf = False

        result = {
            "title": n.title,
            "path": n._path,
            "level": n.level,
            "start_para": n.start,
            "end_para": n.end,
            "para_count": n.para_count,
            "is_leaf": is_leaf,
            "needs_split": is_leaf and n.para_count > LEAF_SPLIT_THRESHOLD,
            "children": [] if is_leaf else children_dicts,
        }
        return result

    return [finalize(n) for n in root]


def collect_all_paths(tree: list[dict]) -> list[str]:
    """递归收集所有节点的 path 为扁平列表。"""
    paths: list[str] = []

    def _walk(nodes: list[dict]) -> None:
        for node in nodes:
            paths.append(node["path"])
            _walk(node.get("children", []))

    _walk(tree)
    return paths
