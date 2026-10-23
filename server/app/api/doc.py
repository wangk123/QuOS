"""基线/草案/版本读取与草案提交(校验闸门 + 覆盖语义)。"""
import json
import re
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.projects import assert_writable
from app.api.questions import QuestionIn
from app.db import get_session
from app.models import (Baseline, ChangeLog, DocDraft, DocPayload, DocVersion,
                        Material, Project, Question, Rule, Term)
from app.services.diagram_check import check_diagram, is_html_form
from app.services.md_import import detect_format_issues, detect_format_soft, md_to_payload
from app.services.validators import check_draft

router = APIRouter(prefix="/api/v1/projects/{pid}/doc", tags=["doc"])

ONE_PAGER_MAX = 65536  # 伴生一页纸上限,防 agent 误塞整份文档


def _check_one_pager(op: str | None) -> str | None:
    """导入与手工提交同闸门:类型/超长整体拒收(草案不入库)。"""
    if op is not None and not isinstance(op, str):
        raise HTTPException(422, {"hard_errors": [
            {"code": "ONE_PAGER_TOO_LARGE", "detail": "one_pager_md 须为字符串"}
        ]})
    if op is not None and len(op) > ONE_PAGER_MAX:
        raise HTTPException(422, {"hard_errors": [
            {"code": "ONE_PAGER_TOO_LARGE",
             "detail": f"one_pager_md {len(op)} 字符超过上限 {ONE_PAGER_MAX}"}
        ]})
    return op


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
            "note": ver.note, "one_pager_md": ver.one_pager_md}


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
            "check_report": draft.check_report, "created_at": draft.created_at.isoformat(),
            "one_pager_md": draft.one_pager_md}


@router.get("/versions")
def list_versions(pid: int, db: Session = Depends(get_session)):
    _get_project(db, pid)
    vers = db.exec(
        select(DocVersion).where(DocVersion.project_id == pid).order_by(DocVersion.id.desc())
    ).all()
    return [{"version": v.version, "note": v.note, "created_at": v.created_at.isoformat()}
            for v in vers]


@router.post("/draft/import")
async def import_draft(pid: int, db: Session = Depends(get_session),
                       md: UploadFile = File(...),
                       figures: list[UploadFile] = File(default=[]),
                       rules_meta: str | None = Form(None),
                       one_pager_md: str | None = Form(None)):
    """markdown 直接导入(multipart:md 全文 + figures 图文件集):平台内置转换(md→DocPayload,
    整行图引用收图内容进 diagram 块),后续走与 POST /draft 完全相同的校验与落库。
    硬软分流:HTML 图结构非法/引用闭合失败 422;存量 mermaid 图源与未引用图文件走软警告。"""
    assert_writable(db, pid)
    materials = {
        m.id: m for m in db.exec(select(Material).where(Material.project_id == pid)).all()
    }
    md_text = (await md.read()).decode("utf-8", errors="replace")
    fig_map = {f"figures/{f.filename}": (await f.read()).decode("utf-8", errors="replace")
               for f in figures if f.filename}
    rules_meta_obj = None
    if rules_meta:
        try:
            rules_meta_obj = json.loads(rules_meta)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, {"hard_errors": [{
                "code": "FORMAT_CONTRACT",
                "detail": f"rules_meta 非合法 JSON: {exc.msg} (line {exc.lineno})"}]})
    payload, questions = md_to_payload(md_text, materials, rules_meta_obj, fig_map)
    # 转换层同款结构校验:附录一行式载体只承载题面,选择题无选项载体——422 打回而非静默入库
    # (导入转换直插 question 表,不走 POST /questions 的 semantic_err,此处补同一道闸)
    bad_qs = []
    for i, q in enumerate(questions, 1):
        err = QuestionIn(kind=q["kind"], payload=q["payload"], anchor=q["anchor"]).semantic_err()
        if err:
            bad_qs.append(f"第{i}条[{q['payload'].get('klabel', q['kind'])}]: {err}")
    if bad_qs:
        raise HTTPException(422, {"hard_errors": [{
            "code": "QUESTION_FORMAT",
            "detail": "附录A待确认清单转换出结构非法的批注: " + "; ".join(bad_qs)
                      + " | md 一行式清单只支持填空/确认;选择题(需选项)请经 post-questions 提交"}]})
    # fail fast:格式契约违规与图结构非法导入即拒收,agent 修复后重导(全程无人工)
    hard = [{"code": "FORMAT_CONTRACT", "detail": w}
            for w in detect_format_issues(md_text, set(fig_map))]
    extra_soft: list[dict] = []
    for ch in payload.chapters:
        for b in ch.blocks:
            if b.type != "diagram" or not is_html_form(b.text):
                continue
            for err in check_diagram(b.text):   # 非 HTML 形态(存量 mermaid)由 check_draft 统一出软警告
                hard.append({"code": "DIAGRAM_CHECK",
                             "detail": f"章节[{ch.title}]图块: {err} | 源码: {b.text[:60]}"})
    extra_soft += [{"code": "DIAGRAM_ORPHAN", "rule_no": None, "detail": w}
                   for w in detect_format_soft(md_text, set(fig_map))]
    if hard:
        raise HTTPException(422, {"hard_errors": hard})
    out = _persist_draft(db, pid, payload, extra_soft=extra_soft,
                         one_pager_md=_check_one_pager(one_pager_md))
    # 附录 A 待确认问题清单 → agent 批注(锚定正文;与现存同题去重)
    if questions:
        # 挂当前草案:需求状态派生按 reviewing 草案名下批注计数(_persist_draft 已先行落库)
        cur_draft = db.exec(
            select(DocDraft).where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
        ).first()
        # 去重语义:pending/answered 不重复插;withdrawn(因旧草案覆盖被撤)的同内容题复活——
        # 重导意味着这批待确认问题仍然有效,不能被「撤回后不重复问」吞掉
        olds = db.exec(select(Question).where(Question.project_id == pid)).all()
        existing = {(q.kind, q.payload.get("q", "")): q for q in olds}
        for q in questions:
            key = (q["kind"], q["payload"]["q"])
            anchor = dict(q["anchor"])
            if anchor.get("rule_no") and not anchor.get("chapter_id"):
                for ch in payload.model_dump()["chapters"]:
                    if anchor["rule_no"] in ch["rule_nos"]:
                        anchor["chapter_id"] = ch["id"]
                        break
            elif not anchor.get("chapter_id"):
                # 无规则号可锚:题号在正文以【TBD-xx】标注出现的章 → 锚到该章(批注卡挂章节旁,定位可滚)
                tno = anchor.get("seg") or ""
                pat = re.compile(tno + r"(?!\d)") if tno else None
                for ch in payload.model_dump()["chapters"]:
                    blob = ch["background"] + ' '.join(
                        str(b.get("text", "")) + ' ' + ' '.join(str(c) for r in b.get("rows", []) for c in r)
                        + ' ' + ' '.join(b.get("flows", []) + b.get("items", []))
                        for b in ch["blocks"])
                    if pat and pat.search(blob):   # 【TBD-xx】/(见 TBD-xx)/裸 TBD-xx 均命中
                        anchor.update({"chapter_id": ch["id"], "chapter": True})
                        break
                    hit_rule = next((no for no in ch["rule_nos"]
                                     if pat.search(payload.model_dump()["rules"].get(no, {}).get("text", ""))), None)
                    if hit_rule:                    # 标注在规则行内 → 锚到该规则(正文规则行高亮)
                        anchor.update({"chapter_id": ch["id"], "rule_no": hit_rule, "seg": tno})
                        break
            if key in existing:
                old_q = existing[key]
                if old_q.status == "withdrawn" and old_q.source == "agent":
                    old_q.status = "pending"
                    old_q.anchor = anchor   # 复活同时刷新锚定(重导可能改进了锚定策略)
                    old_q.draft_id = cur_draft.id if cur_draft else None
                    db.add(old_q)
                continue
            nq = Question(project_id=pid, kind=q["kind"], payload=q["payload"],
                          anchor=anchor, status="pending", source="agent",
                          draft_id=cur_draft.id if cur_draft else None)
            db.add(nq)
            existing[key] = nq
        db.commit()
    return out


@router.post("/draft")
def submit_draft(pid: int, body: dict, db: Session = Depends(get_session)):
    assert_writable(db, pid)
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

    return _persist_draft(db, pid, payload, report,
                          one_pager_md=_check_one_pager(body.pop("one_pager_md", None)))


def _persist_draft(db: Session, pid: int, payload: DocPayload, report=None,
                   one_pager_md: str | None = None, extra_soft: list[dict] | None = None):
    if report is None:
        rules_existing = {
            r.no: r.status for r in db.exec(select(Rule).where(Rule.project_id == pid)).all()
        }
        materials = {
            m.id: m for m in db.exec(select(Material).where(Material.project_id == pid)).all()
        }
        terms = {t.name for t in db.exec(select(Term).where(Term.project_id == pid)).all()}
        report = check_draft(payload, rules_existing, materials, terms)
        if report.hard_errors:
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

    draft = DocDraft(project_id=pid, payload=payload.model_dump(), status="reviewing",
                     one_pager_md=one_pager_md)
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
        "soft_warnings": [{"code": w.code, "rule_no": w.rule_no, "detail": w.detail}
                          for w in report.soft_warnings]
        + (extra_soft or []),
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
    assert_writable(db, pid)
    from app.services import snapshots
    ver = snapshots.finalize(db, pid, body.draft_id, body.version, body.note)
    return {"version": ver.version, "note": ver.note}


class RevertBody(BaseModel):
    version: str


@router.post("/revert")
def revert_baseline(pid: int, body: RevertBody, db: Session = Depends(get_session)):
    assert_writable(db, pid)
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
