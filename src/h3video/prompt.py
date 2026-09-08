"""H3-Context-IR 형식의 프롬프트 빌더.

공식 파이프라인은 짧은 사용자 프롬프트를 H3-Context-IR(API 전용)로 확장한 뒤 H3-Base 에 넣는다.
로컬만 쓸 때는 같은 3단 구조(integrated_multimodal_description / overall_soundscape /
non_diegetic_music)로 직접 써 주면 품질이 크게 오른다. 짧은 프롬프트도 그대로 동작은 한다.
"""
from __future__ import annotations

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


def keyframe_note(first: bool = True, last: bool = False) -> str:
    notes = []
    if first:
        notes.append("For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.")
    if last:
        idx = 2 if first else 1
        notes.append(f"At the final frame of the target video, <Picture {idx}> is fully referenced.")
    return "\n".join(notes)


def scene_prompts(description: str, n_scenes: int) -> list[str]:
    """장면 체인용: 한 설명을 n개 장면으로 나눈다. '[Shot k]' 표기가 있으면 그대로 분할, 없으면 동일 설명에 장면 번호를 붙인다."""
    import re
    shots = [s.strip() for s in re.split(r"\[Shot \d+\]", description) if s.strip()]
    if len(shots) >= n_scenes:
        return [f"[Shot 1] {shots[i]}" for i in range(n_scenes)]
    return [f"[Shot 1] {description.strip()} (scene {i + 1} of {n_scenes}, continuous action, same subjects and setting)"
            for i in range(n_scenes)]
