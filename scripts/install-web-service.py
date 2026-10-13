"""Publish the existing 8790 web application as a user service; no GPU server startup."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
directory = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
directory.mkdir(parents=True, exist_ok=True)
service = directory / 'h3video-web.service'
service.write_text(f'''[Unit]
Description=H3 Video Studio web and editing tools
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
Environment=PYTHONPATH={root / 'src'}
Environment=PYTHONUNBUFFERED=1
ExecStart={sys.executable} -m h3video.cli web --host 127.0.0.1 --port 8790 --cors-origin https://33modeling.pages.dev,http://127.0.0.1:4173,http://localhost:4173
Restart=on-failure
RestartSec=3
TimeoutStopSec=20

[Install]
WantedBy=default.target
''')
subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
subprocess.run(['systemctl', '--user', 'enable', '--now', service.name], check=True)
print('Existing H3 web endpoint deployed: 127.0.0.1:8790. Generation model endpoints and their processes are unchanged.')
