"""CLI 쓰기 편하게: 인자 없이 빠른 시작, 명령 없이 알아서 고르기, 다른 이름·오타 안내, 저장 설정(config) 우선순위,
진행 한 줄 표시, Ctrl+C 이어 하기 안내, health/doctor 할 일, --open."""
import contextlib
import io
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from test_cli import dead_url, run  # noqa: E402
from test_story import CONTI, png  # noqa: E402
from h3video import cli, config, hints  # noqa: E402
from h3video.jobs import Job, Scene  # noqa: E402

ENV_KEYS = ("H3_ENDPOINT", "H3_REF_ENDPOINT", "H3_OUTPUT_DIR", "H3_INBOX_DIR")


class CleanEnv(unittest.TestCase):
    """설정 파일은 임시 폴더(XDG_CONFIG_HOME)에, H3_* 환경 변수는 비운다."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
        env["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)


class QuickStartAndRoutingTest(CleanEnv):
    def test_no_args_prints_quick_start(self):
        for argv in ([], ["--endpoint", dead_url()]):
            code, out, err = run(*argv)
            self.assertEqual(code, 0, err)
            self.assertIn("h3video — ", out)
            for c in ('h3video "', "h3video jobs", "h3video doctor", "h3video web", "h3video --help"):
                self.assertIn(c, out)
            self.assertLessEqual(len([l for l in out.splitlines() if l.startswith("  h3video")]), 6)

    def test_prompt_first_is_gen(self):
        code, out, err = run("비 오는 서울 밤거리", "-s", "20", "--dry-run", "--endpoint", dead_url())
        self.assertEqual(code, 0, err)
        self.assertEqual(len([l for l in err.splitlines() if l.startswith("[자동]")]), 1)
        self.assertIn("gen", err)
        self.assertIn("장면 2개 [10, 10]", out)
        # 공통 옵션을 앞에 써도, 옵션부터 써도
        code, out, err = run("--endpoint", dead_url(), "--poll", "1", "고양이", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn('"prompt": "고양이"', out)
        code, out, err = run("-s", "6", "고양이", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn("장면 1개 [6]", out); self.assertIn("[자동]", err)
        self.assertEqual(cli.route(["--poll=1", "x y"])[0], ["--poll=1", "gen", "x y"])

    def test_files_first(self):
        a, b = png(self.tmp / "a.png"), png(self.tmp / "b.png")
        code, out, err = run(str(a), "아이가 웃는다", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("--first", err); self.assertIn('"task": "fl2va"', out); self.assertIn('"frame_index": 0', out)
        code, out, err = run(str(a), str(b), "아이가 웃는다", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn('"frame_index": -1', out)
        (self.tmp / "p.txt").write_text("파일에 쓴 프롬프트", encoding="utf-8")
        code, out, err = run(str(self.tmp / "p.txt"), "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn("파일에 쓴 프롬프트", out)
        (self.tmp / "t.json").write_text(json.dumps(CONTI, ensure_ascii=False), encoding="utf-8")
        code, out, err = run(str(self.tmp / "t.json"), "--list", "--output-dir", str(self.tmp / "o"))
        self.assertEqual(code, 0, err)
        self.assertIn("json", err.splitlines()[0]); self.assertIn("[page-01]", out)

    def test_aliases_and_typos(self):
        code, out, err = run("t2v", "고양이", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn("t2v → h3video gen", err); self.assertIn("[dry-run] t2va", out)
        code, out, err = run("i2v", "고양이", "--dry-run")
        self.assertEqual(code, 0, err); self.assertIn("--first", err)
        code, out, err = run("list", "--output-dir", str(self.tmp / "none"))
        self.assertEqual(code, 0, err); self.assertIn("jobs", err); self.assertIn("작업이 없다", out)
        self.assertEqual(cli.route(["story", "a.json"])[0], ["json", "a.json"])
        self.assertEqual(cli.route(["ref2va", "x"])[0], ["ref", "x"])
        code, out, err = run("help", "json")
        self.assertEqual(code, 0); self.assertIn("사용법: h3video json", out)
        code, out, err = run("gne", "x")
        self.assertEqual(code, 2); self.assertIn("'gne'", err); self.assertIn("혹시: h3video gen", err)
        code, out, err = run("helth")
        self.assertEqual(code, 2); self.assertIn("혹시: h3video health", err)
        code, out, err = run("qqqzzz")
        self.assertEqual(code, 2); self.assertNotIn("혹시", err); self.assertIn('h3video gen "qqqzzz"', err)
        # 모르는 옵션: 그 명령의 사용법 + 비슷한 옵션, 한국어
        code, out, err = run("gen", "x", "--secs", "4")
        self.assertEqual(code, 2)
        self.assertIn("사용법: h3video gen", err); self.assertIn("--secs → --seconds", err); self.assertIn("모르는 옵션", err)
        code, out, err = run("gen", "x", "-r", "5:4")
        self.assertEqual(code, 2); self.assertIn("쓸 수 없다", err); self.assertNotIn("invalid choice", err)


class ConfigTest(CleanEnv):
    def parsed(self, *argv):
        return cli.build_parser().parse_args(list(argv))

    def test_precedence_flag_env_config_default(self):
        self.assertEqual(config.path(), self.tmp / "xdg" / "h3video" / "config.json")
        self.assertEqual(self.parsed("gen", "x").endpoint, "http://127.0.0.1:30010")              # 기본값
        code, out, err = run("config", "set", "endpoint", "http://cfg-host:1/")
        self.assertEqual(code, 0, err); self.assertIn("저장했다", out)
        self.assertEqual(json.loads(config.path().read_text())["endpoint"], "http://cfg-host:1")
        self.assertEqual(self.parsed("gen", "x").endpoint, "http://cfg-host:1")                    # 설정 파일
        with mock.patch.dict(os.environ, {"H3_ENDPOINT": "http://env-host:2"}):
            self.assertEqual(self.parsed("gen", "x").endpoint, "http://env-host:2")                # 환경 변수
            self.assertEqual(self.parsed("gen", "x", "--endpoint", "http://flag:3").endpoint, "http://flag:3")   # 옵션
            self.assertEqual(self.parsed("--endpoint", "http://flag:4", "gen", "x").endpoint, "http://flag:4")
            code, out, _ = run("config")
            self.assertIn("환경 변수 H3_ENDPOINT", out); self.assertIn("가려", out)
        code, out, _ = run("config", "show")
        self.assertIn("http://cfg-host:1", out); self.assertIn("설정 파일", out); self.assertIn("우선순위", out)
        code, out, _ = run("config", "unset", "endpoint")
        self.assertEqual(code, 0); self.assertIn("지웠다", out)
        self.assertEqual(self.parsed("gen", "x").endpoint, "http://127.0.0.1:30010")

    def test_output_dir_and_errors(self):
        out_dir = self.tmp / "my videos"
        code, out, err = run("config", "set", "output_dir", str(out_dir))   # _ 도 받는다
        self.assertEqual(code, 0, err)
        self.assertEqual(self.parsed("jobs").output_dir, str(out_dir.resolve()))
        code, _, err = run("config", "set", "endpont", "http://x")
        self.assertEqual(code, 1); self.assertIn("혹시: endpoint", err)
        code, _, err = run("config", "set", "endpoint", "127.0.0.1:30010")
        self.assertEqual(code, 1); self.assertIn("http://", err)
        code, _, err = run("config", "sett")
        self.assertEqual(code, 1); self.assertIn("혹시: h3video config set", err)
        # 혹시 비밀 값이 들어 있어도 화면에 보이지 않는다
        cfg = json.loads(config.path().read_text()); cfg["api-token"] = "s3cret-value"
        config.path().write_text(json.dumps(cfg))
        code, out, _ = run("config")
        self.assertIn("(가림)", out); self.assertNotIn("s3cret-value", out)
        config.path().write_text("{broken")      # 깨진 파일 때문에 명령이 멈추지 않는다
        self.assertEqual(self.parsed("gen", "x").endpoint, "http://127.0.0.1:30010")


class ServerCheckTest(CleanEnv):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def test_health_and_doctor_say_what_to_do(self):
        dead = dead_url()
        code, out, _ = run("health", "--endpoint", dead, "--ref-endpoint", self.url)
        self.assertEqual(code, 1)
        self.assertIn("실패", out); self.assertIn("bash scripts/up.sh", out); self.assertIn("h3video config set endpoint", out)
        self.assertIn("옵션 --endpoint", out)
        self.assertRegex(out, r"OK\s+참고 자료 서버")
        code, out, _ = run("doctor", "--endpoint", self.url, "--ref-endpoint", dead, "--output-dir", str(self.tmp / "o"))
        self.assertEqual(code, 0, out)
        self.assertIn("up.sh --ref", out); self.assertIn("결과 폴더", out); self.assertIn("전부 괜찮다", out)
        code, out, _ = run("doctor", "--endpoint", dead, "--output-dir", str(self.tmp / "o"))
        self.assertEqual(code, 1); self.assertIn("안 되는 것 1개", out)

    def test_result_path_and_open(self):
        bindir = self.tmp / "bin"; bindir.mkdir()
        log = self.tmp / "opened.txt"
        opener = bindir / "xdg-open"
        opener.write_text(f"#!/bin/sh\necho \"$@\" > {shlex.quote(str(log))}\n"); opener.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ.get('PATH', '')}", "DISPLAY": ":0"}):
            code, out, err = run("고양이가 하품한다", "-s", "4", "--open", "--endpoint", self.url,
                                 "--output-dir", str(self.tmp / "o"), "--poll", "0.01")
        self.assertEqual(code, 0, err)
        path = out.strip()
        self.assertTrue(path.endswith(".mp4") and Path(path).is_file())
        self.assertIn("결과 파일:", err)
        for _ in range(50):
            if log.exists():
                break
            time.sleep(0.05)
        self.assertEqual(log.read_text().strip(), path)
        with mock.patch.dict(os.environ, {"PATH": str(bindir), "DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                cli.open_paths(["/x/a.mp4"])
            self.assertIn("화면이 없는 곳", buf.getvalue())


class ProgressTest(unittest.TestCase):
    def test_one_line_on_tty_plain_lines_otherwise(self):
        buf = io.StringIO()
        p = cli.Progress(buf, tty=True)
        p.line("경과 3초 · 장면 1/2 · 생성 50%")
        p.line("경과 4초 · 장면 1/2 · 생성 60%")
        p.log("  ✓ 완료")
        p.close()
        s = buf.getvalue()
        self.assertEqual(s.count("\n"), 1)                 # 진행 줄은 고쳐 쓰고, 남길 줄만 줄바꿈
        self.assertEqual(s.count("\r\x1b[K"), 3)
        self.assertIn("생성 60%", s)
        buf = io.StringIO()
        p = cli.Progress(buf, tty=False)
        p.line("안 보임"); p.log("보임"); p.close()
        self.assertEqual(buf.getvalue(), "보임\n")
        self.assertEqual(cli.fit_width("가나다라마바사", 9), "가나다라…")
        self.assertEqual(cli.text_width("가a"), 3)

    def test_compact_status(self):
        jb = Job(id="j", prompt="p", total_seconds=20, aspect_ratio="16:9", seed=0, task="t2va", status="running",
                 scenes=[Scene(0, "p", 10, "t2va", status="completed", progress=1),
                         Scene(1, "p", 10, "fl2va", status="in_progress", progress=0.45)])
        self.assertEqual(cli.compact_status(jb), "장면 2/2 · 생성 45%")
        jb.scenes[1].stage = "다듬는 중"
        self.assertEqual(cli.compact_status(jb), "장면 2/2 · 다듬는 중")
        jb.scenes[1].status = "queued"
        self.assertEqual(cli.compact_status(jb), "장면 2/2 · 서버 대기열")
        jb.status = "pending"
        self.assertEqual(cli.compact_status(jb), "준비 중")


class CtrlCTest(CleanEnv):
    def test_ctrl_c_on_json_says_how_to_resume(self):
        slow_httpd, _, slow_url = mock_server.start(steps=10_000)
        self.addCleanup(lambda: (slow_httpd.shutdown(), slow_httpd.server_close()))
        (self.tmp / "t.json").write_text(json.dumps({"clips": ["고양이", "강아지"]}, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen([sys.executable, "-m", "h3video.cli", str(self.tmp / "t.json"), "--endpoint", slow_url,
                              "--output-dir", str(self.tmp / "o"), "--poll", "0.05"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        time.sleep(3)
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 130, err)
        self.assertNotIn("Traceback", err)
        self.assertIn("h3video json --resume story-", err)
        self.assertIn("--output-dir", err)
        self.assertIn("h3video fetch video_0001", err)


class CommandForJobTest(unittest.TestCase):
    def test_job_command_parses_back_to_the_same_settings(self):
        d = {"prompt": "비 오는 밤 'quote' $HOME", "total_seconds": 40, "aspect_ratio": "9:16", "seed": 7, "short_edge": 576,
             "scene_seconds": 10, "steps": 30, "negative": "글자", "raw": True, "title": "밤", "first_image": "/up/a b.png",
             "last_image": None, "refs": []}
        cmd = hints.job_command(d)
        self.assertTrue(cmd.startswith("h3video gen "))
        a = cli.build_parser().parse_args(shlex.split(cmd)[1:])
        self.assertEqual((a.prompt, a.seconds, a.ratio, a.seed, a.size, a.steps, a.negative, a.raw, a.title, a.first),
                         (d["prompt"], 40, "9:16", 7, 576, 30, "글자", True, "밤", "/up/a b.png"))
        refs = {"prompt": "1번 사진", "total_seconds": 8, "aspect_ratio": "16:9", "seed": 0,
                "refs": [{"type": "image", "path": "/u/1.png"}, {"type": "audio", "path": "/u/v.wav"}]}
        a = cli.build_parser().parse_args(shlex.split(hints.job_command(refs))[1:])
        self.assertEqual((a.image, a.audio, a.ratio), (["/u/1.png"], ["/u/v.wav"], "16:9"))
        a = cli.build_parser().parse_args(shlex.split(hints.job_command({**refs, "prompt": "-대시로 시작"}))[1:])
        self.assertEqual(a.prompt, "-대시로 시작")

    def test_plain_errors(self):
        self.assertIn("연결하지 못했어요", hints.explain_error("POST /v1/videos 연결 실패 (http://x): refused"))
        self.assertIn("up.sh --ref", hints.explain_error("연결 실패", "ref2va"))
        self.assertIn("576", hints.explain_error("RuntimeError: CUDA out of memory"))
        self.assertIn("멈췄어요", hints.explain_error("사용자가 중단함 (Ctrl+C)"))
        self.assertIsNone(hints.explain_error(None))
        self.assertIn("터널", hints.server_hint("fl2va", "http://127.0.0.1:30010"))
        self.assertNotIn("터널", hints.server_hint("fl2va", "http://gpu-node:30010"))


if __name__ == "__main__":
    unittest.main()
