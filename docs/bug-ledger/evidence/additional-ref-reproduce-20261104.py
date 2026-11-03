"""Read-only CPU reproductions. No models, process groups, sockets or services."""
import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch
from diffusers.modular_pipelines.modular_pipeline import PipelineState
from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3VideoReference
from diffusers.modular_pipelines.minimax_h3.modular_blocks_minimax_h3 import MiniMaxH3AutoDenoiseStep
from h3video.dserver import Engine
import h3video.dworker as worker_module

root = Path(worker_module.__file__).resolve().parents[2]
block = MiniMaxH3AutoDenoiseStep()
engine = Engine.__new__(Engine)
engine._den_keys = {i.name for i in block.inputs if i.name} | set(block.block_trigger_inputs)
messages = []
engine._conn = SimpleNamespace(send_bytes=messages.append)
response = io.BytesIO()
torch.save({'ok': True}, response)
engine._recv = lambda: b'DONE' + response.getvalue()
original = np.zeros((24, 128, 128, 3), dtype=np.uint8)
normalized = np.ones_like(original)
state = PipelineState()
state.values = {
    'references': [MiniMaxH3VideoReference(frames=original, fps=24)],
    'normalized_references': [MiniMaxH3VideoReference(frames=normalized, fps=24)],
    'condition_latents': [torch.zeros((1, 2, 2, 2, 2))],
    'latents': torch.zeros((1, 2, 2, 2, 2)),
}
engine._denoise_remote(state, torch.Generator('cpu'), {})
decoded = torch.load(io.BytesIO(messages[0]), weights_only=False)
assert np.array_equal(decoded['state'].values['references'][0].frames, original)
assert np.array_equal(decoded['state'].values['normalized_references'][0].frames, normalized)
for name in ('references', 'normalized_references'):
    decoded['state'].values[name] = [SimpleNamespace(kind='video', has_audio=False)]
compact = io.BytesIO()
torch.save(decoded, compact)

# Execute the current worker's unmodified request try/finally and reply statements
# with a fake failing pipe. This is not a full worker or distributed-runtime test.
source = Path(worker_module.__file__).read_text()
tree = ast.parse(source)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
loop = next(n for n in main.body if isinstance(n, ast.While))
start = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.Try)
             and any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                     and x.func.id == 'pipe' for x in ast.walk(n)))
fragment = ast.Module(body=loop.body[start:], type_ignores=[])
ast.fix_missing_locations(fragment)

def attempt(error):
    sent, released, stopped = [], [], []
    def fail(**_):
        raise error
    env = {'__name__': 'h3video.dworker', '__package__': 'h3video',
           'pipe': fail, 'state': object(), 'gen': None, 'job': {'kwargs': {}},
           'stop': SimpleNamespace(set=lambda: stopped.append(True)), 'th': None,
           'out': None, 'rank': 0, 'use_cuda': False, 'torch': torch, 'io': io,
           'traceback': SimpleNamespace(print_exc=lambda: None),
           'conn': SimpleNamespace(send_bytes=sent.append)}
    raised = None
    with patch('h3video.memory.release_request_memory', side_effect=lambda *a, **k: released.append(True)):
        try:
            exec(compile(fragment, str(Path(worker_module.__file__)), 'exec'), env)
        except RuntimeError as caught:
            raised = str(caught)
    return {'doneMessages': len(sent), 'raised': raised, 'finallyRan': bool(stopped),
            'cleanupCalls': len(released)}

oom = attempt(RuntimeError('CUDA out of memory (synthetic audit failure)'))
control = attempt(RuntimeError('ordinary synthetic error'))
assert oom['doneMessages'] == 0 and oom['raised'] and oom['finallyRan']
assert control['doneMessages'] == 1 and control['raised'] is None
report = {
    'sourceCommit': '7b705452056e93f55ed07a9ef94d64ac2919bd9d',
    'scope': 'CPU code-path audit; synthetic arrays; captured transport; extracted worker request statements',
    'rpc': {'originalArrayBytes': original.nbytes, 'normalizedArrayBytes': normalized.nbytes,
            'actualPayloadBytes': len(messages[0]),
            'illustrativeMetadataOnlyPayloadBytes': len(compact.getvalue()),
            'rawOriginalAndNormalizedFramesSurviveRPC': True,
            'metadataReplacementCompatibilityValidated': False},
    'workerErrorReply': {'oom': oom, 'nonMemoryControl': control,
                         'fullDistributedWorkerExecuted': False,
                         'stderrTracebackStillExistsInProduction': True},
    'sourceHashes': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (root/'src/h3video/dserver.py', Path(worker_module.__file__))},
    'limits': {'H100InferenceMeasured': False, 'userOOMCauseConfirmed': False,
               'runtimeCodeChanged': False, 'serversStartedOrRestarted': 0},
}
dest = Path(__file__).with_name('additional-ref-reproductions-20261104.json')
dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
