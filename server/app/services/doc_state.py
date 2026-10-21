"""需求状态派生(展示层,不改管线行为)。

两轴正交(状态设计 v1,2026-10-21):项目状态=能不能写(治理开关);
需求状态=等谁——平台按事实派生,五态:
- idle          未开始:无草案无基线(人备料/唤起 agent)
- in_review     待评审:草案存在且有待答批注(人作答)
- await_resubmit 待重交:批注答完,答案待 agent 消费重交
- await_finalize 待定稿:草案存在,无人待办(人抽查定稿)
- finalized     已定稿:无草案有基线(等新素材)

口径:只统计**当前 reviewing 草案**名下的批注(覆盖语义:旧草案置 superseded
时 answered 存续但 draft_id 指旧草案,不得计入待重交)。
"""
from sqlmodel import Session, func, select

from app.models import Baseline, DocDraft, Question


def derive_requirement_status(db: Session, pid: int) -> str:
    draft = db.exec(
        select(DocDraft).where(DocDraft.project_id == pid, DocDraft.status == "reviewing")
    ).first()
    if draft is None:
        base = db.get(Baseline, pid)
        return "finalized" if base and base.version else "idle"

    def _cnt(status: str) -> int:
        return db.exec(
            select(func.count())
            .select_from(Question)
            .where(
                Question.project_id == pid,
                Question.status == status,
                Question.draft_id == draft.id,
            )
        ).one()

    if _cnt("pending") > 0:
        return "in_review"
    if _cnt("answered") > 0:
        return "await_resubmit"
    return "await_finalize"
