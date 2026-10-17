"""Release failed request tensors without unloading models or touching other processes."""
import gc
import traceback


def is_memory_failure(error):
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen: continue
        seen.add(id(current))
        text = str(current).lower()
        if isinstance(current, MemoryError) or 'out of memory' in text or 'gpu_oom' in text or '메모리 부족' in text:
            return True
        pending.extend((current.__cause__, current.__context__))
    return False


def release_request_memory(error=None, torch=None):
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if current.__traceback__:
            traceback.clear_frames(current.__traceback__)
        pending.extend((current.__cause__, current.__context__))
    gc.collect()
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            # A failed allocator cleanup must not replace the generation error.
            pass
