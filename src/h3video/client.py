"""SGLang `/v1/videos` 클라이언트 (표준 라이브러리만 사용).

  POST {endpoint}/v1/videos                 → {"id": ...}
  GET  {endpoint}/v1/videos/{id}            → {"status": queued|in_progress|completed|failed, "progress": 0~1, "error": ...}
  GET  {endpoint}/v1/videos/{id}/content    → mp4 바이트
conditions[].uri 의 file:// 경로는 *서버 프로세스*가 읽으므로 로컬 파일은 inbox(공유 볼륨)로 복사해 넘긴다.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import spec

DEFAULT_ENDPOINT = os.environ.get("H3_ENDPOINT", "http://127.0.0.1:30010")
DEFAULT_REF_ENDPOINT = os.environ.get("H3_REF_ENDPOINT", "http://127.0.0.1:30011")


class H3Error(RuntimeError):
    pass


@dataclass
class Condition:
    type: str                 # image | video | audio | video_audio
    uri: str                  # http(s):// 또는 file://
    role: str = "reference"   # reference | keyframe
    frame_index: int | None = None   # keyframe: 0=첫 프레임, -1=끝 프레임

    def to_json(self) -> dict:
        d = {"type": self.type, "uri": self.uri, "role": self.role}
        if self.frame_index is not None:
            d["frame_index"] = self.frame_index
        return d


@dataclass
class VideoRequest:
    prompt: str
    task: str = "t2va"                       # t2va | fl2va | ref2va
    duration_seconds: int = 8
    aspect_ratio: str = "16:9"
    short_edge: int = spec.SHORT_EDGE_DEFAULT
    seed: int = 0
    conditions: list[Condition] = field(default_factory=list)
    num_inference_steps: int | None = None
    negative_prompt: str | None = None
    num_outputs: int = 1
    rewrite: bool = True                     # Diffusers 서버가 공식 형식으로 다듬는다 (False = 쓴 그대로)

    def validate(self) -> None:
        if self.task not in spec.TASKS:
            raise H3Error(f"task 는 {list(spec.TASKS)} 중 하나: {self.task}")
        if not (spec.DURATION_MIN <= self.duration_seconds <= spec.DURATION_MAX):
            raise H3Error(f"duration 은 {spec.DURATION_MIN}~{spec.DURATION_MAX}초: {self.duration_seconds}")
        if self.aspect_ratio not in spec.ASPECT_RATIOS:
            raise H3Error(f"aspect_ratio 는 {spec.ASPECT_RATIOS} 중 하나: {self.aspect_ratio}")
        if not self.prompt.strip():
            raise H3Error("prompt 가 비었다")
        kf = [c for c in self.conditions if c.role == "keyframe"]
        if self.task == "t2va" and self.conditions:
            raise H3Error("t2va 는 conditions 없이 호출한다 (이미지가 있으면 fl2va)")
        if self.task == "fl2va" and len(kf) > 2:
            raise H3Error("fl2va 키프레임은 최대 2장")
        if self.task == "ref2va":
            counts = {}
            for c in self.conditions:
                counts[c.type] = counts.get(c.type, 0) + 1
            for t, lim in (("image", spec.REF_LIMITS["image"]), ("video", spec.REF_LIMITS["video"]), ("audio", spec.REF_LIMITS["audio"])):
                if counts.get(t, 0) > lim:
                    raise H3Error(f"ref2va {t} 는 최대 {lim}개")
            if len(self.conditions) > spec.REF_LIMITS["total"]:
                raise H3Error(f"ref2va 레퍼런스는 합계 {spec.REF_LIMITS['total']}개 이하")

    def to_json(self) -> dict:
        body = {
            "task": self.task,
            "prompt": self.prompt,
            "conditions": [c.to_json() for c in self.conditions],
            "target": {"short_edge": self.short_edge, "aspect_ratio": self.aspect_ratio,
                       "duration_seconds": self.duration_seconds},
            "seed": self.seed,
        }
        if self.num_inference_steps:
            body["num_inference_steps"] = self.num_inference_steps
        if self.negative_prompt:
            body["negative_prompt"] = self.negative_prompt
        if self.num_outputs and self.num_outputs != 1:
            body["num_outputs_per_prompt"] = self.num_outputs
        if not self.rewrite:
            body["rewrite"] = False
        return body


def stage_input(path: str | os.PathLike, inbox_dir: str | os.PathLike | None) -> str:
    """로컬 파일을 서버가 읽을 수 있는 file:// URI 로. http(s) 는 그대로."""
    s = str(path)
    if s.startswith(("http://", "https://", "file://")):
        return s
    p = Path(s).expanduser().resolve()
    if not p.is_file():
        raise H3Error(f"입력 파일 없음: {p}")
    if inbox_dir:
        inbox = Path(inbox_dir).expanduser().resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        if inbox not in p.parents:
            digest = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
            dest = inbox / f"{digest}-{p.name}"
            if not dest.exists():
                shutil.copy2(p, dest)
            p = dest
    return p.as_uri()


class H3Client:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 60.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    # --- HTTP ---
    def _request(self, method: str, path: str, body: dict | None = None, raw: bool = False, timeout: float | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.endpoint + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            raise H3Error(f"{method} {path} -> HTTP {e.code}: {e.read()[:500].decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise H3Error(f"{method} {path} 연결 실패 ({self.endpoint}): {e.reason}") from e
        except (OSError, http.client.HTTPException) as e:
            # 연결 직후 끊김(SSH 터널은 살아 있는데 서버가 꺼짐), 응답 중 시간 초과 등: urlopen 이 URLError 로 감싸지 않는 경우
            raise H3Error(f"{method} {path} 연결이 끊겼다 ({self.endpoint}): {type(e).__name__}: {e}") from e
        if raw:
            return payload
        try:
            return json.loads(payload or b"{}")
        except json.JSONDecodeError as e:
            raise H3Error(f"{method} {path} JSON 아님: {payload[:200]!r}") from e

    def healthy(self, timeout: float = 5.0) -> bool:
        """짧게 확인한다: 서버가 멈춰 있을 때 웹 /api/health 나 TUI 화면이 60초씩 굳지 않게."""
        for path in ("/health", "/v1/models"):
            try:
                self._request("GET", path, timeout=timeout)
                return True
            except H3Error:
                continue
        return False

    # --- API ---
    def submit(self, req: VideoRequest) -> str:
        req.validate()
        resp = self._request("POST", "/v1/videos", req.to_json())
        vid = resp.get("id")
        if not vid:
            raise H3Error(f"응답에 id 없음: {resp}")
        return str(vid)

    def rewrite(self, req: VideoRequest, timeout: float = 3600.0) -> dict:
        """Diffusers 서버에서 다듬은 프롬프트만 받는다 (생성 안 함). 생성 중이면 그 뒤에 처리된다."""
        req.validate()
        return self._request("POST", "/v1/prompts/rewrite", req.to_json(), timeout=timeout)

    def status(self, video_id: str) -> dict:
        return self._request("GET", f"/v1/videos/{video_id}")

    def content(self, video_id: str) -> bytes:
        return self._request("GET", f"/v1/videos/{video_id}/content", raw=True)

    def wait(self, video_id: str, poll: float = 3.0, timeout: float = 3600.0,
             on_progress: Callable[[dict], None] | None = None) -> dict:
        t0 = time.monotonic()
        last = None
        while True:
            st = self.status(video_id)
            if on_progress and st != last:
                on_progress(st)
            last = st
            s = st.get("status")
            if s == "completed":
                return st
            if s == "failed":
                raise H3Error(f"생성 실패 {video_id}: {st.get('error')}")
            if time.monotonic() - t0 > timeout:
                raise H3Error(f"대기 시간 초과 {video_id} ({int(timeout)}초, 마지막 상태 {s}). 서버에서는 계속될 수 있으니 "
                              f"끝난 뒤 h3video fetch {video_id} 로 받는다(레퍼런스 영상이면 --ref). 한도는 H3_WAIT_TIMEOUT(초)")
            time.sleep(poll)

    def download(self, video_id: str, out_path: str | os.PathLike) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.content(video_id)
        if len(data) < 1000:
            raise H3Error(f"다운로드 내용이 너무 작다 ({len(data)} bytes): {data[:200]!r}")
        out.write_bytes(data)
        return out

    def generate(self, req: VideoRequest, out_path: str | os.PathLike, poll: float = 3.0,
                 timeout: float = 3600.0, on_progress: Callable[[dict], None] | None = None) -> Path:
        vid = self.submit(req)
        st = self.wait(vid, poll=poll, timeout=timeout, on_progress=on_progress)
        out = self.download(vid, out_path)
        Path(str(out) + ".json").write_text(json.dumps({"id": vid, "request": req.to_json(), "prompt_used": st.get("prompt_used")},
                                                       ensure_ascii=False, indent=2))
        return out
