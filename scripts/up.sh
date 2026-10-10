#!/usr/bin/env bash
# 클러스터 노드에서 명령 하나로: 환경 설정 → 점검 → tmux 세션에 서버·웹 UI 띄우기 → 준비될 때까지 대기 → PC 접속 방법 안내.
#
#   bash scripts/up.sh                 fl2va 서버(GPU 0,1,2,3) + 웹 UI(8790)
#   bash scripts/up.sh --ref           ref2va 서버도 (GPU 4,5,6,7 — 8장 노드)
#   bash scripts/up.sh --no-web        웹 UI 없이
#   bash scripts/up.sh --gpus 0,1,2,3 --ref-gpus 4,5,6,7 --mode memory
#   bash scripts/up.sh --cors https://33modeling.pages.dev    허브 '숏폼 제작'에서 웹 UI 를 부를 수 있게
#   bash scripts/up.sh --check         점검만
# 끄기: bash scripts/down.sh       보기: tmux attach -t h3   (창: fl2va · ref2va · web)
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
command -v tmux >/dev/null || fail "tmux 가 없다" "apt install tmux 또는 관리자에게 요청"
[[ -f "$H3_MODEL_DIR/model_index.json" ]] && green "✓ 모델: $H3_MODEL_DIR" || fail "모델 없음: $H3_MODEL_DIR" "bash scripts/provision.sh, 또는 .cluster_env.local.sh 에 H3_MODEL_DIR"
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

# 3) tmux 세션에 창마다 포그라운드로 띄운다 (로그는 창과 $H3_LOG_DIR 에 같이 남는다)
win_cmd() {  # 창이 끝나도 바로 닫히지 않게 메시지를 남긴다
  printf 'cd %q && source scripts/cluster_env.sh >/dev/null && %s; echo; echo "[%s 종료됨: 위 로그 확인. Enter 로 창 닫기]"; read' "$ROOT" "$1" "$2"
}
# tmux 서버가 이미 떠 있으면 새 창은 그 서버의 환경을 물려받는다. 이 셸에서 정한 값(명령줄의 H3_PORT_* 등)이
# 창에도 가도록 관련 변수를 -e 로 넘긴다 (tmux 3.0+).
E_ARGS=()
while IFS='=' read -r k _; do
  [[ "$k" =~ ^(H3_[A-Z0-9_]*|GROUP_VOLUME_ROOT|STORAGE_ROOT|MODELS_DIR|WORK_ROOT|PATH|CUDA_VISIBLE_DEVICES|HF_[A-Z_]*)$ ]] && E_ARGS+=(-e "$k=${!k}")
done < <(env)
for w in "${START[@]}"; do
  case $w in
    fl2va) cmd="bash scripts/serve.sh fl2va --gpus $GPUS ${MODE_ARGS[*]}" ;;
    ref2va) cmd="bash scripts/serve.sh ref2va --gpus $REF_GPUS ${MODE_ARGS[*]}" ;;
    web) cmd="python3 -m h3video.cli web --host 127.0.0.1 --port ${PORT[web]}${CORS:+ --cors-origin $CORS}" ;;
  esac
  if tmux has-session -t "$SESSION" 2>/dev/null; then tmux new-window -d "${E_ARGS[@]}" -t "$SESSION" -n "$w" "$(win_cmd "$cmd" "$w")"
  else tmux new-session -d "${E_ARGS[@]}" -s "$SESSION" -n "$w" "$(win_cmd "$cmd" "$w")"; fi
  echo "· tmux $SESSION:$w ← $cmd"
done

# 4) 준비될 때까지 대기 (모델 로딩에 몇 분). 서버 창이 먼저 끝나면 로그 끝부분을 보여 주고 멈춘다
limit=${H3_UP_TIMEOUT:-1800}; t=0
for w in "${START[@]}"; do
  [[ $w == web ]] && continue
  p=${PORT[$w]}; pidf="$H3_LOG_DIR/serve-$w.pid"
  until healthy "$p"; do
    sleep 5; t=$((t + 5))
    if [[ $t -gt 10 && -f "$pidf" ]] && ! kill -0 "$(cat "$pidf")" 2>/dev/null; then
      red "✗ $w 서버가 끝났다. 로그 끝부분:"; tail -n 20 "$(ls -t "$H3_LOG_DIR"/serve-$w-*.log 2>/dev/null | head -1)" 2>/dev/null; exit 1; fi
    if [[ $t -ge $limit ]]; then red "✗ $w: ${limit}초 안에 준비되지 않음 (tmux attach -t $SESSION 로 확인)"; exit 1; fi
    (( t % 30 == 0 )) && echo "  … $w 로딩 중 ${t}초: $(tail -n 1 "$(ls -t "$H3_LOG_DIR"/serve-$w-*.log 2>/dev/null | head -1)" 2>/dev/null | cut -c1-100)"
  done
  green "✓ $w 준비됨 (포트 $p)"
done

# 5) 안내
host="$(hostname -f 2>/dev/null || hostname)"
echo
green "== 실행 중 (tmux 세션 $SESSION)"
echo "  보기:   tmux attach -t $SESSION      (창 이동 Ctrl-b n, 나오기 Ctrl-b d)"
echo "  끄기:   bash scripts/down.sh"
echo "  영상:   h3video gen \"...\" -s 8          (이 노드에서. source scripts/cluster_env.sh 후)"
echo "  PC 에서: ssh -N -L 8790:127.0.0.1:${PORT[web]} -L ${PORT[fl2va]}:127.0.0.1:${PORT[fl2va]} -L ${PORT[ref2va]}:127.0.0.1:${PORT[ref2va]} $(id -un)@$host"
echo "           그다음 브라우저 http://127.0.0.1:8790 (허브 숏폼 제작의 서버 주소도 http://localhost:8790)"
