"""JSON 한번에: 길이 자동(글 읽는 시간), 콘티·동화책 만들기 book.json·장면 목록 읽기, 그림 맞추기, CLI json·--resume, 웹 API."""
import json
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_cli import run  # noqa: E402
from h3video import story as S  # noqa: E402
from h3video.client import H3Error  # noqa: E402

CONTI = {
    "guide": "고슴도치 이야기", "opts": {"ratio": "4:3", "target": "qwen"},
    "book": {
        "title": "토토의 우산", "style": {"prompt": "soft watercolor", "palette": "moss green"},
        "characters": [{"name": "Toto", "prompt": "a baby hedgehog with a red scarf"}, {"name": "Bori", "prompt": "a baby squirrel"}],
        "places": [], "cover": {"scene": "Toto holds a taro leaf", "characters": ["Toto"]},
        "pages": [
            {"page": 1, "text": "숲 가장자리에 아기 고슴도치 토토가 살았어요.\n토토는 늘 혼자 놀았어요.", "shot": "wide", "characters": ["Toto"], "scene": "Toto sits alone"},
            {"page": 2, "text": "\"같이 쓰자!\"", "shot": "close-up", "characters": ["Toto", "Bori"], "scene": "Toto smiles at Bori"},
            {"page": 3, "text": "", "shot": "bird-eye", "characters": ["Bori"], "scene": "A rainbow over the forest"},
        ],
    },
}


def png(path: Path, w=8, h=6) -> Path:
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


class StoryReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_seconds_follow_the_text(self):
        self.assertEqual(S.auto_seconds("숲 가장자리에 아기 고슴도치 토토가 살았어요.\n토토는 늘 혼자 놀았어요."), (10, "글 31자"))
        self.assertEqual(S.auto_seconds("안녕"), (5, "글 2자"))                       # 최소 5초
        self.assertEqual(S.auto_seconds("가" * 200)[0], 52)                           # 읽는 시간이 잘리지 않는다
        self.assertEqual(S.auto_seconds("The little fox ran to the river and looked back"), (6, "글 10단어"))
        self.assertEqual(S.auto_seconds(""), (6, "기본"))
        self.assertEqual(S.auto_seconds("긴 글이어도", 12), (12, "JSON"))
        self.assertEqual(S.auto_seconds("", 30)[0], 30)
        with self.assertRaises(H3Error):
            S.auto_seconds("", "열초")

    def test_conti_json_with_images_by_name_and_order(self):
        imgs = [png(self.tmp / n) for n in ("cover.png", "page-02.png", "a-first.png", "zz-extra.png")]
        st = S.load_story(json.dumps(CONTI), [str(p) for p in imgs])
        self.assertEqual((st.source, st.title, st.ratio), ("conti", "토토의 우산", "4:3"))
        self.assertEqual([c.id for c in st.clips], ["cover", "page-01", "page-02", "page-03"])
        self.assertEqual([Path(c.image).name if c.image else None for c in st.clips], ["cover.png", "a-first.png", "page-02.png", "zz-extra.png"])
        self.assertEqual([c.seconds for c in st.clips], [6, 10, 5, 6])
        p1, p2 = st.clips[1].prompt, st.clips[2].prompt
        self.assertTrue(p1.startswith("Wide shot: Toto sits alone. Bring this picture-book illustration to life"))
        self.assertIn("reads slowly and clearly <d>[Korean] 숲 가장자리에 아기 고슴도치 토토가 살았어요. 토토는 늘 혼자 놀았어요.</d>", p1)
        self.assertIn('<d>[Korean] "같이 쓰자!"</d>', p2)
        self.assertNotIn("Voice-over", st.clips[3].prompt)       # 글 없는 쪽
        self.assertEqual([c.seed for c in st.clips], [0, 1, 2, 3])
        # 그림이 없으면 표지는 빠지고, 쪽은 글로 그림체·인물을 알려 준다(t2va). 내레이션 끄기
        st = S.load_story(CONTI, [], narration=False, seed=7)
        self.assertEqual([c.id for c in st.clips], ["page-01", "page-02", "page-03"])
        self.assertEqual(st.clips[0].seed, 7)
        self.assertIn("Characters — Toto: a baby hedgehog with a red scarf; Bori: a baby squirrel", st.clips[1].prompt)
        self.assertIn("Style: children's picture book illustration, soft watercolor", st.clips[1].prompt)
        self.assertNotIn("Voice-over", st.clips[0].prompt)
        self.assertEqual(st.clips[0].seconds, 10)               # 내레이션을 꺼도 길이는 글 읽는 시간
        self.assertEqual(S.load_story(CONTI["book"]).ratio, "16:9")   # book 만 있으면 판형 정보가 없다

    def test_storybook_maker_book_json(self):
        d = self.tmp / "book"; (d / "images").mkdir(parents=True)
        for n in ("sheet-1", "cover", "page-01", "page-02"):
            png(d / "images" / f"{n}.png")
        book = {"kind": "batch", "title": "만든 책", "style": "watercolor", "width": 1152, "height": 864, "items": [
            {"id": "sheet-1", "kind": "sheet", "image": "images/sheet-1.png", "prompt": "sheet"},
            {"id": "cover", "kind": "cover", "label": "표지", "image": "images/cover.png", "scene": "Book cover: A", "prompt": "long"},
            {"id": "page-01", "kind": "page", "label": "1쪽", "page": 1, "text": "하나", "image": "images/page-01.png", "scene": "Wide shot: B", "prompt": "long"},
            {"id": "page-02", "kind": "page", "label": "2쪽", "page": 2, "text": "둘", "image": "images/page-02.png", "prompt": "Scene C. Style: x"}]}
        (d / "book.json").write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
        st = S.load_story_file(str(d / "book.json"))
        self.assertEqual((st.source, st.ratio), ("book", "4:3"))
        self.assertEqual([c.id for c in st.clips], ["cover", "page-01", "page-02"])      # 캐릭터 시트는 영상이 아니다
        self.assertTrue(all(c.image and Path(c.image).is_file() for c in st.clips))
        self.assertTrue(st.clips[1].prompt.startswith("Wide shot: B. Bring this"))
        self.assertTrue(st.clips[2].prompt.startswith("Scene C. Style: x."))           # scene 이 없으면 그림 프롬프트

    def test_clip_lists_and_errors(self):
        st = S.load_story(["비 오는 서울 밤거리", "새벽 바다"])
        self.assertEqual((st.source, st.ratio, [c.seconds for c in st.clips]), ("list", "16:9", [6, 6]))
        self.assertEqual(st.clips[0].prompt, "비 오는 서울 밤거리")
        img = png(self.tmp / "k.png")
        (self.tmp / "s.json").write_text(json.dumps({"title": "묶음", "ratio": "9:16", "clips": [
            {"prompt": "고양이가 하품한다", "image": "k.png", "seconds": 8, "text": "하암"},
            {"prompt": "강아지", "duration": 4, "seed": 42}]}, ensure_ascii=False), encoding="utf-8")
        st = S.load_story_file(str(self.tmp / "s.json"))
        self.assertEqual((st.ratio, st.clips[0].image, st.clips[0].seconds, st.clips[1].seconds, st.clips[1].seed), ("9:16", str(img), 8, 4, 42))
        self.assertIn("Voice-over", st.clips[0].prompt)
        for bad, msg in [("{oops", "JSON 을 읽을 수 없다"), ({"clips": [{"text": "x"}]}, "prompt 가 없다"), ({"foo": 1}, "장면을 찾지 못했다"),
                         ({"clips": [{"prompt": "a", "image": "nope.png"}]}, "nope.png"), ([{"prompt": "a", "image": "x.svg"}], "x.svg")]:
            with self.assertRaises(H3Error) as e:
                S.load_story(bad, ["x.svg"] if "svg" in json.dumps(bad) else [], base=self.tmp)
            self.assertIn(msg, str(e.exception))
        self.assertEqual(len(S.load_story(["a"] * 100).clips), 100)
        # 웹 요청은 JSON 에 적힌 경로로 이 컴퓨터의 파일을 읽지 않는다
        with self.assertRaises(H3Error):
            S.load_story({"clips": [{"prompt": "a", "image": str(img)}]}, [], local_paths=False)
        self.assertEqual(Path(S.load_story({"clips": [{"prompt": "a", "image": str(img)}]}, ["/up/k.png"], local_paths=False).clips[0].image).name, "k.png")
        # 폴더를 주면 안의 그림을 이름순(숫자는 숫자순)으로
        f = self.tmp / "imgs"; f.mkdir()
        for n in ("p10.png", "p2.png", "notes.txt"):
            (f / n).write_bytes(b"x")
        self.assertEqual([Path(x).name for x in S.expand_images([str(f)])], ["p2.png", "p10.png"])


class StoryRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.g = ["--endpoint", self.url, "--ref-endpoint", self.url, "--output-dir", str(self.tmp / "outputs"), "--poll", "0.01"]
        (self.tmp / "imgs").mkdir()
        for n in ("cover.png", "page-01.png", "page-02.png", "page-03.png"):
            png(self.tmp / "imgs" / n)
        (self.tmp / "toto.json").write_text(json.dumps(CONTI, ensure_ascii=False), encoding="utf-8")

    def test_cli_json_makes_every_clip_and_joins_them(self):
        code, out, err = run("json", str(self.tmp / "toto.json"), "--list", *self.g)
        self.assertEqual(code, 0, err)
        self.assertIn("토토의 우산 · 장면 3개 · 합계 21초 · 화면비 4:3", err)   # 그림 없이: 표지 빠짐
        self.assertIn("[page-02] 2쪽 · 5초 · 그림 없음", out)
        n0 = len(self.state.requests)
        code, out, err = run("json", str(self.tmp / "toto.json"), str(self.tmp / "imgs"), "-o", str(self.tmp / "final.mp4"), *self.g)
        self.assertEqual(code, 0, err)
        reqs = self.state.requests[n0:]
        self.assertEqual(sorted(r["target"]["duration_seconds"] for r in reqs), [5, 6, 6, 10])
        self.assertTrue(all(r["task"] == "fl2va" and r["target"]["aspect_ratio"] == "4:3" for r in reqs))
        self.assertEqual(out.strip(), str(self.tmp / "final.mp4"))
        self.assertGreater((self.tmp / "final.mp4").stat().st_size, 1000)
        d = next((self.tmp / "outputs").glob("story-*"))
        st = json.loads((d / "story.json").read_text(encoding="utf-8"))
        self.assertTrue(st["output"] and Path(st["output"]).is_file())
        self.assertTrue(all(c["output"] and c["job_id"] for c in st["clips"]))
        self.assertIn("이어 붙였다", err)

    def test_failed_clip_is_redone_with_resume(self):
        self.state.fail_once.append("Toto smiles at Bori")
        code, out, err = run("json", str(self.tmp / "toto.json"), str(self.tmp / "imgs"), *self.g)
        self.assertEqual(code, 1)
        self.assertIn("실패 2쪽", err)
        self.assertIn("h3video json --resume story-", err)
        d = next((self.tmp / "outputs").glob("story-*"))
        self.assertIsNone(json.loads((d / "story.json").read_text(encoding="utf-8"))["output"])
        n0 = len(self.state.requests)
        code, out, err = run("json", "--resume", "last", *self.g)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.state.requests) - n0, 1)                    # 실패한 장면만
        self.assertIn("Toto smiles at Bori", self.state.requests[-1]["prompt"])
        self.assertTrue(Path(out.strip()).is_file())
        self.assertEqual(run("json", "--resume", "last", "--only", "nope", *self.g)[0], 1)
        code, _, err = run("json", *self.g)
        self.assertEqual(code, 1); self.assertIn("JSON 파일이 필요하다", err)

    def test_web_story_api(self):
        from http.server import ThreadingHTTPServer
        from h3video.web import App, make_handler
        app = App(self.url, self.url, self.tmp / "web", str(self.tmp / "inbox"), poll=0.01)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(path, parts):
            b = "Bnd77"
            body = b""
            for name, fname, data in parts:
                disp = f'form-data; name="{name}"' + (f'; filename="{fname}"' if fname else "")
                body += f"--{b}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + (data if isinstance(data, bytes) else data.encode()) + b"\r\n"
            body += f"--{b}--\r\n".encode()
            req = urllib.request.Request(base + path, data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={b}"})
            try:
                r = urllib.request.urlopen(req)
                return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        js = ("json", "toto.json", json.dumps(CONTI, ensure_ascii=False).encode())
        try:
            self.assertIn("JSON 한번에", urllib.request.urlopen(base + "/").read().decode())
            code, plan = post("/api/story/plan", [js, ("image_names", None, "page-01.png"), ("image_names", None, "cover.png"), ("narration", None, "0")])
            self.assertEqual(code, 200, plan)
            self.assertEqual([(c["id"], c["image"], c["seconds"]) for c in plan["clips"]],
                             [("cover", "cover.png", 6), ("page-01", "page-01.png", 10), ("page-02", None, 5), ("page-03", None, 6)])
            self.assertNotIn("Voice-over", plan["clips"][1]["prompt"])
            self.assertEqual(post("/api/story", [("json", None, "")])[0], 400)
            self.assertEqual(post("/api/story", [js, ("ratio", None, "5:4")])[0], 400)
            imgs = [("images", n, (self.tmp / "imgs" / n).read_bytes()) for n in ("page-02.png", "page-01.png")]
            code, made = post("/api/story", [js, *imgs, ("size", None, "576")])
            self.assertEqual(code, 201, made)
            self.assertEqual((made["total"], made["seconds"]), (3, 21))
            for _ in range(300):
                time.sleep(0.05)
                st = json.loads(urllib.request.urlopen(f"{base}/api/story/{made['id']}").read())
                if st["output"] or st["failed"]:
                    break
            self.assertTrue(st["output"], st)
            self.assertEqual([Path(c["image"]).name if c["image"] else None for c in st["clips"]], ["page-01.png", "page-02.png", None])
            data = urllib.request.urlopen(f"{base}/files/{made['id']}/{urllib.request.quote(Path(st['output']).name)}").read()
            self.assertGreater(len(data), 1000)
            self.assertEqual(json.loads(urllib.request.urlopen(base + "/api/stories").read())[0]["id"], made["id"])
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{base}/api/story/..%2Fx")
            # JSON 에 적힌 이 컴퓨터의 경로는 읽지 않는다 (올린 그림만)
            secret = png(self.tmp / "secret.png")
            code, res = post("/api/story", [("json", "s.json", json.dumps({"clips": [{"prompt": "a", "image": str(secret)}]}))])
            self.assertEqual(code, 400); self.assertIn("secret.png", res["error"])
        finally:
            httpd.shutdown(); httpd.server_close()


if __name__ == "__main__":
    unittest.main()
