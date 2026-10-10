#!/usr/bin/env bash
# MiniMax-H3 서빙 — 포그라운드 실행 (nohup 금지). 로그는 $H3_LOG_DIR 에 tee.
# 엔진은 cluster_env.sh 가 드라이버를 보고 고른다: CUDA 12.x → diffusers(h3video.dserver), CUDA 13+ → sglang.
# 사용: source scripts/cluster_env.sh && bash scripts/serve.sh fl2va|ref2va [--gpus 0,1,2,3] [--mode speed|memory] [-- 추가 sglang 옵션]
#   fl2va : 텍스트→영상, 첫/끝 프레임→영상 (포트 $H3_PORT_FL2VA)
#   ref2va: 이미지·영상·오디오 레퍼런스→영상 (포트 $H3_PORT_REF2VA)
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 환경은 이 스크립트가 직접 읽는다: 셸에 남은 예전 값(H3_MODEL_DIR 등)이 아니라 고정 위치를 쓰게
# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cluster_env.sh" >/dev/null || { echo "cluster_env.sh 실패"; exit 1; }
VARIANT="${1:-}"; shift || true
[[ "$VARIANT" == fl2va || "$VARIANT" == ref2va ]] || { echo "usage: serve.sh fl2va|ref2va [--gpus LIST] [--mode speed|memory] [-- extra]"; exit 2; }
GPUS="${CUDA_VISIBLE_DEVICES:-}"; MODE="${H3_PERF_MODE:-speed}"; EXTRA=()
while [[ $# -gt 0 ]]; do case "$1" in
  --gpus) GPUS="$2"; shift 2 ;; --mode) MODE="$2"; shift 2 ;; --) shift; EXTRA=("$@"); break ;;
  *) echo "알 수 없는 옵션: $1"; exit 2 ;; esac; done
if [[ -n "$GPUS" ]]; then export CUDA_VISIBLE_DEVICES="$GPUS"; NGPU=$(tr ',' '\n' <<<"$GPUS" | grep -c .); else NGPU="$H3_NUM_GPUS"; fi
PORT="$H3_PORT_FL2VA"; [[ "$VARIANT" == ref2va ]] && PORT="$H3_PORT_REF2VA"
if [[ "$H3_ENGINE" == diffusers ]]; then   # 드라이버 CUDA 12.x 노드 (cluster_env.sh 가 고른다)
  [[ -x "$VENV/bin/python" ]] || { echo "Diffusers venv 없음: $VENV — bash scripts/provision.sh"; exit 1; }
  "$VENV/bin/python" "$ROOT/scripts/check_diffusers_model.py" "$H3_DIFFUSERS_DIR" --variant "$VARIANT" \
    || { echo "→ bash scripts/provision.sh$([[ $VARIANT == ref2va ]] && echo ' --ref') (없는 것만 받는다)"; exit 1; }
else
  [[ -f "$H3_MODEL_DIR/model_index.json" ]] || { echo "모델 없음: $H3_MODEL_DIR (provision.sh 또는 H3_MODEL_DIR 확인)"; exit 1; }
  h3_cuda_compat || exit 1   # 드라이버가 CUDA 12.x 면 CUDA 13 호환 라이브러리
  command -v sglang >/dev/null || { echo "sglang 없음 — provision.sh 실행 또는 docker 사용"; exit 1; }
  "$VENV/bin/python" "$ROOT/scripts/check_torchvision.py" --repair
fi
port_busy() {
  python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(0)   # 누가 쓰고 있다
sys.exit(1)
PY
}
if port_busy; then echo "포트 $PORT 이미 사용 중 (이미 떠 있는 서버를 쓰거나 bash scripts/down.sh)"; exit 1; fi

LOG="$H3_LOG_DIR/serve-$VARIANT-$(date +%Y%m%d-%H%M%S).log"
PIDFILE="$H3_LOG_DIR/serve-$VARIANT.pid"
echo $$ > "$PIDFILE"
export H3_SERVE_ID="$VARIANT-$$"   # 이 serve.sh 가 띄운 서버·워커 표시 (h3_leftovers.py 가 남은 것을 이것으로 찾는다)
if [[ "$H3_ENGINE" == diffusers ]]; then
  echo "[serve] engine=diffusers variant=$VARIANT gpus=${CUDA_VISIBLE_DEVICES:-all} port=$PORT model=$H3_DIFFUSERS_DIR log=$LOG"
  exec "$VENV/bin/python" -m h3video.dserver --model-dir "$H3_DIFFUSERS_DIR" --variant "$VARIANT" \
    --host "$H3_HOST" --port "$PORT" --out-dir "$STORAGE_ROOT/dserver/$VARIANT" "${EXTRA[@]}" 2>&1 | tee "$LOG"
  exit "${PIPESTATUS[0]}"
fi
echo "[serve] engine=sglang variant=$VARIANT gpus=${CUDA_VISIBLE_DEVICES:-all}($NGPU) mode=$MODE port=$PORT model=$H3_MODEL_DIR log=$LOG"
exec sglang serve \
  --model-path "$H3_MODEL_DIR" \
  --model-variant "$VARIANT" \
  --num-gpus "$NGPU" --ulysses-degree "$NGPU" \
  --performance-mode "$MODE" \
  --host "$H3_HOST" --port "$PORT" \
  "${EXTRA[@]}" 2>&1 | tee "$LOG"
