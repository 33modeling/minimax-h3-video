"""Install CPU speech tools in a separate environment; never start a GPU server."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'scripts/video-tools.json').read_text())
venv = root / '.venv-video-studio'
python = venv / 'bin/python'
if not python.exists():
    subprocess.run(['uv', 'venv', str(venv)], check=True)
subprocess.run(['uv', 'pip', 'install', '--python', str(python), manifest['asrPackage'], 'pillow==11.3.0'], check=True)
home = Path(os.environ.get('H3_STUDIO_TOOLS', Path.home() / '.local/share/h3video/studio'))
home.mkdir(parents=True, exist_ok=True)
subprocess.run([str(python), '-c',
    'from huggingface_hub import snapshot_download;import sys;snapshot_download(repo_id=sys.argv[1],revision=sys.argv[2],local_dir=sys.argv[3],allow_patterns=["model.bin","config.json","tokenizer.json","vocabulary.*","preprocessor_config.json"])',
    manifest['asrModel'], manifest['asrRevision'], str(home / 'whisper-small')], check=True)
(home / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('Ready: pinned multilingual Whisper small on CPU. Existing Real-ESRGAN and DINOv2 tools are reused.')
