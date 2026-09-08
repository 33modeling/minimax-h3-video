#!/usr/bin/env bash
# MiniMax-H3 SGLang 서빙 — tmux 포그라운드에서 실행 (nohup 금지). 로그는 $H3_LOG_DIR 에 tee.
# 사용: source scripts/cluster_env.sh && bash scripts/serve.sh fl2va|ref2va [--gpus 0,1,2,3] [--mode speed|memory] [-- 추가 sglang 옵션]
#   fl2va : 텍스트→영상, 첫/끝 프레임→영상 (포트 $H3_PORT_FL2VA)
#   ref2va: 이미지·영상·오디오 레퍼런스→영상 (포트 $H3_PORT_REF2VA)
set -Eeuo pipefail
[[ -n "${STORAGE_ROOT:-}" ]] || { echo "cluster_env.sh 를 먼저 source 하라"; exit 1; }
VARIANT="${1:-}"; shift || true
[[ "$VARIANT" == fl2va || "$VARIANT" == ref2va ]] || { echo "usage: serve.sh fl2va|ref2va [--gpus LIST] [--mode speed|memory] [-- extra]"; exit 2; }
GPUS="${CUDA_VISIBLE_DEVICES:-}"; MODE="${H3_PERF_MODE:-speed}"; EXTRA=()
while [[ $# -gt 0 ]]; do case "$1" in
  --gpus) GPUS="$2"; shift 2 ;; --mode) MODE="$2"; shift 2 ;; --) shift; EXTRA=("$@"); break ;;
  *) echo "알 수 없는 옵션: $1"; exit 2 ;; esac; done
if [[ -n "$GPUS" ]]; then export CUDA_VISIBLE_DEVICES="$GPUS"; NGPU=$(tr ',' '\n' <<<"$GPUS" | grep -c .); else NGPU="$H3_NUM_GPUS"; fi
PORT="$H3_PORT_FL2VA"; [[ "$VARIANT" == ref2va ]] && PORT="$H3_PORT_REF2VA"
[[ -f "$H3_MODEL_DIR/model_index.json" ]] || { echo "모델 없음: $H3_MODEL_DIR (provision.sh 또는 H3_MODEL_DIR 확인)"; exit 1; }
command -v sglang >/dev/null || { echo "sglang 없음 — provision.sh 실행 또는 docker 사용"; exit 1; }
if ss -ltn 2>/dev/null | grep -q ":$PORT "; then echo "포트 $PORT 이미 사용 중 (stop.sh 로 정리)"; exit 1; fi

LOG="$H3_LOG_DIR/serve-$VARIANT-$(date +%Y%m%d-%H%M%S).log"
PIDFILE="$H3_LOG_DIR/serve-$VARIANT.pid"
echo "[serve] variant=$VARIANT gpus=${CUDA_VISIBLE_DEVICES:-all}($NGPU) mode=$MODE port=$PORT model=$H3_MODEL_DIR log=$LOG"
echo $$ > "$PIDFILE"
exec sglang serve \
  --model-path "$H3_MODEL_DIR" \
  --model-variant "$VARIANT" \
  --num-gpus "$NGPU" --ulysses-degree "$NGPU" \
  --performance-mode "$MODE" \
  --host "$H3_HOST" --port "$PORT" \
  "${EXTRA[@]}" 2>&1 | tee "$LOG"
