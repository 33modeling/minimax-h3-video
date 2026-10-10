#!/usr/bin/env bash
# 클러스터 노드에서 명령 하나로: 환경 설정 → 점검 → H3 서버를 이 화면에서 포그라운드로 실행 (웹 UI 는 --web 일 때만).
# 서버 원본 로그와 오류가 이 화면에 그대로 나온다. 준비되면 PC 접속 방법을 출력하고 계속 돈다. Ctrl+C 로 전부 끈다.
# (오래 띄워 둘 거면 직접 연 tmux 창 안에서 실행)
#
#   bash scripts/up.sh                 fl2va 서버(포트 30010) — CLI(h3video gen)는 이것만 있으면 된다
#   bash scripts/up.sh --ref           ref2va 서버도 (포트 30011)
#     GPU: --gpus 를 안 주면 비어 있는 GPU 를 쓴다. diffusers 엔진은 빈 GPU 전부(--ref 면 반씩), sglang 은 4장씩. 다른 프로세스가 쓰는 GPU 는 피한다
#   bash scripts/up.sh --web           웹 UI(8790)도 (브라우저·허브 숏폼 제작에서 쓸 때만)
#   bash scripts/up.sh --gpus 0,1,2,3 --ref-gpus 4,5,6,7 --mode memory
#   bash scripts/up.sh --cors https://33modeling.pages.dev    허브 '숏폼 제작'에서 웹 UI 를 부를 수 있게
#   bash scripts/up.sh --check         점검만
# 끄기: 이 화면에서 Ctrl+C (다른 창에서는 bash scripts/down.sh)
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${H3_TMUX:-h3}"
GPUS=""; REF_GPUS=""; REF=0; WEB=0; CHECK=0; MODE_ARGS=(); CORS="${H3_CORS_ORIGIN:-}"
while [[ $# -gt 0 ]]; do case "$1" in
  --ref) REF=1; shift ;; --web) WEB=1; shift ;; --no-web) WEB=0; shift ;; --check) CHECK=1; shift ;;
  --gpus) GPUS="$2"; shift 2 ;; --ref-gpus) REF_GPUS="$2"; shift 2 ;;
  --mode) MODE_ARGS=(--mode "$2"); shift 2 ;; --cors) CORS="$2"; shift 2 ;;
  -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "알 수 없는 옵션: $1 (--help)"; exit 2 ;; esac; done

red() { printf '\033[31m%s\033[0m\n' "$*"; }; green() { printf '\033[32m%s\033[0m\n' "$*"; }; yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
problems=0; fail() { red "✗ $1"; [[ -n "${2:-}" ]] && echo "   → $2"; problems=$((problems + 1)); }

# 1) 환경 (저장 경로·캐시·포트 기본값). 문제가 있으면 cluster_env.sh 가 이유를 출력한다
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" || { red "cluster_env.sh 실패 (위 메시지 참고)"; exit 1; }
cd "$ROOT"
# 이 화면에 나오는 것 전부(서버 원본 로그·오류 포함)를 파일로도 남긴다. Ctrl+C 때 기록이 끊기지 않게 tee 는 INT 를 무시
mkdir -p "$H3_LOG_DIR"; UP_LOG="$H3_LOG_DIR/up-$(date +%Y%m%d-%H%M%S).log"
exec > >(trap '' INT; tee -a "$UP_LOG") 2>&1
echo "[up] 로그 파일: $UP_LOG"

# 2) 점검
echo "[up] 엔진: $H3_ENGINE (드라이버 CUDA $(h3_driver_cuda || true); 12.x → diffusers, 13 이상 → sglang)"
# 전에 띄운 H3 서버·워커가 GPU 를 잡고 남아 있으면 먼저 내린다 (내 계정이 이 레포로 띄운 것만, 다른 작업은 그대로)
if ! python3 "$ROOT/scripts/h3_leftovers.py" >/dev/null 2>&1; then
  if [[ $CHECK == 1 ]]; then yellow "· 전에 띄운 H3 서버가 GPU 를 잡고 남아 있다 (up.sh 로 띄우면 먼저 내린다)"; python3 "$ROOT/scripts/h3_leftovers.py"
  else yellow "· 전에 띄운 H3 서버가 GPU 를 잡고 남아 있다 → 내리고 시작한다"; python3 "$ROOT/scripts/h3_leftovers.py" --kill; sleep 3; fi
fi
h3_model_ok "$H3_MODEL_DIR" || h3_ask_model_dir || true    # 기본·저장·검색으로도 없으면 경로를 묻는다
if h3_model_ok "$H3_MODEL_DIR" || grep -qs "^export H3_MODEL_DIR=\"$H3_MODEL_DIR\"" "$ROOT/.cluster_env.local.sh"; then green "✓ 모델: $H3_MODEL_DIR"
  # (sglang) Ref2VA 폴더 확인. diffusers 는 아래에서 transformer_ref 로 확인한다
  if [[ $REF == 1 && $H3_ENGINE == sglang ]] && ! compgen -G "$H3_MODEL_DIR/[Rr][Ee][Ff]2[Vv][Aa]" >/dev/null; then fail "Ref2VA 가중치 없음: $H3_MODEL_DIR/Ref2VA" "--ref 빼고 실행 (fl2va 만)"; fi
else
  fail "모델 없음: $H3_MODEL_DIR (model_index.json 이나 FL2VA 폴더를 찾지 못함)"
  echo "   그 폴더에 들어 있는 것:"; ls -la "$H3_MODEL_DIR" 2>&1 | head -20 | sed 's/^/     /'
  echo "   $(dirname "$H3_MODEL_DIR") 안:"; ls "$(dirname "$H3_MODEL_DIR")" 2>&1 | head -20 | sed 's/^/     /'
fi
if [[ "$H3_ENGINE" == diffusers ]]; then
  for v in fl2va $([[ $REF == 1 ]] && echo ref2va); do
    if python3 "$ROOT/scripts/check_diffusers_model.py" "$H3_DIFFUSERS_DIR" --variant "$v"; then green "✓ Diffusers 형식 가중치($v): $H3_DIFFUSERS_DIR"
    else fail "Diffusers 형식 가중치($v)가 아직 없다 (위 목록)" "bash scripts/provision.sh$([[ $REF == 1 ]] && echo ' --ref')  (없는 것만 받는다, 텍스트 인코더는 FL2VA 것 재사용)"; fi
  done
  if [[ -s "$H3_GUIDE_DIR/VIDEO_PROMPT_WRITING_GUIDE_base_en.md" && -s "$H3_GUIDE_DIR/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md" ]]; then
    green "✓ 프롬프트 다듬기: 공식 작성 가이드 있음 (짧은 요청을 H3 공식 형식으로 다시 써서 생성)"
  else yellow "· 공식 작성 가이드가 없어 프롬프트를 다듬지 않는다 → bash scripts/provision.sh --skip-model (40KB 만 받는다)"; fi
  if "$VENV/bin/python" -c "from diffusers import MiniMaxH3ModularPipeline" 2>/dev/null; then green "✓ diffusers: $VENV"
  else fail "Diffusers venv 없음 또는 불완전: $VENV" "bash scripts/provision.sh"; fi
  # 컴포넌트를 CPU 메모리에 두고 GPU 로 옮겨 쓴다: 서버 하나에 약 140GB (텍스트 인코더 62 + 영상 모델 62 + VAE 10)
  need_ram=$((140 * $([[ $REF == 1 ]] && echo 2 || echo 1)))
  # 컨테이너(쿠버네티스 파드)는 /proc/meminfo 가 노드 전체를 보여 주므로 cgroup 한도도 본다
  avail_ram=$(python3 - <<'PY' 2>/dev/null || echo 0
avail = next(int(l.split()[1]) * 1024 for l in open("/proc/meminfo") if l.startswith("MemAvailable"))
for lim_f, use_f in (("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
                     ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes")):
    try:
        lim = open(lim_f).read().strip()
    except OSError:
        continue
    if lim != "max" and int(lim) < 1 << 60:
        avail = min(avail, int(lim) - int(open(use_f).read()))
    break
print(max(0, avail) // 2**30)
PY
)
  if [[ $avail_ram -ge $need_ram ]]; then green "✓ 메모리 여유 ${avail_ram}GB (컨테이너 한도 반영, 필요 약 ${need_ram}GB)"
  else yellow "· 메모리 여유 ${avail_ram}GB (컨테이너 한도 반영) < 필요 약 ${need_ram}GB — 적재 중 메모리 부족으로 꺼질 수 있다$([[ $REF == 1 ]] && echo ' (--ref 빼면 약 140GB)')"; fi
else
  command -v sglang >/dev/null && green "✓ sglang: $(command -v sglang)" || fail "sglang 없음" "bash scripts/provision.sh (venv: $VENV)"
fi
healthy() {  # curl 이 없는 컨테이너에서도 되게 파이썬으로 /health 또는 /v1/models
  python3 - "$1" <<'PY' 2>/dev/null
import sys, urllib.request
for path in ("/health", "/v1/models"):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}{path}", timeout=5); sys.exit(0)
    except Exception:
        pass
sys.exit(1)
PY
}
in_use() { h3_port_busy "$1"; }   # ss 없이도 (실제 바인딩으로) 확인
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
# GPU: 띄울 서버마다 **비어 있는** GPU 를 쓴다. 다른 프로세스가 차지한 GPU 에 올리면 CUDA OOM 이 난다 (그 프로세스는 건드리지 않는다)
FREE_MIB=${H3_GPU_BUSY_MIB:-2048}   # 이만큼(MiB)보다 더 쓰고 있으면 '사용 중'
GALL=(); declare -A GUSED=() GTOT=()
while IFS=, read -r i u tt; do i=${i// /}; [[ -n "$i" ]] || continue; GALL+=("$i"); GUSED[$i]=${u// /}; GTOT[$i]=${tt// /}; done \
  < <(nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null)
FREE=(); for i in "${GALL[@]}"; do [[ ${GUSED[$i]} -le $FREE_MIB ]] && FREE+=("$i"); done
gpu_table() { local i; for i in "${GALL[@]}"; do echo "     GPU $i: $(( ${GUSED[$i]} / 1024 ))GB / $(( ${GTOT[$i]} / 1024 ))GB 사용$([[ ${GUSED[$i]} -gt $FREE_MIB ]] && echo '  ← 다른 프로세스가 쓰는 중')"; done
  nvidia-smi --query-compute-apps=gpu_bus_id,pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/     프로세스: /' | head -8; }
TAKEN=(); gpu_problems=$problems
if [[ ${#GALL[@]} -eq 0 ]]; then fail "GPU 가 안 보인다 (nvidia-smi 실패)" "GPU 노드인지, nvidia-smi 가 되는지 확인"
else
  for w in "${START[@]}"; do   # 직접 준 GPU 먼저 확인
    [[ $w == fl2va ]] && want="$GPUS"; [[ $w == ref2va ]] && want="$REF_GPUS"; [[ $w == web || -z "${want:-}" ]] && continue
    for i in ${want//,/ }; do
      if [[ -z "${GUSED[$i]:-}" ]]; then fail "$w: GPU $i 가 없다 (이 노드 GPU: ${GALL[*]})"
      elif [[ ${GUSED[$i]} -gt $FREE_MIB ]]; then fail "$w: GPU $i 를 다른 프로세스가 $(( ${GUSED[$i]} / 1024 ))GB 쓰고 있다 (여기에 올리면 OOM)" "비어 있는 GPU: ${FREE[*]:-없음} → --gpus 로 바꾸거나 --gpus 를 빼면 알아서 고른다"
      fi; TAKEN+=("$i")
    done
  done
  # 안 준 것은 비어 있는 GPU 에서: diffusers 는 남은 빈 GPU 를 서버 수로 나눠 전부(서버당 최대 8장), sglang 은 4장씩
  AUTO=(); for w in "${START[@]}"; do [[ $w == fl2va && -z "$GPUS" ]] && AUTO+=(fl2va); [[ $w == ref2va && -z "$REF_GPUS" ]] && AUTO+=(ref2va); done
  left=0; for i in "${FREE[@]}"; do [[ " ${TAKEN[*]} " == *" $i "* ]] || left=$((left + 1)); done
  if [[ "$H3_ENGINE" == diffusers ]]; then PER=$(( ${#AUTO[@]} > 0 ? left / ${#AUTO[@]} : 0 )); [[ $PER -gt 8 ]] && PER=8; [[ $PER -lt 1 ]] && PER=1
    [[ "${H3_DSERVER_CP:-1}" == 0 && $PER -gt 2 ]] && PER=2   # 여러 장 방식을 끄면 서버당 2장
  else PER=4; fi
  for w in "${AUTO[@]}"; do
    got=(); for i in "${FREE[@]}"; do [[ " ${TAKEN[*]} " == *" $i "* ]] && continue; got+=("$i"); [[ ${#got[@]} -ge $PER ]] && break; done
    if [[ ${#got[@]} -lt $PER ]]; then fail "$w: 비어 있는 GPU 가 ${#got[@]}장뿐이다 (필요 ${PER}장)" "아래 '다른 프로세스가 쓰는 중' GPU 는 이 레포가 띄운 서버가 아니다(남은 서버는 위에서 이미 내렸다). 그 작업을 끄거나 끝나길 기다린다$([[ $REF == 1 ]] && echo ', 또는 --ref 빼기')"; continue; fi
    TAKEN+=("${got[@]}"); sel=$(IFS=,; echo "${got[*]}")
    [[ $w == fl2va ]] && GPUS=$sel; [[ $w == ref2va ]] && REF_GPUS=$sel
  done
  layout() {   # GPU 목록 → 쓰는 방식 (diffusers)
    local n; n=$(tr ',' '\n' <<<"$1" | grep -c .)
    [[ "$H3_ENGINE" != diffusers ]] && return
    if [[ $n -ge 3 ]]; then echo " — 텍스트 인코더·VAE 1장 + 영상 모델 $((n - 1))장에 나눠 함께"
    elif [[ $n -eq 2 ]]; then echo " — 텍스트 인코더 1장 + 영상 모델 1장"
    else echo " — 1장에서 번갈아 올림 (느림)"; fi; }
  if [[ $problems -eq $gpu_problems ]]; then
    for w in "${START[@]}"; do [[ $w == fl2va ]] && green "✓ fl2va GPU $GPUS (비어 있음)$(layout "$GPUS")"; [[ $w == ref2va ]] && green "✓ ref2va GPU $REF_GPUS (비어 있음)$(layout "$REF_GPUS")"; done
  fi
fi
if [[ $problems -gt 0 ]]; then
  [[ ${#GALL[@]} -gt 0 ]] && { echo "   GPU 상태:"; gpu_table; }
  red "== 문제 ${problems}개: 위 → 를 처리한 뒤 다시 실행"; exit 1
fi
# (sglang 엔진) 드라이버가 CUDA 12.x 인데 sglang 으로 고정했으면 CUDA 13 호환 라이브러리를 써 본다
[[ "$H3_ENGINE" == sglang ]] && { h3_cuda_compat || fail "CUDA 13 호환 라이브러리를 준비하지 못했다 (위 [cuda-compat] 줄 참고)"; }
# GPU 를 실제로 쓸 수 있는지 (안 되면 원래 오류가 그대로 나온다)
if ! python3 -c "import torch; torch.zeros(1).cuda(); print('[up] torch', torch.__version__, 'CUDA', torch.version.cuda, '→', torch.cuda.get_device_name(0)); import torchaudio" ; then
  drv="$(nvidia-smi 2>/dev/null | grep -o 'CUDA Version: [0-9.]*' | awk '{print $3}')"
  fail "torch 가 GPU 를 못 쓴다 (바로 위 원래 오류 참고). 이 노드 드라이버는 CUDA ${drv:-?} 까지" \
       "$([[ $H3_ENGINE == diffusers ]] && echo "Diffusers venv 를 다시 맞춘다: bash scripts/provision.sh --skip-model" || echo "sglang(CUDA 13)이 이 드라이버에서 안 돈다 → H3_ENGINE=diffusers bash scripts/provision.sh 후 다시 실행")"
  red "== 문제가 있어 서버를 띄우지 않는다. 로그: $UP_LOG"; exit 1
fi
green "✓ torch GPU 사용 가능"
VISION_ARGS=(); [[ $CHECK == 1 || $H3_ENGINE == diffusers ]] || VISION_ARGS=(--repair)   # diffusers venv 는 고정 버전이라 고치지 않고 확인만
if ! "$VENV/bin/python" "$ROOT/scripts/check_torchvision.py" "${VISION_ARGS[@]}"; then
  red "== torchvision 점검 실패. 로그: $UP_LOG"; exit 1
fi
green "✓ torchvision CPU·CUDA NMS 사용 가능"
green "== 점검 통과"; [[ $CHECK == 1 ]] && exit 0

# 3) 이 화면에서 포그라운드로 실행. 각 서버의 출력(원본 로그·오류)이 그대로 이 화면에 나온다.
PIDS=(); NAMES=()
cleanup() {   # 서버·웹 UI 를 하위 프로세스까지 끄고 GPU 반환 확인
  trap - INT TERM HUP EXIT
  echo; yellow "== 끄는 중: ${NAMES[*]} (GPU 반환까지 확인)"
  h3_stop_tree "${PIDS[@]}"
  python3 "$ROOT/scripts/h3_leftovers.py" --kill | grep -v "남은 H3 서버 프로세스 없음"   # 묶음 밖으로 빠진 워커까지
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
# 서버가 살아 있는가: 실행 스크립트가 살아 있고, (시작 후 10초가 지났다면) 그룹 안에 서버 본체("sglang serve" 또는 h3video.dserver)가 있어야 한다.
# 본체가 OOM 등으로 죽어도 워커가 로그 파이프를 잡고 있으면 serve.sh 가 끝나지 않으므로 본체를 직접 본다.
server_alive() {  # name pid seconds-since-start
  kill -0 "$2" 2>/dev/null || return 1
  [[ $1 == web || $3 -le 10 ]] && return 0
  pgrep -g "$2" -f 'sglang serve|h3video.dserver' >/dev/null
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
echo "  영상:   다른 창에서  cd $ROOT && source scripts/cluster_env.sh && h3video gen \"...\" -s 8"
if [[ $WEB == 1 ]]; then
  echo "  PC 에서: ssh -N -L 8790:127.0.0.1:${PORT[web]} -L ${PORT[fl2va]}:127.0.0.1:${PORT[fl2va]} -L ${PORT[ref2va]}:127.0.0.1:${PORT[ref2va]} $(id -un)@$host"
  echo "           그다음 브라우저 http://127.0.0.1:8790 (허브 숏폼 제작의 서버 주소도 http://localhost:8790)"
fi
echo

# 서버 하나라도 끝나면 알리고 전부 끈다
while :; do
  for i in "${!PIDS[@]}"; do
    if ! server_alive "${NAMES[$i]}" "${PIDS[$i]}" 99; then red "✗ ${NAMES[$i]} 가 끝났다 (바로 위 로그가 원인). 남은 프로세스를 끄고 GPU 를 반환한다"; cleanup; exit 1; fi
  done
  sleep 3
done
