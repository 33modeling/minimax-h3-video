import json
import os
from pathlib import Path
import sys
from faster_whisper import WhisperModel

v = json.load(sys.stdin)
home = Path(os.environ.get('H3_STUDIO_TOOLS', Path.home() / '.local/share/h3video/studio'))
model = WhisperModel(str(home / 'whisper-small'), device='cpu', compute_type='int8', cpu_threads=2)
segments, info = model.transcribe(v['input'], language=v.get('language') or None, beam_size=5,
                                  word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
captions = []
for segment in segments:
    if segment.text.strip():
        captions.append({'start': round(segment.start, 3), 'end': round(segment.end, 3),
                         'text': segment.text.strip(), 'words': [
            {'start': round(w.start, 3), 'end': round(w.end, 3), 'text': w.word, 'probability': w.probability}
            for w in segment.words or []]})
print(json.dumps({'captions': captions, 'language': info.language, 'languageProbability': info.language_probability,
                  'engine': 'faster-whisper small / CPU int8', 'duration': info.duration}, ensure_ascii=False))
