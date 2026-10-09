# shellcheck shell=bash
# 이 셸에서만 shortform-studio 환경을 켠다 (bash·zsh). 끄기: shorts-env-off (또는 deactivate)
#   source scripts/env.sh
# 하는 일 (차례로, 이 셸 안에서만 — 셸 rc 파일·전역 설정은 건드리지 않음):
#   1) .venv 활성화 + .tools/bin·.tools/node/bin 을 PATH 앞에 (있는 것만)
#   2) .env 로드 (있을 때만). 값이 빈 줄은 건너뛰고, 셸에 이미 있는 값은 덮어쓰지 않는다
#   3) H3_REPO 가 있으면 그 레포의 scripts/cluster_env.sh 를 서브셸에서 읽어 주소 변수만 가져온다
#      (H3_ENDPOINT·H3_REF_ENDPOINT·H3_INBOX_DIR·H3_OUTPUT_DIR — HOME·PATH·HF 설정은 가져오지 않음)
# 우선순위: 셸에 이미 있는 값 > .env > cluster_env.sh 기본값.

if [ -n "${BASH_SOURCE:-}" ]; then _shorts_f="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then eval '_shorts_f="${(%):-%x}"'
else _shorts_f="$PWD/scripts/env.sh"; fi
if [ -n "${_SHORTS_ENV_ON:-}" ] && command -v shorts-env-off >/dev/null 2>&1; then shorts-env-off; fi
SHORTS_ROOT="$(cd "$(dirname "$_shorts_f")/.." && pwd -P)"
_SHORTS_RESTORE=""

_shorts_set() {  # 이름 값 — 원래 값(또는 없었음)을 기억해 두고 export
  if eval "[ \"\${$1+x}\" = x ]"; then
    _shorts_old=""; eval "_shorts_old=\"\${$1}\""
    _SHORTS_RESTORE="${_SHORTS_RESTORE}export $1=$(printf '%q' "$_shorts_old");"
  else
    _SHORTS_RESTORE="${_SHORTS_RESTORE}unset $1;"
  fi
  export "$1=$2"
}
_shorts_default() {  # 비어 있을 때만 설정
  eval "[ -n \"\${$1:-}\" ]" || _shorts_set "$1" "$2"
}

# 1) .venv + .tools
_shorts_venv="${SHORTS_VENV:-$SHORTS_ROOT/.venv}"
_SHORTS_PREV_VENV=""
if [ -n "${VIRTUAL_ENV:-}" ] && [ "$VIRTUAL_ENV" != "$_shorts_venv" ] && command -v deactivate >/dev/null 2>&1; then
  # 끌 때(shorts-env-off) 이 venv 를 다시 켜서 원래 상태로 돌려 놓는다
  echo "[shorts-env] 켜져 있던 venv($VIRTUAL_ENV)를 잠시 끄고 켭니다 (shorts-env-off 때 다시 켬)"
  _SHORTS_PREV_VENV="$VIRTUAL_ENV"; deactivate
fi
_shorts_path=""
for _shorts_d in "$_shorts_venv/bin" "$SHORTS_ROOT/.tools/bin" "$SHORTS_ROOT/.tools/node/bin"; do
  [ -d "$_shorts_d" ] && _shorts_path="$_shorts_path$_shorts_d:"
done
_shorts_set PATH "$_shorts_path$PATH"
if [ -x "$_shorts_venv/bin/python" ]; then
  _shorts_set VIRTUAL_ENV "$_shorts_venv"
  if [ -n "${PYTHONHOME+x}" ]; then _shorts_set PYTHONHOME ""; unset PYTHONHOME; fi
else
  echo "[shorts-env] 주의: $_shorts_venv 가 없습니다 — 먼저 scripts/setup.sh" >&2
fi
_shorts_set npm_config_cache "$SHORTS_ROOT/.tools/npm-cache"
[ -f "$SHORTS_ROOT/.tools/fonts/NotoSansKR-Bold.otf" ] && _shorts_default SHORTS_FONT "$SHORTS_ROOT/.tools/fonts/NotoSansKR-Bold.otf"

# 2) .env
if [ -f "$SHORTS_ROOT/.env" ]; then
  while IFS= read -r _shorts_l || [ -n "$_shorts_l" ]; do
    _shorts_l="${_shorts_l%$'\r'}"
    case "$_shorts_l" in ''|'#'*) continue ;; esac
    _shorts_l="${_shorts_l#export }"
    _shorts_k="${_shorts_l%%=*}"; _shorts_v="${_shorts_l#*=}"
    case "$_shorts_k" in ''|*[!A-Za-z0-9_]*) continue ;; esac
    case "$_shorts_v" in \"*\") _shorts_v="${_shorts_v#\"}"; _shorts_v="${_shorts_v%\"}" ;;
                         \'*\') _shorts_v="${_shorts_v#\'}"; _shorts_v="${_shorts_v%\'}" ;; esac
    [ -n "$_shorts_v" ] && _shorts_default "$_shorts_k" "$_shorts_v"
  done < "$SHORTS_ROOT/.env"
fi

# 3) cluster_env.sh — 읽기만
if [ -n "${H3_REPO:-}" ]; then
  if [ -f "$H3_REPO/scripts/cluster_env.sh" ]; then
    if _shorts_vars="$(bash -c 'source "$1" >/dev/null 2>&1 || exit 3
        for v in H3_ENDPOINT H3_REF_ENDPOINT H3_INBOX_DIR H3_OUTPUT_DIR; do printf "%s=%s\n" "$v" "${!v:-}"; done' _ "$H3_REPO/scripts/cluster_env.sh")"; then
      while IFS= read -r _shorts_l; do
        [ -n "${_shorts_l#*=}" ] && _shorts_default "${_shorts_l%%=*}" "${_shorts_l#*=}"
      done <<EOF
$_shorts_vars
EOF
      [ -n "${H3_INBOX_DIR:-}" ] && _shorts_default SHORTS_INBOX "$H3_INBOX_DIR"
    else
      echo "[shorts-env] 주의: $H3_REPO/scripts/cluster_env.sh 를 읽지 못했습니다 (클러스터 밖이면 정상)" >&2
    fi
  else
    echo "[shorts-env] 주의: H3_REPO=$H3_REPO 에 scripts/cluster_env.sh 가 없습니다" >&2
  fi
fi

shorts-env-off() {
  eval "$_SHORTS_RESTORE"
  _shorts_prev="${_SHORTS_PREV_VENV:-}"
  unset _SHORTS_RESTORE _SHORTS_ENV_ON SHORTS_ROOT _shorts_old _SHORTS_PREV_VENV
  unset -f deactivate shorts-env-off _shorts_set _shorts_default 2>/dev/null
  # 켜기 전에 다른 venv 가 켜져 있었으면 다시 켠다(그 venv 의 PATH·VIRTUAL_ENV·deactivate 가 돌아옴)
  if [ -n "$_shorts_prev" ] && [ -f "$_shorts_prev/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$_shorts_prev/bin/activate"
    echo "[shorts-env] 원래 켜져 있던 venv($_shorts_prev)를 다시 켰습니다"
  fi
  unset _shorts_prev
  hash -r 2>/dev/null || true
  echo "[shorts-env] 껐습니다 (PATH·변수 원래대로)"
}
deactivate() { shorts-env-off; }
_SHORTS_ENV_ON=1
hash -r 2>/dev/null || true
echo "[shorts-env] 켜짐: $(command -v python 2>/dev/null || echo 'python 없음') · ffmpeg $(command -v ffmpeg 2>/dev/null || echo 없음)${H3_ENDPOINT:+ · H3 $H3_ENDPOINT} · 끄기: shorts-env-off"
unset _shorts_f _shorts_venv _shorts_path _shorts_d _shorts_l _shorts_k _shorts_v _shorts_vars
