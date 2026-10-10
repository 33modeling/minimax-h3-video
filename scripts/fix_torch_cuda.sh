#!/usr/bin/env bash
# 주의: H3 용 sglang(0.5.17+)은 CUDA 13 전용이라 이 스크립트로는 H3 서버 문제가 풀리지 않는다(드라이버 580 이상 노드 필요).
#       sglang 없이 torch 만 쓰는 venv 에서, 드라이버보다 새 CUDA 빌드가 깔렸을 때 같은 버전의 CUDA 12 빌드로 바꾸는 용도.
# 노드 드라이버보다 새 CUDA 로 빌드된 PyTorch 를 같은 버전의 CUDA 12 빌드로 바꾼다.
# ("The NVIDIA driver on your system is too old (found version 12020)" 오류: 드라이버는 CUDA 12.2 까지인데 torch 가 CUDA 13 용일 때)
#   bash scripts/fix_torch_cuda.sh          확인하고 필요하면 바꾼다 (provision.sh 가 끝에 자동으로 부른다)
#   bash scripts/fix_torch_cuda.sh --check  확인만
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
PY="$VENV/bin/python"; [[ -x "$PY" ]] || PY="$(command -v python3)"
gpu_ok() { "$PY" -c "import torch; torch.zeros(1).cuda(); print('torch', torch.__version__, 'CUDA', torch.version.cuda, '→ GPU OK:', torch.cuda.get_device_name(0))"; }
drv="$(nvidia-smi 2>/dev/null | grep -o 'CUDA Version: [0-9.]*' | awk '{print $3}')"
echo "[torch-cuda] 드라이버가 지원하는 CUDA: ${drv:-알 수 없음}"
if gpu_ok; then exit 0; fi
[[ "${1:-}" == --check ]] && { echo "[torch-cuda] GPU 를 못 쓴다. 고치려면: bash scripts/fix_torch_cuda.sh"; exit 1; }
tv="$("$PY" -c "import torch; print(torch.__version__.split('+')[0])" 2>/dev/null)"
tcu="$("$PY" -c "import torch; print(torch.version.cuda or '')" 2>/dev/null)"
echo "[torch-cuda] 지금 torch $tv (CUDA $tcu). 드라이버(CUDA $drv)에 맞는 CUDA 12 빌드로 다시 설치한다"
dmaj="${drv%%.*}"; dmin="${drv#*.}"; dmin="${dmin%%.*}"
for cu in cu129 cu128 cu126 cu124 cu121 cu118; do
  v="${cu#cu}"; cmaj="${v:0:2}"; [[ ${#v} == 3 && $v == 118 ]] && cmaj=11
  # 드라이버 주 버전보다 높은 CUDA 는 건너뛴다 (12.x 안에서는 드라이버 12.0 이상이면 하위 호환으로 동작)
  [[ -n "$dmaj" && "$cmaj" -gt "$dmaj" ]] && continue
  echo "[torch-cuda] 시도: torch==$tv  ($cu)"
  if "$PY" -m pip install --force-reinstall "torch==$tv" --index-url "https://download.pytorch.org/whl/$cu" ${PIP_EXTRA_INDEX_URL:+--extra-index-url "$PIP_EXTRA_INDEX_URL"}; then
    if gpu_ok; then echo "[torch-cuda] 해결: torch==$tv ($cu)"; exit 0; fi
  fi
done
echo "[torch-cuda] 실패: 같은 버전의 CUDA 12 빌드를 찾지 못했거나 그래도 GPU 를 못 쓴다."
echo "  → 다른 버전을 직접 지정: TORCH_VERSION=2.8.0 처럼 정한 뒤 $PY -m pip install torch==\$TORCH_VERSION --index-url https://download.pytorch.org/whl/cu128"
echo "  → sglang 이 요구하는 torch 버전과 맞는지: $PY -m pip check"
exit 1
