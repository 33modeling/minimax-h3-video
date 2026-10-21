"""웹 화면용 API: 이 서버가 준 화면 표시, 카드 목록(/api/feed: 쉬운 오류·CLI 명령·미리보기 주소), 길이 → 장면(/api/plan),
같은 설정으로 다시(/retry), 안 된 장면만 다시(/resume), 시드 random·크기·네거티브, CORS 사전 요청의 사설망 허용."""
import json
import shlex
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
from test_story import CONTI, png  # noqa: E402
from h3video import cli  # noqa: E402
from h3video.web import App, make_handler, parse_origins  # noqa: E402

BND = "Bnd42"


def form(parts):
    body = b""
    for name, fname, data in parts:
        disp = f'form-data; name="{name}"' + (f'; filename="{fname}"' if fname else "")
        body += f"--{BND}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + (data if isinstance(data, bytes) else str(data).encode()) + b"\r\n"
    return body + f"--{BND}--\r\n".encode()


class WebUiApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = App(self.url, self.url, self.tmp / "web", str(self.tmp / "inbox"), poll=0.01)
        self.web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.web.server_address[1]}"
        self.addCleanup(lambda: (self.web.shutdown(), self.web.server_close()))

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.base + path).read())

    def post(self, path, parts=None, body=None):
        if parts is not None:
            req = urllib.request.Request(self.base + path, data=form(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={BND}"})
        else:
            req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else b"", method="POST",
                                         headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            r = urllib.request.urlopen(req)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(self, pred, what="", n=400):
        for _ in range(n):
            feed = self.get("/api/feed")
            if pred(feed):
                return feed
            time.sleep(0.05)
        self.fail(f"기다렸지만 안 됨: {what} {json.dumps(feed, ensure_ascii=False)[:600]}")

    def test_page_and_spec(self):
        html = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn('data-served="h3video"', html)
        for t in ("H3 Video Studio", "글로 만들기", "그림으로 시작", "참고 자료로", "JSON 한번에", "모델 정보", "서버 주소"):
            self.assertIn(t, html)
        raw = (ROOT / "src/h3video/ui.html").read_text(encoding="utf-8")
        self.assertNotIn("data-served", raw.split("<head>")[0])     # 파일 그대로(허브에 올린 것)는 표시 없음
        sp = self.get("/api/spec")
        self.assertIn("tasks", sp); self.assertEqual(sp["sizes"], [512, 576, 640, 704, 768]); self.assertIn("MiniMax-H3", sp["model"])
        h = self.get("/api/health")
        self.assertTrue(h["fl2va"]); self.assertIsNone(h["hints"]["fl2va"]); self.assertEqual(h["endpoints"]["fl2va"], self.url)

    def test_plan_uses_server_limit_and_caches_it(self):
        p = self.get("/api/plan?seconds=40&task=t2va&aspect=16:9&size=768")
        self.assertEqual((p["scenes"], p["max_scene"]), ([10, 10, 10, 10], None))   # 모의 서버는 한도를 모른다
        self.assertEqual(self.get("/api/plan?seconds=8")["scenes"], [8])
        calls = []
        self.app.ref_client.max_seconds = lambda *a, **k: calls.append(a) or 12
        for _ in range(3):
            p = self.get("/api/plan?seconds=15&task=ref2va&aspect=9:16&size=768&images=2")
        self.assertEqual((p["scenes"], p["max_scene"], p["limit"]), ([8, 7], 12, 12))
        self.assertEqual(len(calls), 1)                                  # 잠깐 기억해 둔다
        self.assertEqual(calls[0][:4], ("9:16", 768, 0, 2))
        req = urllib.request.Request(self.base + "/api/plan?seconds=8&aspect=5:4")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)

    def test_feed_job_card_retry_and_new_fields(self):
        img = png(self.tmp / "key.png")
        code, job = self.post("/api/jobs", [("prompt", None, "비 오는 서울 밤거리"), ("seconds", None, "5"), ("aspect_ratio", None, "9:16"),
                                            ("seed", None, "random"), ("size", None, "576"), ("negative", None, "글자"), ("raw", None, "1"),
                                            ("first_image", "key.png", img.read_bytes())])
        self.assertEqual(code, 201, job)
        self.assertNotEqual(job["seed"], 0)
        self.assertEqual((job["short_edge"], job["negative"], job["raw"], job["task"]), (576, "글자", True, "fl2va"))
        feed = self.wait(lambda f: f["items"] and f["items"][0]["status"] == "completed", "완성")
        it = feed["items"][0]
        self.assertEqual(it["kind"], "job")
        self.assertTrue(it["video_url"].startswith("/files/") and it["video_url"].endswith(".mp4"))
        self.assertGreater(len(urllib.request.urlopen(self.base + it["video_url"]).read()), 1000)
        self.assertEqual(it["first_name"], "key.png")
        self.assertTrue(urllib.request.urlopen(self.base + it["first_url"]).read().startswith(b"\x89PNG"))
        a = cli.build_parser().parse_args(shlex.split(it["cli"])[1:])     # 같은 설정의 CLI 명령
        self.assertEqual((a.prompt, a.seconds, a.ratio, a.seed, a.size, a.negative, a.raw), ("비 오는 서울 밤거리", 5, "9:16", job["seed"], 576, "글자", True))
        self.assertTrue(Path(a.first).is_file())
        # 비운 시드는 예전처럼 0, JSON 요청도 그대로
        code, j0 = self.post("/api/jobs", body={"prompt": "x", "seconds": 4})
        self.assertEqual((code, j0["seed"], j0["short_edge"]), (201, 0, 768))
        self.assertEqual(self.post("/api/jobs", body={"prompt": "x", "seconds": 4, "size": 999})[0], 400)
        # 실패 → 쉬운 말 + 다시 하기
        self.state.fail_once.append("FAILME")
        code, bad = self.post("/api/jobs", body={"prompt": "FAILME 영상", "seconds": 4, "seed": 3})
        feed = self.wait(lambda f: any(x["id"] == bad["id"] and x["status"] == "failed" for x in f["items"]), "실패")
        it = next(x for x in feed["items"] if x["id"] == bad["id"])
        self.assertIn("mock failure", it["error"]); self.assertTrue(it["error_ko"])
        code, again = self.post(f"/api/jobs/{bad['id']}/retry")
        self.assertEqual(code, 201, again)
        self.assertEqual((again["prompt"], again["seed"], again["total_seconds"]), ("FAILME 영상", 3, 4))
        self.assertNotEqual(again["id"], bad["id"])
        self.wait(lambda f: any(x["id"] == again["id"] and x["status"] == "completed" for x in f["items"]), "다시 하기 완성")
        self.assertEqual(self.post("/api/jobs/nope/retry")[0], 404)

    def test_feed_story_card_and_resume(self):
        imgs = [png(self.tmp / n) for n in ("page-01.png", "page-02.png")]
        self.state.fail_once.append("Toto smiles at Bori")
        code, made = self.post("/api/story", [("json", "toto.json", json.dumps(CONTI, ensure_ascii=False).encode()),
                                              *[("images", p.name, p.read_bytes()) for p in imgs], ("size", None, "576"), ("seed", None, "5")])
        self.assertEqual(code, 201, made)
        feed = self.wait(lambda f: f["items"] and f["items"][0]["kind"] == "story" and f["items"][0]["status"] == "failed", "장면 하나 실패")
        self.assertEqual([x["kind"] for x in feed["items"]], ["story"])          # 장면 작업은 이야기 카드 안에만
        st = feed["items"][0]
        self.assertEqual((st["total"], st["done"], st["failed"]), (3, 2, 1))
        self.assertEqual([c["image_name"] for c in st["clips"]], ["page-01.png", "page-02.png", None])
        self.assertTrue(st["clips"][0]["image_url"].startswith("/files/_uploads/story-"))
        self.assertTrue(st["inputs"]["json_url"].endswith("toto.json"))
        self.assertEqual(sorted(i["name"] for i in st["inputs"]["images"]), ["page-01.png", "page-02.png"])
        self.assertIn("--resume " + made["id"], st["resume_cli"]); self.assertIn("--output-dir", st["resume_cli"])
        a = cli.build_parser().parse_args(shlex.split(st["cli"])[1:])
        self.assertEqual((a.cmd, a.size, a.seed, a.ratio), ("json", 576, 5, "4:3"))
        self.assertTrue(Path(a.file).is_file() and Path(a.images[0]).is_dir())
        self.assertTrue(next(c for c in st["clips"] if c["status"] == "failed")["error_ko"])
        code, r = self.post(f"/api/story/{made['id']}/resume")
        self.assertEqual((code, r.get("redo")), (201, 1), r)
        feed = self.wait(lambda f: f["items"][0]["status"] == "completed", "다시 해서 완성")
        st = feed["items"][0]
        self.assertTrue(st["video_url"].endswith(".mp4"))
        self.assertEqual(self.post(f"/api/story/{made['id']}/resume")[0], 400)   # 다시 할 장면이 없다
        self.assertEqual(self.post("/api/story/story-nope/resume")[0], 404)
        plan = self.post("/api/story/plan", [("json", "toto.json", json.dumps(CONTI).encode()), ("image_names", None, "page-01.png")])[1]
        self.assertEqual(plan["missing_images"], ["page-02", "page-03"])

    def test_cors_preflight_allows_private_network(self):
        site = "https://33modeling.pages.dev"
        on = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app, [site]))
        threading.Thread(target=on.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (on.shutdown(), on.server_close()))
        url = f"http://127.0.0.1:{on.server_address[1]}"
        r = urllib.request.urlopen(urllib.request.Request(url + "/api/feed", method="OPTIONS", headers={"Origin": site}))
        self.assertEqual((r.status, r.headers.get("Access-Control-Allow-Private-Network")), (204, "true"))
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), site)
        r = urllib.request.urlopen(urllib.request.Request(url + "/api/feed", headers={"Origin": site}))
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), site)
        self.assertIsNone(r.headers.get("Access-Control-Allow-Private-Network"))   # 사전 요청에만
        with self.assertRaises(urllib.error.HTTPError) as e:   # 기본(CORS 끔)은 그대로
            urllib.request.urlopen(urllib.request.Request(self.base + "/api/feed", method="OPTIONS", headers={"Origin": site}))
        self.assertEqual(e.exception.code, 405)
        self.assertIsNone(e.exception.headers.get("Access-Control-Allow-Private-Network"))


if __name__ == "__main__":
    unittest.main()


class ManagedOriginsTest(unittest.TestCase):
    def test_approved_tools_origin_is_available_without_allowing_unrelated_origins(self):
        origins=parse_origins("https://33modeling.pages.dev")
        self.assertIn("https://77modeling.pages.dev",origins)
        self.assertNotIn("https://77modeling.pages.dev",parse_origins("https://unrelated.example"))
        self.assertEqual(parse_origins(""),[])
