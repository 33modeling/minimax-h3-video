"""scripts/h3_leftovers.py: serve.sh 가 띄운 서버·워커만 고르고, 같은 셸에서 띄운 다른 GPU 작업은 건드리지 않는다."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOLD = "import sys, time\nfs = [open(p) for p in sys.argv[1:]]\ntime.sleep(60)\n"


@unittest.skipUnless(sys.platform.startswith("linux"), "/proc 필요")
class Leftovers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.dev = d / "fakenv"
        (d / "fakenv0").touch()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        self.tmp.cleanup()

    def spawn(self, script_name, env_extra):
        script = Path(self.tmp.name) / script_name
        script.write_text(HOLD)
        env = {k: v for k, v in os.environ.items() if not k.startswith("H3_")}
        env.update(env_extra)
        p = subprocess.Popen([sys.executable, str(script), f"{self.dev}0"], env=env)
        self.procs.append(p)
        return p.pid

    def find(self):
        env = dict(os.environ, H3_LEFTOVER_DEV_PREFIX=str(self.dev))
        out = subprocess.run([sys.executable, str(ROOT / "scripts/h3_leftovers.py")], env=env, capture_output=True, text=True).stdout
        return out

    def test_only_ours(self):
        served = self.spawn("worker.py", {"H3_SERVE_ID": "fl2va-1", "H3_PORT_FL2VA": "30010"})
        old = self.spawn("h3video.dworker.py", {"H3_PORT_FL2VA": "30010"})          # 예전 워커: 표시 + 명령줄
        other = self.spawn("train.py", {"H3_PORT_FL2VA": "30010"})                   # 같은 셸에서 띄운 다른 GPU 작업
        plain = self.spawn("h3video.dserver.py", {})                                 # 표시가 없는 프로세스
        time.sleep(1)
        out = self.find()
        self.assertIn(f"pid {served}", out)
        self.assertIn(f"pid {old}", out)
        self.assertNotIn(f"pid {other}", out)
        self.assertNotIn(f"pid {plain}", out)


if __name__ == "__main__":
    unittest.main()
