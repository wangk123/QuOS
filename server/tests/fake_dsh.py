# server/tests/fake_dsh.py
"""模拟 dsh --profile headless --json：读 stdin 任务文本，行为由 cwd 下 FAKE.json 控制文件驱动
（runner 子进程走环境白名单，测试配置只能走文件）：
  {"result": {...}}      产物 JSON（默认 {}）
  {"result_raw": "text"} 原样写产物（测坏 JSON/围栏）
  {"fail": true}         打 error 事件并退出码 1
  {"hang": true}         睡 60s（测超时 kill）
用法：QUOS_DSH_CMD="python3 <abs>/tests/fake_dsh.py"（cwd=任务目录）"""
import json
import sys
from pathlib import Path

task_text = sys.stdin.read()  # 任务文本（本替身不解析，转存供测试断言）
cwd = Path.cwd()
ctrl = json.loads((cwd / "FAKE.json").read_text("utf-8")) if (cwd / "FAKE.json").exists() else {}
(cwd / "out").mkdir(exist_ok=True)
(cwd / "out" / "stdin.txt").write_text(task_text, "utf-8")
task = (cwd / "RULES.md").stem if (cwd / "RULES.md").exists() else ""
for e in ({"type": "session", "id": "session-fake"},
          {"type": "text", "text": f"正在处理 {task}"},
          {"type": "tool_call", "tool": "read", "arguments": {"path": "TASK.md"}}):
    print(json.dumps(e, ensure_ascii=False), flush=True)
if ctrl.get("hang"):
    import time
    time.sleep(60)
if ctrl.get("fail"):
    print(json.dumps({"type": "error", "message": "boom"}), flush=True)
    sys.exit(1)
if "result_raw" in ctrl:
    (cwd / "out" / "result.json").write_text(ctrl["result_raw"], "utf-8")
else:
    (cwd / "out" / "result.json").write_text(
        json.dumps(ctrl.get("result", {}), ensure_ascii=False), "utf-8")
print(json.dumps({"type": "final", "text": "done"}), flush=True)
