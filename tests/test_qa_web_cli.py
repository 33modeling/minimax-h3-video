"""2026-10-12 점검에서 찾은 것들: 웹 받기(?download=1)·숫자 칸 쉬운 오류·JSON 한번에 화면비 기억, CLI 없는 파일 이름 안내·
서버 HTTP 오류를 쉬운 말로·batch 오류·show 장면 상태·config 줄 맞춤·Ctrl+C 기록 안내·JSON 형식 오류 위치."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_cli import dead_url, run  # noqa: E402
from test_cli_ux import CleanEnv  # noqa: E402
from test_story import CONTI, png  # noqa: E402
from test_web_ui import BND, form  # noqa: E402
from h3video import cli, story  # noqa: E402
from h3video.client import H3Error  # noqa: E402
from h3video.jobs import Job, JobStore, Scene  # noqa: E402
from h3video.web import App, make_handler  # noqa: E402


class WebFixesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = App(self.url, self.url, self.tmp / "web", None, poll=0.01)
        self.web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.web.server_address[1]}"
        self.addCleanup(lambda: (self.web.shutdown(), self.web.server_close()))

    def post(self, path, parts=None, body=None):
        if parts is not None:
            req = urllib.request.Request(self.base + path, data=form(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={BND}"})
        else:
            req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_download_link_sends_attachment_with_korean_name(self):
        d = self.app.store.root / "j1"; d.mkdir(parents=True)
        (d / "비 오는 밤.mp4").write_bytes(b"\0" * 2048)
        url = self.base + "/files/" + urllib.parse.quote("j1/비 오는 밤.mp4")
        r = urllib.request.urlopen(url)
        self.assertIsNone(r.headers.get("Content-Disposition"))            # 재생(<video>)은 그대로
        r = urllib.request.urlopen(url + "?download=1")
        cd = r.headers.get("Content-Disposition")
        self.assertTrue(cd.startswith("attachment;"), cd)
        self.assertIn("filename*=UTF-8''" + urllib.parse.quote("비 오는 밤.mp4"), cd)
        self.assertEqual(len(r.read()), 2048)
        r = urllib.request.urlopen(urllib.request.Request(url + "?download=1", headers={"Range": "bytes=0-9"}))
        self.assertEqual((r.status, len(r.read())), (206, 10))

    def test_number_fields_give_plain_korean_errors(self):
        for fields, word in (([("seconds", None, "abc")], "길이"), ([("seconds", None, "2")], "4초 이상"),
                             ([("steps", None, "많이")], "스텝"), ([("steps", None, "999")], "스텝"),
                             ([("seed", None, "abc")], "시드"), ([("aspect_ratio", None, "5:4")], "화면비"),
                             ([("size", None, "big")], "크기")):
            code, r = self.post("/api/jobs", [("prompt", None, "고양이")] + fields)
            self.assertEqual(code, 400, (fields, r))
            self.assertIn(word, r["error"])
            self.assertNotIn("invalid literal", r["error"])
        code, r = self.post("/api/jobs", [("prompt", None, "고양이"), ("seconds", None, "8.0"), ("seed", None, "-3")])
        self.assertEqual((code, r.get("total_seconds"), r.get("seed")), (201, 8, -3), r)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/api/plan?seconds=abc")
        self.assertIn("숫자", json.loads(e.exception.read())["error"])

    def test_story_remembers_chosen_ratio_for_same_settings_again(self):
        imgs = [png(self.tmp / n) for n in ("page-01.png", "page-02.png")]
        code, made = self.post("/api/story", [("json", "toto.json", json.dumps(CONTI, ensure_ascii=False).encode()),
                                              *[("images", p.name, p.read_bytes()) for p in imgs], ("ratio", None, "9:16")])
        self.assertEqual(code, 201, made)
        self.assertEqual((made["ratio"], made["params"]["ratio"]), ("9:16", "9:16"))
        code, made = self.post("/api/story", [("json", "toto.json", json.dumps(CONTI, ensure_ascii=False).encode())])
        self.assertEqual((code, made["ratio"], made["params"]["ratio"]), (201, "4:3", None))   # JSON 대로
        code, r = self.post("/api/story/plan", [("json", "bad.json", b"{oops")])
        self.assertEqual(code, 400)
        self.assertIn("1줄 2번째 글자", r["error"])

    def test_ui_has_offline_defaults_and_download_param(self):
        html = (ROOT / "src/h3video/ui.html").read_text(encoding="utf-8")
        self.assertIn("fillSelects(['16:9'", html)                 # 서버 연결 전에도 화면비·크기 칸이 비지 않는다
        self.assertIn("'download=1'", html)                        # 허브에서 연 화면도 받기가 내려받기로
        self.assertIn("health[need] === false", html)              # 꺼진 서버로 보내지 않는다


class CliFixesTest(CleanEnv):
    def test_missing_media_file_names_are_not_prompts(self):
        png(self.tmp / "first.png")
        cwd = os.getcwd(); os.chdir(self.tmp); self.addCleanup(os.chdir, cwd)
        code, out, err = run("firts.png", "아이가 웃는다")
        self.assertEqual(code, 2)
        self.assertIn("그림 파일이 없다: firts.png", err); self.assertIn("혹시: first.png", err)
        self.assertNotIn("모르는 옵션", err)
        code, out, err = run("tot.json", "pages/")
        self.assertEqual(code, 2); self.assertIn("JSON 파일이 없다", err)
        code, out, err = run("song.mp3", "춤춘다")
        self.assertEqual(code, 2); self.assertIn("소리 파일이 없다", err)
        code, out, err = run("고양이.png 를 닮은 그림", "--dry-run")   # 띄어쓰기가 있으면 글
        self.assertEqual(code, 0, err)

    def test_batch_errors_in_korean(self):
        code, _, err = run("batch", str(self.tmp / "nope.txt"))
        self.assertEqual(code, 1); self.assertIn("프롬프트 파일이 없다", err); self.assertNotIn("Errno", err)
        f = self.tmp / "b.txt"; f.write_text("seconds: x\n고양이\n", encoding="utf-8")
        code, _, err = run("batch", str(f), "--dry-run")
        self.assertEqual(code, 1); self.assertIn("seconds 는 정수여야 한다: x", err); self.assertNotIn("invalid literal", err)

    def test_server_http_errors_in_plain_words(self):
        httpd, state, url = mock_server.start(steps=50)
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        code, _, err = run("fetch", "video_9999", "--endpoint", url, "-o", str(self.tmp / "a.mp4"))
        self.assertEqual(code, 1); self.assertIn("서버에 그런 영상이 없다", err); self.assertIn("원래 메시지", err)
        code, _, err = run("status", "video_9999", "--endpoint", url)
        self.assertEqual(code, 1); self.assertIn("서버에 그런 영상이 없다", err)
        req = urllib.request.Request(url + "/v1/videos", data=json.dumps({"prompt": "x"}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        vid = json.loads(urllib.request.urlopen(req).read())["id"]
        code, _, err = run("fetch", vid, "--endpoint", url, "-o", str(self.tmp / "b.mp4"))
        self.assertEqual(code, 1); self.assertIn("아직 다 만들지 않았다", err); self.assertIn(f"h3video status {vid}", err)
        code, _, err = run("ir", "x", "--endpoint", url)
        self.assertEqual(code, 1); self.assertIn("다듬은 프롬프트만 보기(ir)를 하지 못한다", err)

    def test_server_down_message_uses_the_real_port(self):
        msg = cli.server_down("fl2va", "http://127.0.0.1:39010")
        self.assertIn("ssh -N -L 39010:127.0.0.1:39010", msg); self.assertNotIn("30011", msg)
        msg = cli.server_down("ref2va", "http://gpu-node:30011")
        self.assertIn("up.sh --ref", msg); self.assertNotIn("ssh -N", msg); self.assertIn("config set ref-endpoint", msg)

    def test_show_scene_status_in_korean_and_config_lines_up(self):
        out_dir = self.tmp / "o"
        store = JobStore(out_dir)
        jb = Job(id="20261012-000000-abcdef", prompt="p", total_seconds=4, aspect_ratio="16:9", seed=0, task="t2va",
                 status="failed", error="사용자가 중단함 (Ctrl+C)", scenes=[Scene(0, "p", 4, "t2va", status="in_progress", video_id="video_1")])
        store.save(jb)
        code, out, err = run("show", "last", "--output-dir", str(out_dir))
        self.assertEqual(code, 0, err)
        self.assertIn("장면1 t2va 4초 진행", out); self.assertNotIn("in_progress", out)
        code, out, _ = run("config")
        arrows = {cli.text_width(l.split("←")[0]) for l in out.splitlines() if "←" in l}
        self.assertEqual(len(arrows), 1, out)                    # ← 가 한 줄로 맞는다 (한글 '(없음)' 도)
        code, out, _ = run("config", "unset", "endpoint")
        self.assertNotIn("값 값", out); self.assertNotIn("기본값 값", out)

    def test_ctrl_c_points_at_the_stopped_job(self):
        store = JobStore(self.tmp / "o")
        done = Job(id="20261012-000001-aaaaaa", prompt="a", total_seconds=4, aspect_ratio="16:9", seed=0, task="t2va", status="completed",
                   title="이야기-clip-01", scenes=[Scene(0, "a", 4, "t2va", status="completed")])
        live = Job(id="20261012-000002-bbbbbb", prompt="b", total_seconds=4, aspect_ratio="16:9", seed=1, task="t2va", status="running",
                   title="이야기-clip-02", scenes=[Scene(0, "b", 4, "t2va", status="in_progress", video_id="video_7")])
        for j in (done, live):
            store.add(j)
        buf = io.StringIO()
        with redirect_stderr(buf):
            cli.interrupted(store, [done, live], "h3video json --resume story-x")
        s = buf.getvalue()
        self.assertIn("기록 보기: h3video show 20261012-000002-bbbbbb", s)
        self.assertIn("작업 2/2(이야기-clip-02) 장면 1(video_7)", s)
        self.assertEqual(store.get("20261012-000002-bbbbbb").status, "failed")

    def test_story_json_error_says_where(self):
        with self.assertRaises(H3Error) as e:
            story.load_story('{"clips": [\n  {"prompt": "a",}\n]}')
        self.assertIn("2줄", str(e.exception)); self.assertIn("쉼표", str(e.exception))


if __name__ == "__main__":
    unittest.main()
