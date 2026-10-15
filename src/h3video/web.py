"""로컬호스트 웹 UI (표준 라이브러리 http.server). 프롬프트 입력 → 진행 상황 → 결과 재생.

  h3video web --port 8790
API: GET /api/spec, GET /api/jobs, GET /api/jobs/{id}, POST /api/jobs (multipart), GET /files/{job}/{name}, GET /api/health
     JSON 한번에: POST /api/story/plan (미리 보기), POST /api/story (multipart: json, images[], narration, ratio, seed, size),
     GET /api/story/{id} (장면별 상태, 다 끝나면 이어 붙인 영상), GET /api/stories
     화면용: GET /api/feed (작업·JSON 한번에를 카드 하나씩, 쉬운 오류·CLI 명령 포함),
             GET /api/plan?seconds=40&task=t2va&aspect=16:9&size=768 (몇 장면으로 나뉘는지, 서버 GPU 한도 반영),
             POST /api/jobs/{id}/retry (같은 설정으로 다시), POST /api/story/{id}/resume (안 된 장면만 다시)

CORS: 기본은 끔. 다른 웹 페이지(예: 33modeling 허브의 숏폼 제작)에서 이 서버를 부르려면
  h3video web --cors-origin https://33modeling.pages.dev   (여러 개는 쉼표, 전부 허용은 *)
또는 환경변수 H3_CORS_ORIGIN. 허용한 출처에만 Access-Control-Allow-Origin 을 돌려주고,
사전 요청(OPTIONS)에는 사설망 접근 허용(Access-Control-Allow-Private-Network: true)도 붙인다.
"""
from __future__ import annotations

import email
import email.policy
import json
import mimetypes
import os
import random
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import hints
from . import spec
from . import story as ST
from . import storyrun as SR
from .client import DEFAULT_ENDPOINT, DEFAULT_REF_ENDPOINT, H3Client, H3Error
from .jobs import INBOX_DIR, OUTPUT_DIR, JobStore, Worker, new_job

from .recovery import edit_story, restore_story, edit_job, restore_job
from .studio import VideoStudio

HTML = Path(__file__).with_name("ui.html").read_text(encoding="utf-8")
SIZES = (512, 576, 640, 704, 768)


def served_html() -> bytes:
    """이 서버가 직접 준 화면이라는 표시: 화면은 같은 주소로 API 를 부른다 (허브 등 다른 곳에서 열면 '서버 주소'를 묻는다)."""
    return HTML.replace('<html lang="ko">', '<html lang="ko" data-served="h3video">', 1).encode()


def parse_seed(v) -> int:
    """비었으면 0 (예전과 같게), random 이면 매번 다르게."""
    s = str(v if v is not None else "").strip().lower()
    if s in ("random", "rand", "r"):
        return random.randrange(2 ** 31)
    if s and not re.fullmatch(r"-?\d+", s):
        raise H3Error(f"시드는 숫자만 적어요 (비우면 매번 다르게): {s}")
    return int(s or 0)


def parse_int(v, name: str, default: int | None = None) -> int | None:
    """폼 값 → 정수. '8.0' 같은 것도 받고, 숫자가 아니면 쉬운 말로 (파이썬 int() 의 영어 오류 대신)."""
    s = str(v if v is not None else "").strip()
    if not s:
        return default
    try:
        f = float(s)
    except ValueError:
        raise H3Error(f"{name}에는 숫자를 적어 주세요: {s}") from None
    if f != f or f in (float("inf"), float("-inf")):
        raise H3Error(f"{name}에는 숫자를 적어 주세요: {s}")
    return int(round(f))


def parse_size(v) -> int:
    size = parse_int(v, "크기", spec.SHORT_EDGE_DEFAULT)
    if size not in SIZES:
        raise H3Error("크기(size)는 512·576·640·704·768 중 하나")
    return size


def parse_bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes", "y", "예")


def display_name(path: str) -> str:
    """업로드 때 붙인 앞 8자리(충돌 방지)를 뗀 원래 파일 이름."""
    return re.sub(r"^[0-9a-f]{8}-", "", Path(str(path)).name)


class App:
    def __init__(self, endpoint: str, ref_endpoint: str, output_dir: Path, inbox_dir: str | None, poll: float = 3.0):
        self.client = H3Client(endpoint)
        self.ref_client = H3Client(ref_endpoint)
        self.store = JobStore(output_dir)
        self.upload_dir = output_dir / "_uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.worker = Worker(self.store, self.client, self.ref_client, inbox_dir=inbox_dir, poll=poll)
        self.worker.start()
        self.endpoint, self.ref_endpoint = endpoint, ref_endpoint
        self.inbox_dir = inbox_dir
        self.cli_output_dir = str(Path(output_dir).resolve())   # '명령어로 보기'의 --output-dir (다른 폴더에서 실행해도 찾게)
        self._limits: dict[tuple, tuple[float, int | None]] = {}
        self._limits_lock = threading.Lock()
        self.studio = VideoStudio(self)
        from .reference import ReferenceLibrary
        self.references = ReferenceLibrary(self)
        from .motion import MotionStudio
        self.motion = MotionStudio(self)

    def allowed_input(self, path: str) -> bool:
        if path.startswith(("http://", "https://")):
            return True
        p = Path(path[7:] if path.startswith("file://") else path).expanduser().resolve()
        roots = [self.upload_dir.resolve()] + ([Path(self.inbox_dir).expanduser().resolve()] if self.inbox_dir else [])
        return any(r == p or r in p.parents for r in roots)

    def save_upload(self, filename: str | None, data: bytes) -> str | None:
        if not filename or not data:
            return None
        dest = self.upload_dir / f"{os.urandom(4).hex()}-{Path(filename).name}"
        dest.write_bytes(data)
        return str(dest)

    # ---------- 화면용 ----------
    def file_url(self, path: str | None) -> str | None:
        """결과 폴더 안의 파일 → /files/... 주소 (그 밖의 파일은 보여 주지 않는다)."""
        if not path:
            return None
        s = str(path)
        if s.startswith(("http://", "https://")):
            return s
        p = Path(s[7:] if s.startswith("file://") else s).expanduser().resolve()
        root = self.store.root.resolve()
        if root not in p.parents:
            return None
        return "/files/" + urllib.parse.quote(p.relative_to(root).as_posix())

    def max_scene(self, task: str, aspect: str, size: int, keyframes: int, images: int, video_seconds: float) -> int | None:
        """서버가 알려 주는 한 장면 최대 초 (잠깐 기억해 둔다: 화면이 길이를 바꿀 때마다 묻지 않게)."""
        key = (task == "ref2va", aspect, size, keyframes, images, round(video_seconds))
        with self._limits_lock:
            hit = self._limits.get(key)
        if hit and time.time() - hit[0] < (300 if hit[1] else 30):
            return hit[1]
        client = self.ref_client if task == "ref2va" else self.client
        m = client.max_seconds(aspect, size, keyframes, images, video_seconds, timeout=3) if hasattr(client, "max_seconds") else None
        with self._limits_lock:
            self._limits[key] = (time.time(), m)
        return m

    def plan(self, q: dict) -> dict:
        g = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731
        seconds = max(spec.DURATION_MIN, parse_int(g("seconds"), "길이(초)", 8))
        task = g("task", "t2va") or "t2va"
        aspect = g("aspect", "16:9") or "16:9"
        if aspect not in spec.ASPECT_RATIOS:
            raise H3Error(f"aspect 는 {spec.ASPECT_RATIOS} 중 하나")
        size = parse_size(g("size"))
        keyframes = 0 if task == "ref2va" else (2 if parse_bool(g("last", "0")) else 1)
        m = self.max_scene(task, aspect, size, keyframes, parse_int(g("images"), "images", 0), float(parse_int(g("video_seconds"), "video_seconds", 0)))
        scenes = spec.plan_scenes(seconds, parse_int(g("scene_seconds"), "장면 길이", 10) or 10, m or None)
        return {"seconds": seconds, "scenes": scenes, "max_scene": m or None,
                "limit": max(spec.SCENE_MIN, min(spec.DURATION_MAX, m)) if m else spec.DURATION_MAX}

    def job_item(self, d: dict) -> dict:
        refs = [{"type": r["type"], "name": display_name(r["path"]), "url": self.file_url(r["path"])} for r in d.get("refs") or []]
        q = list(self.worker.queue)
        return {**d, "kind": "job", "cli": hints.job_command(d), "error_ko": hints.explain_error(d.get("error"), d.get("task", "t2va")),
                "video_url": self.file_url(d.get("output")) if d.get("status") == "completed" else None,
                "first_url": self.file_url(d.get("first_image")), "last_url": self.file_url(d.get("last_image")),
                "first_name": display_name(d["first_image"]) if d.get("first_image") else None,
                "last_name": display_name(d["last_image"]) if d.get("last_image") else None,
                "revisions":len(list((self.store.root/d["id"]/"history").glob("*/job.json"))), "ref_files": refs, "queue_pos": (q.index(d["id"]) + 1) if d["id"] in q else None}

    def story_dirs(self) -> list[Path]:
        return sorted((d for d in self.store.root.glob("story-*") if (d / SR.STATE).is_file()), key=lambda d: d.name, reverse=True)

    def story_item(self, d: Path) -> dict:
        with SR.story_lock(d):
            return self._story_item(d)

    def _story_item(self, d: Path) -> dict:
        try:
            st = SR.refresh(d, SR.load_state(d), self.store)
            join_error = None
        except Exception as e:   # noqa: BLE001  이어 붙이기 실패(ffmpeg 등)도 카드에 보이게
            st, join_error = SR.load_state(d), f"이어 붙이기 실패: {e}"
        s = SR.summary(st)
        jobs = [self.store.get(c["job_id"]) for c in st["clips"] if c.get("job_id")]
        jobs = [j for j in jobs if j]
        busy = any(j.status in ("pending", "running") for j in jobs)
        status = "completed" if st.get("output") else "pausing" if busy and st.get("paused") else "running" if busy else "paused" if st.get("paused") or any(j.status=="paused" for j in jobs) else "failed" if (s["failed"] or join_error) else "paused"
        started = min((j.started or j.created for j in jobs), default=st.get("created") or time.time())
        finished = max((j.finished or 0 for j in jobs), default=0) if status in ("completed", "failed") else None
        clips = []
        for c in st["clips"]:
            clips.append({"id": c["id"], "label": c["label"], "seconds": c["seconds"], "auto": c.get("auto", ""),
                          "text": c.get("text", ""), "prompt": c.get("prompt",""), "image_name": Path(c["image"]).name if c.get("image") else None,
                          "image_url": self.file_url(c.get("image")), "status": "completed" if c.get("output") else
                          ("failed" if c.get("error") else c.get("status") or "pending"), "progress": c.get("progress") or 0,
                          "error": c.get("error"), "error_ko": hints.explain_error(c.get("error")),
                          "video_url": self.file_url(c.get("output"))})
        inp = st.get("input") or {}
        imgs = sorted(Path(inp["images"]).glob("*")) if inp.get("images") and Path(inp["images"]).is_dir() else []
        cmds = hints.story_commands(st, d.name, self.cli_output_dir)
        return {"kind": "story", "id": d.name, "title": st.get("title"), "created": st.get("created") or 0, "ratio": st.get("ratio"),
                "status": status, "elapsed": round((finished or time.time()) - started, 1), "clips": clips, **s,
                "video_url": self.file_url(st.get("output")), "error": join_error, "error_ko": hints.explain_error(join_error),
                "cli": cmds["make"] or cmds["resume"], "resume_cli": cmds["resume"], "params": st.get("params") or {},
                "revisions":len(st.get("revisions") or []), "inputs": {"json_url": self.file_url(inp.get("json")), "json_name": Path(inp["json"]).name if inp.get("json") else None,
                           "images": [{"name": p.name, "url": self.file_url(str(p))} for p in imgs
                                      if p.suffix.lower() in ST.IMAGE_EXTS]}}

    def feed(self, limit: int | None = None) -> dict:
        """화면 오른쪽 카드 목록: 작업과 JSON 한번에를 최근 순으로. JSON 한번에의 장면 작업은 그 카드 안에만 보인다."""
        items, in_story = [], set()
        for d in self.story_dirs():
            try:
                it = self.story_item(d)
            except (OSError, ValueError, KeyError):
                continue
            items.append(it)
        for d in self.story_dirs():
            try:
                in_story |= {j for c in SR.load_state(d)["clips"] for j in [c.get("job_id"), *(c.get("past_jobs") or [])]}
            except (OSError, ValueError, KeyError):
                continue
        items += [self.job_item(j) for j in self.store.list() if j["id"] not in in_story]
        items.sort(key=lambda x: x.get("created") or 0, reverse=True)
        return {"items": items if limit is None else items[:limit], "queue": list(self.worker.queue), "current": self.worker.current, "now": time.time()}

    def health(self) -> dict:
        ok = {"fl2va": self.client.healthy(), "ref2va": self.ref_client.healthy()}
        return {**ok, "queue": len(self.worker.queue), "current": self.worker.current,
                "endpoints": {"fl2va": self.endpoint, "ref2va": self.ref_endpoint},
                "hints": {k: (None if v else hints.server_hint(k, self.endpoint if k == "fl2va" else self.ref_endpoint)) for k, v in ok.items()}}

    def retry(self, job_id: str):
        jb = self.store.get(job_id)
        if not jb:
            raise KeyError(job_id)
        for path in [jb.first_image, jb.last_image] + [r["path"] for r in jb.refs]:
            if path and not self.allowed_input(str(path)):
                raise H3Error(f"이 작업의 파일은 웹에서 다시 쓸 수 없어요: {path}")
        job = new_job(prompt=jb.prompt, seconds=jb.total_seconds, aspect_ratio=jb.aspect_ratio, seed=jb.seed, task=jb.task,
                      first_image=jb.first_image, last_image=jb.last_image, refs=list(jb.refs), scene_seconds=jb.scene_seconds,
                      steps=jb.steps, title=jb.title, negative=jb.negative, raw=jb.raw, short_edge=jb.short_edge)
        self.worker.enqueue(job)
        return job

    def resume_story(self, name: str) -> dict:
        with SR.story_lock(self.store.root / name):
            return self._resume_story(name)

    def _resume_story(self, name: str) -> dict:
        d = self.store.root / name
        if not re.fullmatch(r"story-[\w-]+", name) or not (d / SR.STATE).is_file():
            raise KeyError(name)
        st = SR.refresh(d, SR.load_state(d), self.store)
        busy = [c for c in st["clips"] if c.get("job_id") and (self.store.get(c["job_id"]) and
                                                             self.store.get(c["job_id"]).status in ("pending", "running"))]
        if busy:
            raise H3Error("아직 만드는 장면이 있어요. 끝난 뒤에 다시 하세요")
        existing=[]
        for c in st["clips"]:
            job=self.store.get(c.get("job_id")) if c.get("job_id") else None
            if not c.get("output") and job and job.status in ("paused","failed"):
                existing.append(job)
        existing_ids={j.id for j in existing}
        selected={c["id"] for c in st["clips"] if not c.get("output") and c.get("job_id") not in existing_ids}
        jobs=SR.jobs_for(st,only=selected) if selected else []
        if not jobs and not existing:
            raise H3Error("다시 만들 장면이 없어요")
        st["paused"]=False
        SR.save_state(d,st)
        for job in existing:
            self.worker.resume(job.id)
        for job in jobs:
            self.worker.enqueue(job)
        return {"id":name,**SR.summary(st),"redo":len(jobs)+len(existing)}


def story_fields(fields: dict) -> dict:
    """JSON 한번에 폼: json(파일이나 글), narration, ratio, seed, size."""
    g = lambda k, d=None: (fields[k][0][1].decode("utf-8", "replace").strip() if k in fields else d)  # noqa: E731
    raw = fields.get("json", [(None, b"")])[0][1]
    if not raw.strip():
        raise H3Error("JSON 파일을 고르거나 붙여 넣어라")
    ratio = g("ratio") or None
    if ratio and ratio not in spec.ASPECT_RATIOS:
        raise H3Error(f"ratio 는 {spec.ASPECT_RATIOS} 중 하나")
    return {"json": raw, "json_name": fields["json"][0][0], "narration": g("narration", "1") not in ("0", "false", "off", ""),
            "ratio": ratio, "seed": parse_seed(g("seed")), "size": parse_size(g("size"))}


def attachment(name: str) -> str:
    """Content-Disposition: 한글 파일 이름도 깨지지 않게 (RFC 6266/5987)."""
    ascii_name = re.sub(r'[^A-Za-z0-9._-]+', "_", name).strip("_") or "video.mp4"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name)}"


def parse_multipart(content_type: str, body: bytes) -> dict[str, list[tuple[str | None, bytes]]]:
    """multipart/form-data → {field: [(filename|None, bytes), ...]} (cgi 모듈 없이)."""
    msg = email.message_from_bytes(b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
                                   policy=email.policy.HTTP)
    out: dict[str, list[tuple[str | None, bytes]]] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        out.setdefault(name, []).append((part.get_filename(), part.get_payload(decode=True) or b""))
    return out


def parse_origins(value: str | None) -> list[str]:
    return [o.strip().rstrip("/") for o in (value or "").split(",") if o.strip()]


def make_handler(app: App, cors_origins: list[str] | None = None):
    cors_origins = cors_origins or []

    class Handler(BaseHTTPRequestHandler):
        server_version = "h3video/0.1"

        def log_message(self, fmt, *args):  # 조용히
            pass

        def _cors(self, preflight: bool = False):
            if not cors_origins:
                return
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if "*" in cors_origins:
                self.send_header("Access-Control-Allow-Origin", "*")
            elif origin and origin in cors_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            else:
                return
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
            if preflight or self.headers.get("Access-Control-Request-Private-Network"):
                # 공개 웹(허브)에서 이 컴퓨터(127.0.0.1)의 서버를 부를 때 크롬이 묻는 사설망 접근 허용
                self.send_header("Access-Control-Allow-Private-Network", "true")
            if preflight:
                self.send_header("Access-Control-Max-Age", "600")

        def send_response(self, code, message=None):
            self._started = True
            super().send_response(code, message)

        def _safe(self, fn):
            """처리 중 예상 못 한 오류(디스크·권한 등): 연결을 그냥 끊으면 화면은 '연결하지 못했어요'로 잘못 알린다 → 500 + 쉬운 말."""
            self._started = False
            try:
                fn()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                if not self._started:
                    try:
                        msg = f"권한이 없어 쓸 수 없어요: {e.filename}" if isinstance(e, PermissionError) else f"{type(e).__name__}: {e}"
                        self._json({"error": f"웹 서버 안에서 오류가 났어요 — {msg}"}, 500)
                    except OSError:
                        pass

        def do_GET(self):
            self._safe(self._do_get)

        def do_POST(self):
            self._safe(self._do_post)

        def _studio_method(self):
            from .motion_proxy import motion_route
            if not motion_route(self, app, cors_origins):
                self._json({'error': '이 경로는 GET 또는 POST를 사용하세요.'}, 405)

        def do_PUT(self):
            self._safe(self._studio_method)

        do_PATCH = do_PUT
        do_DELETE = do_PUT
        do_HEAD = do_PUT

        def do_OPTIONS(self):
            self.send_response(204 if cors_origins else 405)
            self._cors(preflight=True)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if ctype.startswith("text/html"):
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, f: Path, download: bool = False):
            """Range 요청을 받는다: 브라우저 <video> 가 구간 이동을 하고, Safari·iOS 는 Range 없이는 재생하지 않는다.
            큰 mp4 를 메모리에 다 올리지 않고 나눠 보낸다. download=True(?download=1)면 내려받기로 보낸다
            (허브처럼 다른 주소에서 연 화면은 <a download> 가 먹지 않아 영상 페이지로 넘어가 버린다)."""
            size = f.stat().st_size
            start, end, code = 0, size - 1, 200
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1)); end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:  # bytes=-N : 마지막 N 바이트
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    self.send_response(416); self._cors()
                    self.send_header("Content-Range", f"bytes */{size}"); self.send_header("Content-Length", "0"); self.end_headers()
                    return
                code = 206
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            if download:
                self.send_header("Content-Disposition", attachment(f.name))
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with f.open("rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 재생 중 다른 구간으로 넘기면 브라우저가 연결을 끊는다

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _do_get(self):
            u = urllib.parse.urlparse(self.path)
            p = u.path
            from .motion_proxy import motion_route
            if motion_route(self, app, cors_origins):
                return
            if p == '/api/motion/capabilities':
                return self._json(app.motion.capabilities())
            if p == '/api/motion/projects':
                return self._json({'projects': app.motion.list()})
            if re.fullmatch(r'/api/motion/projects/hf-[a-f0-9]{32}', p):
                try:
                    return self._json(app.motion.get(p.rsplit('/', 1)[-1]))
                except KeyError:
                    return self._json({'error': '모션 프로젝트 없음'}, 404)
            if p in ("/", "/index.html"):
                return self._send(200, served_html(), "text/html; charset=utf-8")
            if p.startswith('/studio/'):
                file = (Path(__file__).parent / p.lstrip('/')).resolve()
                directory = (Path(__file__).parent / 'studio').resolve()
                if directory not in file.parents or not file.is_file():
                    return self._json({'error': '파일 없음'}, 404)
                return self._send_file(file)
            if p == '/api/studio/capabilities':
                return self._json(app.studio.capabilities())
            if p == '/api/studio/references':
                return self._json({'references': app.references.list()})
            if re.fullmatch(r'/api/studio/references/ref-[a-f0-9]{32}', p):
                try:
                    return self._json(app.references.get(p.rsplit('/', 1)[-1]))
                except KeyError:
                    return self._json({'error': '참고 분석 없음'}, 404)
            if p == '/api/studio/projects':
                return self._json({'projects': app.studio.list()})
            if re.fullmatch(r'/api/studio/projects/edit-[a-f0-9]{32}', p):
                try:
                    return self._json(app.studio.get(p.rsplit('/', 1)[-1]))
                except KeyError:
                    return self._json({'error': '프로젝트 없음'}, 404)
                except H3Error as error:
                    return self._json({'error': str(error)}, 400)
            if p == "/api/spec":
                return self._json({"summary": spec.summary(), "duration_min": spec.DURATION_MIN, "duration_max": spec.DURATION_MAX,
                                   "fps": spec.FPS, "short_edge": spec.SHORT_EDGE_DEFAULT, "aspect_ratios": spec.ASPECT_RATIOS,
                                   "tasks": spec.TASKS, "ref_limits": spec.REF_LIMITS, "endpoint": app.endpoint,
                                   "ref_endpoint": app.ref_endpoint, "output_dir": str(app.store.root),
                                   "model": spec.MODEL_ID, "audio": spec.AUDIO, "languages": spec.LANGUAGES, "hardware": spec.PARAMS,
                                   "scene_min": spec.SCENE_MIN, "sizes": list(SIZES), "steps_default": spec.STEPS_DEFAULT})
            if p == "/api/health":
                return self._json(app.health())
            if p == "/api/feed":
                return self._json(app.feed())
            if p == "/api/plan":
                try:
                    return self._json(app.plan(urllib.parse.parse_qs(u.query)))
                except (H3Error, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
            if p == "/api/jobs":
                return self._json(app.store.list())
            if p.startswith("/api/jobs/"):
                job = app.store.get(p.split("/")[3])
                return self._json(job.to_json()) if job else self._json({"error": "없음"}, 404)
            if p == "/api/stories":
                out = []
                for d in sorted(app.store.root.glob("story-*"), reverse=True)[:20]:
                    if (d / SR.STATE).is_file():
                        st = SR.refresh_saved(d, app.store)
                        out.append({"id": d.name, "title": st["title"], **SR.summary(st)})
                return self._json(out)
            if p.startswith("/api/story/"):
                name = p.split("/")[3]
                d = app.store.root / name
                if not re.fullmatch(r"story-[\w-]+", name) or not (d / SR.STATE).is_file():
                    return self._json({"error": "없음"}, 404)
                try:
                    st = SR.refresh_saved(d, app.store)
                except Exception as e:   # 이어 붙이기 실패(ffmpeg 등)도 화면에 보이게
                    return self._json({"error": f"이어 붙이기 실패: {e}"}, 500)
                return self._json({"id": name, **st, **SR.summary(st)})
            if p.startswith("/files/"):
                rel = urllib.parse.unquote(p[len("/files/"):])
                f = (app.store.root / rel).resolve()
                if app.store.root.resolve() not in f.parents or not f.is_file():
                    return self._json({"error": "없음"}, 404)
                return self._send_file(f, download=parse_bool((urllib.parse.parse_qs(u.query).get("download") or ["0"])[0]))
            self._json({"error": "not found"}, 404)

        def _story_post(self):
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                return self._json({"error": "multipart/form-data 로 보내라 (json 파일 + images)"}, 400)
            try:
                fields = parse_multipart(ctype, self.rfile.read(int(self.headers.get("Content-Length", 0))))
                f = story_fields(fields)
                if self.path == "/api/story/plan":   # 미리 보기: 그림은 이름만 받는다
                    names = [x[1].decode("utf-8", "replace") for x in fields.get("image_names", [])]
                    st = ST.load_story(f["json"], names, narration=f["narration"], ratio=f["ratio"], seed=f["seed"], local_paths=False)
                    d = st.to_json()
                    for c in d["clips"]:
                        c["image"] = Path(c["image"]).name if c["image"] else None
                    d["unused_images"] = [Path(x).name for x in d["unused_images"]]
                    d["missing_images"] = [c["id"] for c in d["clips"] if not c["image"]]
                    return self._json(d)
                folder = app.upload_dir / f"story-{os.urandom(4).hex()}"
                paths = []
                for fname, data in fields.get("images", []):
                    if fname and data:
                        folder.mkdir(parents=True, exist_ok=True)
                        dest = folder / Path(fname).name
                        dest.write_bytes(data)
                        paths.append(str(dest))
                st = ST.load_story(f["json"], paths, narration=f["narration"], ratio=f["ratio"], seed=f["seed"], local_paths=False)
                # ratio: 화면에서 고른 화면비(없으면 JSON 대로) — '같은 설정으로 다시'가 그대로 채운다
                state = SR.initial_state(st, {"size": f["size"], "narration": f["narration"], "seed": f["seed"], "ratio": f["ratio"]})
                # 올린 JSON 도 같이 둔다: 화면의 '명령어로 보기'·'같은 설정으로 다시'가 같은 파일을 쓴다
                folder.mkdir(parents=True, exist_ok=True)
                jname = Path(f["json_name"] or "story.json").name
                jpath = folder / (jname if jname.lower().endswith(".json") else jname + ".json")
                jpath.write_bytes(f["json"])
                state["input"] = {"json": str(jpath), "images": str(folder)}
                jobs = SR.jobs_for(state)
                d = SR.new_story_dir(app.store.root)
                SR.save_state(d, state)
                for job in jobs:
                    app.worker.enqueue(job)
                return self._json({"id": d.name, **state, **SR.summary(state)}, 201)
            except (H3Error, ValueError) as e:
                return self._json({"error": str(e)}, 400)

        def _do_post(self):
            p = urllib.parse.urlparse(self.path).path
            from .motion_proxy import motion_route
            if motion_route(self, app, cors_origins):
                return
            motion = re.fullmatch(r'/api/motion/projects(?:/(hf-[a-f0-9]{32})(?:/(save|upload|render|pause|resume|restore|export))?)?', p)
            if motion:
                try:
                    origin = self.headers.get('Origin')
                    host = self.headers.get('Host', '')
                    if origin and origin not in cors_origins and '*' not in cors_origins and origin not in ('http://' + host, 'https://' + host):
                        return self._json({'error': '허용되지 않은 출처입니다.'}, 403)
                    length = int(self.headers.get('Content-Length', 0))
                    if length < 0 or length > 512 * 1024 * 1024:
                        return self._json({'error': '업로드는 512MB 이하로 준비하세요.'}, 413)
                    data = self.rfile.read(length)
                    name, action = motion.groups()
                    if action == 'upload':
                        fields = parse_multipart(self.headers.get('Content-Type', ''), data)
                        filename, content = fields['file'][0]
                        return self._json(app.motion.upload(name, filename, content))
                    if not self.headers.get('Content-Type', '').startswith('application/json'):
                        return self._json({'error': 'JSON 요청이 필요합니다.'}, 415)
                    body = json.loads(data or b'{}')
                    if not isinstance(body, dict):
                        raise H3Error('JSON 객체를 보내세요.')
                    if not name:
                        return self._json(app.motion.create(body), 201)
                    if action == 'save': return self._json(app.motion.edit(name, body))
                    if action == 'restore': return self._json(app.motion.restore(name, body.get('version')))
                    if action == 'render': return self._json(app.motion.render(name, body), 202)
                    if action == 'resume': return self._json(app.motion.render(name, body, resume=True), 202)
                    if action == 'pause': return self._json(app.motion.pause(name))
                    if action == 'export': return self._json(app.motion.export(name))
                    raise H3Error('모션 작업을 선택하세요.')
                except KeyError:
                    return self._json({'error': '모션 프로젝트·파일을 찾지 못했습니다.'}, 404)
                except (H3Error, ValueError, TypeError) as error:
                    return self._json({'error': str(error)}, 400)
            reference_route = re.fullmatch(r'/api/studio/references(?:/(ref-[a-f0-9]{32})(?:/(pause|resume|save|import))?)?', p)
            if reference_route:
                try:
                    name, action = reference_route.groups()
                    length = int(self.headers.get('Content-Length', 0))
                    if length < 0 or length > 512 * 1024 * 1024:
                        return self._json({'error': '업로드는 512MB 이하로 준비하세요.'}, 413)
                    data = self.rfile.read(length)
                    if 'multipart/form-data' in self.headers.get('Content-Type', ''):
                        fields = parse_multipart(self.headers.get('Content-Type', ''), data)
                        body = {key: rows[0][1].decode() for key, rows in fields.items() if key != 'file'}
                        return self._json(app.references.create(body, fields['file'][0]), 202)
                    body = json.loads(data or b'{}')
                    if not isinstance(body, dict):
                        raise H3Error('JSON 객체를 보내세요.')
                    if not name:
                        return self._json(app.references.create(body), 202)
                    if action == 'pause': return self._json(app.references.pause(name))
                    if action == 'resume': return self._json(app.references.resume(name), 202)
                    if action == 'save': return self._json(app.references.edit(name, body))
                    if action == 'import': return self._json(app.references.import_project(name), 201)
                    raise H3Error('참고 분석 작업을 선택하세요.')
                except KeyError:
                    return self._json({'error': '참고 분석·업로드 파일을 찾지 못했습니다.'}, 404)
                except (H3Error, ValueError, TypeError) as error:
                    return self._json({'error': str(error)}, 400)
            studio_route = re.fullmatch(r'/api/studio/projects(?:/(edit-[a-f0-9]{32})(?:/([a-z-]+))?)?', p)
            if studio_route:
                try:
                    name, action = studio_route.groups()
                    length = int(self.headers.get('Content-Length', 0))
                    if length < 0 or length > 512 * 1024 * 1024:
                        return self._json({'error': '파일은 512MB 이하로 업로드하세요.'}, 413)
                    data = self.rfile.read(length)
                    if action == 'upload':
                        fields = parse_multipart(self.headers.get('Content-Type', ''), data)
                        body = {key: rows[0][1].decode() for key, rows in fields.items() if key != 'file'}
                        filename, content = fields['file'][0]
                        return self._json(app.studio.upload(name, body, filename, content))
                    body = json.loads(data or b'{}')
                    if not isinstance(body, dict):
                        raise H3Error('요청은 JSON 객체로 보내세요.')
                    if not name:
                        return self._json(app.studio.create(body), 201)
                    return self._json(app.studio.dispatch(name, action, body), 202 if action in ('preview','render','transcribe','inspect','upscale','candidates','resume') else 200)
                except KeyError:
                    return self._json({'error': '프로젝트·파일·필수 입력을 찾지 못했습니다.'}, 404)
                except (H3Error, ValueError, TypeError) as error:
                    return self._json({'error': str(error)}, 400)
            recovery=re.fullmatch(r"/api/(jobs|story)/([\w-]+)/(pause|continue|edit|restore)",p)
            if recovery:
                kind, name, action = recovery.groups()
                try:
                    if kind=="jobs":
                        if action=="pause": result=app.worker.pause(name).to_json()
                        elif action=="continue": result=app.worker.resume(name).to_json()
                        elif action=="edit":
                            body=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
                            result=edit_job(app.store,name,body).to_json()
                        else: result=restore_job(app.store,name).to_json()
                    else:
                        d=app.store.root/name
                        if not name.startswith("story-") or not (d/SR.STATE).is_file():raise KeyError(name)
                        with SR.story_lock(d):
                            state=SR.load_state(d)
                            if action=="pause":
                                state["paused"]=True
                                for clip in state["clips"]:
                                    job=app.store.get(clip.get("job_id")) if clip.get("job_id") else None
                                    if job and job.status in ("pending","running"):app.worker.pause(job.id)
                                SR.save_state(d,state);result={"id":name,"paused":True}
                            elif action=="continue": result=app.resume_story(name)
                            elif action=="edit":
                                body=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
                                result=edit_story(d,app.store,body)
                            else: result=restore_story(d,app.store)
                    return self._json(result)
                except KeyError:return self._json({"error":"저장된 작업을 찾지 못했습니다."},404)
                except (H3Error,ValueError,TypeError) as error:return self._json({"error":str(error)},400)
            if p in ("/api/story", "/api/story/plan"):
                return self._story_post()
            m = re.fullmatch(r"/api/jobs/([\w-]+)/retry", p)
            if m:
                try:
                    return self._json(app.retry(m.group(1)).to_json(), 201)
                except KeyError:
                    return self._json({"error": "없음"}, 404)
                except (H3Error, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
            m = re.fullmatch(r"/api/story/([\w-]+)/resume", p)
            if m:
                try:
                    return self._json(app.resume_story(m.group(1)), 201)
                except KeyError:
                    return self._json({"error": "없음"}, 404)
                except (H3Error, ValueError) as e:
                    return self._json({"error": str(e)}, 400)
            if p != "/api/jobs":
                return self._json({"error": "not found"}, 404)
            ctype = self.headers.get("Content-Type", "")
            try:
                if ctype.startswith("multipart/form-data"):
                    n = int(self.headers.get("Content-Length", 0))
                    fields = parse_multipart(ctype, self.rfile.read(n))
                    g = lambda k, d=None: (fields[k][0][1].decode("utf-8", "replace") if k in fields else d)  # noqa: E731
                    refs = []
                    for key, t in (("ref_images", "image"), ("ref_videos", "video"), ("ref_audios", "audio")):
                        for fname, data in fields.get(key, []):
                            path = app.save_upload(fname, data)
                            if path:
                                refs.append({"type": t, "path": path})
                    first = last = None
                    if fields.get("first_image"):
                        first = app.save_upload(*fields["first_image"][0])
                    if fields.get("last_image"):
                        last = app.save_upload(*fields["last_image"][0])
                else:
                    n = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(n) or b"{}")
                    g = lambda k, d=None: body.get(k, d)  # noqa: E731
                    refs = body.get("refs") or []
                    if not isinstance(refs, list) or any(not isinstance(r, dict) or r.get("type") not in ("image", "video", "audio")
                                                         or not isinstance(r.get("path"), str) for r in refs):
                        raise H3Error('refs 는 [{"type": "image|video|audio", "path": "..."}] 형식')
                    first, last = body.get("first_image"), body.get("last_image")
                    # 웹 요청이 이 컴퓨터의 아무 파일이나 가리켜 공유 inbox 로 복사되게 두지 않는다:
                    # http(s) 주소, 또는 이 서버가 받은 업로드·inbox 안의 파일만.
                    for path in [first, last] + [r["path"] for r in refs]:
                        if path and not app.allowed_input(str(path)):
                            raise H3Error(f"로컬 파일 경로는 업로드(multipart)로 보내라: {path}")
                seconds = parse_int(g("seconds"), "길이(초)", 8)
                if seconds < spec.DURATION_MIN:
                    raise H3Error(f"길이는 {spec.DURATION_MIN}초 이상으로 적어 주세요")
                steps = parse_int(g("steps"), "스텝")
                if steps is not None and not (1 <= steps <= 200):
                    raise H3Error("스텝은 1~200 (비우면 서버 기본)")
                aspect = str(g("aspect_ratio") or "16:9")
                if aspect not in spec.ASPECT_RATIOS:
                    raise H3Error(f"화면비는 {', '.join(spec.ASPECT_RATIOS)} 중 하나")
                job = new_job(prompt=str(g("prompt", "")).strip(), seconds=seconds,
                              aspect_ratio=aspect, seed=parse_seed(g("seed", 0)),
                              task=(g("task") or None), first_image=first, last_image=last, refs=refs,
                              scene_seconds=parse_int(g("scene_seconds"), "장면 길이", 10) or 10,
                              steps=steps, title=str(g("title", "") or ""),
                              negative=(str(g("negative") or "").strip() or None), raw=parse_bool(g("raw", "")),
                              short_edge=parse_size(g("size")))
                if not job.prompt:
                    raise H3Error("프롬프트를 입력하라")
                app.worker.enqueue(job)
                self._json(job.to_json(), 201)
            except (H3Error, ValueError) as e:
                self._json({"error": str(e)}, 400)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8790, endpoint: str = DEFAULT_ENDPOINT,
          ref_endpoint: str = DEFAULT_REF_ENDPOINT, output_dir: Path = OUTPUT_DIR, inbox_dir: str | None = INBOX_DIR,
          poll: float = 3.0, cors_origin: str | None = None):
    app = App(endpoint, ref_endpoint, Path(output_dir), inbox_dir, poll)
    origins = parse_origins(cors_origin if cors_origin is not None else os.environ.get("H3_CORS_ORIGIN"))
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(app, origins))
    except OSError as e:   # 파이썬 traceback 대신 할 일을 한 줄로
        import errno
        import socket
        if isinstance(e, socket.gaierror):
            raise H3Error(f"--host {host} 를 찾을 수 없다 (이 컴퓨터에서만: 127.0.0.1, 다른 컴퓨터에서도: 0.0.0.0)") from None
        if e.errno == errno.EADDRINUSE:
            raise H3Error(f"포트 {port} 를 이미 다른 프로그램이 쓰고 있다. 웹 UI 가 벌써 켜져 있으면 http://{host}:{port} 를 열면 된다. "
                          f"다른 포트로: h3video web --port {port + 1}   (scripts/web.sh 는 전에 띄운 웹 UI 를 끄고 다시 켠다)") from None
        if e.errno in (errno.EACCES, errno.EPERM):
            raise H3Error(f"포트 {port} 는 관리자 권한이 있어야 쓸 수 있다. 1024 이상으로: h3video web --port 8790") from None
        if e.errno == errno.EADDRNOTAVAIL:
            raise H3Error(f"이 컴퓨터에 {host} 주소가 없다 (이 컴퓨터에서만: 127.0.0.1, 다른 컴퓨터에서도: 0.0.0.0)") from None
        raise H3Error(f"웹 서버를 열지 못했다 ({host}:{port}): {e.strerror or e}") from None
    if origins:
        print(f"[h3video web] CORS 허용: {', '.join(origins)}", flush=True)
    print(f"[h3video web] http://{host}:{port}  (H3 서버: {endpoint} / ref: {ref_endpoint}, 출력: {output_dir})", flush=True)
    # systemd's SIGTERM must also flush editing state and stop owned renderers.
    import signal
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    previous_term = signal.signal(signal.SIGTERM, interrupted) if threading.current_thread() is threading.main_thread() else None
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        app.studio.close()
        app.motion.close()
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
