#!/usr/bin/env bash
# 클러스터 노드에서 명령 하나로: 환경 설정 → 점검 → 서버·웹 UI 를 이 화면에서 포그라운드로 실행.
# 서버 원본 로그와 오류가 이 화면에 그대로 나온다. 준비되면 PC 접속 방법을 출력하고 계속 돈다. Ctrl+C 로 전부 끈다.
# (오래 띄워 둘 거면 직접 연 tmux 창 안에서 실행)
#
#   bash scripts/up.sh                 fl2va 서버(GPU 0,1,2,3) + 웹 UI(8790)
#   bash scripts/up.sh --ref           ref2va 서버도 (GPU 4,5,6,7 — 8장 노드)
#   bash scripts/up.sh --no-web        웹 UI 없이
#   bash scripts/up.sh --gpus 0,1,2,3 --ref-gpus 4,5,6,7 --mode memory
#   bash scripts/up.sh --cors https://33modeling.pages.dev    허브 '숏폼 제작'에서 웹 UI 를 부를 수 있게
#   bash scripts/up.sh --check         점검만
# 끄기: 이 화면에서 Ctrl+C (다른 창에서는 bash scripts/down.sh)
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${H3_TMUX:-h3}"
GPUS="0,1,2,3"; REF_GPUS="4,5,6,7"; REF=0; WEB=1; CHECK=0; MODE_ARGS=(); CORS="${H3_CORS_ORIGIN:-}"
while [[ $# -gt 0 ]]; do case "$1" in
  --ref) REF=1; shift ;; --no-web) WEB=0; shift ;; --check) CHECK=1; shift ;;
  --gpus) GPUS="$2"; shift 2 ;; --ref-gpus) REF_GPUS="$2"; shift 2 ;;
  --mode) MODE_ARGS=(--mode "$2"); shift 2 ;; --cors) CORS="$2"; shift 2 ;;
  -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "알 수 없는 옵션: $1 (--help)"; exit 2 ;; esac; done

red() { printf '\033[31m%s\033[0m\n' "$*"; }; green() { printf '\033[32m%s\033[0m\n' "$*"; }; yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
problems=0; fail() { red "✗ $1"; [[ -n "${2:-}" ]] && echo "   → $2"; problems=$((problems + 1)); }

# 1) 환경 (저장 경로·캐시·포트 기본값). 문제가 있으면 cluster_env.sh 가 이유를 출력한다
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" || { red "cluster_env.sh 실패 (위 메시지 참고)"; exit 1; }
cd "$ROOT"

# 2) 점검
model_ok=0
if h3_model_ok "$H3_MODEL_DIR"; then model_ok=1
elif h3_ask_model_dir; then model_ok=1; fi      # 못 찾으면 경로를 물어보고 .cluster_env.local.sh 에 저장
if [[ $model_ok == 1 ]]; then green "✓ 모델: $H3_MODEL_DIR"
  if [[ $REF == 1 ]] && ! compgen -G "$H3_MODEL_DIR/[Rr][Ee][Ff]2[Vv][Aa]" >/dev/null; then fail "Ref2VA 가중치 없음: $H3_MODEL_DIR/Ref2VA" "--ref 빼고 실행 (fl2va 만)"; fi
else
  cands="$(h3_find_models 2>/dev/null | awk '!seen[$0]++' | tr '\n' ' ')"
  fail "모델 없음: $H3_MODEL_DIR" "받아 둔 곳을 .cluster_env.local.sh 에 export H3_MODEL_DIR=<경로>${cands:+ (찾은 곳: $cands)}. 새로 받는 건 provision.sh --download 뿐"
fi
command -v sglang >/dev/null && green "✓ sglang: $(command -v sglang)" || fail "sglang 없음" "bash scripts/provision.sh (venv: $VENV)"
ngpu=0; command -v nvidia-smi >/dev/null && ngpu=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU')
need=$(tr ',' '\n' <<<"$GPUS" | grep -c .); [[ $REF == 1 ]] && need=$((need + $(tr ',' '\n' <<<"$REF_GPUS" | grep -c .)))
if [[ $ngpu -ge $need ]]; then green "✓ GPU ${ngpu}장 (필요 ${need}장)"; else fail "GPU ${ngpu}장, 필요 ${need}장" "--gpus 로 줄이거나 --ref 빼기"; fi
healthy() { curl -fsS -m 5 "http://127.0.0.1:$1/health" >/dev/null 2>&1 || curl -fsS -m 5 "http://127.0.0.1:$1/v1/models" >/dev/null 2>&1; }
in_use() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
declare -A PORT=([fl2va]=$H3_PORT_FL2VA [ref2va]=$H3_PORT_REF2VA [web]=${H3_WEB_PORT:-8790})
TODO=(fl2va); [[ $REF == 1 ]] && TODO+=(ref2va); [[ $WEB == 1 ]] && TODO+=(web)
START=()
for w in "${TODO[@]}"; do
  p=${PORT[$w]}
  if in_use "$p"; then
    if [[ $w == web ]] || healthy "$p"; then yellow "· $w: 포트 $p 에서 이미 떠 있다 → 그대로 쓴다"
    else fail "$w: 포트 $p 를 다른 프로그램이 쓰고 있다" "bash scripts/down.sh 또는 ss -ltnp 로 확인"; fi
  else START+=("$w"); fi
done
if [[ $problems -gt 0 ]]; then red "== 문제 ${problems}개: 위 → 를 처리한 뒤 다시 실행"; exit 1; fi
green "== 점검 통과"; [[ $CHECK == 1 ]] && exit 0

# 3) 이 화면에서 포그라운드로 실행. 각 서버의 출력(원본 로그·오류)이 그대로 이 화면에 나온다.
PIDS=(); NAMES=()
cleanup() {   # 서버·웹 UI 를 하위 프로세스까지 끄고 GPU 반환 확인
  trap - INT TERM HUP EXIT
  echo; yellow "== 끄는 중: ${NAMES[*]} (GPU 반환까지 확인)"
  h3_stop_tree "${PIDS[@]}"
  rm -f "$H3_LOG_DIR/web.pid" "$H3_LOG_DIR"/serve-*.pid
  green "== 종료"
}
trap 'cleanup; exit 130' INT TERM HUP
for w in "${START[@]}"; do
  case $w in
    fl2va) cmd=(bash scripts/serve.sh fl2va --gpus "$GPUS" "${MODE_ARGS[@]}") ;;
    ref2va) cmd=(bash scripts/serve.sh ref2va --gpus "$REF_GPUS" "${MODE_ARGS[@]}") ;;
    web) cmd=(python3 -m h3video.cli web --host 127.0.0.1 --port "${PORT[web]}"); [[ -n "$CORS" ]] && cmd+=(--cors-origin "$CORS") ;;
  esac
  echo "== $w 시작: ${cmd[*]}"
  # 작업 제어(set -m)로 서버마다 자기 프로세스 그룹을 갖게 한다: $! 가 곧 그룹 번호라 끌 때 하위 프로세스까지 정확히 끈다.
  # (setsid 는 경우에 따라 한 번 더 fork 해서 $! 가 금방 끝나는 중간 프로세스가 될 수 있다.) 출력은 그대로 이 화면으로.
  set -m; "${cmd[@]}" & PIDS+=($!); set +m
  NAMES+=("$w")
  [[ $w == web ]] && echo $! > "$H3_LOG_DIR/web.pid"
done

# 4) 준비될 때까지 기다린다 (시간 제한 없음, H3_UP_TIMEOUT=초 로 걸 수 있음). 그동안 로그는 위에 그대로 흐른다.
limit=${H3_UP_TIMEOUT:-0}; t=0
pid_of() { local i; for i in "${!NAMES[@]}"; do [[ ${NAMES[$i]} == "$1" ]] && echo "${PIDS[$i]}"; done; }
# 서버가 살아 있는가: 실행 스크립트가 살아 있고, (시작 후 10초가 지났다면) 그룹 안에 sglang 본체("sglang serve")가 있어야 한다.
# 본체가 OOM 등으로 죽어도 워커가 로그 파이프를 잡고 있으면 serve.sh 가 끝나지 않으므로 본체를 직접 본다.
server_alive() {  # name pid seconds-since-start
  kill -0 "$2" 2>/dev/null || return 1
  [[ $1 == web || $3 -le 10 ]] && return 0
  pgrep -g "$2" -f 'sglang serve' >/dev/null
}
for w in "${START[@]}"; do
  [[ $w == web ]] && continue
  until healthy "${PORT[$w]}"; do
    if ! server_alive "$w" "$(pid_of "$w")" "$t"; then sleep 1; red "✗ $w 서버가 끝났다 (바로 위 로그가 원인). 남은 프로세스를 끄고 GPU 를 반환한다"; cleanup; exit 1; fi
    sleep 5; t=$((t + 5))
    if [[ $limit -gt 0 && $t -ge $limit ]]; then red "✗ $w: ${limit}초 안에 준비되지 않음"; cleanup; exit 1; fi
  done
  green "✓ $w 준비됨 (포트 ${PORT[$w]})"
done

# 5) 안내 (서버는 계속 이 화면에서 돈다)
host="$(hostname -f 2>/dev/null || hostname)"
echo
green "== 준비 완료. 로그는 계속 이 화면에 나온다. 끄기: Ctrl+C"
echo "  영상:   다른 창에서 source scripts/cluster_env.sh && h3video gen \"...\" -s 8"
echo "  PC 에서: ssh -N -L 8790:127.0.0.1:${PORT[web]} -L ${PORT[fl2va]}:127.0.0.1:${PORT[fl2va]} -L ${PORT[ref2va]}:127.0.0.1:${PORT[ref2va]} $(id -un)@$host"
echo "           그다음 브라우저 http://127.0.0.1:8790 (허브 숏폼 제작의 서버 주소도 http://localhost:8790)"
echo

# 서버 하나라도 끝나면 알리고 전부 끈다
while :; do
  for i in "${!PIDS[@]}"; do
    if ! server_alive "${NAMES[$i]}" "${PIDS[$i]}" 99; then red "✗ ${NAMES[$i]} 가 끝났다 (바로 위 로그가 원인). 남은 프로세스를 끄고 GPU 를 반환한다"; cleanup; exit 1; fi
  done
  sleep 3
done
