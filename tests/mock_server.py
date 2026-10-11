"""SGLang /v1/videos 흉내 — CPU 테스트용. 진행률을 몇 번 올린 뒤 1초짜리 mp4 를 돌려준다."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_MP4 = None


def fake_mp4() -> bytes:
    global FAKE_MP4
    if FAKE_MP4 is None:
        ff = shutil.which("ffmpeg")
        if ff:
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1:r=24",
                                "-f", "lavfi", "-i", "anullsrc=r=32000:cl=stereo", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "pipe:1"], capture_output=True)
            FAKE_MP4 = r.stdout if r.returncode == 0 and len(r.stdout) > 1000 else None
        if FAKE_MP4 is None:
            FAKE_MP4 = b"\x00\x00\x00\x1cftypisom" + b"\x00" * 4096
    return FAKE_MP4


class State:
    def __init__(self):
        self.videos: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.n = 0
        self.lock = threading.Lock()
        self.fail_once: list[str] = []   # 프롬프트에 이 글이 든 요청을 한 번 실패시킨다 (다시 하기 테스트)


def make_handler(state: State, steps: int = 3):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            if self.path == "/health":
                return self._json({"ok": True})
            parts = self.path.strip("/").split("/")
            if len(parts) >= 3 and parts[1] == "videos":
                v = state.videos.get(parts[2])
                if not v:
                    return self._json({"error": "no such video"}, 404)
                if len(parts) == 4 and parts[3] == "content":
                    if v["status"] != "completed":
                        return self._json({"error": "not ready"}, 409)
                    b = fake_mp4()
                    self.send_response(200); self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(b))); self.end_headers(); return self.wfile.write(b)
                with state.lock:
                    v["polls"] += 1
                    if v["polls"] >= steps and v.get("fail"):
                        return self._json({"id": parts[2], "status": "failed", "progress": v["progress"], "error": "mock failure"})
                    if v["polls"] >= steps:
                        v["status"], v["progress"] = "completed", 1.0
                    else:
                        v["status"], v["progress"] = "in_progress", v["polls"] / steps
                return self._json({"id": parts[2], "status": v["status"], "progress": v["progress"], "error": None})
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path != "/v1/videos":
                return self._json({"error": "not found"}, 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if not body.get("prompt"):
                return self._json({"error": "prompt required"}, 400)
            with state.lock:
                state.n += 1
                vid = f"video_{state.n:04d}"
                hit = next((x for x in state.fail_once if x in body["prompt"]), None)
                if hit:
                    state.fail_once.remove(hit)
                state.videos[vid] = {"status": "queued", "progress": 0.0, "polls": 0, "fail": bool(hit)}
                state.requests.append(body)
            self._json({"id": vid, "status": "queued"}, 201)
    return H


def start(port: int = 0, steps: int = 3):
    state = State()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, steps))
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    return httpd, state, f"http://127.0.0.1:{httpd.server_address[1]}"


if __name__ == "__main__":
    import sys
    httpd, _, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 30010)
    print("mock sglang at", url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
