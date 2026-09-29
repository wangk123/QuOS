# server/app/ai/fake.py
# QUOS_FAKE_AI=1 时替换 tasks 里的 AI 任务为固定假数据（无 LLM key 的端到端走查用）。
# 签名与 app/ai/tasks.py 一一对应；install() 由 main.py 在启动时调用。
from app.ai import tasks
from app.ai.tasks import AssembleBlocked, VerifyOut
from app.core.models import Conflict, Gap, Rule
from app.storage.profiles import Profile, ProfileRule

# extract 产出中的一对冲突素材（conflict 按文本配对识别）
_PAIR = ("重试上限为 3 次", "重试上限为 5 次")


async def fake_extract(evidence_content: str, evidence_type: str, tree_text: str) -> list[Rule]:
    return [
        Rule(id="", text="回调超时 30s 触发自动重试", src="材料实证", conf="实证", node=""),
        Rule(id="", text=_PAIR[0], src="材料实证", conf="实证", node=""),
        Rule(id="", text=_PAIR[1], src="材料文档", conf="文档", node=""),
    ]


async def fake_verify(rules: list[Rule], evidence_content: str) -> VerifyOut:
    return VerifyOut(results=[{"id": r.id, "ok": True} for r in rules])


async def fake_conflict(rules: list[Rule]) -> list[Conflict]:
    pair = [r for r in rules if r.text in _PAIR]
    if len(pair) < 2:
        return []
    return [Conflict(id="C1", a=pair[0].id, b=pair[1].id,
                     q="重试上限到底是几次？（代码与文档不一致）")]


async def fake_gaps(profile_summary: str, dims: list[str]) -> list[Gap]:
    # 维度必须在当前维度清单内（router 会过滤 AI 自造维度）
    dim = dims[0] if dims else "状态"
    return [Gap(id="G1", dim=dim, text="「重试中」状态无出口——人工干预路径未定义")]


async def fake_assemble(rules: list[Rule], node_name: str, note: str) -> Profile:
    # 与真实 assemble 相同的硬阻断：未核验/待实证规则不允许进用户画像
    unqualified = [r for r in rules if not (r.verified and r.conf != "待实证")]
    if unqualified:
        raise AssembleBlocked(unqualified)
    profile_rules = [ProfileRule(id=f"R{i + 1}", text=r.text, src=r.src, conf=r.conf)
                     for i, r in enumerate(rules)]
    return Profile(
        node=node_name,
        goal="回调超时后不产生重复放款",
        entry="回调超时 30s",
        flow="① 进入重试队列 → ② 以原流水号重发 → ③ 最多 3 次",
        rules=profile_rules,
        states="待放款 → 放款中 → 成功｜失败｜重试中",
        boundaries="服务重启恢复 / 并发重试未覆盖",
        note=note,
        deps="核心账务（写）· 回调网关（读）",
        unconfirmed=[f"{r.id} {r.text}" for r in rules if r.conf != "实证"],
    )


async def fake_impact(diff_text: str, tree_dump: str, profile_list: list[str]) -> list[str]:
    return profile_list[:1]


async def fake_outline(material: str) -> list[tasks.OutlineNode]:
    return [tasks.OutlineNode(name="支付", children=[
        tasks.OutlineNode(name="放款重试", children=[]),
        tasks.OutlineNode(name="回调处理", children=[]),
    ])]


def install() -> None:
    """把假实现挂到 tasks 模块上（router 以 tasks.fn 形式调用，运行时生效）"""
    tasks.extract = fake_extract
    tasks.verify = fake_verify
    tasks.conflict = fake_conflict
    tasks.gaps = fake_gaps
    tasks.assemble = fake_assemble
    tasks.impact = fake_impact
    tasks.outline = fake_outline
