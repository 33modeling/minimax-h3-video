"""CLI 편의 기능: 옵션 위치, 표준입력, --dry-run, 서버 사전 확인, -o 복사, batch, jobs/show, fetch --ref, Ctrl+C."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import mock_server  # noqa: E402
from h3video import cli  # noqa: E402
from h3video.client import H3Client, VideoRequest  # noqa: E402


def run(*argv):
    """main() 를 같은 프로세스에서 돌리고 (종료 코드, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if not isinstance(e.code, int) and e.code:
                err.write(str(e.code))
    return code, out.getvalue(), err.getvalue()


def dead_url():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return f"http://127.0.0.1:{port}"


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, cls.state, cls.url = mock_server.start(steps=2)
        cls.ref_httpd, cls.ref_state, cls.ref_url = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.ref_httpd.shutdown(); cls.httpd.server_close(); cls.ref_httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.g = ["--endpoint", self.url, "--ref-endpoint", self.ref_url, "--output-dir", str(self.tmp / "outputs"), "--poll", "0.01"]

    def test_options_after_command_and_out_copy(self):
        # 공통 옵션을 명령 뒤에 써도 되고, -o 로 원하는 곳에 저장된다.
        code, out, err = run("gen", "비 오는 서울 밤거리", "-s", "5", "-r", "9:16", "-t", "seoul", "-n", "글자", "-o", str(self.tmp / "mine" / "rain"), *self.g)
        self.assertEqual(code, 0, err)
        dest = self.tmp / "mine" / "rain.mp4"
        self.assertEqual(out.strip().splitlines(), [str(dest)])   # stdout 에는 결과 경로만
        self.assertTrue(dest.exists() and dest.stat().st_size > 1000)
        req = self.state.requests[-1]
        self.assertEqual((req["target"]["duration_seconds"], req["target"]["aspect_ratio"], req["negative_prompt"]), (5, "9:16", "글자"))
        self.assertIn("완료", err)

    def test_stdin_prompt(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        r = subprocess.run([sys.executable, "-m", "h3video.cli", "gen", "-s", "4", *self.g], input="표준입력 프롬프트: 고양이가 하품한다",
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.state.requests[-1]["prompt"], "표준입력 프롬프트: 고양이가 하품한다")

    def test_dry_run_needs_no_server_and_matches_chain(self):
        img = self.tmp / "key.png"; img.write_bytes(b"\x89PNG" + b"\0" * 50)
        n = len(self.state.requests)
        code, out, err = run("gen", "배가 떠난다", "--first", str(img), "-s", "40", "--dry-run", "--endpoint", dead_url())
        self.assertEqual(code, 0, err)
        self.assertIn("장면 4개 [10, 10, 10, 10]", out)
        self.assertEqual(out.count('"task": "fl2va"'), 4)
        self.assertIn("<이전 장면 마지막 프레임>", out)
        self.assertEqual(len(self.state.requests), n)   # 아무것도 보내지 않았다

    def test_early_errors(self):
        code, _, err = run("gen", "x", *self.g, "--endpoint", dead_url())
        self.assertEqual(code, 1); self.assertIn("서버가 응답하지 않는다", err); self.assertIn("SSH 터널", err)
        code, _, err = run("gen", "x", "--first", "missing.png", *self.g)
        self.assertEqual(code, 1); self.assertIn("입력 파일 없음", err)
        imgs = []
        for i in range(10):
            p = self.tmp / f"i{i}.png"; p.write_bytes(b"\x89PNG"); imgs += ["--image", str(p)]
        n = len(self.ref_state.requests)
        code, _, err = run("ref", "x", *imgs, *self.g)
        self.assertEqual(code, 1); self.assertIn("최대 9", err)
        self.assertEqual(len(self.ref_state.requests), n)
        code, _, err = run("gen", "x", "-s", "3", *self.g)
        self.assertEqual(code, 1); self.assertIn("최소 4초", err)
        code, _, _ = run("gen", "x", "--seed", "abc", *self.g)
        self.assertEqual(code, 2)

    def test_batch_jobs_show(self):
        (self.tmp / "k.png").write_bytes(b"\x89PNG" + b"\0" * 50)
        (self.tmp / "b.txt").write_text("# 두 개\nseconds: 6\ntitle: one\n첫 번째 영상 프롬프트\n둘째 줄\n---\nratio: 1:1\nfirst: k.png\n두 번째 영상\n", encoding="utf-8")
        code, out, err = run("batch", str(self.tmp / "b.txt"), "-o", str(self.tmp / "all"), *self.g)
        self.assertEqual(code, 0, err)
        files = sorted(p.name for p in (self.tmp / "all").iterdir())
        self.assertEqual(len(files), 2); self.assertIn("one.mp4", files)
        r1, r2 = self.state.requests[-2:]
        self.assertEqual((r1["prompt"], r1["target"]["duration_seconds"]), ("첫 번째 영상 프롬프트\n둘째 줄", 6))
        self.assertEqual((r2["target"]["aspect_ratio"], r2["task"]), ("1:1", "fl2va"))   # first: 는 batch 파일 기준 상대 경로
        code, out, _ = run("jobs", *self.g)
        self.assertEqual(code, 0); self.assertEqual(out.count("완료"), 2)
        code, out, _ = run("show", "last", *self.g)
        self.assertEqual(code, 0); self.assertIn("두 번째 영상", out); self.assertIn("결과:", out)
        code, _, err = run("show", "nope", *self.g)
        self.assertEqual(code, 1); self.assertIn("찾지 못했다", err)
        code, _, err = run("batch", str(self.tmp / "b.txt"), "--seconds", "x", *self.g)
        self.assertEqual(code, 2)

    def test_fetch_ref_uses_ref_server(self):
        vid = H3Client(self.ref_url).submit(VideoRequest("ref video", task="ref2va", conditions=[]))
        for _ in range(3):
            H3Client(self.ref_url).status(vid)
        code, out, err = run("fetch", vid, "--ref", "-o", str(self.tmp / "r.mp4"), *self.g)
        self.assertEqual(code, 0, err); self.assertTrue((self.tmp / "r.mp4").exists())
        code, _, err = run("fetch", "video_9999", "-o", str(self.tmp / "x.mp4"), *self.g)
        self.assertEqual(code, 1); self.assertIn("404", err)

    def test_health_exit_code(self):
        self.assertEqual(run("health", *self.g)[0], 0)
        self.assertEqual(run("health", *self.g, "--endpoint", dead_url())[0], 1)

    def test_ctrl_c_marks_job_and_prints_fetch_hint(self):
        slow_httpd, _, slow_url = mock_server.start(steps=10_000)
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen([sys.executable, "-m", "h3video.cli", "gen", "느린 영상", "--endpoint", slow_url,
                              "--output-dir", str(self.tmp / "o"), "--poll", "0.05"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        time.sleep(2.5)
        p.send_signal(2)
        out, err = p.communicate(timeout=30)
        slow_httpd.shutdown(); slow_httpd.server_close()
        self.assertEqual(p.returncode, 130, err)
        self.assertIn("h3video fetch video_0001", err)
        self.assertNotIn("Traceback", err)
        job = json.loads(next((self.tmp / "o").glob("*/job.json")).read_text(encoding="utf-8"))
        self.assertEqual(job["status"], "failed"); self.assertIn("중단", job["error"])

    def test_no_command_prints_help(self):
        code, out, _ = run()   # 인자 없이: 빠른 시작 (자주 쓰는 명령 몇 개)
        self.assertEqual(code, 0); self.assertIn("h3video doctor", out); self.assertIn("h3video --help", out)
        code, out, _ = run("--help")
        self.assertEqual(code, 0); self.assertIn("h3video batch", out); self.assertIn("서버·설정", out)


if __name__ == "__main__":
    unittest.main()
