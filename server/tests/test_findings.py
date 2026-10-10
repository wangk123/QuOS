# server/tests/test_findings.py
from app.core.models import Conflict, Gap
from app.storage import findings


def test_merge_conflicts_keeps_adjudicated_on_rescan_id_drift(tmp_path):
    # 旧 C1(A1,A2) 已裁决；重扫返回新 id 的新对 C1(A9,A8)——同一语义键不存在，不得丢弃
    findings.save_conflicts(tmp_path, [Conflict(id="C1", parties=["A1", "A2"], q="重试几次？", st="done", resolution="A1")])
    merged = findings.merge_conflicts(tmp_path, [Conflict(id="C1", parties=["A9", "A8"], q="重试几次？")])
    sets = {frozenset(c.parties) for c in merged}
    assert sets == {frozenset(("A1", "A2")), frozenset(("A8", "A9"))}
    old = next(c for c in merged if "A1" in c.parties)
    assert old.st == "done" and old.resolution == "A1"  # 已裁决状态保留


def test_merge_conflicts_no_duplicate_same_pair(tmp_path):
    findings.save_conflicts(tmp_path, [Conflict(id="C1", parties=["A1", "A2"], q="q")])
    merged = findings.merge_conflicts(tmp_path, [Conflict(id="C2", parties=["A2", "A1"], q="q")])  # 无序对：换边也去重
    assert len(merged) == 1


def test_merge_gaps_dedup_by_dim_text(tmp_path):
    findings.save_gaps(tmp_path, [Gap(id="G1", dim="状态", text="「重试中」无出口", st="ok")])
    merged = findings.merge_gaps(tmp_path, [
        Gap(id="G1", dim="状态", text="「重试中」无出口"),  # 同 (dim,text,node)：不重复
        Gap(id="G2", dim="边界", text="「重试中」无出口"),  # 同文本不同维度：新空白
    ])
    assert len(merged) == 2
    assert merged[0].st == "ok"  # 已处置状态保留


def test_merge_gaps_same_text_different_node_both_kept(tmp_path):
    # 节点绑定后，同 (dim,text) 挂在不同节点是两条独立缺口
    findings.save_gaps(tmp_path, [Gap(id="G1", dim="状态", text="未说明状态流转", node="支付/放款")])
    merged = findings.merge_gaps(tmp_path, [
        Gap(id="G2", dim="状态", text="未说明状态流转", node="支付/放款"),  # 同节点：去重
        Gap(id="G3", dim="状态", text="未说明状态流转", node="风控/额度"),  # 异节点：保留
    ])
    assert [g.id for g in merged] == ["G1", "G3"]
