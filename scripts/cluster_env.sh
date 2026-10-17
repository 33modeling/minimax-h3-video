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
_h3_env_model="${H3_MODEL_DIR:-}"   # 셸에서 이미 정해 둔 값 (어디서 덮어썼는지 알려 주려고)
# .cluster_env.local.sh 안에서 이 파일을 다시 읽어도 되돌아가 반복하지 않게
[[ -n "${_H3_IN_LOCAL_ENV:-}" ]] && { return 0 2>/dev/null || exit 0; }
if [[ -f "$_REPO_ROOT/.cluster_env.local.sh" ]]; then _H3_IN_LOCAL_ENV=1; source "$_REPO_ROOT/.cluster_env.local.sh"; unset _H3_IN_LOCAL_ENV; fi

export GROUP_VOLUME_ROOT="${GROUP_VOLUME_ROOT:-/group-volume}"
export STORAGE_ROOT="${STORAGE_ROOT:-$GROUP_VOLUME_ROOT/minsoo3.kim/$REPO_NAME}"
export MODELS_DIR="${MODELS_DIR:-/rdata/models}"
# 모델 위치: ① 기본 /rdata/models/MiniMax-H3 → 없으면 ② 저장해 둔 경로(.cluster_env.local.sh·셸의 H3_MODEL_DIR)
#            → ③ group-volume 검색 → 그래도 없으면 ④ up.sh·provision.sh 가 경로를 묻는다. 받기는 하지 않는다.
H3_MODEL_DEFAULT="$MODELS_DIR/MiniMax-H3"
_h3_model_saved="${H3_MODEL_DIR:-}"
h3_model_ok() { [[ -d "$1" ]] && { [[ -f "$1/model_index.json" || -f "$1/modular_model_index.json" ]] || compgen -G "$1/[Ff][Ll]2[Vv][Aa]" >/dev/null; }; }
# 한 폴더 안의 구조 맞추기: 한 단계 더 들어간 폴더, HF 캐시(models--…/snapshots/<해시>), 대소문자 다른 이름
h3_resolve_model() {
  local base="$1" d f
  h3_model_ok "$base" && { echo "$base"; return 0; }
  if [[ ! -d "$base" ]]; then
    for d in "$(dirname "$base")"/*; do [[ -d "$d" && "${d##*/},," == "${base##*/},," ]] && base="$d"; done
    shopt -s nocasematch; for d in "$(dirname "$base")"/*; do [[ -d "$d" && "${d##*/}" == "${base##*/}" ]] && base="$d"; done; shopt -u nocasematch
  fi
  h3_model_ok "$base" && { echo "$base"; return 0; }
  [[ -d "$base" ]] || return 1
  while read -r f; do
    d="$(dirname "$f")"
    case "${d##*/}" in [Ff][Ll]2[Vv][Aa]|[Rr][Ee][Ff]2[Vv][Aa]) d="$(dirname "$d")" ;; esac
    h3_model_ok "$d" && { echo "$d"; return 0; }
  done < <(timeout 20 find -L "$base" -maxdepth 5 \( -iname model_index.json -o -iname modular_model_index.json \) 2>/dev/null | sort)
  return 1
}
# group-volume 검색: model_index.json 과 fl2va 폴더가 있는 곳
h3_find_models() {
  local f d
  timeout 30 find -L "$MODELS_DIR" "$GROUP_VOLUME_ROOT/models" "$GROUP_VOLUME_ROOT/minsoo3.kim" -maxdepth 6 \( -iname model_index.json -o -iname modular_model_index.json \) 2>/dev/null | sort | while read -r f; do
    d="$(dirname "$f")"
    case "${d##*/}" in [Ff][Ll]2[Vv][Aa]|[Rr][Ee][Ff]2[Vv][Aa]) d="$(dirname "$d")" ;; esac
    if compgen -G "$d/[Ff][Ll]2[Vv][Aa]" >/dev/null || [[ -f "$d/modular_model_index.json" ]]; then h3_model_ok "$d" && realpath -m -- "$d"; fi
  done
}
# 그래도 못 찾았을 때 경로를 묻는다 (up.sh·provision.sh 가 부른다). 정한 경로는 .cluster_env.local.sh 에 저장해 다음부터 묻지 않는다.
h3_ask_model_dir() {
  local p a tries=0 local_file="$_REPO_ROOT/.cluster_env.local.sh" real_home
  real_home="$(getent passwd "$(id -un)" | cut -d: -f6)"
  if ! { : </dev/tty; } 2>/dev/null; then
    echo "모델(MiniMax-H3 가중치)을 찾지 못했다: $H3_MODEL_DIR" >&2
    echo "  → $local_file 에 export H3_MODEL_DIR=<가중치 폴더> 를 적고 다시 실행" >&2
    return 1
  fi
  echo "모델(MiniMax-H3 가중치)을 찾지 못했다: $H3_MODEL_DIR"
  echo "  $GROUP_VOLUME_ROOT/models 안에 있는 것:"; ls -1 "$GROUP_VOLUME_ROOT/models" 2>/dev/null | head -20 | sed 's/^/    /'
  while (( tries < 3 )); do
    read -r -e -p "가중치 폴더 경로를 입력하세요 (Tab 자동완성, 빈 값은 취소): " p </dev/tty || return 1
    [[ -z "$p" ]] && return 1
    p="${p/#\~/$real_home}"; p="$(realpath -m -- "$p")"
    if h3_model_ok "$p"; then :
    elif [[ -d "$p" ]]; then
      echo "  이 폴더에는 model_index.json 이나 fl2va 폴더가 안 보인다. 들어 있는 것:"; ls -1 "$p" | head -15 | sed 's/^/    /'
      read -r -p "  그래도 이 경로를 쓸까요? [y/N] " a </dev/tty; [[ "$a" =~ ^[Yy] ]] || { tries=$((tries + 1)); continue; }
    else echo "  없는 경로: $p"; tries=$((tries + 1)); continue; fi
    export H3_MODEL_DIR="$p"
    touch "$local_file"
    if grep -q '^export H3_MODEL_DIR=' "$local_file"; then sed -i "s|^export H3_MODEL_DIR=.*|export H3_MODEL_DIR=\"$p\"|" "$local_file"
    else echo "export H3_MODEL_DIR=\"$p\"" >> "$local_file"; fi
    echo "  저장함: $local_file (다음부터 묻지 않는다)"
    return 0
  done
  return 1
}

if _m="$(h3_resolve_model "$H3_MODEL_DEFAULT")"; then
  export H3_MODEL_DIR="$_m"
elif [[ -n "$_h3_model_saved" ]] && _m="$(h3_resolve_model "$_h3_model_saved")"; then
  export H3_MODEL_DIR="$_m"; echo "[cluster-env] 기본 위치에 없어 저장된 경로를 쓴다: $_m" >&2
elif _m="$(h3_find_models | awk '!seen[$0]++' | head -1)"; [[ -n "$_m" ]]; then
  export H3_MODEL_DIR="$_m"; echo "[cluster-env] 기본 위치에 없어 찾은 곳을 쓴다: $_m" >&2
else
  export H3_MODEL_DIR="$H3_MODEL_DEFAULT"   # 못 찾음: up.sh·provision.sh 가 경로를 묻는다
fi

# 드라이버가 CUDA 12.x 인 노드(ubuntu22 이미지, R535)에서 CUDA 13 프로그램(H3 용 sglang 0.5.17+)을 돌리는 호환 라이브러리.
# NVIDIA forward compatibility: 데이터센터 GPU 는 cuda-compat 패키지의 libcuda 로 새 CUDA 를 쓸 수 있다. 관리자 권한 불필요.
H3_CUDA_COMPAT_PKG="${H3_CUDA_COMPAT_PKG:-cuda-compat-13-0_580.178.04-1ubuntu1_amd64.deb}"
H3_CUDA_COMPAT_DIR="${H3_CUDA_COMPAT_DIR:-$STORAGE_ROOT/cuda-compat/${H3_CUDA_COMPAT_PKG%.deb}}"
h3_driver_cuda() { nvidia-smi 2>/dev/null | grep -o 'CUDA Version: [0-9.]*' | awk '{print $3}'; }
h3_cuda_compat() {   # 필요하면 (처음 한 번) 받아서 풀고 LD_LIBRARY_PATH 앞에 넣는다. 0 = 준비됨 또는 필요 없음
  local drv lib deb url
  drv="$(h3_driver_cuda)"
  [[ -z "$drv" || "${drv%%.*}" -ge 13 ]] && return 0
  lib="$(find "$H3_CUDA_COMPAT_DIR" -name 'libcuda.so.*' -printf '%h\n' 2>/dev/null | head -1)"
  if [[ -z "$lib" ]]; then
    deb="$(dirname "$H3_CUDA_COMPAT_DIR")/$H3_CUDA_COMPAT_PKG"; mkdir -p "$(dirname "$deb")"
    if [[ ! -s "$deb" ]]; then
      url="https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/$H3_CUDA_COMPAT_PKG"
      echo "[cuda-compat] 드라이버가 CUDA $drv 까지라 CUDA 13 호환 라이브러리를 받는다 (처음 한 번, 약 65MB): $url"
      if ! curl -fL --retry 2 -o "$deb.part" "$url"; then
        echo "[cuda-compat] 받기 실패. 인터넷이 막혀 있으면 이 파일을 받아 $deb 에 두고 다시 실행: $url"; rm -f "$deb.part"; return 1
      fi
      mv "$deb.part" "$deb"
    fi
    mkdir -p "$H3_CUDA_COMPAT_DIR"
    if command -v dpkg-deb >/dev/null; then dpkg-deb -x "$deb" "$H3_CUDA_COMPAT_DIR"
    else (cd "$H3_CUDA_COMPAT_DIR" && ar x "$deb" && tar xf data.tar.*); fi || { echo "[cuda-compat] 풀기 실패: $deb"; return 1; }
    lib="$(find "$H3_CUDA_COMPAT_DIR" -name 'libcuda.so.*' -printf '%h\n' | head -1)"
    [[ -n "$lib" ]] || { echo "[cuda-compat] 풀었는데 libcuda 가 없다: $H3_CUDA_COMPAT_DIR"; return 1; }
  fi
  case ":${LD_LIBRARY_PATH:-}:" in *":$lib:"*) ;; *) export LD_LIBRARY_PATH="$lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;; esac
  echo "[cuda-compat] 드라이버 CUDA $drv 노드 → CUDA 13 호환 라이브러리 사용: $lib"
}

# 포트를 누가 쓰고 있나 (0 = 쓰는 중). ss 가 없는 컨테이너에서도 되게 실제로 바인딩해 본다.
h3_port_busy() {
  python3 - "$1" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(0)   # 누가 쓰고 있다
sys.exit(1)
PY
}

# 서버 끄기: 우리가 띄운 프로세스와 그 하위 프로세스(sglang 워커 등)만 정확히 끈다 (다른 GPU 실험은 건드리지 않는다).
h3_tree() { local c; echo "$1"; for c in $(ps -o pid= --ppid "$1" 2>/dev/null); do h3_tree "$c"; done; }
h3_stop_tree() {
  local pid all=() alive=() _ cl
  for pid in "$@"; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    if kill -0 "$pid" 2>/dev/null; then
      cl="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)"
      if [[ ! "$cl" =~ serve\.sh|sglang|h3video|vllm|qwen_image ]]; then echo "[stop] pid $pid 는 서버가 아니라 건너뜀 ($cl)"; continue; fi
      all+=($(h3_tree "$pid"))
    fi
    # 같은 프로세스 그룹(서버를 띄운 그룹 = pid)의 남은 프로세스: 본체가 죽어 부모가 바뀐 워커도 여기 남는다.
    # 그룹 번호는 그 그룹에 프로세스가 하나라도 있는 동안 다른 프로그램이 쓸 수 없어 우리 것만 잡힌다.
    all+=($(ps -eo pid=,pgid= | awk -v g="$pid" '$2 == g {print $1}'))
  done
  if [[ ${#all[@]} -gt 0 ]]; then
    all=($(printf '%s\n' "${all[@]}" | sort -un))
    kill -TERM "${all[@]}" 2>/dev/null
    for _ in $(seq 1 30); do alive=(); for pid in "${all[@]}"; do kill -0 "$pid" 2>/dev/null && alive+=("$pid"); done
      [[ ${#alive[@]} -eq 0 ]] && break; sleep 1; done
    if [[ ${#alive[@]} -gt 0 ]]; then echo "[stop] 30초 안에 안 꺼져 강제 종료: ${alive[*]}"; kill -KILL "${alive[@]}" 2>/dev/null; sleep 3; fi
  fi
  if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
    sleep 2
    nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/[stop] GPU /'
    local left; left="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)"
    [[ -n "$left" ]] && { echo "[stop] 아직 GPU 를 쓰는 프로세스 (이 스크립트가 띄운 것 아님, 그대로 둠):"; sed 's/^/    /' <<<"$left"; }
  fi
  return 0
}

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
export CUDA_DEVICE_ORDER=PCI_BUS_ID   # CUDA 번호를 nvidia-smi 번호와 같게 (--gpus 1 이 nvidia-smi 의 GPU 1)
export NCCL_ASYNC_ERROR_HANDLING=1 TORCH_NCCL_ASYNC_ERROR_HANDLING=1
mkdir -p "$H3_OUTPUT_DIR" "$H3_INBOX_DIR" "$H3_LOG_DIR" "$STORAGE_ROOT/runs" "$HOME" "$TMPDIR" "$HF_HUB_CACHE" \
         "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$TORCH_HOME" "$TORCH_EXTENSIONS_DIR" \
         "$TRITON_CACHE_DIR" "$CUDA_CACHE_PATH" "$PIP_CACHE_DIR" "$PYTHONPYCACHEPREFIX" "$MPLCONFIGDIR" || {
  echo "스크래치 생성 실패: $WORK_ROOT" >&2; return 2 2>/dev/null || exit 2; }

# 엔진: sglang = 드라이버 CUDA 13 이상 노드 | diffusers = 드라이버 CUDA 12.x 노드 (H3 용 sglang 0.5.17+ 은 CUDA 13 전용이라).
# 기본 auto: 노드 드라이버를 보고 고른다. 고정하려면 H3_ENGINE=sglang|diffusers
if [[ "${H3_ENGINE:-auto}" == auto ]]; then
  _drv="$(h3_driver_cuda)"
  if [[ -n "$_drv" && "${_drv%%.*}" -lt 13 ]]; then H3_ENGINE=diffusers; else H3_ENGINE=sglang; fi
fi
export H3_ENGINE
if [[ "$H3_ENGINE" == diffusers ]]; then
  export VENV="${H3_DIFFUSERS_VENV:-$STORAGE_ROOT/.venv-diffusers}"   # torch 2.7.1(CUDA 12.6) + diffusers 0.41 — sglang venv 와 따로
  # Diffusers 형식 폴더: 공유 모델 폴더에 이미 있으면 그대로, 없으면 내 저장 공간에 (텍스트 인코더는 FL2VA 것을 링크로 재사용)
  if [[ -z "${H3_DIFFUSERS_DIR:-}" ]]; then
    if [[ -f "$H3_MODEL_DIR/modular_model_index.json" && -d "$H3_MODEL_DIR/transformer" ]]; then H3_DIFFUSERS_DIR="$H3_MODEL_DIR"
    elif [[ -f "$MODELS_DIR/MiniMax-H3-diffusers/modular_model_index.json" ]]; then H3_DIFFUSERS_DIR="$MODELS_DIR/MiniMax-H3-diffusers"
    elif [[ -f "$STORAGE_ROOT/models/MiniMax-H3-diffusers/modular_model_index.json" ]]; then H3_DIFFUSERS_DIR="$STORAGE_ROOT/models/MiniMax-H3-diffusers"
    else H3_DIFFUSERS_DIR="$MODELS_DIR/MiniMax-H3-diffusers"; fi
  fi
  export H3_DIFFUSERS_DIR
  export H3_GUIDE_DIR="${H3_GUIDE_DIR:-$STORAGE_ROOT/h3-guides}"   # MiniMax 공식 프롬프트 작성 가이드 (provision.sh 가 받는다)
else
  export VENV="${H3_VENV:-$STORAGE_ROOT/.venv}"
fi
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

echo "[cluster-env] engine=$H3_ENGINE storage=$STORAGE_ROOT model=$H3_MODEL_DIR${H3_DIFFUSERS_DIR:+ diffusers=$H3_DIFFUSERS_DIR} outputs=$H3_OUTPUT_DIR scratch=$WORK_ROOT venv=$VENV"
