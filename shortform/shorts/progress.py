"""CLI 진행 표시.

- 단계 줄: [1/5 검증] → [2/5 서버 연결] → [3/5 생성] → [4/5 다운로드] → [5/5 합성]
- 생성 중: 장면마다 한 줄(상태·진행률 막대·경과·예상 남은 시간). 진행률이 없으면 스피너+경과.
- TTY 면 줄을 제자리에서 다시 그리고, 아니면(파이프·로그 파일) 상태가 바뀔 때와 LOG_INTERVAL 초마다 한 줄씩 남긴다.
- --json 이면 모든 것을 줄 단위 JSON 이벤트로.
"""
from __future__ import annotations

import json
import os
import sys
import time

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STATE_KO = {"submitting": "요청 중", "queued": "대기열", "running": "생성 중", "done": "완료", "failed": "실패",
            "retry": "재시도", "downloaded": "받음"}


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "-"
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def bar(frac: float, width: int = 20) -> str:
    frac = max(0.0, min(1.0, frac))
    full = int(frac * width)
    return "[" + "#" * full + "-" * (width - full) + "]"


class Out:
    """사람이 읽는 출력과 --json(줄마다 JSON 이벤트) 출력."""

    def __init__(self, as_json: bool = False, stream=None, tty: bool | None = None, log_interval: float | None = None):
        self.as_json = as_json
        self.stream = stream
        self._tty = tty
        self.log_interval = log_interval if log_interval is not None else float(os.environ.get("SHORTS_LOG_INTERVAL", "15"))
        self._last = 0.0
        self.stages: list[str] = []
        self.stage_times: dict[str, float] = {}
        self._stage_name: str | None = None
        self._stage_t0 = 0.0
        self.t0 = time.monotonic()

    # 출력 대상은 호출 때마다 sys.stdout 을 본다(테스트의 redirect_stdout 과 맞추려고)
    @property
    def w(self):
        return self.stream or sys.stdout

    @property
    def tty(self) -> bool:
        if self._tty is not None:
            return self._tty
        if os.environ.get("SHORTS_NO_TTY"):
            return False
        try:
            return self.w.isatty()
        except (AttributeError, ValueError):
            return False

    def _print(self, line: str = ""):
        self.w.write(line + "\n")
        self.w.flush()

    def event(self, kind: str, msg: str = "", **data):
        if self.as_json:
            self._print(json.dumps({"event": kind, "message": msg, **data}, ensure_ascii=False))
        elif msg:
            self._print(msg)

    # ---------------- 단계 ----------------
    def plan_stages(self, names: list[str]):
        self.stages = names

    def stage(self, name: str, detail: str = ""):
        now = time.monotonic()
        if self._stage_name:
            self.stage_times[self._stage_name] = self.stage_times.get(self._stage_name, 0) + now - self._stage_t0
        self._stage_name, self._stage_t0 = name, now
        k = self.stages.index(name) + 1 if name in self.stages else 0
        total = len(self.stages)
        label = f"[{k}/{total} {name}]" if k else f"[{name}]"
        self.event("stage", f"{label} {detail}".rstrip(), stage=k, total=total, name=name, detail=detail)

    def end_stages(self):
        if self._stage_name:
            now = time.monotonic()
            self.stage_times[self._stage_name] = self.stage_times.get(self._stage_name, 0) + now - self._stage_t0
            self._stage_name = None

    # ---------------- 한 줄 진행(합성 등) ----------------
    def progress(self, stage: str, frac: float, extra: str = ""):
        now = time.monotonic()
        if self.as_json:
            if frac >= 1 or now - self._last > 0.5:
                self._last = now
                self._print(json.dumps({"event": "progress", "stage": stage, "progress": round(frac, 3), "message": extra},
                                       ensure_ascii=False))
            return
        if self.tty:
            if frac >= 1 or now - self._last > 0.2:
                self._last = now
                end = "\n" if frac >= 1 else ""
                self.w.write(f"\r\x1b[2K  {stage} {bar(frac, 24)} {frac * 100:5.1f}% {extra}{end}")
                self.w.flush()
        elif frac >= 1 or now - self._last > self.log_interval:
            self._last = now
            self._print(f"  {stage} {frac * 100:5.1f}% {extra}".rstrip())


class SceneBoard:
    """장면별 상태 줄. TTY 면 제자리 갱신, 아니면 상태 변화·주기 로그, JSON 이면 이벤트."""

    def __init__(self, out: Out, n: int):
        self.out, self.n = out, n
        self.rows: list[dict] = [{"state": "queued", "progress": None, "job_id": None, "t_seen": None, "t_run": None,
                                  "t_end": None, "task": "", "note": ""} for _ in range(n)]
        self.drawn = 0
        self.tick = 0
        self._last_log = time.monotonic()
        self._last_json: list[tuple] = [()] * n
        self._last_state: list[str | None] = [None] * n
        self.active = [True] * n

    def set(self, i: int, state: str | None = None, progress=None, has_progress: bool = False, note: str | None = None,
            job_id: str | None = None, task: str | None = None):
        r = self.rows[i]
        now = time.monotonic()
        if r["t_seen"] is None:
            r["t_seen"] = now
        if state:
            if state == "running" and r["t_run"] is None:
                r["t_run"] = now
            if state in ("done", "failed") and r["t_end"] is None:
                r["t_end"] = now
            r["state"] = state
        if has_progress:
            r["progress"] = progress
        if note is not None:
            r["note"] = note
        if job_id:
            r["job_id"] = job_id
        if task:
            r["task"] = task
        self._emit(i)

    def elapsed(self, i: int) -> float:
        r = self.rows[i]
        if r["t_seen"] is None:
            return 0.0
        return (r["t_end"] or time.monotonic()) - r["t_seen"]

    def eta(self, i: int) -> float | None:
        r = self.rows[i]
        p = r["progress"]
        if r["state"] != "running" or p is None or not (0.01 <= p < 1) or r["t_run"] is None:
            return None
        run = time.monotonic() - r["t_run"]
        return run * (1 - p) / p

    def line(self, i: int) -> str:
        r = self.rows[i]
        st = STATE_KO.get(r["state"], r["state"])
        head = f"  장면 {i + 1}/{self.n}  {st:<4}"
        if r["state"] == "done":
            body = f"{bar(1.0)} 100%  {fmt_time(self.elapsed(i))}"
        elif r["state"] == "failed":
            body = f"경과 {fmt_time(self.elapsed(i))}"
        elif r["progress"] is not None and r["state"] == "running":
            eta = self.eta(i)
            body = f"{bar(r['progress'])} {r['progress'] * 100:5.1f}%  경과 {fmt_time(self.elapsed(i))}"
            if eta is not None:
                body += f"  남은 약 {fmt_time(eta)}"
        else:
            spin = SPINNER[self.tick % len(SPINNER)] if self.out.tty else "…"
            body = f"{spin} 경과 {fmt_time(self.elapsed(i))}"
        tail = f"  ({r['job_id']})" if r["job_id"] else ""
        note = f"  {r['note']}" if r["note"] else ""
        return f"{head}  {body}{tail}{note}"

    def _emit(self, i: int):
        out = self.out
        r = self.rows[i]
        if out.as_json:
            key = (r["state"], None if r["progress"] is None else round(r["progress"], 3), r["note"])
            if key != self._last_json[i]:
                self._last_json[i] = key
                eta = self.eta(i)
                out._print(json.dumps({"event": "scene", "scene": i + 1, "total": self.n, "state": r["state"],
                                       "progress": r["progress"], "elapsed": round(self.elapsed(i), 1),
                                       "eta": None if eta is None else round(eta, 1), "job_id": r["job_id"],
                                       "note": r["note"] or None}, ensure_ascii=False))
            return
        if out.tty:
            return  # render() 가 그린다
        if r["state"] != self._last_state[i]:
            self._last_state[i] = r["state"]
            out._print(self.line(i))

    def render(self, force: bool = False):
        """TTY: 줄을 제자리에서 다시 그림. 그 밖: LOG_INTERVAL 마다 진행 중인 장면 한 줄씩."""
        out = self.out
        if out.as_json:
            return
        self.tick += 1
        if out.tty:
            w = out.w
            if self.drawn:
                w.write(f"\x1b[{self.drawn}F")
            for i in range(self.n):
                w.write("\x1b[2K" + self.line(i) + "\n")
            self.drawn = self.n
            w.flush()
            return
        now = time.monotonic()
        if force or now - self._last_log >= out.log_interval:
            self._last_log = now
            for i in range(self.n):
                if self.rows[i]["state"] in ("queued", "running", "retry", "submitting"):
                    out._print(self.line(i))

    def finish(self):
        if self.out.tty and not self.out.as_json:
            self.render()
        self.drawn = 0
