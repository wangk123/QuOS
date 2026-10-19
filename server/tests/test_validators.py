"""校验器测试:归一化定位 / 编号口径 / 硬结构 / 软警告转批注(Review Focus 1-3)。"""
from types import SimpleNamespace

from app.models import DocPayload
from app.services.validators import check_draft, locate_quote, normalize

MATERIAL_TEXT = (
    "幂等与恢复\n"
    "服务以 身份 + 请求体 + 每个文件的 文件名:大小:SHA-256 计算幂等内容摘要。\n"
    "请求处于 PROCESSING 超过 15 分钟时,在进程启动与定时扫描中执行恢复。\n"
)


def mat(mid: int = 1, text: str = MATERIAL_TEXT) -> SimpleNamespace:
    return SimpleNamespace(id=mid, parsed_text=text)


def rule(no: str, text: str = "规则文本足够长", violation: str = "怎样算违反的标准描述",
         quote: str = "", material_id: int | None = 1, status: str = "active",
         replaced_by: str | None = None) -> dict:
    return {"no": no, "text": text, "violation": violation, "quote": quote,
            "material_id": material_id, "status": status, "replaced_by": replaced_by}


def chapter(cid: str = "c1", title: str = "幂等与恢复", rule_nos: list | None = None,
            blocks: list | None = None, parent: str | None = None) -> dict:
    ch = {"id": cid, "title": title, "rule_nos": rule_nos or []}
    if blocks is not None:
        ch["blocks"] = blocks
    if parent is not None:
        ch["parent"] = parent
    return ch


def payload(rules: dict | None = None, chapters: list | None = None,
            new_terms: list | None = None) -> DocPayload:
    return DocPayload.model_validate({
        "meta": {"version": "draft", "date": "2026-10-14", "scope": "test"},
        "chapters": chapters if chapters is not None else [chapter(rule_nos=list((rules or {}).keys()))],
        "rules": rules or {},
        "new_terms": new_terms or [],
    })


# ── 归一化与定位(Review Focus 1) ──


def test_normalize_folds_width_case_space():
    assert normalize("Ｉｄｅｍｐｏｔｅｎｃｙ　Ｋｅｙ  ABC") == normalize("idempotency key abc")


def test_locate_quote_tolerates_pdf_noise():
    noisy = "以 身份＋请求体＋每个文件的\n  文件名:大小:SHA-256 计算"
    r = locate_quote(noisy, MATERIAL_TEXT)
    assert r.ok


def test_locate_quote_failure_returns_nearest():
    r = locate_quote("完全不存在的一句话引用内容啊", MATERIAL_TEXT)
    assert not r.ok
    assert r.nearest  # 附最相近片段供 agent 修正


def test_locate_quote_empty_material_fails_gracefully():
    r = locate_quote("任何引用", "")
    assert not r.ok


# ── 编号口径(Review Focus 2) ──


def test_modify_path_reuses_existing_no():
    p = payload(rules={"R12": rule("R12", quote="计算幂等内容摘要")})
    rpt = check_draft(p, rules_existing={"R12": "active"}, materials={1: mat()}, terms=set())
    assert not [e for e in rpt.hard_errors if e.code == "NO_CONFLICT"]


def test_resurrect_voided_no_rejected():
    p = payload(rules={"R99": rule("R99", quote="计算幂等内容摘要")})
    rpt = check_draft(p, rules_existing={"R99": "voided"}, materials={1: mat()}, terms=set())
    assert any(e.code == "NO_CONFLICT" and e.rule_no == "R99" for e in rpt.hard_errors)


def test_duplicate_no_inside_draft_rejected():
    p = DocPayload.model_validate({
        "chapters": [chapter(rule_nos=["R1", "R1"])],
        "rules": {"R1": rule("R1", quote="计算幂等内容摘要")},
    })
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "NO_CONFLICT" for e in rpt.hard_errors)


def test_chapter_references_missing_rule_rejected():
    p = DocPayload.model_validate({
        "chapters": [chapter(rule_nos=["R1", "R7"])],
        "rules": {"R1": rule("R1", quote="计算幂等内容摘要")},
    })
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "DANGLING_REF" for e in rpt.hard_errors)


# ── quote / 材料(Review Focus 3 + 短引用降级) ──


def test_image_material_skips_quote():
    img = mat(2, text="")  # 图片:parsed_text 为空
    p = payload(rules={"R1": rule("R1", quote="无论如何都定位不到的引用文本", material_id=2)})
    rpt = check_draft(p, rules_existing={}, materials={2: img}, terms=set())
    assert not [e for e in rpt.hard_errors if e.code == "QUOTE_NOT_FOUND"]


def test_missing_material_id_distinct_error():
    p = payload(rules={"R1": rule("R1", material_id=99)})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "MATERIAL_NOT_FOUND" for e in rpt.hard_errors)


def test_quote_not_found_hard_error_with_nearest():
    p = payload(rules={"R1": rule("R1", quote="材料里没有的引用内容一二三四五")})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    errs = [e for e in rpt.hard_errors if e.code == "QUOTE_NOT_FOUND"]
    assert errs and errs[0].detail.get("nearest")


def test_short_quote_downgrades_to_soft():
    p = payload(rules={"R1": rule("R1", quote="恢复")})  # <6 字
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert not [e for e in rpt.hard_errors if e.code == "QUOTE_NOT_FOUND"]
    assert any(w.code == "QUOTE_TOO_SHORT" for w in rpt.soft_warnings)


# ── 结构硬校验 ──


def test_active_rule_requires_violation():
    p = payload(rules={"R1": rule("R1", violation="", quote="计算幂等内容摘要")})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "VIOLATION_EMPTY" for e in rpt.hard_errors)


def test_voided_rule_requires_replaced_by():
    p = payload(rules={"R9": rule("R9", status="voided", replaced_by=None)})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "VOIDED_NO_REPLACED_BY" for e in rpt.hard_errors)


def test_chapter_requires_title():
    p = payload(chapters=[{"id": "c1", "title": ""}])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "CHAPTER_NO_TITLE" for e in rpt.hard_errors)


# ── 软警告转批注 ──


def test_soft_new_terms_to_confirm():
    p = payload(rules={"R1": rule("R1", quote="计算幂等内容摘要")},
                new_terms=[{"name": "幂等键", "context": "对外API章"}])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    qs = [q for q in rpt.auto_questions if q.payload.get("klabel") == "术语确认"]
    assert qs and "幂等键" in qs[0].payload["q"]
    assert qs[0].kind == "confirm"


def test_soft_violation_clone_to_confirm():
    p = payload(rules={"R1": rule("R1", text="取消时已建单则不停止执行",
                                  violation="取消时已建单则不停止执行",
                                  quote="执行恢复")})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(q.kind == "confirm" and q.anchor.get("rule_no") == "R1"
               for q in rpt.auto_questions)


def test_soft_empty_chapter_to_fill():
    """空壳章(无正文块且零规则)出 fill;有叙述无规则/有规则无正文均不再出题(不逼填模板)。"""
    p = payload(rules={"R1": rule("R1", quote="计算幂等内容摘要")},
                chapters=[
                    chapter("c1", rule_nos=["R1"]),  # 有规则:不出题
                    chapter("c2", "解析路由", [], blocks=[{"type": "para", "text": "路由叙述"}]),  # 有叙述:不出题
                    chapter("c3", "空壳章", []),  # 无正文无规则:fill
                ])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    fills = [q for q in rpt.auto_questions if q.kind == "fill"]
    assert len(fills) == 1 and "没有任何正文与规则" in fills[0].payload["q"]
    assert fills[0].anchor.get("chapter_id") == "c3"


# ── 正文块与层级(契约升级:blocks 自由块 + parent 层级) ──


def test_block_bad_type_rejected():
    p = payload(chapters=[chapter("c1", blocks=[{"type": "prose", "text": "x"}])])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "BLOCK_BAD_TYPE" for e in rpt.hard_errors)


def test_block_empty_rejected():
    p = payload(chapters=[
        chapter("c1", blocks=[{"type": "table", "title": "参数", "columns": ["字段"], "rows": []}]),
    ])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "BLOCK_EMPTY" and e.detail.get("type") == "table"
               for e in rpt.hard_errors)


def test_parent_dangling_rejected():
    p = payload(chapters=[chapter("c2", parent="no-such")])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "CHAPTER_PARENT_DANGLING" for e in rpt.hard_errors)


def test_parent_cycle_rejected():
    p = payload(chapters=[chapter("c1", parent="c2"), chapter("c2", parent="c1")])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert any(e.code == "CHAPTER_PARENT_CYCLE" for e in rpt.hard_errors)


def test_valid_blocks_and_hierarchy_pass():
    p = payload(rules={"R1": rule("R1", quote="计算幂等内容摘要")},
                chapters=[
                    chapter("c1", "接入", rule_nos=["R1"], blocks=[
                        {"type": "para", "text": "主链路叙述"},
                        {"type": "table", "title": "参数", "columns": ["字段", "说明"], "rows": [["k", "键"]]},
                        {"type": "figure", "title": "主流程", "flows": ["上传 → 解析 → 发布"]},
                    ]),
                    chapter("c1-1", "解析子流程", parent="c1",
                            blocks=[{"type": "states", "text": "A → B → C"},
                                    {"type": "exceptions", "items": ["失败 → 重试"]}]),
                ])
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert not rpt.hard_errors


def test_soft_registered_term_variant_writing():
    p = payload(rules={"R1": rule("R1", text="IDEMPOTENCY_KEY 必须唯一", quote="执行恢复")})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()},
                      terms={"idempotency_key"})
    assert any(q.payload.get("klabel") == "术语写法" for q in rpt.auto_questions)


def test_locate_quote_against_real_material():
    """真实验收材料锚定:raw-backup 多模态 overview(design §2 验收硬门槛)。"""
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data/raw-backup/多模态/hanhai-multimodal-requirements-overview.md"
    if not path.exists():
        import pytest
        pytest.skip("raw-backup 材料不在测试环境")  # 显式 skip,不得静默记为通过
    text = path.read_text(encoding="utf-8")
    assert locate_quote("同 case + 输入版本 + 策略版本仅一个有效运行", text).ok
    assert locate_quote("代码不一致时以代码行为为准", text).ok


# ── 终审修复 ──
def test_empty_quote_downgrades_to_soft_not_silent():  # I1:空 quote 不得绕过出处层
    p = payload(rules={"R1": rule("R1", quote="")})
    rpt = check_draft(p, rules_existing={}, materials={1: mat()}, terms=set())
    assert not [e for e in rpt.hard_errors if e.code == "QUOTE_NOT_FOUND"]
    assert any(w.code == "QUOTE_TOO_SHORT" and w.rule_no == "R1" for w in rpt.soft_warnings)


def test_nearest_is_original_text_sentence():  # I6:nearest 必须是原文句,不是错位切片
    material = "接入流程包含解析与校验环节。\n恢复流程按现场分支处理。\n"
    r = locate_quote("恢复流程如何按分支处理的方式", material)
    assert not r.ok
    assert "恢复流程" in r.nearest and "\n" not in r.nearest


# ── 终审 fix:check_draft 对 diagram 块的硬软分流直测 ──
def _mk_payload_with_diagram(text):
    return {"meta": {"version": "draft", "date": "2026-10-19", "scope": "s"},
            "chapters": [{"id": "c1", "title": "接入", "pri": "P0", "rule_nos": [],
                          "blocks": [{"type": "diagram", "text": text}]}],
            "rules": {}}


def test_check_draft_diagram_html_hard():
    from app.services.validators import check_draft
    from app.models import DocPayload
    payload = DocPayload.model_validate(_mk_payload_with_diagram(
        '<svg viewBox="0 0 4 4"><title id="a-title">a</title><script>alert(1)</script></svg>'))
    rpt = check_draft(payload, rules_existing={}, materials={}, terms=set())
    assert any(e.code == "DIAGRAM_CHECK" for e in rpt.hard_errors)


def test_check_draft_diagram_legacy_soft():
    from app.services.validators import check_draft
    from app.models import DocPayload
    payload = DocPayload.model_validate(_mk_payload_with_diagram("flowchart TD\nA-->B"))
    rpt = check_draft(payload, rules_existing={}, materials={}, terms=set())
    assert not rpt.hard_errors
    assert any(w.code == "DIAGRAM_LEGACY" for w in rpt.soft_warnings)
