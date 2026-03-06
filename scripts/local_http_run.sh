#!/bin/bash
# 本地启动 HTTP 服务（不依赖 Coze 平台 load_env）
# 使用前请先导出环境变量，见 docs/LOCAL_RUN.md
# 用法: bash scripts/local_http_run.sh [端口]  默认 5000

set -e
WORK_DIR="${COZE_WORKSPACE_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PORT="${1:-5000}"

# 若存在 .env.local 则加载
if [ -f "$WORK_DIR/.env.local" ]; then
  echo "Loading .env.local..."
  set -a
  source "$WORK_DIR/.env.local"
  set +a
fi

echo "Starting server on port $PORT..."
python "$WORK_DIR/src/main.py" -m http -p "$PORT"
