#!/usr/bin/env bash
# 안 될 때 이것 하나만 실행해서 출력을 통째로 붙여 준다: 코드 버전·서버 로그 끝·오류·GPU·마지막 작업
#   bash scripts/diagnose.sh
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/cluster_env.sh" >/dev/null 2>&1
sec() { echo; echo "===== $* ====="; }
sec "코드"; (cd "$ROOT" && git -c safe.directory='*' log -1 --format='%h %ad %s' --date=format:'%m-%d %H:%M' 2>/dev/null || echo "git 없음 (rsync 로 올린 코드)"); ls -l --time-style=+%m-%d_%H:%M "$ROOT/src/h3video/dserver.py" | awk '{print "dserver.py 수정 시각:", $6}'
sec "엔진·경로"; echo "H3_ENGINE=$H3_ENGINE VENV=$VENV"; echo "DIFFUSERS_DIR=${H3_DIFFUSERS_DIR:-} GUIDE_DIR=${H3_GUIDE_DIR:-}"
sec "서버 상태"; bash "$ROOT/scripts/status.sh" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
sec "GPU"; nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>&1; python3 "$ROOT/scripts/h3_leftovers.py" --gpu-users 2>&1
L=$(ls -t "$H3_LOG_DIR"/up-*.log 2>/dev/null | head -1)
sec "up 로그: ${L:-없음} — 오류·단계 줄"
[[ -n "$L" ]] && grep -n -E "Error|error|Traceback|실패|끝났다|OOM|out of memory|경고|준비됨|장 방식|워커 연결|생성:|걸린 시간|다듬" "$L" | sed 's/\x1b\[[0-9;]*m//g' | tail -40
sec "up 로그 마지막 60줄"; [[ -n "$L" ]] && tail -n 60 "$L" | sed 's/\x1b\[[0-9;]*m//g'
sec "마지막 작업"
J=$(ls -td "$H3_OUTPUT_DIR"/*/ 2>/dev/null | head -1)
if [[ -n "$J" ]]; then python3 - "$J/job.json" <<'PY' 2>&1
import json, sys
j = json.load(open(sys.argv[1]))
print("작업", j.get("id"), "상태", j.get("status"), "| 오류:", j.get("error"))
for s in j.get("scenes", []):
    print(f"  장면{s['index'] + 1} {s.get('task')} {s.get('duration')}초 상태 {s.get('status')} 단계 {s.get('stage')} video_id {s.get('video_id')} 오류 {s.get('error')}")
PY
else echo "없음"; fi
for f in $(ls -t "$STORAGE_ROOT"/dserver/*/*.json 2>/dev/null | head -2); do echo "-- 서버 작업 $f"; python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('status'), d.get('error'))" "$f"; done
