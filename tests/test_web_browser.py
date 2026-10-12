"""웹 UI 를 실제 브라우저(Playwright)로 끝까지 눌러 본다 — tests/e2e/web_ui.cjs.
node 와 Playwright 가 있을 때만: H3_PLAYWRIGHT=<playwright 모듈 경로> (없으면 shortform/node_modules/playwright-core + google-chrome).
스크린샷은 H3_E2E_OUT 폴더(기본: 임시 폴더)에 남는다."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_story import CONTI, png  # noqa: E402
from h3video.web import App, make_handler  # noqa: E402


class QuietStatic(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def playwright_env() -> dict | None:
    node = shutil.which("node")
    if not node:
        return None
    if os.environ.get("H3_PLAYWRIGHT"):
        return {"H3_PLAYWRIGHT": os.environ["H3_PLAYWRIGHT"]}
    core = ROOT / "shortform" / "node_modules" / "playwright-core"
    chrome = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
    if core.is_dir() and chrome:
        return {"H3_PLAYWRIGHT": str(core), "CHROME": chrome}
    return None


@unittest.skipUnless(playwright_env(), "node 와 Playwright 가 없어 브라우저 확인을 건너뜀 (H3_PLAYWRIGHT 로 지정)")
class WebBrowserTest(unittest.TestCase):
    def test_web_ui_in_a_real_browser(self):
        tmp = Path(tempfile.mkdtemp())
        out = Path(os.environ.get("H3_E2E_OUT") or tmp / "shots")
        media = tmp / "media"; media.mkdir()
        for n in ("first.png", "face.png", "style.png", "page-01.png", "page-02.png"):
            png(media / n, 64, 48)
        with wave.open(str(media / "voice.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000 * 3)
        (media / "clip.mp4").write_bytes(mock_server.fake_mp4())
        (media / "toto.json").write_text(json.dumps(CONTI, ensure_ascii=False), encoding="utf-8")

        fl, fl_state, fl_url = mock_server.start(steps=3)
        ref, _, ref_url = mock_server.start(steps=3)
        fl_state.fail_once.append("FAILME")
        app = App(fl_url, ref_url, tmp / "web", str(tmp / "inbox"), poll=0.05)
        hub_site = "http://127.0.0.1"   # 허브 대신: 다른 포트(=다른 출처)에서 ui.html 파일 그대로
        static = tmp / "hub"; static.mkdir()
        shutil.copy(ROOT / "src/h3video/ui.html", static / "index.html")
        hub = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietStatic, directory=str(static)))
        hub_origin = f"{hub_site}:{hub.server_address[1]}"
        web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, [hub_origin]))
        for s in (hub, web):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{web.server_address[1]}"
        try:
            r = subprocess.run(["node", str(ROOT / "tests/e2e/web_ui.cjs"), base, str(out), str(media), hub_origin + "/"],
                               capture_output=True, text=True, timeout=300, env={**os.environ, **playwright_env()})
        finally:
            for s in (hub, web, fl, ref):
                s.shutdown(); s.server_close()
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertIn("웹 UI 확인 끝", r.stdout)


if __name__ == "__main__":
    unittest.main()
