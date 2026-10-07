"""타임라인·배치 계획 — src/core/plan.js 를 한 줄씩 옮긴 것. 둘은 같은 숫자를 내야 한다(tests 의 parity 검사)."""
from __future__ import annotations

import math
import re

FPS = 30
TEMPLATES = ["cutaway", "split", "pip", "montage"]
TEMPLATE_KO = {"cutaway": "컷어웨이", "split": "위아래 분할", "pip": "PIP", "montage": "몽타주", "base": "기본 영상만"}
CUTAWAY_MAX_SHARE = 0.6
MAX_SEGMENTS = 240


def js_round(x: float) -> int:
    """JS Math.round 와 같은 반올림(파이썬 round 는 짝수 반올림이라 쓰지 않는다)."""
    return int(math.floor(x + 0.5))


def r3(x: float) -> float:
    return js_round(x * 1000) / 1000


def even(x: float) -> int:
    return 2 * js_round(x / 2)


def parse_resolution(r: str) -> tuple[int, int]:
    w, h = str(r).split("x")
    return int(w), int(h)


def eff_range(media: dict, info: dict) -> dict:
    start = min(max(media.get("start") or 0, 0), info["duration"])
    end = info["duration"] if media.get("end") is None else min(media["end"], info["duration"])
    return {"start": r3(start), "dur": r3(max(0, end - start))}


def fit_geometry(src_w: int, src_h: int, rect: dict) -> dict:
    sc = max(rect["w"] / src_w, rect["h"] / src_h)
    sw = min(src_w, even(rect["w"] / sc))
    sh = min(src_h, even(rect["h"] / sc))
    cover = {"sx": math.floor((src_w - sw) / 2), "sy": math.floor((src_h - sh) / 2), "sw": sw, "sh": sh}
    sc2 = min(rect["w"] / src_w, rect["h"] / src_h)
    cw = min(rect["w"], even(src_w * sc2))
    ch = min(rect["h"], even(src_h * sc2))
    contain = {"x": rect["x"] + math.floor((rect["w"] - cw) / 2), "y": rect["y"] + math.floor((rect["h"] - ch) / 2), "w": cw, "h": ch}
    return {"cover": cover, "contain": contain}


def _segment(kind, index, t0, t1, src, rect, fit, info, z, border=0):
    geom = fit_geometry(info["width"], info["height"], rect)
    eff = "blur" if fit == "blur" and (geom["contain"]["w"] < rect["w"] - 2 or geom["contain"]["h"] < rect["h"] - 2) else "crop"
    return {"kind": kind, "index": index, "t0": t0, "t1": t1, "src": src, "rect": rect, "fit": eff,
            "srcW": info["width"], "srcH": info["height"], "cover": geom["cover"], "contain": geom["contain"], "z": z, "border": border}


# ---------- 자막·제목 ----------
def is_wide(code: int) -> bool:
    return ((0x1100 <= code <= 0x115F) or (0x2E80 <= code <= 0xA4CF) or (0xAC00 <= code <= 0xD7A3)
            or (0xF900 <= code <= 0xFAFF) or (0xFE30 <= code <= 0xFE4F) or (0xFF00 <= code <= 0xFF60)
            or (0xFFE0 <= code <= 0xFFE6) or code >= 0x1F300)


def char_units(ch: str) -> float:
    code = ord(ch)
    if ch in (" ", "\t"):
        return 0.3
    if is_wide(code):
        return 1.0
    if 0x41 <= code <= 0x5A or 0x30 <= code <= 0x39:
        return 0.62
    return 0.56


def text_units(s: str) -> float:
    u = 0.0
    for ch in s:
        u += char_units(ch)
    return u


def wrap_text(text: str, font_size: float, max_width: float, max_lines: int) -> list[str]:
    limit = max_width / font_size
    words = [w for w in str(text).strip().split() if w]
    lines: list[str] = []
    cur, cur_u = "", 0.0

    def push_chars(word):
        nonlocal cur, cur_u
        for ch in word:
            u = char_units(ch)
            if cur and cur_u + u > limit:
                lines.append(cur)
                cur, cur_u = "", 0.0
            cur += ch
            cur_u += u

    for w in words:
        wu = text_units(w)
        if not cur:
            if wu <= limit:
                cur, cur_u = w, wu
            else:
                push_chars(w)
        elif cur_u + 0.3 + wu <= limit:
            cur += " " + w
            cur_u += 0.3 + wu
        else:
            lines.append(cur)
            cur, cur_u = "", 0.0
            if wu <= limit:
                cur, cur_u = w, wu
            else:
                push_chars(w)
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        chars = list(kept[max_lines - 1])
        while chars and text_units("".join(chars)) + 1 > limit:
            chars.pop()
        kept[max_lines - 1] = "".join(chars) + "…"
        return kept
    return lines


def count_chars(text: str) -> int:
    return len(re.sub(r"\s", "", str(text)))


def time_captions(captions: list, T: float) -> list[dict]:
    items = [{"text": c} if isinstance(c, str) else c for c in captions]
    weights = [2 + count_chars(c["text"]) for c in items]
    total = sum(weights)
    out = []
    acc = 0
    for i, c in enumerate(items):
        start = r3(T * acc / total)
        acc += weights[i]
        end = r3(T * acc / total)
        if c.get("start") is not None:
            start = r3(min(max(c["start"], 0), T))
        if c.get("end") is not None:
            end = r3(min(max(c["end"], 0), T))
        if end - start >= 0.05:
            out.append({"text": c["text"], "start": start, "end": end, "auto": c.get("start") is None and c.get("end") is None})
    return out


def text_style(W: int, H: int, template: str) -> dict:
    cap_fs = even(W * 0.056)
    title_fs = even(W * 0.07)
    return {
        "caption": {"fontSize": cap_fs, "lineHeight": js_round(cap_fs * 1.28), "maxWidth": js_round(W * 0.86),
                    "centerY": js_round(H * 0.5) if template == "split" else js_round(H * 0.74), "maxLines": 3,
                    "border": max(2, js_round(W * 0.0075)), "color": "#ffffff", "borderColor": "#000000"},
        "title": {"fontSize": title_fs, "lineHeight": js_round(title_fs * 1.25), "maxWidth": js_round(W * 0.88),
                  "top": js_round(H * 0.065), "pad": js_round(title_fs * 0.3), "gap": js_round(title_fs * 0.12),
                  "maxLines": 2, "color": "#ffe14d", "box": "rgba(0,0,0,0.6)"},
    }


def layout_caption(text: str, W: int, st: dict) -> list[dict]:
    lines = wrap_text(text, st["fontSize"], st["maxWidth"], st["maxLines"])
    n = len(lines)
    first = st["centerY"] - ((n - 1) * st["lineHeight"]) / 2
    return [{"text": t, "cx": js_round(W / 2), "cy": js_round(first + i * st["lineHeight"])} for i, t in enumerate(lines)]


def layout_title(text, W: int, st: dict) -> list[dict]:
    if not text or not str(text).strip():
        return []
    lines = wrap_text(text, st["fontSize"], st["maxWidth"], st["maxLines"])
    step = st["lineHeight"] + 2 * st["pad"] + st["gap"]
    return [{"text": t, "cx": js_round(W / 2), "cy": js_round(st["top"] + st["pad"] + st["lineHeight"] / 2 + i * step)}
            for i, t in enumerate(lines)]


# ---------- 타임라인 ----------
def plan_timeline(spec: dict, inputs: dict) -> dict:
    W, H = parse_resolution(spec["resolution"])
    warnings: list[str] = []
    ov = spec["original_volume"]
    full = {"x": 0, "y": 0, "w": W, "h": H}
    base = None
    if inputs.get("base"):
        base = dict(eff_range(inputs["base"]["media"], inputs["base"]["info"]), info=inputs["base"]["info"])
    clips = []
    for i, c in enumerate(inputs["clips"]):
        r = eff_range(c["media"], c["info"])
        if r["dur"] >= 0.1 and c["info"]["width"] > 0:
            clips.append(dict(r, info=c["info"], index=i))
        else:
            warnings.append(f"소스 {i + 1}: 길이가 너무 짧거나 영상이 없어 뺍니다")
    template = spec["template"]
    if not base and template != "montage":
        warnings.append(f"기본 영상(base)이 없어 '{template}' 대신 몽타주로 만듭니다")
        template = "montage"
    if base and not clips:
        template = "base"
    if not base and not clips:
        raise ValueError("합성할 영상이 없습니다")
    sum_clips = 0
    for c in clips:
        sum_clips += c["dur"]
    T = min(spec["max_duration"], sum_clips) if template == "montage" else min(spec["max_duration"], base["dur"])
    T = r3(T)
    segments: list[dict] = []
    audio: list[dict] = []

    def base_audio():
        if base and base["info"]["hasAudio"]:
            audio.append({"kind": "base", "index": 0, "t0": 0, "t1": T, "src": base["start"], "gain": ov, "loop": False})

    def sequential(rect, z, loop, border):
        t, i = 0, 0
        while t < T - 0.05 and len(segments) < MAX_SEGMENTS:
            if not loop and i >= len(clips):
                break
            c = clips[i % len(clips)]
            d = min(c["dur"], T - t)
            t1 = r3(t + d)
            segments.append(_segment("clip", c["index"], r3(t), t1, c["start"], rect, spec["fit"], c["info"], z, border))
            t = t1
            i += 1

    if template == "base":
        segments.append(_segment("base", 0, 0, T, base["start"], full, spec["fit"], base["info"], 0))
        base_audio()
    elif template == "cutaway":
        segments.append(_segment("base", 0, 0, T, base["start"], full, spec["fit"], base["info"], 0))
        base_audio()
        durs = [c["dur"] for c in clips]
        C = 0
        for d in durs:
            C += d
        cap = T * CUTAWAY_MAX_SHARE
        if C > cap:
            durs = [r3(d * cap / C) for d in durs]
        used = 0
        for d in durs:
            used += d
        gap = (T - used) / (len(clips) + 1)
        acc = 0
        for i, c in enumerate(clips):
            t0 = r3(gap * (i + 1) + acc)
            acc += durs[i]
            t1 = r3(min(T, t0 + durs[i]))
            if t1 - t0 >= 0.05:
                segments.append(_segment("clip", c["index"], t0, t1, c["start"], full, spec["fit"], c["info"], 1))
    elif template == "split":
        half = even(H / 2)
        segments.append(_segment("base", 0, 0, T, base["start"], {"x": 0, "y": 0, "w": W, "h": half}, spec["fit"], base["info"], 0))
        sequential({"x": 0, "y": half, "w": W, "h": H - half}, 1, True, 0)
        base_audio()
    elif template == "pip":
        segments.append(_segment("base", 0, 0, T, base["start"], full, spec["fit"], base["info"], 0))
        pw = even(W * 0.42)
        ph = even(pw * 9 / 16)
        rect = {"x": W - pw - js_round(W * 0.045), "y": js_round(H * 0.24), "w": pw, "h": ph}
        sequential(rect, 1, True, max(2, js_round(W * 0.006)))
        base_audio()
    else:
        sequential(full, 0, False, 0)
        if base and base["info"]["hasAudio"]:
            base_audio()
        else:
            for s in segments:
                c = next(x for x in clips if x["index"] == s["index"])
                if c["info"]["hasAudio"]:
                    audio.append({"kind": "clip", "index": s["index"], "t0": s["t0"], "t1": s["t1"], "src": s["src"], "gain": ov, "loop": False})
    if inputs.get("bgm") and spec["bgm_volume"] > 0:
        audio.append({"kind": "bgm", "index": 0, "t0": 0, "t1": T, "src": 0, "gain": spec["bgm_volume"], "loop": True})
    style = text_style(W, H, template)
    captions = [dict(c, lines=layout_caption(c["text"], W, style["caption"])) for c in time_captions(spec.get("captions") or [], T)]
    title = layout_title(spec.get("title"), W, style["title"])
    return {"width": W, "height": H, "fps": FPS, "duration": T, "template": template, "segments": segments, "audio": audio,
            "captions": captions, "title": title, "style": style, "warnings": warnings}


def describe_plan(plan: dict) -> str:
    segs = sum(1 for s in plan["segments"] if s["kind"] == "clip")
    return (f"{TEMPLATE_KO[plan['template']]} · {plan['width']}×{plan['height']} · {plan['duration']:.1f}초 · "
            f"소스 구간 {segs}개 · 자막 {len(plan['captions'])}줄")
