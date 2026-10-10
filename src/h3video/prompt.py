"""H3-Context-IR 형식의 프롬프트 빌더.

공식 파이프라인은 짧은 사용자 프롬프트를 H3-Context-IR(API 전용)로 확장한 뒤 H3-Base 에 넣는다.
로컬만 쓸 때는 같은 3단 구조(integrated_multimodal_description / overall_soundscape /
non_diegetic_music)로 직접 써 주면 품질이 크게 오른다. 짧은 프롬프트도 그대로 동작은 한다.
"""
from __future__ import annotations

import re

SECTIONS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")


def is_context_ir(prompt: str) -> bool:
    return any(prompt.lstrip().startswith(s + ":") or f"\n{s}:" in prompt for s in SECTIONS)


def build_context_ir(description: str, soundscape: str | None = None, music: str | None = None,
                     keyframe_note: str | None = None) -> str:
    parts = []
    if keyframe_note:
        parts.append(keyframe_note.strip() + "\n")
    parts.append(f"integrated_multimodal_description: {description.strip()}")
    parts.append(f"overall_soundscape: {(soundscape or '장면에 자연스럽게 어울리는 환경음과 효과음.').strip()}")
    parts.append(f"non_diegetic_music: {(music or '장면 분위기에 맞는 잔잔한 배경음악.').strip()}")
    return "\n".join(parts)


def keyframe_note(first: bool = True, last: bool = False, seconds: float = 8.0, shots: int = 1) -> str:
    """키프레임 정렬 줄 — 공식 가이드 2.1 의 문구 그대로 (I2VA·FL2VA·L2VA). Diffusers 서버는 실제 길이로 다시 계산해 붙인다."""
    from .rewrite import instruction
    slots = (["image"] if first else []) + (["last_image"] if last else [])
    return instruction(slots, float(seconds), shots) or ""


_SHOT = re.compile(r"\[Shot (\d+)\]")
_AT = re.compile(r"^\s*At (\d+):(\d+(?:\.\d+)?),\s*")
_CUT = re.compile(r"^(the camera|the shot) (cuts|transitions|changes|switches) to\s+", re.I)


def split_fields(text: str) -> dict | None:
    """공식 형식(3단)이면 {필드: 내용}. 맨 앞의 키프레임 정렬 줄은 버린다 (장면마다 다시 붙는다)."""
    if not is_context_ir(text):
        return None
    pos = []
    for s in SECTIONS:
        m = re.search(rf"(^|\n)\s*{s}\s*:", text)
        if m is None:
            return None
        pos.append((m.end(), m.start() + len(m.group(1)), s))
    pos.sort()
    out = {}
    for i, (body_start, _, name) in enumerate(pos):
        end = pos[i + 1][1] if i + 1 < len(pos) else len(text)
        out[name] = text[body_start:end].strip()
    return out


def _fmt(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:06.3f}"


def scene_prompts(description: str, durations: list[int] | int, rewrite: bool = True) -> list[str]:
    """장면 체인(16초 이상)용: 한 프롬프트를 장면들로 나눈다.

    - 공식 형식(3단)이면 integrated_multimodal_description 의 샷을 시작 시각(`At mm:ss.sss`)으로 장면에 나누고,
      장면마다 샷 번호를 1부터·시각을 장면 시작 기준으로 다시 매긴다. 소리·음악 칸은 모든 장면에 그대로 넣는다.
      어떤 장면에 시작하는 샷이 없으면 그 시각에 이어지던 샷을 넣는다.
    - 그냥 글이면 원문 그대로, 서버가 다듬을 때 쓰라고 몇 번째 장면·몇 초 부분인지만 덧붙인다 (rewrite=False 면 원문만).
    """
    if isinstance(durations, int):   # 예전 호출(장면 수만): 10초씩으로 본다
        durations = [10] * durations
    n = len(durations)
    starts = [sum(durations[:i]) for i in range(n)]
    total = sum(durations)
    f = split_fields(description)
    if f is None:
        if not rewrite:
            return [description.strip()] * n
        return [f"{description.strip()}\n\n(전체 {total}초 영상을 {n}개 장면으로 나눠 만든다. 이 요청은 {i + 1}번째 장면, "
                f"전체의 {starts[i]}~{starts[i] + durations[i]}초 부분만 그린다"
                + (". 앞 장면의 마지막 모습에서 바로 이어진다)" if i else ")")
                for i in range(n)]
    parts = [p.strip() for p in _SHOT.split(f["integrated_multimodal_description"])]
    # split 결과: [앞부분, 번호, 내용, 번호, 내용, ...]
    shots = []
    for k in range(1, len(parts) - 1, 2):
        text = parts[k + 1]
        m = _AT.match(text)
        t0 = float(m.group(1)) * 60 + float(m.group(2)) if m else (shots[-1][0] if shots else 0.0)
        shots.append((0.0 if not shots else t0, _AT.sub("", text, count=1)))
    if not shots:
        shots = [(0.0, f["integrated_multimodal_description"])]
    out = []
    for i in range(n):
        a, b = starts[i], starts[i] + durations[i]
        inside = [(t, s) for t, s in shots if a <= t < b]
        before = [(t, s) for t, s in shots if t < a]
        # 장면 시작 시각에 이어지던 샷이 있으면 그것을 첫 샷으로 (그 샷이 장면 안에서 끝날 때까지)
        mine = ([before[-1]] if before and (not inside or inside[0][0] > a) else []) + inside or [shots[0]]
        lines = []
        for j, (t, s) in enumerate(mine, 1):
            if j == 1:   # 장면의 첫 샷에는 시각을 쓰지 않는다 (가이드 4.2)
                s = _CUT.sub("", s, count=1)
                lines.append(f"[Shot 1] {s[:1].upper()}{s[1:]}")
            else:
                lines.append(f"[Shot {j}] At {_fmt(t - a)}, {s}")
        out.append(f"integrated_multimodal_description: {' '.join(lines)}\n\n"
                   f"overall_soundscape: {f['overall_soundscape']}\n\nnon_diegetic_music: {f['non_diegetic_music']}")
    return out
