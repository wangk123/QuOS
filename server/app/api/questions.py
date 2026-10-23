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
        """结构校验:返回错误原因,None=通过。坏结构在入库前 422 打回,agent 按明细修复重交。
        q 为所有题型必填(题面即问题本体);options 仅 choice 需要,元素须 {k, t} 对象。"""
        q = str(self.payload.get("q", "")).strip()
        if not q:
            # 常见错误:字段名误用 question/label 等——提示到位,一轮修复
            alt = [k for k in ("question", "label", "text") if str(self.payload.get(k, "")).strip()]
            hint = f"(文本似乎误写在 {alt[0]!r} 字段,契约字段名为 q)" if alt else ""
            return f"{self.kind} 题的 payload.q 必填且非空{hint}"
        if self.kind == "choice":
            opts = self.payload.get("options")
            if not isinstance(opts, list) or len(opts) < 2:
                return "choice options 须为 ≥2 元素的数组"
            for i, o in enumerate(opts):
                if not (isinstance(o, dict) and str(o.get("k", "")).strip()
                        and str(o.get("t", "")).strip()):
                    return (f"choice options[{i}] 须为 {{k, t}} 对象(k=选项键,t=文案),"
                            f"当前: {o!r}"[:120])
            ks = [str(o["k"]).strip() for o in opts]
            if len(set(ks)) != len(ks):
                dup = sorted({x for x in ks if ks.count(x) > 1})
                return f"choice options 选项键重复: {dup}(作答按选项键回填,键须唯一)"
        elif self.kind == "scan":
            items = self.payload.get("items")
            if (not isinstance(items, list) or not items
                    or any(not isinstance(it, str) or not it.strip() for it in items)):
                return "scan 题的 payload.items 须为非空字符串数组(逐项核对清单)"
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


@router.post("/questions/{qid}/reopen")
def reopen_question(qid: int, db: Session = Depends(get_session)):
    """重新作答:已答批注重开为 pending 并清空旧答案。评审页「重新作答」的持久化入口
    (此前仅前端本地态,刷新即回弹);agent 消歧循环用 answer 覆盖语义即可,无需先重开。"""
    q = db.get(Question, qid)
    if q is None:
        raise HTTPException(404, "question not found")
    if q.status == "withdrawn":
        raise HTTPException(409, "question withdrawn")
    if q.status != "answered":
        raise HTTPException(409, "仅已答批注可重开")
    assert_writable(db, q.project_id)
    q.status = "pending"
    q.answer = None
    q.answered_at = None
    db.add(q)
    db.commit()
    db.refresh(q)
    return _q_out(q)


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
