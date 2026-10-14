"""模型与 payload 契约测试。"""
import json

from app.models import DocPayload, Question, RuleInPayload


def test_question_anchor_flattened(db):
    q = Question(
        project_id=1, kind="confirm",
        payload={"q": "术语「幂等键」收录?", "klabel": "术语确认"},
        anchor={"chapter_id": "c3", "rule_no": "R15", "seg": "idempotency_key"},
        status="pending", source="auto",
    )
    db.add(q)
    db.commit()
    got = db.query(Question).one()
    assert got.anchor["rule_no"] == "R15"
    assert got.anchor["chapter_id"] == "c3"
    assert got.source == "auto"


VOIDED_SNAPSHOT = {
    "meta": {"version": "v1", "date": "2026-10-10", "scope": "三章"},
    "overview": {"intent": "收编散落文档", "boundary": "不含通知"},
    "glossary": [{"name": "Run", "definition": "一次处理执行"}],
    "new_terms": [{"name": "幂等键", "definition": "", "context": "对外API章"}],
    "chapters": [
        {"id": "c3", "title": "幂等与恢复", "pri": "P0", "background": "稳定性底线",
         "states": "受理 → PROCESSING → SUCCEEDED", "exceptions": ["同键不同内容:409"],
         "rule_nos": ["R9", "R15"]}
    ],
    "rules": {
        "R9": {"no": "R9", "text": "", "violation": "", "quote": "", "material_id": None,
               "status": "voided", "replaced_by": "R15"},
        "R15": {"no": "R15", "text": "幂等作用域为 tenant_id + idempotency_key",
                "violation": "不同租户同键被判为同键",
                "quote": "幂等作用域为 tenant_id + idempotency_key", "material_id": 1,
                "status": "active", "replaced_by": None},
    },
}


def test_docpayload_roundtrip_with_voided_rule():
    p = DocPayload.model_validate(json.loads(json.dumps(VOIDED_SNAPSHOT)))
    assert p.rules["R9"].status == "voided"
    assert p.rules["R9"].replaced_by == "R15"
    r: RuleInPayload = p.rules["R15"]
    assert r.material_id == 1 and r.status == "active"
    assert p.chapters[0].rule_nos == ["R9", "R15"]
    assert p.new_terms[0].name == "幂等键"
