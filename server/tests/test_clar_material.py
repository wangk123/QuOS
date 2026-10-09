# server/tests/test_clar_material.py
import io
import json
import pytest
from app.core.models import AiReview, ClarAnswer, Clarification, Evidence


def test_clarification_defaults_for_old_rows():
    """旧 JSON 行缺新字段：kind 兜底 choice，ai/ans 兜底 None"""
    c = Clarification(no=1, q="重试上限？", opts=["3次", "5次"], st="wait")
    assert c.kind == "choice" and c.ai is None and c.ans is None
    assert c.st == "wait"


def test_evidence_source_default_empty():
    e = Evidence(id="文本1", name="n", type="文本", reg="2026-09-29", path="")
    assert e.source == ""


@pytest.mark.asyncio
async def test_add_open_kind_when_opts_empty(tmp_path):
    from app.storage import clarifications as cl
    c = await cl.add(tmp_path, "退款审批阈值未说明，请补充", [], ref=None)
    assert c.kind == "open" and c.opts == []
    c2 = await cl.add(tmp_path, "冷却期多久？", ["7天", "30天"])
    assert c2.kind == "choice"


@pytest.mark.asyncio
async def test_set_ai_roundtrip(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "q", [])
    ai = {"answer": "答", "quote": "材料原文", "ev_ids": ["文本ABCD"], "conf": "high", "quote_ok": True}
    c = await cl.set_ai(tmp_path, 1, ai)
    assert c.ai == ai
    rows = json.loads((tmp_path / "clarifications.json").read_text("utf-8"))
    assert rows[0]["ai"]["quote"] == "材料原文"
    await cl.set_ai(tmp_path, 1, None)  # 忽略/采纳后清空
    assert (await cl.list_all(tmp_path))[0].ai is None


@pytest.mark.asyncio
async def test_set_ai_invalid_dict_not_persisted(tmp_path):
    """非法代答（缺 answer）：ValidationError 抛出且不落盘毒化存储"""
    from pydantic import ValidationError
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "q", [])
    with pytest.raises(ValidationError):
        await cl.set_ai(tmp_path, 1, {"quote": "x"})
    assert (await cl.list_all(tmp_path))[0].ai is None  # 文件未被写坏，仍可正常加载


@pytest.mark.asyncio
async def test_clar_review_task_parses(monkeypatch):
    from app.ai import tasks
    fake = tasks.ClarReviewOut(results=[
        {"no": 1, "answered": True, "answer": "7 天", "quote": "冷却期为7天", "conf": "high"},
        {"no": 2, "answered": False},
    ])

    async def mock(task, variables, schema, images=None):
        assert "冷却期" in variables["questions"] and "制度原文" in variables["materials"]
        assert images == [b"jpeg"]
        return fake

    monkeypatch.setattr(tasks, "complete", mock)
    out = await tasks.clar_review("1. 冷却期多久？", "制度原文：冷却期为7天", [b"jpeg"])
    assert out.results[0].no == 1 and out.results[1].answered is False


@pytest.mark.asyncio
async def test_fake_clar_review_installed():
    from app.ai import fake, tasks
    fake.install()
    out = await tasks.clar_review("1. q", "材料", None)
    assert len(out.results) == 1 and out.results[0].answered is True


def test_pdf_text_roundtrip(tmp_path):
    from app.core import parse
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)  # 空白页：无文本
    f = tmp_path / "scan.pdf"
    f.write_bytes(_pdf_bytes(w))
    assert parse.pdf_text(f) == ""  # 扫描件/无文本 → 空


def _pdf_bytes(w) -> bytes:
    import io
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_shrink_image_resizes_and_jpeg(tmp_path):
    from PIL import Image
    from app.core import parse
    f = tmp_path / "big.png"
    Image.new("RGB", (3200, 100), "red").save(f)
    out = parse.shrink_image(f)
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.width <= 1600 and img.height <= 1600


def test_pdf_text_corrupt_raises_chinese(tmp_path):
    from app.core import parse
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")
    with pytest.raises(RuntimeError, match="PDF 解析失败"):
        parse.pdf_text(f)


# ---------- 澄清重检（review 端点 + job 编排 + 防幻觉校验） ----------

BASE = "/api/projects/演示项目"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    monkeypatch.setattr("app.storage.project.DATA_DIR", tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_review_validates_and_persists(tmp_path, monkeypatch):
    from app.api import router as R
    from app.core.models import Clarification
    from app.ai.tasks import ClarReviewItem
    waits = [Clarification(no=1, q="冷却期多久？", opts=["7天", "30天"], kind="choice"),
             Clarification(no=2, q="退款阈值？", opts=[], kind="open"),
             Clarification(no=3, q="未涉问题", opts=["a"])]
    results = [ClarReviewItem(no=1, answered=True, answer="90 天", quote="冷却期为7天", conf="high"),  # 选项不命中→丢弃
               ClarReviewItem(no=2, answered=True, answer="1万以下主管审批", quote="不在材料里的原文", conf="high"),  # quote 不命中→quote_ok False+conf low
               ClarReviewItem(no=99, answered=True, answer="x", quote="材料原文", conf="high")]  # 未知 no→丢弃
    n = R._apply_review(results, waits, "制度原文：冷却期为7天", ["E1"])
    assert n == 1
    ai = next(w for w in waits if w.no == 2).ai
    assert ai.quote_ok is False and ai.conf == "low"
    assert next(w for w in waits if w.no == 1).ai is None


@pytest.mark.asyncio
async def test_review_endpoint_creates_job(client, monkeypatch):
    """入池 1 份文本（source=clar）→ 发起重检 → job 建立、代答落 ai、st 仍 wait"""
    from app.storage.project import ensure_root
    root = ensure_root("演示项目")
    r = await client.post(f"{BASE}/evidence?source=clar", json={"raw": "制度原文：授信冷却期为7天"})
    ev_id = r.json()["id"]
    # 直接造一条 wait 题：通过既有 ask 链路太重，走 storage
    from app.storage import clarifications as cl
    from app.core.models import Rule
    from app.storage import rules as rule_store
    rule_store.save(root, [Rule(id="R1", text="冷却期推测", src="s", conf="推测", verified=False)])
    c = await cl.add(root, "冷却期多久？", ["7天", "30天"], ref="R1", type="custom")  # 事实题送 AI；confirm 不送

    from app.ai.tasks import ClarReviewOut
    async def mock(qs, ms, images=None):
        return ClarReviewOut(results=[{"no": c.no, "answered": True, "answer": "7天", "quote": "授信冷却期为7天", "conf": "high"}])
    monkeypatch.setattr("app.ai.tasks.clar_review", mock)

    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 200 and "job_id" in r.json()
    import asyncio; await asyncio.sleep(0.1)  # create_task 事务让子弹飞
    rows = await cl.list_all(root)
    assert rows[0].ai is not None and rows[0].st == "wait"  # 待采纳：st 不动


@pytest.mark.asyncio
async def test_review_guards(client):
    """无待问→422；ev 不存在→404；运行中任务→409"""
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": ["NOPE"]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_review_guard_empty_ev_ids(client):
    """空材料列表 → 422：防误触空材料重检，把已有待采纳代答静默清空（须有 wait 题，否则先命中「无待问」422）"""
    from app.storage.project import ensure_root
    from app.storage import clarifications as cl
    root = ensure_root("演示项目")
    await cl.add(root, "冷却期多久？", ["7天", "30天"])
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": []})
    assert r.status_code == 422 and "未选择" in r.json()["detail"]


@pytest.mark.asyncio
async def test_review_guard_running_job(client, monkeypatch):
    """已有任务运行中 → 409"""
    from app.storage.project import ensure_root
    from app.storage import jobs as jobs_store
    ensure_root("演示项目")
    monkeypatch.setattr(jobs_store, "running", lambda: {"label": "AI 全量核验", "cur": 1, "total": 2})
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": ["E1"]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_review_guard_image_cap(client, monkeypatch):
    """图片超上限 → 422"""
    from app.storage.project import ensure_root
    from app.storage import clarifications as cl
    root = ensure_root("演示项目")
    r = await client.post(f"{BASE}/evidence", json={"raw": "x"})
    ev_id = r.json()["id"]
    await cl.add(root, "q", [])
    monkeypatch.setattr("app.api.router._evidence_parts", lambda root, ev: ("", [("image/jpeg", b"x")] * 6))
    r = await client.post(f"{BASE}/clarifications/review", json={"ev_ids": [ev_id]})
    assert r.status_code == 422 and "最多 5 张" in r.json()["detail"]


@pytest.mark.asyncio
async def test_evidence_source_clar_query(client):
    """POST /evidence?source=clar：仅 'clar' 落 source（文本与文件两分支），其余值/不带均落空"""
    from app.storage.project import ensure_root
    ensure_root("演示项目")
    r = await client.post(f"{BASE}/evidence?source=clar", json={"raw": "制度原文：阈值 1 万"})
    assert r.json()["source"] == "clar"
    assert (await client.post(f"{BASE}/evidence", json={"raw": "普通文本"})).json()["source"] == ""
    assert (await client.post(f"{BASE}/evidence?source=evil", json={"raw": "非法来源"})).json()["source"] == ""
    r4 = await client.post(f"{BASE}/evidence?source=clar", content=b"\x89PNG",
                           headers={"x-filename": "%E6%88%AA%E5%9B%BE.png"})
    assert r4.json()["source"] == "clar"
    lst = {e["id"]: e["source"] for e in (await client.get(f"{BASE}/evidence")).json()}
    assert lst[r.json()["id"]] == "clar"  # GET /evidence 透出，供证据池徽章
    assert lst[r4.json()["id"]] == "clar"


# ---------- 澄清答案升级（open 题文本/材料作答、AI 代答 adopt/ignore） ----------

@pytest.mark.asyncio
async def test_answer_text_for_open(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "退款阈值？", [])
    c = await cl.answer(tmp_path, 1, text="1万以下主管审批", ev_ids=["E1"])
    assert c.st == "answered" and c.ans.kind == "material" and c.ans.ev_ids == ["E1"]
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 1, idx=0)  # open 题不接受 idx


@pytest.mark.asyncio
async def test_answer_choice_requires_idx(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "冷却期？", ["7天"])
    with pytest.raises(ValueError):
        await cl.answer(tmp_path, 1, text="文字")  # choice 题不接受 text
    c = await cl.answer(tmp_path, 1, idx=0)
    assert c.ans.kind == "opt" and c.answer == "7天"


@pytest.mark.asyncio
async def test_adopt_and_ignore(tmp_path):
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "开放题", [])
    await cl.set_ai(tmp_path, 1, {"answer": "代答", "quote": "q", "ev_ids": ["E1"], "conf": "high", "quote_ok": True})
    c = await cl.clar_adopt(tmp_path, 1)
    assert c.st == "answered" and c.ans.kind == "material" and c.ans.text == "代答" and c.ai is None
    await cl.set_ai(tmp_path, 1, {"answer": "再检", "quote": "q", "ev_ids": [], "conf": "med", "quote_ok": True})
    c2 = await cl.clar_ignore(tmp_path, 1)
    assert c2.ai is None  # 待问 tab 不再出现代答卡


@pytest.mark.asyncio
async def test_adopt_triggers_rule_verify(client, monkeypatch):
    from app.storage.project import ensure_root
    root = ensure_root("演示项目")
    from app.storage import rules as rule_store, clarifications as cl
    from app.core.models import Rule
    rule_store.save(root, [Rule(id="R1", text="推测规则", src="s", conf="推测")])
    c = await cl.add(root, "该推测与实际一致吗？", ["确认一致"], ref="R1")
    await cl.set_ai(root, c.no, {"answer": "确认一致", "quote": "原文", "ev_ids": [], "conf": "high", "quote_ok": True})
    r = await client.post(f"{BASE}/clarifications", json={"no": c.no, "action": "adopt"})
    assert r.status_code == 200
    assert rule_store.load(root)[0].verified is True  # 既有联动：采纳=人工确认
    assert rule_store.load(root)[0].clar is None


@pytest.mark.asyncio
async def test_ignore_does_not_verify_rule(client):
    """忽略 AI 代答 ≠ 人工确认：不触发 ref→规则核过联动，问题仍 wait"""
    from app.storage.project import ensure_root
    root = ensure_root("演示项目")
    from app.storage import rules as rule_store, clarifications as cl
    from app.core.models import Rule
    rule_store.save(root, [Rule(id="R1", text="推测规则", src="s", conf="推测")])
    c = await cl.add(root, "该推测与实际一致吗？", ["确认一致"], ref="R1")
    await cl.set_ai(root, c.no, {"answer": "确认一致", "quote": "原文", "ev_ids": [], "conf": "high", "quote_ok": True})
    r = await client.post(f"{BASE}/clarifications", json={"no": c.no, "action": "ignore"})
    assert r.status_code == 200
    assert rule_store.load(root)[0].verified is False  # 忽略不联动核过
    rows = await cl.list_all(root)
    assert rows[0].st == "wait" and rows[0].ai is None


@pytest.mark.asyncio
async def test_answer_invalid_ev_ids_not_persisted(tmp_path):
    """非法 ev_ids（字符串而非列表）：ValidationError 抛出且不落盘毒化存储"""
    from pydantic import ValidationError
    from app.storage import clarifications as cl
    await cl.add(tmp_path, "q", [])
    with pytest.raises(ValidationError):
        await cl.answer(tmp_path, 1, text="x", ev_ids="E1")
    assert (await cl.list_all(tmp_path))[0].ans is None  # 文件未被写坏，仍可正常加载
