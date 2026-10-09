"""AI 영상 서버 어댑터 (표준 라이브러리만). 웹(src/ai/backends.js)과 같은 요청 형식을 쓴다.

- sglang : SGLang `/v1/videos` (MiniMax-H3 형식, minimax-h3-video/src/h3video/client.py 와 같은 JSON)
           POST /v1/videos → {"id"} · GET /v1/videos/{id} → {"status","progress"} · GET /v1/videos/{id}/content → mp4
- vllm   : vLLM-Omni `/v1/videos` (multipart: prompt, seconds, size, seed, input_reference)
- h3video: minimax-h3-video 웹 서버 (POST /api/jobs multipart · GET /api/jobs/{id} · GET /files/{job}/{name})
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import math
import mimetypes
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

H3_SHORT_EDGE = 768
VLLM_SHORT_EDGE = 720
H3_TASKS = {"t2va": "텍스트 → 영상+오디오", "fl2va": "첫 프레임 이미지 + 텍스트 → 영상+오디오",
            "ref2va": "참조(이미지≤9·영상≤3·오디오≤3, 합계≤12) + 텍스트 → 영상+오디오"}
# MiniMax-H3 공식 사양(minimax-h3-video/src/h3video/spec.py): 장면 4~15초, 24fps, 짧은 변 768px.
# 생성 영상은 짧은 변 768 기반(9:16 이면 약 768×1366)이고, 합성 단계에서 720×1280 / 1080×1920 으로 맞춘다.
H3_LIMITS = {"duration": (4, 15), "fps": 24, "short_edge": 768, "ref_video": 3, "ref_image": 9, "ref_audio": 3, "ref_total": 12,
             "ref_clip_seconds": (2, 15), "ref_clip_total_seconds": 15}
ASPECTS = ["9:16", "16:9", "1:1", "4:3", "3:4", "21:9", "auto"]


class BackendError(RuntimeError):
    def __init__(self, msg: str, retryable: bool = False, code: int | None = None):
        super().__init__(msg)
        self.retryable = retryable   # 연결 끊김·시간 초과·5xx 게이트웨이: 잠시 뒤 다시 하면 될 수 있음
        self.code = code


ERROR_HINTS = [
    (("out of memory", "cuda oom", "oom"), "GPU 메모리가 부족합니다. 장면 길이(duration)나 gen_size 를 줄이거나 다른 작업이 GPU 를 쓰는지 확인하세요"),
    (("no such file", "not found: file", "file://", "filenotfound"), "서버가 참조 파일을 읽지 못했습니다. --inbox-dir 로 서버와 공유된 폴더에 복사하거나 h3video 웹 서버를 쓰세요"),
    (("no such video", "not found", "404"), "서버가 이 작업을 모릅니다. 서버가 재시작돼 작업 목록이 지워졌을 수 있습니다"),
    (("timed out", "timeout", "시간 초과"), "서버 응답이 너무 늦습니다. 서버 부하나 네트워크(SSH 터널)를 확인하세요"),
    (("connection refused", "연결하지 못했습니다", "connection reset", "remote end closed"), "서버가 꺼졌거나 SSH 터널이 끊겼습니다. `shorts server check` 로 확인하세요"),
    (("401", "403", "unauthorized", "인증"), "인증에 실패했습니다. 서버에 --api-key 를 걸었다면 SHORTS_API_KEY 를 설정하세요"),
    (("aspect", "duration", "short_edge", "invalid", "validation", "400"), "서버가 요청 값을 거절했습니다. 길이·화면비·gen_size 가 서버(모델) 사양 안인지 확인하세요"),
]


def explain_error(msg: str | None) -> str:
    """서버 오류 문장에 한국어 설명을 붙인다."""
    low = (msg or "").lower()
    for keys, hint in ERROR_HINTS:
        if any(k in low for k in keys):
            return hint
    return "서버가 생성에 실패했습니다. 서버 로그(serve.sh 가 남기는 로그)를 확인하세요"


_H3 = None


def h3video_client():
    """같은 venv 에 minimax-h3-video 가 설치돼 있으면(pip install -e) 그 client 모듈을 쓴다. 없으면 None(내장 구현)."""
    global _H3
    if _H3 is None:
        if os.environ.get("SHORTS_NO_H3VIDEO"):
            _H3 = False
        else:
            try:
                from h3video import client as h3  # type: ignore
                _H3 = h3
            except Exception:  # noqa: BLE001
                _H3 = False
    return _H3 or None


def seconds_of(req: dict) -> int:
    """장면 길이 → 서버에 보낼 정수 초. 웹(Math.round)과 같은 반올림(파이썬 round 는 4.5 → 4 라 쓰지 않는다)."""
    return int(math.floor(float(req["duration"]) + 0.5))


def gen_size_of(req: dict, default_short: int) -> tuple[int, str]:
    """요청의 gen_size → (짧은 변, "WxH"). 숫자면 ratio 로 WxH 를 계산, "WxH" 면 그대로."""
    g = req.get("gen_size")
    if isinstance(g, str) and "x" in g:
        w, h = (int(x) for x in g.split("x"))
        return min(w, h), f"{w}x{h}"
    short = int(g) if g else default_short
    return short, size_for_ratio(req.get("ratio") or "9:16", short)


def size_for_ratio(ratio: str, short_edge: int) -> str:
    if ratio in ("auto", None):
        ratio = "9:16"
    a, b = (int(x) for x in ratio.split(":"))
    if a >= b:
        h = short_edge
        w = int(round(short_edge * a / b / 2) * 2)
    else:
        w = short_edge
        h = int(round(short_edge * b / a / 2) * 2)
    return f"{w}x{h}"


def auth_headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def encode_multipart(fields: list[tuple[str, str]], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----shorts" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    for name, filename, data, ctype in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class Http:
    def __init__(self, base: str, api_key: str | None = None, timeout: float = 120.0):
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None, raw: bool = False):
        headers = {"Accept": "*/*", **auth_headers(self.api_key)}
        if ctype:
            headers["Content-Type"] = ctype
        url = path if path.startswith("http") else self.base + path
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            msg = e.read()[:400].decode(errors="replace")
            e.close()
            if e.code in (401, 403):
                raise BackendError(f"{method} {path}: 인증 실패(HTTP {e.code}). 서버에 --api-key 를 걸었다면 SHORTS_API_KEY 를 설정하세요",
                                   code=e.code) from e
            raise BackendError(f"{method} {path}: HTTP {e.code} {msg}", retryable=500 <= e.code < 600, code=e.code) from e
        except urllib.error.URLError as e:
            raise BackendError(f"서버에 연결하지 못했습니다 ({self.base}): {e.reason}. 주소·포트·SSH 터널을 확인하세요",
                               retryable=True) from e
        except (TimeoutError, ConnectionError, http.client.HTTPException) as e:
            raise BackendError(f"{method} {path}: 응답 시간 초과·연결 끊김 ({self.base}): {e}", retryable=True) from e
        if raw:
            return payload
        try:
            return json.loads(payload or b"{}")
        except json.JSONDecodeError as e:
            raise BackendError(f"{method} {path}: JSON 이 아닌 응답 {payload[:120]!r}") from e

    def get_json(self, path: str):
        return self.request("GET", path)

    def post_json(self, path: str, obj: dict):
        return self.request("POST", path, json.dumps(obj, ensure_ascii=False).encode(), "application/json")


def guess_type(path: str) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def media_kind(path: str) -> str:
    t = guess_type(path)
    return "image" if t.startswith("image/") else "audio" if t.startswith("audio/") else "video"


class Stager:
    """SGLang 은 conditions[].uri 를 *서버 프로세스*가 읽는다. 로컬 파일을 서버가 읽을 수 있는 URI 로 바꾼다.
    - inbox_dir 가 있으면 그 폴더(서버와 공유된 볼륨)로 복사하고 file:// (또는 inbox_uri 접두사)
    - inline 이면 data:<type>;base64,... URI — SGLang MiniMax-H3 는 conditions[].uri 로 file://(서버 로컬)·http(s)·
      data:;base64·base64:// 를 받는다(sglang .../minimax_h3/material_io.py minimax_h3_localize_material_uri).
      원격 서버(SSH 터널)라도 파일을 공유하지 않고 보낼 수 있지만 요청 본문이 그만큼 커진다.
    - 그 외 로컬 절대경로 file:// (서버가 같은 컴퓨터일 때)"""

    def __init__(self, inbox_dir: str | None = None, inbox_uri: str | None = None, inline: bool = False):
        self.inbox_dir, self.inbox_uri, self.inline = inbox_dir, inbox_uri, inline

    def uri(self, path: str) -> str:
        s = str(path)
        if s.startswith(("http://", "https://", "file://", "data:")):
            return s
        p = Path(s).expanduser().resolve()
        if not p.is_file():
            raise BackendError(f"입력 파일이 없습니다: {p}")
        if self.inline:
            return f"data:{guess_type(str(p))};base64," + base64.b64encode(p.read_bytes()).decode()
        if self.inbox_dir:
            inbox = Path(self.inbox_dir).expanduser().resolve()
            inbox.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
            dest = inbox / f"{digest}-{p.name}"
            if not dest.exists():
                shutil.copy2(p, dest)
            if self.inbox_uri:  # 파일 이름의 # ? % 공백 등은 URI 로 인코딩(서버가 urlsplit + unquote 로 읽음)
                return self.inbox_uri.rstrip("/") + "/" + urllib.parse.quote(dest.name)
            return dest.as_uri()
        return p.as_uri()


def norm_progress(v) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, x / 100 if x > 1 else x))


class SGLangBackend:
    name = "sglang"

    def __init__(self, server: str, api_key: str | None = None, stager: Stager | None = None, model: str | None = None,
                 ref_server: str | None = None):
        self.http = Http(server, api_key)
        self.ref_http = Http(ref_server, api_key) if ref_server else self.http
        self.stager = stager or Stager()
        self.model = model

    def build_body(self, req: dict, stage=True) -> dict:
        """h3video(minimax-h3-video) 의 client.VideoRequest 와 같은 JSON. 그 패키지가 import 되면 그것으로 만든다."""
        uri = self.stager.uri if stage else (lambda p: f"<{Path(str(p)).name} 경로>")
        conds = []
        if req["task"] == "fl2va" and req.get("image"):
            conds.append(("image", uri(req["image"]), "keyframe", 0))
        if req["task"] == "ref2va":
            for r in req.get("refs", []):
                conds.append((media_kind(r["path"]), uri(r["path"]), "reference", None))
            if req.get("image"):
                conds.append(("image", uri(req["image"]), "reference", None))
        h3 = h3video_client()
        if h3:
            vr = h3.VideoRequest(prompt=req["prompt"], task=req["task"], duration_seconds=seconds_of(req),
                                 aspect_ratio=req["ratio"], short_edge=gen_size_of(req, H3_SHORT_EDGE)[0], seed=int(req.get("seed") or 0),
                                 conditions=[h3.Condition(t, u, role, fi) for t, u, role, fi in conds])
            try:
                vr.validate()
            except h3.H3Error as e:
                raise BackendError(f"H3 요청 검사 실패: {e}") from e
            body = vr.to_json()
        else:
            cj = []
            for t, u, role, fi in conds:
                d = {"type": t, "uri": u, "role": role}
                if fi is not None:
                    d["frame_index"] = fi
                cj.append(d)
            body = {"task": req["task"], "prompt": req["prompt"], "conditions": cj,
                    "target": {"short_edge": gen_size_of(req, H3_SHORT_EDGE)[0], "aspect_ratio": req["ratio"],
                               "duration_seconds": seconds_of(req)},
                    "seed": int(req.get("seed") or 0)}
        if self.model:
            body["model"] = self.model
        return body

    def _http_for(self, task: str) -> Http:
        return self.ref_http if task == "ref2va" else self.http

    def submit(self, req: dict) -> str:
        resp = self._http_for(req["task"]).post_json("/v1/videos", self.build_body(req))
        vid = resp.get("id")
        if not vid:
            raise BackendError(f"응답에 id 가 없습니다: {str(resp)[:200]}")
        return str(vid)

    def status(self, rid: str, task: str = "t2va") -> dict:
        st = self._http_for(task).get_json(f"/v1/videos/{urllib.parse.quote(rid)}")
        s = st.get("status")
        state = "done" if s in ("completed", "succeeded") else "failed" if s in ("failed", "error", "cancelled") else (
            "queued" if s == "queued" else "running")
        err = st.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        return {"state": state, "progress": norm_progress(st.get("progress")), "has_progress": st.get("progress") is not None,
                "error": err, "raw": st}

    def download(self, rid: str, out: str, task: str = "t2va") -> str:
        data = self._http_for(task).request("GET", f"/v1/videos/{urllib.parse.quote(rid)}/content", raw=True)
        if len(data) < 1000:
            raise BackendError(f"받은 영상이 너무 작습니다 ({len(data)} bytes)")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(data)
        return out


class VLLMBackend(SGLangBackend):
    name = "vllm"

    def build_form(self, req: dict, read: bool = True) -> tuple[list, list]:
        fields = [("prompt", req["prompt"]), ("seconds", str(seconds_of(req))),
                  ("size", gen_size_of(req, VLLM_SHORT_EDGE)[1]), ("seed", str(int(req.get("seed") or 0)))]
        if self.model:
            fields.append(("model", self.model))
        ref = req.get("image") or (req.get("refs") or [{}])[0].get("path")
        files = []
        if ref:
            p = Path(ref)
            files.append(("input_reference", p.name, p.read_bytes() if read else b"", guess_type(str(p))))
        return fields, files

    def build_body(self, req: dict, stage=True) -> dict:
        """--dry-run(stage=False)도 보낼 필드를 모두 보여 준다(파일은 읽지 않고 이름만)."""
        fields, files = self.build_form(req, read=stage)
        return {"multipart": dict(fields), "files": [f"{f[0]}={f[1]}" for f in files]}

    def submit(self, req: dict) -> str:
        fields, files = self.build_form(req)
        body, ctype = encode_multipart(fields, files)
        resp = self.http.request("POST", "/v1/videos", body, ctype)
        vid = resp.get("id")
        if not vid:
            raise BackendError(f"응답에 id 가 없습니다: {str(resp)[:200]}")
        return str(vid)

    def _http_for(self, task: str) -> Http:
        return self.http


class H3VideoBackend:
    """minimax-h3-video 의 `h3video web` 서버. 파일을 multipart 로 올리면 서버가 inbox 로 옮겨 SGLang 에 넘긴다."""
    name = "h3video"

    def __init__(self, server: str, api_key: str | None = None, **_):
        self.http = Http(server, api_key)

    def build_form(self, req: dict, read: bool = True) -> tuple[list, list]:
        fields = [("prompt", req["prompt"]), ("seconds", str(seconds_of(req))), ("aspect_ratio", req["ratio"]),
                  ("seed", str(int(req.get("seed") or 0))), ("title", req.get("title") or "shorts")]
        files = []

        def add(key, path):
            p = Path(path)
            files.append((key, p.name, p.read_bytes() if read else b"", guess_type(str(p))))
        if req.get("image") and req["task"] != "ref2va":
            add("first_image", req["image"])
        for r in req.get("refs", []):
            add({"image": "ref_images", "audio": "ref_audios"}.get(media_kind(str(r["path"])), "ref_videos"), r["path"])
        if req["task"] == "ref2va" and req.get("image"):
            add("ref_images", req["image"])
        return fields, files

    def build_body(self, req: dict, stage=True) -> dict:
        """--dry-run(stage=False)도 보낼 필드를 모두 보여 준다(파일은 읽지 않고 이름만)."""
        fields, files = self.build_form(req, read=stage)
        return {"multipart": dict(fields), "files": [f"{f[0]}={f[1]}" for f in files]}

    def submit(self, req: dict) -> str:
        fields, files = self.build_form(req)
        body, ctype = encode_multipart(fields, files)
        resp = self.http.request("POST", "/api/jobs", body, ctype)
        if resp.get("error"):
            raise BackendError(f"h3video 서버가 거절했습니다: {resp['error']}")
        return str(resp["id"])

    def status(self, rid: str, task: str = "t2va") -> dict:
        j = self.http.get_json(f"/api/jobs/{urllib.parse.quote(rid)}")
        s = j.get("status")
        scenes = j.get("scenes") or []
        prog = sum(norm_progress(x.get("progress")) for x in scenes) / len(scenes) if scenes else 0.0
        state = "done" if s == "completed" else "failed" if s == "failed" else "queued" if s == "pending" else "running"
        return {"state": state, "progress": prog, "has_progress": bool(scenes), "error": j.get("error"), "raw": j}

    def download(self, rid: str, out: str, task: str = "t2va") -> str:
        j = self.http.get_json(f"/api/jobs/{urllib.parse.quote(rid)}")
        if not j.get("output"):
            raise BackendError("작업에 결과 파일이 없습니다")
        name = urllib.parse.quote(Path(j["output"]).name)
        data = self.http.request("GET", f"/files/{urllib.parse.quote(rid)}/{name}", raw=True)
        if len(data) < 1000:
            raise BackendError(f"받은 영상이 너무 작습니다 ({len(data)} bytes)")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(data)
        return out


BACKENDS = {"sglang": SGLangBackend, "vllm": VLLMBackend, "h3video": H3VideoBackend}


def detect_backend(server: str, api_key: str | None = None, timeout: float = 10) -> tuple[str, dict]:
    """서버 종류 자동 판별: /api/spec 이 있으면 h3video, /v1/models 의 owned_by 로 vllm/sglang."""
    http = Http(server, api_key, timeout=timeout)
    info: dict = {}
    try:
        spec = http.get_json("/api/spec")
        if isinstance(spec, dict) and "tasks" in spec:
            return "h3video", {"spec": spec}
    except BackendError as e:
        if "연결하지 못했습니다" in str(e):
            raise
    try:
        models = http.get_json("/v1/models")
        info["models"] = models
        owners = " ".join(str(m.get("owned_by", "")) for m in (models.get("data") or []) if isinstance(m, dict)).lower()
        if "vllm" in owners:
            return "vllm", info
        return "sglang", info
    except BackendError:
        pass
    try:
        http.get_json("/health")
        return "sglang", info
    except BackendError as e:
        raise BackendError(f"서버 종류를 알아내지 못했습니다 ({server}). --backend sglang|vllm|h3video 로 지정하세요") from e


def make_backend(name: str, server: str, api_key: str | None = None, stager: Stager | None = None,
                 model: str | None = None, ref_server: str | None = None):
    if name == "auto":
        name, _ = detect_backend(server, api_key)
    if name == "h3video":
        return H3VideoBackend(server, api_key)
    cls = BACKENDS[name]
    return cls(server, api_key, stager=stager, model=model, ref_server=ref_server)


def server_check(server: str, backend: str = "auto", api_key: str | None = None, timeout: float = 10) -> dict:
    """shorts server check — 서버 상태·모델·모드·사양. doctor 는 짧은 timeout 으로 부른다."""
    name, info = (detect_backend(server, api_key, timeout) if backend == "auto" else (backend, {}))
    http = Http(server, api_key, timeout=timeout)
    out: dict = {"server": server, "backend": name, "ok": True}
    if name == "h3video":
        spec = info.get("spec") or http.get_json("/api/spec")
        out["modes"] = spec.get("tasks")
        out["limits"] = {"duration": [spec.get("duration_min"), spec.get("duration_max")], "aspect_ratios": spec.get("aspect_ratios"),
                         "ref_limits": spec.get("ref_limits")}
        try:
            out["health"] = http.get_json("/api/health")
        except BackendError as e:
            out["health"] = {"error": str(e)}
        out["model"] = "MiniMax-H3 (h3video 경유: " + str(spec.get("endpoint")) + ")"
    else:
        models = info.get("models")
        if models is None:
            try:
                models = http.get_json("/v1/models")
            except BackendError as e:
                models = {"error": str(e)}
        ids = [m.get("id") for m in (models.get("data") or [])] if isinstance(models, dict) else []
        out["model"] = ", ".join(i for i in ids if i) or "(알 수 없음)"
        try:
            http.get_json("/health")
            out["health"] = "ok"
        except BackendError as e:
            out["health"] = str(e)
        if name == "sglang":
            out["modes"] = H3_TASKS
            out["limits"] = {"duration": list(H3_LIMITS["duration"]), "fps": H3_LIMITS["fps"], "short_edge": H3_LIMITS["short_edge"],
                             "aspect_ratios": ASPECTS, "ref_limits": {"video": 3, "image": 9, "audio": 3, "total": 12}}
        else:
            out["modes"] = {"t2v": "텍스트 → 영상", "i2v": "input_reference 1개(이미지/영상) + 텍스트 → 영상"}
            out["limits"] = {"duration": "모델마다 다름", "ref_limits": {"total": 1}}
    return out


def check_h3_limits(scene: dict, ref_durations: dict[str, float] | None = None) -> list[str]:
    """보내기 전에 H3 사양 한도 검사(한국어 오류)."""
    errs = []
    lo, hi = H3_LIMITS["duration"]
    if not (lo <= scene["duration"] <= hi):
        errs.append(f"장면 길이는 {lo}~{hi}초입니다 (지금 {scene['duration']}초)")
    if scene.get("ratio") not in ASPECTS:
        errs.append(f"화면비는 {', '.join(ASPECTS)} 중 하나입니다 (지금 {scene.get('ratio')})")
    short = gen_size_of(scene, H3_SHORT_EDGE)[0]
    if short > H3_LIMITS["short_edge"]:
        errs.append(f"생성 해상도 짧은 변은 {H3_LIMITS['short_edge']}px 이하입니다(로컬 H3-Base 상한, 지금 {short}px). "
                    "gen_size 를 768 이하로 낮추세요")
    vids = [r for r in scene.get("refs", []) if media_kind(r["path"]) == "video"]
    if len(vids) > H3_LIMITS["ref_video"]:
        errs.append(f"참조 영상은 최대 {H3_LIMITS['ref_video']}개입니다 (지금 {len(vids)}개)")
    imgs = [r for r in scene.get("refs", []) if media_kind(r["path"]) == "image"]
    total = len(scene.get("refs", [])) + (1 if scene.get("task") == "ref2va" and scene.get("image") else 0)
    if len(imgs) > H3_LIMITS["ref_image"]:
        errs.append(f"참조 이미지는 최대 {H3_LIMITS['ref_image']}개입니다 (지금 {len(imgs)}개)")
    if total > H3_LIMITS["ref_total"]:
        errs.append(f"ref2va 참조는 합계 {H3_LIMITS['ref_total']}개 이하입니다 (지금 {total}개)")
    if ref_durations:
        total = 0.0
        a, b = H3_LIMITS["ref_clip_seconds"]
        for r in vids:
            d = ref_durations.get(r["path"])
            if d is None:
                continue
            if r.get("end") is not None:
                d = min(d, r["end"]) - (r.get("start") or 0)
            elif r.get("start"):
                d = d - r["start"]
            total += d
            if d < a:
                errs.append(f"참조 영상 {Path(r['path']).name}: {a}초 이상이어야 합니다 (지금 {d:.1f}초)")
            if d > b:
                errs.append(f"참조 영상 {Path(r['path']).name}: {b}초 이하여야 합니다 (지금 {d:.1f}초). start/end 로 구간을 줄이세요")
        if total > H3_LIMITS["ref_clip_total_seconds"] + 0.01:
            errs.append(f"참조 영상 길이 합계는 {H3_LIMITS['ref_clip_total_seconds']}초 이하여야 합니다 (지금 {total:.1f}초)")
    return errs


def wait_and_download(backend, rid: str, task: str, out: str, poll: float = 3.0, timeout: float = 3600.0,
                      on_progress: Callable[[dict], None] | None = None, sleep=time.sleep) -> str:
    t0 = time.monotonic()
    while True:
        st = backend.status(rid, task)
        if on_progress:
            on_progress(st)
        if st["state"] == "done":
            return backend.download(rid, out, task)
        if st["state"] == "failed":
            raise BackendError(f"생성 실패 ({rid}): {st.get('error') or '이유 없음'}")
        if time.monotonic() - t0 > timeout:
            raise BackendError(f"대기 시간 {timeout:.0f}초를 넘었습니다 ({rid}). 나중에 `shorts resume {rid}` 로 이어 받으세요")
        sleep(poll)
