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
# .cluster_env.local.sh 안에서 이 파일을 다시 읽어도 되돌아가 반복하지 않게
[[ -n "${_H3_IN_LOCAL_ENV:-}" ]] && { return 0 2>/dev/null || exit 0; }
if [[ -f "$_REPO_ROOT/.cluster_env.local.sh" ]]; then _H3_IN_LOCAL_ENV=1; source "$_REPO_ROOT/.cluster_env.local.sh"; unset _H3_IN_LOCAL_ENV; fi

export GROUP_VOLUME_ROOT="${GROUP_VOLUME_ROOT:-/group-volume}"
export STORAGE_ROOT="${STORAGE_ROOT:-$GROUP_VOLUME_ROOT/minsoo3.kim/$REPO_NAME}"
export MODELS_DIR="${MODELS_DIR:-$GROUP_VOLUME_ROOT/models}"
# 모델 위치 (고정): /group-volume/models/MiniMax-H3
export H3_MODEL_DIR="${H3_MODEL_DIR:-$GROUP_VOLUME_ROOT/models/MiniMax-H3}"
h3_model_ok() { [[ -d "$1" ]] && { [[ -f "$1/model_index.json" ]] || compgen -G "$1/[Ff][Ll]2[Vv][Aa]" >/dev/null; }; }

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
