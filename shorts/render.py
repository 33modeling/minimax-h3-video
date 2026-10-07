"""계획(plan)을 ffmpeg 명령 하나로 옮긴다. 배치 숫자는 전부 plan 에서 오고, 여기서는 그리는 방법만 정한다.
웹(src/render/draw.js)과 같은 규칙: 흐린 배경 = 1/16 축소 후 확대 + 30% 어둡게, PIP 테두리 = 흰색, 자막 = 흰 글씨 검은 테두리."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

BLUR_DIV = 16
DARKEN = 0.7


class RenderError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    ff = os.environ.get("SHORTS_FFMPEG") or shutil.which("ffmpeg")
    if not ff:
        raise RenderError("ffmpeg 가 없습니다. 설치하세요: sudo apt install ffmpeg (macOS: brew install ffmpeg, Windows: winget install ffmpeg)")
    return ff


def ffprobe_bin() -> str:
    fp = os.environ.get("SHORTS_FFPROBE") or shutil.which("ffprobe")
    if not fp:
        raise RenderError("ffprobe 가 없습니다. ffmpeg 패키지를 설치하면 함께 들어옵니다")
    return fp


def find_font() -> str:
    env = os.environ.get("SHORTS_FONT")
    if env:
        return env
    fc = shutil.which("fc-match")
    if fc:
        for q in ("Noto Sans CJK KR:bold", "Noto Sans KR:bold", "NanumGothic:bold", "Malgun Gothic:bold"):
            r = subprocess.run([fc, "-f", "%{file}", q], capture_output=True, text=True)
            f = r.stdout.strip()
            if r.returncode == 0 and f and Path(f).is_file() and ("CJK" in f or "KR" in f or "Nanum" in f or "malgun" in f.lower()):
                return f
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "C:/Windows/Fonts/malgunbd.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc"):
        if Path(f).is_file():
            return f
    raise RenderError("한글 글꼴을 찾지 못했습니다. SHORTS_FONT=/경로/글꼴.ttf 로 지정하세요 (예: Noto Sans CJK)")


def probe(path: str) -> dict:
    """ffprobe 로 길이·크기·오디오 유무를 읽는다."""
    import json
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,width,height,duration:stream_side_data=rotation",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RenderError(f"영상 정보를 읽지 못했습니다: {path} ({r.stderr.strip()[:200]})")
    d = json.loads(r.stdout or "{}")
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0)
    w, h = (int(v.get("width", 0)), int(v.get("height", 0))) if v else (0, 0)
    rot = 0
    for sd in (v or {}).get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if abs(rot) in (90, 270):
        w, h = h, w
    return {"duration": round(dur, 3), "width": w, "height": h, "hasAudio": a is not None, "hasVideo": v is not None}


def _esc_path(p: str) -> str:
    # filtergraph 안 옵션 값: \ : ' 를 이스케이프
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _seg_chain(seg: dict, label_in: str, label_out: str, idx: int, fps: int = 30) -> list[str]:
    r, cov, con = seg["rect"], seg["cover"], seg["contain"]
    dur = seg["t1"] - seg["t0"]
    head = f"[{label_in}]fps={fps},trim=duration={dur:.3f},setpts=PTS-STARTPTS"
    crop = f"crop={cov['sw']}:{cov['sh']}:{cov['sx']}:{cov['sy']}"
    shift = f"setpts=PTS+{seg['t0']:.3f}/TB"
    out: list[str] = []
    b = seg.get("border") or 0
    if seg["fit"] == "blur":
        bw, bh = max(2, r["w"] // BLUR_DIV), max(2, r["h"] // BLUR_DIV)
        out.append(f"{head},split=2[sa{idx}][sb{idx}]")
        out.append(f"[sa{idx}]{crop},scale={bw}:{bh},scale={r['w']}:{r['h']}:flags=bilinear,"
                   f"colorchannelmixer=rr={DARKEN}:gg={DARKEN}:bb={DARKEN},setsar=1[bg{idx}]")
        out.append(f"[sb{idx}]scale={con['w']}:{con['h']},setsar=1[fg{idx}]")
        tail = f",pad={r['w'] + 2 * b}:{r['h'] + 2 * b}:{b}:{b}:color=white" if b else ""
        out.append(f"[bg{idx}][fg{idx}]overlay={con['x'] - r['x']}:{con['y'] - r['y']}:shortest=1{tail},{shift}[{label_out}]")
    else:
        tail = f",pad={r['w'] + 2 * b}:{r['h'] + 2 * b}:{b}:{b}:color=white" if b else ""
        out.append(f"{head},{crop},scale={r['w']}:{r['h']},setsar=1{tail},{shift}[{label_out}]")
    return out


def build_command(plan: dict, paths: dict, out: str, workdir: str, font: str | None = None,
                  crf: int | None = None, preset: str = "veryfast") -> list[str]:
    """paths = {"base": str|None, "clips": [str], "bgm": str|None}. workdir 에 자막 텍스트 파일을 쓴다."""
    W, H, T, fps = plan["width"], plan["height"], plan["duration"], plan["fps"]
    if crf is None:
        crf = (plan.get("quality") or {}).get("crf", 23)
    args = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
            "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={fps}:d={T:.3f}"]
    n_in = 1

    def add_input(path, ss=None, t=None, loop=False):
        nonlocal n_in
        if loop:
            args.extend(["-stream_loop", "-1"])
        if ss is not None and ss > 0:
            args.extend(["-ss", f"{ss:.3f}"])
        if t is not None:
            args.extend(["-t", f"{t:.3f}"])
        args.extend(["-i", str(path)])
        n_in += 1
        return n_in - 1

    def src_path(kind, index):
        return paths["base"] if kind == "base" else paths["bgm"] if kind == "bgm" else paths["clips"][index]

    fg: list[str] = ["[0:v]setsar=1,format=yuv420p[cv0]"]
    cur = "cv0"
    order = sorted(range(len(plan["segments"])), key=lambda i: (plan["segments"][i]["z"], plan["segments"][i]["t0"]))
    for k, si in enumerate(order):
        seg = plan["segments"][si]
        dur = seg["t1"] - seg["t0"]
        ii = add_input(src_path(seg["kind"], seg["index"]), seg["src"], dur + 0.1)
        fg.extend(_seg_chain(seg, f"{ii}:v", f"s{k}", k, fps))
        b = seg.get("border") or 0
        x, y = seg["rect"]["x"] - b, seg["rect"]["y"] - b
        nxt = f"cv{k + 1}"
        fg.append(f"[{cur}][s{k}]overlay={x}:{y}:eof_action=pass:enable='gte(t,{seg['t0']:.3f})*lt(t,{seg['t1']:.3f})'[{nxt}]")
        cur = nxt
    # 제목·자막: 줄마다 drawtext 하나(웹과 같은 줄바꿈). 글자는 textfile 로 넘겨 이스케이프 문제를 피한다.
    font = font or find_font()
    st = plan["style"]
    draws: list[str] = []
    tdir = Path(workdir)
    tdir.mkdir(parents=True, exist_ok=True)
    nfile = 0

    def text_file(text):
        nonlocal nfile
        nfile += 1
        p = tdir / f"text{nfile:03d}.txt"
        p.write_text(text, encoding="utf-8")
        return _esc_path(str(p.resolve()))

    ts = st["title"]
    for ln in plan["title"]:
        draws.append(f"drawtext=fontfile='{_esc_path(font)}':textfile='{text_file(ln['text'])}':fontsize={ts['fontSize']}:"
                     f"fontcolor=0xffe14d:x=(w-text_w)/2:y={ln['cy']}-{ts['lineHeight']}/2:"
                     f"box=1:boxcolor=black@0.6:boxborderw={ts['pad']}")
    cs = st["caption"]
    for cap in plan["captions"]:
        for ln in cap["lines"]:
            draws.append(f"drawtext=fontfile='{_esc_path(font)}':textfile='{text_file(ln['text'])}':fontsize={cs['fontSize']}:"
                         f"fontcolor=white:borderw={cs['border']}:bordercolor=black:x=(w-text_w)/2:y={ln['cy']}-{cs['lineHeight']}/2:"
                         f"enable='gte(t,{cap['start']:.3f})*lt(t,{cap['end']:.3f})'")
    chain = ",".join(draws + ["format=yuv420p"])
    fg.append(f"[{cur}]{chain}[vout]")
    # 오디오
    alabels = []
    for j, a in enumerate(plan["audio"]):
        if a["kind"] == "bgm":
            ii = add_input(src_path("bgm", 0), None, T, loop=True)
        else:
            ii = add_input(src_path(a["kind"], a["index"]), a["src"], a["t1"] - a["t0"])
        delay = int(round(a["t0"] * 1000))
        chainA = f"[{ii}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={a['gain']}"
        if delay > 0:
            chainA += f",adelay=delays={delay}:all=1"
        fg.append(chainA + f"[a{j}]")
        alabels.append(f"[a{j}]")
    if alabels:
        fg.append("".join(alabels) + f"amix=inputs={len(alabels)}:duration=longest:normalize=0,apad,atrim=0:{T:.3f}[aout]")
    else:
        ii = add_input("anullsrc=r=48000:cl=stereo")
        args[-2:-2] = ["-f", "lavfi"]
        fg.append(f"[{ii}:a]atrim=0:{T:.3f}[aout]")
    args.extend(["-filter_complex", ";".join(fg), "-map", "[vout]", "-map", "[aout]",
                 "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
                 "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                 "-t", f"{T:.3f}", str(out)])
    return args


def run_ffmpeg(args: list[str], duration: float, on_progress: Callable[[float], None] | None = None) -> None:
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if on_progress and duration > 0:
                    on_progress(min(1.0, us / 1e6 / duration))
        err = proc.stderr.read()  # type: ignore[union-attr]
        code = proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        raise
    if code != 0:
        raise RenderError(f"ffmpeg 합성 실패 (코드 {code}): {err.strip()[-800:]}")
    if on_progress:
        on_progress(1.0)


def render(plan: dict, paths: dict, out: str, on_progress=None, font: str | None = None) -> str:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shorts-") as tmp:
        args = build_command(plan, paths, out, tmp, font=font)
        run_ffmpeg(args, plan["duration"], on_progress)
    return out


def extract_frames(path: str, count: int, width: int = 384) -> list[tuple[float, bytes]]:
    """Claude 기획용 작은 JPEG 프레임들(고르게 나눈 시점)."""
    info = probe(path)
    dur = info["duration"] or 1
    out = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                           capture_output=True)
        if r.returncode == 0 and r.stdout:
            out.append((round(t, 2), r.stdout))
    return out


def cut_clip(path: str, start: float, end: float | None, out: str) -> str:
    """참조 영상 구간 자르기(서버에 보낼 때)."""
    args = [ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path)]
    if end is not None:
        args += ["-t", f"{max(0.1, end - start):.3f}"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", out]
    subprocess.run(args, check=True)
    return out
