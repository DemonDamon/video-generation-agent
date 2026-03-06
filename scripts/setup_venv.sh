#!/bin/bash
# Linux/macOS: 在干净虚拟环境中安装依赖
# 用法: bash scripts/setup_venv.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_ROOT/.venv"

echo "Project: $PROJECT_ROOT"
echo "Creating venv at: $VENV_PATH"

rm -rf "$VENV_PATH"
python -m venv "$VENV_PATH"
source "$VENV_PATH/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_ROOT/requirements.txt"

echo ""
echo "Done. Activate with: source .venv/bin/activate"
