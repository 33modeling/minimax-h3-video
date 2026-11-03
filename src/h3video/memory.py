"""Release failed request tensors without unloading models or touching other processes."""
import gc
import traceback
import os


def memory_report(torch, devices, stage, error):
    text = str(error).lower()
    kind = "cuda" if "cuda" in text or type(error).__name__ == "OutOfMemoryError" else "host"
    report = {"kind": kind, "stage": stage, "error": str(error), "devices": [],
              "pid": os.getpid(), "allocatorScope": "this_process"}
    for device in devices:
        if not str(device).startswith("cuda"):
            continue
        try:
            free, total = torch.cuda.mem_get_info(torch.device(device))
            row = {"device": device, "freeBytes": free, "totalBytes": total,
                   "allocatedBytes": torch.cuda.memory_allocated(device),
                   "reservedBytes": torch.cuda.memory_reserved(device)}
            for key, name in [('peakAllocatedBytes', 'max_memory_allocated'), ('peakReservedBytes', 'max_memory_reserved')]:
                if hasattr(torch.cuda, name):
                    row[key] = getattr(torch.cuda, name)(device)
            report["devices"].append(row)
        except Exception:
            pass
    return report


class GenerationMemoryError(RuntimeError):
    def __init__(self, error, report):
        self.report = report
        label = "GPU 메모리 부족(CUDA OOM)" if report["kind"] == "cuda" else "CPU 메모리 부족(OOM)"
        super().__init__(f"{label} · 단계: {report['stage']} · {error}")


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
