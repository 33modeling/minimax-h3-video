"""주요 인물 설정: JSON 안의 인물(동화책 콘티 opts.cast·영상 콘티 brief.cast·동화책 만들기 book.json cast), 화면에서 보낸 cast,
이름이 나오는 장면 프롬프트에 외모·성격·말투·목소리, 내레이션 앞에 붙이기, 같은 문구 두 번 붙이지 않기, 웹 장면 표·만들기, CLI --cast."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_story import CONTI  # noqa: E402
from test_web_ui import BND, form  # noqa: E402
from test_web_browser import playwright_env  # noqa: E402
from h3video import cli  # noqa: E402
from h3video import story as S  # noqa: E402
from h3video.web import App, make_handler  # noqa: E402

TOTO = {"name": "Toto", "role": "주인공", "kind": "아기 고슴도치", "look": "밤색 가시", "personality": "겁이 많다", "speech": '"괜찮아."',
        "want": "친구를 사귀고 싶다", "lookEn": "a tiny hedgehog in a green raincoat"}
MINJUN = {"name": "민준", "role": "주인공", "age": "40대 남성", "look": "짧은 검은 머리", "outfit": "베이지 앞치마", "personality": "말수가 적다",
          "speech": "짧게 말한다", "voice": "낮고 따뜻한 목소리", "lookEn": "a man in his 40s with a beige apron"}
BOARD = {"brief": {"ratio": "16:9", "cast": [MINJUN]}, "board": {"title": "골목 카페", "scenes": [
    {"title": "아침", "visual": "민준이 원두를 볶는다", "duration": 6, "caption": "", "videoPrompt": f"A man roasts coffee beans. Character (민준): {MINJUN['lookEn']}."},
    {"title": "빈 가게", "visual": "빈 카페", "duration": 5, "caption": "", "videoPrompt": "An empty cafe at dawn."}]}}


def conti_with(cast):
    d = copy.deepcopy(CONTI)
    d["opts"]["cast"] = cast
    return d


class CastStoryTest(unittest.TestCase):
    def test_normalize_and_find(self):
        [t] = S.normalize_cast([TOTO, {"name": ""}, "x"])
        self.assertEqual((t["age"], t["personality"]), ("아기 고슴도치", "겁이 많다 · 바라는 것: 친구를 사귀고 싶다"))
        self.assertEqual([c["name"] for c in S.cast_from(BOARD)], ["민준"])
        self.assertEqual([c["name"] for c in S.cast_from({"cast": [TOTO]})], ["Toto"])
        self.assertEqual(S.cast_from({"opts": {}}), [])

    def test_conti_cast_goes_into_named_scenes_before_narration(self):
        st = S.load_story(json.dumps(conti_with([TOTO])))
        self.assertEqual([c["name"] for c in st.cast], ["Toto"])
        p1, p3 = st.clips[0].prompt, st.clips[2].prompt
        # 그림 없는 장면: 등장인물 묘사도 정한 영어 문구, 이어서 성격·말투, 내레이션은 맨 끝
        self.assertIn("Characters — Toto: a tiny hedgehog in a green raincoat.", p1)
        self.assertIn("Personality of Toto: 겁이 많다 · 바라는 것: 친구를 사귀고 싶다.", p1)
        self.assertIn('Speech style of Toto: "괜찮아."', p1)
        self.assertLess(p1.index("Personality of Toto"), p1.index("Voice-over"))
        self.assertEqual(p1.count("a tiny hedgehog in a green raincoat"), 1)
        self.assertNotIn("Toto", p3)                      # 3쪽은 Bori 만 나온다
        # 인물 없이 읽으면 예전과 같다
        plain = S.load_story(json.dumps(CONTI))
        self.assertIn("Toto: a baby hedgehog with a red scarf", plain.clips[0].prompt)
        self.assertNotIn("Personality", plain.clips[0].prompt)

    def test_explicit_cast_overrides_json(self):
        st = S.load_story(json.dumps(conti_with([TOTO])), cast=[])
        self.assertEqual(st.cast, [])
        self.assertNotIn("green raincoat", st.clips[0].prompt)
        st = S.load_story(json.dumps(CONTI), cast=[{"name": "Bori", "voice": "작고 높은 목소리"}])
        self.assertIn("Voice of Bori: 작고 높은 목소리.", st.clips[2].prompt)
        self.assertNotIn("Voice of Bori", st.clips[0].prompt)

    def test_video_conti_brief_cast_adds_voice_once(self):
        st = S.load_story(json.dumps(BOARD))
        a, b = st.clips[0].prompt, st.clips[1].prompt
        self.assertEqual(a.count(MINJUN["lookEn"]), 1)    # 콘티가 이미 붙인 외모는 그대로
        self.assertIn("Voice of 민준: 낮고 따뜻한 목소리.", a)
        self.assertEqual(b, "An empty cafe at dawn.")
        # 이름이 영어 프롬프트에 없어도 장면 설명(visual)에 있으면 붙인다
        board = copy.deepcopy(BOARD)
        board["board"]["scenes"][0]["videoPrompt"] = "A man roasts coffee beans."
        self.assertIn(f"Character (민준): {MINJUN['lookEn']}.", S.load_story(json.dumps(board)).clips[0].prompt)

    def test_maker_book_cast(self):
        tmp = Path(tempfile.mkdtemp())
        book = {"kind": "batch", "title": "토토", "cast": [TOTO], "items": [
            {"id": "page-01", "kind": "page", "label": "1쪽", "page": 1, "scene": "Toto walks", "text": "토토가 걸어요."}]}
        st = S.load_story(json.dumps(book), base=tmp)
        self.assertIn("Character (Toto): a tiny hedgehog in a green raincoat.", st.clips[0].prompt)

    def test_cli_cast_file(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "toto.json").write_text(json.dumps(CONTI), encoding="utf-8")
        (tmp / "cast.json").write_text(json.dumps([{"name": "Bori", "voice": "작고 높은 목소리"}]), encoding="utf-8")
        a = cli.build_parser().parse_args(["json", str(tmp / "toto.json"), "--cast", str(tmp / "cast.json"), "--list"])
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        out = StringIO()
        with redirect_stdout(out), redirect_stderr(StringIO()):
            cli.cmd_json(a)
        self.assertIn("Voice of Bori: 작고 높은 목소리.", out.getvalue())


class CastWebTest(unittest.TestCase):
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

    def post(self, path, parts):
        req = urllib.request.Request(self.base + path, data=form(parts), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={BND}"})
        try:
            r = urllib.request.urlopen(req)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_plan_and_create_use_screen_cast(self):
        js = ("json", "toto.json", json.dumps(conti_with([TOTO])).encode())
        code, plan = self.post("/api/story/plan", [js])
        self.assertEqual(code, 200)
        self.assertEqual([c["name"] for c in plan["cast"]], ["Toto"])      # 보내지 않으면 JSON 안의 인물
        self.assertIn("green raincoat", plan["clips"][0]["prompt"])
        edited = dict(TOTO, lookEn="a hedgehog with a blue hat")
        code, plan = self.post("/api/story/plan", [js, ("cast", None, json.dumps([edited]))])
        self.assertIn("a hedgehog with a blue hat", plan["clips"][0]["prompt"])
        self.assertNotIn("green raincoat", plan["clips"][0]["prompt"])
        code, made = self.post("/api/story", [js, ("cast", None, json.dumps([edited]))])
        self.assertEqual(code, 201)
        self.assertEqual(made["cast"][0]["lookEn"], "a hedgehog with a blue hat")
        self.assertTrue(all("blue hat" in c["prompt"] for c in made["clips"] if "Toto" in c["prompt"]))
        self.assertEqual(self.post("/api/story/plan", [js, ("cast", None, "{oops")])[0], 400)
        self.assertEqual(self.post("/api/story/plan", [js, ("cast", None, '{"name": "x"}')])[0], 400)



@unittest.skipUnless(playwright_env(), "node 와 Playwright 가 없어 브라우저 확인을 건너뜀 (H3_PLAYWRIGHT 로 지정)")
class CastBrowserTest(unittest.TestCase):
    def test_cast_ui_in_a_real_browser(self):
        tmp = Path(tempfile.mkdtemp())
        media = tmp / "media"; media.mkdir()
        (media / "toto.json").write_text(json.dumps(conti_with([TOTO]), ensure_ascii=False), encoding="utf-8")
        fl, _, fl_url = mock_server.start(steps=3)
        ref, _, ref_url = mock_server.start(steps=3)
        app = App(fl_url, ref_url, tmp / "web", str(tmp / "inbox"), poll=0.05)
        web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            r = subprocess.run(["node", str(ROOT / "tests/e2e/cast_ui.cjs"), f"http://127.0.0.1:{web.server_address[1]}", str(media)],
                               capture_output=True, text=True, timeout=300, env={**os.environ, **playwright_env()})
        finally:
            for s in (web, fl, ref):
                s.shutdown(); s.server_close()
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertIn("인물 설정 확인 끝", r.stdout)


if __name__ == "__main__":
    unittest.main()
