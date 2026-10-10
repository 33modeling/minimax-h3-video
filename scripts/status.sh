#!/usr/bin/env bash
# 서버가 떴는지 한 번에 보기 (어느 창에서든): fl2va·ref2va·웹 UI 상태, 로딩 중이면 로그 마지막 줄, GPU 메모리.
#   bash scripts/status.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null 2>&1 || true
green() { printf '\033[32m%s\033[0m\n' "$*"; }; yellow() { printf '\033[33m%s\033[0m\n' "$*"; }; red() { printf '\033[31m%s\033[0m\n' "$*"; }
http_ok() {  # curl 이 없는 컨테이너에서도 되게 파이썬으로
  python3 - "$@" <<'PY' 2>/dev/null
import sys, urllib.request
for u in sys.argv[1:]:
    try:
        urllib.request.urlopen(u, timeout=3); sys.exit(0)
    except Exception:
        pass
sys.exit(1)
PY
}
echo "== 서버 상태 ($(hostname))"
any_up=0
for v in fl2va ref2va; do
  [[ $v == fl2va ]] && port=${H3_PORT_FL2VA:-30010} || port=${H3_PORT_REF2VA:-30011}
  pidf="${H3_LOG_DIR:-/nonexistent}/serve-$v.pid"; pid=""; [[ -f "$pidf" ]] && pid="$(cat "$pidf")"
  log="$(ls -t "${H3_LOG_DIR:-/nonexistent}"/serve-$v-*.log 2>/dev/null | head -1)"
  if http_ok "http://127.0.0.1:$port/health" "http://127.0.0.1:$port/v1/models"; then
    green "  $v  포트 $port : 준비됨 ✓ (영상 요청 가능)"; any_up=1
  elif [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    yellow "  $v  포트 $port : 로딩 중 (pid $pid)"
    [[ -n "$log" ]] && echo "      로그 마지막: $(tail -n 1 "$log" | tr -d '\r' | cut -c1-150)"
  elif h3_port_busy "$port" 2>/dev/null; then
    yellow "  $v  포트 $port : 열려 있지만 응답 없음 (다른 프로그램이거나 멈춤)"
  else
    echo "  $v  포트 $port : 꺼짐"
  fi
done
wport=${H3_WEB_PORT:-8790}
if http_ok "http://127.0.0.1:$wport/api/health"; then green "  웹 UI 포트 $wport : 켜짐 ✓ (브라우저 http://127.0.0.1:$wport)"
else echo "  웹 UI 포트 $wport : 꺼짐"; fi
if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  echo "== GPU"; nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader | sed 's/^/  GPU /'
fi
[[ $any_up == 1 ]] && exit 0 || exit 1
