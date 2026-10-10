"""이 계정이 전에 띄운 H3 서버·워커 중 GPU 를 잡고 남은 프로세스를 찾는다. --kill 이면 끄고 GPU 를 반환한다.

'우리 것' = 내 계정 프로세스이면서 GPU 장치(/dev/nvidia*)를 열고 있고,
  ① serve.sh 가 띄운 표시(환경의 H3_SERVE_ID)가 있거나 — 서버·torchrun·워커가 모두 물려받는다
  ② (예전에 띄운 것) cluster_env.sh 표시(H3_PORT_FL2VA)가 있으면서 명령줄이 H3 서버·워커(h3video.dserver/dworker, sglang serve)인 것.
cluster_env.sh 를 source 한 셸에서 띄운 다른 GPU 작업(학습·노트북 등)은 건드리지 않는다.
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
def _module(argv):
    """python … -m <모듈> 의 모듈 이름 (없으면 None)."""
    for i, a in enumerate(argv[:-1]):
        if a == "-m":
            return argv[i + 1]
    return None


def is_server(argv) -> bool:
    """실제로 돌고 있는 것이 H3 서버·워커인가 (명령줄 글자가 아니라 실행 중인 모듈·프로그램으로 판단)."""
    m = _module(argv)
    exe = os.path.basename(argv[0]) if argv else ""
    return (m in ("h3video.dserver", "h3video.dworker") or (m or "").startswith("sglang")
            or (exe == "sglang" and argv[1:2] == ["serve"]) or (argv[0] if argv else "").startswith("sglang::"))


def is_web(argv) -> bool:
    return _module(argv) == "h3video.cli" and "web" in argv


def is_stack(argv) -> bool:
    """--all: GPU 를 안 잡은 것까지 — 서버를 띄운 serve.sh·torchrun·웹 UI."""
    m = _module(argv)
    exe = os.path.basename(argv[0]) if argv else ""
    return (is_server(argv)
            or (m == "torch.distributed.run" and "h3video.dworker" in argv)
            or is_web(argv)
            or (exe in ("bash", "sh") and len(argv) > 1 and argv[1].endswith("scripts/serve.sh")))


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


def argv_of(pid):
    try:
        return [x.decode(errors="replace") for x in read(pid, "cmdline").split(b"\0") if x]
    except OSError:
        return []


def gpu_holders(exclude=()):
    """이 계정에서 GPU 장치를 연 프로세스 전부 (진단용: 무엇이 GPU 를 잡고 있나). [(pid, gpu 번호들, 명령줄)]"""
    me, skip, out = os.getuid(), ancestors() | set(exclude), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in skip:
            continue
        pid = int(d)
        try:
            if os.stat(f"/proc/{pid}").st_uid != me:
                continue
            devs = {os.readlink(f"/proc/{pid}/fd/{fd}") for fd in os.listdir(f"/proc/{pid}/fd")
                    if os.path.islink(f"/proc/{pid}/fd/{fd}")}
            devs = {x[len(DEV):] for x in devs if x.startswith(DEV)}
            if devs:
                cmd = read(pid, "cmdline").replace(b"\0", b" ").decode(errors="replace").strip()
                out.append((pid, sorted(x for x in devs if x.isdigit()), cmd[:150]))
        except OSError:
            continue
    return out


def stack_procs(exclude=()):
    """GPU 를 잡지 않은 것까지 이 레포의 서버 묶음 (serve.sh·torchrun·웹 UI·서버·워커)."""
    me, skip, out = os.getuid(), ancestors() | set(exclude), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in skip:
            continue
        pid = int(d)
        try:
            if os.stat(f"/proc/{pid}").st_uid != me:
                continue
            argv = [x.decode(errors="replace") for x in read(pid, "cmdline").split(b"\0") if x]
            if is_stack(argv) and is_alive(pid):
                out.append((pid, [], " ".join(argv)[:150]))
        except OSError:
            continue
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
            argv = [x.decode(errors="replace") for x in read(pid, "cmdline").split(b"\0") if x]
            mine = any(e.startswith(b"H3_SERVE_ID=") for e in env) or is_server(argv)
            if mine:
                gpus = sorted(x for x in devs if x.isdigit())
                found.append((pid, gpus, cmd[:150]))
        except OSError:
            continue
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kill", action="store_true")
    ap.add_argument("--all", action="store_true", help="GPU 를 안 잡은 serve.sh·torchrun·웹 UI 까지 (다시 띄우기 전에)")
    ap.add_argument("--keep-web", action="store_true", help="웹 UI 는 빼고 (H3 서버만 — up.sh·down.sh)")
    ap.add_argument("--web-only", action="store_true", help="웹 UI 만 (web.sh)")
    ap.add_argument("--gpu-users", action="store_true", help="이 계정에서 GPU 를 잡은 프로세스 전부 보여 주기만")
    ap.add_argument("--exclude", type=int, nargs="*", default=[])
    a = ap.parse_args()
    if a.gpu_users:
        users = gpu_holders(a.exclude)
        if not users:   # 붙여 넣을 때 한글이 지워져도 알 수 있게 영어 표시를 같이 둔다
            print("     (none) 이 계정 프로세스 중 GPU 를 잡은 것은 없다 → 다른 계정·다른 파드가 쓰거나, 비정상 종료로 남은 메모리다")
        for pid, gpus, cmd in users:
            print(f"     pid {pid}  GPU {','.join(gpus) or '-'}  {cmd}")
        import subprocess
        try:
            apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory,process_name", "--format=csv,noheader"],
                                  capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            apps = ""
        print("     nvidia-smi apps: " + ("; ".join(apps.splitlines()) if apps else "(none)"))
        return 0
    procs = find(a.exclude)
    if a.all or a.web_only:
        seen = {p for p, _, _ in procs}
        procs += [x for x in stack_procs(a.exclude) if x[0] not in seen]
    if a.keep_web:
        procs = [x for x in procs if not is_web(argv_of(x[0]))]
    if a.web_only:
        procs = [x for x in procs if is_web(argv_of(x[0]))]
    if not procs:
        print("[leftover] 남은 " + ("웹 UI" if a.web_only else "H3 서버") + " 프로세스 없음")
        return 0
    print(f"[leftover] 남아 있는 " + ("웹 UI" if a.web_only else "H3 서버") + f" 프로세스 {len(procs)}개:")
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
