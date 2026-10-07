"""shorts CLI 테스트: 가짜 /v1/videos 서버(SGLang·vLLM 모양), minimax-h3-video 웹 서버, 가짜 Anthropic 엔드포인트.

  python3 -m unittest discover -s tests -p 'test_*.py'
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_servers as F  # noqa: E402
from shorts import backends as B  # noqa: E402
from shorts import claude as C  # noqa: E402
from shorts import cli  # noqa: E402
from shorts import render as R  # noqa: E402
from shorts import spec as S  # noqa: E402

H3_REPO = Path(os.environ.get("H3VIDEO_REPO", "/home/kms/dev/minimax-h3-video"))


def run_cli(*argv, env=None) -> tuple[int, str]:
    buf = io.StringIO()
    with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = cli.main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (print(e.code) or 2)
    return code, buf.getvalue()


def events(text: str) -> list[dict]:
    return [json.loads(ln) for ln in text.splitlines() if ln.startswith("{")]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shorts-test-"))
        cls.media = cls.tmp / "media"
        subprocess.run([str(ROOT / "tests" / "fixtures" / "make_media.sh"), str(cls.media)], check=True, capture_output=True)
        cls.state_env = {"XDG_STATE_HOME": str(cls.tmp / "state"), "SHORTS_SERVER": "", "SHORTS_API_KEY": "",
                         "SHORTS_REF_SERVER": "", "H3_ENDPOINT": "", "H3_REF_ENDPOINT": ""}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def m(self, name: str) -> str:
        return str(self.media / name)

    def write_job(self, name: str, obj: dict) -> Path:
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        p = d / "prompt.json"
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def assertShort(self, path, duration, size=(720, 1280)):
        info = R.probe(str(path))
        self.assertEqual((info["width"], info["height"]), size)
        self.assertAlmostEqual(info["duration"], duration, delta=0.15)
        self.assertTrue(info["hasAudio"], "오디오 트랙이 없음")
        return info


class SpecTest(Base):
    def test_korean_errors(self):
        errs, _ = S.check_spec({"prompt": "", "duration": 30, "ratio": "2:1", "templat": "pip", "server": "localhost:30010"})
        joined = "\n".join(errs)
        self.assertIn("비어 있으면 안 됩니다", joined)
        self.assertIn("15 이하여야 합니다 (지금 30)", joined)
        self.assertIn("'template' 인가요?", joined)
        self.assertIn("http:// 또는 https://", joined)
        self.assertTrue(all(any("가" <= ch <= "힣" for ch in e) for e in errs))

    def test_same_errors_as_web(self):
        """웹(src/core/spec.js)과 같은 문장을 낸다."""
        bad = {"duration": 3, "ratio": "2:1", "templat": "x", "captions": [3, {"text": "a", "start": 2, "end": 1}],
               "sources": [{"path": "a.mp4", "start": 3, "end": 1}]}
        py, _ = S.check_spec(bad)
        js = subprocess.run(["node", "-e", "import('./src/core/spec.js').then(m=>console.log(JSON.stringify(m.checkSpec("
                             + json.dumps(bad) + ").errors)))"], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(py, json.loads(js.stdout))

    def test_run_invalid_json_exit_2(self):
        p = self.write_job("bad", {"prompt": "x", "duration": 2})
        code, out = run_cli("run", p, env=self.state_env)
        self.assertEqual(code, 2)
        self.assertIn("4 이상이어야 합니다", out)
        p.write_text("{ broken", encoding="utf-8")
        code, out = run_cli("run", p, env=self.state_env)
        self.assertIn("JSON 문법 오류", out)

    def test_needs_server_for_ai(self):
        p = self.write_job("noserver", {"prompt": "x"})
        code, out = run_cli("run", p, env=self.state_env)
        self.assertEqual(code, 2)
        self.assertIn("서버 주소가 필요합니다", out)


class ComposeTest(Base):
    """소스만 있는 경우(AI 없음): 템플릿 4종."""

    def test_templates(self):
        caps = ["첫 번째 자막", "두 번째 자막입니다", "마지막 자막"]
        for tpl, exp in (("cutaway", 8.0), ("split", 8.0), ("pip", 8.0), ("montage", 8.5)):
            p = self.write_job(f"tpl-{tpl}", {"base": self.m("base.mp4"), "template": tpl, "title": f"{tpl} 템플릿",
                                              "captions": caps, "output": f"{tpl}.mp4"})
            code, out = run_cli("run", p, self.m("src1.mp4"), self.m("src2.mp4"), self.m("src3.mp4"), "--json", env=self.state_env)
            self.assertEqual(code, 0, out)
            done = [e for e in events(out) if e["event"] == "done"][0]
            self.assertShort(done["output"], exp)
            # montage: 소스 합 3+2.5+3=8.5 를 base 소리 아래 이어 붙이되 길이는 소스 합(최대 60)
        self.assertTrue((self.tmp / "tpl-montage" / "montage.mp4").is_file())

    def test_sources_only_no_base_montage(self):
        p = self.write_job("srconly", {"captions": ["소스만"], "template": "pip", "resolution": "1080x1920"})
        code, out = run_cli("run", p, self.m("src1.mp4"), self.m("src2.mp4"), env=self.state_env)
        self.assertEqual(code, 0, out)
        self.assertIn("몽타주", out)
        self.assertShort(self.tmp / "srconly" / "short.mp4", 5.5, (1080, 1920))

    def test_compose_subcommand_and_dry_run(self):
        caps = self.tmp / "caps.txt"
        caps.write_text("하나\n\n둘\n", encoding="utf-8")
        out_mp4 = self.tmp / "compose.mp4"
        code, out = run_cli("compose", "--base", self.m("base.mp4"), "--source", self.m("src1.mp4"), "--template", "split",
                            "--captions", caps, "--title", "분할", "--bgm", self.m("bgm.m4a"), "-o", out_mp4)
        self.assertEqual(code, 0, out)
        self.assertShort(out_mp4, 8.0)
        code, out = run_cli("compose", "--base", self.m("base.mp4"), "--source", self.m("src1.mp4"), "-o", self.tmp / "dry.mp4", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("ffmpeg 명령", out)
        self.assertIn("filter_complex", out)
        self.assertFalse((self.tmp / "dry.mp4").exists())

    def test_missing_file(self):
        p = self.write_job("missing", {"base": "nope.mp4"})
        code, out = run_cli("run", p, env=self.state_env)
        self.assertEqual(code, 2)
        self.assertIn("파일이 없습니다", out)


class GenTest(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.httpd, cls.st, cls.url = F.start_video("sglang", steps=2)
        cls.vhttpd, cls.vst, cls.vurl = F.start_video("vllm", steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.vhttpd.shutdown()
        super().tearDownClass()

    def env(self, **kw):
        return {**self.state_env, "SHORTS_SERVER": self.url, **kw}

    def test_prompt_only(self):
        n0 = len(self.st.requests)
        p = self.write_job("ai-prompt", {"prompt": "a cat jumps", "duration": 8, "title": "점프", "captions": ["하나", "둘"]})
        code, out = run_cli("run", p, "--poll", "0.2", env=self.env())
        self.assertEqual(code, 0, out)
        req = self.st.requests[n0]["body"]
        self.assertEqual(req["task"], "t2va")
        self.assertEqual(req["conditions"], [])
        self.assertEqual(req["target"], {"short_edge": 768, "aspect_ratio": "9:16", "duration_seconds": 8})
        self.assertShort(self.tmp / "ai-prompt" / "short.mp4", 8.0)

    def test_prompt_and_source(self):
        n0 = len(self.st.requests)
        p = self.write_job("ai-both", {"prompt": "dance like <Video 1>", "duration": 5, "image": self.m("first.png")})
        code, out = run_cli("run", p, self.m("src1.mp4"), "--poll", "0.2", "--inbox-dir", self.tmp / "inbox", env=self.env())
        self.assertEqual(code, 0, out)
        req = self.st.requests[n0]["body"]
        self.assertEqual(req["task"], "ref2va")
        types = [c["type"] for c in req["conditions"]]
        self.assertEqual(types, ["video", "image"])
        self.assertTrue(req["conditions"][0]["uri"].startswith("file://" + str(self.tmp / "inbox")))
        self.assertShort(self.tmp / "ai-both" / "short.mp4", 5.0)

    def test_scenes_and_base(self):
        n0 = len(self.st.requests)
        p = self.write_job("ai-scenes", {"scenes": [{"prompt": "s1", "duration": 4}, {"prompt": "s2", "duration": 5, "image": self.m("first.png")}],
                                         "base": self.m("base.mp4"), "template": "cutaway", "captions": ["가", "나"]})
        code, out = run_cli("run", p, "--poll", "0.2", env=self.env())
        self.assertEqual(code, 0, out)
        reqs = [r["body"] for r in self.st.requests[n0:]]
        self.assertEqual([r["task"] for r in reqs], ["t2va", "fl2va"])
        self.assertEqual(reqs[1]["conditions"][0]["role"], "keyframe")
        self.assertEqual(reqs[1]["seed"], 1)
        self.assertShort(self.tmp / "ai-scenes" / "short.mp4", 8.0)

    def test_dry_run_json(self):
        n0 = len(self.st.requests)
        p = self.write_job("ai-dry", {"prompt": "x", "duration": 6})
        code, out = run_cli("run", p, "--dry-run", "--json", env=self.env())
        self.assertEqual(code, 0, out)
        evs = events(out)
        self.assertTrue(any(e["event"] == "request" and e["body"]["target"]["duration_seconds"] == 6 for e in evs))
        self.assertEqual(len(self.st.requests), n0, "dry-run 이 요청을 보냄")

    def test_h3_limits_block_before_send(self):
        long = self.tmp / "long.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=10:d=16", "-c:v", "libx264", str(long)], check=True)
        n0 = len(self.st.requests)
        p = self.write_job("ai-limit", {"prompt": "x"})
        code, out = run_cli("run", p, long, env=self.env())
        self.assertEqual(code, 2)
        self.assertIn("15초 이하여야 합니다", out)
        self.assertEqual(len(self.st.requests), n0)

    def test_length_mismatch_warning(self):
        self.st.max_seconds = 6.0
        try:
            p = self.write_job("ai-short", {"prompt": "x", "duration": 8})
            code, out = run_cli("run", p, "--poll", "0.2", "--json", env=self.env())
        finally:
            self.st.max_seconds = 15.0
        self.assertEqual(code, 0, out)
        self.assertTrue(any(e["event"] == "warning" and "요청(8초)" in e["message"] for e in events(out)))

    def test_rerun_reuses_same_request_only(self):
        p = self.write_job("ai-rerun", {"prompt": "rerun", "duration": 4})
        run_cli("run", p, "--poll", "0.2", env=self.env())
        n0 = len(self.st.requests)
        code, out = run_cli("run", p, "--poll", "0.2", env=self.env())
        self.assertIn("이어 씁니다", out)
        self.assertEqual(len(self.st.requests), n0)
        p.write_text(json.dumps({"prompt": "rerun", "duration": 5}), encoding="utf-8")
        run_cli("run", p, "--poll", "0.2", env=self.env())
        self.assertEqual(len(self.st.requests), n0 + 1)
        self.assertShort(self.tmp / "ai-rerun" / "short.mp4", 5.0)

    def test_gen_subcommand_and_api_key(self):
        self.st.api_key = "secret-token"
        try:
            out_mp4 = self.tmp / "clip.mp4"
            code, out = run_cli("gen", "--prompt", "x", "--duration", "4", "--poll", "0.2", "-o", out_mp4, env=self.env())
            self.assertEqual(code, 1)
            self.assertIn("SHORTS_API_KEY", out)
            code, out = run_cli("gen", "--prompt", "x", "--duration", "4", "--poll", "0.2", "-o", out_mp4,
                                env=self.env(SHORTS_API_KEY="secret-token"))
            self.assertEqual(code, 0, out)
            self.assertEqual(self.st.requests[-1]["auth"], "Bearer secret-token")
            self.assertEqual(R.probe(str(out_mp4))["duration"], 4.0)
        finally:
            self.st.api_key = None

    def test_vllm_autodetect_multipart(self):
        n0 = len(self.vst.requests)
        p = self.write_job("vllm", {"prompt": "x", "duration": 4})
        code, out = run_cli("run", p, self.m("first.png"), "--poll", "0.2", env=self.env(SHORTS_SERVER=self.vurl))
        self.assertEqual(code, 0, out)
        self.assertIn("(vllm)", out)
        r = self.vst.requests[n0]
        self.assertEqual(r["kind"], "multipart")
        self.assertEqual(r["body"]["size"], ["720x1280"])
        self.assertEqual(r["body"]["seconds"], ["4"])
        self.assertEqual(r["body"]["input_reference"][0]["filename"], "first.png")

    def test_server_check(self):
        code, out = run_cli("server", "check", "--server", self.url)
        self.assertEqual(code, 0, out)
        self.assertIn("종류: sglang", out)
        self.assertIn("MiniMax-H3", out)
        self.assertIn("ref2va", out)
        code, out = run_cli("server", "check", "--server", self.vurl, "--json")
        self.assertEqual(events(out)[0]["backend"], "vllm")
        code, out = run_cli("server", "check", "--server", "http://127.0.0.1:9")
        self.assertEqual(code, 1)
        self.assertIn("연결하지 못했습니다", out)

    def test_timeout_then_resume(self):
        self.st.steps = 10_000
        p = self.write_job("ai-resume", {"prompt": "slow", "duration": 4, "timeout": 10})
        try:
            import itertools
            with mock.patch.object(B.time, "monotonic", side_effect=(float(x) for x in itertools.count(0, 100))):
                code, out = run_cli("run", p, "--poll", "0.2", env=self.env())
        finally:
            self.st.steps = 2
        self.assertEqual(code, 1)
        self.assertIn("shorts resume", out)
        rid = [ln for ln in out.splitlines() if "작업 ID:" in ln][0].split("작업 ID:")[1].strip()
        code, out = run_cli("resume", rid, "--poll", "0.2", env=self.env())
        self.assertEqual(code, 0, out)
        self.assertShort(self.tmp / "ai-resume" / "short.mp4", 4.0)

    def test_ctrl_c_prints_job_id(self):
        p = self.write_job("ai-ctrlc", {"prompt": "interrupt", "duration": 4})
        with mock.patch.object(B, "wait_and_download", side_effect=KeyboardInterrupt):
            code, out = run_cli("run", p, "--poll", "0.2", env=self.env())
        self.assertEqual(code, 130)
        self.assertIn("작업 ID: video_", out)
        self.assertIn("shorts resume video_", out)


class H3RoutingTest(Base):
    """cluster_env.sh 처럼 H3_ENDPOINT(30010 역할)·H3_REF_ENDPOINT(30011 역할)만 잡혀 있을 때: 소스 없으면 fl2va 쪽, 있으면 ref2va 쪽."""

    def test_routing_and_h3video_body(self):
        fl, fl_st, fl_url = F.start_video("sglang", steps=1)
        ref, ref_st, ref_url = F.start_video("sglang", steps=1)
        env = {**self.state_env, "H3_ENDPOINT": fl_url, "H3_REF_ENDPOINT": ref_url}
        try:
            p1 = self.write_job("route-t2v", {"prompt": "no source", "duration": 4})
            self.assertEqual(run_cli("run", p1, "--poll", "0.2", env=env)[0], 0)
            p2 = self.write_job("route-ref", {"prompt": "with source", "duration": 4,
                                              "sources": [{"path": self.m("base.mp4"), "start": 1, "end": 4}]})
            code, out = run_cli("run", p2, "--poll", "0.2", env=env)
            self.assertEqual(code, 0, out)
        finally:
            fl.shutdown()
            ref.shutdown()
        self.assertEqual([r["body"]["task"] for r in fl_st.requests], ["t2va"])
        self.assertEqual([r["body"]["task"] for r in ref_st.requests], ["ref2va"])
        cond = ref_st.requests[0]["body"]["conditions"][0]
        self.assertEqual(set(cond), {"type", "uri", "role"})          # h3video Condition 과 같은 필드
        self.assertIn("ref01-1.mp4", cond["uri"])                      # start/end 구간은 잘라서 보냄
        # 같은 venv 에 h3video 가 있으면 그 VideoRequest 로 만든 본문과 내장 구현이 같아야 한다
        if (H3_REPO / "src").is_dir():
            sys.path.insert(0, str(H3_REPO / "src"))
            req = {"prompt": "p", "task": "fl2va", "duration": 6, "ratio": "9:16", "seed": 2, "refs": [], "image": "/x/f.png"}
            bk = B.SGLangBackend("http://x", stager=B.Stager())
            B._H3 = None
            with_h3 = bk.build_body(req, stage=False)
            B._H3 = False
            builtin = bk.build_body(req, stage=False)
            B._H3 = None
            self.assertIsNotNone(B.h3video_client())
            self.assertEqual(with_h3, builtin)


@unittest.skipUnless((H3_REPO / "src" / "h3video" / "web.py").is_file(), "minimax-h3-video 저장소 없음")
class H3VideoWebTest(Base):
    """minimax-h3-video 의 h3video web 서버(/api/jobs)에 붙는 경우."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.path.insert(0, str(H3_REPO / "src"))
        sys.path.insert(0, str(H3_REPO / "tests"))
        import mock_server  # noqa: E402  (minimax-h3-video 의 가짜 SGLang)
        from h3video.web import App, make_handler
        from http.server import ThreadingHTTPServer
        import threading
        cls.sg, cls.sg_state, sg_url = mock_server.start(steps=2)
        app = App(sg_url, sg_url, cls.tmp / "h3out", str(cls.tmp / "h3inbox"), poll=0.05)
        cls.web = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.web.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.sg.shutdown()
        super().tearDownClass()

    def test_detect_check_and_run_with_source(self):
        code, out = run_cli("server", "check", "--server", self.url)
        self.assertEqual(code, 0, out)
        self.assertIn("종류: h3video", out)
        p = self.write_job("h3web", {"prompt": "ref test", "duration": 4, "captions": ["h3video 경유"]})
        code, out = run_cli("run", p, self.m("src1.mp4"), "--poll", "0.2", env={**self.state_env, "SHORTS_SERVER": self.url})
        self.assertEqual(code, 0, out)
        self.assertIn("(h3video)", out)
        sent = self.sg_state.requests[-1]
        self.assertEqual(sent["task"], "ref2va")
        self.assertEqual(sent["conditions"][0]["type"], "video")
        info = R.probe(str(self.tmp / "h3web" / "short.mp4"))
        self.assertEqual((info["width"], info["height"]), (720, 1280))
        self.assertTrue(info["hasAudio"])


class ClaudePlanTest(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vhttpd, cls.vst, cls.vurl = F.start_video("sglang", steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.vhttpd.shutdown()
        super().tearDownClass()

    def good_spec(self, src=None):
        spec = {"scenes": [{"prompt": "A neon street at night, slow dolly in", "duration": 5},
                           {"prompt": "Close-up of rain on a window", "duration": 4}],
                "ratio": "9:16", "title": "비 오는 밤", "captions": ["비가 온다", "네온이 번진다", "창문 너머"], "template": "montage"}
        if src:
            spec.update({"base": src, "template": "cutaway"})
        return spec

    def test_api_schema_has_only_supported_keywords(self):
        sch = json.dumps(C.api_schema())
        for k in ("minimum", "maximum", "minLength", "pattern", "$ref", "server", "output"):
            self.assertNotIn(f'"{k}"', sch)
        self.assertIn('"additionalProperties": false', sch)

    def test_plan_retry_then_valid(self):
        bad = self.good_spec()
        bad["scenes"][0]["duration"] = 30
        httpd, st, url = F.start_anthropic([F.reply_with_json(bad), F.reply_with_json(self.good_spec())])
        try:
            out_json = self.tmp / "planned.json"
            code, out = run_cli("plan", "비 오는 밤 네온 거리 감성 숏폼", "-o", out_json,
                                env={"ANTHROPIC_API_KEY": "sk-test-123", "ANTHROPIC_BASE_URL": url})
        finally:
            httpd.shutdown()
        self.assertEqual(code, 0, out)
        self.assertIn("다시 요청합니다", out)
        self.assertNotIn("sk-test-123", out)
        self.assertEqual(len(st.requests), 2)
        h = st.headers[0]
        self.assertEqual(h["x-api-key"], "sk-test-123")
        self.assertEqual(h["anthropic-version"], "2023-06-01")
        first, second = st.requests
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("tool_choice", first)
        self.assertEqual(second["messages"][1]["role"], "assistant")
        self.assertEqual(second["messages"][1]["content"][0]["type"], "thinking")
        self.assertIn("15 이하여야 합니다", second["messages"][2]["content"][0]["text"])
        saved = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(S.check_spec(saved)[0], [])

    def test_plan_gives_up_after_one_retry(self):
        bad = {"scenes": [{"prompt": "x", "duration": 99}]}
        httpd, st, url = F.start_anthropic([F.reply_with_json(bad), F.reply_with_json(bad)])
        try:
            code, out = run_cli("plan", "아이디어", env={"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": url})
        finally:
            httpd.shutdown()
        self.assertEqual(code, 2)
        self.assertIn("검증을 통과하지 못했습니다", out)
        self.assertEqual(len(st.requests), 2)

    def test_plan_dry_run_hides_key_and_sends_frames(self):
        code, out = run_cli("plan", "소스 영상 요약", "--source", self.m("base.mp4"), "--dry-run",
                            env={"ANTHROPIC_API_KEY": "sk-secret-zzz"})
        self.assertEqual(code, 0, out)
        self.assertNotIn("sk-secret-zzz", out)
        self.assertIn("image/jpeg", out)
        self.assertIn("base.mp4", out)
        code, out = run_cli("plan", "x", env={"ANTHROPIC_API_KEY": ""})
        self.assertIn("ANTHROPIC_API_KEY", out)

    def test_run_idea_end_to_end_with_source(self):
        spec = self.good_spec("src1.mp4")
        httpd, st, url = F.start_anthropic([F.reply_with_json(spec)])
        try:
            out_mp4 = self.tmp / "idea.mp4"
            code, out = run_cli("run", "--idea", "빨간 화면 소개", self.m("src1.mp4"), "-o", out_mp4, "--poll", "0.2",
                                "--plan-output", self.tmp / "idea.json",
                                env={**self.state_env, "ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": url, "SHORTS_SERVER": self.vurl})
        finally:
            httpd.shutdown()
        self.assertEqual(code, 0, out)
        imgs = [b for b in st.requests[0]["messages"][0]["content"] if b["type"] == "image"]
        self.assertGreaterEqual(len(imgs), 2)
        self.assertEqual(len(self.vst.requests[-2:]), 2)
        info = self.assertShort(out_mp4, 3.0)
        self.assertEqual(info["width"], 720)


if __name__ == "__main__":
    unittest.main()
