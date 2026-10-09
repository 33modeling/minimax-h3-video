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
from .progress import Out, SceneBoard, fmt_time


def input_error(msg: str):
    """입력(파일·옵션) 오류: 명세 오류와 같은 종료 코드 2 로 끝낸다."""
    print(f"오류: {msg}", file=sys.stderr)
    raise SystemExit(2)


def load_spec(path: str) -> tuple[dict, Path]:
    p = Path(path)
    try:
        # utf-8-sig: 메모장 등이 붙이는 BOM 도 받는다(웹의 File.text() 와 같음)
        spec = json.loads(p.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        input_error(f"프롬프트 JSON 파일이 없습니다: {path}")
    except IsADirectoryError:
        input_error(f"프롬프트 JSON 자리에 폴더를 줬습니다: {path}")
    except OSError as e:
        input_error(f"프롬프트 JSON 파일을 읽지 못했습니다: {path} ({e.strerror or e})")
    except UnicodeDecodeError:
        input_error(f"프롬프트 JSON 이 UTF-8 글자 파일이 아닙니다: {path} (영상 파일을 첫 번째로 주지 않았는지 확인하세요)")
    except json.JSONDecodeError as e:
        input_error(f"JSON 문법 오류 {path} {e.lineno}번째 줄 {e.colno}번째 글자: {e.msg}")
    if not isinstance(spec, dict):
        input_error(f"JSON 최상위는 객체({{ ... }})여야 합니다: {path}")  # 웹과 같은 문장
    return spec, p.resolve().parent


def resolve(path: str | None, root: Path) -> str | None:
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    p = Path(path).expanduser()
    return str(p if p.is_absolute() else (root / p).resolve())


def resolve_spec_paths(spec: dict, root: Path, extra: list[str]) -> dict:
    """명세 안 경로를 JSON 폴더 기준 절대경로로. 이름이 두 번째 파일(들)과 같으면 그 파일을 쓴다
    (두 번째 파일을 명세에 붙이는 일은 그 전에 S.match_files 가 한다)."""
    by_name = {S.base_name(f): str(Path(f).resolve()) for f in extra}

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


def parse_gen_size(v):
    """--gen-size 768 → 768(짧은 변), 432x768 → "432x768"."""
    v = str(v).strip()
    return int(v) if v.isdigit() else v


def missing_files(spec: dict) -> list[str]:
    miss = []
    for p in S.referenced_paths(spec):
        if not p.startswith(("http://", "https://")) and not Path(p).is_file():
            miss.append(p)
    return miss


def apply_overrides(spec: dict, a) -> dict:
    spec = dict(spec)
    for key in ("server", "ref_server", "backend", "template", "resolution", "fit", "model", "quality"):
        v = getattr(a, key, None)
        if v:
            spec[key] = v
    # 숫자 옵션은 0 도 그대로 넣어 검사를 받게 한다(전에는 --fps 0·--max-duration 0·--poll 0 이 말없이 무시됐다)
    for key in ("fps", "max_duration", "poll", "timeout"):
        if getattr(a, key, None) is not None:
            spec[key] = getattr(a, key)
    if getattr(a, "gen_size", None) is not None:
        spec["gen_size"] = parse_gen_size(a.gen_size)
    if getattr(a, "output", None):
        spec["output"] = a.output
    for key, env in (("resolution", "SHORTS_RESOLUTION"), ("quality", "SHORTS_QUALITY"), ("fps", "SHORTS_FPS")):
        v = os.environ.get(env, "").strip()
        if spec.get(key) is None and v:  # .env 의 기본값: 옵션·JSON 에 없을 때만. 틀린 값은 명세 검사가 한국어로 알려 준다
            spec[key] = int(v) if key == "fps" and v.isdigit() else v
    if not spec.get("server") and env_server():
        spec["server"] = env_server()
    if not spec.get("ref_server") and env_ref_server():
        spec["ref_server"] = env_ref_server()
    return spec


def env_server() -> str | None:
    """SHORTS_SERVER, 없으면 minimax-h3-video 의 cluster_env.sh 가 내보내는 H3_ENDPOINT(fl2va, 30010)."""
    return os.environ.get("SHORTS_SERVER") or os.environ.get("H3_ENDPOINT") or None


def env_ref_server() -> str | None:
    """SHORTS_REF_SERVER, 없으면 H3_REF_ENDPOINT(ref2va, 30011). 소스·참조가 있는 장면은 이쪽으로 보낸다."""
    return os.environ.get("SHORTS_REF_SERVER") or os.environ.get("H3_REF_ENDPOINT") or None


def cut_refs(reqs: list[dict], work: Path) -> None:
    """참조 영상에 start/end 가 있으면 그 구간만 잘라 보낸다(h3video 요청 형식에는 구간 필드가 없다)."""
    for i, r in enumerate(reqs):
        for j, m in enumerate(r["refs"]):
            if (m.get("start") or m.get("end") is not None) and media_kind_is_video(m["path"]):
                work.mkdir(parents=True, exist_ok=True)
                dst = work / f"ref{i + 1:02d}-{j + 1}.mp4"
                R.cut_clip(m["path"], m.get("start") or 0, m.get("end"), str(dst))
                r["refs"][j] = {"path": str(dst), "start": 0, "end": None}


def media_kind_is_video(path: str) -> bool:
    return B.media_kind(path) == "video"


def scene_request(sc: dict, norm: dict) -> dict:
    req = {"prompt": sc["prompt"], "task": sc["task"], "duration": sc["duration"], "ratio": norm["ratio"], "seed": sc["seed"],
           "refs": sc["sources"], "image": sc["image"], "title": norm.get("title") or ""}
    if norm.get("gen_size") is not None:
        req["gen_size"] = norm["gen_size"]
    return req


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
    # 웹(main.js prepareCompose)과 같은 검사·문장. 그대로 두면 계획 단계에서 0 으로 나누거나 ffmpeg 가 알 수 없는 오류를 낸다.
    if inputs["base"] and not inputs["base"]["info"]["width"]:
        raise S.SpecError([f"{Path(paths['base']).name}: 영상 트랙이 없습니다"])
    if inputs["bgm"] and not inputs["bgm"]["info"]["hasAudio"]:
        raise S.SpecError([f"{Path(paths['bgm']).name}: 소리 트랙이 없습니다"])
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


RETRIES = 5


class GenFailed(Exception):
    def __init__(self, scene: int, job_id: str | None, msg: str, hint: str):
        super().__init__(msg)
        self.scene, self.job_id, self.hint = scene, job_id, hint


def with_retry(fn, out: Out, board: SceneBoard | None, i: int | None, wait: float, sleep=time.sleep):
    """연결 끊김·시간 초과·5xx 는 RETRIES 번까지 다시 한다("재시도 중(3/5)")."""
    for k in range(1, RETRIES + 1):
        try:
            return fn()
        except B.BackendError as e:
            if not e.retryable or k == RETRIES:
                raise
            note = f"재시도 중({k}/{RETRIES}): {str(e)[:60]}"
            if board is not None and i is not None:
                board.set(i, note=note)
                board.render(force=True)
            else:
                out.event("retry", f"  {note}", attempt=k, total=RETRIES)
            sleep(min(30.0, max(1.0, wait) * k))
    raise AssertionError("unreachable")


def interrupted(out: Out, state: dict, job_id: str | None):
    out._print("")
    out.event("interrupted", f"중단했습니다. 서버 작업은 계속 돌고 있습니다. 작업 ID: {job_id}\n"
              f"이어 받기: shorts resume {job_id}", job_id=job_id, state=state["state_path"])
    raise SystemExit(130)


def generate_all(state: dict, backend, out: Out, poll: float, timeout: float) -> list[str]:
    """3단계(생성): 모든 장면을 요청하고 장면마다 한 줄로 상태를 보여 준다. 4단계(다운로드): 받은 길이도 확인."""
    scenes = state["scenes"]
    n = len(scenes)
    need = [i for i, sc in enumerate(scenes) if not (Path(sc["file"]).is_file() and Path(sc["file"]).stat().st_size > 1000)]
    out.stage("생성", f"장면 {n}개 · 장면당 최대 {fmt_time(timeout)} 대기")
    board = SceneBoard(out, n)
    for i, sc in enumerate(scenes):
        if i not in need:
            board.set(i, "done", 1.0, True, note="이미 받음", job_id=sc.get("remote_id"))
    for i in need:
        sc, req = scenes[i], scenes[i]["request"]
        if sc.get("remote_id"):
            out.event("submitted", f"  장면 {i + 1}/{n}: {req['task']} 이어서 확인 · 작업 ID: {sc['remote_id']}", scene=i + 1,
                      job_id=sc["remote_id"], task=req["task"])
        else:
            sc["remote_id"] = backend.submit(req)   # 요청은 다시 보내지 않는다(서버에 같은 작업이 두 번 생길 수 있음)
            sc["t_submit"] = time.time()
            save_state(state)
            out.event("submitted", f"  장면 {i + 1}/{n}: {req['task']} 요청함 · 작업 ID: {sc['remote_id']}", scene=i + 1,
                      job_id=sc["remote_id"], task=req["task"])
        board.set(i, "queued", job_id=sc["remote_id"], task=req["task"])
    active = list(need)
    t0 = time.monotonic()
    deadline = timeout * max(1, len(need))
    try:
        while active:
            for i in list(active):
                sc = scenes[i]
                st = with_retry(lambda sc=sc: backend.status(sc["remote_id"], sc["request"]["task"]), out, board, i, poll)
                board.set(i, st["state"], st["progress"] if st["state"] != "done" else 1.0,
                          st.get("has_progress", False) or st["state"] == "done", note="")
                if st["state"] == "failed":
                    err = st.get("error") or "이유 없음"
                    sc["remote_id_failed"] = sc["remote_id"]
                    sc["remote_id"] = None          # resume 하면 이 장면을 다시 요청한다
                    save_state(state)
                    board.finish()
                    raise GenFailed(i + 1, sc["remote_id_failed"], f"장면 {i + 1} 생성 실패: {err}", B.explain_error(str(err)))
                if st["state"] == "done":
                    active.remove(i)
                    sc["gen_seconds"] = round(board.elapsed(i), 1)
            if not active:
                break
            if time.monotonic() - t0 > deadline:
                board.finish()
                rid = scenes[active[0]]["remote_id"]
                raise B.BackendError(f"대기 시간 {fmt_time(deadline)} 를 넘었습니다 (장면 {active[0] + 1}, 작업 ID: {rid}). "
                                     f"나중에 `shorts resume {rid}` 로 이어 받으세요")
            # TTY 면 기다리는 동안 스피너·경과를 계속 갱신
            t_next = time.monotonic() + poll
            board.render()
            while out.tty and not out.as_json and time.monotonic() < t_next - 0.2:
                time.sleep(0.2)
                board.render()
            if not (out.tty and not out.as_json):
                time.sleep(poll)
        board.finish()
    except KeyboardInterrupt:
        board.finish()
        rid = next((scenes[i]["remote_id"] for i in active if scenes[i].get("remote_id")), None)
        interrupted(out, state, rid)
    out.stage("다운로드", f"장면 {len(need)}개")
    files = []
    for i, sc in enumerate(scenes):
        target, req = sc["file"], sc["request"]
        if i in need:
            try:
                with_retry(lambda: backend.download(sc["remote_id"], target, req["task"]), out, None, None, poll)
            except KeyboardInterrupt:
                interrupted(out, state, sc["remote_id"])
            sc["done"] = True
            save_state(state)
        got = R.probe(target)
        out.event("downloaded", f"  장면 {i + 1}/{n} 받음: {target} ({got['width']}×{got['height']}, {got['duration']:.1f}초)",
                  scene=i + 1, file=target, duration=got["duration"], requested=req["duration"])
        if abs(got["duration"] - float(req["duration"])) > 0.5:
            out.event("warning", f"주의: 서버가 돌려준 영상 길이({got['duration']:.1f}초)가 요청({req['duration']}초)과 다릅니다. "
                      "합성은 받은 길이로 합니다", scene=i + 1)
        files.append(target)
    return files


def print_summary(out: Out, state: dict | None, info: dict, output: str, fps: int):
    out.end_stages()
    total = time.monotonic() - out.t0
    parts = " · ".join(f"{k} {fmt_time(v)}" for k, v in out.stage_times.items() if v >= 0.05)
    lines = ["── 요약 ──", f"총 소요 {fmt_time(total)}" + (f" ({parts})" if parts else "")]
    scenes = []
    for i, sc in enumerate((state or {}).get("scenes", [])):
        rid = sc.get("remote_id") or sc.get("remote_id_failed") or "-"
        g = sc.get("gen_seconds")
        scenes.append({"scene": i + 1, "task": sc["request"]["task"], "seconds": g, "job_id": rid})
        lines.append(f"  장면 {i + 1}  {sc['request']['task']:<6} 생성 {fmt_time(g) if g is not None else '이전 실행'}  ({rid})")
    lines.append(f"출력: {output}  {info['width']}×{info['height']} · {info['duration']:.1f}초 · {fps}fps · "
                 f"오디오 {'있음' if info['hasAudio'] else '없음'}")
    out.event("summary", "\n".join(lines), total_seconds=round(total, 1), stages={k: round(v, 1) for k, v in out.stage_times.items()},
              scenes=scenes, output=output, **info)


def compose_from_spec(spec: dict, generated: list[str], output: str, out: Out, dry_run=False):
    norm = S.normalize_spec(spec)
    inputs, paths = probe_inputs(spec, generated)
    plan = P.plan_timeline(norm, inputs)
    for w in plan["warnings"]:
        out.event("warning", f"주의: {w}", warning=w)
    out.stage("합성", P.describe_plan(plan))
    out.event("plan", "", plan=P.describe_plan(plan), duration=plan["duration"], width=plan["width"], height=plan["height"],
              template=plan["template"], fps=plan["fps"])
    if dry_run:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            args = R.build_command(plan, paths, output, tmp)
        out.event("ffmpeg", "ffmpeg 명령:\n  " + " ".join(_q(x) for x in args), argv=args)
        return plan, None
    R.render(plan, paths, output, on_progress=lambda f: out.progress("합성", f))
    info = R.probe(output)
    out.event("done", f"완성: {output} ({info['width']}×{info['height']}, {info['duration']:.1f}초, 오디오 {'있음' if info['hasAudio'] else '없음'})",
              output=output, **info)
    return plan, info


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
            input_error("프롬프트 JSON 파일을 주세요: shorts run prompt.json [source.mp4]")
        spec, root = load_spec(a.files[0])
        extra = a.files[1:]
    uses_ai = bool(spec.get("prompt") or spec.get("scenes"))
    out.plan_stages(["검증", "서버 연결", "생성", "다운로드", "합성"] if uses_ai else ["검증", "합성"])
    out.stage("검증", f"{a.files[0] if a.files and not a.idea else '기획 결과'}" + (f" + 소스 {len(extra)}개" if extra else ""))
    spec = apply_overrides(spec, a)
    # 두 번째 파일: 명세가 같은 이름으로 가리키면 그 자리, 남는 영상은 sources, 음악은 빈 bgm — 검증 전에 붙인다(웹과 같은 규칙)
    spec, unused = S.match_files(spec, [str(Path(f).resolve()) for f in extra])
    for f in unused:
        out.event("warning", f"주의: {Path(f).name} 은(는) 쓰지 않습니다 (배경음이 이미 있거나, AI 없이 이미지는 쓰지 않음)", file=f)
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
            out.event("invalid", "AI 생성에는 서버 주소가 필요합니다: JSON 의 server, --server, SHORTS_SERVER 또는 H3_ENDPOINT"
                      "(minimax-h3-video 의 scripts/cluster_env.sh 를 source 하면 잡힘)")
            return 2
        work = Path(output + ".parts")
        reqs = [scene_request(sc, norm) for sc in scenes]
        if not a.dry_run:
            cut_refs(reqs, work)
        ref_durs = {}
        for r in reqs:
            for m in r["refs"]:
                if B.media_kind(m["path"]) == "video" and m["path"] not in ref_durs:
                    ref_durs[m["path"]] = R.probe(m["path"])["duration"]
        backend = None
        if not a.dry_run:  # 서버 종류를 먼저 알아내야 H3 한도를 적용할지 정할 수 있다(vLLM 은 적용 안 함)
            out.stage("서버 연결", norm["server"] + (f" (참조 모드: {norm['ref_server']})" if norm["ref_server"] else ""))
            backend = B.make_backend(norm["backend"], norm["server"], os.environ.get("SHORTS_API_KEY"), stager_from(a),
                                     norm["model"], norm["ref_server"])
        bname = backend.name if backend else norm["backend"]
        lim_errors = [f"장면 {i + 1}: {e}" for i, r in enumerate(reqs) for e in B.check_h3_limits(r, ref_durs)]
        if lim_errors and bname in ("auto", "sglang", "h3video"):
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
        out.event("backend", f"  서버 종류: {backend.name} · 주소: {norm['server']}"
                  + (f" · 참조 모드(ref2va): {norm['ref_server']}" if norm["ref_server"] and backend.name != "h3video" else ""),
                  backend=backend.name, server=norm["server"], ref_server=norm["ref_server"])
        gse = S.gen_short_edge(norm.get("gen_size"))
        if backend.name == "h3video" and gse not in (None, B.H3_SHORT_EDGE):
            out.event("warning", f"주의: h3video 웹 서버는 생성 해상도를 짧은 변 {B.H3_SHORT_EDGE}px 로 고정합니다(gen_size {gse} 무시)")
        state = {"kind": "run", "state_path": str(work / "state.json"), "server": norm["server"], "ref_server": norm["ref_server"],
                 "backend": backend.name, "model": norm["model"], "spec": spec, "output": output,
                 "scenes": reuse_scenes(work, reqs, norm["server"], fresh=a.fresh, out=out)}
        save_state(state)
        generated = generate_all(state, backend, out, norm["poll"], norm["timeout"])
    plan, info = compose_from_spec(spec, generated, output, out, dry_run=a.dry_run)
    if info:
        print_summary(out, state if norm["usesAi"] else None, info, output, plan["fps"])
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
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        out.event("error", f"작업 {key} 의 상태 파일을 읽지 못했습니다 ({p}): {e}")
        return 2
    server = a.server or state["server"]
    backend = B.make_backend(state["backend"], server, os.environ.get("SHORTS_API_KEY"), stager_from(a), state.get("model"),
                             state.get("ref_server"))
    out.plan_stages(["서버 연결", "생성", "다운로드"] + (["합성"] if state["kind"] == "run" else []))
    out.stage("서버 연결", f"{server} · 이어 받기 {p}")
    out.event("backend", f"  서버 종류: {backend.name} · 주소: {server}", backend=backend.name, server=server)
    norm = S.normalize_spec(state["spec"])
    files = generate_all(state, backend, out, a.poll or norm["poll"], a.timeout or norm["timeout"])
    if state["kind"] == "run":
        plan, info = compose_from_spec(state["spec"], files, state["output"], out)
        print_summary(out, state, info, state["output"], plan["fps"])
    elif state["kind"] == "gen":
        import shutil
        shutil.copy2(files[0], state["output"])
        out.event("done", f"완성: {state['output']}", output=state["output"])
    return 0


def cmd_gen(a) -> int:
    out = Out(a.json)
    server = a.server or env_server()
    a.ref_server = a.ref_server or env_ref_server()
    if not server:
        input_error("--server, SHORTS_SERVER 또는 H3_ENDPOINT 가 필요합니다")
    spec = {"prompt": a.prompt, "duration": a.duration, "ratio": a.ratio, "seed": a.seed}
    if a.gen_size:
        spec["gen_size"] = parse_gen_size(a.gen_size)
    if a.source:
        spec["sources"] = [str(Path(s).resolve()) for s in a.source]
    if a.image:
        spec["image"] = str(Path(a.image).resolve())
    errors, _ = S.check_spec(spec)
    if errors:
        out.event("invalid", "입력 오류:\n  - " + "\n  - ".join(errors), errors=errors)
        return 2
    miss = missing_files(spec)
    if miss:
        out.event("invalid", "파일이 없습니다:\n  - " + "\n  - ".join(miss), errors=miss)
        return 2
    sc = S.ai_scenes(spec)[0]
    req = scene_request(sc, S.normalize_spec(spec))
    ref_durs = {m["path"]: R.probe(m["path"])["duration"] for m in req["refs"] if B.media_kind(m["path"]) == "video"}
    out.plan_stages(["검증", "서버 연결", "생성", "다운로드"])
    out.stage("검증", "")
    out.stage("서버 연결", server)
    lim = B.check_h3_limits(req, ref_durs)
    if a.dry_run:  # run --dry-run 처럼 서버에 붙지 않는다(자동 판별이면 SGLang 형식으로 보여 줌)
        name = a.backend if a.backend != "auto" else "sglang"
        if lim and name != "vllm":
            out.event("invalid", "H3 사양 한도를 넘습니다:\n  - " + "\n  - ".join(lim), errors=lim)
            return 2
        bk = B.H3VideoBackend(server) if name == "h3video" else B.BACKENDS[name](server, None, stager=stager_from(a), model=a.model)
        label = name if a.backend != "auto" else "자동 판별: 실행 때 서버에 물어봄 · SGLang 형식"
        out.event("request", f"POST ({label}) " + json.dumps(bk.build_body(req, stage=False), ensure_ascii=False),
                  backend=a.backend, body=bk.build_body(req, stage=False))
        return 0
    backend = B.make_backend(a.backend, server, os.environ.get("SHORTS_API_KEY"), stager_from(a), a.model, a.ref_server)
    out.event("backend", f"  서버 종류: {backend.name} · 주소: {server}", backend=backend.name, server=server)
    if lim and backend.name != "vllm":
        out.event("invalid", "H3 사양 한도를 넘습니다:\n  - " + "\n  - ".join(lim), errors=lim)
        return 2
    output = str(Path(a.output).resolve())
    state = {"kind": "gen", "state_path": output + ".state.json", "server": server, "ref_server": a.ref_server,
             "backend": backend.name, "model": a.model, "spec": spec, "output": output,
             "scenes": [{"request": req, "file": output + ".part.mp4", "remote_id": None}]}
    save_state(state)
    files = generate_all(state, backend, out, a.poll, a.timeout)
    os.replace(files[0], output)
    info = R.probe(output)
    out.event("done", f"완성: {output}", output=output, **info)
    print_summary(out, state, info, output, info.get("fps") or 24)
    return 0


def cmd_compose(a) -> int:
    out = Out(a.json)
    out.plan_stages(["검증", "합성"])
    out.stage("검증", "")
    spec: dict = {"base": a.base, "sources": a.source or [], "template": a.template, "resolution": a.resolution, "fit": a.fit,
                  "max_duration": 60 if a.max_duration is None else a.max_duration, "fps": a.fps, "quality": a.quality}
    if not a.base:
        spec.pop("base")
    if a.title:
        spec["title"] = a.title
    if a.captions:
        try:
            text = Path(a.captions).read_bytes().decode("utf-8-sig")
        except FileNotFoundError:
            input_error(f"자막 파일이 없습니다: {a.captions}")
        except (OSError, UnicodeDecodeError) as e:
            input_error(f"자막 파일을 읽지 못했습니다(UTF-8 글자 파일이어야 함): {a.captions} ({e})")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
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
    plan, info = compose_from_spec(spec, [], str(Path(a.output).resolve()), out, dry_run=a.dry_run)
    if info:
        print_summary(out, None, info, str(Path(a.output).resolve()), plan["fps"])
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
        spec, _ = S.match_files(spec, [Path(s).name for s in sources])
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
    server = a.server or env_server()
    if not server:
        input_error("--server, SHORTS_SERVER 또는 H3_ENDPOINT 가 필요합니다")
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


def cmd_doctor(a) -> int:
    from . import doctor as D
    server = a.server or env_server()
    checks = D.run_checks(server, env_ref_server() if not a.server else None, timeout=a.timeout)
    return D.report(checks, a.json)


def add_server_opts(p):
    p.add_argument("--server", help="AI 서버 주소 (기본: SHORTS_SERVER, 없으면 H3_ENDPOINT — fl2va 30010)")
    p.add_argument("--ref-server", dest="ref_server",
                   help="참조 모드(ref2va) 서버 (기본: SHORTS_REF_SERVER, 없으면 H3_REF_ENDPOINT — 30011). 없으면 --server 로 보냄")
    p.add_argument("--backend", default=None, choices=["auto", "sglang", "vllm", "h3video"], help="서버 종류 (기본: 자동 판별)")
    p.add_argument("--model", help="서버에 보낼 model 이름 (선택)")
    p.add_argument("--poll", type=float, help="상태 확인 간격(초), 기본 3")
    p.add_argument("--timeout", type=float, help="장면당 생성 대기 한도(초), 기본 1800(H3 는 장면당 수 분)")
    p.add_argument("--inbox-dir", dest="inbox_dir", help="SGLang 서버와 공유된 폴더(참조 파일을 여기에 복사해 file:// 로 넘김)")
    p.add_argument("--inbox-uri", dest="inbox_uri", help="서버에서 본 inbox 경로 접두사 (예: file:///data/inbox)")
    p.add_argument("--inline", action="store_true", help="참조 파일을 data:;base64 URI 로 요청에 넣어 보냄(SGLang H3 가 받음, 원격 서버에서 파일 공유 없이 쓸 때)")


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
    r.add_argument("--resolution", help="출력 해상도 WxH (프리셋: " + ", ".join(S.RESOLUTION_PRESETS) + ", 짝수·240~2160)")
    r.add_argument("--gen-size", dest="gen_size", help="AI 생성 크기: 짧은 변(예: 768) 또는 WxH. H3 상한 768")
    r.add_argument("--fps", type=int, help="출력 fps (기본 30, 생성은 24 고정)")
    r.add_argument("--quality", choices=["low", "medium", "high"], help="출력 품질 (기본 medium)")
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
    g.add_argument("--gen-size", dest="gen_size", help="생성 크기: 짧은 변(예: 768) 또는 WxH. H3 상한 768")
    g.add_argument("-o", "--output", default="clip.mp4")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--json", action="store_true")
    add_server_opts(g)
    g.set_defaults(fn=cmd_gen, backend="auto", poll=3.0, timeout=1800.0)

    c = sub.add_parser("compose", help="AI 없이 템플릿 합성")
    c.add_argument("--base", help="기본 영상")
    c.add_argument("--source", nargs="*", help="소스 영상들")
    c.add_argument("--template", choices=P.TEMPLATES, default="cutaway")
    c.add_argument("--captions", help="자막 파일(한 줄에 한 장면)")
    c.add_argument("--title")
    c.add_argument("--bgm")
    c.add_argument("--bgm-volume", dest="bgm_volume", type=float, default=0.25)
    c.add_argument("--resolution", default=os.environ.get("SHORTS_RESOLUTION") or "720x1280", help="출력 해상도 WxH (프리셋: " + ", ".join(S.RESOLUTION_PRESETS) + ")")
    c.add_argument("--fps", type=int, default=os.environ.get("SHORTS_FPS") or 30, help="출력 fps (기본 30, SHORTS_FPS)")
    c.add_argument("--quality", choices=["low", "medium", "high"], default=os.environ.get("SHORTS_QUALITY") or "medium")
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

    dr = sub.add_parser("doctor", help="실행 환경 점검(파이썬·venv·ffmpeg·글꼴·서버·키·node)")
    dr.add_argument("--server", help="연결을 확인할 서버 (기본: SHORTS_SERVER, 없으면 H3_ENDPOINT)")
    dr.add_argument("--timeout", type=float, default=3.0, help="서버 연결 확인 대기(초), 기본 3")
    dr.add_argument("--json", action="store_true")
    dr.set_defaults(fn=cmd_doctor)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd == "run" and a.backend is None:
        a.backend = None
    try:
        return a.fn(a) or 0
    except GenFailed as e:
        tip = f"shorts resume {e.job_id}"
        if getattr(a, "json", False):
            print(json.dumps({"event": "error", "message": str(e), "hint": e.hint, "scene": e.scene, "job_id": e.job_id,
                              "resume": tip}, ensure_ascii=False), flush=True)
        else:
            print(f"오류: {e}\n  설명: {e.hint}\n  다시 시도: {tip}  (실패한 장면을 다시 요청하고 이어서 합성)", file=sys.stderr)
        return 1
    except S.SpecError as e:
        if getattr(a, "json", False):
            print(json.dumps({"event": "invalid", "message": str(e), "errors": e.errors}, ensure_ascii=False), flush=True)
        else:
            print("오류: " + "\n  - ".join(e.errors), file=sys.stderr)
        return 2
    except (B.BackendError, R.RenderError, ValueError) as e:
        hint = B.explain_error(str(e)) if isinstance(e, B.BackendError) else None
        if getattr(a, "json", False):
            print(json.dumps({"event": "error", "message": str(e), "hint": hint}, ensure_ascii=False), flush=True)
        else:
            print(f"오류: {e}" + (f"\n  설명: {hint}" if hint else ""), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
