# server/app/api/projects.py
# 项目管理端点：同步 def（pymysql 阻塞调用交 FastAPI 线程池）。
# 真相源是文件系统扫描，db.* 仅补动态列（last_opened_at）与对账。
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage import db, project

projects_router = APIRouter()


class CreateIn(BaseModel):
    name: str
    description: str = ""


class PatchIn(BaseModel):
    description: Optional[str] = None


def _slug_path(slug: str) -> None:
    """path 合法性与存在性的公共校验（不存在统一 404）"""
    if not project.is_valid_name(slug) or project.slugify(slug) != slug:
        raise HTTPException(status_code=422, detail=f"非法项目标识: {slug}")


@projects_router.get("")
def list_projects():
    rows = project.scan("active")
    extra = db.reconcile([{**r, "status": "active"} for r in rows])
    out = [{**r, "last_opened_at": extra.get(r["slug"], {}).get("last_opened_at")}
           for r in rows]
    out.sort(key=lambda r: r["last_opened_at"] or "", reverse=True)
    return out


@projects_router.get("/archived")
def list_archived():
    rows = project.scan("archived")
    db.reconcile([{**r, "status": "archived"} for r in rows])  # 归档侧也对账，防幽灵
    return rows


@projects_router.post("", status_code=201)
def create_project(body: CreateIn):
    if not project.is_valid_name(body.name):
        raise HTTPException(status_code=422, detail=f"非法项目名: {body.name}")
    if len(project.slugify(body.name)) > 191:  # VARCHAR(191) 上限，防超长 slug 毒化 reconcile
        raise HTTPException(status_code=422, detail="项目名过长")
    try:
        row = project.create(body.name, body.description)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.reconcile([{**row, "status": "active"}])
    return row


@projects_router.post("/{slug}/open", status_code=204)
def open_project(slug: str):
    _slug_path(slug)
    try:
        project.require_root(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {e}")
    db.touch_opened(slug)


@projects_router.patch("/{slug}")
def patch_project(slug: str, body: PatchIn):
    _slug_path(slug)
    try:
        project.require_root(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在或已归档: {e}")
    if body.description is not None:
        project.write_description(slug, body.description)
    return {"slug": slug, "description": body.description}


@projects_router.post("/{slug}/archive", status_code=204)
def archive_project(slug: str):
    _slug_path(slug)
    try:
        project.archive(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"项目不存在: {e}")
    db.delete_row(slug)


@projects_router.post("/{slug}/restore", status_code=204)
def restore_project(slug: str):
    _slug_path(slug)
    try:
        project.restore(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"归档项目不存在: {e}")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@projects_router.delete("/{slug}", status_code=204)
def purge_project(slug: str):
    _slug_path(slug)
    try:
        project.purge(slug)
    except project.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=f"归档项目不存在: {e}")
    except ValueError:
        raise HTTPException(status_code=409, detail="仅归档项目可彻底删除")
    db.delete_row(slug)
