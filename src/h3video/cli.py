"""CLI: h3video spec | health | plan | gen | ref | batch | jobs | show | status | fetch | web | tui"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

from . import prompt as P
from . import spec
from .client import DEFAULT_ENDPOINT, DEFAULT_REF_ENDPOINT, H3Client, H3Error, stage_input
from .jobs import INBOX_DIR, OUTPUT_DIR, Job, JobStore, Worker, build_request, new_job, plan_job

SERVER_DOWN = (
    "서버가 응답하지 않는다: {ep}\n"
    "  · 클러스터: 서버가 떠 있는지 scripts/health.sh, 없으면 tmux 에서 scripts/serve.sh\n"
    "  · PC 에서 쓸 때: SSH 터널  ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@host\n"
    "  · 주소가 다르면 --endpoint / --ref-endpoint (또는 H3_ENDPOINT / H3_REF_ENDPOINT)\n"
    "  · 서버 없이 요청만 확인: --dry-run"
)
STATUS_KO = {"pending": "대기", "running": "진행", "completed": "완료", "failed": "실패"}
EXAMPLES = """예:
  h3video health                                   서버 확인
  h3video gen "비 오는 서울 밤거리, 네온 반사" -s 8           8초 영상
  h3video gen -f prompt.txt -s 40 -r 9:16 -o out/          40초(장면 4개 체인), 세로, out/ 에 저장
  echo "..." | h3video gen -s 6                         표준입력으로 프롬프트
  h3video gen "..." --first key.png --dry-run             보내기 전에 요청만 확인
  h3video ir "비 오는 서울 밤거리" -s 8                  서버가 다듬은 공식 형식 프롬프트만 보기 (생성 안 함)
  h3video gen -f my_ir.txt --raw -s 8                   직접 쓴 프롬프트를 다듬지 않고 그대로
  h3video ref "<Subject 1>이 손을 흔든다" --image me.png -s 6
  h3video batch prompts.txt -o out/                     여러 개를 차례로 (--- 로 구분)
  h3video jobs / h3video show last                     지난 작업, 마지막 작업 상세
  h3video shorts run job.json [source.mp4]             숏폼 제작 (자막·음악·템플릿 합성, shortform/)
공통 옵션(--endpoint, --output-dir 등)은 명령 앞뒤 어디에 써도 된다."""


# ---------- helpers ----------
def seed_arg(v: str) -> int:
    if str(v).lower() in ("random", "rand", "r"):
        return random.randrange(2 ** 31)
    try:
        return int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"시드는 정수 또는 random: {v}") from None


def fmt_secs(s: float) -> str:
    s = int(s)
    return f"{s // 60}분 {s % 60:02d}초" if s >= 60 else f"{s}초"


def read_prompt(a) -> str:
    if a.prompt_file == "-" or a.prompt == "-":
        text = sys.stdin.read()
    elif a.prompt_file:
        text = Path(a.prompt_file).expanduser().read_text(encoding="utf-8")
    elif a.prompt:
        text = a.prompt
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = ""
    text = text.strip()
    if not text:
        raise H3Error("프롬프트가 필요하다: 인자로 쓰거나 -f 파일, -f - (표준입력)")
    if a.ir and not P.is_context_ir(text):
        text = P.build_context_ir(text, a.soundscape, a.music)
    return text


def check_inputs(paths) -> None:
    for p in paths:
        if p and not str(p).startswith(("http://", "https://", "file://")) and not Path(p).expanduser().is_file():
            raise H3Error(f"입력 파일 없음: {p}")


def validate_job(job: Job) -> list:
    """모든 장면의 요청을 미리 만들어 검사 (파일은 복사하지 않음). 첫 장면부터 GPU 를 쓰기 전에 잘못을 잡는다."""
    job.scenes = plan_job(job)
    reqs = []
    for sc in job.scenes:
        prev = "<이전 장면 마지막 프레임>" if sc.index > 0 else None
        req = build_request(job, sc, prev, lambda p: p if str(p).startswith(("http", "file://", "<")) else Path(p).expanduser().resolve().as_uri())
        req.validate()
        reqs.append(req)
    return reqs


def preview(job: Job) -> None:
    reqs = validate_job(job)
    print(f"[dry-run] {job.task}, 총 {job.total_seconds}초 → 장면 {len(reqs)}개 {[r.duration_seconds for r in reqs]}, "
          f"화면비 {job.aspect_ratio}, 시드 {job.seed}{'부터' if len(reqs) > 1 else ''}. 서버에 보내지 않았다.")
    for i, r in enumerate(reqs):
        print(f"--- 장면 {i + 1}: {r.task} {r.duration_seconds}초")
        print(json.dumps(r.to_json(), ensure_ascii=False, indent=2))


def preflight(a, needs_ref: bool) -> None:
    ep = a.ref_endpoint if needs_ref else a.endpoint
    if not H3Client(ep, timeout=5).healthy():
        raise H3Error(SERVER_DOWN.format(ep=ep))


def copy_out(final: str, out: str | None, many: bool = False, job_id: str = "") -> str:
    if not out:
        return final
    dest = Path(out).expanduser()
    if many or out.endswith(("/", os.sep)) or dest.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / Path(final).name
        if dest.exists():  # 폴더에 모을 때는 덮어쓰지 않는다 (batch 의 같은 제목, 지난 결과)
            dest = dest.with_name(f"{dest.stem}-{job_id[-6:] or int(time.time())}{dest.suffix}")
    else:
        if not dest.suffix:
            dest = dest.with_suffix(".mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final, dest)
    return str(dest)


def scene_line(jb: Job) -> str:
    marks = []
    for s in jb.scenes:
        if s.status == "completed":
            marks.append(f"장면{s.index + 1} 완료")
        elif s.status == "failed":
            marks.append(f"장면{s.index + 1} 실패")
        elif s.status == "in_progress":
            marks.append(f"장면{s.index + 1} {round(s.progress * 100)}%")
        elif s.status == "queued":
            marks.append(f"장면{s.index + 1} 서버 대기열")
    return f"{STATUS_KO.get(jb.status, jb.status)} " + (" · ".join(marks) if marks else "")


def run_jobs(a, jobs: list[Job], out: str | None = None) -> None:
    """진행 상황은 stderr, 결과 mp4 경로만 stdout (out=$(h3video gen ...) 로 받을 수 있게)."""
    for job in jobs:
        validate_job(job)
    needs_ref = any(j.task == "ref2va" for j in jobs)
    preflight(a, needs_ref)
    if any(j.task != "ref2va" for j in jobs) and needs_ref:
        preflight(a, False)
    store = JobStore(Path(a.output_dir))
    w = Worker(store, H3Client(a.endpoint), H3Client(a.ref_endpoint), inbox_dir=a.inbox_dir, poll=a.poll)
    for job in jobs:
        w.enqueue(job)
        print(f"job {job.id} 등록: {job.total_seconds}초, {job.aspect_ratio}, 시드 {job.seed}" + (f", {job.title}" if job.title else ""), file=sys.stderr)
    w.start()
    t0, last = time.time(), {}
    try:
        while True:
            time.sleep(1)
            pending = 0
            for job in jobs:
                jb = store.get(job.id)
                if jb.status not in ("completed", "failed"):
                    pending += 1
                line = scene_line(jb)
                if line != last.get(job.id) and (jb.status != "pending" or job.id not in last):
                    tag = f"{job.id[-6:]} " if len(jobs) > 1 else ""
                    print(f"  [{time.strftime('%H:%M:%S')}] {tag}{line}  (경과 {fmt_secs(time.time() - t0)})", file=sys.stderr, flush=True)
                    last[job.id] = line
            if not pending:
                break
    except KeyboardInterrupt:
        interrupted(store, jobs)
        sys.exit(130)
    failed = 0
    for job in jobs:
        jb = store.get(job.id)
        if jb.status == "completed":
            print(copy_out(jb.output, out, many=len(jobs) > 1, job_id=job.id))
        else:
            failed += 1
            print(f"실패 {job.id}: {jb.error}", file=sys.stderr)
    print(f"끝: {len(jobs) - failed}/{len(jobs)}개 완료, {fmt_secs(time.time() - t0)}", file=sys.stderr)
    if failed:
        sys.exit(1)


def interrupted(store: JobStore, jobs: list[Job]) -> None:
    print("\n중단했다 (Ctrl+C). 이 터미널의 작업 처리는 멈췄다.", file=sys.stderr)
    for job in jobs:
        jb = store.get(job.id)
        for sc in jb.scenes:
            if sc.video_id and sc.status not in ("completed", "failed"):
                ref = " --ref" if sc.task == "ref2va" else ""
                print(f"  서버에서는 장면 {sc.index + 1}({sc.video_id})이 계속 만들어질 수 있다. 끝난 뒤 받기: "
                      f"h3video fetch {sc.video_id}{ref} -o scene.mp4", file=sys.stderr)
        if jb.status not in ("completed", "failed"):
            jb.status, jb.error, jb.finished = "failed", "사용자가 중단함 (Ctrl+C)", time.time()
            store.save(jb)
    print(f"  기록 보기: h3video show {jobs[0].id}", file=sys.stderr)


def job_from_args(a, prompt: str, refs=None, base: Path | None = None) -> Job:
    def fix(p):  # batch 파일 안의 상대 경로는 그 파일 기준
        if p and base and not str(p).startswith(("http://", "https://", "file://", "/", "~")):
            return str(base / p)
        return p
    first, last = fix(getattr(a, "first", None)), fix(getattr(a, "last", None))
    refs = [{"type": r["type"], "path": fix(r["path"])} for r in (refs or [])]
    check_inputs([first, last] + [r["path"] for r in refs])
    return new_job(prompt, seconds=a.seconds, aspect_ratio=a.ratio, seed=a.seed, first_image=first, last_image=last,
                   refs=refs, scene_seconds=a.scene_seconds, steps=a.steps, title=a.title or "", negative=a.negative,
                   task="ref2va" if refs else None, raw=getattr(a, "raw", False))


# ---------- commands ----------
def cmd_spec(a):
    print(spec.summary())


def cmd_plan(a):
    scenes = spec.plan_scenes(a.seconds, a.scene_seconds)
    print(f"{a.seconds}초 → 장면 {len(scenes)}개: {scenes} (첫 장면 {'fl2va' if a.first else 't2va'}, 이후 fl2va 체인)")


def cmd_health(a):
    ok_main = H3Client(a.endpoint, timeout=5).healthy()
    ok_ref = H3Client(a.ref_endpoint, timeout=5).healthy()
    print(f"fl2va/t2va {a.endpoint}: {'OK' if ok_main else '응답 없음'}")
    print(f"ref2va     {a.ref_endpoint}: {'OK' if ok_ref else '응답 없음 (레퍼런스 영상을 안 쓰면 무시)'}")
    if not ok_main:
        print(SERVER_DOWN.format(ep=a.endpoint), file=sys.stderr)
        sys.exit(1)


def cmd_gen(a):
    job = job_from_args(a, read_prompt(a))
    preview(job) if a.dry_run else run_jobs(a, [job], a.out)


def cmd_ref(a):
    refs = [{"type": t, "path": p} for t in ("image", "video", "audio") for p in getattr(a, t)]
    if not refs:
        raise H3Error("--image/--video/--audio 중 하나 이상 필요")
    job = job_from_args(a, read_prompt(a), refs)
    preview(job) if a.dry_run else run_jobs(a, [job], a.out)


def cmd_ir(a):
    """서버(Diffusers 엔진)가 다듬은 공식 형식 프롬프트만 본다. 생성은 하지 않는다 (장면이 여럿이면 첫 장면)."""
    refs = [{"type": t, "path": p} for t in ("image", "video", "audio") for p in getattr(a, t)]
    job = job_from_args(a, read_prompt(a), refs or None)
    job.scenes = plan_job(job)
    sc = job.scenes[0]
    req = build_request(job, sc, None, lambda path: stage_input(path, a.inbox_dir))
    ep = a.ref_endpoint if req.task == "ref2va" else a.endpoint
    print(f"[ir] {req.task} {sc.duration}초 — 서버가 다듬는 중 (텍스트 인코더로 1분 안팎, 생성 중이면 그 뒤에)…", file=sys.stderr)
    t0 = time.time()
    res = H3Client(ep).rewrite(req)
    print(res["prompt"])
    print(f"[ir] {time.time() - t0:.0f}초. 이대로 만들려면 같은 옵션으로 gen/ref (서버가 같은 시드로 다시 다듬는다), "
          f"고쳐서 쓰려면 파일로 저장해 --raw -f 파일", file=sys.stderr)


BATCH_KEYS = {"seconds", "ratio", "seed", "title", "first", "last", "negative", "scene-seconds", "steps",
              "soundscape", "music", "ir", "raw", "image", "video", "audio"}


def parse_batch(text: str) -> list[tuple[dict, str]]:
    """블록은 '---' 줄로 나눈다. 블록 맨 위의 'key: value' 줄은 그 영상의 옵션, 나머지는 프롬프트. '#' 로 시작하는 줄은 주석."""
    items = []
    for block in re.split(r"^\s*---\s*$", text, flags=re.M):
        opts: dict = {}
        lines, header = [], True
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("#"):
                continue
            m = re.match(r"^([a-z-]+)\s*:\s*(.*)$", s) if header else None
            if m and m.group(1) in BATCH_KEYS:
                k, v = m.group(1), m.group(2).strip()
                if k in ("image", "video", "audio"):
                    opts.setdefault(k, []).extend(x.strip() for x in v.split(",") if x.strip())
                else:
                    opts[k] = v
                continue
            if header and not s:
                continue
            header = False
            lines.append(line)
        prompt = "\n".join(lines).strip()
        if prompt:
            items.append((opts, prompt))
    return items


def cmd_batch(a):
    path = Path(a.file).expanduser()
    items = parse_batch(sys.stdin.read() if a.file == "-" else path.read_text(encoding="utf-8"))
    if not items:
        raise H3Error(f"{a.file} 에 프롬프트가 없다 (블록은 --- 줄로 구분)")
    base = Path.cwd() if a.file == "-" else path.resolve().parent
    jobs = []
    for i, (opts, prompt) in enumerate(items, 1):
        b = argparse.Namespace(**vars(a))
        try:
            for k, v in opts.items():
                attr = k.replace("-", "_")
                if attr in ("seconds", "scene_seconds", "steps"):
                    v = int(v)
                elif attr == "seed":
                    v = seed_arg(v)
                elif attr in ("ir", "raw"):
                    v = v.lower() in ("1", "y", "yes", "true", "on", "예")
                elif attr == "ratio" and v not in spec.ASPECT_RATIOS:
                    raise H3Error(f"ratio 는 {spec.ASPECT_RATIOS} 중 하나: {v}")
                setattr(b, attr, v)
            if b.ir and not P.is_context_ir(prompt):
                prompt = P.build_context_ir(prompt, b.soundscape, b.music)
            refs = [{"type": t, "path": p} for t in ("image", "video", "audio") for p in opts.get(t, [])]
            jobs.append(job_from_args(b, prompt, refs, base))
        except (H3Error, ValueError, argparse.ArgumentTypeError) as e:
            raise H3Error(f"{a.file} 의 {i}번째 블록: {e}") from None
    print(f"{len(jobs)}개 작업", file=sys.stderr)
    if a.dry_run:
        for job in jobs:
            preview(job)
        return
    run_jobs(a, jobs, a.out)


def cmd_jobs(a):
    if not Path(a.output_dir).is_dir():
        print(f"작업이 없다 ({a.output_dir})")
        return
    rows = JobStore(Path(a.output_dir)).list()[: a.limit]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print(f"작업이 없다 ({a.output_dir})")
    for j in rows:
        when = time.strftime("%m-%d %H:%M", time.localtime(j["created"]))
        name = j["title"] or j["prompt"].replace("\n", " ")[:40]
        print(f"{j['id']}  {when}  {STATUS_KO.get(j['status'], j['status'])}  {j['total_seconds']:>3}초  {j['task']:<6}  {name}")
        if j.get("output"):
            print(f"    → {j['output']}")
        if j.get("error"):
            print(f"    ! {j['error'][:160]}")


def cmd_show(a):
    store = JobStore(Path(a.output_dir)) if Path(a.output_dir).is_dir() else None
    jb = store.find(a.job) if store else None
    if not jb:
        raise H3Error(f"작업을 찾지 못했다: {a.job} (목록: h3video jobs)")
    d = jb.to_json()
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return
    print(f"{jb.id}  {STATUS_KO.get(jb.status, jb.status)}  {jb.task}  {jb.total_seconds}초  {jb.aspect_ratio}  시드 {jb.seed}"
          + (f"  경과 {fmt_secs(d['elapsed'])}" if d["elapsed"] else ""))
    print(f"프롬프트: {jb.prompt}")
    for label, v in (("첫 프레임", jb.first_image), ("끝 프레임", jb.last_image), ("네거티브", jb.negative)):
        if v:
            print(f"{label}: {v}")
    for r in jb.refs:
        print(f"레퍼런스 {r['type']}: {r['path']}")
    for s in jb.scenes:
        print(f"  장면{s.index + 1} {s.task} {s.duration}초 {STATUS_KO.get(s.status, s.status)} {round(s.progress * 100)}%"
              + (f" id={s.video_id}" if s.video_id else "") + (f" → {s.output}" if s.output else "") + (f" ! {s.error}" if s.error else ""))
    if jb.output:
        print(f"결과: {jb.output}")
    if jb.error:
        print(f"오류: {jb.error}")


def cmd_status(a):
    print(json.dumps(H3Client(a.ref_endpoint if a.ref else a.endpoint).status(a.video_id), ensure_ascii=False, indent=2))


def cmd_fetch(a):
    out = H3Client(a.ref_endpoint if a.ref else a.endpoint).download(a.video_id, a.out or f"{a.video_id}.mp4")
    print(out)


def cmd_web(a):
    from .web import serve
    serve(host=a.host, port=a.port, endpoint=a.endpoint, ref_endpoint=a.ref_endpoint,
          output_dir=Path(a.output_dir), inbox_dir=a.inbox_dir, poll=a.poll, cors_origin=a.cors_origin)


def cmd_tui(a):
    from .tui import run
    run(a.endpoint, a.ref_endpoint, Path(a.output_dir), a.inbox_dir, a.poll)


# ---------- parser ----------
def add_global(p, top: bool) -> None:
    """공통 옵션. 하위 명령에도 달아 두어 `h3video gen ... --endpoint X` 처럼 뒤에 써도 된다."""
    S = argparse.SUPPRESS
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT if top else S, help="fl2va/t2va 서버 (H3_ENDPOINT)" if top else S)
    p.add_argument("--ref-endpoint", default=DEFAULT_REF_ENDPOINT if top else S, help="ref2va 서버 (H3_REF_ENDPOINT)" if top else S)
    p.add_argument("--output-dir", default=str(OUTPUT_DIR) if top else S, help="결과 폴더 (H3_OUTPUT_DIR)" if top else S)
    p.add_argument("--inbox-dir", default=INBOX_DIR if top else S, help="서버가 file:// 로 읽는 공유 폴더 (H3_INBOX_DIR)" if top else S)
    p.add_argument("--poll", type=float, default=3.0 if top else S, help="상태 확인 간격(초)" if top else S)


def add_video_opts(p) -> None:
    p.add_argument("-s", "--seconds", type=int, default=8, help=f"총 길이(초, 최소 {spec.DURATION_MIN}). {spec.DURATION_MAX} 초과면 장면 체인")
    p.add_argument("-r", "--ratio", default="16:9", choices=spec.ASPECT_RATIOS, help="화면비")
    p.add_argument("--seed", type=seed_arg, default=0, help="정수 또는 random (기본 0: 같은 프롬프트면 같은 결과)")
    p.add_argument("--scene-seconds", type=int, default=10, help="체인일 때 장면 하나 길이")
    p.add_argument("--steps", type=int, help="디노이징 스텝 (기본: 서버 기본값)")
    p.add_argument("-t", "--title", help="결과 mp4 이름")
    p.add_argument("-n", "--negative", help="넣지 않을 것 (네거티브 프롬프트)")
    p.add_argument("-o", "--out", help="결과를 여기로도 복사 (파일 경로, 또는 / 로 끝나는 폴더)")
    p.add_argument("--dry-run", action="store_true", help="서버에 보내지 않고 장면 분할과 요청 JSON 만 출력")
    p.add_argument("--raw", action="store_true",
                   help="서버의 프롬프트 다듬기를 끄고 쓴 그대로 보낸다 (Diffusers 엔진은 기본으로 공식 형식으로 다듬는다)")
    p.add_argument("--ir", action="store_true", help="3단 필드 이름만 붙여 감싸기 (다듬기 없이 직접 쓴 내용 그대로)")
    p.add_argument("--soundscape", help="--ir 일 때 환경음 설명")
    p.add_argument("--music", help="--ir 일 때 배경음악 설명")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="h3video", description="MiniMax-H3 영상 생성 클라이언트",
                                 epilog=EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_global(ap, True)
    sub = ap.add_subparsers(dest="cmd", metavar="명령")

    def cmd(name, fn, help_, **kw):
        p = sub.add_parser(name, help=help_, description=help_, **kw)
        add_global(p, False)
        p.set_defaults(fn=fn)
        return p

    cmd("spec", cmd_spec, "모델 사양")
    cmd("health", cmd_health, "서버 응답 확인 (fl2va 가 안 되면 종료 코드 1)")
    p = cmd("plan", cmd_plan, "길이 → 장면 분할 미리보기")
    p.add_argument("seconds", type=int); p.add_argument("--scene-seconds", type=int, default=10); p.add_argument("--first")

    p = cmd("gen", cmd_gen, "텍스트(+첫/끝 프레임) → 영상")
    p.add_argument("prompt", nargs="?", help="프롬프트. 생략하면 -f 파일이나 표준입력, '-' 는 표준입력")
    p.add_argument("-f", "--prompt-file", help="프롬프트 파일 (- 는 표준입력)")
    p.add_argument("--first", help="첫 프레임 이미지"); p.add_argument("--last", help="끝 프레임 이미지 (한 장면일 때)")
    add_video_opts(p)

    p = cmd("ref", cmd_ref, "레퍼런스(이미지·영상·오디오) → 영상 (ref2va)")
    p.add_argument("prompt", nargs="?", help="프롬프트. <Subject 1> 처럼 레퍼런스를 가리킨다")
    p.add_argument("-f", "--prompt-file", help="프롬프트 파일 (- 는 표준입력)")
    p.add_argument("--image", action="append", default=[], help=f"이미지 (최대 {spec.REF_LIMITS['image']}, 여러 번)")
    p.add_argument("--video", action="append", default=[], help=f"영상 (최대 {spec.REF_LIMITS['video']})")
    p.add_argument("--audio", action="append", default=[], help=f"오디오 (최대 {spec.REF_LIMITS['audio']})")
    add_video_opts(p)

    p = cmd("ir", cmd_ir, "다듬은 프롬프트만 보기 (Diffusers 엔진: 짧은 요청 → H3 공식 형식, 생성 안 함)")
    p.add_argument("prompt", nargs="?", help="프롬프트. 생략하면 -f 파일이나 표준입력")
    p.add_argument("-f", "--prompt-file", help="프롬프트 파일 (- 는 표준입력)")
    p.add_argument("--first", help="첫 프레임 이미지"); p.add_argument("--last", help="끝 프레임 이미지")
    p.add_argument("--image", action="append", default=[], help="레퍼런스 이미지 (ref2va)")
    p.add_argument("--video", action="append", default=[], help="레퍼런스 영상 (ref2va)")
    p.add_argument("--audio", action="append", default=[], help="레퍼런스 오디오 (ref2va)")
    add_video_opts(p)

    p = cmd("batch", cmd_batch, "파일의 여러 프롬프트를 차례로 (--- 줄로 구분, 블록 맨 위 'seconds: 10' 같은 줄은 그 영상 옵션)")
    p.add_argument("file", help="프롬프트 파일 (- 는 표준입력)")
    add_video_opts(p)

    p = cmd("jobs", cmd_jobs, "지난 작업 목록 (최근 순)")
    p.add_argument("--limit", type=int, default=20); p.add_argument("--json", action="store_true")
    p = cmd("show", cmd_show, "작업 상세 (id, id 앞부분, last)")
    p.add_argument("job", nargs="?", default="last"); p.add_argument("--json", action="store_true")
    p = cmd("status", cmd_status, "서버의 영상 상태 (video_id)")
    p.add_argument("video_id"); p.add_argument("--ref", action="store_true", help="ref2va 서버에 묻기")
    p = cmd("fetch", cmd_fetch, "서버에서 완성된 영상 받기 (video_id)")
    p.add_argument("video_id"); p.add_argument("-o", "--out"); p.add_argument("--ref", action="store_true", help="ref2va 서버에서 받기")
    p = cmd("web", cmd_web, "로컬호스트 웹 UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("H3_WEB_PORT", 8790)))
    p.add_argument("--cors-origin", default=None,
                   help="이 서버를 부를 수 있는 웹 출처(쉼표 구분, * 는 전부). 기본 끔. 환경변수 H3_CORS_ORIGIN")
    cmd("tui", cmd_tui, "터미널 UI (tmux 안에서)")
    sub.add_parser("shorts", help="숏폼 제작 (shortform/ 의 shorts CLI, 인자는 그대로 전달: h3video shorts --help)")
    return ap


def run_shorts(argv: list[str]) -> None:
    """`h3video shorts ...` → 숏폼 제작 CLI(shortform/shorts). 인자는 그대로 넘긴다."""
    try:
        from shorts.cli import main as shorts_main
    except ImportError:
        here = Path(__file__).resolve().parents[2] / "shortform"
        if not (here / "shorts" / "cli.py").is_file():
            raise H3Error("숏폼 모듈(shortform/shorts)을 찾지 못했다. 레포 루트에서 pip install -e . 하거나 source scripts/cluster_env.sh") from None
        sys.path.insert(0, str(here))
        from shorts.cli import main as shorts_main
    sys.exit(shorts_main(argv) or 0)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["shorts"]:
        try:
            return run_shorts(argv[1:])
        except H3Error as e:
            sys.exit(f"오류: {e}")
    ap = build_parser()
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return
    try:
        a.fn(a)
    except H3Error as e:
        sys.exit(f"오류: {e}")
    except KeyboardInterrupt:
        sys.exit(130)
    except (FileNotFoundError, UnicodeDecodeError) as e:
        sys.exit(f"오류: {e}")


if __name__ == "__main__":
    main()
