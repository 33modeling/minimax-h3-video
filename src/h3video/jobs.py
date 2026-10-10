"""작업 큐 — 웹 UI·CLI 공용. 단일 워커 스레드가 순서대로 처리하고 상태를 JSON 으로 남긴다.

한 작업(job) = 장면(scene) 1개 이상. 15초 초과 요청은 장면 체인:
  scene1 (t2va/fl2va) → 마지막 프레임 추출(ffmpeg) → scene2 (fl2va, frame_index 0 키프레임) → ... → concat.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import prompt as P
from . import spec
from .client import Condition, H3Client, H3Error, VideoRequest, stage_input

OUTPUT_DIR = Path(os.environ.get("H3_OUTPUT_DIR", "outputs"))
INBOX_DIR = os.environ.get("H3_INBOX_DIR")
# 장면 하나를 기다리는 최대 시간(초). 서버 대기열에 다른 작업이 쌓여 있으면 1시간은 금방 지나간다.
WAIT_TIMEOUT = float(os.environ.get("H3_WAIT_TIMEOUT", 6 * 3600))
HOST = socket.gethostname()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def slugify(text: str, n: int = 40) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", text.strip())[:n].strip("-")
    return s or "video"


@dataclass
class Scene:
    index: int
    prompt: str
    duration: int
    task: str
    video_id: str | None = None
    status: str = "pending"      # pending | queued | in_progress | completed | failed
    progress: float = 0.0
    output: str | None = None
    error: str | None = None


@dataclass
class Job:
    id: str
    prompt: str
    total_seconds: int
    aspect_ratio: str
    seed: int
    task: str
    first_image: str | None = None
    last_image: str | None = None
    refs: list[dict] = field(default_factory=list)   # {"type","path"}
    scene_seconds: int = 10
    steps: int | None = None
    negative: str | None = None
    raw: bool = False            # True = 서버의 프롬프트 다듬기를 끈다
    short_edge: int = spec.SHORT_EDGE_DEFAULT   # 짧은 변 (768 기본, 줄이면 메모리·시간이 준다)
    host: str | None = None      # 처리하는 프로세스의 호스트·pid (죽은 프로세스의 작업을 '진행'으로 남기지 않으려고)
    pid: int | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    status: str = "pending"
    scenes: list[Scene] = field(default_factory=list)
    output: str | None = None
    error: str | None = None
    title: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        d["elapsed"] = round(((self.finished or time.time()) - (self.started or self.created)), 1) if self.started else 0
        return d


class JobStore:
    def __init__(self, root: Path = OUTPUT_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._load()

    def _path(self, job_id: str) -> Path:
        return self.root / job_id / "job.json"

    def _load(self):
        for f in sorted(self.root.glob("*/job.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                d.pop("elapsed", None)
                d["scenes"] = [Scene(**s) for s in d.get("scenes", [])]
                job = Job(**d)
            except Exception:
                continue
            self.jobs[job.id] = job
            # 같은 호스트에서 처리하던 프로세스가 이미 없으면 중단된 작업이다. 다른 노드(group-volume 공유)의 작업은 판단하지 않는다.
            if job.status in ("pending", "running") and job.host == HOST and job.pid and job.pid != os.getpid() and not pid_alive(job.pid):
                left = [s for s in job.scenes if s.video_id and s.status != "completed"]
                job.status, job.finished = "failed", job.finished or time.time()
                job.error = f"처리하던 프로세스(pid {job.pid})가 끝나 중단됨" + (
                    f". 서버에서 만들던 장면은 h3video fetch {left[-1].video_id}{' --ref' if left[-1].task == 'ref2va' else ''} 로 받을 수 있다"
                    if left else "")
                try:
                    self.save(job)
                except OSError:
                    pass

    def save(self, job: Job):
        # 임시 파일에 쓰고 바꿔치기: 쓰는 도중 프로세스가 죽어도 job.json 이 반쪽으로 깨지지 않는다.
        p = self._path(job.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".job.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(job.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def add(self, job: Job):
        with self.lock:
            self.jobs[job.id] = job
            self.save(job)

    def list(self) -> list[dict]:
        with self.lock:
            return [j.to_json() for j in sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)]

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def find(self, key: str) -> Job | None:
        """작업 id, id 앞부분, 또는 'last'(가장 최근)로 찾는다."""
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)
        if key == "last":
            return jobs[0] if jobs else None
        if key in self.jobs:
            return self.jobs[key]
        hits = [j for j in jobs if j.id.startswith(key) or j.id.endswith(key)]
        if len(hits) > 1:
            raise H3Error(f"'{key}' 에 맞는 작업이 {len(hits)}개다. 더 길게 적어라: " + ", ".join(j.id for j in hits[:5]))
        return hits[0] if hits else None


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def extract_last_frame(video: Path, out_png: Path) -> Path:
    ff = ffmpeg()
    if not ff:
        raise H3Error("ffmpeg 가 없어 장면 체인을 이을 수 없다 (apt install ffmpeg / conda install ffmpeg)")
    subprocess.run([ff, "-y", "-loglevel", "error", "-sseof", "-0.05", "-i", str(video), "-frames:v", "1", "-update", "1", str(out_png)], check=True)
    if not out_png.exists():
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,0)", "-frames:v", "1", str(out_png)], check=True)
    return out_png


def concat_videos(parts: list[Path], out: Path) -> Path:
    ff = ffmpeg()
    if not ff:
        raise H3Error("ffmpeg 가 없어 장면을 이어 붙일 수 없다")
    lst = out.with_suffix(".concat.txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    if r.returncode != 0:  # 코덱 파라미터가 달라 copy 가 실패하면 재인코딩
        subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    lst.unlink(missing_ok=True)
    return out


class Worker(threading.Thread):
    """작업을 순서대로 실행. 서버는 GPU 4장 한 세트라 병렬 제출해도 큐만 쌓이므로 직렬 처리."""

    def __init__(self, store: JobStore, client: H3Client, ref_client: H3Client | None = None,
                 inbox_dir: str | None = INBOX_DIR, poll: float = 3.0):
        super().__init__(daemon=True, name="h3-worker")
        self.store, self.client, self.ref_client = store, client, ref_client or client
        self.inbox_dir, self.poll = inbox_dir, poll
        self.queue: list[str] = []
        self.cv = threading.Condition()
        self.current: str | None = None

    def enqueue(self, job: Job):
        job.host, job.pid = HOST, os.getpid()
        self.store.add(job)
        with self.cv:
            self.queue.append(job.id)
            self.cv.notify()

    def run(self):
        while True:
            with self.cv:
                while not self.queue:
                    self.cv.wait()
                job_id = self.queue.pop(0)
            job = self.store.get(job_id)
            if job:
                self.current = job.id
                try:
                    self.process(job)
                except Exception as e:  # noqa: BLE001
                    job.status, job.error, job.finished = "failed", str(e), time.time()
                    self.store.save(job)
                finally:
                    self.current = None

    def plan(self, job: Job):
        job.scenes = plan_job(job)
        self.store.save(job)

    def process(self, job: Job):
        job.status, job.started = "running", time.time()
        self.plan(job)
        job_dir = self.store.root / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        prev_frame: Path | None = None
        for sc in job.scenes:
            req = build_request(job, sc, prev_frame, lambda path: stage_input(path, self.inbox_dir))
            sc.task = req.task
            client = self.ref_client if sc.task == "ref2va" else self.client
            sc.status = "queued"; self.store.save(job)
            sc.video_id = client.submit(req)

            def on_progress(st, sc=sc, job=job):
                sc.status = st.get("status", sc.status)
                sc.progress = float(st.get("progress") or 0)
                self.store.save(job)

            st = client.wait(sc.video_id, poll=self.poll, timeout=WAIT_TIMEOUT, on_progress=on_progress)
            out = job_dir / f"scene{sc.index + 1:02d}.mp4"
            if st.get("prompt_used"):   # 서버가 실제로 쓴 프롬프트 (Diffusers 엔진이 다듬은 것)
                (job_dir / f"scene{sc.index + 1:02d}.prompt.txt").write_text(st["prompt_used"], encoding="utf-8")
            client.download(sc.video_id, out)
            (job_dir / f"scene{sc.index + 1:02d}.request.json").write_text(json.dumps(req.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
            sc.status, sc.progress, sc.output = "completed", 1.0, str(out)
            parts.append(out)
            self.store.save(job)
            if sc.index < len(job.scenes) - 1:
                prev_frame = extract_last_frame(out, job_dir / f"scene{sc.index + 1:02d}.last.png")
        final = job_dir / f"{slugify(job.title or job.prompt)}.mp4"
        if len(parts) == 1:
            shutil.copy2(parts[0], final)
        else:
            concat_videos(parts, final)
        job.output, job.status, job.finished = str(final), "completed", time.time()
        self.store.save(job)


def plan_job(job: Job) -> list[Scene]:
    """총 길이를 장면으로 나누고 장면마다 task 를 정한다 (워커와 CLI --dry-run 공용)."""
    durations = spec.plan_scenes(job.total_seconds, job.scene_seconds)
    prompts = P.scene_prompts(job.prompt, durations, rewrite=not job.raw) if len(durations) > 1 else [job.prompt]
    scenes = []
    for i, (d, pr) in enumerate(zip(durations, prompts)):
        task = job.task
        if len(durations) > 1 and i > 0 and task in ("t2va", "fl2va"):
            task = "fl2va"          # 이전 장면 마지막 프레임을 첫 프레임으로
        scenes.append(Scene(index=i, prompt=pr, duration=d, task=task))
    return scenes


def build_request(job: Job, sc: Scene, prev_frame, stage) -> VideoRequest:
    """장면 하나의 요청. stage(path) 는 입력 파일을 서버가 읽을 URI 로 바꾼다 (실제 실행: stage_input, 미리보기: file:// 표기만)."""
    conds: list[Condition] = []
    prompt_text, task = sc.prompt, sc.task
    if task == "fl2va":
        first = prev_frame or (job.first_image if sc.index == 0 else None)
        last = job.last_image if sc.index == len(job.scenes) - 1 else None
        if first:
            conds.append(Condition("image", stage(first), "keyframe", 0))
        if last:
            conds.append(Condition("image", stage(last), "keyframe", -1))
        if not conds:
            task = "t2va"
        elif not P.is_context_ir(prompt_text):
            prompt_text = P.keyframe_note(first=bool(first), last=bool(last), seconds=sc.duration) + "\n\n" + prompt_text
    elif task == "ref2va":
        for r in job.refs:
            conds.append(Condition(r["type"], stage(r["path"]), "reference"))
        if prev_frame:
            conds.append(Condition("image", stage(prev_frame), "reference"))
    return VideoRequest(prompt=prompt_text, task=task, duration_seconds=sc.duration, aspect_ratio=job.aspect_ratio,
                        seed=job.seed + sc.index, conditions=conds, num_inference_steps=job.steps, negative_prompt=job.negative,
                        rewrite=not job.raw, short_edge=job.short_edge)


def new_job(prompt: str, seconds: int = 8, aspect_ratio: str = "16:9", seed: int = 0, task: str | None = None,
            first_image: str | None = None, last_image: str | None = None, refs: list[dict] | None = None,
            scene_seconds: int = 10, steps: int | None = None, title: str = "", negative: str | None = None,
            raw: bool = False, short_edge: int = spec.SHORT_EDGE_DEFAULT) -> Job:
    refs = refs or []
    if task is None:
        task = "ref2va" if refs else ("fl2va" if (first_image or last_image) else "t2va")
    if aspect_ratio not in spec.ASPECT_RATIOS:
        raise H3Error(f"aspect_ratio 는 {spec.ASPECT_RATIOS} 중 하나")
    seconds = int(seconds)
    if seconds < spec.DURATION_MIN:
        raise H3Error(f"최소 {spec.DURATION_MIN}초")
    return Job(id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], prompt=prompt, total_seconds=seconds,
               aspect_ratio=aspect_ratio, seed=seed, task=task, first_image=first_image, last_image=last_image,
               refs=refs, scene_seconds=scene_seconds, steps=steps, title=title, negative=negative or None, raw=raw,
               short_edge=int(short_edge))
