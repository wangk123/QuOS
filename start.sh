#!/usr/bin/env bash
# QuOS 一键部署启动：装依赖 → 构建前端 → 启动服务
# 用法:
#   ./start.sh              # dist 存在则跳过构建
#   ./start.sh --build      # 强制重新构建前端
#   QUOS_FAKE_AI=1 ./start.sh                    # 假数据模式（无需 LLM key）
#   QUOS_LLM_API_KEY=... QUOS_LLM_BASE_URL=... QUOS_LLM_MODEL=... ./start.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${QUOS_PORT:-8000}"

echo "==> 1/3 依赖检查"
[ -d web/node_modules ] || (cd web && npm install)
(cd server && uv sync --quiet)

echo "==> 2/3 前端构建"
if [ ! -d web/dist ] || [ "${1:-}" = "--build" ]; then
  (cd web && npm run build)
else
  echo "    dist 已存在，跳过（强制重建: ./start.sh --build）"
fi

echo "==> 3/3 启动服务 http://localhost:${PORT}"
if [ -z "${QUOS_LLM_API_KEY:-}" ] && [ "${QUOS_FAKE_AI:-}" != "1" ]; then
  echo "    ⚠ 未配置 AI：设置 QUOS_LLM_API_KEY/BASE_URL/MODEL，或用 QUOS_FAKE_AI=1 假数据模式"
fi

command -v open >/dev/null && open "http://localhost:${PORT}" || true
cd server && exec uv run uvicorn app.main:app --host 127.0.0.1 --port "${PORT}"
