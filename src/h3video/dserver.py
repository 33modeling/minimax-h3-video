"""MiniMax-H3 Diffusers 서버 — SGLang 과 같은 `/v1/videos` API (h3video CLI·웹·숏폼이 그대로 쓴다).

드라이버가 CUDA 12.x 인 노드에서 쓴다. H3 를 지원하는 sglang(0.5.17+)은 CUDA 13 전용이라 그런 노드에서는 못 띄운다.
diffusers 0.41 의 공식 통합(MiniMaxH3ModularPipeline)을 기존 클러스터 레포와 같은 torch 2.7.1(CUDA 12.6)로 돌린다.

  GPU 3장 이상: 텍스트 인코더(Qwen3-VL, 62GB)·VAE → 첫 장, 영상 모델(62GB) → 나머지 장에 나눠 함께 돌린다
                (context parallel, diffusers Ulysses. 워커 h3video.dworker 를 torchrun 으로 띄운다). 4장이면 영상 모델 3장
  GPU 2장:      텍스트 인코더 → 두 번째 장, 영상 모델·VAE → 첫 번째 장 (diffusers 문서의 2장 방식)
  GPU 1장:      한 장에서 컴포넌트를 번갈아 올리고 내린다 (ComponentsManager 자동 오프로드)

  POST /v1/videos                → {"id", "status"}
  GET  /v1/videos/{id}           → {"id", "status": queued|in_progress|completed|failed, "progress": 0~1, "error"}
  GET  /v1/videos/{id}/content   → mp4 (영상+스테레오 오디오)
  GET  /health, /v1/models

  python -m h3video.dserver --model-dir DIR --variant fl2va|ref2va [--port 30010] [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import queue
import re
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
# 영상 모델 블록 하나의 활성 메모리, 토큰(행)당. 실제 크기 블록(hidden 5376·FFN 14336·헤드 56)을 4k·8k 토큰으로 돌려
# PyTorch 프로파일러로 잰 최고치 165.3KB(길이에 정비례) + 입력·회전 임베딩 등 → 180KB 로 잡는다 (2026-10-10)
ACT_BYTES_PER_ROW = int(float(os.environ.get("H3_ACT_KB_PER_ROW", "180")) * 1024)


def log(msg: str) -> None:
    print(f"[dserver {time.strftime('%H:%M:%S')}] {msg}", flush=True)


class BadRequest(ValueError):
    pass


class WorkerDied(RuntimeError):
    """영상 모델 워커(torchrun)가 끝났다. 서버도 끝내서 up.sh 가 알아채고 정리하게 한다."""


def local_path(uri: str) -> str:
    """file:// → 경로 (http(s) 는 그대로: diffusers 가 직접 받는다)."""
    if uri.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    return uri


GUIDE_FILES = {"base": "VIDEO_PROMPT_WRITING_GUIDE_base_en.md", "ref": "VIDEO_PROMPT_WRITING_GUIDE_ref_en.md"}


def load_guides(model_dir: str) -> dict:
    """MiniMax 공식 프롬프트 작성 가이드 (provision.sh 가 모델 폴더 docs/ 에 받아 둔다). H3_GUIDE_DIR 로 바꿀 수 있다."""
    d = Path(os.environ.get("H3_GUIDE_DIR") or Path(model_dir, "docs"))
    return {k: (d / f).read_text(encoding="utf-8") for k, f in GUIDE_FILES.items() if (d / f).is_file()}


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


def _seed(v) -> int:
    s = int(v or 0)
    if not 0 <= s < 2**63:
        raise BadRequest(f"seed 는 0 ~ 2^63-1: {s}")
    return s


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
        self.mode, self._proc, self._conn = "single", None, None
        if len(devices) >= 3:
            self.mode = "cp"
            log(f"GPU {len(devices)}장 방식: 텍스트 인코더·VAE → {devices[0]}, 영상 모델 → {', '.join(devices[1:])} 에 나눔 (context parallel)")
            self._start_workers(model_dir, variant, devices[1:], dtype, attn)   # 워커가 영상 모델을 올리는 동안 여기서도 올린다
            stage = {n: blocks.sub_blocks.pop(n) for n in ("before_encode", "text_encoder", "vae_encoder")}
            m = ComponentsManager()
            self.cond = SequentialPipelineBlocks.from_blocks_dict(stage).init_pipeline(model_dir, components_manager=m)
            self.cond.load_components(dtype=dt)
            m.enable_auto_cpu_offload(device=devices[0], memory_reserve_margin=MARGIN)
            self._cond_dev = devices[0]
            den = blocks.sub_blocks["denoise"]   # 워커로 보낼 상태 값: 디노이징 입력 + 작업을 고르는 값(references·image·last_image)
            self._den_keys = {i.name for i in den.inputs if i.name} | {n for n in (getattr(den, "block_trigger_inputs", None) or []) if n}
            self.dec = SequentialPipelineBlocks.from_blocks_dict({"decode": blocks.sub_blocks["decode"]}).init_pipeline(model_dir)
            self.dec.update_components(vae=self.cond.vae, audio_vae=self.cond.audio_vae)
            self.pipe, self.geo = None, self.cond
            self._wait_workers()
        elif len(devices) >= 2:
            # 여러 장 방식과 같은 구조: 조건(텍스트 인코더·VAE 인코드) → 디노이징(영상 모델만 있는 장) → 디코딩(VAE 장).
            # 예전 구조(VAE 인코드를 영상 모델 쪽에서)는 ref2va 결과가 한 장 방식과 달랐다 (float32 평균차 5.8/255, 2026-10-10)
            from .dworker import geometry
            from diffusers import AutoencoderKLMiniMaxH3, AutoencoderKLMiniMaxH3Audio
            self.mode = "split"
            log(f"GPU 2장 방식: 텍스트 인코더·VAE → {devices[1]}, 영상 모델 → {devices[0]}")
            stage = {n: blocks.sub_blocks.pop(n) for n in ("before_encode", "text_encoder", "vae_encoder")}
            m_c = ComponentsManager()
            self.cond = SequentialPipelineBlocks.from_blocks_dict(stage).init_pipeline(model_dir, components_manager=m_c)
            self.cond.load_components(dtype=dt)
            m_c.enable_auto_cpu_offload(device=devices[1], memory_reserve_margin=MARGIN)
            self._cond_dev = devices[1]
            self.dec = SequentialPipelineBlocks.from_blocks_dict({"decode": blocks.sub_blocks.pop("decode")}).init_pipeline(model_dir)
            self.dec.update_components(vae=self.cond.vae, audio_vae=self.cond.audio_vae)
            m_main = ComponentsManager()
            self.pipe = blocks.init_pipeline(model_dir, components_manager=m_main)   # 남은 블록 = 디노이징
            tname = "transformer" if variant == "fl2va" else "transformer_ref"
            self.pipe.load_components(names=[tname, "scheduler", "audio_scheduler"], dtype=dt)
            m_main.enable_auto_cpu_offload(device=devices[0], memory_reserve_margin=MARGIN)
            self.pipe.vae = geometry(AutoencoderKLMiniMaxH3, model_dir, "vae")   # 디노이징은 VAE 설정값만 읽는다
            self.pipe.audio_vae = geometry(AutoencoderKLMiniMaxH3Audio, model_dir, "audio_vae")
            self.geo = self.cond
        else:
            log(f"GPU 1장 방식: {devices[0]} 에서 컴포넌트를 번갈아 올린다 (CPU 메모리에 가중치 상주)")
            self.cond = None
            m = ComponentsManager()
            self.pipe = blocks.init_pipeline(model_dir, components_manager=m)
            self.pipe.load_components(workflow=load_wf, dtype=dt)
            m.enable_auto_cpu_offload(device=devices[0], memory_reserve_margin=MARGIN)
            self.geo = self.pipe
        self._steps_done = 0
        if self.mode != "cp":   # cp 는 워커가 영상 모델을 갖고 진행 스텝을 보내 준다
            tname = "transformer" if variant == "fl2va" else "transformer_ref"
            self.transformer = getattr(self.pipe, tname, None)
            if self.transformer is None:
                raise RuntimeError(f"{tname} 를 불러오지 못했다: {model_dir}/{tname}")
            if attn:
                self.transformer.set_attention_backend(attn)
                log(f"어텐션 백엔드: {attn}")
            self.transformer.register_forward_hook(self._count)
        self._te_pipe = self.pipe if self.mode == "single" else self.cond   # 텍스트 인코더(= Qwen3-VL-32B-Instruct)가 있는 쪽
        if self.mode != "cp":   # 영상 모델이 올라갈 장: 전체 - 영상 모델 - CUDA 컨텍스트 등 1.5GB
            self.cp_world, self.headroom = 1, None
            if str(devices[0]).startswith("cuda"):
                total = torch.cuda.mem_get_info(torch.device(devices[0]))[1]
                self.headroom = int(total - self.transformer.get_memory_footprint() - 1.5 * 2**30)
        self.guides = load_guides(model_dir)
        log("프롬프트 다듬기: " + ("켜짐 (공식 작성 가이드 base·ref, 텍스트 인코더 Qwen3-VL 로)" if len(self.guides) == 2 else
                             f"꺼짐 — 공식 작성 가이드가 없다 ({model_dir}/docs). bash scripts/provision.sh 로 받는다"))
        cfg = self.geo.config
        self.short_edge = int(getattr(cfg, "canvas_short_edge", 768) or 768)
        self.max_pixels = int(getattr(cfg, "canvas_max_pixels", 768 * 1344) or 768 * 1344)
        log(f"적재 완료 ({time.time() - t0:.0f}초): variant={variant} 작업={'/'.join(TASKS[variant])} "
            f"캔버스 배수={self.geo.canvas_multiple} 기본 짧은 변={self.short_edge}")

    def _count(self, *_):
        self._steps_done += 1

    def _stage(self, name: str) -> None:
        self.stage, self._stage_t0 = name, time.time()
        if getattr(self, "on_stage", None):
            self.on_stage(name)

    # ── 메모리 검사: 길이·해상도·조건이 영상 모델 장에 들어가는지 생성 전에 본다 ──
    def rows(self, plan: dict, h: int, w: int, state=None) -> dict:
        """영상 모델이 한 번에 보는 시퀀스 행 수 (영상·오디오·텍스트·조건). state 가 있으면 실제 조건 크기를 쓴다."""
        from diffusers.modular_pipelines.minimax_h3.modular_pipeline import audio_latent_num_frames, video_latent_num_frames
        g = self.geo
        lf = video_latent_num_frames(plan["num_frames"], g.vae_frames_per_chunk, g.vae_latents_per_chunk)
        grid = (h // g.canvas_multiple) * (w // g.canvas_multiple)
        r = {"video": lf * grid, "audio": audio_latent_num_frames(plan["num_frames"]) * 2, "text": 2000, "cond": 0}
        vals = getattr(state, "values", {}) if state is not None else {}
        pe = vals.get("prompt_embeds")
        if pe is not None and hasattr(pe, "shape"):
            r["text"] = int(pe.shape[-2])
        for t in vals.get("condition_latents") or []:
            r["cond"] += int(t.shape[-3]) * (int(t.shape[-2]) // 2) * (int(t.shape[-1]) // 2)
        for t in vals.get("audio_condition_latents") or []:
            r["cond"] += int(t.numel()) // int(g.audio_latent_channels or 32)
        if state is None:   # 조건을 아직 모르면 키프레임만 (한 장 = 잠재 프레임 1개)
            r["cond"] = len(plan["keyframes"]) * grid
        return r

    def check_memory(self, plan: dict, h: int, w: int, state=None, when: str = "") -> None:
        """추정치는 참고용: 로그에 남기고, 모자랄 것 같으면 경고만 한다 (거절하지 않는다 — 실제 GPU 는 추정보다 덜 쓸 수 있다)."""
        if not getattr(self, "headroom", None):
            return
        r = self.rows(plan, h, w, state)
        total = sum(r.values())
        per_gpu = total / self.cp_world
        need = per_gpu * ACT_BYTES_PER_ROW
        log(f"메모리 예상{when}: 시퀀스 {total:,}행 (영상 {r['video']:,}·오디오 {r['audio']:,}·텍스트 {r['text']:,}·조건 {r['cond']:,})"
            f" → 영상 모델 장마다 약 {need / 2**30:.1f}GB / 여유 {self.headroom / 2**30:.1f}GB")
        if need <= self.headroom:
            return
        g = self.geo   # 들어가는 가장 긴 초: 프레임 수가 VAE 단위로 올림되므로 한 초씩 실제로 넣어 본다
        max_sec = 0
        for s in range(15, 4, -1):
            nf, _ = frames_for(s, g.vae_frames_per_chunk, g.vae_latents_per_chunk, g.fps, g.min_duration, g.max_duration)
            rs = self.rows(dict(plan, num_frames=nf), h, w, state)
            if sum(rs.values()) / self.cp_world * ACT_BYTES_PER_ROW <= self.headroom:
                max_sec = s
                break
        tips = [f"-s {max(5, int(max_sec))} 이하로 (지금 {plan['num_frames'] / 24:.1f}초, 더 길면 장면을 이어 붙인다: -s 30 --scene-seconds {max(5, min(10, int(max_sec)))})"
                if max_sec >= 5 else "길이를 줄여도 안 들어간다",
                "--size 576 (해상도를 낮추면 영상 행이 약 44% 줄어든다)"]
        if r["cond"] > r["video"] * 0.3:
            tips.append(f"레퍼런스·키프레임을 줄이기 (조건이 {r['cond']:,}행)")
        if self.cp_world == 1:
            tips.append("GPU 4장으로 띄우기 (bash scripts/up.sh 를 --ref 없이 → 영상 모델 3장에 나눠 장마다 1/3)")
        log(f"[경고] 메모리가 모자랄 수 있다 (추정 약 {need / 2**30:.1f}GB / 여유 {self.headroom / 2**30:.1f}GB). 그래도 시도한다. "
            f"OOM 이 나면: " + " / ".join(tips))

    def max_seconds(self, aspect: str, short_edge: int, keyframes: int = 1, images: int = 0, video_seconds: float = 0):
        """이 GPU 구성에 들어가는 한 장면의 최대 초(5~15). 여유를 모르면 None, 5초도 안 들어가면 0.
        CLI 가 이 값에 맞춰 긴 영상을 장면으로 나눈다 (OOM 이 나기 전에)."""
        if not getattr(self, "headroom", None):
            return None
        g = self.geo
        h, w = self._canvas("16:9" if aspect == "auto" else aspect, short_edge)
        grid = (h // g.canvas_multiple) * (w // g.canvas_multiple)
        cond = images * grid   # 참고 영상: 초당 잠재 프레임 약 24/17*5 개
        if video_seconds:
            cond += int(math.ceil(video_seconds * g.fps / g.vae_frames_per_chunk * g.vae_latents_per_chunk + 2)) * grid
        for s in range(15, 4, -1):
            nf, _ = frames_for(s, g.vae_frames_per_chunk, g.vae_latents_per_chunk, g.fps, g.min_duration, g.max_duration)
            r = self.rows({"num_frames": nf, "keyframes": [None] * keyframes}, h, w)
            if (sum(r.values()) + cond) / self.cp_world * ACT_BYTES_PER_ROW <= self.headroom:
                return s
        return 0

    # ── 영상 모델 워커 (GPU 3장 이상) ──
    def _start_workers(self, model_dir: str, variant: str, devs: list[str], dtype: str, attn: str | None) -> None:
        import atexit
        import secrets
        import socket
        import subprocess
        import sys
        from multiprocessing.connection import Listener
        key = secrets.token_hex(16)
        self._listener = Listener(("127.0.0.1", 0), authkey=key.encode())
        env = dict(os.environ, H3_CP_AUTHKEY=key)
        if all(d == "cpu" for d in devs):
            env["H3_CP_DEVICE"] = "cpu"
        else:   # 워커가 볼 GPU = 이 프로세스가 보는 GPU 중 첫 장을 뺀 나머지 (nvidia-smi 번호로)
            vis = [x.strip() for x in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if x.strip()]
            idx = [int(d.split(":")[1]) for d in devs]
            env["CUDA_VISIBLE_DEVICES"] = ",".join(vis[i] if i < len(vis) else str(i) for i in idx)
        if attn:
            env["H3_ATTN_BACKEND"] = attn
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        cmd = [sys.executable, "-m", "torch.distributed.run", "--nproc_per_node", str(len(devs)), "--master_addr", "127.0.0.1",
               "--master_port", str(port), "-m", "h3video.dworker", "--model-dir", model_dir, "--variant", variant,
               "--address", f"127.0.0.1:{self._listener.address[1]}", "--dtype", dtype]
        log(f"영상 모델 워커 {len(devs)}개 시작 (GPU {env.get('CUDA_VISIBLE_DEVICES', 'cpu')}): torchrun … -m h3video.dworker")
        self._proc = subprocess.Popen(cmd, env=env)
        atexit.register(self._stop_workers)

    def _wait_workers(self) -> None:
        box = {}
        th = threading.Thread(target=lambda: box.setdefault("conn", self._listener.accept()), daemon=True)
        th.start()
        while th.is_alive():
            if self._proc.poll() is not None:
                raise WorkerDied(f"영상 모델 워커가 준비 중에 끝났다 (종료 코드 {self._proc.returncode}). 바로 위 [dworker] 로그가 원인")
            th.join(1)
        self._conn = box["conn"]
        msg = self._recv().decode().split()
        self.headroom = int(msg[2]) if len(msg) > 2 and int(msg[2]) > 0 else None   # 영상 모델 장의 남는 자리
        self.cp_world = int(msg[1])
        log(f"영상 모델 워커 연결: {msg[1]}장" + (f", 영상 모델 올린 뒤 가장 빠듯한 장 여유 {self.headroom / 2**30:.1f}GB" if self.headroom else ""))

    def _recv(self) -> bytes:
        while True:
            try:
                if self._conn.poll(1):
                    return self._conn.recv_bytes()
            except (EOFError, OSError) as e:
                raise WorkerDied(f"영상 모델 워커와 연결이 끊겼다 ({type(e).__name__}). 바로 위 [dworker] 로그가 원인") from e
            if self._proc.poll() is not None:
                raise WorkerDied(f"영상 모델 워커가 끝났다 (종료 코드 {self._proc.returncode}). 바로 위 [dworker] 로그가 원인")

    def _stop_workers(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            self._conn and self._conn.send_bytes(b"STOP")
            self._proc.wait(timeout=30)
        except Exception:   # noqa: BLE001 — 끄는 길이라 실패해도 아래에서 강제로 끈다
            pass
        if self._proc.poll() is None:
            self._proc.terminate()

    def _denoise_remote(self, state, g, gen: dict) -> dict:
        import torch
        state.values.pop("generator", None)   # 생성기는 직렬화가 안 된다 → 상태만 넘긴다
        keep = self._den_keys | {k for ks in state.kwargs_mapping.values() for k in ks}
        state.values = {k: v for k, v in state.values.items() if k in keep}   # 원본 레퍼런스 영상 등은 빼서 크기를 줄인다
        cuda_keys = [k for k, v in state.values.items() if _on_cuda(v)]   # diffusers 가 CPU 에 둔 값(text_token_tags 등)은 CPU 로 둔다
        state.values = _to_cpu(state.values)
        buf = io.BytesIO()
        torch.save({"state": state, "gen_state": g.get_state(), "kwargs": gen, "cuda_keys": cuda_keys}, buf)
        self._conn.send_bytes(buf.getvalue())
        while True:
            m = self._recv()
            if m.startswith(b"PROG "):
                self._steps_done = int(m[5:])
            elif m.startswith(b"DONE"):
                res = torch.load(io.BytesIO(m[4:]), weights_only=False)
                if not res["ok"]:
                    raise RuntimeError("영상 모델 워커: " + res["error"])   # OOM 이면 run() 이 할 일을 붙인다
                return res

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
        se = int(target.get("short_edge") or self.short_edge)
        if not (256 <= se <= 1024 and se % 32 == 0):
            raise BadRequest(f"short_edge 는 256~1024 의 32 배수 (CLI --size 512·576·640·704·768): {se}")
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
            keyframes = sorted(zip(slots, keyframes), key=lambda x: x[0] != "image")   # diffusers 와 같은 순서: 첫 프레임 먼저
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
        p = self.geo
        nf, secs = frames_for(target.get("duration_seconds", 8), p.vae_frames_per_chunk, p.vae_latents_per_chunk,
                              p.fps, p.min_duration, p.max_duration)
        steps = body.get("num_inference_steps")
        if getattr(self, "headroom", None):   # GPU 여유를 알면 접수할 때 바로 거른다 (다듬기·조건 만들기 전에)
            aspect = str(target.get("aspect_ratio") or "16:9")
            try:
                eh, ew = self._canvas("16:9" if aspect == "auto" else aspect, int(target.get("short_edge") or self.short_edge))
            except ValueError as e:
                raise BadRequest(str(e)) from e
            self.check_memory({"num_frames": nf, "keyframes": keyframes}, eh, ew, when=" (접수)")
        return {"task": task, "prompt": prompt, "keyframes": keyframes, "refs": refs, "num_frames": nf,
                "seconds": secs, "asked_seconds": target.get("duration_seconds", 8),
                "aspect": str(target.get("aspect_ratio") or "16:9"),
                "short_edge": int(target.get("short_edge") or self.short_edge),
                "steps": int(steps) if steps else 50, "seed": _seed(body.get("seed")),
                "rewrite": body.get("rewrite", True) is not False,
                "ignored": [k for k in ("negative_prompt",) if body.get(k)]}

    def _canvas(self, aspect: str, short_edge: int, image=None) -> tuple[int, int]:
        from diffusers.modular_pipelines.minimax_h3.modular_pipeline import resolve_canvas_size
        if aspect == "auto":
            aw, ah = (image.size if image is not None else (16, 9))
        else:
            aw, ah = (float(x) for x in aspect.split(":"))
        max_px = round(self.max_pixels * (short_edge / self.short_edge) ** 2)
        return resolve_canvas_size(aw, ah, self.geo.canvas_multiple, short_edge, max_px)

    def _load_inputs(self, plan: dict) -> tuple[dict, object]:
        from diffusers.modular_pipelines.minimax_h3 import (MiniMaxH3AudioReference, MiniMaxH3ImageReference,
                                                            MiniMaxH3VideoReference)
        from diffusers.utils import load_image
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
        return inputs, first_image

    # ── 프롬프트 다듬기 (H3-Context-IR 대신) ──
    def _visuals(self, plan: dict, inputs: dict) -> tuple[list, list[str]]:
        """다듬는 모델에게 보여 줄 그림과 라벨. 라벨 번호는 diffusers 가 생성 모델에 붙이는 규칙과 같다."""
        import numpy as np
        from PIL import Image
        from .rewrite import small
        visuals, labels = [], []
        if plan["task"] != "ref2va":
            slots = [s for s, _ in plan["keyframes"]]
            for i, s in enumerate(slots, 1):
                role = "the first frame" if s == "image" else "the last frame"
                visuals.append((f"<Picture {i}> ({role} of the target video):", small(inputs[s])))
                labels.append(f"<Picture {i}> = {role} (shown)")
            return visuals, labels
        counts = {"image": 0, "video": 0, "audio": 0}
        for r in inputs.get("references", []):
            if r.has_audio:
                counts["audio"] += 1
                labels.append(f"<Audio {counts['audio']}> = " + ("the soundtrack of the next video" if r.kind == "video"
                                                                else "an audio clip (you cannot hear it; use the user's request)"))
            if r.kind == "image":
                counts["image"] += 1
                img = r.image if isinstance(r.image, Image.Image) else Image.fromarray(np.asarray(r.image))
                visuals.append((f"<Picture {counts['image']}>:", small(img)))
                labels.append(f"<Picture {counts['image']}> = reference image (shown)")
            elif r.kind == "video":
                counts["video"] += 1
                frames = r.frames
                n = len(frames)
                for j in sorted({0, n // 2, n - 1}):   # 처음·중간·끝 세 장
                    f = frames[j]
                    f = f if isinstance(f, Image.Image) else Image.fromarray(np.asarray(f.cpu() if hasattr(f, "cpu") else f).astype("uint8"))
                    visuals.append((f"<Video {counts['video']}> frame {j + 1}/{n}:", small(f, 768)))
                labels.append(f"<Video {counts['video']}> = reference video, {n} frames at {r.fps or 24:g} fps (3 frames shown)")
        return visuals, labels

    def _prepare_prompt(self, plan: dict, inputs: dict) -> str:
        """다듬기가 켜져 있고 공식 형식이 아니면 공식 가이드대로 다시 쓰고, 키프레임 정렬 줄을 실제 길이로 붙인다."""
        from . import rewrite as RW
        task, slots = plan["task"], [s for s, _ in plan["keyframes"]]
        raw = RW.strip_instruction(plan["prompt"])
        secs = plan["num_frames"] / 24
        body = raw
        if plan["rewrite"] and RW.needs_rewrite(raw, task):
            guide = self.guides.get("ref" if task == "ref2va" else "base")
            if not guide:
                log("공식 작성 가이드가 없어 다듬지 않고 그대로 보낸다 → bash scripts/provision.sh (가이드 2개만 받는다)")
            else:
                visuals, labels = self._visuals(plan, inputs)
                tp = self._te_pipe
                mode = RW.mode_name(task, slots)
                for attempt in range(2):
                    t0 = time.time()
                    log(f"프롬프트 다듬기 ({mode}, {secs:.2f}초, 그림 {len(visuals)}장){' 다시' if attempt else ''} …")
                    text = RW.rewrite_with_model(tp.text_encoder, tp.processor, tp._execution_device, guide, mode, secs,
                                                 raw, visuals, labels, seed=plan["seed"] + attempt)
                    out = RW.extract(text, task)
                    if out:
                        body = out
                        log(f"다듬은 프롬프트 ({time.time() - t0:.0f}초):\n{body}")
                        break
                    log(f"다듬은 결과가 형식에 안 맞는다 ({time.time() - t0:.0f}초). 앞부분: {text[:300]!r}")
                else:
                    body = re.sub(r"\s*\(전체 \d+초 영상을 .*?\)\s*$", "", raw, flags=re.S)   # 장면 안내는 다듬는 모델에게만
                    log("두 번 다 형식이 안 맞아 원래 프롬프트를 그대로 쓴다")
        line = RW.instruction(slots, secs, RW.max_shot(body)) if task == "fl2va" else None
        return f"{line}\n\n{body}" if line else body

    def rewrite_only(self, plan: dict) -> str:
        inputs, _ = self._load_inputs(plan)
        return self._prepare_prompt(dict(plan, rewrite=True), inputs)

    def run(self, plan: dict, out_path: Path, on_progress) -> str:
        from diffusers.utils.export_utils import encode_video
        torch = self.torch
        t_all = time.time()
        inputs, first_image = self._load_inputs(plan)
        self._stage("다듬는 중")
        inputs["prompt"] = self._prepare_prompt(plan, inputs)
        t_rw = time.time() - self._stage_t0
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
        g = torch.Generator(device="cpu").manual_seed(plan["seed"])

        def ticker():   # 진행률을 상태에 올리고, 이 창에도 10% 마다 스텝 속도를, 10분 동안 멈추면 STALL 을 찍는다
            first, shown, last_t, last_n = None, 0, time.time(), 0
            while not stop.wait(2):
                done, now = self._steps_done, time.time()
                on_progress(min(0.99, done / total))
                if done != last_n:
                    last_t, last_n = now, done
                elif self.stage == "생성 중" and now - last_t >= 600 and int(now - last_t) % 600 < 2:
                    log(f"[STALL] 디노이징이 {int(now - last_t) // 60}분 동안 스텝 {done}/{total} 에서 안 넘어간다 (no step progress). "
                        f"워커(torchrun) 로그를 본다. 끄지는 않는다")
                if done and first is None:
                    first = (now, done)
                if first and done > first[1] and done * 10 // total > shown:
                    shown = done * 10 // total
                    per = (now - first[0]) / (done - first[1])
                    left = int(per * (total - done))
                    log(f"디노이징 step {done}/{total} ({done * 100 // total}%) · {per:.1f}s/step · 남은 약 {left // 60}분 {left % 60}초")
        self._steps_done = 0
        threading.Thread(target=ticker, daemon=True).start()
        times = {}
        try:
            gen = {k: inputs[k] for k in ("num_frames", "height", "width", "num_inference_steps")}
            self._stage("생성 중")
            t0 = time.time()
            if self.mode == "single":
                self.check_memory(plan, h, w, when=" (생성 전)")
                r = self.pipe(**inputs, generator=g, output=OUTPUTS)
            elif self.mode == "split":   # 조건(VAE 장) → 디노이징(영상 모델 장) → 디코딩(VAE 장)
                state = self.cond(**inputs, generator=g)
                times["조건"] = time.time() - t0
                self.check_memory(plan, h, w, state, when=" (조건 포함)")
                t0 = time.time()
                res = self.pipe(state=state, generator=g, output=["latents", "audio_latents"], **gen)
                times["디노이징"] = time.time() - t0
                self._stage("디코딩")
                t0 = time.time()
                dev = torch.device(self._cond_dev)
                r = self.dec(latents=res["latents"].to(dev), audio_latents=res["audio_latents"].to(dev), output=OUTPUTS)
                times["디코딩"] = time.time() - t0
            else:   # cp: 조건(여기) → 디노이징(워커들) → 디코딩(여기)
                state = self.cond(**inputs, generator=g)
                times["조건"] = time.time() - t0
                self.check_memory(plan, h, w, state, when=" (조건 포함)")
                t0 = time.time()
                res = self._denoise_remote(state, g, gen)
                times["디노이징"] = time.time() - t0
                self._stage("디코딩")
                t0 = time.time()
                dev = torch.device(self._cond_dev)   # 워커가 CPU 로 돌려준 latents → VAE 가 있는 첫 장으로
                r = self.dec(latents=res["latents"].to(dev), audio_latents=res["audio_latents"].to(dev), output=OUTPUTS)
                times["디코딩"] = time.time() - t0
        except Exception as e:
            if "out of memory" in str(e).lower() or type(e).__name__ == "OutOfMemoryError":
                raise RuntimeError(f"GPU 메모리 부족(OOM): {str(e).splitlines()[0][:200]} — 할 일: -s 를 줄이기, --size 576, "
                                   "또는 GPU 4장 방식(bash scripts/up.sh 를 --ref 없이)") from e
            raise
        finally:
            stop.set()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()   # 다음 요청·메모리 검사가 실제 여유를 보게
        if "디노이징" not in times:
            times["조건+디노이징+디코딩"] = time.time() - t0
        steps = max(1, plan["steps"] - 1)
        log(f"걸린 시간: 다듬기 {t_rw:.0f}초 · " + " · ".join(f"{k} {v:.0f}초" for k, v in times.items())
            + (f" (스텝당 {times['디노이징'] / steps:.1f}초 × {steps})" if "디노이징" in times else "")
            + f" · 전체 {time.time() - t_all:.0f}초")
        tmp = out_path.with_suffix(".part.mp4")
        encode_video(r["videos"][0], fps=24, output_path=str(tmp), audio=r["audio"][0],
                     audio_sample_rate=r["sampling_rate"])
        tmp.replace(out_path)
        return inputs["prompt"]


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
        tmp.write_text(json.dumps({k: v for k, v in job.items() if k not in ("plan", "done")}, ensure_ascii=False, indent=2))
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

    def rewrite(self, body: dict) -> dict:
        """다듬은 프롬프트만 돌려준다. 생성과 같은 줄에 서서(텍스트 인코더를 같이 쓰므로) 차례가 오면 처리한다."""
        plan = self.engine.plan(body)
        vid = "rewrite_" + uuid.uuid4().hex[:12]
        job = {"id": vid, "kind": "rewrite", "status": "queued", "plan": plan, "done": threading.Event()}
        with self.lock:
            self.jobs[vid] = job
        self.q.put(vid)
        log(f"다듬기 미리보기 접수 {vid} ({plan['task']}, 대기 {self.q.qsize()})")
        job["done"].wait()
        with self.lock:
            self.jobs.pop(vid, None)
        if job["status"] != "completed":
            raise RuntimeError(job.get("error") or "다듬기 실패")
        return {"prompt": job["prompt_used"], "task": plan["task"], "num_frames": plan["num_frames"]}

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
            try:
                self._one(vid)
            except Exception:   # noqa: BLE001 — 저장 실패 등으로 작업 스레드가 죽으면 이후 요청이 영원히 대기한다
                traceback.print_exc()
                job = self.jobs.get(vid) or {}
                job.update(status="failed", error=job.get("error") or "서버 내부 오류 (서버 로그 참고)")
                if "done" in job:
                    job["done"].set()

    def _one(self, vid: str) -> None:
        job = self.jobs[vid]
        job["status"], job["started_at"] = "in_progress", int(time.time())
        if job.get("kind") != "rewrite":
            self.save(job)
        out = self.out_dir / f"{vid}.mp4"
        try:
            if job.get("kind") == "rewrite":   # 다듬기 미리보기: 생성 없이 프롬프트만
                job.update(status="completed", progress=1.0, prompt_used=self.engine.rewrite_only(job["plan"]))
                log(f"다듬기 미리보기 {vid} 완료")
                job["finished_at"] = int(time.time())
                job["done"].set()
                return
            self.engine.on_stage = lambda s, j=job: j.__setitem__("stage", s)
            used = self.engine.run(job["plan"], out, lambda p, j=job: j.__setitem__("progress", round(p, 3)))
            job.update(status="completed", progress=1.0, file=str(out), prompt_used=used)
            log(f"완료 {vid} → {out} ({out.stat().st_size / 1e6:.1f}MB, {int(time.time()) - job['started_at']}초)")
        except WorkerDied as e:   # 워커 묶음이 죽으면 이후 요청도 못 한다 → 서버를 끝내 up.sh 가 정리하게
            job.update(status="failed", error=str(e), finished_at=int(time.time()))
            self.save(job)
            log(f"실패 {vid}: {e} → 서버를 끝낸다")
            os._exit(3)
        except Exception as e:   # noqa: BLE001 — 실패는 작업 상태로 돌려주고 서버는 계속 돈다
            traceback.print_exc()
            job.update(status="failed", error=f"{type(e).__name__}: {e}")
            log(f"실패 {vid}: {job['error']}")
            if job.get("kind") == "rewrite":
                job["done"].set()
                return
        job["finished_at"] = int(time.time())
        self.save(job)


def _on_cuda(obj) -> bool:
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.is_cuda
    if isinstance(obj, (list, tuple)):
        return any(_on_cuda(x) for x in obj)
    if isinstance(obj, dict):
        return any(_on_cuda(v) for v in obj.values())
    return False


def _to_cpu(obj):
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.cpu()
    if isinstance(obj, (list, tuple)):
        return type(obj)(_to_cpu(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _to_cpu(v) for k, v in obj.items()}
    return obj


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
            if path == "/v1/limits":   # 한 장면 최대 초 (CLI 가 장면 나누기에 쓴다)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
                try:
                    m = srv.engine.max_seconds(q.get("aspect", "16:9"), int(q.get("short_edge") or srv.engine.short_edge),
                                               int(q.get("keyframes", 1)), int(q.get("images", 0)), float(q.get("video_seconds", 0)))
                except (ValueError, TypeError) as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {"max_seconds": m, "gpus": getattr(srv.engine, "cp_world", 1)})
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
                                                                    "started_at", "finished_at", "task", "prompt_used", "stage")})
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
            if path not in ("/v1/videos", "/v1/prompts/rewrite"):
                return self._json(404, {"error": f"없는 경로: {path}"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 4 << 20:
                return self._json(400, {"error": "본문이 없거나 너무 크다 (JSON, 4MB 이하)"})
            try:
                body = json.loads(self.rfile.read(n))
                if not isinstance(body, dict) or not isinstance(body.get("target", {}), dict) \
                        or not all(isinstance(c, dict) for c in body.get("conditions") or []):
                    raise BadRequest("본문은 JSON 객체, target 은 객체, conditions 는 객체 목록이어야 한다")
                return self._json(200, srv.rewrite(body) if path.endswith("/rewrite") else srv.submit(body))
            except (BadRequest, json.JSONDecodeError, TypeError, ValueError, AttributeError, KeyError) as e:
                return self._json(400, {"error": str(e)})
            except RuntimeError as e:
                return self._json(500, {"error": str(e)})
    return H


def pick_devices(spec: str | None) -> list[str]:
    """--devices 'cuda:0,cuda:1' 처럼 직접 주거나, 보이는 GPU 수로 정한다 (CUDA_VISIBLE_DEVICES 는 serve.sh 가 정한다)."""
    if spec:
        return [d.strip() for d in spec.split(",") if d.strip()]
    import torch
    n = torch.cuda.device_count()
    if n == 0:
        raise SystemExit("GPU 가 안 보인다 (CUDA_VISIBLE_DEVICES·드라이버 확인). 바로 위 torch 경고를 참고")
    use = min(n, 2) if os.environ.get("H3_DSERVER_CP", "1") == "0" else min(n, 8)   # 3장 이상이면 영상 모델을 나눠 돌린다
    return [f"cuda:{i}" for i in range(use)]


def check_free(devices: list[str]) -> None:
    """올리기 전에 GPU 가 비어 있는지 본다. 다른 프로세스가 차지한 GPU 에서는 첫 요청 때 CUDA OOM 이 나므로 미리 멈춘다."""
    import torch
    need = float(os.environ.get("H3_DSERVER_MIN_FREE_GB", "70"))   # 텍스트 인코더·영상 모델 각 62GB + 활성값
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    phys = [x.strip() for x in visible.split(",")] if visible else []
    bad = []
    for d in devices:
        if not d.startswith("cuda"):
            continue
        i = int(d.split(":")[1]) if ":" in d else 0
        free, total = torch.cuda.mem_get_info(i)
        name = f"{d}(nvidia-smi GPU {phys[i] if i < len(phys) else i})"
        log(f"{name}: 여유 {free / 2**30:.1f}GB / {total / 2**30:.1f}GB")
        if free / 2**30 < need:
            bad.append(f"{name} 여유 {free / 2**30:.1f}GB < 필요 약 {need:.0f}GB")
    if bad:
        raise SystemExit("[dserver] GPU 를 다른 프로세스가 쓰고 있다 → " + "; ".join(bad)
                         + ". 비어 있는 GPU 로: bash scripts/up.sh (--gpus 를 빼면 빈 GPU 를 고른다) 또는 --gpus A,B")


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
    check_free(devices[:1] if len(devices) >= 3 else devices)   # 3장 이상: 나머지는 워커가 자기 GPU 를 확인한다
    engine = Engine(a.model_dir, a.variant, devices, a.dtype, a.attn)
    srv = Server(engine, out_dir, a.variant)
    threading.Thread(target=srv.worker, daemon=True).start()
    if engine.mode == "cp":   # 쉬는 동안 워커가 죽어도 바로 알아채고 서버를 끝낸다 (up.sh 가 정리)
        def watch():
            while engine._proc.poll() is None:
                time.sleep(2)
            log(f"영상 모델 워커가 끝났다 (종료 코드 {engine._proc.returncode}). 바로 위 [dworker] 로그가 원인 → 서버를 끝낸다")
            os._exit(3)
        threading.Thread(target=watch, daemon=True).start()
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
