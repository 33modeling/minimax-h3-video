#!/usr/bin/env bash
# Restore torchvision matching the existing project torch/CUDA, then test real NMS.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE=diffusers; ARGS=()
while [[ $# -gt 0 ]]; do case "$1" in
  --engine) ENGINE="${2:-}"; [[ "$ENGINE" == diffusers || "$ENGINE" == sglang ]] || { echo "--engine diffusers 또는 sglang 필요" >&2; exit 2; }; shift 2 ;;
  *) ARGS+=("$1"); shift ;;
esac; done
export H3_ENGINE_OVERRIDE="$ENGINE"
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
[[ -x "$VENV/bin/python" ]] || { echo "Project venv missing: $VENV" >&2; exit 1; }
exec "$VENV/bin/python" "$ROOT/scripts/check_torchvision.py" --repair "${ARGS[@]}"
