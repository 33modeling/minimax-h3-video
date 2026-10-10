#!/usr/bin/env bash
# 다른 창에서 끄기: serve.sh pid 파일의 서버와 up.sh 가 띄운 웹 UI (up.sh 화면에서는 Ctrl+C 로 충분).
#   bash scripts/down.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
bash "$ROOT/scripts/stop.sh"
if [[ -f "$H3_LOG_DIR/web.pid" ]]; then p=$(cat "$H3_LOG_DIR/web.pid"); rm -f "$H3_LOG_DIR/web.pid"; echo "[down] 웹 UI pid=$p 종료"; h3_stop_tree "$p" >/dev/null; fi
for p in "$H3_PORT_FL2VA" "$H3_PORT_REF2VA" "${H3_WEB_PORT:-8790}"; do
  h3_port_busy "$p" && echo "[down] 주의: 포트 $p 가 아직 열려 있다"
done
exit 0
