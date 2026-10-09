"""shorts doctor 테스트: 표시·종료 코드·출처 표시·키 비노출·서버 연결(가짜 서버)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_servers as F  # noqa: E402
from shorts import cli  # noqa: E402
from shorts import doctor as D  # noqa: E402
from shorts import render as R  # noqa: E402

CLEAN = {"SHORTS_SERVER": "", "SHORTS_REF_SERVER": "", "H3_ENDPOINT": "", "H3_REF_ENDPOINT": "", "ANTHROPIC_API_KEY": ""}


def doctor(*argv, env=None) -> tuple[int, str]:
    buf = io.StringIO()
    with mock.patch.dict(os.environ, {**CLEAN, **(env or {})}), contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(["doctor", *argv])
    return code, buf.getvalue()


def by_id(out: str) -> dict:
    return {c["id"]: c for c in json.loads(out)["checks"]}


class DoctorTest(unittest.TestCase):
    def test_json_shape_and_key_never_printed(self):
        code, out = doctor("--json", env={"ANTHROPIC_API_KEY": "sk-ant-doctor-secret-123"})
        self.assertNotIn("sk-ant-doctor-secret-123", out)
        c = by_id(out)
        self.assertEqual(c["anthropic"]["status"], "ok")
        for k in ("python", "venv", "ffmpeg", "ffprobe", "drawtext", "font", "h3video", "server-env", "node"):
            self.assertIn(k, c)
        self.assertEqual(c["server-env"]["status"], "warn")  # 서버 주소 없음은 선택 항목
        self.assertEqual(code, 0 if json.loads(out)["ok"] else 1)

    def test_missing_ffmpeg_fails_with_fix_and_exit_1(self):
        def boom():
            raise R.RenderError("ffmpeg 가 없습니다. 설치하세요")
        with mock.patch.object(R, "ffmpeg_bin", boom):
            code, out = doctor()
        self.assertEqual(code, 1)
        self.assertIn("✗ ffmpeg", out)
        self.assertIn("해결: scripts/setup.sh", out)
        self.assertIn("필수 항목", out)

    def test_server_ok_and_unreachable_is_optional(self):
        httpd, _st, url = F.start_video("sglang", steps=1)
        try:
            code, out = doctor("--json", env={"SHORTS_SERVER": url})
            self.assertEqual(by_id(out)["server"]["status"], "ok")
            self.assertIn("sglang", by_id(out)["server"]["detail"])
        finally:
            httpd.shutdown()
        with mock.patch.object(D, "check_ffmpeg", lambda: []), mock.patch.object(D, "check_font", lambda: D._item("font", "font", True, "ok", "x")):
            code, out = doctor("--timeout", "1", env={"H3_ENDPOINT": "http://127.0.0.1:9"})
        self.assertIn("✗ server", out)
        self.assertIn("(선택)", out)
        self.assertEqual(code, 0)  # 서버 연결은 선택 항목 — 합성만 할 수도 있다

    def test_origin_marks_repo_tools(self):
        self.assertEqual(D.origin(R.ROOT / ".tools" / "bin" / "ffmpeg"), ".tools")
        self.assertEqual(D.origin(R.ROOT / ".venv" / "bin" / "python"), ".venv")
        self.assertEqual(D.origin("/usr/bin/ffmpeg"), "시스템")
        with mock.patch.dict(os.environ, {"SHORTS_FFMPEG": "/opt/ff"}):
            self.assertEqual(D.origin("/opt/ff", "SHORTS_FFMPEG"), "SHORTS_FFMPEG")

    def test_local_tools_win_over_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ff = Path(d) / "bin" / "ffmpeg"
            ff.parent.mkdir()
            ff.write_text("#!/bin/sh\n")
            ff.chmod(0o755)
            with mock.patch.object(R, "TOOLS", Path(d)), mock.patch.dict(os.environ, {"SHORTS_FFMPEG": ""}):
                self.assertEqual(R.ffmpeg_bin(), str(ff))

    def test_node_version_range(self):
        r = "^20.19.0 || >=22.12.0"
        self.assertTrue(D.version_ok("20.19.0", r))
        self.assertTrue(D.version_ok("24.1.0", r))
        self.assertFalse(D.version_ok("20.18.3", r))
        self.assertFalse(D.version_ok("22.11.0", r))
        self.assertFalse(D.version_ok("21.9.0", r))


if __name__ == "__main__":
    unittest.main()


class EnvShTest(unittest.TestCase):
    """scripts/env.sh: 켜고 끄면 PATH·VIRTUAL_ENV 가 원래대로(bash·zsh)."""

    def test_off_restores_previously_active_venv(self):
        """다른 venv 가 켜진 셸에서 켰다 끄면 그 venv 가 사라지던 버그(PATH·VIRTUAL_ENV·deactivate)."""
        import shutil
        import subprocess
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="shorts-envsh-"))
        try:
            for name in ("other", "mine"):
                subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp / name)], check=True)
            script = f"""
source '{tmp / "other" / "bin" / "activate"}'
before="$PATH"; bv="$VIRTUAL_ENV"
export SHORTS_VENV='{tmp / "mine"}'
source '{ROOT / "scripts" / "env.sh"}' >/dev/null
[ "$VIRTUAL_ENV" = '{tmp / "mine"}' ] || echo FAIL-on
shorts-env-off >/dev/null
[ "$PATH" = "$before" ] || echo FAIL-path
[ "$VIRTUAL_ENV" = "$bv" ] || echo FAIL-venv
command -v deactivate >/dev/null 2>&1 || echo FAIL-deactivate
deactivate; before2="$PATH"
source '{ROOT / "scripts" / "env.sh"}' >/dev/null; source '{ROOT / "scripts" / "env.sh"}' >/dev/null; deactivate >/dev/null
[ "$PATH" = "$before2" ] || echo FAIL-twice
echo DONE
"""
            for sh in ("bash", "zsh"):
                if not shutil.which(sh):
                    continue
                r = subprocess.run([sh, "-c", script], capture_output=True, text=True, env={**os.environ, "SHORTS_VENV": ""})
                self.assertIn("DONE", r.stdout, (sh, r.stdout, r.stderr))
                self.assertNotIn("FAIL", r.stdout, (sh, r.stdout, r.stderr))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
