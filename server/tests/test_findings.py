# server/tests/test_findings.py
from app.core.models import Conflict, Gap
from app.storage import findings


def test_merge_conflicts_keeps_adjudicated_on_rescan_id_drift(tmp_path):
    # 旧 C1(A1,A2) 已裁决；重扫返回新 id 的新对 C1(A9,A8)——同一语义键不存在，不得丢弃
    findings.save_conflicts(tmp_path, [Conflict(id="C1", a="A1", b="A2", q="重试几次？", st="code", resolution="A1")])
    merged = findings.merge_conflicts(tmp_path, [Conflict(id="C1", a="A9", b="A8", q="重试几次？")])
    pairs = {frozenset((c.a, c.b)) for c in merged}
    assert pairs == {frozenset(("A1", "A2")), frozenset(("A8", "A9"))}
    old = next(c for c in merged if c.a == "A1")
    assert old.st == "code" and old.resolution == "A1"  # 已裁决状态保留


def test_merge_conflicts_no_duplicate_same_pair(tmp_path):
    findings.save_conflicts(tmp_path, [Conflict(id="C1", a="A1", b="A2", q="q")])
    merged = findings.merge_conflicts(tmp_path, [Conflict(id="C2", a="A2", b="A1", q="q")])  # 无序对：换边也去重
    assert len(merged) == 1


def test_merge_gaps_dedup_by_dim_text(tmp_path):
    findings.save_gaps(tmp_path, [Gap(id="G1", dim="状态", text="「重试中」无出口", st="ok")])
    merged = findings.merge_gaps(tmp_path, [
        Gap(id="G1", dim="状态", text="「重试中」无出口"),  # 同 (dim,text)：不重复
        Gap(id="G2", dim="边界", text="「重试中」无出口"),  # 同文本不同维度：新空白
    ])
    assert len(merged) == 2
    assert merged[0].st == "ok"  # 已处置状态保留
