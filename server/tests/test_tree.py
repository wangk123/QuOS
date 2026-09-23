# server/tests/test_tree.py
import pytest
from app.storage.tree import parse, dump, find, add_node, rename, delete, TreeFormatError

MD = """# 项目 · 功能树
- 放款
  - 放款失败处理
    - 放款失败登记
    - 放款重试
- 还款
"""

def test_roundtrip():
    nodes = parse(MD)
    assert nodes[0].name == "放款" and nodes[0].children[0].children[1].name == "放款重试"
    assert parse(dump(nodes))[0].children[0].children[1].name == "放款重试"

def test_find_by_path():
    nodes = parse(MD)
    assert find(nodes, "0,0,1").name == "放款重试"
    assert find(nodes, "0,1") is None

def test_bad_indent_raises():
    with pytest.raises(TreeFormatError):
        parse("- a\n      - b\n  - c")  # 6 空格跳级

def test_dash_without_space_raises():
    # `-名称`（缺空格）不得静默丢行，必须报错带行号
    with pytest.raises(TreeFormatError) as e:
        parse("- 放款\n-额度")
    assert "第 2 行" in str(e.value) and "缺空格" in str(e.value)

def test_negative_path_rejected():
    nodes = parse(MD)
    assert find(nodes, "-1") is None
    with pytest.raises(ValueError):
        delete(nodes, "-1")
    assert len(nodes) == 2 and nodes[0].children[0].children[1].name == "放款重试"

def test_ops():
    nodes = parse(MD)
    add_node(nodes, "0,0", "重试监控告警")
    assert find(nodes, "0,0,2").name == "重试监控告警"
    add_node(nodes, None, "额度管理")
    rename(nodes, "0,0,2", "重试告警")
    assert find(nodes, "0,0,2").name == "重试告警"
    delete(nodes, "0,0,2")
    assert len(find(nodes, "0,0").children) == 2
