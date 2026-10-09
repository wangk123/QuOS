# server/app/ai/agent/runner.py —— dsh headless 子进程编排（spec §4.2）
import asyncio
import json
import os
import signal
from pathlib import Path

from app.ai.runner import _strip_fence  # 围栏剥离复用现有实现

_ENV_OK = ("PATH", "HOME", "LANG", "DSH_HOME",
           "http_proxy", "https_proxy", "no_proxy",
           "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
# 任务接线文本：注入任务目录绝对路径——QUOS_DSH_CMD 可含 cd（dsh workspace 在别处），agent 经绝对路径读材料
_PROMPT = ("先读 {base}/TASK.md 与 {base}/RULES.md，严格按规则处理 {base}/materials/ 清单，"
           "产物只写 {base}/out/result.json 与 {base}/out/report.md。")


class AgentRunError(Exception):
    def __init__(self, msg: str):
        self.msg = msg
        super().__init__(msg)


def _label(ev: dict) -> str | None:
    """事件 → 进度文案：text 取首行 40 字；tool_call 显示在读什么"""
    if ev.get("type") == "text":
        lines = (ev.get("text") or "").strip().splitlines()
        return lines[0][:40] if lines else None
    if ev.get("type") == "tool_call":
        arg = ev.get("arguments") or {}
        target = arg.get("path") or arg.get("file") or ev.get("tool") or ""
        return f"正在读 {str(target)[:40]}".strip()
    return None


async def _pump(proc, dir_path: Path, on_event) -> bool:
    """启动后立即注入 stdin 任务文本并关闭；两路持续读防 pipe 满：
    stdout 逐行解析 NDJSON 事件（on_event 回调），stderr 追写 run.log；返回是否见到 final"""
    proc.stdin.write(_PROMPT.format(base=dir_path.resolve()).encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()
    saw_final = False
    with open(dir_path / "run.log", "wb") as log:

        async def _err():
            while True:
                chunk = await proc.stderr.read(65536)
                if not chunk:
                    break
                log.write(chunk)

        err_task = asyncio.create_task(_err())
        try:
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "final":
                    saw_final = True
                if on_event is not None and (text := _label(ev)):
                    on_event(text)
        finally:
            # 取消场景（超时）不得阻塞在 stderr 读上；正常路径 err_task 已自然结束
            if not err_task.done():
                err_task.cancel()
            try:
                await err_task
            except asyncio.CancelledError:
                pass
    await proc.wait()
    return saw_final


async def run_agent(dir_path: Path, on_event=None, timeout: float | None = None) -> dict:
    """拉起 dsh headless：cwd=任务目录、任务文本走 stdin；NDJSON 事件→on_event；
    stderr→run.log；退出码 0 且有 final 且 result.json 合法 → 返回 dict，否则 AgentRunError"""
    timeout = timeout if timeout is not None else float(os.environ.get("QUOS_AGENT_TIMEOUT", "1200"))
    env = {k: os.environ[k] for k in _ENV_OK if k in os.environ}
    proc = await asyncio.create_subprocess_shell(
        os.environ["QUOS_DSH_CMD"], cwd=dir_path,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True)
    try:
        saw_final = await asyncio.wait_for(_pump(proc, dir_path, on_event), timeout=timeout)
    except asyncio.TimeoutError:
        _kill_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)  # 收尸，防 transport 晚关报 ProcessLookup
        except asyncio.TimeoutError:
            pass
        raise AgentRunError("agent 运行超时被终止")
    if proc.returncode != 0 or not saw_final:
        raise AgentRunError(f"agent 异常退出（code={proc.returncode}）")
    return _load_result(dir_path)


def _kill_tree(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _load_result(dir_path: Path) -> dict:
    f = dir_path / "out" / "result.json"
    if not f.exists():
        raise AgentRunError("产物缺失：out/result.json 不存在")
    try:
        return json.loads(_strip_fence(f.read_text("utf-8")))
    except (json.JSONDecodeError, ValueError) as e:
        raise AgentRunError(f"产物不是合法 JSON: {e}")
