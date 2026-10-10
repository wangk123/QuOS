# server/tests/test_cards.py
import pytest
from app.storage.profiles import save_profile, load_profile, export_doc, Profile, ProfileRule

def _card(node="放款/重试", **kw):
    data = dict(node=node, goal="不重复放款", entry="回调超时30s",
                flow="入队→重发→最多3次",
                rules=[ProfileRule(id="R1", text="上限3次", src="retry.py:42", conf="实证")],
                states="待放款→…", boundaries="", note="", deps="")
    data.update(kw)
    return Profile(**data)

def test_slug_and_roundtrip(tmp_path):
    p = save_profile(tmp_path, "放款/重试", _card())
    assert "重试" in p.name and "/" not in p.name
    assert load_profile(tmp_path, "放款/重试").rules[0].id == "R1"

def test_duplicate_name_suffix(tmp_path):
    save_profile(tmp_path, "放款/重试", _card())
    p2 = save_profile(tmp_path, "放款/重试", _card(note="第二张"))
    assert p2.name != "重试.md"

def test_export_doc(tmp_path):
    save_profile(tmp_path, "放款/重试", _card())
    doc = export_doc(tmp_path)
    assert "上限3次" in doc and "放款/重试" in doc

def test_export_doc_format(tmp_path):
    """面向人的文档格式：粗体小节标签、规则列表化无 ID、状态机按组拆行"""
    save_profile(tmp_path, "放款/重试", _card(states="待放款→已放款；失败→回滚"))
    doc = export_doc(tmp_path)
    assert "**主流程**" in doc and "**规则**" in doc and "**状态机**" in doc
    assert "- 上限3次" in doc            # 规则列表化
    assert "| R1 |" not in doc           # ID 列不进文档（跨模块撞号，对读者无意义）
    assert "retry.py:42" not in doc      # src 值不进文档
    i, j = doc.index("待放款→已放款"), doc.index("失败→回滚")
    assert doc[i:j].count("\n") >= 1     # 状态机组各自成行

def test_export_doc_humanize(tmp_path):
    """过程性措辞规整：验证句式去壳；计数型边界（0 实证）过滤"""
    save_profile(tmp_path, "放款/重试", _card(
        goal="验证上传文件时三类渠道均可正常提交并进入解析链路的行为。",
        boundaries="0 实证"))
    doc = export_doc(tmp_path)
    assert "上传文件时三类渠道均可正常提交并进入解析链路。" in doc
    assert "验证" not in doc and "0 实证" not in doc
    assert "**异常边界**" not in doc      # 过滤后空字段整节跳过

def test_export_doc_header(tmp_path):
    """文档头元信息：项目名/生成时间/范围统计；版本行接当前基线 tag，无版本则省"""
    save_profile(tmp_path, "放款/重试", _card())
    doc = export_doc(tmp_path)
    assert doc.startswith(f"# {tmp_path.name} · 需求文档")
    assert "- 生成：" in doc and "- 范围：0 个模块 · 1 条规则" in doc  # 无树：画像进附录
    assert "## 附录：未挂树的画像" in doc
    assert "- 版本：" not in doc          # 无 git 基线时省版本行
    from app.storage import gitops
    gitops.save_baseline(tmp_path, "1.0.0", "一")
    doc2 = export_doc(tmp_path)
    assert "- 版本：v1.0.0（当前基线）" in doc2

def test_export_doc_rule_table_drops_src_conf(tmp_path):
    """面向人的需求文档：来源与置信度是过程产物不进文档（合并入 format 用例，保留独立防回归）"""
    save_profile(tmp_path, "放款/重试", _card())
    doc = export_doc(tmp_path)
    assert "来源" not in doc and "置信度" not in doc
    assert "retry.py:42" not in doc  # src 值不落文档

def test_slug_special_chars(tmp_path):
    p = save_profile(tmp_path, "放款/重 试!", _card(node="放款/重 试!"))
    assert "/" not in p.name and " " not in p.name and "!" not in p.name
    assert load_profile(tmp_path, "放款/重 试!").rules[0].id == "R1"

def test_duplicate_latest_wins(tmp_path):
    save_profile(tmp_path, "放款/重试", _card(goal="v1"))
    save_profile(tmp_path, "放款/重试", _card(goal="v2"))
    save_profile(tmp_path, "放款/重试", _card(goal="v3"))
    assert load_profile(tmp_path, "放款/重试").goal == "v3"
    doc = export_doc(tmp_path)
    assert "v3" in doc and "v1" not in doc and "v2" not in doc

def test_roundtrip_full(tmp_path):
    card = Profile(node="还款/扣款", goal="准确扣款", entry="到期日触发",
                flow="计算→扣款→记账",
                rules=[ProfileRule(id="R2", text="金额取整", src="pay.py:10", conf="推测")],
                states="待扣→已扣", boundaries="余额不足退卡", note="按日计息",
                deps="账务核心")
    save_profile(tmp_path, "还款/扣款", card)
    assert load_profile(tmp_path, "还款/扣款") == card


def test_legacy_unconfirmed_section_ignored(tmp_path):
    """unconfirmed 已退役（assemble 读后感，游离于「核验通过/待处理」两分流外）：
    存量画像的「## 未确认项」段静默忽略，其余字段正常读；重存后该段消失"""
    d = tmp_path / "profiles"; d.mkdir()
    (d / "旧节点.md").write_text("""---
node: 旧节点
kind: leaf
goal: g
entry: e
---

# 旧节点

## 未确认项

- 某某待确认（历史遗留读后感）

## 主流程

1. 步骤一

## 规则

| ID | 规则 | 来源 | 置信度 |
|---|---|---|---|
| R1 | 旧规则 | a.md | 文档 |
""", "utf-8")
    p = load_profile(tmp_path, "旧节点")
    assert p.goal == "g" and p.flow.strip().startswith("1.")
    assert len(p.rules) == 1
    save_profile(tmp_path, "旧节点", p)
    assert "未确认项" not in (d / "旧节点-2.md").read_text("utf-8")


