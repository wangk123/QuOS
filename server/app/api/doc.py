"""基线/草案/版本读取与草案提交(校验闸门 + 覆盖语义)。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import (Baseline, ChangeLog, DocDraft, DocPayload, DocVersion,
                        Material, Project, Question, Rule, Term)
from app.services.validators import check_draft

router = APIRouter(prefix="/api/v1/projects/{pid}/doc", tags=["doc"])


def _get_project(db: Session, pid: int) -> Project:
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    return proj


@router.get("/baseline")
def get_baseline(pid: int, db: Session = Depends(get_session)):
    _get_project(db, pid)
    base = db.get(Baseline, pid)
    if base is None or not base.version:
        return {"empty": True}
    ver = db.exec(
        select(DocVersion).where(DocVersion.project_id == pid, DocVersion.version == base.version)
    ).first()
    if ver is None:
        return {"empty": True}
    return {"empty": False, "version": ver.version, "snapshot": ver.snapshot,
            "note": ver.note}


@router.get("/draft")
def get_draft(pid: int, db: Session = Depends(get_session)):
    _get_project(db, pid)
    draft = db.exec(
        select(DocDraft)
        .where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
        .order_by(DocDraft.id.desc())
    ).first()
    if draft is None:
        return {"empty": True}
    return {"draft_id": draft.id, "status": draft.status, "payload": draft.payload,
            "check_report": draft.check_report, "created_at": draft.created_at.isoformat()}


@router.get("/versions")
def list_versions(pid: int, db: Session = Depends(get_session)):
    _get_project(db, pid)
    vers = db.exec(
        select(DocVersion).where(DocVersion.project_id == pid).order_by(DocVersion.id.desc())
    ).all()
    return [{"version": v.version, "note": v.note, "created_at": v.created_at.isoformat()}
            for v in vers]


@router.post("/draft")
def submit_draft(pid: int, body: dict, db: Session = Depends(get_session)):
    _get_project(db, pid)
    try:
        payload = DocPayload.model_validate(body)
    except Exception as exc:
        raise HTTPException(422, {"hard_errors": [{"code": "SCHEMA", "detail": str(exc)}]})

    rules_existing = {
        r.no: r.status for r in db.exec(select(Rule).where(Rule.project_id == pid)).all()
    }
    materials = {
        m.id: m for m in db.exec(select(Material).where(Material.project_id == pid)).all()
    }
    terms = {t.name for t in db.exec(select(Term).where(Term.project_id == pid)).all()}

    report = check_draft(payload, rules_existing, materials, terms)
    if report.hard_errors:
        # 硬错误整体拒收:草案不入库(422 携带明细)
        raise HTTPException(422, {"hard_errors": [
            {"code": e.code, "rule_no": e.rule_no, "detail": e.detail} for e in report.hard_errors
        ]})

    # ── 覆盖语义(事务):旧 reviewing → superseded,其 pending 批注撤回;answered 存续 ──
    old = db.exec(
        select(DocDraft).where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
    ).all()
    old_ids = [d.id for d in old]
    for d in old:
        d.status = "superseded"
        db.add(d)
    if old_ids:
        for q in db.exec(
            select(Question).where(Question.project_id == pid, Question.status == "pending")
        ).all():
            q.status = "withdrawn"
            db.add(q)

    draft = DocDraft(project_id=pid, payload=payload.model_dump(), status="reviewing")
    db.add(draft)
    try:
        db.flush()  # 拿 draft_id 供批注关联;并发撞单 reviewing 唯一索引在此抛出
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "SINGLE_REVIEWING",
                                   "detail": "并发提交,项目已存在 reviewing 草案"})

    # 软警告转批注落库:题型+关键内容与现存 pending auto 去重
    existing_keys = {
        (q.kind, q.payload.get("q", ""))
        for q in db.exec(
            select(Question).where(Question.project_id == pid, Question.source == "auto")
        ).all()
    }  # 去重键含 withdrawn 的 auto 题:撤回后不得就同内容重复出题
    for aq in report.auto_questions:
        key = (aq.kind, aq.payload.get("q", ""))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        db.add(Question(
            project_id=pid, kind=aq.kind, payload=aq.payload, anchor=aq.anchor,
            status="pending", source="auto", draft_id=draft.id,
        ))

    check_report = {
        "soft_warnings": [{"code": w.code, "rule_no": w.rule_no} for w in report.soft_warnings],
        "auto_questions": [q.payload for q in report.auto_questions],
    }
    draft.check_report = check_report
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return {"draft_id": draft.id, "status": draft.status, "check_report": check_report}


class FinalizeBody(BaseModel):
    draft_id: int
    version: str
    note: str = ""


@router.post("/finalize")
def finalize_draft(pid: int, body: FinalizeBody, db: Session = Depends(get_session)):
    _get_project(db, pid)
    from app.services import snapshots
    ver = snapshots.finalize(db, pid, body.draft_id, body.version, body.note)
    return {"version": ver.version, "note": ver.note}


class RevertBody(BaseModel):
    version: str


@router.post("/revert")
def revert_baseline(pid: int, body: RevertBody, db: Session = Depends(get_session)):
    _get_project(db, pid)
    from app.services import snapshots
    snapshots.revert(db, pid, body.version)
    return {"ok": True, "baseline": body.version}


@router.get("/changes")
def list_changes(pid: int, version: str | None = None, db: Session = Depends(get_session)):
    _get_project(db, pid)
    stmt = select(ChangeLog).where(ChangeLog.project_id == pid).order_by(ChangeLog.id)
    if version:
        stmt = stmt.where(ChangeLog.version == version)
    return [{
        "version": c.version, "rule_no": c.rule_no, "kind": c.kind,
        "old_text": c.old_text, "new_text": c.new_text,
        "reason": c.reason, "approver": c.approver,
        "created_at": c.created_at.isoformat(),
    } for c in db.exec(stmt).all()]
