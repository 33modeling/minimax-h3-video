"""Small denoiser messages and durable, request-scoped worker diagnostics."""
from copy import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time


@dataclass(frozen=True)
class ReferenceLayout:
    kind: str
    has_audio: bool


def denoiser_state(state, required_keys):
    """Encoding is finished: retain layout metadata, never raw media.

    H3's denoiser selects its workflow by presence of references/keyframes. Its
    reference layout reads kind/has_audio; geometry is in the encoded latents.
    Leave the source state alone so retry preparation cannot be corrupted.
    """
    result = copy(state)
    keep = set(required_keys) | {k for keys in state.kwargs_mapping.values() for k in keys}
    result.values = {k: v for k, v in state.values.items() if k in keep and k != 'generator'}
    for key in ('references', 'image', 'last_image'):
        if result.values.get(key) is not None:
            result.values[key] = True
    if result.values.get('normalized_references') is not None:
        result.values['normalized_references'] = [ReferenceLayout(r.kind, bool(r.has_audio))
                                                   for r in result.values['normalized_references']]
    result.kwargs_mapping = {k: [name for name in names if name in result.values]
                             for k, names in state.kwargs_mapping.items()}
    return result


def write_failure(directory, request_id, rank, report):
    if not directory:
        return
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_id):
        raise ValueError('Invalid worker request ID')
    root = Path(directory)
    data = dict(report, requestId=request_id, rank=int(rank), pid=os.getpid(), recordedAt=time.time())
    destination = root / f'{request_id}-rank{int(rank)}.json'
    temporary = destination.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)


def read_failures(directory, request_id):
    if not directory or not request_id:
        return []
    reports = []
    for path in sorted(Path(directory).glob(f'{request_id}-rank*.json')):
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            row = json.loads(path.read_text())
            if row.get('requestId') == request_id:
                reports.append(row)
        except (OSError, ValueError):
            continue
    return reports
