"""项目 CRUD / 删除 / 状态总览。"""
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, select

from app import db as dbmod
from app.db import get_session
from app.models import (
    Baseline,
    ChangeLog,
    DocDraft,
    DocVersion,
    Material,
    Project,
    Question,
    Rule,
    Term,
)
from app.services.doc_state import derive_requirement_status
from app.services.validators import VERSION_RE

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    version: str | None = None
    status: str | None = None


# 项目状态合法转移(治理开关):进行中↔暂停、进行中/暂停→结项、结项→进行中(重开)
TRANSITIONS = {
    "in_progress": {"paused", "closed"},
    "paused": {"in_progress", "closed"},
    "closed": {"in_progress"},
}
PROJECT_STATUSES = set(TRANSITIONS)


def _assert_name_free(db: Session, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Project).where(Project.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Project.id != exclude_id)
    if db.exec(stmt).first() is not None:
        raise HTTPException(409, {"code": "DUP_NAME", "name": name})


def _get_or_404(db: Session, pid: int) -> Project:
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    return proj


def assert_writable(db: Session, pid: int) -> None:
    """写守卫:项目不存在 404;非进行中(已暂停/已结项)只读,拒收一切写操作。"""
    proj = _get_or_404(db, pid)
    if proj.status != "in_progress":
        raise HTTPException(409, {"code": "PROJECT_READ_ONLY", "status": proj.status})


def _stats(db: Session, pid: int) -> dict:
    materials = len(db.exec(select(Material.id).where(Material.project_id == pid)).all())
    pending = len(
        db.exec(
            select(Question.id).where(Question.project_id == pid, Question.status == "pending")
        ).all()
    )
    base = db.get(Baseline, pid)
    version = base.version if base and base.version else None
    has_draft = (
        db.exec(
            select(DocDraft.id)
            .where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
            .limit(1)
        ).first()
        is not None
    )
    return {
        "materials": materials,
        "pending_annos": pending,
        "version": version,
        "draft_status": "reviewing" if has_draft else None,
        "requirement_status": derive_requirement_status(db, pid),
    }


def _proj_out(db: Session, proj: Project) -> dict:
    return {
        "id": proj.id,
        "name": proj.name,
        "description": proj.description,
        "status": proj.status,
        "version": proj.version,
        "created_at": proj.created_at.isoformat(),
        "stats": _stats(db, proj.id),
    }


@router.get("")
def list_projects(db: Session = Depends(get_session)):
    projs = db.exec(select(Project)).all()
    return [_proj_out(db, p) for p in projs]


@router.post("")
def create_project(body: ProjectIn, db: Session = Depends(get_session)):
    if not body.name.strip():
        raise HTTPException(422, "name required")
    name = body.name.strip()
    _assert_name_free(db, name)
    proj = Project(name=name, description=body.description)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return _proj_out(db, proj)


@router.get("/{pid}")
def get_project(pid: int, db: Session = Depends(get_session)):
    return _proj_out(db, _get_or_404(db, pid))


@router.patch("/{pid}")
def patch_project(pid: int, body: ProjectPatch, db: Session = Depends(get_session)):
    proj = _get_or_404(db, pid)
    orig_status = proj.status  # 守卫与转移校验均以进入时状态为准,不被本请求的赋值毒化
    # 治理字段先校验后赋值(与内容赋值分离):状态切换是治理动作,只读态可执行(恢复/重开入口)
    if body.status is not None:
        if body.status not in PROJECT_STATUSES:
            raise HTTPException(422, f"invalid status: {body.status}")
        if body.status != orig_status and body.status not in TRANSITIONS[orig_status]:
            raise HTTPException(
                409, {"code": "INVALID_STATUS_TRANSITION",
                      "from": orig_status, "to": body.status})
    # 内容字段(name/description/version):只读态拦截;本请求同时恢复/重开(in_progress)则放行
    if body.name is not None or body.description is not None or body.version is not None:
        if orig_status != "in_progress" and body.status != "in_progress":
            raise HTTPException(409, {"code": "PROJECT_READ_ONLY", "status": orig_status})
        if body.name is not None:
            if not body.name.strip():
                raise HTTPException(422, "name required")
            name = body.name.strip()
            _assert_name_free(db, name, exclude_id=pid)
            proj.name = name
        if body.description is not None:
            proj.description = body.description
        if body.version is not None:
            if not VERSION_RE.match(body.version.strip()):
                raise HTTPException(422, {"code": "VERSION_FORMAT", "version": body.version})
            proj.version = body.version.strip()
    if body.status is not None:
        proj.status = body.status
    db.add(proj)
    db.commit()
    return _proj_out(db, proj)


@router.delete("/{pid}")
def delete_project(pid: int, db: Session = Depends(get_session)):
    proj = _get_or_404(db, pid)
    # 外键无 CASCADE 且生产库 foreign_keys=ON:DocVersion.draft_id 指向 DocDraft,必须先删
    for model in (DocVersion, DocDraft, Baseline, ChangeLog, Question, Rule, Term, Material):
        db.execute(delete(model).where(model.project_id == pid))
    db.delete(proj)
    db.commit()
    # 先库后文件:库是唯一真相源,目录残留只是可清理的孤儿
    shutil.rmtree(dbmod.DATA_DIR / str(pid), ignore_errors=True)
    return {"ok": True}
