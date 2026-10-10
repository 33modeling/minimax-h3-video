#!/usr/bin/env bash
# 서버 응답 확인. 사용: bash scripts/health.sh [endpoint]
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"   # sh 로 실행해도 bash 로 다시 실행
EP="${1:-${H3_ENDPOINT:-http://127.0.0.1:30010}}"
for p in /health /v1/models /v1/videos; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$EP$p" || echo 000)
  echo "$EP$p -> $code"
done
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv 2>/dev/null || true
