"""发版与版本化:快照、条款级 ChangeLog、Rule/Term 同步、auto 批注撤回、回退。

口径(design §4.5 + §6):
- 与「当前基线」逐规则比对(非最新版);作废以草案显式声明为准,基线有而草案无=未声明移除也记 voided;
- reason 优先取项目内全部 answered 批注中同 rule_no 的答案(跨草案),缺省材料文件名/草案说明;
- 变更记录只覆盖规则层,章节文本变更不进 ChangeLog;
- 发版全程单事务。
"""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (Baseline, ChangeLog, DocDraft, DocPayload, DocVersion,
                        Material, Question, Rule, Term)


def _answer_text(answer: dict | None) -> str:
    if not answer:
        return ""
    for key in ("text", "key", "note"):
        if answer.get(key):
            return str(answer[key])
    return ""


def _diff_rules(db: Session, pid: int, payload: DocPayload, prev: DocVersion | None,
                note: str) -> list[ChangeLog]:
    rows: list[ChangeLog] = []
    prev_rules: dict = (prev.snapshot or {}).get("rules", {}) if prev else {}
    answered = {
        q.anchor.get("rule_no"): q for q in db.exec(
            select(Question).where(Question.project_id == pid, Question.status == "answered")
        ).all() if q.anchor.get("rule_no")
    }
    mats = {m.id: m.filename for m in db.exec(
        select(Material).where(Material.project_id == pid)).all()}

    def reason_for(no: str, default: str) -> str:
        q = answered.get(no)
        return _answer_text(q.answer if q else None) or default

    for no, r in payload.rules.items():
        if r.status == "voided":
            if no in prev_rules and prev_rules[no].get("status") != "voided":
                rows.append(ChangeLog(
                    project_id=pid, version="", rule_no=no, kind="voided",
                    old_text=prev_rules[no].get("text", ""), new_text="",
                    reason=reason_for(no, r.replaced_by and f"由 {r.replaced_by} 替代" or note)))
            continue
        prev_r = prev_rules.get(no) if prev else None
        if prev_r is None or prev_r.get("status") == "voided":
            default = mats.get(r.material_id, "") if not prev else note
            rows.append(ChangeLog(project_id=pid, version="", rule_no=no, kind="added",
                                  new_text=r.text,
                                  reason=reason_for(no, default)))
        elif prev_r.get("text", "") != r.text:
            rows.append(ChangeLog(project_id=pid, version="", rule_no=no, kind="modified",
                                  old_text=prev_r.get("text", ""), new_text=r.text,
                                  reason=reason_for(no, note)))
    # 基线 active 而草案未出现且未声明作废 → 未声明移除
    if prev:
        for no, prev_r in prev_rules.items():
            if prev_r.get("status") != "voided" and no not in payload.rules:
                rows.append(ChangeLog(
                    project_id=pid, version="", rule_no=no, kind="voided",
                    old_text=prev_r.get("text", ""),
                    reason="草案未声明移除"))
    return rows


def _sync_rule_table(db: Session, pid: int, payload: DocPayload) -> None:
    for r in db.exec(select(Rule).where(Rule.project_id == pid)).all():
        db.delete(r)
    for no, r in payload.rules.items():
        db.add(Rule(project_id=pid, no=no, text=r.text, violation=r.violation,
                    quote=r.quote, material_id=r.material_id, status=r.status,
                    replaced_by=r.replaced_by))


def _rebuild_terms(db: Session, pid: int, payload: DocPayload) -> None:
    for t in db.exec(select(Term).where(Term.project_id == pid)).all():
        db.delete(t)
    for g in payload.glossary:
        db.add(Term(project_id=pid, name=g.name, definition=g.definition))


def finalize(db: Session, pid: int, draft_id: int, version: str, note: str) -> DocVersion:
    draft = db.get(DocDraft, draft_id)
    if draft is None or draft.project_id != pid:
        raise HTTPException(404, "draft not found")
    if draft.status != "reviewing":
        raise HTTPException(409, {"code": "NOT_REVIEWING", "status": draft.status})
    if not version.strip():
        raise HTTPException(422, "version required")
    version = version.strip()
    dup = db.exec(
        select(DocVersion).where(DocVersion.project_id == pid, DocVersion.version == version)
    ).first()
    if dup is not None:
        raise HTTPException(409, {"code": "DUP_VERSION", "version": version})

    payload = DocPayload.model_validate(draft.payload)
    base = db.get(Baseline, pid)
    prev = None
    if base and base.version:
        prev = db.exec(
            select(DocVersion)
            .where(DocVersion.project_id == pid, DocVersion.version == base.version)
        ).first()

    rows = _diff_rules(db, pid, payload, prev, note or "收敛草案")
    ver = DocVersion(project_id=pid, version=version, snapshot=payload.model_dump(),
                     draft_id=draft.id, note=note)
    db.add(ver)
    try:
        db.flush()  # 唯一约束在此先于 commit 触发(并发同号)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "DUP_VERSION", "version": version})
    for row in rows:
        row.version = version
        db.add(row)

    _sync_rule_table(db, pid, payload)
    _rebuild_terms(db, pid, payload)

    # 本草案未答的自动批注撤回;agent 提交批注保留
    for q in db.exec(
        select(Question).where(
            Question.project_id == pid, Question.status == "pending",
            Question.source == "auto", Question.draft_id == draft.id)
    ).all():
        q.status = "withdrawn"
        db.add(q)

    if base is None:
        base = Baseline(project_id=pid, version=version)
    else:
        base.version = version
    db.add(base)
    draft.status = "finalized"
    db.add(draft)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "DUP_VERSION", "version": version})
    db.refresh(ver)
    return ver


def revert(db: Session, pid: int, version: str) -> None:
    ver = db.exec(
        select(DocVersion)
        .where(DocVersion.project_id == pid, DocVersion.version == version)
    ).first()
    if ver is None:
        raise HTTPException(404, "version not found")
    base = db.get(Baseline, pid)
    if base is None:
        base = Baseline(project_id=pid)
    base.version = version
    db.add(base)
    # Rule/Term 随基线回滚:后续草案与该版比对、术语校验均以当前态为准
    payload = DocPayload.model_validate(ver.snapshot)
    _sync_rule_table(db, pid, payload)
    _rebuild_terms(db, pid, payload)
    db.commit()
