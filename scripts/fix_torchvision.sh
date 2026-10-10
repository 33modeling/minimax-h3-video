#!/usr/bin/env bash
# Restore torchvision matching the existing project torch/CUDA, then test real NMS.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/cluster_env.sh" >/dev/null || exit 1
[[ -x "$VENV/bin/python" ]] || { echo "Project venv missing: $VENV" >&2; exit 1; }
exec "$VENV/bin/python" "$ROOT/scripts/check_torchvision.py" --repair "$@"
