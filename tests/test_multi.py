"""여러 편 한꺼번에(밤새 돌려 두기): multi 로 넣은 이야기는 영상 서버가 꺼져 있다가 켜지면 기다렸다가 다시 만들고,
서버를 다시 켜서 대기열에서 빠진 장면은 다시 넣고, 브라우저 없이도 다 만든 장면을 이어 붙인다."""
import json
import os
import socket
import subprocess
import zipfile
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_web_ui import BND, form  # noqa: E402
from h3video import story as ST  # noqa: E402
from h3video import storyrun as SR  # noqa: E402
from h3video.web import App, make_handler  # noqa: E402
from test_story import CONTI, png  # noqa: E402
from test_web_browser import playwright_env  # noqa: E402

BOOK = {"title": "두 장면", "clips": [{"prompt": "a cat walks", "seconds": 5}, {"prompt": "a cat sleeps", "seconds": 5}]}


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


class MultiTest(unittest.TestCase):
    def serve(self, endpoint):
        tmp = Path(tempfile.mkdtemp())
        app = App(endpoint, endpoint, tmp / "web", str(tmp / "inbox"), poll=0.01)
        web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=web.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (web.shutdown(), web.server_close()))
        return app, f"http://127.0.0.1:{web.server_address[1]}"

    def post(self, base, parts):
        req = urllib.request.Request(base + "/api/story", data=form(parts), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={BND}"})
        try:
            r = urllib.request.urlopen(req)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def until(self, pred, what, n=600):
        for _ in range(n):
            if pred():
                return
            time.sleep(0.02)
        self.fail("기다렸지만 안 됨: " + what)

    def jobs(self, app, name):
        st = SR.load_state(app.store.root / name)
        return [app.store.get(c["job_id"]) for c in st["clips"]]

    def test_waits_for_the_video_server_then_finishes_without_a_browser(self):
        port = free_port()
        app, base = self.serve(f"http://127.0.0.1:{port}")
        code, made = self.post(base, [("json", "a.json", json.dumps(BOOK).encode()), ("multi", None, "multi-test")])
        self.assertEqual(code, 201)
        name = made["id"]
        self.assertEqual(SR.load_state(app.store.root / name)["multi"], "multi-test")
        self.until(lambda: all(j.status == "failed" for j in self.jobs(app, name)), "영상 서버가 꺼져 있어 실패")
        self.assertRegex(self.jobs(app, name)[0].error, "연결 실패")
        t0 = time.time()
        app.keep_multi(now=t0)                                   # 바로 다시 하지 않고 1분 뒤로 잡는다
        self.assertGreater(SR.load_state(app.store.root / name)["multi_retry"]["at"], t0 + 59)
        app.keep_multi(now=t0 + 30)
        self.assertTrue(all(j.status == "failed" for j in self.jobs(app, name)))
        httpd, _, _ = mock_server.start(port=port, steps=2)       # 영상 서버가 다시 켜졌다
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        app.keep_multi(now=t0 + 61)
        self.until(lambda: all(j.status == "completed" for j in self.jobs(app, name)), "다시 만들기")
        app.keep_multi()                                          # 화면 없이도 이어 붙인다
        st = SR.load_state(app.store.root / name)
        self.assertTrue(st.get("output") and Path(st["output"]).is_file())
        self.assertEqual(st["multi_retry"]["count"], 1)

    def test_requeues_scenes_left_behind_by_a_restart_but_not_user_paused_or_plain_stories(self):
        httpd, _, url = mock_server.start(steps=2)
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        app, _ = self.serve(url)
        made = []
        for multi in ("multi-x", None, "multi-paused"):
            story = ST.load_story(json.dumps(BOOK))
            state = SR.initial_state(story, {"size": 768, "narration": True, "seed": 0})
            if multi:
                state["multi"] = multi
            if multi == "multi-paused":
                state["paused"] = True
            jobs = SR.jobs_for(state)
            d = SR.new_story_dir(app.store.root)
            SR.save_state(d, state)
            for job in jobs:
                job.group_id = d.name
                app.store.add(job)                               # 서버를 다시 켠 것처럼: 기록에는 있고 대기열에는 없다
            made.append(d.name)
        app.keep_multi()
        self.until(lambda: all(j.status == "completed" for j in self.jobs(app, made[0])), "남은 장면 다시 넣기")
        app.keep_multi()
        self.assertTrue(SR.load_state(app.store.root / made[0]).get("output"))
        self.assertTrue(all(j.status == "pending" for j in self.jobs(app, made[1])))      # 여러 편이 아닌 이야기는 그대로
        self.assertTrue(all(j.status == "pending" for j in self.jobs(app, made[2])))      # 사용자가 멈춘 묶음도 그대로

    def test_other_failures_are_retried_only_twice(self):
        httpd, _, url = mock_server.start(steps=2)
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        app, base = self.serve(url)
        code, made = self.post(base, [("json", "a.json", json.dumps(BOOK).encode()), ("multi", None, "multi-y")])
        name = made["id"]
        self.until(lambda: all(j.status == "completed" for j in self.jobs(app, name)), "완성")
        st = SR.load_state(app.store.root / name)
        job = self.jobs(app, name)[0]
        job.status, job.error = "failed", "HTTP 400: bad prompt"
        app.store.save(job)
        st["clips"][0]["output"] = None
        st["multi_retry"] = {"count": 2}
        SR.save_state(app.store.root / name, st)
        app.keep_multi(now=time.time() + 3600)
        self.assertEqual(self.jobs(app, name)[0].status, "failed")
        self.assertNotIn("at", SR.load_state(app.store.root / name)["multi_retry"])



@unittest.skipUnless(playwright_env(), "node 와 Playwright 가 없어 브라우저 확인을 건너뜀 (H3_PLAYWRIGHT 로 지정)")
class MultiBrowserTest(unittest.TestCase):
    def test_multi_ui_in_a_real_browser(self):
        tmp = Path(tempfile.mkdtemp())
        media = tmp / "media"; media.mkdir()
        (media / "toto.json").write_text(json.dumps(CONTI, ensure_ascii=False), encoding="utf-8")
        (media / "bad.json").write_text("{oops", encoding="utf-8")
        png(media / "page-01.png", 64, 48)
        book = {"kind": "batch", "title": "달빛 토끼", "width": 1152, "height": 864, "items": [
            {"id": "page-01", "kind": "page", "label": "1쪽", "page": 1, "text": "토끼가 뛰었어요.", "image": "images/page-01.png", "scene": "A rabbit jumps"},
            {"id": "page-02", "kind": "page", "label": "2쪽", "page": 2, "text": "잘 자요.", "image": "images/page-02.png", "scene": "The rabbit sleeps"}]}
        with zipfile.ZipFile(media / "book.zip", "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("book.json", json.dumps(book, ensure_ascii=False))
            for n in ("page-01", "page-02"):
                zf.writestr(f"images/{n}.png", (media / "page-01.png").read_bytes())
        httpd, _, url = mock_server.start(steps=2)
        app = App(url, url, tmp / "web", str(tmp / "inbox"), poll=0.02)
        web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            r = subprocess.run(["node", str(ROOT / "tests/e2e/multi_ui.cjs"), f"http://127.0.0.1:{web.server_address[1]}", str(media)],
                               capture_output=True, text=True, timeout=300, env={**os.environ, **playwright_env()})
        finally:
            for srv in (web, httpd):
                srv.shutdown(); srv.server_close()
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertIn("여러 편 확인 끝", r.stdout)


if __name__ == "__main__":
    unittest.main()
