#!/usr/bin/env bash
# shortform-studio 환경 설정 (멱등). 다시 실행해도 이미 된 것은 건너뛴다.
#
# 격리 원칙: 설치 위치는 레포 안의 .venv/ 와 .tools/ 뿐이다.
#   시스템 파이썬·전역 pip/npm·~/.local·apt/brew·sudo·셸 rc 파일·다른 venv(minimax-h3-video 포함)는 건드리지 않는다.
#   이미 조건을 만족하는 도구는 그대로 쓰고, 없을 때만 .tools/ 에 받는다(--yes 없으면 받기 전에 묻는다).
#
# 사용: scripts/setup.sh [--mode cli|web|cluster|all] [옵션]
#   --mode cli       .venv + shorts(pip install -e .) + ffmpeg/ffprobe/drawtext + 한글 글꼴 (기본)
#   --mode web       node(package.json engines) + npm ci  (--build 면 vite build 까지)
#   --mode cluster   cli + minimax-h3-video 위치 확인 (--h3-repo 또는 H3_REPO, 기본 ../minimax-h3-video)
#   --mode all       cli + web + cluster
#   --python 경로    .venv 를 만들 파이썬          --venv 경로       .venv 대신 쓸 venv 위치
#   --index-url URL  사내 PyPI 미러 (PIP_INDEX_URL 도 존중)
#   --offline        설치·다운로드 없이 확인만      --yes, -y         묻지 않고 받기
#   --isolated       시스템 도구가 있어도 .tools 의 로컬 사본을 씀 (파이썬·ffmpeg·글꼴·node)
#   --with-h3video   (cluster) h3video 소스를 .venv 에 pip install -e --no-deps (sglang 등은 안 받음)
#   --build          (web) npm run build 로 빌드 확인
#   --uninstall      .venv/ 와 .tools/ 만 지움 (경로를 보여 주고 확인)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TOOLS="$ROOT/.tools"
DL="$TOOLS/dl.$$"
MODE=cli PY_ARG="" VENV="$ROOT/.venv" INDEX_URL="${PIP_INDEX_URL:-}"
OFFLINE=0 YES=0 ISOLATED=0 BUILD=0 WITH_H3=0 UNINSTALL=0
H3_REPO="${H3_REPO:-$ROOT/../minimax-h3-video}"

# 받을 것 (출처는 ffmpeg.org·nodejs.org·astral·Google Noto 공식 배포처)
UV_BASE=https://github.com/astral-sh/uv/releases/latest/download
PY_VERSION=3.12
# ffmpeg: ffmpeg.org/download.html 이 안내하는 정적 빌드. johnvansickle 빌드는 harfbuzz 가 없어 drawtext 가 빠져 있어 쓰지 않음
FF_BTBN=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest  # Linux x86_64·arm64 (sha256)
FF_EVERMEET=https://evermeet.cx/ffmpeg                                  # macOS (x86_64, 크기 확인)
FF_MAC=https://ffmpeg.martin-riedl.de/redirect/latest/macos            # macOS 대체: arm64 네이티브 (sha256)
FONT_URL=https://github.com/notofonts/noto-cjk/raw/Sans2.004/Sans/SubsetOTF/KR/NotoSansKR-Bold.otf
FONT_SHA=5a6ceb287ed2fc6cfc6213144ebea68cbd94b20fc9eb873d8486493bf02d9bda
FONT_LIC_URL=https://github.com/notofonts/noto-cjk/raw/Sans2.004/LICENSE
FONT_LIC_SHA=6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2
NODE_MAJOR=22

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; }
while (($#)); do
  if [[ "$1" == --*=* ]]; then set -- "${1%%=*}" "${1#*=}" "${@:2}"; fi
  case "$1" in
    --mode) MODE="${2:?--mode 값}"; shift 2 ;;
    --python) PY_ARG="${2:?--python 경로}"; shift 2 ;;
    --venv) VENV="$(mkdir -p "$(dirname "${2:?--venv 경로}")" && cd "$(dirname "$2")" && pwd -P)/$(basename "$2")"; shift 2 ;;
    --index-url) INDEX_URL="${2:?--index-url URL}"; shift 2 ;;
    --h3-repo) H3_REPO="${2:?--h3-repo 경로}"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --isolated) ISOLATED=1; shift ;;
    --with-h3video) WITH_H3=1; shift ;;
    --build) BUILD=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1 (--help 참고)" >&2; exit 2 ;;
  esac
done
case "$MODE" in cli|web|cluster|all) ;; *) echo "--mode 는 cli|web|cluster|all" >&2; exit 2 ;; esac

log() { printf '[setup] %s\n' "$*"; }
warn() { printf '[setup] 주의: %s\n' "$*" >&2; }
ROWS=() FAILED=0
row() { ROWS+=("$1|$2|$3"); [[ "$1" != "✗" ]] || FAILED=1; }   # 상태|항목|내용

ask() {  # 질문 — --yes 면 바로 예, 터미널이 아니면 아니오
  ((YES)) && return 0
  if [[ ! -t 0 ]]; then warn "확인이 필요합니다(터미널 아님): $1 → --yes 로 다시 실행"; return 1; fi
  local r; read -r -p "[setup] $1 [y/N] " r; [[ "$r" == [yY]* ]]
}
want() {  # 받기 전 확인: 무엇을, 어디서, 어디로
  ((OFFLINE)) && { warn "--offline: $1 을(를) 받지 않음"; return 1; }
  printf '[setup] 받을 것: %s\n          출처: %s\n          위치: %s\n' "$1" "$2" "$3"
  ask "받을까요?"
}

# 레포 안에만 쓰도록 캐시·설정 경로를 가둔다 (이 스크립트 프로세스 안에서만)
export PIP_CACHE_DIR="$TOOLS/cache/pip" PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1
UV_ENV=(UV_NO_CONFIG=1 UV_CACHE_DIR="$TOOLS/cache/uv" UV_PYTHON_INSTALL_DIR="$TOOLS/python"
        UV_PYTHON_BIN_DIR="$TOOLS/python/bin" UV_TOOL_DIR="$TOOLS/uv-tools" UV_TOOL_BIN_DIR="$TOOLS/uv-tools/bin"
        UV_NO_MODIFY_PATH=1 UV_PYTHON_INSTALL_REGISTRY=0)
uv() { env "${UV_ENV[@]}" ${INDEX_URL:+UV_DEFAULT_INDEX="$INDEX_URL"} "$TOOLS/bin/uv" "$@"; }
NPM_ENV=(npm_config_cache="$TOOLS/npm-cache" npm_config_update_notifier=false npm_config_fund=false npm_config_audit=false)

OS="$(uname -s)" ARCH="$(uname -m)"
case "$ARCH" in x86_64|amd64) ARCH=x86_64 ;; aarch64|arm64) ARCH=arm64 ;; esac
trap 'rm -rf "$DL"' EXIT

fetch() {  # URL 파일
  mkdir -p "$(dirname "$2")"
  local bar=-sS; [[ -t 2 ]] && bar=--progress-bar
  if command -v curl >/dev/null; then curl -fL --retry 2 --connect-timeout 20 "$bar" -o "$2" "$1"
  elif command -v wget >/dev/null; then wget -q --show-progress -O "$2" "$1"
  else warn "curl 이나 wget 이 필요합니다"; return 1; fi
}
# shellcheck disable=SC2317  # verify 가 "${2}_of" 로 부름
sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
# shellcheck disable=SC2317
md5_of() { if command -v md5sum >/dev/null; then md5sum "$1" | cut -d' ' -f1; else md5 -q "$1"; fi; }
verify() {  # 파일 sha256|md5 기대값
  local got; got="$("${2}_of" "$1")"
  if [[ -z "$3" || "$got" != "$3" ]]; then warn "체크섬 불일치: $(basename "$1") ($2 기대 ${3:-없음}, 실제 $got)"; rm -f "$1"; return 1; fi
  log "체크섬 확인($2): $(basename "$1")"
}
under_tools() { [[ "$1" == "$TOOLS"/* ]]; }
src_of() { if under_tools "$1"; then echo .tools; else echo 시스템; fi; }

# ── 지우기 ─────────────────────────────────────────────
if ((UNINSTALL)); then
  targets=()
  for d in "$ROOT/.venv" "$TOOLS"; do [[ -e "$d" ]] && targets+=("$d"); done
  ((${#targets[@]})) || { log "지울 것이 없습니다 (.venv/ .tools/ 없음)"; exit 0; }
  log "지울 경로 (이 레포 안의 것만):"
  for d in "${targets[@]}"; do printf '          %s  (%s)\n' "$d" "$(du -sh "$d" 2>/dev/null | cut -f1)"; done
  ask "위 경로를 지울까요?" || { log "취소했습니다"; exit 1; }
  rm -rf "${targets[@]}"; log "지웠습니다. .env 와 node_modules 는 그대로 둡니다."; exit 0
fi

# ── 파이썬 ────────────────────────────────────────────
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }
py_ver() { "$1" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo "?"; }
local_python() {
  local p
  for p in "$TOOLS"/python/cpython-3.*/bin/python3; do [[ -x "$p" ]] && py_ok "$p" && { echo "$p"; return 0; }; done
  return 1
}
ensure_uv() {
  [[ -x "$TOOLS/bin/uv" ]] && return 0
  local t
  case "$OS-$ARCH" in
    Linux-x86_64) t=x86_64-unknown-linux-gnu ;; Linux-arm64) t=aarch64-unknown-linux-gnu ;;
    Darwin-x86_64) t=x86_64-apple-darwin ;; Darwin-arm64) t=aarch64-apple-darwin ;;
    *) warn "uv 를 받을 수 없는 플랫폼: $OS-$ARCH"; return 1 ;;
  esac
  want "uv (독립 파이썬 설치 도구, 약 20MB)" "$UV_BASE/uv-$t.tar.gz (+ .sha256)" ".tools/bin/uv" || return 1
  fetch "$UV_BASE/uv-$t.tar.gz" "$DL/uv.tgz" && fetch "$UV_BASE/uv-$t.tar.gz.sha256" "$DL/uv.sha256" || return 1
  verify "$DL/uv.tgz" sha256 "$(cut -d' ' -f1 "$DL/uv.sha256")" || return 1
  tar -xzf "$DL/uv.tgz" -C "$DL" && mkdir -p "$TOOLS/bin" && cp "$DL/uv-$t/uv" "$TOOLS/bin/uv" && chmod 755 "$TOOLS/bin/uv"
}
pick_python() {  # PY, PY_SRC 를 정한다
  local c p
  if [[ -n "$PY_ARG" ]]; then
    py_ok "$PY_ARG" || { warn "--python $PY_ARG: 3.10 이상이 아닙니다 ($(py_ver "$PY_ARG"))"; return 1; }
    PY="$PY_ARG" PY_SRC="--python"; return 0
  fi
  if ((!ISOLATED)); then
    for c in python3 python3.13 python3.12 python3.11 python3.10 python; do
      p="$(command -v "$c" 2>/dev/null)" || continue
      py_ok "$p" && { PY="$p" PY_SRC="시스템"; return 0; }
    done
    warn "PATH 에 파이썬 3.10 이상이 없습니다 → .tools/python 에 독립 파이썬을 받습니다"
  fi
  if p="$(local_python)"; then PY="$p" PY_SRC=".tools"; return 0; fi
  ensure_uv || return 1
  want "독립 파이썬 $PY_VERSION (python-build-standalone, 약 30MB)" "uv python install (GitHub astral-sh/python-build-standalone)" ".tools/python" || return 1
  uv python install --no-bin "$PY_VERSION" || return 1
  p="$(local_python)" || { warn "설치한 파이썬을 찾지 못했습니다: $TOOLS/python"; return 1; }
  PY="$p" PY_SRC=".tools"
}
venv_home() { sed -n 's/^home *= *//p' "$VENV/pyvenv.cfg" 2>/dev/null; }
ensure_venv() {
  if [[ -x "$VENV/bin/python" ]] && py_ok "$VENV/bin/python"; then
    if ((ISOLATED)) && [[ -z "$PY_ARG" ]] && ! under_tools "$(venv_home)/"; then
      [[ "$VENV" == "$ROOT/.venv" ]] || { warn "--isolated: $VENV 는 시스템 파이썬 기반 — 직접 지우거나 다른 --venv 를 주세요"; return 1; }
      log "--isolated: 시스템 파이썬으로 만든 .venv 를 .tools 파이썬으로 다시 만듭니다"
    else
      log "venv 재사용: $VENV ($(py_ver "$VENV/bin/python"))"; return 0
    fi
  elif [[ -e "$VENV" ]]; then
    [[ "$VENV" == "$ROOT/.venv" ]] || { warn "$VENV 가 있지만 쓸 수 없습니다(3.10 미만이거나 깨짐). 다른 --venv 를 주세요"; return 1; }
    log ".venv 가 깨졌거나 3.10 미만 — 다시 만듭니다"
  fi
  ((OFFLINE)) && { warn "--offline: venv 를 만들지 않음"; return 1; }
  pick_python || return 1
  [[ "$VENV" != "$ROOT/.venv" ]] || rm -rf "$VENV"
  log "venv 생성: $VENV ← $PY ($(py_ver "$PY"), $PY_SRC)"
  if ! "$PY" -m venv "$VENV" 2>"$TOOLS/venv.err"; then   # 데비안 계열: python3-venv(ensurepip) 없으면 실패
    warn "python -m venv 실패($(tail -1 "$TOOLS/venv.err")) → uv 로 만듭니다"
    rm -rf "$VENV"; ensure_uv || return 1
    uv venv --seed --python "$PY" "$VENV" || return 1
  fi
  rm -f "$TOOLS/venv.err"
}
pip_in() { "$VENV/bin/python" -m pip install ${INDEX_URL:+--index-url "$INDEX_URL"} "$@"; }
installed_from() {  # 모듈 이름 → 그 패키지 디렉터리 (현재 폴더를 sys.path 에서 뺀 상태로)
  (cd / && "$VENV/bin/python" -I -c 'import importlib, os, sys; m = importlib.import_module(sys.argv[1]); print(os.path.dirname(os.path.realpath(m.__file__)))' "$1" 2>/dev/null)
}
do_cli() {
  mkdir -p "$TOOLS"
  # 1) 파이썬 + .venv + shorts
  if ensure_venv; then
    local vpy="$VENV/bin/python" home; home="$(venv_home)"
    row ✓ python "$(py_ver "$vpy") ($(src_of "$home/"): $home)"
    row ✓ venv "$VENV"
    if [[ -x "$VENV/bin/shorts" && "$(installed_from shorts)" == "$ROOT/shorts" ]]; then
      log "shorts 이미 설치됨 (pip install -e $ROOT)"; row ✓ shorts "$VENV/bin/shorts (편집 가능 설치)"
    elif ((OFFLINE)); then row ✗ shorts "설치 안 됨 (--offline)"
    elif pip_in -e "$ROOT"; then row ✓ shorts "$VENV/bin/shorts (편집 가능 설치)"
    else row ✗ shorts "pip install -e . 실패 — 미러는 --index-url 또는 PIP_INDEX_URL"
    fi
  else
    row ✗ python "3.10 이상 파이썬·venv 준비 실패 (--python 경로, --isolated, 네트워크 확인)"
  fi
  ensure_ffmpeg
  ensure_font
}

# ── ffmpeg ────────────────────────────────────────────
has_drawtext() { [[ "$("$1" -hide_banner -filters 2>/dev/null)" == *" drawtext "* ]]; }  # grep -q 는 pipefail 에서 SIGPIPE 로 거짓
ff_ver() { "$1" -version 2>/dev/null | sed -n '1s/^ffmpeg version \([^ ]*\).*/\1/p'; }
dl_ffmpeg_linux() {  # BtbN 정적 빌드(gpl: libx264·freetype·harfbuzz → drawtext), 릴리스 분기 중 최신, sha256
  local x f sum
  [[ "$ARCH" == x86_64 ]] && x=linux64 || x=linuxarm64
  fetch "$FF_BTBN/checksums.sha256" "$DL/ff.sha" || return 1
  f="$(grep -oE "ffmpeg-n[0-9.]+-latest-$x-gpl-[0-9.]+\.tar\.xz" "$DL/ff.sha" | sort -V | tail -1)"
  [[ -n "$f" ]] || f="ffmpeg-master-latest-$x-gpl.tar.xz"
  sum="$(grep " $f\$" "$DL/ff.sha" | cut -d' ' -f1)"
  log "ffmpeg: $f"
  fetch "$FF_BTBN/$f" "$DL/ff.tar.xz" && verify "$DL/ff.tar.xz" sha256 "$sum" || return 1
  mkdir -p "$DL/ff" && tar -xJf "$DL/ff.tar.xz" -C "$DL/ff" || return 1
  for x in ffmpeg ffprobe; do
    f="$(find "$DL/ff" -type f -path "*/bin/$x" -print -quit)"; [[ -n "$f" ]] || return 1
    cp "$f" "$TOOLS/bin/$x" && chmod 755 "$TOOLS/bin/$x" || return 1
  done
}
dl_ffmpeg_mac() {  # evermeet.cx(ffmpeg.org 안내, x86_64 — arm64 는 Rosetta) → 안 돌면 martin-riedl(arm64·sha256)
  local x info url size real a
  for x in ffmpeg ffprobe; do
    info="$(curl -fsSL "$FF_EVERMEET/info/$x/release")" || return 1
    url="$(sed -n 's/.*"zip":{"url":"\([^"]*\)","size":\([0-9]*\).*/\1/p' <<<"$info")"
    size="$(sed -n 's/.*"zip":{"url":"[^"]*","size":\([0-9]*\).*/\1/p' <<<"$info")"
    [[ -n "$url" ]] && fetch "$url" "$DL/$x.zip" || return 1
    # evermeet 은 체크섬 없이 GPG 서명만 준다 → 크기로만 확인(HTTPS)
    [[ "$(wc -c <"$DL/$x.zip" | tr -d ' ')" == "$size" ]] || { warn "크기 불일치: $x.zip"; return 1; }
    log "크기 확인(서명 미검증): $x.zip"
    rm -rf "${DL:?}/$x" && unzip -o -q "$DL/$x.zip" -d "$DL/$x" && cp "$DL/$x/$x" "$TOOLS/bin/$x" && chmod 755 "$TOOLS/bin/$x" || return 1
  done
  has_drawtext "$TOOLS/bin/ffmpeg" && return 0
  warn "evermeet 빌드가 이 Mac 에서 돌지 않음(arm64·Rosetta 없음 등) → martin-riedl arm64 빌드(sha256)"
  [[ "$ARCH" == x86_64 ]] && a=amd64 || a=arm64
  for x in ffmpeg ffprobe; do
    real="$(curl -fsSL --retry 2 -o "$DL/$x.zip" -w '%{url_effective}' "$FF_MAC/$a/release/$x.zip")" || return 1
    fetch "$real.sha256" "$DL/$x.sha" && verify "$DL/$x.zip" sha256 "$(cut -d' ' -f1 "$DL/$x.sha")" || return 1
    rm -rf "${DL:?}/$x" && unzip -o -q "$DL/$x.zip" -d "$DL/$x" && cp "$DL/$x/$x" "$TOOLS/bin/$x" && chmod 755 "$TOOLS/bin/$x" || return 1
  done
}
ensure_ffmpeg() {
  local ff fp why=""
  if [[ -x "$TOOLS/bin/ffmpeg" && -x "$TOOLS/bin/ffprobe" ]] && has_drawtext "$TOOLS/bin/ffmpeg"; then
    log "ffmpeg: .tools/bin 의 사본 사용"
  else
    if ((!ISOLATED)); then
      ff="$(command -v ffmpeg || true)" fp="$(command -v ffprobe || true)"
      if [[ -n "$ff" && -n "$fp" ]] && has_drawtext "$ff"; then
        row ✓ ffmpeg "$(ff_ver "$ff") (시스템: $ff, drawtext 있음)"; row ✓ ffprobe "시스템: $fp"; return
      fi
      if [[ -z "$ff" || -z "$fp" ]]; then why="ffmpeg/ffprobe 없음"; else why="$ff 에 drawtext 필터 없음"; fi
      warn "$why → .tools/bin 에 정적 빌드를 받습니다"
    fi
    local from
    case "$OS" in
      Linux) from="$FF_BTBN (ffmpeg.org 안내 BtbN 정적 빌드, sha256)" ;;
      Darwin) from="$FF_EVERMEET (ffmpeg.org 안내, 크기 확인) / 안 돌면 $FF_MAC (sha256)" ;;
      *) from="" ;;
    esac
    if [[ -z "$from" ]]; then row ✗ ffmpeg "${why:-없음} — 이 OS 는 자동 설치 미지원, https://ffmpeg.org/download.html"; return; fi
    mkdir -p "$TOOLS/bin"
    if ! want "ffmpeg·ffprobe 정적 빌드 (drawtext 포함, 받기 약 30~150MB)" "$from" ".tools/bin/ffmpeg, .tools/bin/ffprobe" \
       || ! { if [[ "$OS" == Darwin ]]; then dl_ffmpeg_mac; else dl_ffmpeg_linux; fi; }; then
      row ✗ ffmpeg "${why:-.tools 사본 없음} — 받지 않음/실패 (apt: sudo apt install ffmpeg, brew: brew install ffmpeg 도 가능)"; return
    fi
    has_drawtext "$TOOLS/bin/ffmpeg" || { row ✗ ffmpeg "받은 .tools/bin/ffmpeg 가 돌지 않거나 drawtext 가 없음"; return; }
  fi
  row ✓ ffmpeg "$(ff_ver "$TOOLS/bin/ffmpeg") (.tools/bin, drawtext 있음)"; row ✓ ffprobe ".tools/bin/ffprobe"
}

# ── 한글 글꼴 ─────────────────────────────────────────
font_found() {  # shorts 가 실제로 쓸 글꼴 (render.find_font 와 같은 규칙)
  local py="$VENV/bin/python"; [[ -x "$py" ]] || py="$(command -v python3 || true)"; [[ -n "$py" ]] || return 1
  (cd "$ROOT" && "$py" -c 'from shorts.render import find_font; print(find_font())' 2>/dev/null)
}
ensure_font() {
  local f="$TOOLS/fonts/NotoSansKR-Bold.otf" found
  if [[ -f "$f" ]]; then row ✓ font "$f (.tools)"; return; fi
  if ((!ISOLATED)) && found="$(font_found)" && [[ -n "$found" ]]; then row ✓ font "$found (시스템)"; return; fi
  ((ISOLATED)) || warn "한글 글꼴을 못 찾았습니다 (fc-list :lang=ko 결과 $(fc-list :lang=ko file 2>/dev/null | wc -l | tr -d ' ')개)"
  if want "Noto Sans KR Bold (SIL OFL 1.1, 약 5MB)" "$FONT_URL (sha256 고정)" ".tools/fonts/NotoSansKR-Bold.otf" \
     && fetch "$FONT_URL" "$DL/font.otf" && verify "$DL/font.otf" sha256 "$FONT_SHA" \
     && fetch "$FONT_LIC_URL" "$DL/OFL.txt" && verify "$DL/OFL.txt" sha256 "$FONT_LIC_SHA"; then
    mkdir -p "$TOOLS/fonts" && mv "$DL/OFL.txt" "$TOOLS/fonts/LICENSE-OFL.txt" && mv "$DL/font.otf" "$f"
    row ✓ font "$f (.tools, env.sh 가 SHORTS_FONT 로 잡음)"
  else
    row ✗ font "없음 — 받지 않음/실패. 직접 설치: sudo apt install fonts-noto-cjk / brew install --cask font-noto-sans-cjk-kr, 또는 SHORTS_FONT=/경로"
  fi
}

# ── 웹 (node + npm ci) ────────────────────────────────
NODE_RANGE="$(sed -n 's/.*"node": *"\([^"]*\)".*/\1/p' "$ROOT/package.json")"; NODE_RANGE="${NODE_RANGE%%$'\n'*}"
ver_num() { local a; IFS=. read -r -a a <<<"${1//[^0-9.]/}"; printf '%d%04d%04d' "${a[0]:-0}" "${a[1]:-0}" "${a[2]:-0}"; }
node_ok() {  # 버전 범위 — package.json engines 의 '^20.19.0 || >=22.12.0' 같은 ^ 와 >= 만
  local v="${1#v}" cl IFS='|'
  [[ -n "$NODE_RANGE" ]] || return 0
  for cl in $NODE_RANGE; do
    cl="${cl// /}"
    case "$cl" in
      ^*) cl="${cl#^}"; [[ "${v%%.*}" == "${cl%%.*}" ]] && (( $(ver_num "$v") >= $(ver_num "$cl") )) && return 0 ;;
      '>='*) cl="${cl#>=}"; (( $(ver_num "$v") >= $(ver_num "$cl") )) && return 0 ;;
    esac
  done
  return 1
}
dl_node() {
  local plat ext f sum base="https://nodejs.org/dist/latest-v$NODE_MAJOR.x"
  case "$OS-$ARCH" in
    Linux-x86_64) plat=linux-x64 ext=tar.xz ;; Linux-arm64) plat=linux-arm64 ext=tar.xz ;;
    Darwin-x86_64) plat=darwin-x64 ext=tar.gz ;; Darwin-arm64) plat=darwin-arm64 ext=tar.gz ;;
    *) warn "node 를 받을 수 없는 플랫폼: $OS-$ARCH"; return 1 ;;
  esac
  ((OFFLINE)) && { warn "--offline: node 를 받지 않음"; return 1; }
  fetch "$base/SHASUMS256.txt" "$DL/SHASUMS256.txt" || return 1
  f="$(grep -m1 -o "node-v[0-9.]*-$plat\.$ext" "$DL/SHASUMS256.txt")"; [[ -n "$f" ]] || return 1
  sum="$(grep " $f\$" "$DL/SHASUMS256.txt" | cut -d' ' -f1)"
  want "Node.js ${f%-"$plat".*} (nodejs.org 공식, 약 30MB)" "$base/$f (SHASUMS256 확인)" ".tools/node" || return 1
  fetch "$base/$f" "$DL/$f" && verify "$DL/$f" sha256 "$sum" || return 1
  mkdir -p "$DL/node" && tar -xf "$DL/$f" -C "$DL/node" --strip-components=1 || return 1
  rm -rf "$TOOLS/node" && mv "$DL/node" "$TOOLS/node"
}
do_web() {
  local node="" nv
  mkdir -p "$TOOLS"
  if [[ -x "$TOOLS/node/bin/node" ]] && node_ok "$("$TOOLS/node/bin/node" --version)"; then node="$TOOLS/node/bin/node"
  elif ((!ISOLATED)) && command -v node >/dev/null && command -v npm >/dev/null && node_ok "$(node --version)"; then node="$(command -v node)"
  else
    if ((!ISOLATED)); then
      if command -v node >/dev/null; then warn "node $(node --version) 는 범위($NODE_RANGE) 밖 → .tools/node 에 받습니다"
      else warn "node 없음 → .tools/node 에 받습니다"; fi
    fi
    dl_node && node="$TOOLS/node/bin/node"
  fi
  if [[ -z "$node" ]]; then row ✗ node "필요: $NODE_RANGE — 받지 않음/실패"; return; fi
  nv="$("$node" --version)"; row ✓ node "$nv ($(src_of "$node"): $node)"
  local bin; bin="$(dirname "$node")"
  npm_() { env "${NPM_ENV[@]}" PATH="$bin:$PATH" npm "$@"; }
  local nm="$ROOT/node_modules/.package-lock.json"
  if [[ -f "$nm" && "$nm" -nt "$ROOT/package-lock.json" && "$nm" -nt "$ROOT/package.json" ]]; then
    log "node_modules 최신 — npm ci 건너뜀"; row ✓ npm "node_modules 최신 (npm $(npm_ --version))"
  elif ((OFFLINE)); then row ✗ npm "node_modules 없음/오래됨 (--offline)"
  elif (cd "$ROOT" && npm_ ci); then row ✓ npm "npm ci 완료 (캐시 .tools/npm-cache)"
  else row ✗ npm "npm ci 실패 — 사내 미러면 .npmrc 의 registry 확인"
  fi
  if ((BUILD)); then
    if (cd "$ROOT" && npm_ run build >/dev/null); then row ✓ build "vite build → dist/"; else row ✗ build "npm run build 실패"; fi
  fi
}

# ── 클러스터 (minimax-h3-video) ──────────────────────
do_cluster() {
  if [[ ! -d "$H3_REPO" ]]; then row ✗ h3-repo "없음: $H3_REPO (--h3-repo 경로 또는 H3_REPO)"; return; fi
  H3_REPO="$(cd "$H3_REPO" && pwd -P)"
  if [[ -f "$H3_REPO/scripts/cluster_env.sh" ]]; then row ✓ h3-repo "$H3_REPO (cluster_env.sh 있음, 읽기만 함)"
  else row ✗ h3-repo "$H3_REPO 에 scripts/cluster_env.sh 가 없음"; fi
  if ((!WITH_H3)); then row ✓ h3video "내장 호환 클라이언트 사용 (기본, 설치 없음)"; return; fi
  [[ -x "$VENV/bin/python" ]] || { row ✗ h3video ".venv 가 없어 넣지 못함"; return; }
  if [[ "$(installed_from h3video)" == "$H3_REPO/src/h3video" ]]; then row ✓ h3video "이미 .venv 에 있음 ($H3_REPO/src)"
  elif ((OFFLINE)); then row ✗ h3video ".venv 에 없음 (--offline)"
  elif pip_in --no-deps -e "$H3_REPO"; then row ✓ h3video ".venv 에 --no-deps 편집 설치 ($H3_REPO/src, sglang 미설치)"
  else row ✗ h3video "pip install --no-deps -e $H3_REPO 실패"; fi
}

ensure_dotenv() {  # .env 가 없을 때만 .env.example 을 복사 (있으면 절대 건드리지 않음)
  [[ -f "$ROOT/.env" || ! -f "$ROOT/.env.example" ]] && return 0
  if [[ "$MODE" == cluster || "$MODE" == all ]] && [[ -d "$H3_REPO" ]]; then
    sed "s|^H3_REPO=.*|H3_REPO=$H3_REPO|" "$ROOT/.env.example" >"$ROOT/.env"
  else cp "$ROOT/.env.example" "$ROOT/.env"; fi
  chmod 600 "$ROOT/.env"; log ".env 를 만들었습니다 (.env.example 복사, git 에 안 올라감) — 키는 여기에"
}

FLAGS=""; ((ISOLATED)) && FLAGS+=", isolated"; ((OFFLINE)) && FLAGS+=", offline"
log "모드: $MODE  레포: $ROOT  ($OS-$ARCH$FLAGS)"
case "$MODE" in
  cli) do_cli ;;
  web) do_web ;;
  cluster) do_cli; do_cluster ;;
  all) do_cli; do_web; do_cluster ;;
esac
((OFFLINE)) || ensure_dotenv

echo
echo "== 요약 ($MODE) =="
printf ' %s  %-9s %s\n' "상태" "항목" "내용"
for r in "${ROWS[@]}"; do IFS='|' read -r s k v <<<"$r"; printf '  %s   %-9s %s\n' "$s" "$k" "$v"; done
echo
echo "== 다음 명령 =="
[[ "$VENV" == "$ROOT/.venv" ]] || echo "  export SHORTS_VENV=$VENV          # env.sh 가 이 venv 를 켜도록"
echo "  source scripts/env.sh               # 이 셸에서만 .venv·.tools 사용 (끄기: shorts-env-off)"
echo "  shorts doctor                       # 전체 점검"
case "$MODE" in
  cli) echo "  shorts compose --base a.mp4 --source b.mp4 --title '제목' -o short.mp4" ;;
  web|all) echo "  npm run dev                         # 웹 개발 서버 (vite)" ;;&
  cluster|all)
    echo "  # 클러스터: H3_REPO=$H3_REPO 를 .env 에 두면 env.sh 가 cluster_env.sh 의 주소만 읽음"
    echo "  # 서버는 그 레포에서 따로: source scripts/cluster_env.sh && bash scripts/provision.sh && bash scripts/serve.sh fl2va"
    echo "  shorts server check && shorts run examples/prompt-only.json" ;;
esac
exit "$FAILED"
