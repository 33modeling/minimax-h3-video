"""Reuse one request's CPU inputs and rewritten prompt across bounded retries."""
import os
from pathlib import Path
import shutil
import tempfile


class RequestPreparation:
    def __init__(self, memory_bytes=None):
        self.memory_bytes = memory_bytes if memory_bytes is not None else int(os.environ.get('H3_INPUT_CACHE_MIB', '256')) * 2**20
        self.inputs = None
        self.first_image = None
        self.prompt = None
        self._temporary = None
        self._maps = []
        self._remaining = self.memory_bytes

    def remember(self, inputs, first_image):
        import numpy as np
        from PIL import Image
        # Non-video images/audio also count against the in-RAM cache budget.
        remaining = self.memory_bytes
        values = [inputs.get(k) for k in ('image', 'last_image')]
        for ref in inputs.get('references', []):
            values.extend([getattr(ref, 'image', None), getattr(ref, 'audio', None)])
        for value in values:
            if isinstance(value, Image.Image):
                remaining -= value.width * value.height * len(value.getbands())
            elif isinstance(value, np.ndarray):
                remaining -= value.nbytes
            elif hasattr(value, 'numel'):
                remaining -= value.numel() * value.element_size()
        if remaining < 0:
            return
        self._remaining = remaining
        # Reference objects are private to this request. Large frame arrays are
        # backed by a temporary mapping rather than retained as anonymous RAM.
        for ref in inputs.get('references', []):
            frames = getattr(ref, 'frames', None)
            if not isinstance(frames, np.ndarray):
                continue
            if frames.nbytes <= self._remaining:
                self._remaining -= frames.nbytes
                continue
            self._temporary = self._temporary or tempfile.TemporaryDirectory(prefix='h3-input-')
            free = shutil.disk_usage(self._temporary.name).free
            if frames.nbytes + 64 * 2**20 > free:
                # No unbounded fallback cache when a node's scratch disk is full.
                self.inputs = None
                return
            path = Path(self._temporary.name) / f'frames-{len(self._maps)}.npy'
            try:
                np.save(path, frames, allow_pickle=False)
                mapped = np.load(path, mmap_mode='r+', allow_pickle=False)
            except OSError:
                path.unlink(missing_ok=True)
                return
            ref.frames = mapped
            self._maps.append(mapped)
        self.inputs, self.first_image = dict(inputs), first_image

    def close(self):
        self.inputs = self.first_image = self.prompt = None
        for mapped in self._maps:
            mapped._mmap.close()
        self._maps.clear()
        if self._temporary:
            self._temporary.cleanup()
