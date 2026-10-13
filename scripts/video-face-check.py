"""Inspect sampled human faces with the existing pinned local DINOv2 engine."""
import importlib.util
import json
import os
from pathlib import Path
import sys

source = Path(os.environ.get('H3_SHARED_STUDIO', Path(__file__).resolve().parents[2] / 'storybook-maker'))
spec = importlib.util.spec_from_file_location('consistency', source / 'scripts/studio-consistency.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
v = json.load(sys.stdin)
reference = None
events = []
measured = 0
for sample in v['samples']:
    im = engine.vision.image(sample['file']).convert('RGB')
    boxes = engine.faces(im)
    if not boxes:
        continue
    features = [engine.feature(engine.crop(im, box)) for box in boxes]
    if reference is None:
        reference = features[0]
    score = max(float(reference @ f) for f in features)
    measured += 1
    if score < float(v.get('threshold', .62)):
        events.append({'type': 'appearance', 'start': sample['time'], 'end': sample['time'],
                       'score': round(score, 4), 'reason': '첫 검출 얼굴과 시각 특징이 달라 확인이 필요합니다.'})
print(json.dumps({'events': events, 'measuredFaces': measured, 'sampleCount': len(v['samples']),
    'engine': 'DINOv2 ViT-S/14 + human face detector',
    'note': '동일 인물 확률이 아닙니다. 얼굴 미검출·의도된 인물 전환은 자동 판정하지 않습니다.'}, ensure_ascii=False))
