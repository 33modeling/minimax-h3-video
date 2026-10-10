"""2026-10-10 점검에서 찾은 버그의 회귀 테스트."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mock_server  # noqa: E402
from h3video import cli, jobs as J  # noqa: E402
from h3video.client import H3Client, H3Error, VideoRequest  # noqa: E402


def closing_server():
    """연결을 받자마자 끊는 서버 = SSH 터널은 살아 있는데 원격 서버가 꺼진 상태."""
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", 0)); s.listen(50)
    stop = threading.Event()

    def loop():
        s.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = s.accept(); c.close()
            except OSError:
                pass
    threading.Thread(target=loop, daemon=True).start()
    return s, stop, f"http://127.0.0.1:{s.getsockname()[1]}"


def silent_server():
    """연결은 받지만 아무 응답도 하지 않는 서버 = 멈춘 서버."""
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(50)
    held = []

    def loop():
        try:
            for _ in range(50):
                held.append(s.accept())
        except OSError:
            pass  # 테스트가 소켓을 닫음
    threading.Thread(target=loop, daemon=True).start()
    return s, f"http://127.0.0.1:{s.getsockname()[1]}"


class BugfixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_dropped_connection_is_an_h3error_not_a_crash(self):
        s, stop, url = closing_server()
        try:
            self.assertFalse(H3Client(url).healthy())
            with self.assertRaises(H3Error):
                H3Client(url).status("x")
        finally:
            stop.set(); s.close()

    def test_health_check_is_short_and_tui_does_not_block(self):
        s, url = silent_server()
        try:
            t0 = time.time()
            self.assertFalse(H3Client(url, timeout=60).healthy(timeout=0.3))
            self.assertLess(time.time() - t0, 3)
            from h3video.tui import Tui
            tui = Tui(url, url, self.tmp / "tui", None, 0.05)
            t0 = time.time(); tui.check_health()
            self.assertLess(time.time() - t0, 0.5)   # 확인은 백그라운드 스레드에서
        finally:
            s.close()

    def test_wait_timeout_message_tells_how_to_fetch(self):
        slow, _, slow_url = mock_server.start(steps=10_000)
        try:
            c = H3Client(slow_url)
            vid = c.submit(VideoRequest("x", duration_seconds=4))
            with self.assertRaises(H3Error) as e:
                c.wait(vid, poll=0.01, timeout=0.2)
            self.assertIn(f"h3video fetch {vid}", str(e.exception))
        finally:
            slow.shutdown(); slow.server_close()

    def test_stale_jobs_from_dead_processes_on_this_host(self):
        root = self.tmp / "out"
        dead = J.Job(id="dead", prompt="p", total_seconds=8, aspect_ratio="16:9", seed=0, task="t2va", status="running",
                     host=J.HOST, pid=2 ** 22 + 12345, scenes=[J.Scene(0, "p", 8, "t2va", video_id="video_0007", status="in_progress")])
        other = J.Job(id="other", prompt="p", total_seconds=8, aspect_ratio="16:9", seed=0, task="t2va", status="running",
                      host="another-node", pid=1)
        mine = J.Job(id="mine", prompt="p", total_seconds=8, aspect_ratio="16:9", seed=0, task="t2va", status="running",
                     host=J.HOST, pid=os.getpid())
        store = J.JobStore(root)
        for j in (dead, other, mine):
            store.add(j)
        again = J.JobStore(root)
        self.assertEqual(again.get("dead").status, "failed")
        self.assertIn("h3video fetch video_0007", again.get("dead").error)
        self.assertEqual(again.get("other").status, "running")   # 다른 노드의 작업은 건드리지 않는다
        self.assertEqual(again.get("mine").status, "running")
        self.assertEqual(list(root.glob("*/.job.*.tmp")), [])      # 원자적 저장: 임시 파일이 남지 않는다

    def test_web_files_support_range_and_json_paths_are_restricted(self):
        from h3video.web import App, make_handler
        from http.server import ThreadingHTTPServer
        app = App(self.url, self.url, self.tmp / "web", str(self.tmp / "inbox"), poll=0.01)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            d = self.tmp / "web" / "job1"; d.mkdir(parents=True)
            data = bytes(range(256)) * 40
            (d / "v.mp4").write_bytes(data)
            r = urllib.request.urlopen(base + "/files/job1/v.mp4")
            self.assertEqual((r.status, r.headers["Accept-Ranges"], r.read()), (200, "bytes", data))
            r = urllib.request.urlopen(urllib.request.Request(base + "/files/job1/v.mp4", headers={"Range": "bytes=100-199"}))
            self.assertEqual((r.status, r.headers["Content-Range"], r.read()), (206, f"bytes 100-199/{len(data)}", data[100:200]))
            r = urllib.request.urlopen(urllib.request.Request(base + "/files/job1/v.mp4", headers={"Range": "bytes=-50"}))
            self.assertEqual(r.read(), data[-50:])
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(base + "/files/job1/v.mp4", headers={"Range": f"bytes={len(data)}-"}))
            self.assertEqual(e.exception.code, 416)

            def post(body):
                req = urllib.request.Request(base + "/api/jobs", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
                try:
                    return urllib.request.urlopen(req).status, None
                except urllib.error.HTTPError as err:
                    return err.code, json.loads(err.read())["error"]
            secret = self.tmp / "secret.txt"; secret.write_text("x")
            code, err = post({"prompt": "x", "seconds": 4, "first_image": str(secret)})
            self.assertEqual(code, 400); self.assertIn("업로드", err)
            code, err = post({"prompt": "x", "seconds": 4, "refs": [{"type": "image", "path": "/etc/passwd"}]})
            self.assertEqual(code, 400)
            code, err = post({"prompt": "x", "seconds": 4, "refs": [{"kind": "image"}]})
            self.assertEqual(code, 400); self.assertIn("refs", err)
            self.assertEqual(post({"prompt": "x", "seconds": 4, "first_image": "https://example.com/a.png"})[0], 201)
            inbox_file = self.tmp / "inbox" / "k.png"; inbox_file.parent.mkdir(exist_ok=True); inbox_file.write_bytes(b"\x89PNG")
            self.assertEqual(post({"prompt": "x", "seconds": 4, "first_image": str(inbox_file)})[0], 201)
        finally:
            httpd.shutdown(); httpd.server_close()

    def test_batch_results_with_the_same_name_do_not_overwrite(self):
        (self.tmp / "b.txt").write_text("title: same\n첫 영상\n---\ntitle: same\n둘째 영상\n", encoding="utf-8")
        g = ["--endpoint", self.url, "--output-dir", str(self.tmp / "o"), "--poll", "0.01"]
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["batch", str(self.tmp / "b.txt"), "-s", "4", "-o", str(self.tmp / "all"), *g])
        paths = out.getvalue().split()
        self.assertEqual(len(set(paths)), 2)
        self.assertEqual(len(list((self.tmp / "all").iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
