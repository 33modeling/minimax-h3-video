"""dserver 의 영상 모델 워커 — GPU 여러 장에 영상 모델을 나눠(context parallel) 디노이징만 한다.

dserver 본체(첫 GPU)가 텍스트 인코더·VAE 로 조건을 만들고 상태(PipelineState)를 보내면, 워커 N 개가 같은 상태로
디노이징 단계를 함께 돌려(시퀀스를 N 등분, diffusers ContextParallelConfig Ulysses) latents 를 돌려준다. 디코딩은 본체가 한다.
torchrun 으로 띄운다 (dserver 가 알아서 띄움):
  python -m torch.distributed.run --nproc_per_node N -m h3video.dworker --model-dir DIR --variant fl2va --address 127.0.0.1:PORT
본체와는 multiprocessing.connection 으로 주고받는다 (rank 0 만). 메시지: 본체→워커 작업(torch.save 바이트) | b"STOP",
워커→본체 b"READY <N>" | b"PROG <n>"(지금까지 끝난 스텝 수) | b"DONE" + 결과(torch.save 바이트: ok, latents, audio_latents 또는 error).
"""
from __future__ import annotations

import argparse
import io
import os
import threading
import time
import traceback


def log(rank: int, msg: str) -> None:
    if rank == 0:
        print(f"[dworker {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def to_device(obj, device):
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, (list, tuple)):
        return type(obj)(to_device(x, device) for x in obj)
    if isinstance(obj, dict):
        return {k: to_device(v, device) for k, v in obj.items()}
    return obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="h3video.dworker")
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--variant", choices=["fl2va", "ref2va"], default="fl2va")
    ap.add_argument("--address", required=True, help="본체 주소 host:port")
    ap.add_argument("--dtype", default="bfloat16")
    a = ap.parse_args(argv)

    import torch
    import torch.distributed as dist
    from multiprocessing.connection import Client

    use_cuda = torch.cuda.is_available() and os.environ.get("H3_CP_DEVICE", "cuda") != "cpu"
    # cpu:gloo 를 같이 둔다: diffusers 의 Ulysses-anything 은 어텐션마다 조각 크기를 모으는데, 백엔드에 cpu 가 있으면 CPU 로 모아
    # GPU 동기화를 피한다(diffusers 권장 "cpu:gloo,cuda:nccl"). 큰 텐서 통신은 NCCL 로 간다.
    dist.init_process_group(backend="cpu:gloo,cuda:nccl" if use_cuda else "cpu:gloo")
    rank, world = dist.get_rank(), dist.get_world_size()
    local = int(os.environ.get("LOCAL_RANK", rank))
    if use_cuda:
        torch.cuda.set_device(local)
        device = torch.device("cuda", local)
        free, total = torch.cuda.mem_get_info(local)
        need = float(os.environ.get("H3_DSERVER_MIN_FREE_GB", "70"))
        bad = torch.tensor([1 if free / 2**30 < need else 0], device=device)
        dist.all_reduce(bad)   # 한 장이라도 모자라면 모두 멈춘다 (혼자 멈추면 나머지가 기다리며 멈춰 버린다)
        if free / 2**30 < need:
            print(f"[dworker] rank {rank}: GPU {os.environ.get('CUDA_VISIBLE_DEVICES', '?').split(',')[local]} 여유 {free / 2**30:.1f}GB < 필요 약 {need:.0f}GB — 다른 프로세스가 쓰고 있다", flush=True)
        if bad.item():
            dist.destroy_process_group()
            return 2
    else:
        device = torch.device("cpu")

    from diffusers import AutoencoderKLMiniMaxH3, AutoencoderKLMiniMaxH3Audio, ContextParallelConfig, ModularPipeline
    from diffusers.modular_pipelines import SequentialPipelineBlocks

    t0 = time.time()
    blocks = ModularPipeline.from_pretrained(a.model_dir).blocks
    pipe = SequentialPipelineBlocks.from_blocks_dict({"denoise": blocks.sub_blocks["denoise"]}).init_pipeline(a.model_dir)
    tname = "transformer" if a.variant == "fl2va" else "transformer_ref"
    # 한 장씩 차례로 올린다: 동시에 올리면 CPU 메모리에 62GB × N 이 한꺼번에 잡힌다
    for r in range(world):
        if r == rank:
            pipe.load_components(names=[tname, "scheduler", "audio_scheduler"], dtype=getattr(torch, a.dtype))
            getattr(pipe, tname).to(device)
            if use_cuda:
                free, total = torch.cuda.mem_get_info(local)
                print(f"[dworker {time.strftime('%H:%M:%S')}] rank {rank}: 영상 모델 → {device} (여유 {free / 2**30:.1f}GB / {total / 2**30:.1f}GB)", flush=True)
        dist.barrier()
    # 디노이징은 VAE 를 돌리지 않고 설정값(잠재 채널·압축 비율·청크 길이·오디오 샘플레이트)만 읽는다 → 가중치 없이 설정만 넣는다
    pipe.vae = geometry(AutoencoderKLMiniMaxH3, a.model_dir, "vae")
    pipe.audio_vae = geometry(AutoencoderKLMiniMaxH3Audio, a.model_dir, "audio_vae")
    tr = getattr(pipe, tname)
    if os.environ.get("H3_ATTN_BACKEND"):
        tr.set_attention_backend(os.environ["H3_ATTN_BACKEND"])
    heads = tr.config.num_attention_heads
    if world > 1:
        # anything: H3 는 텍스트·조건·오디오·영상을 한 시퀀스로 묶어 길이가 제멋대로라 N 으로 안 나누어떨어질 수 있다 (헤드 56 도 3 으로 안 나뉨)
        tr.enable_parallelism(config=ContextParallelConfig(ulysses_degree=world, ulysses_anything=True))
    steps = [0]
    tr.register_forward_hook(lambda *_: steps.__setitem__(0, steps[0] + 1))
    log(rank, f"준비 ({time.time() - t0:.0f}초): {tname} 을 {world}장에 나눔 (Ulysses {world}, 헤드 {heads})")

    conn = Client(tuple_addr(a.address), authkey=os.environ["H3_CP_AUTHKEY"].encode()) if rank == 0 else None
    if rank == 0:
        conn.send_bytes(f"READY {world}".encode())
    bdev = device if use_cuda else None
    while True:
        box = [conn.recv_bytes() if rank == 0 else None]
        dist.broadcast_object_list(box, src=0, device=bdev)
        msg = box[0]
        if msg == b"STOP":
            break
        job = torch.load(io.BytesIO(msg), weights_only=False, map_location="cpu")
        state = job["state"]
        state.values = to_device(state.values, device)
        gen = torch.Generator("cpu")
        gen.set_state(job["gen_state"])
        steps[0] = 0
        stop = threading.Event()

        def ticker():
            while not stop.wait(2):
                conn.send_bytes(b"PROG %d" % steps[0])
        th = threading.Thread(target=ticker, daemon=True) if rank == 0 else None
        if th:
            th.start()
        try:
            out = pipe(state=state, generator=gen, output=["latents", "audio_latents"], **job["kwargs"])
            result = {"ok": True, "latents": out["latents"].cpu(), "audio_latents": out["audio_latents"].cpu()}
        except Exception as e:   # noqa: BLE001 — 실패는 본체에 돌려준다 (모든 rank 가 같은 입력이라 같이 실패한다)
            traceback.print_exc()
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            stop.set()
            if th:
                th.join()
        if rank == 0:
            buf = io.BytesIO()
            torch.save(result, buf)
            conn.send_bytes(b"DONE" + buf.getvalue())
    dist.destroy_process_group()
    return 0


def geometry(cls, model_dir: str, sub: str):
    """VAE 를 가중치 없이(meta 장치) 만들어 설정과 파생값만 담는다. 파이프라인의 vae_* 속성이 이것을 읽는다."""
    import torch
    from types import SimpleNamespace
    with torch.device("meta"):
        m = cls.from_config(cls.load_config(model_dir, subfolder=sub))
    return SimpleNamespace(config=m.config, spatial_compression_ratio=getattr(m, "spatial_compression_ratio", None),
                           tokens_chunk_size=getattr(m, "tokens_chunk_size", None))


def tuple_addr(s: str):
    host, port = s.rsplit(":", 1)
    return host, int(port)


if __name__ == "__main__":
    raise SystemExit(main())
