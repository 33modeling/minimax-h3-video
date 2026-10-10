#!/usr/bin/env bash
# H100 클러스터 환경 — fdmu 규약 이식. 매 셸에서: source scripts/cluster_env.sh
#
# 저장 규약: user-volume(체크아웃)에는 코드만. 모든 저장물은 group-volume.
#   프로젝트 저장:   $GROUP_VOLUME_ROOT/minsoo3.kim/minimax-h3-video   (outputs/ logs/ inbox/ .venv)
#   모델(공유):      $GROUP_VOLUME_ROOT/models/MiniMax-H3               (FL2VA/ Ref2VA/ model_index.json)
#   호스트 스크래치: <프로젝트>/runtime/<user>/<host>  (HOME·TMP·라이브러리 캐시 재지향)
# 오버라이드: 리포 루트의 .cluster_env.local.sh (비추적) 가 먼저 source 된다.
# 클러스터 제약: GitHub egress 없음(코드는 rsync), HF Hub 불안정(provision.sh 미러 폴백).

REPO_NAME=minimax-h3-video
_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$_REPO_ROOT/.cluster_env.local.sh" ]] && source "$_REPO_ROOT/.cluster_env.local.sh"

export GROUP_VOLUME_ROOT="${GROUP_VOLUME_ROOT:-/group-volume}"
export STORAGE_ROOT="${STORAGE_ROOT:-$GROUP_VOLUME_ROOT/minsoo3.kim/$REPO_NAME}"
export MODELS_DIR="${MODELS_DIR:-$GROUP_VOLUME_ROOT/models}"
_h3_model_explicit="${H3_MODEL_DIR:-}"
export H3_MODEL_DIR="${H3_MODEL_DIR:-$MODELS_DIR/MiniMax-H3}"

# 이미 받아 둔 MiniMax-H3 가중치 찾기 (받기는 하지 않는다). 폴더 이름·대소문자·HF 캐시 구조가 달라도 찾는다:
# model_index.json 이 있고 fl2va 폴더(대소문자 무관)가 있는 곳. FL2VA/ 안의 model_index.json 을 찾으면 그 위 폴더.
h3_model_ok() { [[ -f "$1/model_index.json" ]] && compgen -G "$1/[Ff][Ll]2[Vv][Aa]" >/dev/null; }
h3_find_models() {
  local f d
  for d in "$MODELS_DIR/MiniMax-H3" "$GROUP_VOLUME_ROOT/models/MiniMax-H3"; do h3_model_ok "$d" && realpath -m -- "$d"; done
  timeout 20 find -L "$MODELS_DIR" "$GROUP_VOLUME_ROOT/models" "$GROUP_VOLUME_ROOT/minsoo3.kim/models" "$STORAGE_ROOT/models" \
      "${HF_HOME:-/nonexistent}/hub" -maxdepth 6 -iname model_index.json 2>/dev/null | while read -r f; do
    d="$(dirname "$f")"
    case "${d##*/}" in [Ff][Ll]2[Vv][Aa]|[Rr][Ee][Ff]2[Vv][Aa]) d="$(dirname "$d")" ;; esac
    h3_model_ok "$d" && realpath -m -- "$d"
  done
}
if [[ -z "$_h3_model_explicit" ]] && ! h3_model_ok "$H3_MODEL_DIR"; then
  _found="$(h3_find_models | awk '!seen[$0]++' | head -1)"
  if [[ -n "$_found" ]]; then
    echo "[cluster-env] 기본 경로에 가중치가 없어 이미 받아 둔 곳을 쓴다: $_found (고정하려면 .cluster_env.local.sh 에 export H3_MODEL_DIR=...)" >&2
    export H3_MODEL_DIR="$_found"
  fi
fi

_user="${USER:-$(id -un)}"; _host="${HOSTNAME:-$(hostname)}"
export WORK_ROOT="${WORK_ROOT:-$STORAGE_ROOT/runtime/$_user/$_host}"

for _p in "$STORAGE_ROOT" "$WORK_ROOT"; do
  case "$_p/" in "$GROUP_VOLUME_ROOT"/*) ;; *)
    echo "저장 경로가 group-volume 밖: $_p" >&2; return 2 2>/dev/null || exit 2;; esac
done

# 서빙/클라이언트 기본값
export H3_HOST="${H3_HOST:-0.0.0.0}"
export H3_PORT_FL2VA="${H3_PORT_FL2VA:-30010}"
export H3_PORT_REF2VA="${H3_PORT_REF2VA:-30011}"
export H3_NUM_GPUS="${H3_NUM_GPUS:-4}"
export H3_ENDPOINT="${H3_ENDPOINT:-http://127.0.0.1:$H3_PORT_FL2VA}"
export H3_REF_ENDPOINT="${H3_REF_ENDPOINT:-http://127.0.0.1:$H3_PORT_REF2VA}"
export H3_OUTPUT_DIR="${H3_OUTPUT_DIR:-$STORAGE_ROOT/outputs}"
export H3_INBOX_DIR="${H3_INBOX_DIR:-$STORAGE_ROOT/inbox}"   # 서버가 file:// 로 읽을 입력 파일 위치
export H3_LOG_DIR="${H3_LOG_DIR:-$STORAGE_ROOT/logs}"

# HF: 실행 경로는 오프라인 기본(Hub 차단 시 재시도 스톨 방지). provision.sh 가 자체 unset.
export HF_HOME="${HF_HOME:-$WORK_ROOT/huggingface}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

# HOME·temp·캐시류 전부 스크래치로
export HOME="$WORK_ROOT/home" TMPDIR="$WORK_ROOT/tmp" TMP="$WORK_ROOT/tmp" TEMP="$WORK_ROOT/tmp"
export XDG_CACHE_HOME="$WORK_ROOT/xdg_cache" XDG_CONFIG_HOME="$WORK_ROOT/xdg_config" XDG_DATA_HOME="$WORK_ROOT/xdg_data"
export HF_HUB_CACHE="$WORK_ROOT/hf/hub" TORCH_HOME="$WORK_ROOT/torch" TORCH_EXTENSIONS_DIR="$WORK_ROOT/torch_ext"
export TRITON_CACHE_DIR="$WORK_ROOT/triton" CUDA_CACHE_PATH="$WORK_ROOT/cuda" PIP_CACHE_DIR="$WORK_ROOT/pip"
export PYTHONPYCACHEPREFIX="$WORK_ROOT/pycache" MPLCONFIGDIR="$WORK_ROOT/matplotlib"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True   # H3 디코드 OOM 방지(공식 권고)
export NCCL_ASYNC_ERROR_HANDLING=1 TORCH_NCCL_ASYNC_ERROR_HANDLING=1
mkdir -p "$H3_OUTPUT_DIR" "$H3_INBOX_DIR" "$H3_LOG_DIR" "$STORAGE_ROOT/runs" "$HOME" "$TMPDIR" "$HF_HUB_CACHE" \
         "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$TORCH_HOME" "$TORCH_EXTENSIONS_DIR" \
         "$TRITON_CACHE_DIR" "$CUDA_CACHE_PATH" "$PIP_CACHE_DIR" "$PYTHONPYCACHEPREFIX" "$MPLCONFIGDIR" || {
  echo "스크래치 생성 실패: $WORK_ROOT" >&2; return 2 2>/dev/null || exit 2; }

export VENV="${H3_VENV:-$STORAGE_ROOT/.venv}"
[[ -x "$VENV/bin/python" ]] && export PATH="$VENV/bin:$PATH"
export PYTHONPATH="$_REPO_ROOT/src:$_REPO_ROOT/shortform${PYTHONPATH:+:$PYTHONPATH}"   # h3video + shorts(숏폼)

# 체크아웃의 runs/ 는 심볼릭 링크만 허용 (fdmu 패턴)
_RUNS="$_REPO_ROOT/runs"
if [[ -L "$_RUNS" ]]; then
  [[ "$(realpath -m -- "$_RUNS")" == "$(realpath -m -- "$STORAGE_ROOT/runs")" ]] || {
    echo "runs/ symlink target mismatch: $_RUNS -> $(readlink "$_RUNS")" >&2; return 2 2>/dev/null || exit 2; }
elif [[ -e "$_RUNS" ]]; then
  echo "runs/ 가 실제 디렉토리 — user-volume 저장 금지. 옮긴 뒤 삭제하라: $_RUNS" >&2; return 2 2>/dev/null || exit 2
else ln -s "$STORAGE_ROOT/runs" "$_RUNS"; fi

echo "[cluster-env] storage=$STORAGE_ROOT model=$H3_MODEL_DIR outputs=$H3_OUTPUT_DIR scratch=$WORK_ROOT venv=$VENV"
