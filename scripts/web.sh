#!/usr/bin/env bash
# 웹 UI 만 띄운다 (H3 서버와 따로: 이것을 다시 띄우거나 꺼도 H3 서버는 그대로). H3 서버는 bash scripts/up.sh.
#   bash scripts/web.sh                                    웹 UI(8790), 이 화면에서. 끄기 Ctrl+C
#   bash scripts/web.sh --cors https://33modeling.pages.dev  허브 '숏폼 제작'에서 부를 수 있게
#   bash scripts/web.sh --stop                             다른 창에서 웹 UI 끄기
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null || { echo "cluster_env.sh 실패"; exit 1; }
PORT="${H3_WEB_PORT:-8790}"; CORS="${H3_CORS_ORIGIN:-}"; STOP=0
while [[ $# -gt 0 ]]; do case "$1" in
  --cors) CORS="$2"; shift 2 ;; --port) PORT="$2"; shift 2 ;; --stop) STOP=1; shift ;;
  -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "알 수 없는 옵션: $1 (--help)"; exit 2 ;; esac; done
# 전에 띄운 웹 UI 만 내린다 (H3 서버는 건드리지 않는다)
python3 "$ROOT/scripts/h3_leftovers.py" --kill --web-only | grep -v "남은 웹 UI 프로세스 없음"
[[ $STOP == 1 ]] && { echo "[web] 웹 UI 를 껐다 (H3 서버는 그대로)"; exit 0; }
for _ in $(seq 1 15); do h3_port_busy "$PORT" || break; sleep 1; done
if h3_port_busy "$PORT"; then echo "[web] 포트 $PORT 를 다른 프로그램이 쓰고 있다 → --port 로 바꾸거나 그 프로그램을 끈다"; exit 1; fi
mkdir -p "$H3_LOG_DIR"; LOG="$H3_LOG_DIR/web-$(date +%Y%m%d-%H%M%S).log"
exec > >(trap '' INT; tee -a "$LOG") 2>&1
ok() { python3 - "$1" <<'PY' 2>/dev/null
import sys, urllib.request
try:
    urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=3); sys.exit(0)
except Exception:
    sys.exit(1)
PY
}
echo "[web] 로그 파일: $LOG"
for v in "fl2va:$H3_PORT_FL2VA" "ref2va:$H3_PORT_REF2VA"; do
  ok "${v#*:}" && echo "[web] H3 ${v%%:*} 서버(포트 ${v#*:}): 준비됨" || echo "[web] H3 ${v%%:*} 서버(포트 ${v#*:}): 꺼져 있다 — 영상을 만들려면 다른 창에서 bash scripts/up.sh$([[ ${v%%:*} == ref2va ]] && echo ' --ref')"
done
host="$(hostname -f 2>/dev/null || hostname)"
echo "[web] PC 에서: ssh -N -L $PORT:127.0.0.1:$PORT $(id -un)@$host   그다음 브라우저 http://127.0.0.1:$PORT"
echo "[web] 끄기: 이 화면에서 Ctrl+C (H3 서버는 그대로)"
cmd=(python3 -m h3video.cli web --host 127.0.0.1 --port "$PORT"); [[ -n "$CORS" ]] && cmd+=(--cors-origin "$CORS")
exec "${cmd[@]}"
