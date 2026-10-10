"""h3video.dserver (Diffusers 엔진 서버)의 요청 검사·길이 계산·HTTP API. 무거운 모델 없이 가짜 엔진으로 돈다.

실제 파이프라인(diffusers 0.41 MiniMaxH3)과의 연결은 작은 H3 모델로 따로 확인했다 (2026-10-10, torch 2.7.1 CPU):
세 작업 생성·두 GPU 분할과 한 GPU 결과 프레임 동일·mp4(h264 24fps + AAC 스테레오).
"""
import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from h3video import dserver  # noqa: E402
from h3video.client import Condition, H3Client, H3Error, VideoRequest  # noqa: E402

FAKE_PIPE = SimpleNamespace(vae_frames_per_chunk=17, vae_latents_per_chunk=5, fps=24, min_duration=5.0,
                            max_duration=15.0, canvas_multiple=32)


def fake_engine(variant="fl2va"):
    e = dserver.Engine.__new__(dserver.Engine)
    e.variant, e.pipe, e.geo, e.short_edge, e.max_pixels = variant, FAKE_PIPE, FAKE_PIPE, 768, 768 * 1344
    return e


class WorkerHelpersTest(unittest.TestCase):
    def test_addr(self):
        from h3video import dworker
        self.assertEqual(dworker.tuple_addr("127.0.0.1:4567"), ("127.0.0.1", 4567))

    @unittest.skipUnless(importlib.util.find_spec("torch"), "torch 없음")
    def test_to_cpu(self):
        import torch
        out = dserver._to_cpu({"a": [torch.ones(2), (2, "x")], "b": None})
        self.assertEqual(out["a"][1], (2, "x"))
        self.assertEqual(out["a"][0].device.type, "cpu")

    def test_pick_devices_spec(self):
        self.assertEqual(dserver.pick_devices("cpu, cpu,cpu"), ["cpu", "cpu", "cpu"])


@unittest.skipUnless(importlib.util.find_spec("diffusers"), "diffusers 없음")
class MemoryCheckTest(unittest.TestCase):
    """영상 모델 장의 여유(가중치 62GB 를 뺀 약 16.5GB)에 길이·해상도가 들어가는지 생성 전에 판정."""

    def engine(self, world=1, headroom_gb=16.5):
        e = fake_engine()
        e.cp_world, e.headroom = world, int(headroom_gb * 2**30)
        return e

    def body(self, seconds, size=768):
        return {"task": "t2va", "prompt": "p", "target": {"short_edge": size, "aspect_ratio": "16:9", "duration_seconds": seconds}}

    def test_one_gpu_15s_rejected_with_advice(self):
        with self.assertRaises(dserver.BadRequest) as cm:
            self.engine().plan(self.body(15))
        msg = str(cm.exception)
        self.assertIn("-s 12 이하", msg)   # 13초는 프레임이 328(13.67초)로 올림돼 안 들어간다
        self.assertIn("--size 576", msg)
        self.assertIn("GPU 4장", msg)

    def test_fits(self):
        self.engine().plan(self.body(10))             # 1장, 10초
        self.engine().plan(self.body(15, size=576))   # 1장, 15초라도 576 이면
        self.engine(world=3).plan(self.body(15))      # 3장에 나누면 15초

    def test_rows(self):
        r = self.engine().rows({"num_frames": 345, "keyframes": []}, 768, 1344)
        self.assertEqual(r["video"], 102 * 24 * 42)   # 잠재 프레임 102 × (768/32) × (1344/32)
        self.assertEqual(r["audio"], 575 * 2)


class FramesTest(unittest.TestCase):
    def test_frames(self):
        f = lambda s: dserver.frames_for(s, 17, 5, 24, 5.0, 15.0)
        self.assertEqual(f(5), (124, 5.0))
        self.assertEqual(f(8), (192, 8.0))      # 192 = 17*11+5
        self.assertEqual(f(4), (124, 5.0))      # 최소 5초로 올림
        self.assertEqual(f(15), (345, 15.0))    # 362 는 15초를 넘으므로 내림
        self.assertEqual(f(30), (345, 15.0))
        for s in range(1, 20):
            n, _ = f(s)
            self.assertEqual(n % 17, 5)
            self.assertTrue(120 <= n <= 360, (s, n))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.img = Path(self.tmp.name, "a.png")
        self.img.write_bytes(b"x")
        self.uri = self.img.as_uri()

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, body, variant="fl2va"):
        body.setdefault("prompt", "p")
        body.setdefault("target", {"short_edge": 768, "aspect_ratio": "16:9", "duration_seconds": 8})
        return fake_engine(variant).plan(body)

    def test_t2va(self):
        p = self.plan({"task": "t2va", "seed": 7, "num_inference_steps": 30})
        self.assertEqual((p["task"], p["num_frames"], p["seed"], p["steps"]), ("t2va", 192, 7, 30))
        self.assertEqual(self.plan({"task": "t2va"})["steps"], 50)

    def test_keyframe_slots(self):
        kf = lambda fi: {"type": "image", "uri": self.uri, "role": "keyframe", "frame_index": fi}
        self.assertEqual([s for s, _ in self.plan({"task": "fl2va", "conditions": [kf(0)]})["keyframes"]], ["image"])
        self.assertEqual([s for s, _ in self.plan({"task": "fl2va", "conditions": [kf(-1)]})["keyframes"]], ["last_image"])
        self.assertEqual([s for s, _ in self.plan({"task": "fl2va", "conditions": [kf(0), kf(-1)]})["keyframes"]],
                         ["image", "last_image"])
        self.assertEqual([s for s, _ in self.plan({"task": "fl2va", "conditions": [kf(None), kf(None)]})["keyframes"]],
                         ["image", "last_image"])

    def test_rejects(self):
        kf = {"type": "image", "uri": self.uri, "role": "keyframe", "frame_index": 0}
        ref = lambda t: {"type": t, "uri": self.uri, "role": "reference"}
        bad = [
            ({"task": "ref2va", "conditions": [ref("image")]}, "fl2va"),
            ({"task": "t2va"}, "ref2va"),
            ({"task": "t2va", "prompt": "  "}, "fl2va"),
            ({"task": "t2va", "conditions": [kf]}, "fl2va"),
            ({"task": "fl2va"}, "fl2va"),
            ({"task": "fl2va", "conditions": [kf, kf]}, "fl2va"),                     # 같은 자리 두 번
            ({"task": "fl2va", "conditions": [kf] * 3}, "fl2va"),
            ({"task": "t2va", "num_outputs_per_prompt": 2}, "fl2va"),
            ({"task": "fl2va", "conditions": [dict(kf, uri="file:///nope/x.png")]}, "fl2va"),
            ({"task": "ref2va", "conditions": [ref("audio")]}, "ref2va"),             # 오디오만은 안 됨
            ({"task": "ref2va", "conditions": [ref("image")] * 10}, "ref2va"),
            ({"task": "ref2va", "conditions": [ref("video")] * 4}, "ref2va"),
            ({"task": "ref2va", "conditions": [ref("gif")]}, "ref2va"),
        ]
        for body, variant in bad:
            with self.subTest(body=body, variant=variant), self.assertRaises(dserver.BadRequest):
                self.plan(body, variant)

    def test_ref_ok_and_ignored(self):
        refs = [{"type": t, "uri": self.uri, "role": "reference"} for t in ("image", "video", "video_audio", "audio")]
        p = self.plan({"task": "ref2va", "conditions": refs, "negative_prompt": "blur"}, "ref2va")
        self.assertEqual([c["type"] for c in p["refs"]], ["image", "video", "video_audio", "audio"])
        self.assertEqual(p["ignored"], ["negative_prompt"])

    def test_local_path(self):
        self.assertEqual(dserver.local_path("file:///a%20b/c.png"), "/a b/c.png")
        self.assertEqual(dserver.local_path("https://x/y.png"), "https://x/y.png")


class FakeRunEngine:
    """plan 은 진짜, run 은 가짜 mp4 를 쓴다 (진행률 콜백 포함)."""
    variant = "fl2va"

    def __init__(self):
        self.inner = fake_engine("fl2va")
        self.ran = []

    def plan(self, body):
        return self.inner.plan(body)

    def run(self, plan, out_path, on_progress):
        self.ran.append(plan)
        if plan["prompt"] == "boom":
            raise RuntimeError("CUDA out of memory")
        for i in range(3):
            on_progress(i / 3)
            time.sleep(0.05)
        out_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 4000)


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = FakeRunEngine()
        self.srv = dserver.Server(self.engine, Path(self.tmp.name, "out"), "fl2va")
        threading.Thread(target=self.srv.worker, daemon=True).start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), dserver.make_handler(self.srv))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.client = H3Client(f"http://127.0.0.1:{self.httpd.server_address[1]}")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_generate_roundtrip(self):
        self.assertTrue(self.client.healthy())
        img = Path(self.tmp.name, "first.png")
        img.write_bytes(b"x")
        out = self.client.generate(VideoRequest(prompt="여우", task="fl2va", duration_seconds=6,
                                                conditions=[Condition("image", img.as_uri(), "keyframe", 0)]),
                                   Path(self.tmp.name, "res.mp4"), poll=0.05)
        self.assertGreater(out.stat().st_size, 1000)
        plan = self.engine.ran[-1]
        self.assertEqual((plan["task"], plan["num_frames"], plan["short_edge"]), ("fl2va", 158, 768))   # 6초 → 158
        vid = Path(str(out) + ".json").read_text()
        self.assertIn("video_", vid)

    def test_failure_and_restart(self):
        vid = self.client.submit(VideoRequest(prompt="boom", task="t2va"))
        with self.assertRaises(H3Error) as cm:
            self.client.wait(vid, poll=0.05, timeout=10)
        self.assertIn("CUDA out of memory", str(cm.exception))
        ok = self.client.submit(VideoRequest(prompt="ok", task="t2va"))   # 실패 뒤에도 계속 받는다
        self.client.wait(ok, poll=0.05, timeout=10)
        # 서버를 새로 띄워도(메모리의 작업 목록이 비어도) 끝난 결과는 받을 수 있다
        fresh = dserver.Server(self.engine, self.srv.out_dir, "fl2va")
        self.assertEqual(fresh.get(ok)["status"], "completed")
        self.assertEqual(fresh.get(vid)["status"], "failed")
        self.assertIsNone(fresh.get("video_nope"))
        self.assertIsNone(fresh.get("../etc"))

    def test_bad_request_is_400(self):
        with self.assertRaises(H3Error) as cm:
            self.client._request("POST", "/v1/videos", {"task": "ref2va", "prompt": "x", "conditions": []})
        self.assertIn("400", str(cm.exception))
        with self.assertRaises(H3Error):
            self.client.content("video_nope")


if __name__ == "__main__":
    unittest.main()
