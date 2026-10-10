"""이 계정이 전에 띄운 H3 서버·워커 중 GPU 를 잡고 남은 프로세스를 찾는다. --kill 이면 끄고 GPU 를 반환한다.

'우리 것' = 내 계정 프로세스이면서 GPU 장치(/dev/nvidia*)를 열고 있고,
  ① 환경에 cluster_env.sh 표시(H3_PORT_FL2VA)가 있거나 ② 명령줄에 sglang·h3video·MiniMax-H3 가 들어 있는 것.
컨테이너에서는 nvidia-smi 가 프로세스를 못 보여 주므로 /proc 으로 찾는다. 다른 계정·다른 작업은 건드리지 않는다.

  python scripts/h3_leftovers.py            찾기만
  python scripts/h3_leftovers.py --kill     끄기 (TERM → 30초 뒤 KILL)
"""
import argparse
import os
import re
import signal
import sys
import time

DEV = os.environ.get("H3_LEFTOVER_DEV_PREFIX", "/dev/nvidia")   # 테스트에서만 바꾼다
NAME = re.compile(r"sglang|h3video|MiniMax-H3|minimax-h3-video", re.I)


def read(pid, name):
    with open(f"/proc/{pid}/{name}", "rb") as f:
        return f.read()


def is_alive(pid):
    try:
        return read(pid, "stat").rsplit(b")", 1)[1].split()[0] != b"Z"   # 좀비는 이미 꺼진 것
    except (OSError, IndexError):
        return False


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            pid = int(read(pid, "stat").rsplit(b")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def find(exclude=()):
    me, skip, found = os.getuid(), ancestors() | set(exclude), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in skip:
            continue
        pid = int(d)
        try:
            if os.stat(f"/proc/{pid}").st_uid != me:
                continue
            devs = set()
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    t = os.readlink(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if t.startswith(DEV):
                    devs.add(t[len(DEV):] or "?")
            if not devs:
                continue
            cmd = read(pid, "cmdline").replace(b"\0", b" ").decode(errors="replace").strip()
            env = read(pid, "environ").split(b"\0")
            if any(e.startswith(b"H3_PORT_FL2VA=") for e in env) or NAME.search(cmd):
                gpus = sorted(x for x in devs if x.isdigit())
                found.append((pid, gpus, cmd[:150]))
        except OSError:
            continue
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kill", action="store_true")
    ap.add_argument("--exclude", type=int, nargs="*", default=[])
    a = ap.parse_args()
    procs = find(a.exclude)
    if not procs:
        print("[leftover] 남은 H3 서버 프로세스 없음")
        return 0
    print(f"[leftover] GPU 를 잡고 남은 H3 서버 프로세스 {len(procs)}개:")
    for pid, gpus, cmd in procs:
        print(f"   pid {pid}  GPU 장치 {','.join(gpus) or '-'}  {cmd}")
    if not a.kill:
        return 1
    pids = [p for p, _, _ in procs]
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(30):
        alive = [p for p in pids if is_alive(p)]
        if not alive:
            break
        time.sleep(1)
    else:
        print(f"[leftover] 30초 안에 안 꺼져 강제 종료: {alive}")
        for p in alive:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(2)
    print("[leftover] 내렸다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
