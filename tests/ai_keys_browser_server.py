"""생성 방식(키) 브라우저 점검용: 실제 h3video 웹 서버(127.0.0.1:4561, 화면·API)와 같은 프로세스 안의 가짜 영상 서버.
tests/e2e/ai_keys.mjs 가 띄우고 끈다. 포트를 바꾸려면 H3_AI_E2E_PORT."""
import json
import os
import signal
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_server  # noqa: E402
from h3video.web import App, make_handler  # noqa: E402

directory = Path(sys.argv[1]); directory.mkdir(parents=True, exist_ok=True)
backend, state, endpoint = mock_server.start(steps=2)
app = App(endpoint, endpoint, directory / "outputs", None, poll=.02)
server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("H3_AI_E2E_PORT", "4561"))), make_handler(app, ["*"]))
print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}"}), flush=True)


def interrupted(signum, frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, interrupted)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    for close in (getattr(app, "motion", None), getattr(app, "studio", None)):
        try:
            close and close.close()
        except Exception:
            pass
    backend.shutdown(); backend.server_close()
