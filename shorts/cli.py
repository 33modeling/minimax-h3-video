"""shorts — 프롬프트 JSON(+소스 영상)으로 9:16 숏폼을 만드는 CLI (표준 라이브러리 + ffmpeg).

  shorts run prompt.json [source.mp4 ...]      검증 → (AI 생성) → 합성 → 출력
  shorts gen --server URL --prompt "..." -o clip.mp4
  shorts compose --base base.mp4 --source a.mp4 b.mp4 --template cutaway -o short.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import backends as B
from . import plan as P
from . import render as R
from . import spec as S


class Out:
    """사람이 읽는 출력과 --json(줄마다 JSON 이벤트) 출력."""

    def __init__(self, as_json: bool = False):
        self.as_json = as_json
        self._last = 0.0

    def event(self, kind: str, msg: str = "", **data):
        if self.as_json:
            print(json.dumps({"event": kind, "message": msg, **data}, ensure_ascii=False), flush=True)
        elif msg:
            print(msg, flush=True)

    def progress(self, stage: str, frac: float, extra: str = ""):
        now = time.monotonic()
        if self.as_json:
            if frac >= 1 or now - self._last > 0.5:
                self._last = now
                print(json.dumps({"event": "progress", "stage": stage, "progress": round(frac, 3), "message": extra},
                                 ensure_ascii=False), flush=True)
            return
        if frac >= 1 or now - self._last > 0.2:
            self._last = now
            bar = "#" * int(frac * 24)
            end = "\n" if frac >= 1 else ""
            sys.stdout.write(f"\r  {stage} [{bar:<24}] {frac * 100:5.1f}% {extra}{end}")
            sys.stdout.flush()


def load_spec(path: str) -> tuple[dict, Path]:
    p = Path(path)
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"오류: 프롬프트 JSON 파일이 없습니다: {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"오류: JSON 문법 오류 {path} {e.lineno}번째 줄 {e.colno}번째 글자: {e.msg}")
    return spec, p.resolve().parent


def resolve(path: str | None, root: Path) -> str | None:
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    p = Path(path).expanduser()
    return str(p if p.is_absolute() else (root / p).resolve())


def resolve_spec_paths(spec: dict, root: Path, extra: list[str]) -> dict:
    """명세 안 경로를 JSON 폴더 기준 절대경로로. 두 번째 파일(들)은 같은 이름이면 그 자리에, 아니면 sources 로."""
    by_name = {S.base_name(f): str(Path(f).resolve()) for f in extra}
    spec = S.attach_files(spec, [str(Path(f).resolve()) for f in extra])

    def fix(p):
        if p is None:
            return None
        if S.base_name(p) in by_name and not Path(resolve(p, root) or "").is_file():
            return by_name[S.base_name(p)]
        return resolve(p, root)

    def fix_media(m):
        if isinstance(m, str):
            return fix(m)
        return dict(m, path=fix(m["path"]))
    out = dict(spec)
    if out.get("base"):
        out["base"] = fix_media(out["base"])
    if out.get("sources"):
        out["sources"] = [fix_media(m) for m in out["sources"]]
    for k in ("image", "bgm"):
        if out.get(k):
            out[k] = fix(out[k])
    if out.get("scenes"):
        out["scenes"] = [dict(s, **({"sources": [fix_media(m) for m in s["sources"]]} if s.get("sources") else {}),
                              **({"image": fix(s["image"])} if s.get("image") else {})) for s in out["scenes"]]
    return out


def missing_files(spec: dict) -> list[str]:
    miss = []
    for p in S.referenced_paths(spec):
        if not p.startswith(("http://", "https://")) and not Path(p).is_file():
            miss.append(p)
    return miss


def apply_overrides(spec: dict, a) -> dict:
    spec = dict(spec)
    for key in ("server", "ref_server", "backend", "template", "resolution", "fit", "model"):
        v = getattr(a, key, None)
        if v:
            spec[key] = v
    if getattr(a, "output", None):
        spec["output"] = a.output
    if getattr(a, "max_duration", None):
        spec["max_duration"] = a.max_duration
    if getattr(a, "poll", None):
        spec["poll"] = a.poll
    if getattr(a, "timeout", None):
        spec["timeout"] = a.timeout
    if not spec.get("server") and os.environ.get("SHORTS_SERVER"):
        spec["server"] = os.environ["SHORTS_SERVER"]
    if not spec.get("ref_server") and os.environ.get("SHORTS_REF_SERVER"):
        spec["ref_server"] = os.environ["SHORTS_REF_SERVER"]
    return spec


def scene_request(sc: dict, norm: dict) -> dict:
    return {"prompt": sc["prompt"], "task": sc["task"], "duration": sc["duration"], "ratio": norm["ratio"], "seed": sc["seed"],
            "refs": sc["sources"], "image": sc["image"], "title": norm.get("title") or ""}


def stager_from(a) -> B.Stager:
    return B.Stager(inbox_dir=getattr(a, "inbox_dir", None) or os.environ.get("SHORTS_INBOX"),
                    inbox_uri=getattr(a, "inbox_uri", None) or os.environ.get("SHORTS_INBOX_URI"),
                    inline=bool(getattr(a, "inline", False)))


def probe_inputs(spec: dict, generated: list[str]) -> tuple[dict, dict]:
    ci = S.compose_inputs(spec, generated)
    inputs = {"base": None, "clips": [], "bgm": None}
    paths = {"base": None, "clips": [], "bgm": None}
    if ci["base"]:
        inputs["base"] = {"media": ci["base"], "info": R.probe(ci["base"]["path"])}
        paths["base"] = ci["base"]["path"]
    for m in ci["clips"]:
        inputs["clips"].append({"media": m, "info": R.probe(m["path"])})
        paths["clips"].append(m["path"])
    if ci["bgm"]:
        inputs["bgm"] = {"path": ci["bgm"], "info": R.probe(ci["bgm"])}
        paths["bgm"] = ci["bgm"]
    return inputs, paths


# ---------------- 실행 상태(이어 받기) ----------------
def state_home() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "shorts"


def save_state(state: dict):
    p = Path(state["state_path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    reg = state_home() / "jobs"
    reg.mkdir(parents=True, exist_ok=True)
    for sc in state.get("scenes", []):
        if sc.get("remote_id"):
            (reg / f"{safe_id(sc['remote_id'])}.json").write_text(json.dumps({"state": str(p)}), encoding="utf-8")


def safe_id(rid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in rid)


def reuse_scenes(work: Path, reqs: list[dict], server: str, fresh: bool, out: Out) -> list[dict]:
    """같은 출력으로 다시 돌리면 요청이 같은 장면은 이어 쓰고(받은 파일·작업 ID), 달라진 장면은 새로 만든다."""
    old = {}
    sp = work / "state.json"
    if sp.is_file() and not fresh:
        try:
            old = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
    scenes = []
    for i, r in enumerate(reqs):
        f = work / f"scene{i + 1:02d}.mp4"
        prev = (old.get("scenes") or [])[i] if i < len(old.get("scenes") or []) else None
        if prev and prev.get("request") == r and old.get("server") == server:
            if prev.get("remote_id") or f.is_file():
                out.event("reuse", f"장면 {i + 1}: 지난 실행과 요청이 같아 이어 씁니다 (--fresh 로 새로 만들기)", scene=i + 1)
            scenes.append(prev)
            continue
        if f.exists():
            f.unlink()
        scenes.append({"request": r, "file": str(f), "remote_id": None})
    return scenes


def generate_all(state: dict, backend, out: Out, poll: float, timeout: float) -> list[str]:
    files = []
    n = len(state["scenes"])
    for i, sc in enumerate(state["scenes"]):
        target = sc["file"]
        if Path(target).is_file() and Path(target).stat().st_size > 1000:
            out.event("scene_skip", f"장면 {i + 1}/{n}: 이미 받음 ({target})", scene=i + 1)
            files.append(target)
            continue
        req = sc["request"]
        if not sc.get("remote_id"):
            out.event("submit", f"장면 {i + 1}/{n}: {req['task']} 요청 보내는 중… ({backend.name})", scene=i + 1, task=req["task"])
            sc["remote_id"] = backend.submit(req)
            save_state(state)
            out.event("submitted", f"  작업 ID: {sc['remote_id']}", scene=i + 1, job_id=sc["remote_id"])

        def on_prog(st, i=i):
            label = {"queued": "대기", "running": "생성", "done": "완료"}.get(st["state"], st["state"])
            out.progress(f"장면 {i + 1}/{n} {label}", st["progress"] if st["state"] != "done" else 1.0)
        try:
            B.wait_and_download(backend, sc["remote_id"], req["task"], target, poll=poll, timeout=timeout, on_progress=on_prog)
        except KeyboardInterrupt:
            print("", flush=True)
            out.event("interrupted", f"중단했습니다. 서버 작업은 계속 돌고 있습니다. 작업 ID: {sc['remote_id']}\n"
                      f"이어 받기: shorts resume {sc['remote_id']}", job_id=sc["remote_id"], state=state["state_path"])
            raise SystemExit(130)
        got = R.probe(target)
        out.event("downloaded", f"  받음: {target} ({got['width']}×{got['height']}, {got['duration']:.1f}초)", scene=i + 1, file=target,
                  duration=got["duration"], requested=req["duration"])
        if abs(got["duration"] - float(req["duration"])) > 0.5:
            out.event("warning", f"주의: 서버가 돌려준 영상 길이({got['duration']:.1f}초)가 요청({req['duration']}초)과 다릅니다. "
                      "합성은 받은 길이로 합니다", scene=i + 1)
        sc["done"] = True
        save_state(state)
        files.append(target)
    return files


def compose_from_spec(spec: dict, generated: list[str], output: str, out: Out, dry_run=False):
    norm = S.normalize_spec(spec)
    inputs, paths = probe_inputs(spec, generated)
    plan = P.plan_timeline(norm, inputs)
    for w in plan["warnings"]:
        out.event("warning", f"주의: {w}", warning=w)
    out.event("plan", "합성 계획: " + P.describe_plan(plan), plan=P.describe_plan(plan), duration=plan["duration"],
              width=plan["width"], height=plan["height"], template=plan["template"])
    if dry_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            args = R.build_command(plan, paths, output, tmp)
        out.event("ffmpeg", "ffmpeg 명령:\n  " + " ".join(_q(x) for x in args), argv=args)
        return plan
    R.render(plan, paths, output, on_progress=lambda f: out.progress("합성", f))
    info = R.probe(output)
    out.event("done", f"완성: {output} ({info['width']}×{info['height']}, {info['duration']:.1f}초, 오디오 {'있음' if info['hasAudio'] else '없음'})",
              output=output, **info)
    return plan


def _q(s: str) -> str:
    return s if all(c.isalnum() or c in "-_=./:,[]" for c in s) else "'" + s.replace("'", "'\\''") + "'"


def cmd_run(a) -> int:
    out = Out(a.json)
    if a.idea:
        from . import claude as C
        spec = plan_with_claude(a, out, a.files)
        if spec is None:
            return 0
        root = Path.cwd()
        extra = a.files
    else:
        if not a.files:
            raise SystemExit("오류: 프롬프트 JSON 파일을 주세요: shorts run prompt.json [source.mp4]")
        spec, root = load_spec(a.files[0])
        extra = a.files[1:]
    spec = apply_overrides(spec, a)
    # 두 번째 파일(소스 영상): 명세가 같은 이름으로 가리키면 그 자리, 아니면 sources 로 — 검증 전에 붙인다
    spec = S.attach_files(spec, [str(Path(f).resolve()) for f in extra])
    errors, warnings = S.check_spec(spec)
    if errors:
        out.event("invalid", "명세 오류:\n  - " + "\n  - ".join(errors), errors=errors)
        return 2
    for w in warnings:
        out.event("warning", f"주의: {w}", warning=w)
    spec = resolve_spec_paths(spec, root, extra)
    miss = missing_files(spec)
    if miss:
        out.event("invalid", "파일이 없습니다:\n  - " + "\n  - ".join(miss), errors=miss)
        return 2
    output = str(Path(spec.get("output") or "short.mp4") if Path(spec.get("output") or "short.mp4").is_absolute()
                 else (root / (spec.get("output") or "short.mp4")).resolve())
    if a.output:
        output = str(Path(a.output).resolve())
    norm = S.normalize_spec(spec)
    generated: list[str] = []
    if norm["usesAi"]:
        scenes = S.ai_scenes(spec)
        if not norm["server"]:
            out.event("invalid", "AI 생성에는 서버 주소가 필요합니다: JSON 의 server, --server 옵션, SHORTS_SERVER 환경변수 중 하나")
            return 2
        work = Path(output + ".parts")
        reqs = [scene_request(sc, norm) for sc in scenes]
        ref_durs = {}
        for r in reqs:
            for m in r["refs"]:
                if B.media_kind(m["path"]) == "video" and m["path"] not in ref_durs:
                    ref_durs[m["path"]] = R.probe(m["path"])["duration"]
        lim_errors = [f"장면 {i + 1}: {e}" for i, r in enumerate(reqs) for e in B.check_h3_limits(r, ref_durs)]
        if lim_errors and (norm["backend"] in ("auto", "sglang", "h3video")):
            out.event("invalid", "H3 사양 한도를 넘습니다:\n  - " + "\n  - ".join(lim_errors), errors=lim_errors)
            return 2
        if a.dry_run:
            backend_name = norm["backend"] if norm["backend"] != "auto" else "(자동 판별: 실행 때 서버에 물어봄)"
            out.event("dry_run", f"AI 서버: {norm['server']} · 종류 {backend_name}")
            tmp_backend = B.BACKENDS.get(norm["backend"] if norm["backend"] != "auto" else "sglang")
            bk = tmp_backend(norm["server"], None, stager=stager_from(a), model=norm["model"]) if tmp_backend is not B.H3VideoBackend else B.H3VideoBackend(norm["server"])
            for i, r in enumerate(reqs):
                body = bk.build_body(r, stage=False)
                out.event("request", f"장면 {i + 1}: POST {'/api/jobs' if bk.name == 'h3video' else '/v1/videos'} "
                          + json.dumps(body, ensure_ascii=False), scene=i + 1, body=body)
            fake = [str(Path(output + ".parts") / f"scene{i + 1:02d}.mp4") for i in range(len(reqs))]
            out.event("dry_run", "생성 영상이 생기면 이 영상들로 합성합니다: " + ", ".join(fake))
            return 0
        api_key = os.environ.get("SHORTS_API_KEY")
        backend = B.make_backend(norm["backend"], norm["server"], api_key, stager_from(a), norm["model"], norm["ref_server"])
        out.event("backend", f"AI 서버: {norm['server']} ({backend.name})", backend=backend.name)
        state = {"kind": "run", "state_path": str(work / "state.json"), "server": norm["server"], "ref_server": norm["ref_server"],
                 "backend": backend.name, "model": norm["model"], "spec": spec, "output": output,
                 "scenes": reuse_scenes(work, reqs, norm["server"], fresh=a.fresh, out=out)}
        save_state(state)
        generated = generate_all(state, backend, out, norm["poll"], norm["timeout"])
    compose_from_spec(spec, generated, output, out, dry_run=a.dry_run)
    return 0


def cmd_resume(a) -> int:
    out = Out(a.json)
    key = a.job
    p = Path(key)
    if not p.is_file():
        reg = state_home() / "jobs" / f"{safe_id(key)}.json"
        if not reg.is_file():
            out.event("error", f"작업 {key} 기록을 찾지 못했습니다 ({reg}). state.json 경로를 직접 주세요")
            return 2
        p = Path(json.loads(reg.read_text())["state"])
    state = json.loads(p.read_text(encoding="utf-8"))
    server = a.server or state["server"]
    backend = B.make_backend(state["backend"], server, os.environ.get("SHORTS_API_KEY"), stager_from(a), state.get("model"),
                             state.get("ref_server"))
    out.event("resume", f"이어 받기: {p} ({backend.name}, {server})")
    norm = S.normalize_spec(state["spec"])
    files = generate_all(state, backend, out, a.poll or norm["poll"], a.timeout or norm["timeout"])
    if state["kind"] == "run":
        compose_from_spec(state["spec"], files, state["output"], out)
    elif state["kind"] == "gen":
        import shutil
        shutil.copy2(files[0], state["output"])
        out.event("done", f"완성: {state['output']}", output=state["output"])
    return 0


def cmd_gen(a) -> int:
    out = Out(a.json)
    server = a.server or os.environ.get("SHORTS_SERVER")
    if not server:
        raise SystemExit("오류: --server 또는 SHORTS_SERVER 가 필요합니다")
    spec = {"prompt": a.prompt, "duration": a.duration, "ratio": a.ratio, "seed": a.seed}
    if a.source:
        spec["sources"] = [str(Path(s).resolve()) for s in a.source]
    if a.image:
        spec["image"] = str(Path(a.image).resolve())
    errors, _ = S.check_spec(spec)
    if errors:
        out.event("invalid", "입력 오류:\n  - " + "\n  - ".join(errors), errors=errors)
        return 2
    sc = S.ai_scenes(spec)[0]
    req = scene_request(sc, S.normalize_spec(spec))
    ref_durs = {m["path"]: R.probe(m["path"])["duration"] for m in req["refs"] if B.media_kind(m["path"]) == "video"}
    lim = B.check_h3_limits(req, ref_durs)
    if lim and a.backend != "vllm":
        out.event("invalid", "H3 사양 한도를 넘습니다:\n  - " + "\n  - ".join(lim), errors=lim)
        return 2
    backend = B.make_backend(a.backend, server, os.environ.get("SHORTS_API_KEY"), stager_from(a), a.model, a.ref_server)
    if a.dry_run:
        out.event("request", f"POST ({backend.name}) " + json.dumps(backend.build_body(req, stage=False), ensure_ascii=False))
        return 0
    output = str(Path(a.output).resolve())
    state = {"kind": "gen", "state_path": output + ".state.json", "server": server, "ref_server": a.ref_server,
             "backend": backend.name, "model": a.model, "spec": spec, "output": output,
             "scenes": [{"request": req, "file": output + ".part.mp4", "remote_id": None}]}
    save_state(state)
    files = generate_all(state, backend, out, a.poll, a.timeout)
    os.replace(files[0], output)
    out.event("done", f"완성: {output}", output=output, **R.probe(output))
    return 0


def cmd_compose(a) -> int:
    out = Out(a.json)
    spec: dict = {"base": a.base, "sources": a.source or [], "template": a.template, "resolution": a.resolution, "fit": a.fit,
                  "max_duration": a.max_duration or 60}
    if not a.base:
        spec.pop("base")
    if a.title:
        spec["title"] = a.title
    if a.captions:
        lines = [ln.strip() for ln in Path(a.captions).read_text(encoding="utf-8").splitlines() if ln.strip()]
        spec["captions"] = lines
    if a.bgm:
        spec["bgm"] = a.bgm
        spec["bgm_volume"] = a.bgm_volume
    errors, warnings = S.check_spec(spec)
    if errors:
        out.event("invalid", "입력 오류:\n  - " + "\n  - ".join(errors), errors=errors)
        return 2
    for w in warnings:
        out.event("warning", f"주의: {w}")
    spec = resolve_spec_paths(spec, Path.cwd(), [])
    miss = missing_files(spec)
    if miss:
        out.event("invalid", "파일이 없습니다:\n  - " + "\n  - ".join(miss), errors=miss)
        return 2
    compose_from_spec(spec, [], str(Path(a.output).resolve()), out, dry_run=a.dry_run)
    return 0


def plan_with_claude(a, out: Out, sources: list[str]):
    from . import claude as C
    srcs = []
    nframes = max(2, 6 // max(1, len(sources))) if sources else 0
    for s in sources:
        info = R.probe(s)
        frames = R.extract_frames(s, min(6, nframes))
        srcs.append({"name": Path(s).name, "duration": info["duration"], "width": info["width"], "height": info["height"],
                     "frames": frames})
    model = getattr(a, "model_claude", None) or C.DEFAULT_MODEL
    if a.dry_run:
        body = C.build_request(a.idea, srcs, model)
        url = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        out.event("claude_request", "Claude 에 보낼 요청 요약:\n" + json.dumps(C.request_summary(body, url), ensure_ascii=False, indent=2),
                  summary=C.request_summary(body, url))
        return None
    out.event("claude", f"Claude({model})에 기획을 요청합니다… (프레임 {sum(len(s['frames']) for s in srcs)}장)")
    try:
        res = C.plan(a.idea, srcs, model=model, log=lambda m: out.event("claude_retry", m))
    except C.PlanError as e:
        out.event("invalid", f"기획 실패: {e}" + ("".join(f"\n  - {x}" for x in e.errors)), errors=e.errors)
        raise SystemExit(2)
    spec = res["spec"]
    if sources:
        spec = S.attach_files(spec, [Path(s).name for s in sources])
    out.event("claude_done", f"기획 완료 (시도 {res['attempts']}회): 장면 {len(spec.get('scenes') or [1])}개", spec=spec)
    save_to = getattr(a, "plan_output", None)
    if save_to:
        Path(save_to).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out.event("saved", f"명세 저장: {save_to}", file=save_to)
    return spec


def cmd_plan(a) -> int:
    out = Out(a.json)
    a.plan_output = a.output
    spec = plan_with_claude(a, out, a.source or [])
    if spec is not None and not a.output:
        print(json.dumps(spec, ensure_ascii=False, indent=2))
    return 0


def cmd_server_check(a) -> int:
    out = Out(a.json)
    server = a.server or os.environ.get("SHORTS_SERVER")
    if not server:
        raise SystemExit("오류: --server 또는 SHORTS_SERVER 가 필요합니다")
    try:
        info = B.server_check(server, a.backend, os.environ.get("SHORTS_API_KEY"))
    except B.BackendError as e:
        out.event("error", f"서버 확인 실패: {e}", ok=False)
        return 1
    if a.json:
        out.event("server", "", **info)
        return 0
    print(f"서버: {info['server']}\n종류: {info['backend']}\n모델: {info.get('model')}\n상태: {json.dumps(info.get('health'), ensure_ascii=False)}")
    print("가능한 모드:")
    for k, v in (info.get("modes") or {}).items():
        print(f"  {k}: {v}")
    print("사양: " + json.dumps(info.get("limits"), ensure_ascii=False))
    return 0


def add_server_opts(p):
    p.add_argument("--server", help="AI 서버 주소 (또는 SHORTS_SERVER)")
    p.add_argument("--ref-server", dest="ref_server", help="참조 모드(ref2va) 전용 서버 주소 (SGLang H3 는 보통 30011)")
    p.add_argument("--backend", default=None, choices=["auto", "sglang", "vllm", "h3video"], help="서버 종류 (기본: 자동 판별)")
    p.add_argument("--model", help="서버에 보낼 model 이름 (선택)")
    p.add_argument("--poll", type=float, help="상태 확인 간격(초), 기본 3")
    p.add_argument("--timeout", type=float, help="생성 대기 한도(초), 기본 3600")
    p.add_argument("--inbox-dir", dest="inbox_dir", help="SGLang 서버와 공유된 폴더(참조 파일을 여기에 복사해 file:// 로 넘김)")
    p.add_argument("--inbox-uri", dest="inbox_uri", help="서버에서 본 inbox 경로 접두사 (예: file:///data/inbox)")
    p.add_argument("--inline", action="store_true", help="참조 파일을 data: URI 로 넣어 보냄(서버 지원 필요)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="shorts", description="프롬프트 JSON(+소스 영상)으로 9:16 숏폼 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="검증 → (AI 생성) → 합성 → 출력")
    r.add_argument("files", nargs="*", help="prompt.json [source.mp4 ...]  (--idea 를 쓰면 소스 영상만)")
    r.add_argument("--idea", help="아이디어로 시작: Claude 가 명세를 쓰고 이어서 생성·합성")
    r.add_argument("--claude-model", dest="model_claude", help="기획 모델 (기본 claude-opus-5-5)")
    r.add_argument("--plan-output", dest="plan_output", help="--idea 로 만든 명세를 저장할 경로")
    r.add_argument("-o", "--output", help="출력 MP4 (기본: JSON 의 output 또는 short.mp4)")
    r.add_argument("--template", choices=P.TEMPLATES)
    r.add_argument("--resolution", choices=["720x1280", "1080x1920"])
    r.add_argument("--fit", choices=["crop", "blur"])
    r.add_argument("--max-duration", dest="max_duration", type=float)
    r.add_argument("--fresh", action="store_true", help="지난 실행에서 받은 장면을 쓰지 않고 새로 생성")
    r.add_argument("--dry-run", action="store_true", help="계획만 보여 줌(요청 본문, ffmpeg 명령)")
    r.add_argument("--json", action="store_true", help="진행 상황을 줄마다 JSON 으로")
    add_server_opts(r)
    r.set_defaults(fn=cmd_run)

    g = sub.add_parser("gen", help="AI 영상 한 개 생성")
    g.add_argument("--prompt", required=True)
    g.add_argument("--source", nargs="*", help="참조 영상/이미지 (있으면 ref2va)")
    g.add_argument("--image", help="첫 프레임 이미지 (fl2va)")
    g.add_argument("--ratio", default="9:16")
    g.add_argument("--duration", type=float, default=8)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("-o", "--output", default="clip.mp4")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--json", action="store_true")
    add_server_opts(g)
    g.set_defaults(fn=cmd_gen, backend="auto", poll=3.0, timeout=3600.0)

    c = sub.add_parser("compose", help="AI 없이 템플릿 합성")
    c.add_argument("--base", help="기본 영상")
    c.add_argument("--source", nargs="*", help="소스 영상들")
    c.add_argument("--template", choices=P.TEMPLATES, default="cutaway")
    c.add_argument("--captions", help="자막 파일(한 줄에 한 장면)")
    c.add_argument("--title")
    c.add_argument("--bgm")
    c.add_argument("--bgm-volume", dest="bgm_volume", type=float, default=0.25)
    c.add_argument("--resolution", choices=["720x1280", "1080x1920"], default="720x1280")
    c.add_argument("--fit", choices=["crop", "blur"], default="blur")
    c.add_argument("--max-duration", dest="max_duration", type=float)
    c.add_argument("-o", "--output", default="short.mp4")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_compose)

    pl = sub.add_parser("plan", help="Claude 로 아이디어 → 프롬프트 JSON (ANTHROPIC_API_KEY 필요)")
    pl.add_argument("idea")
    pl.add_argument("--source", nargs="*", help="소스 영상 (프레임을 뽑아 함께 보냄)")
    pl.add_argument("--claude-model", dest="model_claude")
    pl.add_argument("-o", "--output", help="저장할 JSON 경로 (없으면 화면에)")
    pl.add_argument("--dry-run", action="store_true", help="보낼 요청 요약만 (키는 출력 안 함)")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=cmd_plan)

    rs = sub.add_parser("resume", help="중단한 생성 이어 받기")
    rs.add_argument("job", help="작업 ID 또는 state.json 경로")
    rs.add_argument("--json", action="store_true")
    add_server_opts(rs)
    rs.set_defaults(fn=cmd_resume)

    sv = sub.add_parser("server", help="서버 도구")
    svs = sv.add_subparsers(dest="server_cmd", required=True)
    ck = svs.add_parser("check", help="서버 상태·모델·모드·사양")
    ck.add_argument("--server")
    ck.add_argument("--backend", default="auto", choices=["auto", "sglang", "vllm", "h3video"])
    ck.add_argument("--json", action="store_true")
    ck.set_defaults(fn=cmd_server_check)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd == "run" and a.backend is None:
        a.backend = None
    try:
        return a.fn(a) or 0
    except (B.BackendError, R.RenderError, ValueError) as e:
        if getattr(a, "json", False):
            print(json.dumps({"event": "error", "message": str(e)}, ensure_ascii=False), flush=True)
        else:
            print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
