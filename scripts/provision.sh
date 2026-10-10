#!/usr/bin/env bash
# 프로비저닝 (멱등): venv + sglang[diffusion] + MiniMax-H3 가중치 확인.
# 사용: source scripts/cluster_env.sh && bash scripts/provision.sh [--fl2va-only] [--skip-model] [--download]
# 가중치는 기본으로 **받지 않는다**: 이미 받아 둔 곳을 찾아 확인만 한다(cluster_env.sh 가 자동으로 찾음).
# 정말 새로 받아야 할 때만 --download (수백 GB, 받을 위치는 H3_MODEL_DIR).
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
# 환경은 이 스크립트가 직접 읽는다: 셸에 남은 예전 값(H3_MODEL_DIR 등)이 아니라 고정 위치를 쓰게
# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cluster_env.sh" >/dev/null || { echo "cluster_env.sh 실패"; exit 1; }
unset HF_HUB_OFFLINE HF_DATASETS_OFFLINE TRANSFORMERS_OFFLINE || true
log() { printf '[provision %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
mkdir -p "$H3_LOG_DIR"; PROV_LOG="$H3_LOG_DIR/provision-$(date +%Y%m%d-%H%M%S).log"
exec > >(trap '' INT; tee -a "$PROV_LOG") 2>&1
log "로그 파일: $PROV_LOG"

FL2VA_ONLY=0 SKIP_MODEL=0 DOWNLOAD=0
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3.12}"
for arg in "$@"; do case "$arg" in
  --fl2va-only) FL2VA_ONLY=1 ;; --skip-model) SKIP_MODEL=1 ;; --download) DOWNLOAD=1 ;;
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
# Verify native torchvision operators too; importing torch alone misses ABI mismatches.
"$VENV/bin/python" "$ROOT/scripts/check_torchvision.py" --repair --cpu-only
# sglang 이 고정한 torchaudio(PyPI 기본판)는 torch(CUDA 13 빌드)와 CUDA 가 달라 _torchaudio.abi3.so 를 못 읽는다
#  → 같은 버전의 torch CUDA 빌드(예: 2.11.0+cu130)로 맞춘다
if ! "$VENV/bin/python" -c "import torch, torchaudio" 2>/dev/null; then
  tcu="$("$VENV/bin/python" -c "import torch; print('cu' + (torch.version.cuda or '').replace('.', '')[:3])" 2>/dev/null)"
  tav="$("$VENV/bin/python" -m pip show torchaudio 2>/dev/null | awk '/^Version:/{print $2}' | cut -d+ -f1)"
  if [[ -n "$tav" && "$tcu" == cu1* ]]; then
    log "torchaudio $tav 를 torch 와 같은 CUDA 빌드($tcu)로 맞춘다"
    "$VENV/bin/python" -m pip install --force-reinstall --no-deps "torchaudio==$tav+$tcu" --index-url "https://download.pytorch.org/whl/$tcu" \
      || log "경고: torchaudio 맞추기 실패 — 직접: pip install --force-reinstall --no-deps torchaudio==$tav+$tcu --index-url https://download.pytorch.org/whl/$tcu"
  fi
fi
"$VENV/bin/python" -c "import torch, torchaudio; print('torch', torch.__version__, '/ torchaudio', torchaudio.__version__)" || log "경고: torchaudio 를 불러오지 못한다 (위 오류)"

# H3 를 지원하는 sglang(0.5.17+)은 CUDA 13 전용(torch 2.11+, flashinfer[cu13]) → 노드 드라이버가 580 이상이어야 한다
drv="$(nvidia-smi 2>/dev/null | grep -o 'CUDA Version: [0-9.]*' | awk '{print $3}')"
if [[ -n "$drv" && "${drv%%.*}" -lt 13 ]]; then
  log "주의: 이 노드 드라이버는 CUDA $drv 까지다. H3 용 sglang(CUDA 13)은 드라이버 580 이상 노드에서만 돈다 (B200·B300 등, 또는 드라이버 업데이트)"
fi

# 2) 모델: 확인만. 받기는 --download 일 때만 (예전에는 경로만 달라도 전부 다시 받았다)
fl2va_ok() { h3_model_ok "$H3_MODEL_DIR"; }   # cluster_env.sh: model_index.json + fl2va 폴더(대소문자 무관)
if [[ "$SKIP_MODEL" == 1 ]]; then log "모델 단계 스킵"
elif fl2va_ok; then
  log "모델 확인: $H3_MODEL_DIR (FL2VA 있음)"
  compgen -G "$H3_MODEL_DIR/[Rr][Ee][Ff]2[Vv][Aa]" >/dev/null && log "Ref2VA 있음" \
    || log "Ref2VA 없음 → ref2va(레퍼런스→영상) 서버는 못 띄운다. fl2va 는 그대로 쓴다 (받지 않음)"
elif [[ "$DOWNLOAD" != 1 ]] && h3_ask_model_dir; then
  log "모델 경로: $H3_MODEL_DIR (.cluster_env.local.sh 에 저장)"
elif [[ "$DOWNLOAD" != 1 ]]; then
  log "가중치가 없다: $H3_MODEL_DIR (ls 로 확인). 새로 받으려면: bash scripts/provision.sh --download"
  exit 1
else
  log "다운로드(--download): MiniMaxAI/MiniMax-H3 -> $H3_MODEL_DIR"
  INCLUDE=(--include "model_index.json" "FL2VA/*"); [[ "$FL2VA_ONLY" == 1 ]] || INCLUDE+=("Ref2VA/*")
  mkdir -p "$H3_MODEL_DIR"
  hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR" \
  || { log "Hub 실패 — 미러 재시도"; HF_ENDPOINT=https://hf-mirror.com hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR"; } \
  || { log "미러도 실패 — 로컬에서 받아 rsync: hf download MiniMaxAI/MiniMax-H3 --include model_index.json 'FL2VA/*' 'Ref2VA/*' --local-dir MiniMax-H3"; exit 1; }
  fl2va_ok || { log "다운로드 후에도 불완전: $H3_MODEL_DIR"; exit 1; }
fi
du -sh "$H3_MODEL_DIR" 2>/dev/null || true
log "완료. 다음: bash scripts/serve.sh fl2va   (tmux 포그라운드)"
