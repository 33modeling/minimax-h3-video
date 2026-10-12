"""2026-10-12 점검에서 찾은 것들: h3video 웹 서버에 생성 크기(gen_size) 보내기(웹·CLI 같게), Claude API 오류를 쉬운 말로(웹·CLI 같게),
명령 오타·옵션 오류를 한국어로, 동화책 만들기 '파일 받기' zip 을 shorts run 에 그대로."""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from shorts import backends as B  # noqa: E402
from shorts import claude as C  # noqa: E402
from test_cli import events, run_cli  # noqa: E402


def png(path: Path, w=16, h=12) -> Path:
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def node(script: str) -> str:
    return subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout


class GenSizeTest(unittest.TestCase):
    def test_h3video_gets_size_like_web(self):
        """'생성 크기'를 골라도 h3video 웹 서버에는 보내지 않아 늘 768p 로 만들던 것 — 서버가 받는 값(512~768)으로 맞춰 보낸다."""
        cases = [None, 480, 512, 576, 600, 720, 768, "432x768", "576x1024"]
        bk = B.H3VideoBackend("http://x")
        py = []
        for g in cases:
            req = {"prompt": "p", "task": "t2va", "duration": 4, "ratio": "9:16", "seed": 0, "refs": [], "image": None}
            if g is not None:
                req["gen_size"] = g
            py.append(dict(bk.build_form(req, read=False)[0]).get("size"))
        self.assertEqual(py, [None, "512", "512", "576", "576", "704", "768", "512", "576"])
        js = json.loads(node("import { h3videoForm } from './src/ai/generate.js';"
                             f"const out = {json.dumps(cases)}.map((g) => {{ const spec = g == null ? {{}} : {{ gen_size: g }};"
                             "const sc = { prompt: 'p', task: 't2va', sources: [], image: null, duration: 4, seed: 0 };"
                             "return h3videoForm(sc, spec, () => null).get('size'); });"
                             "console.log(JSON.stringify(out));"))
        self.assertEqual(js, py)


class ClaudeErrorTest(unittest.TestCase):
    def test_http_errors_in_plain_words_same_as_web(self):
        body = json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        cases = [[401, ""], [403, '{"type":"error","error":{"type":"permission_error","message":"no access"}}'], [429, ""],
                 [413, "too big"], [529, body], [503, ""], [500, '{"type":"error","error":{"type":"api_error","message":"boom"}}'],
                 [400, '{"type":"error","error":{"type":"invalid_request_error","message":"bad field"}}'], [418, "teapot"]]
        py = [C.http_error_text(s, b) for s, b in cases]
        self.assertIn("붐빕니다(529)", py[4]); self.assertNotIn("{", py[4])
        self.assertIn("bad field", py[7]); self.assertNotIn('"type"', py[7])
        self.assertIn("boom", py[6]); self.assertIn("(403)", py[1])
        js = json.loads(node("import { httpErrorText } from './src/core/claude.js';"
                             f"console.log(JSON.stringify({json.dumps(cases)}.map(([s, b]) => httpErrorText(s, b))));"))
        self.assertEqual(js, py)


class KoreanArgsTest(unittest.TestCase):
    def test_typos_and_bad_options_in_korean(self):
        code, out = run_cli("rnu", "x.json")
        self.assertEqual(code, 2); self.assertIn("혹시: shorts run", out); self.assertNotIn("invalid choice", out)
        code, out = run_cli("run", "--template", "zoom", "x.json")
        self.assertEqual(code, 2); self.assertIn("고를 수 있는 것: cutaway", out); self.assertNotIn("choose from", out)
        code, out = run_cli("compose", "job.json")
        self.assertEqual(code, 2); self.assertIn("shorts run job.json", out)
        code, out = run_cli("run", "--fps", "abc", "x.json")
        self.assertEqual(code, 2); self.assertIn("정수여야", out)
        code, out = run_cli("--help")
        self.assertEqual(code, 0); self.assertIn("사용법: shorts", out); self.assertNotIn("show this help", out)


class StoryZipTest(unittest.TestCase):
    def test_run_takes_storybook_maker_zip(self):
        tmp = Path(tempfile.mkdtemp(prefix="shorts-zip-"))
        book = {"kind": "batch", "title": "달빛 토끼", "style": "watercolor", "width": 1152, "height": 864, "items": [
            {"id": "sheet-1", "kind": "sheet", "image": "images/sheet-1.png", "prompt": "sheet"},
            {"id": "page-01", "kind": "page", "label": "1쪽", "page": 1, "text": "토끼가 뛰었어요.", "image": "images/page-01.png", "scene": "A rabbit jumps"},
            {"id": "page-02", "kind": "page", "label": "2쪽", "page": 2, "text": "잘 자요.", "image": "images/page-02.png", "scene": "The rabbit sleeps"}]}
        z = tmp / "달빛_토끼.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:   # 동화책 만들기처럼 압축 없이, images/ 폴더째
            zf.writestr("book.json", json.dumps(book, ensure_ascii=False))
            for n in ("sheet-1", "page-01", "page-02"):
                zf.writestr(f"images/{n}.png", png(tmp / f"{n}.png").read_bytes())
            zf.writestr("index.html", "<html></html>")
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp / "cache")}):
            code, out = run_cli("run", z, "--dry-run", "--json", "--server", "http://127.0.0.1:9", "--backend", "h3video", "--gen-size", "576")
        self.assertEqual(code, 0, out)
        ev = events(out)
        story = next(e for e in ev if e["event"] == "story")
        self.assertEqual((story["title"], len(story["clips"])), ("달빛 토끼", 2))
        self.assertTrue(any(e["event"] == "zip" for e in ev))
        self.assertTrue(any(e["event"] == "warning" and "sheet-1.png" in e["message"] for e in ev))   # 시트는 쓰지 않음
        reqs = [e for e in ev if e["event"] == "request"]
        self.assertEqual([r["body"]["multipart"]["size"] for r in reqs], ["576", "576"])
        self.assertEqual([r["body"]["files"] for r in reqs], [["first_image=page-01.png"], ["first_image=page-02.png"]])
        dry = [e for e in ev if e["event"] == "dry_run"][-1]
        self.assertIn(str(tmp / "달빛-토끼.mp4.parts"), dry["message"])   # 결과는 zip 옆에 (풀어 둔 캐시 폴더가 아니라)
        empty = tmp / "empty.zip"
        with zipfile.ZipFile(empty, "w") as zf:
            zf.writestr("a.txt", "x")
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp / "cache")}):
            code, out = run_cli("run", empty, "--dry-run")
        self.assertEqual(code, 2); self.assertIn("zip 안에 JSON 이 없습니다", out)


if __name__ == "__main__":
    unittest.main()
