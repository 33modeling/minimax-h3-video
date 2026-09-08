#!/usr/bin/env bash
# 로컬 → 클러스터 user-volume 코드 동기화 (GitHub egress 없으므로 rsync). 저장물은 보내지 않는다.
# 사용: CLUSTER_SSH=user@host CLUSTER_CODE_DIR=/user-volume/<you>/minimax-h3-video bash scripts/sync_to_cluster.sh
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${CLUSTER_SSH:?CLUSTER_SSH=user@host 필요}"; : "${CLUSTER_CODE_DIR:?CLUSTER_CODE_DIR 필요}"
rsync -avz --delete --exclude-from="$ROOT/.gitignore" --exclude .git "$ROOT/" "$CLUSTER_SSH:$CLUSTER_CODE_DIR/"
echo "동기화 완료 → $CLUSTER_SSH:$CLUSTER_CODE_DIR"
