"""로컬호스트 웹 UI (표준 라이브러리 http.server). 프롬프트 입력 → 진행 상황 → 결과 재생.

  h3video web --port 8790
API: GET /api/spec, GET /api/jobs, GET /api/jobs/{id}, POST /api/jobs (multipart), GET /files/{job}/{name}, GET /api/health

CORS: 기본은 끔. 다른 웹 페이지(예: 33modeling 허브의 숏폼 제작)에서 이 서버를 부르려면
  h3video web --cors-origin https://33modeling.pages.dev   (여러 개는 쉼표, 전부 허용은 *)
또는 환경변수 H3_CORS_ORIGIN. 허용한 출처에만 Access-Control-Allow-Origin 을 돌려주고,
사설망 접근 사전 요청(Access-Control-Request-Private-Network)에도 답한다.
"""
from __future__ import annotations

import email
import email.policy
import json
import mimetypes
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import spec
from .client import DEFAULT_ENDPOINT, DEFAULT_REF_ENDPOINT, H3Client, H3Error
from .jobs import INBOX_DIR, OUTPUT_DIR, JobStore, Worker, new_job

HTML = Path(__file__).with_name("ui.html").read_text(encoding="utf-8")


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

        def _cors(self):
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def do_OPTIONS(self):
            self.send_response(204 if cors_origins else 405)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, f: Path):
            """Range 요청을 받는다: 브라우저 <video> 가 구간 이동을 하고, Safari·iOS 는 Range 없이는 재생하지 않는다.
            큰 mp4 를 메모리에 다 올리지 않고 나눠 보낸다."""
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

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            p = u.path
            if p == "/":
                return self._send(200, HTML.encode(), "text/html; charset=utf-8")
            if p == "/api/spec":
                return self._json({"summary": spec.summary(), "duration_min": spec.DURATION_MIN, "duration_max": spec.DURATION_MAX,
                                   "fps": spec.FPS, "short_edge": spec.SHORT_EDGE_DEFAULT, "aspect_ratios": spec.ASPECT_RATIOS,
                                   "tasks": spec.TASKS, "ref_limits": spec.REF_LIMITS, "endpoint": app.endpoint,
                                   "ref_endpoint": app.ref_endpoint, "output_dir": str(app.store.root)})
            if p == "/api/health":
                return self._json({"fl2va": app.client.healthy(), "ref2va": app.ref_client.healthy(),
                                   "queue": len(app.worker.queue), "current": app.worker.current})
            if p == "/api/jobs":
                return self._json(app.store.list())
            if p.startswith("/api/jobs/"):
                job = app.store.get(p.split("/")[3])
                return self._json(job.to_json()) if job else self._json({"error": "없음"}, 404)
            if p.startswith("/files/"):
                rel = urllib.parse.unquote(p[len("/files/"):])
                f = (app.store.root / rel).resolve()
                if app.store.root.resolve() not in f.parents or not f.is_file():
                    return self._json({"error": "없음"}, 404)
                return self._send_file(f)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path != "/api/jobs":
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
                job = new_job(prompt=str(g("prompt", "")).strip(), seconds=int(g("seconds", 8)),
                              aspect_ratio=str(g("aspect_ratio", "16:9")), seed=int(g("seed", 0) or 0),
                              task=(g("task") or None), first_image=first, last_image=last, refs=refs,
                              scene_seconds=int(g("scene_seconds", 10) or 10),
                              steps=(int(g("steps")) if g("steps") else None), title=str(g("title", "") or ""))
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
    httpd = ThreadingHTTPServer((host, port), make_handler(app, origins))
    if origins:
        print(f"[h3video web] CORS 허용: {', '.join(origins)}", flush=True)
    print(f"[h3video web] http://{host}:{port}  (H3 서버: {endpoint} / ref: {ref_endpoint}, 출력: {output_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
