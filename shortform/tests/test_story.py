"""JSON 한번에(숏폼): 이야기 JSON → 숏폼 명세. 웹 src/core/story.js 와 같은 기대 결과(tests/fixtures/story)를 확인하고, CLI 로 끝까지 만든다."""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "src"))

from shorts import spec as S  # noqa: E402
from shorts.story import caption_pieces, is_story, story_to_spec  # noqa: E402

FIX = HERE / "fixtures" / "story"


def png(path: Path, w=16, h=12) -> Path:
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


class StoryToSpecTest(unittest.TestCase):
    def test_fixtures_match_expected_and_pass_the_spec_check(self):
        cases = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))
        expected = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases["cases"]), len(expected))
        for c, want in zip(cases["cases"], expected):
            spec, info = story_to_spec(c["data"], c["images"], narration=c["narration"], local_paths=False)
            self.assertEqual({"spec": spec, "info": info}, want, c["name"])
            errors, _ = S.check_spec(spec)
            self.assertEqual(errors, [], c["name"])
            self.assertEqual(len(S.ai_scenes(spec)), len(spec["scenes"]))
        for e in cases["errors"]:
            with self.assertRaises(Exception) as ctx:
                story_to_spec(e["data"], e["images"], local_paths=False)
            self.assertIn(e["contains"], str(ctx.exception))

    def test_story_detection_leaves_shortform_specs_alone(self):
        self.assertTrue(is_story(["a"]))
        self.assertFalse(is_story([1, 2])); self.assertFalse(is_story([]))
        self.assertTrue(is_story({"clips": []}))
        self.assertTrue(is_story({"kind": "batch", "items": []}))
        self.assertTrue(is_story(json.loads((FIX / "cases.json").read_text(encoding="utf-8"))["cases"][0]["data"]))
        for name in ("scenes.json", "prompt-only.json", "compose-only.json"):
            self.assertFalse(is_story(json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))), name)

    def test_caption_pieces(self):
        self.assertEqual(caption_pieces("첫 줄\n\n 둘째   줄 "), ["첫 줄", "둘째 줄"])
        long = "가" * 130
        self.assertEqual([len(x) for x in caption_pieces(long)], [120, 10])
        self.assertTrue(all(len(x) <= 120 for x in caption_pieces("이것은 문장입니다. " * 20)))


class StoryRunTest(unittest.TestCase):
    def test_cli_runs_a_conti_json_with_a_picture_folder_end_to_end(self):
        from shorts.cli import main
        sys.path.insert(0, str(ROOT.parent / "tests"))
        import mock_server  # H3 서버 흉내 (레포 루트 tests/)
        httpd, state, url = mock_server.start(steps=2)
        try:
            tmp = Path(tempfile.mkdtemp())
            data = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))["cases"][0]["data"]
            (tmp / "toto.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            (tmp / "pages").mkdir()
            for n in ("cover.png", "page-01.png", "page-02.png", "page-03.png", "page-04.png", "extra-99.png"):
                png(tmp / "pages" / n)
            out = tmp / "short.mp4"
            r = subprocess.run([sys.executable, "-m", "shorts", "run", str(tmp / "toto.json"), str(tmp / "pages"), "--server", url,
                                "--backend", "sglang", "--poll", "0.2", "--inline", "-o", str(out), "--json"],
                               cwd=ROOT, capture_output=True, text=True, timeout=300,
                               env={**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT.parent / 'src'}", "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
            events = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
            story = next(e for e in events if e.get("event") == "story")
            self.assertEqual([c["seconds"] for c in story["clips"]], [6, 10, 5, 33, 8])
            self.assertTrue(any(e.get("event") == "warning" and "extra-99.png" in e.get("message", "") for e in events))
            reqs = state.requests
            self.assertEqual([q["target"]["duration_seconds"] for q in reqs], [6, 10, 5, 9, 8, 8, 8, 8])
            self.assertTrue(all(q["task"] == "fl2va" and q["target"]["aspect_ratio"] == "4:3" for q in reqs))
            self.assertIn("<d>[Korean] 숲 가장자리에", reqs[1]["prompt"])
            self.assertTrue(out.is_file() and out.stat().st_size > 1000)
        finally:
            httpd.shutdown(); httpd.server_close()


if __name__ == "__main__":
    unittest.main()
