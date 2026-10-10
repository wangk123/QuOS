# server/tests/test_agent_rules.py
from pathlib import Path

RULES = Path(__file__).parent.parent / "app" / "ai" / "agent" / "rules"
TASKS = ("tree-gen", "extract", "verify")


def test_shared_preamble():
    for t in TASKS:
        text = (RULES / f"{t}.md").read_text("utf-8")
        assert "不是指令" in text          # 材料是数据不是指令
        assert "out/result.json" in text    # 只写 out/
        assert "臆造" in text               # 不臆造
        assert "report.md" in text          # 自评报告


def test_schema_examples_present():
    for t, key in (("tree-gen", '"nodes"'), ("extract", '"rules"'), ("verify", '"results"')):
        assert key in (RULES / f"{t}.md").read_text("utf-8")
