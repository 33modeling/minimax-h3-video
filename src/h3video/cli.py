"""CLI: h3video gen | json | batch | ref | ir | plan | jobs | show | fetch | status | health | doctor | config | spec | web | tui | shorts

명령 없이 써도 알아서 고른다: h3video "프롬프트" → gen, h3video 이야기.json 그림/ → json, h3video 사진.png "프롬프트" → gen --first.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from . import config as C
from . import hints as HN
from . import prompt as P
from . import spec
from .client import H3Client, H3Error, stage_input
from .jobs import Job, JobStore, Worker, build_request, fit_to_server, new_job, plan_job

SERVER_DOWN = (
    "서버가 응답하지 않는다: {ep}\n"
    "  · 클러스터: 서버 켜기 bash scripts/up.sh (참고 자료는 --ref), 떠 있는지는 bash scripts/status.sh\n"
    "  · PC 에서 쓸 때: SSH 터널  ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@host\n"
    "  · 주소가 다르면 한 번 저장: h3video config set endpoint http://주소:포트 (참고 자료는 ref-endpoint)\n"
    "    또는 --endpoint / --ref-endpoint, H3_ENDPOINT / H3_REF_ENDPOINT\n"
    "  · 서버 없이 요청만 확인: --dry-run   · 한 번에 점검: h3video doctor"
)
STATUS_KO = {"pending": "대기", "running": "진행", "completed": "완료", "failed": "실패"}
EXAMPLES = [
    ('h3video "비 오는 서울 밤거리, 네온 반사" -s 8', "글로 8초 영상"),
    ("h3video gen prompt.txt -s 40 -r 9:16 -o out/", "40초(장면 4개 이어 붙임), 세로, out/ 에도 저장"),
    ('h3video 사진.png "아이가 천천히 웃는다" -s 6', "이 그림에서 시작 (= gen --first 사진.png)"),
    ('h3video gen "1번 사진 사람이 손을 흔든다" --image me.png', "사진 참고 (ref2va 서버)"),
    ("h3video 토토.json pages/ -o 토토.mp4", "JSON + 그림 폴더로 한 번에 (= json)"),
    ("h3video json --resume last", "실패한 장면만 다시 하고 이어 붙이기"),
    ('echo "..." | h3video gen -s 6', "표준입력으로 프롬프트"),
    ('h3video gen "..." -s 40 --dry-run', "보내지 않고 장면 나누기·요청만 보기"),
    ("h3video batch prompts.txt -o out/", "여러 개를 차례로 (--- 로 구분)"),
    ("h3video jobs · h3video show last", "지난 작업, 마지막 작업 자세히"),
    ("h3video doctor", "서버·폴더·ffmpeg 점검과 할 일"),
    ("h3video shorts run job.json", "숏폼 제작 (자막·음악·템플릿, shortform/)"),
]
QUICKSTART = [
    ('h3video "비 오는 서울 밤거리, 네온 반사" -s 8', "글로 8초 영상"),
    ('h3video 사진.png "아이가 천천히 웃는다" -s 6', "이 그림에서 시작"),
    ("h3video 이야기.json 그림폴더/", "JSON + 그림으로 장면마다 만들어 이어 붙이기"),
    ("h3video jobs", "지난 작업 (자세히: h3video show last)"),
    ("h3video doctor", "서버가 켜졌는지, 안 되면 할 일"),
    ("h3video web", "브라우저 화면 (http://127.0.0.1:8790)"),
]


def text_width(s: str) -> int:
    """터미널에서 차지하는 칸 수 (한글은 두 칸)."""
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def rows(items, indent: int = 2, gap: int = 3) -> str:
    """(명령, 설명) 줄들을 설명 칸이 맞게 그린다. 설명이 빈 줄은 그대로."""
    w = max((text_width(c) for c, d in items if d), default=0)
    return "\n".join(" " * indent + c + (" " * (w - text_width(c) + gap) + d if d else "") for c, d in items)


def quickstart() -> str:
    return ("h3video — 글·그림으로 소리까지 있는 영상 만들기\n\n" + rows(QUICKSTART) + "\n\n"
            "서버 주소 저장(한 번만): h3video config set endpoint http://127.0.0.1:30010\n"
            "명령 전부와 옵션: h3video --help   ·   명령마다: h3video gen --help")


# (묶음 이름, [(명령, 한 줄 설명)])
COMMAND_GROUPS = [
    ("만들기", [("gen", "영상 만들기: 글, 첫/끝 그림(--first/--last), 참고 자료(--image/--video/--audio)"),
               ("json", "JSON 하나 + 그림들로 장면마다 만들어 이어 붙이기 (장면 수·길이는 JSON 에서)"),
               ("batch", "파일의 여러 프롬프트를 차례로 (--- 줄로 구분)"),
               ("ref", "참고 자료로 만들기 (gen --image 와 같다)"),
               ("ir", "서버가 다듬은 프롬프트만 보기 (만들지 않음)"),
               ("plan", "길이 → 장면 나누기 미리 보기")]),
    ("지난 작업", [("jobs", "지난 작업 목록 (최근 순)"),
                 ("show", "작업 자세히 (id, id 앞부분, last)"),
                 ("fetch", "서버에서 완성된 영상 받기 (video_id)"),
                 ("status", "서버의 영상 상태 (video_id)")]),
    ("서버·설정", [("health", "서버 확인 (꺼져 있으면 할 일)"),
                 ("doctor", "서버·결과 폴더·ffmpeg 를 한 번에 점검하고 할 일 알려 주기"),
                 ("config", "서버 주소·결과 폴더 저장 (환경 변수 없이)"),
                 ("spec", "모델 사양")]),
    ("화면", [("web", "브라우저 화면 (로컬호스트 웹 UI)"),
             ("tui", "터미널 화면 (tmux 안에서)"),
             ("shorts", "숏폼 제작 (shortform/ 의 shorts CLI, 인자는 그대로 전달)")]),
]
COMMANDS = [n for _, cmds in COMMAND_GROUPS for n, _ in cmds]
COMMAND_HELP = {n: h for _, cmds in COMMAND_GROUPS for n, h in cmds}
# 다른 이름으로 불러도 알아듣는다 (예전 이름·모델 이름·흔한 말)
ALIASES = {"t2v": "gen", "t2va": "gen", "text": "gen", "make": "gen", "generate": "gen", "new": "gen",
           "i2v": "gen", "image": "gen", "img": "gen", "fl2va": "gen", "first": "gen",
           "ref2va": "ref", "reference": "ref", "story": "json", "book": "json", "list": "jobs", "ls": "jobs",
           "history": "jobs", "log": "jobs", "info": "show", "get": "fetch", "download": "fetch",
           "check": "health", "ping": "health", "settings": "config", "conf": "config", "ui": "web", "server": "web"}
ALIAS_NOTE = {"i2v": "그림에서 시작하려면 --first 그림.png", "image": "그림에서 시작하려면 --first 그림.png",
              "img": "그림에서 시작하려면 --first 그림.png", "fl2va": "그림에서 시작하려면 --first 그림.png (끝 그림은 --last)",
              "first": "그림은 --first 그림.png 로 준다", "server": "H3 서버를 켜는 것은 bash scripts/up.sh"}
GLOBAL_VALUE_OPTS = ("--endpoint", "--ref-endpoint", "--output-dir", "--inbox-dir", "--poll")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")

CMD_EXAMPLES = {
    "gen": [('h3video gen "비 오는 서울 밤거리, 네온 반사" -s 8', "글로 8초"),
            ("h3video gen prompt.txt -s 40 -r 9:16 -o out/", "40초(장면 4개 이어 붙임), 세로, out/ 에도 저장"),
            ('h3video gen "아이가 웃는다" --first a.png --last b.png', "이 그림에서 시작해 저 그림으로 끝"),
            ('h3video gen "1번 사진 사람이 손을 흔든다" --image me.png', "사진 참고 (ref2va 서버)"),
            ('h3video gen "..." -s 40 --dry-run', "보내지 않고 장면 나누기·요청만 보기"),
            ('h3video gen "..." --open', "끝나면 바로 재생"),
            ('명령 없이도: h3video "비 오는 밤거리" -s 8 · h3video 사진.png "웃는다"', "")],
    "ref": [('h3video ref "1번 사진 사람이 바닷가를 걷는다" --image face.png -s 8', ""),
            ('h3video ref "1번 영상 춤을 1번 사진 사람이" --video dance.mp4 --image face.png', "")],
    "ir": [('h3video ir "비 오는 서울 밤거리" -s 8 > p.txt', "다듬은 글만 보기 (만들지 않음)"),
           ("h3video gen p.txt --raw -s 8", "고친 글을 그대로 만들기")],
    "batch": [("h3video batch prompts.txt -o ~/videos/", ""),
              ("prompts.txt: 영상마다 --- 줄로 나누고, 블록 위쪽 'seconds: 8' 'first: a.png' 줄은 그 영상의 옵션", "")],
    "json": [("h3video json 토토.json --list", "만들지 않고 장면·길이·그림만 보기"),
             ("h3video json 토토.json pages/ -o 토토.mp4", "그림 폴더와 함께 → 이어 붙인 영상"),
             ("h3video json --resume last", "실패한·안 된 장면만 다시 하고 이어 붙이기"),
             ("명령 없이도: h3video 토토.json pages/", "")],
    "plan": [("h3video plan 45", "45초 → 장면 몇 개로 나뉘는지")],
    "jobs": [("h3video jobs --limit 5", ""), ("h3video jobs --json", "")],
    "show": [("h3video show last", "마지막 작업"), ("h3video show 20261012-1015", "id 앞부분으로")],
    "status": [("h3video status video_0001 [--ref]", "")],
    "fetch": [("h3video fetch video_0001 -o a.mp4", "참고 자료로 만든 것은 --ref")],
    "health": [("h3video health", ""), ("h3video health --endpoint http://127.0.0.1:30010", "")],
    "doctor": [("h3video doctor", "서버·결과 폴더·ffmpeg·설정을 보고, 안 되는 것마다 할 일")],
    "config": [("h3video config", "지금 값과 어디서 왔는지"),
               ("h3video config set endpoint http://127.0.0.1:30010", "글·그림 서버 주소 저장"),
               ("h3video config set ref-endpoint http://127.0.0.1:30011", "참고 자료 서버 주소"),
               ("h3video config set output-dir ~/videos", "결과 폴더"),
               ("h3video config unset endpoint", "지우기"),
               ("쓸 수 있는 이름: endpoint, ref-endpoint, output-dir, inbox-dir", ""),
               ("우선순위: 명령 옵션 > 환경 변수(H3_ENDPOINT 등) > 설정 파일 > 기본값", "")],
    "spec": [("h3video spec", "")],
    "web": [("h3video web", "http://127.0.0.1:8790"), ("h3video web --port 8800", ""),
            ("h3video web --cors-origin https://33modeling.pages.dev", "허브 화면에서도 부를 수 있게")],
    "tui": [("h3video tui", "tmux 안에서. n 새 작업, q 끝내기")],
}


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


PROMPT_EXTS = (".txt", ".md", ".json", ".prompt", ".text", ".yaml", ".yml")


def looks_like_file(s: str) -> bool:
    s = s.strip()
    return bool(s) and not any(c.isspace() for c in s) and (s.lower().endswith(PROMPT_EXTS) or "/" in s)


def similar_files(s: str) -> str:
    import difflib
    p = Path(s).expanduser()
    folder = p.parent if str(p.parent) not in ("", ".") else Path.cwd()
    try:
        names = [f.name for f in folder.iterdir() if f.is_file()]
    except OSError:
        return ""
    near = difflib.get_close_matches(p.name, names, n=3, cutoff=0.6)
    return (" — 혹시: " + ", ".join(str(folder / n) if folder != Path.cwd() else n for n in near)) if near else ""


def read_prompt(a) -> str:
    if a.prompt_file == "-" or a.prompt == "-":
        text = sys.stdin.read()
    elif a.prompt_file:
        text = Path(a.prompt_file).expanduser().read_text(encoding="utf-8")
    elif a.prompt and "\n" not in a.prompt and len(a.prompt) < 4096 and Path(a.prompt).expanduser().is_file():
        text = Path(a.prompt).expanduser().read_text(encoding="utf-8")   # 파일 이름을 주면 그 내용 (-f 없이)
        print(f"[프롬프트] 파일 {a.prompt} 을 읽었다 ({len(text)}자)", file=sys.stderr)
    elif a.prompt and looks_like_file(a.prompt):   # 파일 이름처럼 생겼는데 없다 → 오타일 것: 그 글자로 영상을 만들지 않는다
        raise H3Error(f"프롬프트 파일이 없다: {a.prompt}" + similar_files(a.prompt))
    elif a.prompt:
        text = a.prompt
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = ""
    text = text.strip()
    if not text:
        raise H3Error("프롬프트가 필요하다: 인자로 쓰거나 -f 파일, -f - (표준입력)")
    if a.ir and not P.is_context_ir(text) and not refs_of(a):   # 참고 자료(ref2va)는 형식이 달라 감싸지 않는다(서버가 바꾼다)
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
            stage = getattr(s, "stage", None)
            marks.append(f"장면{s.index + 1} " + (f"{stage} " if stage and stage != "생성 중" else "")
                         + (f"{round(s.progress * 100)}%" if stage in (None, "생성 중") else "").rstrip())
        elif s.status == "queued":
            marks.append(f"장면{s.index + 1} 서버 대기열")
    return f"{STATUS_KO.get(jb.status, jb.status)} " + (" · ".join(marks) if marks else "")


def compact_status(jb: Job) -> str:
    """한 줄 진행 표시용: '장면 2/4 · 생성 45%'."""
    if jb.status == "pending":
        return "준비 중"
    if jb.status in ("completed", "failed"):
        return STATUS_KO[jb.status]
    n = len(jb.scenes)
    cur = next((s for s in jb.scenes if s.status != "completed"), None)
    if cur is None:
        return "이어 붙이는 중" if n > 1 else "마무리 중"
    where = f"장면 {cur.index + 1}/{n} · " if n > 1 else ""
    stage = getattr(cur, "stage", None)
    if cur.status == "queued":
        what = "서버 대기열"
    elif cur.status == "pending":
        what = "준비 중"
    elif stage and stage != "생성 중":
        what = stage
    else:
        what = f"생성 {round(cur.progress * 100)}%"
    return where + what


def fit_width(s: str, cols: int) -> str:
    """터미널 한 줄에 맞게 자른다 (한글은 두 칸)."""
    if text_width(s) <= cols:
        return s
    out, w = [], 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if w + cw > cols - 1:
            break
        out.append(c)
        w += cw
    return "".join(out) + "…"


class Progress:
    """기다리는 동안의 진행 표시. 터미널이면 한 줄을 계속 고쳐 쓰고, 파일·파이프면 바뀔 때만 줄을 더한다."""
    SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, stream=None, tty: bool | None = None):
        self.stream = stream or sys.stderr
        if tty is None:
            try:
                tty = self.stream.isatty() and os.environ.get("TERM") != "dumb"
            except (AttributeError, ValueError):
                tty = False
        self.tty, self.drawn, self.n = tty, False, 0

    def line(self, text: str) -> None:
        if not self.tty:
            return
        self.n += 1
        cols = shutil.get_terminal_size((100, 20)).columns
        self.stream.write("\r\x1b[K" + fit_width(f"{self.SPIN[self.n % len(self.SPIN)]} {text}", max(20, cols - 1)))
        self.stream.flush()
        self.drawn = True

    def log(self, text: str) -> None:
        if self.tty and self.drawn:
            self.stream.write("\r\x1b[K")
        self.stream.write(text + "\n")
        self.stream.flush()
        self.drawn = False

    def close(self) -> None:
        if self.tty and self.drawn:
            self.stream.write("\r\x1b[K")
            self.stream.flush()
        self.drawn = False


def open_paths(paths: list[str]) -> None:
    """--open: 결과를 기본 프로그램(xdg-open, macOS open)으로 연다. 여럿이면 폴더를 연다."""
    if not paths:
        return
    target = paths[0] if len(paths) == 1 else str(Path(paths[0]).parent)
    opener = shutil.which("open") if sys.platform == "darwin" else shutil.which("xdg-open")
    if not opener:
        print(f"열 프로그램(xdg-open)이 없다. 직접 열기: {target}", file=sys.stderr)
        return
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(f"화면이 없는 곳(SSH 등)이라 열지 못했다. PC 로 받아서 열기: {target}", file=sys.stderr)
        return
    subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"여는 중: {target}", file=sys.stderr)


def run_jobs(a, jobs: list[Job], out: str | None = None) -> None:
    """진행 상황은 stderr, 결과 mp4 경로만 stdout (out=$(h3video gen ...) 로 받을 수 있게)."""
    store, t0 = execute_jobs(a, jobs)
    failed, paths = 0, []
    for job in jobs:
        jb = store.get(job.id)
        if jb.status == "completed":
            paths.append(copy_out(jb.output, out, many=len(jobs) > 1, job_id=job.id))
        else:
            failed += 1
            print(f"실패 {job.id}: {jb.error}", file=sys.stderr)
            hint = HN.explain_error(jb.error, jb.task)
            if hint and "원래 메시지" not in hint:
                print(f"  → {hint}", file=sys.stderr)
    print(f"끝: {len(jobs) - failed}/{len(jobs)}개 완료, {fmt_secs(time.time() - t0)}" + (". 결과 파일:" if paths else ""),
          file=sys.stderr, flush=True)
    for path in paths:
        print(path, flush=True)
    if getattr(a, "open", False):
        open_paths(paths)
    if failed:
        print(f"다시 하기: 같은 명령을 다시 실행 · 기록: h3video show {jobs[-1].id}", file=sys.stderr)
        sys.exit(1)


def execute_jobs(a, jobs: list[Job], on_tick=None, resume: str | None = None) -> tuple[JobStore, float]:
    """작업들을 서버에 보내고 다 끝날 때까지 진행 상황을 stderr 에 쓴다. (기록, 시작 시각)을 돌려준다.
    터미널이면 한 줄(경과·단계·장면 i/n)을 계속 고쳐 쓰고, 아니면 바뀔 때만 시각과 함께 한 줄씩 쓴다."""
    for job in jobs:
        validate_job(job)
    needs_ref = any(j.task == "ref2va" for j in jobs)
    preflight(a, needs_ref)
    if any(j.task != "ref2va" for j in jobs) and needs_ref:
        preflight(a, False)
    store = JobStore(Path(a.output_dir))
    w = Worker(store, H3Client(a.endpoint), H3Client(a.ref_endpoint), inbox_dir=a.inbox_dir, poll=a.poll)
    for job in jobs:   # 서버 GPU 에 한 번에 안 들어가는 길이는 장면으로 나눠 이어 붙인다 (OOM 전에)
        before = len(job.scenes)
        m = fit_to_server(job, w.ref_client if job.task == "ref2va" else w.client)
        if m:
            validate_job(job)
            if len(job.scenes) != before or m < spec.DURATION_MAX:
                print(f"  이 서버 GPU 에서 한 장면은 최대 {m}초 → {job.total_seconds}초를 장면 {len(job.scenes)}개"
                      f" {[s.duration for s in job.scenes]}로 만들어 이어 붙인다", file=sys.stderr)
    for job in jobs:
        w.enqueue(job)
        print(f"job {job.id} 등록: {job.total_seconds}초, {job.aspect_ratio}, 시드 {job.seed}" + (f", {job.title}" if job.title else ""), file=sys.stderr)
    w.start()
    prog = Progress()
    t0, last = time.time(), {}
    try:
        while True:
            time.sleep(0.5 if prog.tty else 1)
            pending, live = 0, None
            for k, job in enumerate(jobs):
                jb = store.get(job.id)
                if jb.status not in ("completed", "failed"):
                    pending += 1
                    if live is None and jb.status == "running":
                        live = (k, jb)
                line = scene_line(jb)
                if line != last.get(job.id) and (jb.status != "pending" or job.id not in last):
                    tag = f"{job.id[-6:]} " if len(jobs) > 1 else ""
                    if not prog.tty:
                        print(f"  [{time.strftime('%H:%M:%S')}] {tag}{line}  (경과 {fmt_secs(time.time() - t0)})", file=sys.stderr, flush=True)
                    elif jb.status in ("completed", "failed"):
                        prog.log(f"  {'✓' if jb.status == 'completed' else '✗'} {tag}{STATUS_KO[jb.status]}  (경과 {fmt_secs(time.time() - t0)})")
                    last[job.id] = line
            if prog.tty and pending:
                k, jb = live if live else (None, None)
                where = f"작업 {k + 1}/{len(jobs)} · " if jb is not None and len(jobs) > 1 else ""
                what = compact_status(jb) if jb is not None else "서버 차례를 기다리는 중"
                prog.line(f"경과 {fmt_secs(time.time() - t0)} · {where}{what}   (멈추기 Ctrl+C)")
            if on_tick:
                on_tick(store)
            if not pending:
                break
    except KeyboardInterrupt:
        prog.close()
        interrupted(store, jobs, resume)
        sys.exit(130)
    prog.close()
    return store, t0


def interrupted(store: JobStore, jobs: list[Job], resume: str | None = None) -> None:
    print("\n중단했다 (Ctrl+C). 이 터미널의 작업 처리는 멈췄다.", file=sys.stderr)
    on_server = False
    for job in jobs:
        jb = store.get(job.id)
        for sc in jb.scenes:
            if sc.video_id and sc.status not in ("completed", "failed"):
                on_server = True
                ref = " --ref" if sc.task == "ref2va" else ""
                print(f"  서버에서는 장면 {sc.index + 1}({sc.video_id})이 계속 만들어질 수 있다. 끝난 뒤 받기: "
                      f"h3video fetch {sc.video_id}{ref} -o scene.mp4", file=sys.stderr)
        if jb.status not in ("completed", "failed"):
            jb.status, jb.error, jb.finished = "failed", "사용자가 중단함 (Ctrl+C)", time.time()
            store.save(jb)
    if resume:
        print(f"  이어서 하기 (끝난 장면은 두고 나머지만): {resume}", file=sys.stderr)
    elif not on_server:
        print("  다시 하려면 같은 명령을 다시 실행한다", file=sys.stderr)
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
                   task="ref2va" if refs else None, raw=getattr(a, "raw", False),
                   short_edge=getattr(a, "size", spec.SHORT_EDGE_DEFAULT))


# ---------- commands ----------
def cmd_spec(a):
    print(spec.summary())


def cmd_plan(a):
    scenes = spec.plan_scenes(a.seconds, a.scene_seconds)
    print(f"{a.seconds}초 → 장면 {len(scenes)}개: {scenes} (첫 장면 {'fl2va' if a.first else 't2va'}, 이후 fl2va 체인)")


def given(a, key: str) -> bool:
    """이 설정을 명령 옵션으로 직접 줬는지."""
    return key in getattr(a, "_given", set())


def source_of(a, key: str) -> str:
    return f"옵션 {C.KEYS[key][3]}" if given(a, key) else C.resolve(key)[1]


def server_report(a, kind: str) -> bool:
    """서버 하나: OK/실패 한 줄, 실패면 바로 할 일."""
    key = "endpoint" if kind == "fl2va" else "ref-endpoint"
    ep = a.endpoint if kind == "fl2va" else a.ref_endpoint
    ok = H3Client(ep, timeout=5).healthy()
    name = f"{HN.SERVER_NAME[kind]} ({kind})"
    print(f"{'OK  ' if ok else '실패'}  {name}{' ' * max(1, 25 - text_width(name))}{ep}   ({source_of(a, key)})")
    if not ok:
        print(f"      → 서버 켜기 (클러스터): {HN.up_command(kind)}      켜졌는지: bash scripts/status.sh")
        if HN.is_local(ep):
            print(f"      → PC 에서 쓸 때는 터널: {HN.tunnel_command(ep)}")
        print(f"      → 주소가 다르면 한 번 저장: h3video config set {key} http://주소:포트   (또는 {C.KEYS[key][0]})")
        if kind == "ref2va":
            print("      (참고 자료 --image/--video/--audio 를 안 쓰면 꺼져 있어도 된다)")
    return ok


def cmd_health(a):
    ok_main = server_report(a, "fl2va")
    server_report(a, "ref2va")
    if not ok_main:
        sys.exit(1)


def cmd_doctor(a):
    """서버·결과 폴더·ffmpeg·설정을 한 번에 보고, 안 되는 것마다 할 일을 알려 준다."""
    bad = 0
    print("서버")
    ok_main = server_report(a, "fl2va")
    bad += not ok_main
    if ok_main:
        m = H3Client(a.endpoint).max_seconds("16:9", spec.SHORT_EDGE_DEFAULT, 1, timeout=5)
        print(f"      한 장면 최대 {m}초 (16:9·768 기준, 더 길면 나눠 이어 붙인다)" if m else
              f"      한 장면 최대: 서버가 알려 주지 않는다 (옛 서버) → {spec.DURATION_MAX}초 기준으로 나눈다")
    server_report(a, "ref2va")
    print("\n이 컴퓨터")
    out = Path(a.output_dir).expanduser()
    try:
        out.mkdir(parents=True, exist_ok=True)
        t = out / f".doctor-{os.getpid()}"
        t.write_text("ok")
        t.unlink()
        print(f"OK    결과 폴더       {out.resolve()}   ({source_of(a, 'output-dir')})")
    except OSError as e:
        bad += 1
        print(f"실패  결과 폴더       {out}: {e.strerror or e}")
        print("      → 쓸 수 있는 폴더로: h3video config set output-dir ~/videos   (또는 --output-dir, H3_OUTPUT_DIR)")
    ff = shutil.which("ffmpeg")
    if ff:
        print(f"OK    ffmpeg          {ff}")
    else:
        try:
            import av  # noqa: F401
            print("OK    ffmpeg          없지만 PyAV 로 대신한다")
        except ImportError:
            print("주의  ffmpeg          없음 → 15초보다 긴 영상(장면 이어 붙이기)을 못 만든다")
            print("      → sudo apt install ffmpeg, 또는 클러스터에서 source scripts/cluster_env.sh (PyAV)")
    if a.inbox_dir:
        inbox = Path(a.inbox_dir).expanduser()
        print(f"{'OK  ' if inbox.is_dir() else '주의'}  공유 폴더       {inbox}   ({source_of(a, 'inbox-dir')})"
              + ("" if inbox.is_dir() else " — 없음 (처음 쓸 때 만든다)"))
    cp = C.path()
    print(f"정보  설정 파일       {cp} ({'있음' if cp.is_file() else '없음 — 필요하면 h3video config set ...'})")
    print("\n" + ("전부 괜찮다. 만들기: h3video \"프롬프트\" -s 8" if not bad else f"안 되는 것 {bad}개 — 위의 → 를 따라 하고 다시 h3video doctor"))
    if bad:
        sys.exit(1)


def cmd_config(a):
    """h3video config [show|set|unset|path] [이름] [값]"""
    act = (a.action or "show").lower()
    acts = ("show", "set", "unset", "path")
    if act not in acts:
        near = difflib.get_close_matches(act, acts, n=1, cutoff=0.5)
        raise H3Error(f"config 다음에는 {', '.join(acts)} 중 하나" + (f" — 혹시: h3video config {near[0]}" if near else ""))
    if act == "path":
        print(C.path())
        return
    if act == "show":
        cfg, cp = C.load(), C.path()
        print(f"설정 파일: {cp} ({'있음' if cp.is_file() else '아직 없음'})")
        for key, (env, _default, desc, _flag) in C.KEYS.items():
            val, src = C.resolve(key, cfg)
            print(f"  {key:<13} {val or '(없음)'}   ← {src} · {desc}")
            if src.startswith("환경 변수") and cfg.get(key):
                print(f"  {'':<13} (설정 파일 값 {cfg[key]} 은 환경 변수에 가려 쓰이지 않는다)")
        for k in cfg:
            if k not in C.KEYS:
                print(f"  {k:<13} {C.masked(k, cfg[k])}   (h3video 가 쓰지 않는 이름)")
        print("우선순위: 명령 옵션 > 환경 변수 > 설정 파일 > 기본값")
        print("바꾸기: h3video config set endpoint http://127.0.0.1:30010   ·   지우기: h3video config unset endpoint")
        return
    if not a.key:
        raise H3Error(f"이름이 필요하다: h3video config {act} endpoint ...  (쓸 수 있는 것: {', '.join(C.KEYS)})")
    key = C.norm_key(a.key)
    cfg = C.load()
    if act == "set":
        if not a.value:
            raise H3Error(f"값이 필요하다: h3video config set {key} <값>")
        cfg[key] = C.check_value(key, a.value)
        print(f"저장했다: {key} = {cfg[key]}   ({C.save(cfg)})")
        env = C.KEYS[key][0]
        if os.environ.get(env):
            print(f"  주의: 환경 변수 {env}={os.environ[env]} 이 있어 그 값이 먼저 쓰인다 (unset {env} 하면 이 값)")
        return
    if key in cfg:
        del cfg[key]
        C.save(cfg)
        print(f"지웠다: {key} → 이제 {C.resolve(key, cfg)[1]} 값 {C.resolve(key, cfg)[0] or '(없음)'}")
    else:
        print(f"설정 파일에 {key} 가 없다 (지금 값은 {C.resolve(key, cfg)[1]})")


def refs_of(a) -> list[dict]:
    return [{"type": t, "path": p} for t in ("image", "video", "audio") for p in getattr(a, t, None) or []]


def cmd_gen(a):
    """글·첫/끝 프레임이면 fl2va, --image/--video/--audio 를 주면 ref2va 로 알아서 보낸다."""
    refs = refs_of(a)
    if refs and (a.first or a.last):
        raise H3Error("--first/--last(그 그림이 실제 첫·끝 장면)와 --image/--video/--audio(참고 자료)는 같이 쓸 수 없다. "
                      "둘은 다른 모델(fl2va / ref2va)이다")
    job = job_from_args(a, read_prompt(a), refs or None)
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
          f"고쳐서 쓰려면 파일로 저장해 gen 파일 --raw", file=sys.stderr)


BATCH_KEYS = {"seconds", "ratio", "seed", "title", "first", "last", "negative", "scene-seconds", "steps",
              "soundscape", "music", "ir", "raw", "size", "image", "video", "audio"}


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
                if attr in ("seconds", "scene_seconds", "steps", "size"):
                    v = int(v)
                elif attr == "seed":
                    v = seed_arg(v)
                elif attr in ("ir", "raw"):
                    v = v.lower() in ("1", "y", "yes", "true", "on", "예")
                elif attr == "size" and v not in (512, 576, 640, 704, 768):
                    raise H3Error(f"size 는 512·576·640·704·768 중 하나: {v}")
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


def cmd_json(a):
    """JSON 하나 + 그림들 → 장면마다 영상 → 쪽 순서대로 이어 붙인 영상 하나. 장면 수·길이는 JSON 에서 정한다."""
    from . import story as ST
    from . import storyrun as SR
    root = Path(a.output_dir)
    if a.resume:
        d = SR.find_story_dir(root, a.resume)
        state = SR.load_state(d)
        print(f"이어 하기: {d}", file=sys.stderr)
    else:
        if not a.file:
            raise H3Error("JSON 파일이 필요하다: h3video json 이야기.json [그림들·폴더]  (이어 하기는 --resume last)")
        story = ST.load_story_file(a.file, a.images, narration=not a.no_narration, ratio=a.ratio, seed=a.seed)
        print(ST.describe(story), file=sys.stderr)
        if a.list:
            for c in story.clips:
                print(f"\n[{c.id}] {c.label} · {c.seconds}초 · {Path(c.image).name if c.image else '그림 없음'}\n{c.prompt}")
            return
        params = {"size": a.size, "steps": a.steps, "negative": a.negative, "raw": a.raw, "narration": not a.no_narration}
        state = SR.initial_state(story, params)
        d = None
    only = {x.strip() for x in a.only.split(",") if x.strip()} if a.only else None
    if only and not only <= {c["id"] for c in state["clips"]}:
        raise H3Error(f"없는 장면: {', '.join(sorted(only - {c['id'] for c in state['clips']}))} (목록: --list)")
    jobs = SR.jobs_for(state, only)
    if a.dry_run:
        for job in jobs:
            preview(job)
        return
    if not jobs:
        print("다시 만들 장면이 없다", file=sys.stderr)
    if d is None:
        d = SR.new_story_dir(root)
    SR.save_state(d, state)
    print(f"장면 {len(jobs)}개 만들기 → 기록 {d / SR.STATE}", file=sys.stderr)
    if jobs:
        resume = f"h3video json --resume {d.name}" + (f" --output-dir {a.output_dir}" if given(a, "output-dir") else "")
        store, t0 = execute_jobs(a, jobs, on_tick=lambda st: SR.refresh(d, state, st), resume=resume)
    else:
        store, t0 = JobStore(root), time.time()
    state = SR.refresh(d, state, store)
    s = SR.summary(state)
    if state.get("output"):
        print(f"끝: 장면 {s['total']}개 {s['seconds']}초를 이어 붙였다, {fmt_secs(time.time() - t0)}. 결과 파일:", file=sys.stderr, flush=True)
        path = copy_out(state["output"], a.out)
        print(path, flush=True)
        if getattr(a, "open", False):
            open_paths([path])
        return
    for c in state["clips"]:
        if c.get("error"):
            print(f"실패 {c['label']}: {c['error']}", file=sys.stderr)
    print(f"장면 {s['done']}/{s['total']}개 완료. 실패한 장면만 다시: h3video json --resume {d.name}", file=sys.stderr)
    sys.exit(1)


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
ERR_KO = [
    (r"^the following arguments are required: (.*)$", r"꼭 필요한 값이 빠졌다: \1"),
    (r"^unrecognized arguments: (.*)$", r"모르는 옵션이나 값: \1"),
    (r"^argument (\S+): invalid choice: (.*?) \(choose from (.*)\)$", r"\1 에 \2 는 쓸 수 없다. 고를 수 있는 것: \3"),
    (r"^argument (\S+): expected one argument$", r"\1 뒤에 값이 하나 필요하다"),
    (r"^argument (\S+): expected at least one argument$", r"\1 뒤에 값이 필요하다"),
    (r"^argument (\S+): invalid int value: (.*)$", r"\1 은 정수여야 한다: \2"),
    (r"^argument (\S+): invalid float value: (.*)$", r"\1 은 숫자여야 한다: \2"),
    (r"^ambiguous option: (\S+) could match (.*)$", r"\1 이 여러 옵션과 겹친다: \2 (끝까지 써 주세요)"),
    (r"^argument (\S+): not allowed with argument (\S+)$", r"\1 과 \2 는 같이 쓸 수 없다"),
    (r"^argument (\S+): ignored explicit argument (.*)$", r"\1 은 값을 받지 않는다: \2"),
    (r"^argument (\S+): (.*)$", r"\1: \2"),
]


def ko_error(message: str) -> str:
    for pat, repl in ERR_KO:
        if re.match(pat, message):
            return re.sub(pat, repl, message)
    return message


class KoFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        return super().add_usage(usage, actions, groups, "사용법: " if prefix is None else prefix)


class KoParser(argparse.ArgumentParser):
    """도움말·오류를 한국어로. 모르는 옵션은 비슷한 옵션을 알려 준다."""

    def __init__(self, *args, **kw):
        kw.setdefault("formatter_class", KoFormatter)
        kw["add_help"] = False
        super().__init__(*args, **kw)
        self._positionals.title = "인자"
        self._optionals.title = "옵션"
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="이 도움말")

    def all_options(self) -> list[str]:
        opts = [o for act in self._actions for o in act.option_strings]
        for act in self._actions:
            if isinstance(act, argparse._SubParsersAction):
                for sp in act.choices.values():
                    opts += [o for a2 in sp._actions for o in a2.option_strings]
        return sorted(set(opts))

    def error(self, message):
        msg = ko_error(message)
        unknown = re.findall(r"(?<!\S)(--?[\w-]+)", message) if message.startswith("unrecognized") else []
        near = []
        for u in unknown:
            m = difflib.get_close_matches(u.split("=")[0], self.all_options(), n=1, cutoff=0.6)
            if m:
                near.append(f"{u} → {m[0]}")
        self.print_usage(sys.stderr)
        self.exit(2, f"오류: {msg}\n" + (f"혹시: {', '.join(near)}\n" if near else "") + f"도움말: {self.prog} --help\n")


class TopParser(KoParser):
    def format_help(self):
        out = ["h3video — MiniMax-H3 로 글·그림에서 소리까지 있는 영상 만들기", "",
               "사용법: h3video <명령> [옵션]",
               "        명령 없이 써도 된다: h3video \"프롬프트\" -s 8 · h3video 사진.png \"프롬프트\" · h3video 이야기.json 그림/", ""]
        for group, cmds in COMMAND_GROUPS:
            out.append(group)
            out.append(rows(cmds))
            out.append("")
        out += ["예:", rows(EXAMPLES), "", "공통 옵션 (명령 앞뒤 어디에 써도 된다. 한 번 저장: h3video config set ...)"]
        opts = [(f"{flag} {'URL' if 'endpoint' in key else 'DIR'}", f"{desc} ({env}, 설정 이름 {key})")
                for key, (env, default, desc, flag) in C.KEYS.items()]
        opts += [("--poll SEC", "상태 확인 간격 (기본 3)"), ("-h, --help", "도움말 (명령마다: h3video gen --help)"), ("--version", "버전")]
        out += [rows(opts), "", "명령마다 자세히: h3video <명령> --help"]
        return "\n".join(out) + "\n"


def add_global(p, top: bool) -> None:
    """공통 옵션. 하위 명령에도 달아 두어 `h3video gen ... --endpoint X` 처럼 뒤에 써도 된다.
    기본값: 환경 변수 > 설정 파일(h3video config) > 내장 기본값. 옵션으로 주면 그것이 먼저다."""
    S = argparse.SUPPRESS
    cfg = C.load() if top else {}
    d = (lambda k: C.resolve(k, cfg)[0]) if top else (lambda k: S)
    p.add_argument("--endpoint", default=d("endpoint"), help="글·그림(fl2va) 서버 (H3_ENDPOINT)" if top else S)
    p.add_argument("--ref-endpoint", default=d("ref-endpoint"), help="참고 자료(ref2va) 서버 (H3_REF_ENDPOINT)" if top else S)
    p.add_argument("--output-dir", default=d("output-dir"), help="결과 폴더 (H3_OUTPUT_DIR)" if top else S)
    p.add_argument("--inbox-dir", default=d("inbox-dir"), help="서버가 file:// 로 읽는 공유 폴더 (H3_INBOX_DIR)" if top else S)
    p.add_argument("--poll", type=float, default=3.0 if top else S, help="상태 확인 간격(초)" if top else S)


def add_video_opts(p) -> None:
    g = p.add_argument_group("길이·화면")
    g.add_argument("-s", "--seconds", type=int, default=8, metavar="SEC", help=f"총 길이(초, 최소 {spec.DURATION_MIN}, 기본 8). 서버 한도보다 길면 장면으로 나눠 이어 붙인다")
    g.add_argument("-r", "--ratio", default="16:9", choices=spec.ASPECT_RATIOS, metavar="RATIO",
                   help="화면비: " + ", ".join(spec.ASPECT_RATIOS) + " (기본 16:9, auto 는 첫 그림 비율)")
    g.add_argument("--size", type=int, default=spec.SHORT_EDGE_DEFAULT, choices=[512, 576, 640, 704, 768], metavar="PX",
                   help="짧은 변 512·576·640·704·768 (기본 768 = 1344×768). 576 이면 메모리·시간이 약 40%% 준다")
    g.add_argument("--scene-seconds", type=int, default=10, metavar="SEC", help="이어 붙일 때 장면 하나 길이 (5~15, 기본 10)")
    g = p.add_argument_group("결과")
    g.add_argument("-t", "--title", metavar="TEXT", help="결과 mp4 이름")
    g.add_argument("-o", "--out", metavar="PATH", help="결과를 여기로도 복사 (파일 경로, 또는 / 로 끝나는 폴더)")
    g.add_argument("--open", action="store_true", help="끝나면 결과를 기본 플레이어로 연다 (xdg-open)")
    g.add_argument("--dry-run", action="store_true", help="서버에 보내지 않고 장면 나누기와 요청 JSON 만 보기")
    g = p.add_argument_group("더 자세히")
    g.add_argument("--seed", type=seed_arg, default=0, metavar="N", help="정수 또는 random (기본 0: 같은 프롬프트면 같은 결과)")
    g.add_argument("--steps", type=int, metavar="N", help="디노이징 스텝 (기본: 서버 기본값 50, 30 이면 빠르고 거칠다)")
    g.add_argument("-n", "--negative", metavar="TEXT", help="넣지 않을 것 (네거티브 프롬프트)")
    g.add_argument("--raw", action="store_true",
                   help="서버의 프롬프트 다듬기를 끄고 쓴 그대로 보낸다 (Diffusers 엔진은 기본으로 공식 형식으로 다듬는다)")
    g.add_argument("--ir", action="store_true", help="3단 필드 이름만 붙여 감싸기 (다듬기 없이 직접 쓴 내용 그대로)")
    g.add_argument("--soundscape", metavar="TEXT", help="--ir 일 때 환경음 설명")
    g.add_argument("--music", metavar="TEXT", help="--ir 일 때 배경음악 설명")


def add_prompt_opts(p, what: str = "프롬프트 글, 또는 프롬프트 파일 이름(있으면 그 내용). 생략하면 표준입력") -> None:
    g = p.add_argument_group("프롬프트")
    g.add_argument("prompt", nargs="?", help=what)
    g.add_argument("-f", "--prompt-file", metavar="FILE", help="프롬프트 파일 (- 는 표준입력)")


def add_media_opts(p, first: bool = True, refs: bool = True) -> None:
    g = p.add_argument_group("그림·참고 자료")
    if first:
        g.add_argument("--first", metavar="IMG", help="첫 장면 그림 (그 그림에서 시작)")
        g.add_argument("--last", metavar="IMG", help="끝 장면 그림 (그 그림으로 끝, 한 장면일 때)")
    if refs:
        g.add_argument("--image", action="append", default=[], metavar="IMG",
                       help=f"참고 사진 (최대 {spec.REF_LIMITS['image']}, 여러 번) → ref2va 서버")
        g.add_argument("--video", action="append", default=[], metavar="VIDEO", help=f"참고 영상 (최대 {spec.REF_LIMITS['video']}, 2~15초)")
        g.add_argument("--audio", action="append", default=[], metavar="AUDIO", help=f"참고 소리 (최대 {spec.REF_LIMITS['audio']}, 2~15초)")


def build_parser() -> argparse.ArgumentParser:
    ap = TopParser(prog="h3video", description="MiniMax-H3 영상 생성 클라이언트")
    ap.add_argument("--version", action="version", version="h3video 0.1.0")
    add_global(ap, True)
    sub = ap.add_subparsers(dest="cmd", metavar="명령", parser_class=KoParser)

    def cmd(name, fn, help_=None, **kw):
        help_ = help_ or COMMAND_HELP[name]
        ex = CMD_EXAMPLES.get(name)
        p = sub.add_parser(name, help=help_, description=help_, epilog=("예:\n" + rows(ex)) if ex else None, **kw)
        add_global(p, False)
        p.set_defaults(fn=fn)
        return p

    cmd("spec", cmd_spec)
    cmd("health", cmd_health, "서버 확인: OK/실패와 할 일 (글·그림 서버가 안 되면 종료 코드 1)")
    cmd("doctor", cmd_doctor)
    p = cmd("config", cmd_config)
    p.add_argument("action", nargs="?", default="show", help="show(기본) · set · unset · path")
    p.add_argument("key", nargs="?", help="endpoint · ref-endpoint · output-dir · inbox-dir")
    p.add_argument("value", nargs="?", help="저장할 값")
    p = cmd("plan", cmd_plan)
    p.add_argument("seconds", type=int, help="총 길이(초)"); p.add_argument("--scene-seconds", type=int, default=10)
    p.add_argument("--first", help="첫 그림 (있으면 첫 장면도 fl2va)")

    p = cmd("gen", cmd_gen)
    add_prompt_opts(p)
    add_media_opts(p)
    add_video_opts(p)

    p = cmd("ref", cmd_ref, "참고 자료(사진·영상·소리) → 영상 (ref2va). gen --image 와 같다")
    add_prompt_opts(p, "프롬프트. '1번 사진'처럼 번호로 참고 자료를 가리킨다")
    add_media_opts(p, first=False)
    add_video_opts(p)

    p = cmd("ir", cmd_ir, "다듬은 프롬프트만 보기 (Diffusers 엔진: 짧은 요청 → H3 공식 형식, 생성 안 함)")
    add_prompt_opts(p, "프롬프트. 생략하면 -f 파일이나 표준입력")
    add_media_opts(p)
    add_video_opts(p)

    p = cmd("batch", cmd_batch, "파일의 여러 프롬프트를 차례로 (--- 줄로 구분, 블록 맨 위 'seconds: 10' 같은 줄은 그 영상 옵션)")
    p.add_argument("file", help="프롬프트 파일 (- 는 표준입력)")
    add_video_opts(p)

    p = cmd("json", cmd_json, "JSON 하나 + 그림들로 한 번에: 장면마다 영상을 만들어 이어 붙인다 (장면 수·길이는 JSON 에서, -s 불필요)")
    p.add_argument("file", nargs="?", help="동화책 콘티 JSON, 동화책 만들기 book.json, 또는 {\"clips\": [{\"prompt\", \"image\", \"text\", \"seconds\"}]}")
    p.add_argument("images", nargs="*", help="첫 프레임 그림 파일이나 폴더 (이름 page-03·03 → 3쪽, cover → 표지, 나머지는 순서대로)")
    g = p.add_argument_group("장면")
    g.add_argument("--list", action="store_true", help="만들지 않고 장면·길이·그림·프롬프트만 보기")
    g.add_argument("--only", help="일부 장면만 (예: page-02,page-05 — --list 로 id 확인)")
    g.add_argument("--resume", help="그 JSON 작업 폴더에서 실패한·안 된 장면만 다시 하고 이어 붙이기 (폴더, 이름, last)")
    g.add_argument("--no-narration", action="store_true", help="쪽 글을 내레이션으로 읽게 하지 않기 (길이는 그대로 글 읽는 시간)")
    g = p.add_argument_group("화면·결과")
    g.add_argument("-r", "--ratio", choices=spec.ASPECT_RATIOS, metavar="RATIO", help="화면비 (기본: JSON 판형, 없으면 그림 비율 auto)")
    g.add_argument("--size", type=int, default=spec.SHORT_EDGE_DEFAULT, choices=[512, 576, 640, 704, 768], metavar="PX", help="짧은 변 (기본 768)")
    g.add_argument("-o", "--out", help="이어 붙인 영상을 여기로도 복사")
    g.add_argument("--open", action="store_true", help="끝나면 이어 붙인 영상을 기본 플레이어로 연다 (xdg-open)")
    g.add_argument("--dry-run", action="store_true", help="서버에 보내지 않고 요청만 출력")
    g = p.add_argument_group("더 자세히")
    g.add_argument("--seed", type=seed_arg, default=0, help="첫 장면 시드 (장면마다 1씩 더함, random 이면 무작위)")
    g.add_argument("--steps", type=int, help="디노이징 스텝 (기본: 서버 기본값)")
    g.add_argument("-n", "--negative", help="넣지 않을 것")
    g.add_argument("--raw", action="store_true", help="서버의 프롬프트 다듬기 끄기")

    p = cmd("jobs", cmd_jobs)
    p.add_argument("--limit", type=int, default=20, help="몇 개까지 (기본 20)"); p.add_argument("--json", action="store_true", help="JSON 으로")
    p = cmd("show", cmd_show)
    p.add_argument("job", nargs="?", default="last", help="작업 id, id 앞부분, last(기본)"); p.add_argument("--json", action="store_true", help="JSON 으로")
    p = cmd("status", cmd_status)
    p.add_argument("video_id"); p.add_argument("--ref", action="store_true", help="ref2va 서버에 묻기")
    p = cmd("fetch", cmd_fetch)
    p.add_argument("video_id"); p.add_argument("-o", "--out", help="저장할 파일 (기본 <video_id>.mp4)")
    p.add_argument("--ref", action="store_true", help="ref2va 서버에서 받기")
    p = cmd("web", cmd_web)
    p.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 (이 컴퓨터에서만)")
    p.add_argument("--port", type=int, default=int(os.environ.get("H3_WEB_PORT", 8790)), help="기본 8790 (H3_WEB_PORT)")
    p.add_argument("--cors-origin", default=None,
                   help="이 서버를 부를 수 있는 웹 출처(쉼표 구분, * 는 전부). 기본 끔. 환경변수 H3_CORS_ORIGIN")
    cmd("tui", cmd_tui)
    sub.add_parser("shorts", help=COMMAND_HELP["shorts"], add_help=False)
    return ap


def first_positional(argv: list[str]) -> int | None:
    """공통 옵션(--endpoint X 등)을 건너뛴 첫 인자의 위치."""
    i = 0
    while i < len(argv):
        t = argv[i]
        if t in GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if t.split("=", 1)[0] in GLOBAL_VALUE_OPTS and "=" in t:
            i += 1
            continue
        return i
    return None


class UnknownCommand(H3Error):
    pass


def route(argv: list[str]) -> tuple[list[str], str | None]:
    """명령 없이 쓴 것을 알아서 고친다. (고친 argv, 무엇으로 골랐는지 한 줄 | None)"""
    i = first_positional(argv)
    if i is None:
        return argv, None
    tok = argv[i]
    head, rest = argv[:i], argv[i + 1:]
    if tok in COMMANDS or tok in ("-h", "--help", "--version"):
        return argv, None
    if tok == "help":   # h3video help gen → h3video gen --help
        nxt = rest[0] if rest else None
        nxt = ALIASES.get(nxt, nxt)
        return (head + [nxt, "--help"], None) if nxt in COMMANDS and nxt != "shorts" else (head + ["--help"], None)
    if tok in ALIASES:
        cmd = ALIASES[tok]
        note = f"[자동] {tok} → h3video {cmd}" + (f" ({ALIAS_NOTE[tok]})" if tok in ALIAS_NOTE else "")
        return head + [cmd] + rest, note
    if tok.startswith("-"):
        return head + ["gen", tok] + rest, "[자동] 명령 없이 옵션부터 써서 h3video gen (영상 만들기)으로 실행한다"
    p = Path(tok).expanduser()
    low = tok.lower()
    if p.is_file():
        if low.endswith(".json"):
            return head + ["json", tok] + rest, "[자동] JSON 파일이라 h3video json (장면마다 만들어 이어 붙이기)으로 실행한다"
        if low.endswith(IMAGE_EXTS):
            extra, note = ["--first", tok], "[자동] 그림 파일이라 h3video gen --first (이 그림에서 시작)로 실행한다"
            if rest and Path(rest[0]).expanduser().is_file() and rest[0].lower().endswith(IMAGE_EXTS):
                extra += ["--last", rest[0]]
                rest = rest[1:]
                note = "[자동] 그림 두 장이라 h3video gen --first 첫 그림 --last 끝 그림으로 실행한다"
            return head + ["gen"] + extra + rest, note
        if low.endswith(VIDEO_EXTS) or low.endswith(AUDIO_EXTS):
            kind = "video" if low.endswith(VIDEO_EXTS) else "audio"
            return head + ["gen", f"--{kind}", tok] + rest, f"[자동] {'영상' if kind == 'video' else '소리'} 파일이라 h3video gen --{kind} (참고 자료)로 실행한다"
        return head + ["gen", tok] + rest, f"[자동] 파일 {tok} 을 프롬프트로 h3video gen 실행한다"
    if re.fullmatch(r"[A-Za-z][\w-]*", tok) and not looks_like_file(tok):
        near = difflib.get_close_matches(tok.lower(), COMMANDS + list(ALIASES), n=1, cutoff=0.5)
        sug = ALIASES.get(near[0], near[0]) if near else None
        raise UnknownCommand(f"'{tok}' 라는 명령은 없다." + (f" 혹시: h3video {sug}" if sug else "")
                             + f"\n  명령 목록: h3video --help   ·   영어 한 단어 프롬프트라면: h3video gen \"{tok}\"")
    return head + ["gen", tok] + rest, "[자동] 명령 대신 글을 줘서 h3video gen (글로 영상 만들기)으로 실행한다"


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
    if first_positional(argv) is None and not any(t in ("-h", "--help", "--version") for t in argv):
        print(quickstart())
        return
    try:
        argv, note = route(argv)
    except UnknownCommand as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(2)
    if note:
        print(note, file=sys.stderr)
    ap = build_parser()
    a, extra = ap.parse_known_args(argv)
    if extra:   # 모르는 옵션은 그 명령의 사용법과 함께 (비슷한 옵션도 알려 준다)
        subs = next((x.choices for x in ap._actions if isinstance(x, argparse._SubParsersAction)), {})
        (subs.get(getattr(a, "cmd", None)) or ap).error("unrecognized arguments: " + " ".join(extra))
    if not getattr(a, "fn", None):
        print(quickstart())
        return
    # 어떤 공통 옵션을 직접 줬는지 (doctor·config 가 '어디서 온 값'을 보여 준다)
    a._given = {k for k, v in C.KEYS.items() if any(t == v[3] or t.startswith(v[3] + "=") for t in argv)}
    try:
        a.fn(a)
    except H3Error as e:
        sys.exit(f"오류: {e}")
    except KeyboardInterrupt:
        print("\n중단했다 (Ctrl+C).", file=sys.stderr)
        sys.exit(130)
    except (FileNotFoundError, UnicodeDecodeError) as e:
        sys.exit(f"오류: {e}")


if __name__ == "__main__":
    main()
