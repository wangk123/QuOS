"""项目 CRUD / 归档恢复 / 状态总览。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Baseline, DocDraft, DocVersion, Material, Project, Question

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None


def _get_or_404(db: Session, pid: int) -> Project:
    proj = db.get(Project, pid)
    if proj is None:
        raise HTTPException(404, "project not found")
    return proj


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
    }


def _proj_out(db: Session, proj: Project) -> dict:
    return {
        "id": proj.id,
        "name": proj.name,
        "description": proj.description,
        "archived": proj.archived,
        "created_at": proj.created_at.isoformat(),
        "stats": _stats(db, proj.id),
    }


@router.get("")
def list_projects(archived: bool = False, db: Session = Depends(get_session)):
    projs = db.exec(select(Project).where(Project.archived == archived)).all()
    return [_proj_out(db, p) for p in projs]


@router.post("")
def create_project(body: ProjectIn, db: Session = Depends(get_session)):
    if not body.name.strip():
        raise HTTPException(422, "name required")
    proj = Project(name=body.name.strip(), description=body.description)
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
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, "name required")
        proj.name = body.name.strip()
    if body.description is not None:
        proj.description = body.description
    db.add(proj)
    db.commit()
    return _proj_out(db, proj)


@router.post("/{pid}/archive")
def archive_project(pid: int, db: Session = Depends(get_session)):
    proj = _get_or_404(db, pid)
    proj.archived = True
    db.add(proj)
    db.commit()
    return {"ok": True}


@router.post("/{pid}/restore")
def restore_project(pid: int, db: Session = Depends(get_session)):
    proj = _get_or_404(db, pid)
    proj.archived = False
    db.add(proj)
    db.commit()
    return {"ok": True}
