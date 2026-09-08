"""터미널 UI (curses, 표준 라이브러리). tmux 안에서 `h3video tui`.

키: n 새 작업(프롬프트는 $EDITOR 로 작성 — 한글 입력 안전) · p 한 줄 프롬프트 · f 파일에서 프롬프트
    ↑↓ 선택 · Enter/d 상세 · r 새로고침 · q 종료
"""
from __future__ import annotations

import curses
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import spec
from .client import H3Client
from .jobs import INBOX_DIR, OUTPUT_DIR, JobStore, Worker, new_job
from .client import H3Error

TEMPLATE = """# 아래에 영상 프롬프트를 쓰고 저장 후 종료하세요. '#' 로 시작하는 줄은 무시됩니다.
# 장면·카메라·피사체·동작·소리·음악을 구체적으로. 대사는 <d>[Korean] 대사</d> 형식.
# 예) 새벽 안개 낀 해운대, 드론이 바다 위를 낮게 날아 해변으로 접근. 파도와 갈매기, 잔잔한 피아노.

"""


def strip_template(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")).strip()


def bar(frac: float, width: int) -> str:
    n = max(0, min(width, int(round(frac * width))))
    return "█" * n + "░" * (width - n)


def job_progress(j: dict) -> float:
    sc = j.get("scenes") or []
    if not sc:
        return 1.0 if j["status"] == "completed" else 0.0
    done = sum(1 for s in sc if s["status"] == "completed")
    cur = next((s for s in sc if s["status"] in ("in_progress", "queued")), None)
    return (done + (cur["progress"] if cur else 0)) / len(sc)


def fmt_elapsed(s: float) -> str:
    s = int(s)
    return f"{s // 60}분 {s % 60:02d}초" if s >= 60 else f"{s}초"


class Tui:
    def __init__(self, endpoint: str, ref_endpoint: str, output_dir: Path, inbox_dir: str | None, poll: float):
        self.client, self.ref_client = H3Client(endpoint), H3Client(ref_endpoint)
        self.endpoint, self.ref_endpoint = endpoint, ref_endpoint
        self.store = JobStore(output_dir)
        self.worker = Worker(self.store, self.client, self.ref_client, inbox_dir=inbox_dir, poll=poll)
        self.worker.start()
        self.sel = 0
        self.msg = "n: 새 작업(에디터)  p: 한 줄 프롬프트  f: 파일  Enter: 상세  q: 종료"
        self.health = {"fl2va": None, "ref2va": None, "t": 0}
        self.defaults = {"seconds": "8", "ratio": "16:9", "seed": "0", "scene_seconds": "10", "first": "", "last": "", "title": ""}

    # ---------- 입력 ----------
    def ask(self, scr, label: str, default: str = "") -> str | None:
        """맨 아래 줄에서 한 줄 입력 (ASCII·숫자·경로용). ESC 취소."""
        h, w = scr.getmaxyx()
        buf = list(default)
        curses.curs_set(1); scr.nodelay(False)
        try:
            while True:
                scr.move(h - 1, 0); scr.clrtoeol()
                s = f"{label}: {''.join(buf)}"
                scr.addstr(h - 1, 0, s[: w - 1])
                scr.refresh()
                ch = scr.get_wch()
                if ch in ("\n", "\r"):
                    return "".join(buf)
                if ch == "\x1b":
                    return None
                if ch in ("\x7f", "\b") or ch == curses.KEY_BACKSPACE:
                    if buf:
                        buf.pop()
                elif isinstance(ch, str) and ch.isprintable():
                    buf.append(ch)
        finally:
            curses.curs_set(0); scr.nodelay(True)

    def edit_prompt(self, scr, initial: str = "") -> str | None:
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or (shutil.which("nano") and "nano") or "vi"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(TEMPLATE + initial)
            path = f.name
        curses.def_prog_mode(); curses.endwin()
        try:
            subprocess.call([*editor.split(), path])
        finally:
            curses.reset_prog_mode(); scr.clear(); scr.refresh()
        text = strip_template(Path(path).read_text(encoding="utf-8"))
        os.unlink(path)
        return text or None

    def new_job_flow(self, scr, prompt: str):
        d = self.defaults
        seconds = self.ask(scr, f"총 길이(초, 한 장면 {spec.DURATION_MIN}~{spec.DURATION_MAX}, 초과 시 체인)", d["seconds"])
        if seconds is None: return
        ratio = self.ask(scr, f"화면비 {'/'.join(spec.ASPECT_RATIOS)}", d["ratio"])
        if ratio is None: return
        seed = self.ask(scr, "시드", d["seed"])
        if seed is None: return
        first = self.ask(scr, "첫 프레임 이미지 경로(없으면 비움)", d["first"])
        if first is None: return
        last = self.ask(scr, "끝 프레임 이미지 경로(없으면 비움)", d["last"])
        if last is None: return
        scene = d["scene_seconds"]
        if int(seconds or 0) > spec.DURATION_MAX:
            scene = self.ask(scr, "장면 길이(초)", d["scene_seconds"]) or d["scene_seconds"]
        title = self.ask(scr, "제목(파일명, 비우면 프롬프트 앞부분)", d["title"])
        if title is None: return
        try:
            job = new_job(prompt, seconds=int(seconds), aspect_ratio=ratio.strip(), seed=int(seed or 0),
                          first_image=first.strip() or None, last_image=last.strip() or None,
                          scene_seconds=int(scene), title=title.strip())
        except (H3Error, ValueError) as e:
            self.msg = f"오류: {e}"; return
        d.update(seconds=seconds, ratio=ratio, seed=seed, scene_seconds=scene, first=first, last=last)
        self.worker.enqueue(job)
        self.msg = f"큐에 추가: {job.id} ({job.total_seconds}초, {len(spec.plan_scenes(job.total_seconds, job.scene_seconds))}장면)"
        self.sel = 0

    # ---------- 그리기 ----------
    def check_health(self):
        if time.time() - self.health["t"] > 10:
            self.health = {"fl2va": self.client.healthy(), "ref2va": self.ref_client.healthy(), "t": time.time()}

    def draw(self, scr, jobs: list[dict]):
        scr.erase()
        h, w = scr.getmaxyx()
        hs = lambda ok: "연결됨" if ok else ("확인 중" if ok is None else "응답 없음")  # noqa: E731
        head = (f" H3 Video  fl2va {hs(self.health['fl2va'])} ({self.endpoint})  ref2va {hs(self.health['ref2va'])}"
                f"  대기 {len(self.worker.queue)}  {'진행 ' + self.worker.current if self.worker.current else ''}")
        scr.attron(curses.A_REVERSE); scr.addstr(0, 0, head[: w - 1].ljust(w - 1)); scr.attroff(curses.A_REVERSE)
        scr.addstr(1, 0, f" 한 번 {spec.DURATION_MIN}~{spec.DURATION_MAX}초 · 768p {spec.FPS}fps · 스테레오 오디오 · 출력 {self.store.root}"[: w - 1])
        y = 3
        if not jobs:
            scr.addstr(y, 1, "작업 없음. n 을 눌러 새 작업을 만드세요.")
        bw = max(10, min(30, w - 60))
        for i, j in enumerate(jobs):
            if y >= h - 3:
                break
            frac = job_progress(j)
            st = j["status"]
            cur = next((s for s in j.get("scenes") or [] if s["status"] in ("in_progress", "queued")), None)
            detail = f"장면{cur['index'] + 1} {cur['status']} {int(cur['progress'] * 100)}%" if cur else st
            title = (j.get("title") or j["prompt"].replace("\n", " "))[:28]
            line = f"{'▶' if i == self.sel else ' '} {j['id'][-13:]} {title:<28} {j['total_seconds']:>3}초 {j['aspect_ratio']:<5} [{bar(frac, bw)}] {int(frac * 100):>3}% {detail} {fmt_elapsed(j['elapsed'])}"
            attr = curses.A_BOLD if i == self.sel else curses.A_NORMAL
            if st == "failed":
                attr |= curses.color_pair(1)
            elif st == "completed":
                attr |= curses.color_pair(2)
            try:
                scr.addstr(y, 0, line[: w - 1], attr)
            except curses.error:
                pass
            y += 1
        scr.addstr(h - 2, 0, self.msg[: w - 1])
        scr.refresh()

    def detail(self, scr, j: dict):
        scr.erase(); h, w = scr.getmaxyx(); y = 0
        lines = [f"작업 {j['id']}  상태 {j['status']}  {j['task']}  {j['total_seconds']}초  {j['aspect_ratio']}  seed {j['seed']}  경과 {fmt_elapsed(j['elapsed'])}",
                 f"출력: {j.get('output') or '-'}", ""]
        for s in j.get("scenes") or []:
            lines.append(f"  장면 {s['index'] + 1}: {s['duration']}초 {s['task']} {s['status']} {int(s['progress'] * 100)}% {s.get('video_id') or ''} {s.get('output') or ''}")
        if j.get("error"):
            lines += ["", "오류: " + j["error"]]
        lines += ["", "프롬프트:"] + j["prompt"].splitlines() + ["", "아무 키나 누르면 돌아갑니다."]
        for l in lines:
            if y >= h - 1: break
            try: scr.addstr(y, 0, l[: w - 1])
            except curses.error: pass
            y += 1
        scr.refresh(); scr.nodelay(False); scr.getch(); scr.nodelay(True)

    # ---------- 루프 ----------
    def run(self, scr):
        curses.curs_set(0); scr.nodelay(True); scr.keypad(True)
        curses.start_color(); curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED, -1); curses.init_pair(2, curses.COLOR_GREEN, -1)
        while True:
            self.check_health()
            jobs = self.store.list()
            self.sel = max(0, min(self.sel, len(jobs) - 1))
            self.draw(scr, jobs)
            try:
                ch = scr.get_wch()
            except curses.error:
                time.sleep(0.5); continue
            if ch in ("q", "Q"):
                if self.worker.current or self.worker.queue:
                    a = self.ask(scr, "진행 중인 작업이 있습니다. 종료하면 중단됩니다. 종료? (y/N)", "")
                    if (a or "").lower() != "y":
                        continue
                return
            if ch == "n":
                p = self.edit_prompt(scr)
                if p: self.new_job_flow(scr, p)
                else: self.msg = "프롬프트가 비어 취소"
            elif ch == "p":
                p = self.ask(scr, "프롬프트(한 줄)", "")
                if p: self.new_job_flow(scr, p)
            elif ch == "f":
                p = self.ask(scr, "프롬프트 파일 경로", "")
                if p and Path(p).expanduser().is_file():
                    self.new_job_flow(scr, Path(p).expanduser().read_text(encoding="utf-8").strip())
                elif p:
                    self.msg = f"파일 없음: {p}"
            elif ch in (curses.KEY_UP, "k"):
                self.sel = max(0, self.sel - 1)
            elif ch in (curses.KEY_DOWN, "j"):
                self.sel = min(len(jobs) - 1, self.sel + 1)
            elif ch in ("\n", "\r", "d", curses.KEY_ENTER) and jobs:
                self.detail(scr, jobs[self.sel])
            elif ch == "r":
                self.health["t"] = 0


def run(endpoint: str, ref_endpoint: str, output_dir: Path = OUTPUT_DIR, inbox_dir: str | None = INBOX_DIR, poll: float = 3.0):
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(Tui(endpoint, ref_endpoint, Path(output_dir), inbox_dir, poll).run)
