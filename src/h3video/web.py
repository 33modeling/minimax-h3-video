"""로컬호스트 웹 UI (표준 라이브러리 http.server). 프롬프트 입력 → 진행 상황 → 결과 재생.

  h3video web --port 8790
API: GET /api/spec, GET /api/jobs, GET /api/jobs/{id}, POST /api/jobs (multipart), GET /files/{job}/{name}, GET /api/health
"""
from __future__ import annotations

import email
import email.policy
import json
import mimetypes
import os
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


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "h3video/0.1"

        def log_message(self, fmt, *args):  # 조용히
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
                data = f.read_bytes()
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, data, ctype)
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
                    first, last = body.get("first_image"), body.get("last_image")
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
          poll: float = 3.0):
    app = App(endpoint, ref_endpoint, Path(output_dir), inbox_dir, poll)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"[h3video web] http://{host}:{port}  (H3 서버: {endpoint} / ref: {ref_endpoint}, 출력: {output_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
