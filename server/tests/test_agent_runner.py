# server/tests/test_agent_runner.py
import json
import pathlib

import pytest

from app.ai.agent.runner import AgentRunError, run_agent

_FAKE = pathlib.Path(__file__).parent / "fake_dsh.py"


@pytest.fixture(autouse=True)
def _fake_dsh(monkeypatch):
    # cwd=任务目录，QUOS_DSH_CMD 必须用绝对路径
    monkeypatch.setenv("QUOS_DSH_CMD", f"python3 {_FAKE}")


async def _mk_dir(tmp_path, ctrl: dict | None = None):
    d = tmp_path / "job"
    (d / "out").mkdir(parents=True)
    (d / "RULES.md").write_text("# x", "utf-8")
    if ctrl is not None:
        (d / "FAKE.json").write_text(json.dumps(ctrl, ensure_ascii=False), "utf-8")
    return d


async def test_ok_events_and_result(tmp_path):
    seen = []
    d = await _mk_dir(tmp_path, {"result": {"nodes": []}})
    out = await run_agent(d, on_event=seen.append)
    assert out == {"nodes": []}
    assert seen == ["正在处理 RULES", "正在读 TASK.md"]  # label 文案；session 无文案不透出


async def test_fail_exit_code(tmp_path):
    with pytest.raises(AgentRunError):
        await run_agent(await _mk_dir(tmp_path, {"fail": True}))


async def test_missing_result(tmp_path):
    with pytest.raises(AgentRunError):
        await run_agent(await _mk_dir(tmp_path, {"result_raw": ""}))  # 空 JSON → 解析失败


async def test_timeout_kills(tmp_path):
    import asyncio
    with pytest.raises(AgentRunError):
        await run_agent(await _mk_dir(tmp_path, {"hang": True}), timeout=1.0)
    await asyncio.sleep(0.1)  # 收尸窗口
    assert (tmp_path / "job" / "run.log").exists()  # 超时现场留存


async def test_stderr_to_runlog(tmp_path):
    d = await _mk_dir(tmp_path)
    await run_agent(d)
    assert (d / "run.log").exists()


async def test_prompt_uses_absolute_task_dir(tmp_path):
    """任务文本必须带任务目录绝对路径——QUOS_DSH_CMD 可含 cd（dsh cwd≠任务目录），agent 靠绝对路径寻址"""
    d = await _mk_dir(tmp_path)
    await run_agent(d)
    stdin_text = (d / "out" / "stdin.txt").read_text("utf-8")
    assert str(d.resolve()) in stdin_text
    assert "TASK.md" in stdin_text and "out/result.json" in stdin_text


async def test_events_archived(tmp_path):
    """NDJSON 事件流全文落盘 events.log——失败排障现场（label 透传是有损投影不够用）"""
    d = await _mk_dir(tmp_path)
    await run_agent(d)
    raw = (d / "events.log").read_text("utf-8")
    assert '"type": "session"' in raw and '"type": "final"' in raw


async def test_env_whitelist(tmp_path, monkeypatch):
    """TMPDIR 必传（dsh 沙箱可写根=os.tmpdir()，缺了任务目录会被拒写）；平台密钥不泄漏"""
    monkeypatch.setenv("TMPDIR", "/tmp/quos-env-test")
    monkeypatch.setenv("QUOS_LLM_API_KEY", "secret")
    d = await _mk_dir(tmp_path)
    await run_agent(d)
    env_txt = (d / "out" / "env.txt").read_text("utf-8")
    assert "TMPDIR=/tmp/quos-env-test" in env_txt
    assert "HAS_LLM_KEY=False" in env_txt
