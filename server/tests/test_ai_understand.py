# server/tests/test_ai_understand.py（asyncio_mode=auto：直接 async def，无标记，同 test_api.py 模式）
from app.ai import tasks

async def test_understand_returns_root_and_skeleton(monkeypatch):
    async def fake(task, variables, schema, images=None):
        assert task == "understand"
        assert variables["material"] == "整体方案……"
        return schema.model_validate({
            "root": {"goal": "给客户经理的访前调查助手", "entry": "客户经理 · 一期文字",
                     "flow": "输入→查询→画像→输出", "boundaries": "0 实证", "note": "字数上限×7"},
            "nodes": [{"name": "感知模块", "goal": "接收输入", "children": [
                {"name": "文字输入", "goal": "输入企业名称自动开网页", "children": []}]}]})
    monkeypatch.setattr(tasks, "complete", fake)
    out = await tasks.understand("整体方案……")
    assert out.root.goal.startswith("给客户经理")
    assert out.nodes[0].goal == "接收输入"

async def test_understand_passes_images(monkeypatch):
    seen = {}
    async def fake(task, variables, schema, images=None):
        seen["images"] = images
        return schema.model_validate({"root": {}, "nodes": []})
    monkeypatch.setattr(tasks, "complete", fake)
    await tasks.understand("材料", images=[b"x"])
    assert seen["images"] == [b"x"]
