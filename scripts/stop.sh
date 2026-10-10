#!/usr/bin/env bash
# 서빙 프로세스 정리. 사용: source scripts/cluster_env.sh && bash scripts/stop.sh [fl2va|ref2va]
set -uo pipefail
[[ -n "${STORAGE_ROOT:-}" ]] || { echo "cluster_env.sh 를 먼저 source 하라"; exit 1; }
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/cluster_env.sh" >/dev/null   # h3_stop_tree
PIDS=()
for v in ${1:-fl2va ref2va}; do
  f="$H3_LOG_DIR/serve-$v.pid"; [[ -f "$f" ]] || continue
  pid=$(cat "$f"); echo "[stop] $v pid=$pid"
  PIDS+=("$pid"); rm -f "$f"
done
# 하위 프로세스(sglang 워커)까지 묶음째 끄고, GPU 를 잡은 내 프로세스가 남았으면 강제 종료 (cluster_env.sh)
h3_stop_tree "${PIDS[@]}"
pgrep -u "$(id -un)" -af "sglang serve" || echo "[stop] 남은 sglang 프로세스 없음"
