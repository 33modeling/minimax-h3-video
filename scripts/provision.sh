#!/usr/bin/env bash
# 프로비저닝 (멱등): venv + 엔진 + MiniMax-H3 가중치 확인.
#   드라이버 CUDA 12.x 노드 → diffusers 엔진: torch 2.7.1(CUDA 12.6)+diffusers 0.41 venv, Diffusers 형식 가중치 중 없는 것만 받음
#                                (fl2va 약 72GB, --ref 면 +62GB. 텍스트 인코더 62GB 는 FL2VA 것을 링크로 재사용)
#   드라이버 CUDA 13 이상 노드  → sglang 엔진
# 사용: bash scripts/provision.sh [--ref] [--fl2va-only] [--skip-model] [--download]
# (sglang 엔진) 가중치는 기본으로 **받지 않는다**: 이미 받아 둔 곳을 찾아 확인만 한다(cluster_env.sh 가 자동으로 찾음).
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

FL2VA_ONLY=0 SKIP_MODEL=0 DOWNLOAD=0 REF=0
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3.12}"
for arg in "$@"; do case "$arg" in
  --fl2va-only) FL2VA_ONLY=1 ;; --skip-model) SKIP_MODEL=1 ;; --download) DOWNLOAD=1 ;; --ref) REF=1 ;;
  *) log "알 수 없는 옵션: $arg"; exit 2 ;; esac; done

make_venv() {
  [[ -x "$VENV/bin/python" ]] && return 0
  log "venv 생성: $VENV"
  "$PYTHON_BOOTSTRAP" -m venv "$VENV" || { "$PYTHON_BOOTSTRAP" -m venv --without-pip "$VENV";
    curl -sS https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" - || { log "get-pip 실패 — PIP_INDEX_URL 지정"; exit 1; }; }
}
hf_get() {  # hf download (Hub → 미러 순)
  "$VENV/bin/hf" download "${H3_HF_REPO:-MiniMaxAI/MiniMax-H3}" "$@" \
  || { log "Hub 실패 — 미러 재시도 (hf-mirror.com)"; HF_ENDPOINT=https://hf-mirror.com "$VENV/bin/hf" download "${H3_HF_REPO:-MiniMaxAI/MiniMax-H3}" "$@"; }
}

# ── 드라이버 CUDA 12.x 노드: Diffusers 엔진 (H3 용 sglang 0.5.17+ 은 CUDA 13 전용이라 못 쓴다) ──
if [[ "$H3_ENGINE" == diffusers ]]; then
  log "엔진: diffusers (드라이버 CUDA $(h3_driver_cuda || true)). torch 2.7.1(CUDA 12.6) — 기존 클러스터 레포와 같은 스택"
  make_venv
  "$VENV/bin/pip" install -c "$ROOT/constraints/h100-cu126-diffusers.txt" -e ".[diffusers,dev]" ${PIP_INDEX_URL:+-i "$PIP_INDEX_URL"} \
    || { log "pip 설치 실패 (위 오류). 인트라넷 미러가 있으면 PIP_INDEX_URL=<주소> 로 다시 실행"; exit 1; }
  "$VENV/bin/python" -c "import torch, torchvision, torchaudio, av, diffusers, transformers; from diffusers import MiniMaxH3ModularPipeline; print('torch', torch.__version__, 'CUDA', torch.version.cuda, '| diffusers', diffusers.__version__, '| transformers', transformers.__version__)" \
    || { log "패키지 import 실패 (위 오류)"; exit 1; }
  if nvidia-smi -L >/dev/null 2>&1; then   # GPU 가 있는 노드에서만 (GPU 없는 로그인 노드에서는 건너뜀)
    "$VENV/bin/python" -c "import torch; torch.zeros(1).cuda(); print('GPU', torch.cuda.device_count(), '장:', torch.cuda.get_device_name(0))" \
      || { log "torch 가 GPU 를 못 쓴다 (위 오류)"; exit 1; }
  else log "GPU 가 안 보이는 노드라 GPU 확인은 건너뜀 (up.sh 가 GPU 노드에서 다시 확인한다)"; fi
  # 프롬프트 다듬기에 쓰는 MiniMax 공식 작성 가이드 2개 (약 40KB, 모델 저장소의 docs/)
  if [[ ! -s "$H3_GUIDE_DIR/VIDEO_PROMPT_WRITING_GUIDE_base_en.md" || ! -s "$H3_GUIDE_DIR/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md" ]]; then
    log "공식 프롬프트 작성 가이드 받기 → $H3_GUIDE_DIR"
    G="$STORAGE_ROOT/.guides-dl"; mkdir -p "$G" "$H3_GUIDE_DIR"
    ( unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
      hf_get --include "docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md" --include "docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md" --local-dir "$G" ) \
      && cp "$G"/docs/VIDEO_PROMPT_WRITING_GUIDE_*_en.md "$H3_GUIDE_DIR"/ \
      || log "경고: 가이드를 못 받았다 → 서버는 프롬프트를 다듬지 않고 그대로 쓴다 (다시 실행하면 재시도)"
  fi
  ls "$H3_GUIDE_DIR"/VIDEO_PROMPT_WRITING_GUIDE_*_en.md 2>/dev/null | sed 's/^/  가이드: /'
  if [[ "$SKIP_MODEL" == 1 ]]; then log "모델 단계 스킵"; log "완료. 다음: bash scripts/up.sh"; exit 0; fi
  D="$H3_DIFFUSERS_DIR"; VARS=(fl2va); [[ "$REF" == 1 ]] && VARS+=(ref2va)
  ok_all() { local v; for v in "${VARS[@]}"; do "$VENV/bin/python" "$ROOT/scripts/check_diffusers_model.py" "$D" --variant "$v" --quiet || return 1; done; }
  if ok_all; then log "모델 확인: $D (Diffusers 형식, ${VARS[*]} 준비됨)"; du -shL "$D" 2>/dev/null || true; log "완료. 다음: bash scripts/up.sh$([[ $REF == 1 ]] && echo ' --ref')"; exit 0; fi
  mkdir -p "$D"
  # 텍스트 인코더(62GB)·토크나이저·프로세서는 공유 폴더의 FL2VA(또는 Ref2VA) 것과 파일이 같다(HF 해시 일치) → 링크로 재사용
  SRC=""; for s in "$H3_MODEL_DIR"/[Ff][Ll]2[Vv][Aa] "$H3_MODEL_DIR"/[Rr][Ee][Ff]2[Vv][Aa]; do [[ -f "$s/text_encoder/config.json" ]] && { SRC="$s"; break; }; done
  PATTERNS=(modular_model_index.json "scheduler/*" "audio_scheduler/*" "transformer/*" "vae/*" "audio_vae/*")
  [[ "$REF" == 1 ]] && PATTERNS+=("transformer_ref/*")
  for c in text_encoder tokenizer processor; do
    if [[ -e "$D/$c" ]]; then continue
    elif [[ -n "$SRC" && -d "$SRC/$c" ]]; then ln -s "$SRC/$c" "$D/$c"; log "재사용(링크): $D/$c → $SRC/$c"
    else PATTERNS+=("$c/*"); fi
  done
  GB=72; [[ "$REF" == 1 ]] && GB=$((GB + 62)); [[ " ${PATTERNS[*]} " == *" text_encoder/* "* ]] && GB=$((GB + 62))
  log "Diffusers 형식에 필요한데 없는 것만 받는다 (약 ${GB}GB, 이미 받은 파일은 건너뜀): ${PATTERNS[*]} → $D"
  unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE
  INC=(); for p in "${PATTERNS[@]}"; do INC+=(--include "$p"); done   # hf 1.x 는 --include 하나에 패턴 하나 (뒤 패턴은 파일 이름으로 처리된다)
  hf_get "${INC[@]}" --local-dir "$D" || { log "받기 실패 (위 오류). 다시 실행하면 이어서 받는다"; exit 1; }
  if ! ok_all; then for v in "${VARS[@]}"; do "$VENV/bin/python" "$ROOT/scripts/check_diffusers_model.py" "$D" --variant "$v"; done; log "받은 뒤에도 빠진 것이 있다 (위 목록). 다시 실행하면 이어서 받는다"; exit 1; fi
  du -shL "$D" 2>/dev/null || true
  log "완료. 다음: bash scripts/up.sh$([[ $REF == 1 ]] && echo ' --ref')"
  exit 0
fi

# ── 드라이버 CUDA 13 이상 노드: sglang 엔진 ──
# 1) venv
make_venv
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
  INCLUDE=(--include "model_index.json" --include "FL2VA/*"); [[ "$FL2VA_ONLY" == 1 ]] || INCLUDE+=(--include "Ref2VA/*")   # 패턴마다 --include
  mkdir -p "$H3_MODEL_DIR"
  hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR" \
  || { log "Hub 실패 — 미러 재시도"; HF_ENDPOINT=https://hf-mirror.com hf download MiniMaxAI/MiniMax-H3 "${INCLUDE[@]}" --local-dir "$H3_MODEL_DIR"; } \
  || { log "미러도 실패 — 로컬에서 받아 rsync: hf download MiniMaxAI/MiniMax-H3 --include model_index.json --include 'FL2VA/*' --include 'Ref2VA/*' --local-dir MiniMax-H3"; exit 1; }
  fl2va_ok || { log "다운로드 후에도 불완전: $H3_MODEL_DIR"; exit 1; }
fi
du -sh "$H3_MODEL_DIR" 2>/dev/null || true
log "완료. 다음: bash scripts/serve.sh fl2va   (tmux 포그라운드)"
