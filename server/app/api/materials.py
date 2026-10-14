"""材料上传(sha256 去重)与列表(agent 消费口)。"""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlmodel import Session, select

from app.db import DATA_DIR, get_session
from app.models import Material, Project
from app.parsers.extract import extract_text

router = APIRouter(prefix="/api/v1/projects/{pid}/materials", tags=["materials"])


def _mat_out(m: Material) -> dict:
    return {
        "id": m.id,
        "filename": m.filename,
        "type": Path(m.filename).suffix.lower().lstrip(".") or "bin",
        "sha256": m.sha256,
        "size": m.size,
        "parsed_text": m.parsed_text,
        "created_at": m.created_at.isoformat(),
    }


@router.post("")
def upload_material(pid: int, file: UploadFile, db: Session = Depends(get_session)):
    if db.get(Project, pid) is None:
        raise HTTPException(404, "project not found")
    data = file.file.read()
    sha = hashlib.sha256(data).hexdigest()

    existing = db.exec(
        select(Material).where(Material.project_id == pid, Material.sha256 == sha)
    ).first()
    if existing is not None:  # 材料只增不改:同 hash 拒收并指向原记录
        raise HTTPException(409, {"code": "DUPLICATE_MATERIAL", "material_id": existing.id})

    suffix = Path(file.filename or "blob").suffix.lower() or ".bin"
    store_dir = DATA_DIR / str(pid) / "materials"
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / f"{sha}{suffix}"
    path.write_bytes(data)

    m = Material(
        project_id=pid,
        filename=file.filename or path.name,
        path=str(path),
        sha256=sha,
        mime_type=file.content_type or "",
        size=len(data),
        parsed_text=extract_text(file.filename or "", data),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _mat_out(m)


@router.get("")
def list_materials(pid: int, db: Session = Depends(get_session)):
    if db.get(Project, pid) is None:
        raise HTTPException(404, "project not found")
    mats = db.exec(
        select(Material).where(Material.project_id == pid).order_by(Material.id)
    ).all()
    return [_mat_out(m) for m in mats]
