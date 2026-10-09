# server/app/ai/agent/__init__.py
import os

AGENT_TASKS = ("tree-gen", "extract", "verify", "clar-review")


def engine_on() -> bool:
    """引擎分流判定：开关为 dsh 且配置了启动命令，二者缺一回落现有 LLM 链路"""
    return (os.environ.get("QUOS_AGENT_ENGINE", "dsh") == "dsh"
            and bool(os.environ.get("QUOS_DSH_CMD", "").strip()))
