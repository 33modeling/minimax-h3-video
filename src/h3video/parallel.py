"""Concurrent sequence compute with one checkpoint sharded across FSDP2 ranks.

Checkpoint reads are sliced *before* materialization: no full CPU/GPU model per
rank. Keep H3's mixed BF16/FP32 modules intact and gather only the active block.
"""
import json
import os
from pathlib import Path


def execution_mode(devices, performance=None, override=None):
    performance = performance or os.environ.get('H3_PERF_MODE', 'speed')
    override = os.environ.get('H3_DSERVER_PARALLEL') if override is None else override
    if performance not in ('speed', 'memory'):
        raise ValueError('performance mode는 speed 또는 memory입니다.')
    if override not in (None, '', 'sharded', 'cp', 'fsdp_cp'):
        raise ValueError('H3_DSERVER_PARALLEL은 fsdp_cp, sharded 또는 cp입니다.')
    if len(devices) < 3:
        return 'split' if len(devices) == 2 else 'single'
    if not all(d.startswith('cuda:') for d in devices):
        return 'cp'  # Existing CPU correctness fixtures; never pretend CPU is CUDA FSDP.
    return override or ('fsdp_cp' if performance == 'speed' else 'sharded')


def require_fsdp_runtime():
    import inspect
    try:
        try:
            from torch.distributed.fsdp import fully_shard, MixedPrecisionPolicy
        except ImportError:
            from torch.distributed._composable.fsdp import fully_shard, MixedPrecisionPolicy
        from accelerate import init_empty_weights
        from safetensors import safe_open
        if 'reshard_after_forward' not in inspect.signature(fully_shard).parameters:
            raise ImportError('FSDP2 reshard_after_forward API missing')
        MixedPrecisionPolicy(cast_forward_inputs=False)
    except (ImportError, TypeError) as error:
        raise RuntimeError('speed 모드에는 FSDP2와 safetensors가 필요합니다. 고정 Diffusers 환경을 점검하거나 --mode memory를 사용하세요.') from error


def shard_slice(shape, rank, world, dim=0):
    if not shape or not 0 <= dim < len(shape) or world < 1 or not 0 <= rank < world:
        raise ValueError('Invalid checkpoint shard geometry')
    chunk = (shape[dim] + world - 1) // world
    start = min(shape[dim], rank * chunk)
    slices = [slice(None)] * len(shape)
    slices[dim] = slice(start, min(shape[dim], start + chunk))
    return tuple(slices)


def checkpoint_files(folder):
    """Only local safetensors; never fall back to a full pickle/checkpoint load."""
    folder = Path(folder).resolve()
    indexes = sorted(folder.glob('*.safetensors.index.json'))
    if len(indexes) > 1:
        raise ValueError('여러 safetensors 인덱스가 있습니다. 모델 변형을 분리하세요.')
    if indexes:
        mapping = json.loads(indexes[0].read_text())['weight_map']
        result = {}
        for key, filename in mapping.items():
            file = (folder / filename).resolve()
            if folder not in file.parents or file.suffix != '.safetensors' or not file.is_file():
                raise ValueError('허용되지 않거나 누락된 safetensors shard: '+filename)
            result[key] = file
        return result
    from safetensors import safe_open
    files = sorted(folder.glob('*.safetensors'))
    result = {}
    for file in files:
        with safe_open(file, framework='pt', device='cpu') as source:
            for key in source.keys():
                if key in result:
                    raise ValueError('중복 checkpoint key: '+key)
                result[key] = file
    if not result:
        raise ValueError('로컬 safetensors checkpoint가 없습니다: '+str(folder))
    return result


def load_local_shards(model, folder, rank, world):
    """Copy local slices into already allocated DTensors, at most one slice at a time."""
    import torch
    from torch.distributed.tensor import DTensor, Shard, Replicate
    from safetensors import safe_open
    mapping = checkpoint_files(folder)
    state = model.state_dict(keep_vars=True)
    if set(state) != set(mapping):
        raise ValueError('checkpoint/model key 불일치: missing='+str(sorted(set(state)-set(mapping))[:6])+
                         ' unexpected='+str(sorted(set(mapping)-set(state))[:6]))
    loaded = 0
    with torch.no_grad():
        for name, parameter in state.items():
            with safe_open(mapping[name], framework='pt', device='cpu') as source:
                view = source.get_slice(name)
                shape = tuple(view.get_shape())
                if shape != tuple(parameter.shape):
                    raise ValueError('checkpoint shape 불일치: '+name)
                if isinstance(parameter, DTensor):
                    if len(parameter.placements) != 1:
                        raise ValueError('1D FSDP mesh가 필요합니다.')
                    placement = parameter.placements[0]
                    local = parameter.to_local()
                    if isinstance(placement, Shard):
                        value = view[shard_slice(shape, rank, world, placement.dim)]
                    elif isinstance(placement, Replicate):
                        value = view[...]
                    else:
                        raise ValueError('지원하지 않는 FSDP placement: '+str(placement))
                else:
                    local, value = parameter, view[...]
                if tuple(local.shape) != tuple(value.shape):
                    raise ValueError('local shard shape 불일치: '+name)
                local.copy_(value.to(dtype=local.dtype, device=local.device))
                loaded += local.numel() * local.element_size()
                del value
    return loaded


def load_fsdp_transformer(model_dir, name, device, rank, world, dtype, cp_config=None):
    import torch
    from diffusers import MiniMaxH3Transformer3DModel
    from torch.distributed.device_mesh import init_device_mesh
    try:
        from torch.distributed.fsdp import fully_shard, MixedPrecisionPolicy
    except ImportError:
        from torch.distributed._composable.fsdp import fully_shard, MixedPrecisionPolicy
    from accelerate import init_empty_weights
    # Real buffers (e.g. RoPE frequencies), meta parameters: to_empty must not
    # leave deterministic non-persistent buffers as uninitialized GPU memory.
    with init_empty_weights(include_buffers=False):
        model = MiniMaxH3Transformer3DModel.from_config(
            MiniMaxH3Transformer3DModel.load_config(model_dir, subfolder=name, local_files_only=True))
        model.to(dtype=dtype)
        keep = tuple(getattr(model, '_keep_in_fp32_modules', ()))
        for module_name, module in model.named_modules():
            if module_name and any(part in module_name.split('.') for part in keep):
                module.float()
    buffers = {name:buffer.detach().cpu().clone() for name,buffer in model.named_buffers()}
    model.eval().requires_grad_(False)
    mesh = init_device_mesh(device.type, (world,), mesh_dim_names=('weight_shard',))
    # Do not cast all gathered weights to BF16: H3 deliberately keeps projections FP32.
    policy = MixedPrecisionPolicy(cast_forward_inputs=False)
    for block in model.transformer_blocks:
        fully_shard(block, mesh=mesh, reshard_after_forward=True, mp_policy=policy)
    fully_shard(model, mesh=mesh, reshard_after_forward=True, mp_policy=policy)
    model.to_empty(device=device)
    with torch.no_grad():
        for buffer_name,buffer in model.named_buffers():
            buffer.copy_(buffers[buffer_name].to(device=buffer.device,dtype=buffer.dtype))
    del buffers
    local_bytes = load_local_shards(model, Path(model_dir)/name, rank, world)
    if cp_config is not None:
        model.enable_parallelism(config=cp_config)
    return model, dict(kind='fsdp_cp', weightCopies=1, ranks=world, localWeightBytes=local_bytes,
                       checkpointLoad='local_safetensors_slices', cpuWeightReplication=False)
