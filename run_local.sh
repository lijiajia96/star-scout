#!/usr/bin/env bash
# AI Issue Radar 本地一键跑：发现 → 采集 → 分析
# 用法：./run_local.sh [新增候选数]
set -euo pipefail
cd "$(dirname "$0")"

LIMIT="${1:-5}"
echo "== [1/3] 发现腰部候选（新增 ${LIMIT} 个）=="
python3 discover.py "$LIMIT"

echo "== [2/3] 采集（缩小范围 + 跳过响应采样，省配额）=="
python3 collect.py --limit "$LIMIT" --responses 0

echo "== [3/3] 信号分析 =="
python3 analyze.py
