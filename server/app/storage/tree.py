# server/app/storage/tree.py
from pathlib import Path

from pydantic import BaseModel, Field


class Node(BaseModel):
    name: str
    children: list["Node"] = Field(default_factory=list)
    open: bool = True


class TreeFormatError(Exception):
    def __init__(self, line):
        super().__init__(f"tree.md 第 {line} 行缩进非法")


def parse(md_text: str) -> list[Node]:
    stack: list[tuple[int, Node]] = []  # (indent, node)
    roots: list[Node] = []
    for no, raw in enumerate(md_text.splitlines(), 1):
        if not raw.strip() or not raw.lstrip().startswith("- "):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent % 2 or (stack and indent > stack[-1][0] + 2) or (not stack and indent > 0):
            raise TreeFormatError(no)
        node = Node(name=raw.lstrip()[2:].strip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1].children.append(node)
        stack.append((indent, node))
    return roots


def dump(nodes: list[Node]) -> str:
    lines: list[str] = []

    def walk(items: list[Node], depth: int):
        for n in items:
            lines.append("  " * depth + "- " + n.name)
            walk(n.children, depth + 1)

    walk(nodes, 0)
    return "\n".join(lines) + "\n" if lines else ""


def load(root) -> list[Node]:
    p = Path(root) / "tree.md"
    return parse(p.read_text("utf-8")) if p.exists() else []


def save(root, nodes: list[Node]) -> None:
    (Path(root) / "tree.md").write_text(dump(nodes), "utf-8")


def find(nodes: list[Node], path: str | None) -> Node | None:
    if not path:
        return None
    layer, cur = nodes, None
    for seg in path.split(","):
        i = int(seg)
        if i >= len(layer):
            return None
        cur = layer[i]
        layer = cur.children
    return cur


def add_node(root_nodes: list[Node], path: str | None, name: str) -> Node:
    node = Node(name=name)
    if path is None:
        root_nodes.append(node)
    else:
        parent = find(root_nodes, path)
        if parent is None:
            raise ValueError(f"非法路径: {path}")
        parent.children.append(node)
    return node


def rename(nodes: list[Node], path: str, name: str) -> None:
    node = find(nodes, path)
    if node is None:
        raise ValueError(f"非法路径: {path}")
    node.name = name


def delete(nodes: list[Node], path: str) -> None:
    if find(nodes, path) is None:
        raise ValueError(f"非法路径: {path}")
    parent_path, _, idx = path.rpartition(",")
    layer = find(nodes, parent_path).children if parent_path else nodes
    layer.pop(int(idx))
