"""scripts/h3_leftovers.py: 다시 띄울 때 이 레포의 서버 묶음만 내리고, 다른 GPU 작업·클라이언트·셸은 건드리지 않는다."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLEEP = "import os, time\nfs = [open(p) for p in os.environ.get('HOLD', '').split(':') if p]\ntime.sleep(60)\n"   # 파일을 열어 둔 채로


@unittest.skipUnless(sys.platform.startswith("linux"), "/proc 필요")
class Leftovers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        for m in ("h3video/__init__", "h3video/dserver", "h3video/dworker", "h3video/cli",
                  "torch/__init__", "torch/distributed/__init__", "torch/distributed/run"):
            (self.d / f"{m}.py").parent.mkdir(parents=True, exist_ok=True)
            (self.d / f"{m}.py").write_text(SLEEP)
        (self.d / "scripts").mkdir()
        (self.d / "scripts/serve.sh").write_text("sleep 60\n")
        (self.d / "train.py").write_text(SLEEP)
        (self.d / "fakenv0").touch()
        self.procs = {}

    def tearDown(self):
        for p in self.procs.values():
            p.kill()
            p.wait()
        self.tmp.cleanup()

    def spawn(self, name, argv, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("H3_")}
        e.update(PYTHONPATH=str(self.d), **env)
        self.procs[name] = subprocess.Popen(argv, env=e, cwd=self.d)

    def run_tool(self, *args):
        env = dict(os.environ, H3_LEFTOVER_DEV_PREFIX=str(self.d / "fakenv"))
        return subprocess.run([sys.executable, str(ROOT / "scripts/h3_leftovers.py"), *args], env=env,
                              capture_output=True, text=True).stdout

    def test_restart_takes_down_whole_stack_only(self):
        py = sys.executable
        self.spawn("server", [py, "-m", "h3video.dserver", "--variant", "fl2va"])
        self.spawn("torchrun", [py, "-m", "torch.distributed.run", "--nproc_per_node", "3", "-m", "h3video.dworker"])
        self.spawn("web", [py, "-m", "h3video.cli", "web", "--port", "8790"])
        self.spawn("serve", ["bash", str(self.d / "scripts/serve.sh"), "fl2va"])
        self.spawn("served-gpu", [py, str(self.d / "train.py")], H3_SERVE_ID="fl2va-1", HOLD=str(self.d / "fakenv0"))
        self.spawn("other-gpu", [py, str(self.d / "train.py")], H3_PORT_FL2VA="30010", HOLD=str(self.d / "fakenv0"))
        self.spawn("client", [py, "-m", "h3video.cli", "gen", "여우", "-s", "8"])
        self.spawn("shell-with-text", ["bash", "-c", "sleep 60 # h3video.dserver torch.distributed.run h3video scripts/serve.sh"])
        time.sleep(1.5)
        out = self.run_tool("--all")
        pid = {k: p.pid for k, p in self.procs.items()}
        for k in ("server", "torchrun", "web", "serve", "served-gpu"):
            self.assertIn(f"pid {pid[k]} ", out, k)
        for k in ("other-gpu", "client", "shell-with-text"):
            self.assertNotIn(f"pid {pid[k]} ", out, k)
        users = self.run_tool("--gpu-users")   # GPU 를 잡은 내 프로세스는 무엇이든 보여 준다
        self.assertIn(f"pid {pid['other-gpu']} ", users)


if __name__ == "__main__":
    unittest.main()
