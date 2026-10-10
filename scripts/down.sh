#!/usr/bin/env bash
# up.sh 로 띄운 것 전부 끄기: tmux 세션(서버·웹 UI)과 serve.sh pid 파일의 서버.
#   bash scripts/down.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${H3_TMUX:-h3}"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
if tmux has-session -t "$SESSION" 2>/dev/null; then
  for w in $(tmux list-windows -t "$SESSION" -F '#{window_name}'); do tmux send-keys -t "$SESSION:$w" C-c 2>/dev/null; done
  sleep 5
  tmux kill-session -t "$SESSION" 2>/dev/null && echo "[down] tmux 세션 $SESSION 종료"
fi
bash "$ROOT/scripts/stop.sh"
for p in "$H3_PORT_FL2VA" "$H3_PORT_REF2VA" "${H3_WEB_PORT:-8790}"; do
  ss -ltn 2>/dev/null | grep -q ":$p " && echo "[down] 주의: 포트 $p 가 아직 열려 있다 (ss -ltnp 로 확인)"
done
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/[down] GPU /'
exit 0
