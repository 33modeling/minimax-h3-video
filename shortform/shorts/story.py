"""JSON 한번에: 동화책 콘티·동화책 만들기 book.json·장면 목록(clips) JSON + 쪽 그림 → 숏폼 명세.

장면 수·길이·프롬프트·그림 맞추기는 h3video 의 story.py(`h3video json` 과 같은 규칙)로 정하고,
여기서는 숏폼 명세(scenes·자막·제목)로 옮긴다. 웹은 src/core/story.js 가 같은 일을 한다
(tests/fixtures/story/ 의 기대 결과로 두 쪽이 같은지 확인한다).
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

MAX_TOTAL = float("inf")          # 숏폼 최대 길이(명세 max_duration 상한)
CAPTION_MAX = 120        # 자막 한 줄 최대 글자 (명세 captions 한도)


def _h3story():
    try:
        from h3video import story  # type: ignore
    except ImportError:   # pip install -e . 없이 레포에서 바로 쓸 때
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from h3video import story  # type: ignore
    return story


def is_story(data) -> bool:
    """숏폼 명세가 아니라 이야기 JSON 인가: 동화책 콘티, 동화책 만들기 book.json, 장면 목록(clips·배열)."""
    st = _h3story()
    if isinstance(data, list):   # 배열은 장면 목록일 때만 (["프롬프트", {"prompt": ...}]) — [1, 2] 같은 건 명세 오류로 알린다
        return bool(data) and all(isinstance(x, str) or (isinstance(x, dict) and ("prompt" in x or "scene" in x)) for x in data)
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("board"),dict) and isinstance(data["board"].get("scenes"),list) or st._is_conti(data) or st._is_maker_book(data) or isinstance(data.get("clips"), list)


def _r3(x: float) -> float:
    return math.floor(x * 1000 + 0.5) / 1000


def caption_pieces(text: str) -> list[str]:
    """쪽 글 → 자막 줄들: 줄바꿈마다, 너무 길면 문장마다, 그래도 길면 120자 안에서 끊는다."""
    out = []
    for line in re.split(r"\n+", str(text or "")):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        parts = [line] if len(line) <= CAPTION_MAX else re.split(r"(?<=[.!?。…])\s+", line)
        for part in parts:
            while len(part) > CAPTION_MAX:
                cut = part.rfind(" ", 0, CAPTION_MAX)
                cut = cut if cut > 0 else CAPTION_MAX
                out.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                out.append(part)
    return out


def slug(title: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", str(title or "").strip()).strip("-")[:40]
    return s or "short"


def story_to_spec(data, images: list[str] | None = None, base: Path | None = None, narration: bool = True,
                  local_paths: bool = True) -> tuple[dict, dict]:
    """반환: (숏폼 명세, 요약 {title, clips:[{id,label,seconds,image,auto}], total, unused_images})."""
    st = _h3story()
    story = st.load_story(data, images or [], base=base, narration=narration, local_paths=local_paths)
    secs = [c.seconds for c in story.clips]
    total = sum(secs)
    scenes, captions, t = [], [], 0.0
    for c, sec in zip(story.clips, secs):
        from h3video.spec import plan_scenes
        for part, duration in enumerate(plan_scenes(sec)):
            sc = {"prompt": c.prompt, "duration": duration, "seed": c.seed + part}
            if c.image:
                sc["image"] = c.image
            scenes.append(sc)
        pieces = caption_pieces(c.text)
        weights = [2 + len(re.sub(r"\s", "", p)) for p in pieces]
        acc = 0
        for p, w in zip(pieces, weights):
            start = _r3(t + sec * acc / sum(weights))
            acc += w
            captions.append({"text": p, "start": start, "end": _r3(t + sec * acc / sum(weights))})
        t += sec
    spec = {"scenes": scenes, "ratio": story.ratio, "template": "montage", "fit": "blur", "title": story.title,
            "max_duration": 0, "output": slug(story.title) + ".mp4"}
    if captions:
        spec["captions"] = captions
    info = {"title": story.title, "source": story.source, "total": total, "unused_images": story.unused_images,
            "clips": [{"id": c.id, "label": c.label, "seconds": s, "image": c.image, "auto": c.auto} for c, s in zip(story.clips, secs)]}
    return spec, info
