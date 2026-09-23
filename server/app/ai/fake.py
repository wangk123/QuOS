# server/app/ai/fake.py
# QUOS_FAKE_AI=1 时替换 tasks 里的 AI 任务为固定假数据（无 LLM key 的端到端走查用）。
# 签名与 app/ai/tasks.py 一一对应；install() 由 main.py 在启动时调用。
from app.ai import tasks
from app.ai.tasks import AssembleBlocked, VerifyOut
from app.core.models import Assertion, Conflict, Gap
from app.storage.cards import Card, Rule

# extract 产出中的一对冲突素材（conflict 按文本配对识别）
_PAIR = ("重试上限为 3 次", "重试上限为 5 次")


async def fake_extract(evidence_content: str, evidence_type: str) -> list[Assertion]:
    return [
        Assertion(id="", text="回调超时 30s 触发自动重试", src="材料实证", conf="实证"),
        Assertion(id="", text=_PAIR[0], src="材料实证", conf="实证"),
        Assertion(id="", text=_PAIR[1], src="材料文档", conf="文档"),
    ]


async def fake_verify(assertions: list[Assertion], evidence_content: str) -> VerifyOut:
    return VerifyOut(results=[{"id": a.id, "ok": True} for a in assertions])


async def fake_conflict(assertions: list[Assertion]) -> list[Conflict]:
    pair = [a for a in assertions if a.text in _PAIR]
    if len(pair) < 2:
        return []
    return [Conflict(id="C1", a=pair[0].id, b=pair[1].id,
                     q="重试上限到底是几次？（代码与文档不一致）")]


async def fake_gaps(card_summary: str, dims: list[str]) -> list[Gap]:
    # 维度必须在当前维度清单内（router 会过滤 AI 自造维度）
    dim = dims[0] if dims else "状态"
    return [Gap(id="G1", dim=dim, text="「重试中」状态无出口——人工干预路径未定义")]


async def fake_assemble(assertions: list[Assertion], node_name: str, note: str) -> Card:
    # 与真实 assemble 相同的硬阻断：未核验/待实证断言不允许进卡片
    unqualified = [a for a in assertions if not (a.verified and a.conf != "待实证")]
    if unqualified:
        raise AssembleBlocked(unqualified)
    rules = [Rule(id=f"R{i + 1}", text=a.text, src=a.src, conf=a.conf)
             for i, a in enumerate(assertions)]
    return Card(
        node=node_name,
        goal="回调超时后不产生重复放款",
        entry="回调超时 30s",
        flow="① 进入重试队列 → ② 以原流水号重发 → ③ 最多 3 次",
        rules=rules,
        states="待放款 → 放款中 → 成功｜失败｜重试中",
        boundaries="服务重启恢复 / 并发重试未覆盖",
        note=note,
        deps="核心账务（写）· 回调网关（读）",
        unconfirmed=[f"{a.id} {a.text}" for a in assertions if a.conf != "实证"],
    )


async def fake_impact(diff_text: str, tree_dump: str, card_list: list[str]) -> list[str]:
    return card_list[:1]


def install() -> None:
    """把假实现挂到 tasks 模块上（router 以 tasks.fn 形式调用，运行时生效）"""
    tasks.extract = fake_extract
    tasks.verify = fake_verify
    tasks.conflict = fake_conflict
    tasks.gaps = fake_gaps
    tasks.assemble = fake_assemble
    tasks.impact = fake_impact
