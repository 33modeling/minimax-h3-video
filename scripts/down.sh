#!/usr/bin/env bash
# 다른 창에서 끄기: serve.sh pid 파일의 서버와 up.sh 가 띄운 웹 UI (up.sh 화면에서는 Ctrl+C 로 충분).
#   bash scripts/down.sh
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
bash "$ROOT/scripts/stop.sh"
python3 "$ROOT/scripts/h3_leftovers.py" --kill --all --keep-web   # pid 파일 밖으로 남은 서버·워커·torchrun 까지 (웹 UI 는 web.sh 창에서 Ctrl+C 또는 bash scripts/web.sh --stop)
for p in "$H3_PORT_FL2VA" "$H3_PORT_REF2VA" "${H3_WEB_PORT:-8790}"; do
  h3_port_busy "$p" && echo "[down] 주의: 포트 $p 가 아직 열려 있다"
done
exit 0
