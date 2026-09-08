#!/usr/bin/env bash
# 프로비저닝 (멱등): venv + sglang[diffusion] + MiniMax-H3 가중치 검증/다운로드.
# 사용: source scripts/cluster_env.sh && bash scripts/provision.sh [--fl2va-only] [--skip-model]
# 가중치를 이미 올려 두었으면 H3_MODEL_DIR 만 맞추면 검증만 하고 지나간다.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
[[ -n "${STORAGE_ROOT:-}" ]] || { echo "cluster_env.sh 를 먼저 source 하라"; exit 1; }
unset HF_HUB_OFFLINE HF_DATASETS_OFFLINE TRANSFORMERS_OFFLINE || true
log() { printf '[provision %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

FL2VA_ONLY=0 SKIP_MODEL=0
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3.12}"
for arg in "$@"; do case "$arg" in
  --fl2va-only) FL2VA_ONLY=1 ;; --skip-model) SKIP_MODEL=1 ;;
  *) log "알 수 없는 옵션: $arg"; exit 2 ;; esac; done

# 1) venv
if [[ ! -x "$VENV/bin/python" ]]; then
  log "venv 생성: $VENV"
  "$PYTHON_BOOTSTRAP" -m venv "$VENV" || { "$PYTHON_BOOTSTRAP" -m venv --without-pip "$VENV";
    curl -sS https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" - || { log "get-pip 실패 — PIP_INDEX_URL 지정"; exit 1; }; }
fi
export PATH="$VENV/bin:$PATH"
log "패키지 설치 (h3video + sglang[diffusion])"
"$VENV/bin/pip" install -e ".[serve,dev]" ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} \
  || { log "pip 설치 실패 — sglang 은 docker lmsysorg/sglang:dev 로 대체 가능 (README 참조)"; exit 1; }
"$VENV/bin/python" -c "import sglang, sys; print('sglang', sglang.__version__)" || log "경고: sglang import 실패"

# 2) 모델 검증 → 없으면 다운로드 (Hub → hf-mirror 폴백)
model_ready() {
  [[ -f "$H3_MODEL_DIR/model_index.json" && -f "$H3_MODEL_DIR/FL2VA/model_index.json" \
     && -d "$H3_MODEL_DIR/FL2VA/transformer" ]] || return 1
  [[ "$FL2VA_ONLY" == 1 || -f "$H3_MODEL_DIR/Ref2VA/model_index.json" ]]
}
if [[ "$SKIP_MODEL" == 1 ]]; then log "모델 단계 스킵"
elif model_ready; then log "모델 검증 완료: $H3_MODEL_DIR"
else
  log "모델 불완전 → 다운로드: MiniMaxAI/MiniMax-H3 -> $H3_MODEL_DIR"
  INCLUDE=(--include "model_index.json" "FL2VA/*"); [[ "$FL2VA_ONLY" == 1 ]] || INCLUDE+=("Ref2VA/*")
  mkdir -p "$H3_MODEL_DIR"
  hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR" \
  || { log "Hub 실패 — 미러 재시도"; HF_ENDPOINT=https://hf-mirror.com hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR"; } \
  || { log "미러도 실패 — 로컬에서 받아 rsync: hf download MiniMaxAI/MiniMax-H3 --include model_index.json 'FL2VA/*' 'Ref2VA/*' --local-dir MiniMax-H3"; exit 1; }
  model_ready || { log "다운로드 후에도 불완전: $H3_MODEL_DIR"; exit 1; }
fi
du -sh "$H3_MODEL_DIR" 2>/dev/null || true
log "완료. 다음: bash scripts/serve.sh fl2va   (tmux 포그라운드)"
