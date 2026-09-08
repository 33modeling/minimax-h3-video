import io
import json
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mock_server  # noqa: E402
from h3video import spec  # noqa: E402
from h3video.client import Condition, H3Client, H3Error, VideoRequest, stage_input  # noqa: E402
from h3video.jobs import JobStore, Worker, new_job  # noqa: E402
from h3video.prompt import build_context_ir, is_context_ir, scene_prompts  # noqa: E402


class SpecTest(unittest.TestCase):
    def test_plan_scenes(self):
        self.assertEqual(spec.plan_scenes(8), [8])
        self.assertEqual(spec.plan_scenes(15), [15])
        self.assertEqual(spec.plan_scenes(20), [10, 10])
        self.assertEqual(spec.plan_scenes(23), [8, 8, 7])
        self.assertEqual(spec.plan_scenes(27), [9, 9, 9])
        self.assertEqual(spec.plan_scenes(16, 15), [8, 8])
        self.assertEqual(spec.plan_scenes(60, 15), [15, 15, 15, 15])
        for s in spec.plan_scenes(97, 12):
            self.assertTrue(spec.DURATION_MIN <= s <= spec.DURATION_MAX)
        self.assertEqual(sum(spec.plan_scenes(97, 12)), 97)

    def test_validate(self):
        VideoRequest("x", duration_seconds=4).validate()
        with self.assertRaises(H3Error):
            VideoRequest("x", duration_seconds=16).validate()
        with self.assertRaises(H3Error):
            VideoRequest("x", task="t2va", conditions=[Condition("image", "file:///a.png", "keyframe", 0)]).validate()
        with self.assertRaises(H3Error):
            VideoRequest("x", task="ref2va", conditions=[Condition("video", "file:///v.mp4")] * 4).validate()

    def test_prompt(self):
        p = build_context_ir("a cat", "purring", "piano")
        self.assertTrue(is_context_ir(p))
        self.assertFalse(is_context_ir("a cat"))
        self.assertEqual(len(scene_prompts("a cat walks", 3)), 3)
        self.assertEqual(len(scene_prompts("[Shot 1] a [Shot 2] b [Shot 3] c", 2)), 2)


class ClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start()
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_health_and_generate(self):
        c = H3Client(self.url)
        self.assertTrue(c.healthy())
        out = c.generate(VideoRequest("a dog on the beach", duration_seconds=6), self.tmp / "dog.mp4", poll=0.01)
        self.assertTrue(out.exists() and out.stat().st_size > 1000)
        self.assertTrue(Path(str(out) + ".json").exists())
        req = self.state.requests[-1]
        self.assertEqual(req["target"]["duration_seconds"], 6)
        self.assertEqual(req["task"], "t2va")

    def test_stage_input(self):
        img = self.tmp / "in.png"; img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        inbox = self.tmp / "inbox"
        uri = stage_input(img, inbox)
        self.assertTrue(uri.startswith("file://") and "inbox" in uri)
        self.assertEqual(stage_input("https://x/y.png", inbox), "https://x/y.png")
        with self.assertRaises(H3Error):
            stage_input(self.tmp / "missing.png", inbox)

    def test_worker_chain(self):
        store = JobStore(self.tmp / "out")
        w = Worker(store, H3Client(self.url), inbox_dir=str(self.tmp / "inbox"), poll=0.01)
        w.start()
        img = self.tmp / "first.png"; img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        job = new_job("a boat sails away", seconds=25, first_image=str(img), scene_seconds=10)
        w.enqueue(job)
        for _ in range(600):
            time.sleep(0.05)
            if store.get(job.id).status in ("completed", "failed"):
                break
        jb = store.get(job.id)
        if not mock_server.shutil.which("ffmpeg"):
            self.assertEqual(jb.status, "failed"); self.assertIn("ffmpeg", jb.error); return
        self.assertEqual(jb.status, "completed", jb.error)
        self.assertEqual([s.duration for s in jb.scenes], [9, 8, 8])
        self.assertEqual([s.task for s in jb.scenes], ["fl2va"] * 3)
        self.assertTrue(Path(jb.output).exists())
        reqs = self.state.requests[-3:]
        self.assertEqual(reqs[0]["conditions"][0]["frame_index"], 0)
        self.assertIn("scene01.last.png", reqs[1]["conditions"][0]["uri"])
        self.assertEqual(reqs[1]["seed"], 1)

    def test_web(self):
        from h3video.web import App, make_handler
        from http.server import ThreadingHTTPServer
        import threading
        app = App(self.url, self.url, self.tmp / "web", str(self.tmp / "inbox"), poll=0.01)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        html = urllib.request.urlopen(base + "/").read().decode()
        self.assertIn("H3 Video Studio", html)
        sp = json.loads(urllib.request.urlopen(base + "/api/spec").read())
        self.assertEqual(sp["duration_max"], 15)
        boundary = "XyZ123"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n비 오는 서울 밤거리\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"seconds\"\r\n\r\n5\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"aspect_ratio\"\r\n\r\n9:16\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"first_image\"; filename=\"f.png\"\r\nContent-Type: image/png\r\n\r\n").encode() \
            + b"\x89PNG" + b"\x01" * 50 + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(base + "/api/jobs", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        created = json.loads(urllib.request.urlopen(req).read())
        self.assertEqual(created["task"], "fl2va"); self.assertEqual(created["aspect_ratio"], "9:16")
        for _ in range(200):
            time.sleep(0.05)
            jb = json.loads(urllib.request.urlopen(f"{base}/api/jobs/{created['id']}").read())
            if jb["status"] in ("completed", "failed"):
                break
        self.assertEqual(jb["status"], "completed", jb.get("error"))
        name = jb["output"].split("/")[-1]
        data = urllib.request.urlopen(f"{base}/files/{created['id']}/{urllib.request.quote(name)}").read()
        self.assertGreater(len(data), 1000)
        httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
