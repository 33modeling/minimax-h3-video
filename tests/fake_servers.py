"""테스트용 가짜 서버 (표준 라이브러리 http.server).

- FakeVideoServer: SGLang/vLLM `/v1/videos` 흉내. JSON(SGLang H3 형식)과 multipart(vLLM) 둘 다 받는다.
  상태 조회 몇 번 뒤 completed, /content 는 ffmpeg 로 만든 9:16 mp4(소리 포함). CORS 헤더를 붙인다(웹 e2e 용).
- FakeAnthropic: POST /v1/messages 에 정해 둔 응답을 차례로 돌려준다.

단독 실행: python3 tests/fake_servers.py video 30010 [sglang|vllm]
"""
from __future__ import annotations

import email
import email.policy
import json
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MP4: dict = {}


def fake_mp4(seconds: float = 4.0, color: str = "orange") -> bytes:
    key = (round(seconds, 2), color)
    if key not in _MP4:
        import tempfile
        ff = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as tmp:
            out = f"{tmp}/fake.mp4"
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                f"color=c={color}:s=432x768:r=24:d={seconds},drawbox=x=116:y=284:w=200:h=200:color=black:t=fill",
                                "-f", "lavfi", "-i", f"sine=f=523:r=32000:d={seconds}", "-ac", "2", "-shortest",
                                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                "-movflags", "+faststart", out], capture_output=True)
            data = open(out, "rb").read() if r.returncode == 0 else b""
        if len(data) < 1000:
            raise RuntimeError("ffmpeg 로 가짜 영상을 만들지 못함: " + r.stderr.decode()[-300:])
        _MP4[key] = data
    return _MP4[key]


def parse_multipart(ctype: str, body: bytes) -> dict:
    msg = email.message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body,
                                   policy=email.policy.HTTP)
    out: dict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        fn = part.get_filename()
        data = part.get_payload(decode=True) or b""
        out.setdefault(name, []).append({"filename": fn, "size": len(data)} if fn else data.decode("utf-8", "replace"))
    return out


class VideoState:
    def __init__(self, mode: str = "sglang", steps: int = 3, fail_prompt: str | None = None):
        self.mode, self.steps, self.fail_prompt = mode, steps, fail_prompt
        self.videos: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.n = 0
        self.lock = threading.Lock()
        self.api_key: str | None = None


def make_video_handler(state: VideoState):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _authed(self) -> bool:
            if state.api_key and self.headers.get("Authorization") != f"Bearer {state.api_key}":
                self._json({"error": "unauthorized"}, 401)
                return False
            return True

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/health":
                return self._json({"ok": True})
            if path == "/v1/models":
                return self._json({"object": "list", "data": [{"id": "MiniMaxAI/MiniMax-H3" if state.mode == "sglang" else "Wan-AI/Wan2.2-TI2V-5B",
                                                               "object": "model", "owned_by": state.mode}]})
            if not self._authed():
                return
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["v1", "videos"]:
                v = state.videos.get(parts[2])
                if not v:
                    return self._json({"error": "no such video"}, 404)
                if len(parts) == 4 and parts[3] == "content":
                    if v["status"] != "completed":
                        return self._json({"error": "not ready"}, 409)
                    return self._send(200, fake_mp4(v["seconds"], v["color"]), "video/mp4")
                with state.lock:
                    v["polls"] += 1
                    if v.get("fail"):
                        v["status"], v["error"] = "failed", "fake failure"
                    elif v["polls"] >= state.steps:
                        v["status"], v["progress"] = "completed", 1.0
                    else:
                        v["status"] = "in_progress"
                        v["progress"] = v["polls"] / state.steps
                prog = v["progress"] * (100 if state.mode == "vllm" else 1)
                return self._json({"id": parts[2], "object": "video", "status": v["status"], "progress": prog, "error": v.get("error")})
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path != "/v1/videos":
                return self._json({"error": "not found"}, 404)
            if not self._authed():
                return
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n)
            ctype = self.headers.get("Content-Type", "")
            if ctype.startswith("multipart/form-data"):
                body = parse_multipart(ctype, raw)
                prompt = (body.get("prompt") or [""])[0]
                seconds = float((body.get("seconds") or ["4"])[0])
                kind = "multipart"
            else:
                body = json.loads(raw or b"{}")
                prompt = body.get("prompt", "")
                seconds = float((body.get("target") or {}).get("duration_seconds") or body.get("seconds") or 4)
                kind = "json"
            if not prompt:
                return self._json({"error": "prompt required"}, 400)
            with state.lock:
                state.n += 1
                vid = f"video_{state.n:04d}"
                colors = ["orange", "magenta", "cyan", "white"]
                state.videos[vid] = {"status": "queued", "progress": 0.0, "polls": 0, "seconds": min(seconds, 6.0),
                                     "color": colors[(state.n - 1) % len(colors)],
                                     "fail": bool(state.fail_prompt and state.fail_prompt in prompt)}
                state.requests.append({"kind": kind, "body": body, "auth": self.headers.get("Authorization")})
            self._json({"id": vid, "object": "video", "status": "queued", "created_at": int(time.time())}, 200)
    return H


class AnthropicState:
    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.headers: list[dict] = []


def make_anthropic_handler(state: AnthropicState):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            state.requests.append(body)
            state.headers.append({k.lower(): v for k, v in self.headers.items()})
            if self.path != "/v1/messages":
                code, obj = 404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}}
            elif not self.headers.get("x-api-key"):
                code, obj = 401, {"type": "error", "error": {"type": "authentication_error", "message": "x-api-key required"}}
            elif not state.replies:
                code, obj = 500, {"type": "error", "error": {"type": "api_error", "message": "no scripted reply"}}
            else:
                code, obj = 200, state.replies.pop(0)
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    return H


def reply_with_json(obj, stop="end_turn") -> dict:
    """Messages API 응답 모양: 구조화 출력이면 text 블록에 JSON 문자열."""
    return {"id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "thinking", "thinking": "", "signature": "fake-sig"},
                        {"type": "text", "text": json.dumps(obj, ensure_ascii=False)}],
            "stop_reason": stop, "stop_details": None, "usage": {"input_tokens": 1200, "output_tokens": 300}}


def serve(handler, port: int = 0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def start_video(mode="sglang", port=0, steps=3, fail_prompt=None, api_key=None):
    st = VideoState(mode, steps, fail_prompt)
    st.api_key = api_key
    httpd, url = serve(make_video_handler(st), port)
    return httpd, st, url


def start_anthropic(replies, port=0):
    st = AnthropicState(replies)
    httpd, url = serve(make_anthropic_handler(st), port)
    return httpd, st, url


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "video"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 30010
    if kind == "video":
        mode = sys.argv[3] if len(sys.argv) > 3 else "sglang"
        httpd, _, url = start_video(mode, port)
        print(f"fake {mode} /v1/videos at {url}", flush=True)
    else:
        print("사용: python3 tests/fake_servers.py video PORT [sglang|vllm]")
        sys.exit(2)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
