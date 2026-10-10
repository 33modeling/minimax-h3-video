"""shorts doctor — 실행 환경 점검. ✓ 통과 / ✗ 실패 / △ 선택 항목 없음·주의. 필수 항목이 실패하면 종료 코드 1.

각 도구가 어디서 왔는지(시스템 / .tools / .venv)도 함께 보여 준다. 키 값은 절대 출력하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import backends as B
from . import render as R

MARK = {"ok": "✓", "fail": "✗", "warn": "△"}
SETUP = "scripts/setup.sh"


def origin(path: str | os.PathLike | None, env: str | None = None) -> str:
    """경로가 레포의 .tools/.venv 안이면 그 이름, 환경변수로 지정했으면 그 변수, 아니면 '시스템'.
    (env.sh 가 SHORTS_FONT 를 .tools 글꼴로 잡아 두므로 경로를 먼저 본다 — 전에는 [SHORTS_FONT] 로만 나왔다)"""
    if path:
        p = Path(path).absolute()
        for name in (".tools", ".venv"):
            base = R.ROOT / name
            if p == base or base in p.parents:
                return name
    if env and os.environ.get(env):
        return env
    return "시스템" if path else ""


def _item(cid, label, required, status, detail, fix="", source=""):
    return {"id": cid, "label": label, "required": required, "status": status, "detail": detail, "fix": fix, "source": source}


def _run(args: list[str], timeout: float = 15) -> str:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def check_python() -> dict:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    src = origin(sys.base_prefix)
    if v >= (3, 10):
        return _item("python", "python", True, "ok", f"{ver} ({sys.executable})", source=src)
    return _item("python", "python", True, "fail", f"{ver} — 3.10 이상이 필요합니다",
                 f"{SETUP} --isolated (레포 안 .tools/python 에 독립 파이썬을 받아 .venv 를 만듦)", src)


def check_venv() -> dict:
    if sys.prefix != sys.base_prefix:
        return _item("venv", "venv", False, "ok", sys.prefix, source=origin(sys.prefix))
    return _item("venv", "venv", False, "warn", "가상환경 밖에서 실행 중", "source scripts/env.sh (없으면 먼저 scripts/setup.sh)")


def check_ffmpeg() -> list[dict]:
    out = []
    ff = None
    for cid, fn, env in (("ffmpeg", R.ffmpeg_bin, "SHORTS_FFMPEG"), ("ffprobe", R.ffprobe_bin, "SHORTS_FFPROBE")):
        try:
            path = fn()
            first = (_run([path, "-version"]).splitlines() or [""])[0]
            m = re.search(r"version (\S+)", first)
            out.append(_item(cid, cid, True, "ok", f"{m.group(1) if m else '?'} ({path})", source=origin(path, env)))
            if cid == "ffmpeg":
                ff = path
        except (R.RenderError, OSError, subprocess.SubprocessError) as e:
            out.append(_item(cid, cid, True, "fail", str(e).split(". ")[0],
                             f"{SETUP} (레포 안 .tools/bin 에 정적 빌드를 받음)"))
    if ff:
        try:
            has = " drawtext " in _run([ff, "-hide_banner", "-filters"])
        except (OSError, subprocess.SubprocessError):
            has = False
        out.append(_item("drawtext", "drawtext", True, "ok" if has else "fail",
                         "있음" if has else "이 ffmpeg 빌드에 drawtext 필터가 없음(자막·제목을 못 그림)",
                         "" if has else f"{SETUP} --isolated (drawtext 포함 정적 빌드를 .tools/bin 에 받음)", origin(ff, "SHORTS_FFMPEG")))
    else:
        out.append(_item("drawtext", "drawtext", True, "fail", "ffmpeg 가 없어 확인 못 함", f"{SETUP}"))
    return out


def check_font() -> dict:
    try:
        f = R.find_font()
    except R.RenderError:
        return _item("font", "font", True, "fail", "한글 글꼴을 찾지 못함",
                     f"{SETUP} (Noto Sans KR 을 .tools/fonts 에 받음) 또는 SHORTS_FONT=/경로/글꼴.ttf")
    if not Path(f).is_file():
        return _item("font", "font", True, "fail", f"파일 없음: {f}", "SHORTS_FONT 경로를 확인하세요", origin(f, "SHORTS_FONT"))
    return _item("font", "font", True, "ok", f, source=origin(f, "SHORTS_FONT"))


def check_h3video() -> dict:
    if os.environ.get("SHORTS_NO_H3VIDEO"):
        return _item("h3video", "h3video", False, "warn", "SHORTS_NO_H3VIDEO 가 켜져 있음 → 내장 호환 클라이언트 사용")
    try:
        import h3video  # type: ignore  # noqa: F401
        path = str(Path(h3video.__file__).parent)
        src = origin(path) if "site-packages" in path else "외부 소스(편집 설치)"
        return _item("h3video", "h3video", False, "ok", f"패키지 사용: {path}", source=src)
    except Exception:  # noqa: BLE001
        return _item("h3video", "h3video", False, "warn", "없음 → 내장 호환 클라이언트 사용(같은 요청 형식)",
                     f"원하면 {SETUP} --mode cluster --with-h3video (.venv 에 --no-deps 로만 넣음)")


def check_server(server: str | None, ref: str | None, timeout: float) -> list[dict]:
    if not server:
        return [_item("server-env", "server-env", False, "warn", "서버 주소 없음 (AI 생성 때만 필요, 합성만 하면 불필요)",
                      "export SHORTS_SERVER=http://127.0.0.1:30010 (또는 .env, 클러스터는 H3_REPO 로 cluster_env.sh 읽기)")]
    out = [_item("server-env", "server-env", False, "ok", f"{server}" + (f" · 참조 {ref}" if ref else " · 참조 서버 없음(--server 로 보냄)"))]
    key = os.environ.get("SHORTS_API_KEY")
    for cid, url in (("server", server), ("ref-server", ref if ref and ref != server else None)):
        if not url:
            continue
        try:
            info = B.server_check(url, "auto", key, timeout=timeout)
            out.append(_item(cid, cid, False, "ok", f"{info['backend']} · {info.get('model')}"))
        except B.BackendError as e:
            out.append(_item(cid, cid, False, "fail", str(e).split(". ")[0],
                             f"SSH 터널·서버를 확인한 뒤 shorts server check --server {url}"))
    return out


def check_anthropic() -> dict:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _item("anthropic", "anthropic", False, "ok", "ANTHROPIC_API_KEY 설정됨 (값은 표시하지 않음)")
    return _item("anthropic", "anthropic", False, "warn", "ANTHROPIC_API_KEY 없음 (Claude 기획 shorts plan 때만 필요)",
                 ".env 의 ANTHROPIC_API_KEY= 에 넣고 source scripts/env.sh")


def node_range() -> str:
    try:
        return json.loads((R.ROOT / "package.json").read_text(encoding="utf-8")).get("engines", {}).get("node", "")
    except (OSError, ValueError):
        return ""


def version_ok(ver: str, rng: str) -> bool:
    """'^20.19.0 || >=22.12.0' 같은 단순 범위만 다룬다(^ 와 >=)."""
    def t(s):
        return tuple(int(x) for x in (re.findall(r"\d+", s) + ["0", "0", "0"])[:3])
    v = t(ver)
    for cl in (c.strip() for c in rng.split("||")):
        if not cl:
            continue
        if cl.startswith("^") and v[0] == t(cl)[0] and v >= t(cl):
            return True
        if cl.startswith(">=") and v >= t(cl):
            return True
    return not rng.strip()


def check_node() -> dict:
    local = R.TOOLS / "node" / "bin"
    path = [str(local)] if local.is_dir() else []
    search = os.pathsep.join(path + [os.environ.get("PATH", "")])
    node, npm = shutil.which("node", path=search), shutil.which("npm", path=search)
    fix = f"{SETUP} --mode web (필요하면 nodejs.org 공식 배포본을 .tools/node 에 받음)"
    if not node or not npm:
        return _item("node", "node", False, "warn", "node/npm 없음 (웹 개발 때만 필요)", fix)
    try:
        ver = _run([node, "--version"]).strip()
    except (OSError, subprocess.SubprocessError):
        ver = "?"
    rng = node_range()
    ok = version_ok(ver.lstrip("v"), rng)
    return _item("node", "node", False, "ok" if ok else "fail", f"{ver} ({node})" + ("" if ok else f" — 필요: {rng}"),
                 "" if ok else fix, origin(node))


def run_checks(server: str | None, ref: str | None, timeout: float = 3) -> list[dict]:
    return [check_python(), check_venv(), *check_ffmpeg(), check_font(), check_h3video(),
            *check_server(server, ref, timeout), check_anthropic(), check_node()]


def report(checks: list[dict], as_json: bool) -> int:
    bad = [c for c in checks if c["required"] and c["status"] == "fail"]
    if as_json:
        print(json.dumps({"ok": not bad, "checks": checks}, ensure_ascii=False, indent=2))
        return 1 if bad else 0
    print("shorts doctor — 실행 환경 점검  (✓ 통과 · ✗ 실패 · △ 선택/주의)")
    for c in checks:
        src = f"  [{c['source']}]" if c["source"] else ""
        need = "" if c["required"] else " (선택)" if c["status"] != "ok" else ""
        print(f" {MARK[c['status']]} {c['label']:<11}{c['detail']}{src}{need}")
        if c["fix"] and c["status"] != "ok":
            print(f"     해결: {c['fix']}")
    if bad:
        print(f"\n필수 항목 {len(bad)}개 실패: {', '.join(c['label'] for c in bad)}")
    else:
        print("\n필수 항목 모두 통과 — 합성(compose)은 바로 할 수 있습니다.")
    return 1 if bad else 0
