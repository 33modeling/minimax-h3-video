"""One copy of H3's weights across the selected denoiser GPUs, plus bounded references."""
from contextlib import contextmanager


def weight_placement(model, devices, dtype_bytes=2):
    """Plan contiguous whole blocks; all projections and row indices stay on the first GPU.

    This is a layer/device map, not context parallelism. Every parameter has exactly
    one placement. In particular, the final projections return to the first device
    so the model's sequence-wide index_select uses indices on that same device.
    The meta model supplies sizes without allocating its checkpoint in host RAM.
    """
    if len(set(devices)) != len(devices) or not devices:
        raise ValueError("영상 모델 GPU 번호가 비었거나 중복됐습니다.")
    blocks = model.transformer_blocks
    if len(blocks) < len(devices):
        raise ValueError("영상 모델 블록보다 GPU 수가 많습니다.")
    fp32 = getattr(model, "_keep_in_fp32_modules", [])
    sizes = {}
    for name, parameter in model.named_parameters():
        size = parameter.numel() * (4 if any(part in name for part in fp32) else dtype_bytes)
        sizes[name] = size
    block_sizes = [sum(size for name, size in sizes.items() if name.startswith(f"transformer_blocks.{i}."))
                   for i in range(len(blocks))]
    overhead = sum(sizes.values()) - sum(block_sizes)
    target = sum(sizes.values()) / len(devices)
    # Do not assign the root "": Accelerate would recursively move the entire
    # checkpoint to that GPU while attaching its root hook, before moving blocks
    # away again. Map the other top-level modules individually instead.
    mapping = {name: devices[0] for name, _ in model.named_children() if name != "transformer_blocks"}
    loads, current = {device: 0 for device in devices}, 0
    loads[devices[0]] = overhead
    for i, size in enumerate(block_sizes):
        remaining_blocks, remaining_devices = len(blocks) - i, len(devices) - current - 1
        if current < len(devices) - 1 and (
            remaining_blocks == remaining_devices or
            (loads[devices[current]] >= target * .7 and loads[devices[current]] + size > target)
        ):
            current += 1
        mapping[f"transformer_blocks.{i}"] = devices[current]
        loads[devices[current]] += size
    if any(size == 0 for size in loads.values()):
        raise ValueError("요청한 영상 모델 GPU를 모두 쓰는 배치를 만들지 못했습니다.")
    return mapping, loads


def load_sharded_transformer(model_dir, name, devices, dtype, torch):
    from diffusers import MiniMaxH3Transformer3DModel
    with torch.device("meta"):
        prototype = MiniMaxH3Transformer3DModel.from_config(
            MiniMaxH3Transformer3DModel.load_config(model_dir, subfolder=name, local_files_only=True))
    mapping, weights = weight_placement(prototype, devices, torch.empty((), dtype=dtype).element_size())
    del prototype
    # Leave at least 16 GiB for activations, transfers, and allocator overhead.
    # A failed plan must not quietly fall back to CPU/disk or a full copy per GPU.
    for device, size in weights.items():
        free, _ = torch.cuda.mem_get_info(torch.device(device))
        if size + 16 * 2**30 > free:
            raise ValueError(f"가중치 분산: {device} 여유 {free / 2**30:.1f}GiB, "
                             f"가중치 {size / 2**30:.1f}GiB + 활성값 예약 16GiB가 필요합니다.")
    transformer = MiniMaxH3Transformer3DModel.from_pretrained(
        model_dir, subfolder=name, dtype=dtype, device_map=mapping,
        low_cpu_mem_usage=True, local_files_only=True)
    actual = getattr(transformer, "hf_device_map", None)
    if actual != mapping:
        raise RuntimeError("영상 모델의 실제 GPU 가중치 배치가 요청한 배치와 다릅니다.")
    placed = {device: 0 for device in devices}
    for parameter_name, parameter in transformer.named_parameters():
        key = next(key for key in sorted(mapping, key=len, reverse=True)
                   if parameter_name == key or parameter_name.startswith(key + "."))
        expected = mapping[key]
        if str(parameter.device) != expected:
            raise RuntimeError(f"가중치 {parameter_name}이 {parameter.device}에 있습니다. 필요 GPU: {expected}")
        placed[expected] += parameter.numel() * parameter.element_size()
    return transformer, {"deviceMap": mapping, "weightBytes": placed, "copies": 1}


def transfer_denoiser_state(state, device, required_keys):
    """Move encoded CUDA data, preserving the layout builder's CPU metadata.

    Diffusers packs text tags using CPU advanced indexed assignment before its
    model hooks align arguments. CUDA tags at that earlier stage are invalid.
    The existing Accelerate model hooks handle the later model-input boundary.
    """
    import torch
    def transfer(value):
        if isinstance(value, torch.Tensor):
            return value.to(device) if value.is_cuda else value
        if isinstance(value, dict):
            return {key: transfer(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return type(value)(transfer(item) for item in value)
        return value
    keep = set(required_keys) | {key for keys in state.kwargs_mapping.values() for key in keys}
    state.values = {key: value.to("cpu") if key == "text_token_tags" and isinstance(value, torch.Tensor)
                    else transfer(value) for key, value in state.values.items()
                    if key in keep and key != "generator"}
    return state


@contextmanager
def request_reference_geometry(pipeline, short_edge, enabled=True):
    """Make --size apply to reference encoding too; restore settings after every call.

    H3's released image reference setting upscales to 2048 with no area cap.
    Its reference video canvas is also independent of output height/width.
    Changing only the output size therefore cannot recover an encoder OOM.
    """
    if not enabled:
        yield
        return
    names = ("canvas_short_edge", "canvas_max_pixels", "reference_image_short_edge")
    defaults = (768, 768 * 1344, 2048)
    original = {name: getattr(pipeline.config, name, default) for name, default in zip(names, defaults)}
    edge = min(int(short_edge), original["canvas_short_edge"])
    pixels = max(32 * 32, int(original["canvas_max_pixels"] * (edge / original["canvas_short_edge"]) ** 2))
    pipeline.register_to_config(canvas_short_edge=edge, canvas_max_pixels=pixels,
                                reference_image_short_edge=min(edge, original["reference_image_short_edge"]))
    try:
        yield
    finally:
        pipeline.register_to_config(**original)


class ExclusiveStageOffload:
    """Evict previous component weights before admitting the next component.

    AutoOffloadStrategy budgets weights plus a fixed reserve, not the incoming
    model's activation peak. Keeping a 32B text encoder beside a small VAE can
    therefore exhaust their single conditioning GPU despite idle denoiser GPUs.
    Hook installation initially offloads every model. Evicting all peers at each
    transition maintains one resident component; repeated calls to that same
    component do not transfer its weights again.
    """
    def __init__(self, on_transition=None):
        self.on_transition = on_transition

    def __call__(self, hooks, model_id, model, execution_device):
        if self.on_transition:
            self.on_transition(str(model_id), type(model).__name__, str(execution_device))
        return list(hooks)
