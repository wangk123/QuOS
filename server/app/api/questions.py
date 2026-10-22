"""批注 API:列表(T5 提前实现,覆盖语义可观察);提交与作答在 T6 补全。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.api.projects import assert_writable
from app.models import DocDraft, Project, Question

router = APIRouter(prefix="/api/v1", tags=["questions"])


def _q_out(q: Question) -> dict:
    return {
        "id": q.id,
        "batch_id": q.batch_id,
        "kind": q.kind,
        "payload": q.payload,
        "anchor": q.anchor,
        "status": q.status,
        "answer": q.answer,
        "answered_at": q.answered_at.isoformat() if q.answered_at else None,
        "source": q.source,
        "draft_id": q.draft_id,
        "created_at": q.created_at.isoformat(),
    }


@router.get("/projects/{pid}/questions")
def list_questions(pid: int, status: str | None = None, db: Session = Depends(get_session)):
    if db.get(Project, pid) is None:
        raise HTTPException(404, "project not found")
    stmt = select(Question).where(Question.project_id == pid).order_by(Question.id)
    if status:
        stmt = stmt.where(Question.status == status)
    return [_q_out(q) for q in db.exec(stmt).all()]


# ── 批量提交与作答(T6) ──
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, field_validator


class QuestionIn(BaseModel):
    kind: str
    payload: dict
    anchor: dict

    @field_validator("kind")
    @classmethod
    def _kind_limited(cls, v: str) -> str:
        if v not in {"choice", "confirm", "fill", "scan"}:
            raise ValueError("kind 必须是 choice/confirm/fill/scan")
        return v

    def semantic_err(self) -> str | None:
        """结构校验:返回错误原因,None=通过。坏结构在入库前 422 打回,agent 按明细修复重交。"""
        q = str(self.payload.get("q", "")).strip()
        if self.kind == "choice":
            opts = self.payload.get("options") or []
            if len(opts) < 2:
                return "choice 需 ≥2 options"
            for i, o in enumerate(opts):
                if not (isinstance(o, dict) and str(o.get("k", "")).strip()
                        and str(o.get("t", "")).strip()):
                    return (f"choice options[{i}] 须为 {{k, t}} 对象(k=选项键,t=文案),"
                            f"当前: {o!r}"[:120])
        elif self.kind == "fill":
            if not q:
                return "fill 需非空 q"
        return None


@router.post("/projects/{pid}/questions")
def submit_questions(pid: int, items: list[QuestionIn], db: Session = Depends(get_session)):
    assert_writable(db, pid)
    for i, it in enumerate(items):
        err = it.semantic_err()
        if err:
            raise HTTPException(422, f"批注校验失败[第{i + 1}条 {it.kind}]: {err}")
    batch = uuid4().hex[:12]
    reviewing = db.exec(
        select(DocDraft)
        .where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
        .order_by(DocDraft.id.desc())
    ).first()
    out = []
    for it in items:
        q = Question(project_id=pid, batch_id=batch, kind=it.kind, payload=it.payload,
                     anchor=it.anchor, status="pending", source="agent",
                     draft_id=reviewing.id if reviewing else None)
        db.add(q)
        out.append(q)
    db.commit()
    for q in out:
        db.refresh(q)
    return [_q_out(q) for q in out]


class AnswerBody(BaseModel):
    answer: dict


@router.post("/questions/{qid}/answer")
def answer_question(qid: int, body: AnswerBody, db: Session = Depends(get_session)):
    q = db.get(Question, qid)
    if q is None:
        raise HTTPException(404, "question not found")
    if q.status == "withdrawn":
        raise HTTPException(409, "question withdrawn")
    assert_writable(db, q.project_id)  # 作答属写操作:经批注反查项目,只读态拒收
    # pending/answered 均可作答:重新作答=覆盖(scan 逐项提交依赖此语义)
    q.status = "answered"
    q.answer = body.answer
    q.answered_at = datetime.now(timezone.utc)
    db.add(q)
    db.commit()
    db.refresh(q)
    return _q_out(q)
