"""웹·CLI 공용 안내: 서버가 꺼졌을 때 할 일, 오류를 쉬운 말로, 작업을 같은 CLI 명령으로 바꾸기."""
from __future__ import annotations

import re
import shlex
import urllib.parse

from . import spec

SERVER_NAME = {"fl2va": "글·그림 서버", "ref2va": "참고 자료 서버"}
TASK_NAME = {"t2va": "글로 만들기", "fl2va": "그림으로 시작", "ref2va": "참고 자료로", "story": "JSON 한번에"}


def port_of(endpoint: str) -> int:
    u = urllib.parse.urlparse(endpoint)
    return u.port or (443 if u.scheme == "https" else 80)


def is_local(endpoint: str) -> bool:
    return (urllib.parse.urlparse(endpoint).hostname or "") in ("127.0.0.1", "localhost", "::1")


def up_command(kind: str) -> str:
    return "bash scripts/up.sh" + (" --ref" if kind == "ref2va" else "")


def tunnel_command(endpoint: str) -> str:
    port = port_of(endpoint)
    return f"ssh -N -L {port}:127.0.0.1:{port} <계정>@<노드>"


def server_hint(kind: str, endpoint: str) -> str:
    """서버가 꺼졌을 때 할 일 한 줄 (웹 화면용)."""
    s = f"{SERVER_NAME[kind]}({endpoint})가 꺼져 있어요 → 클러스터에서 {up_command(kind)} 로 켜세요"
    if is_local(endpoint):
        s += f". PC라면 터널도: {tunnel_command(endpoint)}"
    if kind == "ref2va":
        s += " (참고 자료를 안 쓰면 그냥 두어도 돼요)"
    return s


def explain_error(err: str | None, task: str = "t2va") -> str | None:
    """작업 오류를 쉬운 말 한두 문장으로. 원문은 따로 보여 준다."""
    if not err:
        return None
    e = str(err)
    low = e.lower()
    kind = "ref2va" if task == "ref2va" else "fl2va"
    if "사용자가 중단" in e:
        return "중간에 멈췄어요 (Ctrl+C). 다시 하기를 누르면 처음부터 만들어요."
    if "처리하던 프로세스" in e:
        return "만들던 프로그램(웹 서버나 CLI)이 꺼져서 멈췄어요. 다시 하기를 누르세요."
    if "연결 실패" in e or "연결이 끊겼다" in e or "connection refused" in low:
        return (f"{SERVER_NAME[kind]}에 연결하지 못했어요. 서버를 켜고({up_command(kind)}) 다시 하기를 누르세요.")
    if "out of memory" in low or "oom" in low or "메모리 부족" in e:
        return "GPU 메모리가 모자랐어요. 길이를 줄이거나 '크기'를 576으로 낮춰 다시 해 보세요."
    if "대기 시간 초과" in e:
        return "너무 오래 걸려 기다리기를 멈췄어요. 서버에서는 계속 만들 수 있으니 잠시 뒤 명령어(h3video fetch)로 받으세요."
    if "입력 파일 없음" in e or "찾지 못했다" in e:
        return "올린 파일을 찾지 못했어요. 파일을 다시 넣고 만들어 주세요."
    if "ffmpeg" in low and "pyav" in low:
        return "장면을 이어 붙일 도구(ffmpeg)가 없어요. ffmpeg를 설치하거나 클러스터 환경(source scripts/cluster_env.sh)에서 켜세요."
    if "이어 붙이기 실패" in e:
        return "장면은 다 만들었는데 이어 붙이지 못했어요. ffmpeg가 있는지 확인하세요."
    if re.search(r"HTTP 4\d\d", e):
        return "서버가 이 요청을 받지 않았어요. 아래 원래 메시지를 확인하세요."
    if "생성 실패" in e or "HTTP 5" in e:
        return "서버에서 만들다가 실패했어요. 같은 설정으로 한 번 더 해 보고, 또 안 되면 bash scripts/diagnose.sh 결과를 확인하세요."
    return "만들지 못했어요. 아래 원래 메시지를 확인하세요."


def _q(args: list[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in args)


def job_command(d: dict) -> str:
    """작업(job.to_json()) → 같은 영상을 만드는 h3video 명령."""
    prompt = str(d.get("prompt") or "")
    args = ["h3video", "gen"]
    if not prompt.startswith("-"):
        args.append(prompt)
    args += ["-s", str(d.get("total_seconds") or 8)]
    if d.get("aspect_ratio") and d["aspect_ratio"] != "16:9":
        args += ["-r", d["aspect_ratio"]]
    args += ["--seed", str(d.get("seed") or 0)]
    if d.get("short_edge") and int(d["short_edge"]) != spec.SHORT_EDGE_DEFAULT:
        args += ["--size", str(d["short_edge"])]
    if d.get("scene_seconds") and int(d["scene_seconds"]) != 10:
        args += ["--scene-seconds", str(d["scene_seconds"])]
    if d.get("steps"):
        args += ["--steps", str(d["steps"])]
    if d.get("negative"):
        args += ["-n", d["negative"]]
    if d.get("raw"):
        args.append("--raw")
    if d.get("title"):
        args += ["-t", d["title"]]
    if d.get("first_image"):
        args += ["--first", d["first_image"]]
    if d.get("last_image"):
        args += ["--last", d["last_image"]]
    for r in d.get("refs") or []:
        t = r.get("type")
        if t in ("image", "video", "audio"):
            args += [f"--{t}", r.get("path", "")]
    if prompt.startswith("-"):
        args += ["--", prompt]
    return _q(args)


def story_commands(state: dict, name: str, output_dir: str | None = None) -> dict:
    """JSON 한번에 기록 → {"make": 처음부터 같은 명령(올린 JSON·그림이 있을 때), "resume": 안 된 장면만 다시}."""
    out = ["--output-dir", output_dir] if output_dir else []
    inp = state.get("input") or {}
    make = None
    if inp.get("json"):
        p = state.get("params") or {}
        args = ["h3video", "json", inp["json"]] + ([inp["images"]] if inp.get("images") else [])
        if state.get("ratio"):
            args += ["-r", state["ratio"]]
        if p.get("seed") is not None:
            args += ["--seed", str(p["seed"])]
        if p.get("size") and int(p["size"]) != spec.SHORT_EDGE_DEFAULT:
            args += ["--size", str(p["size"])]
        if p.get("narration") is False:
            args.append("--no-narration")
        make = _q(args + out)
    return {"make": make, "resume": _q(["h3video", "json", "--resume", name] + out)}
