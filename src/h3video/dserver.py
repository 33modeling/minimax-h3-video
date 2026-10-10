"""MiniMax-H3 Diffusers 서버 — SGLang 과 같은 `/v1/videos` API (h3video CLI·웹·숏폼이 그대로 쓴다).

드라이버가 CUDA 12.x 인 노드에서 쓴다. H3 를 지원하는 sglang(0.5.17+)은 CUDA 13 전용이라 그런 노드에서는 못 띄운다.
diffusers 0.41 의 공식 통합(MiniMaxH3ModularPipeline)을 기존 클러스터 레포와 같은 torch 2.7.1(CUDA 12.6)로 돌린다.

  GPU 2장 이상: 텍스트 인코더(Qwen3-VL, 62GB) → 두 번째 장, 영상 모델(62GB)·VAE → 첫 번째 장 (diffusers 문서의 2장 방식)
  GPU 1장:      한 장에서 컴포넌트를 번갈아 올리고 내린다 (ComponentsManager 자동 오프로드)

  POST /v1/videos                → {"id", "status"}
  GET  /v1/videos/{id}           → {"id", "status": queued|in_progress|completed|failed, "progress": 0~1, "error"}
  GET  /v1/videos/{id}/content   → mp4 (영상+스테레오 오디오)
  GET  /health, /v1/models

  python -m h3video.dserver --model-dir DIR --variant fl2va|ref2va [--port 30010] [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import threading
import time
import traceback
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUTPUTS = ["videos", "audio", "sampling_rate"]
TASKS = {"fl2va": ("t2va", "fl2va"), "ref2va": ("ref2va",)}   # 서버 종류 → 받는 작업
REF_LIMITS = {"image": 9, "video": 3, "audio": 3, "total": 12}
MARGIN = os.environ.get("H3_DSERVER_MARGIN", "12GB")   # 활성값 여유 (diffusers 문서의 80GB 한 장 설정)


def log(msg: str) -> None:
    print(f"[dserver {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class BadRequest(ValueError):
    pass


def local_path(uri: str) -> str:
    """file:// → 경로 (http(s) 는 그대로: diffusers 가 직접 받는다)."""
    if uri.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    return uri


def frames_for(seconds: float, per_chunk: int, keep: int, fps: int, lo: float, hi: float) -> tuple[int, float]:
    """길이(초) → VAE 가 다루는 `per_chunk*n + keep` 프레임 수. 올림이 상한을 넘으면 내린다 (15초 → 345프레임)."""
    want = min(max(float(seconds), lo), hi)
    n = round(want * fps)
    up = n
    while up % per_chunk != keep:
        up += 1
    if up <= hi * fps:
        return up, want
    down = n
    while down % per_chunk != keep:
        down -= 1
    return down, want


class Engine:
    """파이프라인 적재와 생성. 작업은 한 번에 하나 (GPU 하나를 나눠 쓰지 않는다)."""

    def __init__(self, model_dir: str, variant: str, devices: list[str], dtype: str = "bfloat16", attn: str | None = None):
        import torch
        from diffusers import ComponentsManager, ModularPipeline
        from diffusers.modular_pipelines import SequentialPipelineBlocks

        self.torch, self.variant = torch, variant
        dt = getattr(torch, dtype)
        load_wf = "fl2va" if variant == "fl2va" else "ref2va"   # t2va·fl2va 는 transformer/, ref2va 는 transformer_ref/
        blocks = ModularPipeline.from_pretrained(model_dir).blocks
        t0 = time.time()
        if len(devices) >= 2:
            log(f"GPU 2장 방식: 텍스트 인코더 → {devices[1]}, 영상 모델·VAE → {devices[0]}")
            first = {n: blocks.sub_blocks.pop(n) for n in ("before_encode", "text_encoder")}
            m_text = ComponentsManager()
            m_text.enable_auto_cpu_offload(device=devices[1], memory_reserve_margin=MARGIN)
            self.cond = SequentialPipelineBlocks.from_blocks_dict(first).init_pipeline(model_dir, components_manager=m_text)
            self.cond.load_components(dtype=dt)
            m_main = ComponentsManager()
            m_main.enable_auto_cpu_offload(device=devices[0], memory_reserve_margin=MARGIN)
            self.pipe = blocks.init_pipeline(model_dir, components_manager=m_main)
            self.pipe.load_components(workflow=load_wf, dtype=dt)
        else:
            log(f"GPU 1장 방식: {devices[0]} 에서 컴포넌트를 번갈아 올린다 (CPU 메모리에 가중치 상주)")
            self.cond = None
            m = ComponentsManager()
            m.enable_auto_cpu_offload(device=devices[0], memory_reserve_margin=MARGIN)
            self.pipe = blocks.init_pipeline(model_dir, components_manager=m)
            self.pipe.load_components(workflow=load_wf, dtype=dt)
        tname = "transformer" if variant == "fl2va" else "transformer_ref"
        self.transformer = getattr(self.pipe, tname, None)
        if self.transformer is None:
            raise RuntimeError(f"{tname} 를 불러오지 못했다: {model_dir}/{tname}")
        if attn:
            self.transformer.set_attention_backend(attn)
            log(f"어텐션 백엔드: {attn}")
        self._steps_done = 0
        self.transformer.register_forward_hook(self._count)
        cfg = self.pipe.config
        self.short_edge = int(getattr(cfg, "canvas_short_edge", 768) or 768)
        self.max_pixels = int(getattr(cfg, "canvas_max_pixels", 768 * 1344) or 768 * 1344)
        log(f"적재 완료 ({time.time() - t0:.0f}초): variant={variant} 작업={'/'.join(TASKS[variant])} "
            f"캔버스 배수={self.pipe.canvas_multiple} 기본 짧은 변={self.short_edge}")

    def _count(self, *_):
        self._steps_done += 1

    # ── 요청 → 파이프라인 입력 ──
    def plan(self, body: dict) -> dict:
        """요청 JSON 을 검사해 생성 계획으로 바꾼다 (미디어는 아직 열지 않는다). 잘못되면 BadRequest."""
        task = body.get("task", "t2va")
        if task not in TASKS[self.variant]:
            raise BadRequest(f"이 서버({self.variant})는 {'/'.join(TASKS[self.variant])} 만 받는다: task={task}")
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise BadRequest("prompt 가 비었다")
        if int(body.get("num_outputs_per_prompt") or 1) != 1:
            raise BadRequest("num_outputs_per_prompt 는 1 만 된다 (여러 개는 seed 를 바꿔 여러 번 요청)")
        target = body.get("target") or {}
        conds = body.get("conditions") or []
        for c in conds:
            uri = str(c.get("uri") or "")
            if not uri:
                raise BadRequest(f"condition 에 uri 가 없다: {c}")
            if uri.startswith("file://") and not os.path.isfile(local_path(uri)):
                raise BadRequest(f"입력 파일이 서버에서 안 보인다: {local_path(uri)} (공유 볼륨의 inbox 에 있어야 한다)")
        keyframes, refs = [], []
        if task == "t2va" and conds:
            raise BadRequest("t2va 는 conditions 없이 (이미지가 있으면 fl2va)")
        if task == "fl2va":
            keyframes = [c for c in conds if c.get("role", "keyframe") == "keyframe"]
            if not 1 <= len(keyframes) <= 2 or len(keyframes) != len(conds):
                raise BadRequest("fl2va 는 키프레임 이미지 1~2장 (frame_index 0=첫 프레임, -1=끝 프레임)")
            slots = []
            for i, c in enumerate(keyframes):
                fi = c.get("frame_index")
                slot = "last_image" if fi == -1 or (fi is None and i == 1) else "image"
                if slot in slots:
                    raise BadRequest(f"키프레임 자리가 겹친다: {slot}")
                slots.append(slot)
            keyframes = list(zip(slots, keyframes))
        if task == "ref2va":
            refs = conds
            kinds = [str(c.get("type", "image")) for c in refs]
            for k in kinds:
                if k not in ("image", "video", "video_audio", "audio"):
                    raise BadRequest(f"레퍼런스 type 은 image/video/video_audio/audio: {k}")
            count = lambda *ks: sum(k in ks for k in kinds)
            if count("image") > REF_LIMITS["image"] or count("video", "video_audio") > REF_LIMITS["video"] \
                    or count("audio") > REF_LIMITS["audio"] or len(kinds) > REF_LIMITS["total"]:
                raise BadRequest("레퍼런스는 이미지 9·영상 3·오디오 3, 합계 12 까지")
            if not refs or count("audio") == len(kinds):
                raise BadRequest("ref2va 는 이미지나 영상 레퍼런스가 하나 이상 있어야 한다 (오디오만은 안 된다)")
        p = self.pipe
        nf, secs = frames_for(target.get("duration_seconds", 8), p.vae_frames_per_chunk, p.vae_latents_per_chunk,
                              p.fps, p.min_duration, p.max_duration)
        steps = body.get("num_inference_steps")
        return {"task": task, "prompt": prompt, "keyframes": keyframes, "refs": refs, "num_frames": nf,
                "seconds": secs, "asked_seconds": target.get("duration_seconds", 8),
                "aspect": str(target.get("aspect_ratio") or "16:9"),
                "short_edge": int(target.get("short_edge") or self.short_edge),
                "steps": int(steps) if steps else 50, "seed": int(body.get("seed") or 0),
                "ignored": [k for k in ("negative_prompt",) if body.get(k)]}

    def _canvas(self, aspect: str, short_edge: int, image=None) -> tuple[int, int]:
        from diffusers.modular_pipelines.minimax_h3.modular_pipeline import resolve_canvas_size
        if aspect == "auto":
            aw, ah = (image.size if image is not None else (16, 9))
        else:
            aw, ah = (float(x) for x in aspect.split(":"))
        max_px = round(self.max_pixels * (short_edge / self.short_edge) ** 2)
        return resolve_canvas_size(aw, ah, self.pipe.canvas_multiple, short_edge, max_px)

    def run(self, plan: dict, out_path: Path, on_progress) -> None:
        from diffusers.modular_pipelines.minimax_h3 import (MiniMaxH3AudioReference, MiniMaxH3ImageReference,
                                                            MiniMaxH3VideoReference)
        from diffusers.utils import load_image
        from diffusers.utils.export_utils import encode_video
        torch = self.torch
        inputs = {"prompt": plan["prompt"], "num_frames": plan["num_frames"], "num_inference_steps": plan["steps"]}
        first_image = None
        for slot, c in plan["keyframes"]:
            inputs[slot] = load_image(local_path(c["uri"])).convert("RGB")
            first_image = first_image or inputs[slot]
        if plan["refs"]:
            refs = []
            for c in plan["refs"]:
                src, kind = local_path(c["uri"]), c.get("type", "image")
                if kind == "image":
                    refs.append(MiniMaxH3ImageReference.from_file(src))
                elif kind in ("video", "video_audio"):
                    r = MiniMaxH3VideoReference.from_file(src)
                    if kind == "video":   # video = 움직임·카메라만, video_audio = 소리까지
                        r = MiniMaxH3VideoReference(frames=r.frames, fps=r.fps)
                    refs.append(r)
                else:
                    refs.append(MiniMaxH3AudioReference.from_file(src))
            inputs["references"] = refs
        h, w = self._canvas(plan["aspect"], plan["short_edge"], first_image)
        inputs.update(height=h, width=w)
        total = max(1, plan["steps"] - 1)   # num_inference_steps 는 끝점 0 을 포함해 센다 → 모델 호출은 하나 적다
        log(f"생성: {plan['task']} {w}x{h} {plan['num_frames']}프레임({plan['num_frames'] / 24:.2f}초) "
            f"steps={plan['steps']} seed={plan['seed']}"
            + (f" 키프레임={[s for s, _ in plan['keyframes']]}" if plan["keyframes"] else "")
            + (f" 레퍼런스={[c.get('type') for c in plan['refs']]}" if plan["refs"] else ""))
        if float(plan["asked_seconds"]) != plan["seconds"]:
            log(f"길이 {plan['asked_seconds']}초 → {plan['seconds']}초 (H3 Diffusers 는 5~15초)")
        if plan["ignored"]:
            log(f"무시: {plan['ignored']} (H3 는 guidance 가 가중치에 들어 있어 negative_prompt 를 쓰지 않는다)")
        stop = threading.Event()

        def ticker():
            while not stop.wait(2):
                on_progress(min(0.99, self._steps_done / total))
        self._steps_done = 0
        threading.Thread(target=ticker, daemon=True).start()
        g = torch.Generator(device="cpu").manual_seed(plan["seed"])
        try:
            if self.cond is None:
                r = self.pipe(**inputs, generator=g, output=OUTPUTS)
            else:
                state = self.cond(**inputs, generator=g)
                gen = {k: inputs[k] for k in ("num_frames", "height", "width", "num_inference_steps")}
                r = self.pipe(state=state, generator=g, output=OUTPUTS, **gen)
        finally:
            stop.set()
        tmp = out_path.with_suffix(".part.mp4")
        encode_video(r["videos"][0], fps=24, output_path=str(tmp), audio=r["audio"][0],
                     audio_sample_rate=r["sampling_rate"])
        tmp.replace(out_path)


class Server:
    def __init__(self, engine: Engine | None, out_dir: Path, variant: str):
        self.engine, self.out_dir, self.variant = engine, out_dir, variant
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        out_dir.mkdir(parents=True, exist_ok=True)

    def meta_path(self, vid: str) -> Path:
        return self.out_dir / f"{vid}.json"

    def save(self, job: dict) -> None:
        tmp = self.meta_path(job["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v for k, v in job.items() if k != "plan"}, ensure_ascii=False, indent=2))
        tmp.replace(self.meta_path(job["id"]))

    def get(self, vid: str) -> dict | None:
        with self.lock:
            if vid in self.jobs:
                return self.jobs[vid]
        p = self.meta_path(vid)   # 서버를 다시 띄운 뒤에도 끝난 결과는 받을 수 있게
        if "/" not in vid and p.is_file():
            job = json.loads(p.read_text())
            if job.get("status") not in ("completed", "failed"):
                job.update(status="failed", error="서버가 생성 도중 꺼졌다")
            return job
        return None

    def submit(self, body: dict) -> dict:
        plan = self.engine.plan(body)
        vid = "video_" + uuid.uuid4().hex[:16]
        job = {"id": vid, "status": "queued", "progress": 0.0, "error": None, "created_at": int(time.time()),
               "task": plan["task"], "prompt": plan["prompt"][:200], "plan": plan}
        with self.lock:
            self.jobs[vid] = job
        self.save(job)
        self.q.put(vid)
        log(f"접수 {vid} ({plan['task']}, 대기 {self.q.qsize()})")
        return {"id": vid, "status": "queued"}

    def worker(self) -> None:
        while True:
            vid = self.q.get()
            job = self.jobs[vid]
            job["status"], job["started_at"] = "in_progress", int(time.time())
            self.save(job)
            out = self.out_dir / f"{vid}.mp4"
            try:
                self.engine.run(job["plan"], out, lambda p, j=job: j.__setitem__("progress", round(p, 3)))
                job.update(status="completed", progress=1.0, file=str(out))
                log(f"완료 {vid} → {out} ({out.stat().st_size / 1e6:.1f}MB, {int(time.time()) - job['started_at']}초)")
            except Exception as e:   # noqa: BLE001 — 실패는 작업 상태로 돌려주고 서버는 계속 돈다
                traceback.print_exc()
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
                log(f"실패 {vid}: {job['error']}")
            job["finished_at"] = int(time.time())
            self.save(job)


def make_handler(srv: Server):
    class H(BaseHTTPRequestHandler):
        server_version = "h3-dserver/1"

        def log_message(self, fmt, *args):   # 접근 로그는 상태 조회 폴링으로 너무 많아 끈다 (생성 로그는 그대로)
            pass

        def _json(self, code: int, obj) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path.rstrip("/")
            if path == "/health":
                return self._json(200, {"status": "ok", "engine": "diffusers", "variant": srv.variant})
            if path == "/v1/models":
                return self._json(200, {"object": "list", "data": [{"id": "MiniMaxAI/MiniMax-H3", "object": "model",
                                                                    "engine": "diffusers", "variant": srv.variant}]})
            parts = path.split("/")
            if len(parts) in (4, 5) and parts[1:3] == ["v1", "videos"]:
                job = srv.get(parts[3])
                if job is None:
                    return self._json(404, {"error": f"없는 id: {parts[3]}"})
                if len(parts) == 4:
                    return self._json(200, {k: job.get(k) for k in ("id", "status", "progress", "error", "created_at",
                                                                    "started_at", "finished_at", "task")})
                if parts[4] == "content":
                    f = Path(job.get("file") or "")
                    if job.get("status") != "completed" or not f.is_file():
                        return self._json(409, {"error": f"아직 결과가 없다 (status={job.get('status')})"})
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(f.stat().st_size))
                    self.end_headers()
                    with f.open("rb") as fh:
                        shutil.copyfileobj(fh, self.wfile)
                    return None
            return self._json(404, {"error": f"없는 경로: {path}"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path.rstrip("/")
            if path != "/v1/videos":
                return self._json(404, {"error": f"없는 경로: {path}"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 4 << 20:
                return self._json(400, {"error": "본문이 없거나 너무 크다 (JSON, 4MB 이하)"})
            try:
                body = json.loads(self.rfile.read(n))
                return self._json(200, srv.submit(body))
            except (BadRequest, json.JSONDecodeError, TypeError, ValueError) as e:
                return self._json(400, {"error": str(e)})
    return H


def pick_devices(spec: str | None) -> list[str]:
    """--devices 'cuda:0,cuda:1' 처럼 직접 주거나, 보이는 GPU 수로 정한다 (CUDA_VISIBLE_DEVICES 는 serve.sh 가 정한다)."""
    if spec:
        return [d.strip() for d in spec.split(",") if d.strip()]
    import torch
    n = torch.cuda.device_count()
    if n == 0:
        raise SystemExit("GPU 가 안 보인다 (CUDA_VISIBLE_DEVICES·드라이버 확인). 바로 위 torch 경고를 참고")
    if n > 2:
        log(f"GPU {n}장이 보이지만 2장만 쓴다 (텍스트 인코더 1장 + 영상 모델 1장). 남는 장은 다른 서버(--ref)에 주면 된다")
    return [f"cuda:{i}" for i in range(min(n, 2))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="h3video.dserver", description="MiniMax-H3 Diffusers 서버 (/v1/videos)")
    ap.add_argument("--model-dir", required=True, help="Diffusers 형식 폴더 (modular_model_index.json, transformer/ …)")
    ap.add_argument("--variant", choices=sorted(TASKS), default="fl2va")
    ap.add_argument("--host", default=os.environ.get("H3_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=30010)
    ap.add_argument("--out-dir", default=None, help="결과 mp4 저장 위치 (기본: $STORAGE_ROOT/dserver/<variant>)")
    ap.add_argument("--devices", default=os.environ.get("H3_DSERVER_DEVICES"), help="예: cuda:0,cuda:1 (기본: 보이는 GPU)")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default=os.environ.get("H3_ATTN_BACKEND"), help="어텐션 백엔드 (기본: PyTorch SDPA)")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir or Path(os.environ.get("STORAGE_ROOT", "."), "dserver", a.variant))
    import torch
    log(f"torch {torch.__version__} (CUDA {torch.version.cuda}), 모델 {a.model_dir}, 결과 {out_dir}")
    devices = pick_devices(a.devices)
    engine = Engine(a.model_dir, a.variant, devices, a.dtype, a.attn)
    srv = Server(engine, out_dir, a.variant)
    threading.Thread(target=srv.worker, daemon=True).start()
    httpd = ThreadingHTTPServer((a.host, a.port), make_handler(srv))
    httpd.daemon_threads = True
    log(f"준비됨: http://{a.host}:{a.port} (variant={a.variant})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
