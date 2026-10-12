"""JSON 하나 + 이미지들 → 영상 장면(클립) 목록. `h3video json`, 웹 UI 'JSON 한번에', 숏폼(`shorts run`)이 같이 쓴다.

받는 JSON
  1) 동화책 콘티(허브 /storybook-conti/)의 JSON 내보내기 {guide, opts, book} — "키 없이 쓰기"로 받은 book 만 있는 JSON 도 된다
  2) 동화책 만들기(storybook-maker)의 'JSON 한번에' 결과 폴더 book.json (kind: batch) — 쪽 그림 경로가 들어 있다
  3) 장면 목록: ["프롬프트", ...] 또는 {"title", "ratio", "clips"|"scenes"|"pages"|"items": [{"prompt", "image", "text", "seconds"}]}

클립 수는 JSON 의 쪽·장면 수로 정해지고, 길이는 알아서 정한다(-s 불필요):
  장면에 seconds(또는 duration)가 있으면 그 값, 없으면 글(text)을 소리 내어 읽는 시간, 글도 없으면 6초. 5~15초로 맞춘다.
이미지는 JSON 에 적힌 경로(그 JSON 파일 기준), 파일 이름(cover → 표지, page-03·03·3쪽 → 3쪽), 남은 것은 순서대로 붙는다.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import spec
from .client import H3Error

DEFAULT_SECONDS = 6          # 글이 없는 장면
MAX_CLIPS = float("inf")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
HANGUL = re.compile(r"[가-힣]")


@dataclass
class Clip:
    id: str
    label: str
    prompt: str               # 영상 프롬프트 (그대로 서버에 보낸다)
    seconds: int
    image: str | None = None  # 첫 프레임 (fl2va). 없으면 글만으로 (t2va)
    text: str = ""            # 쪽 글 — 길이 계산·내레이션·숏폼 자막
    page: int | None = None
    seed: int | None = None
    auto: str = ""            # 길이를 어떻게 정했는지 ("글 34자", "기본", "JSON")


@dataclass
class Story:
    title: str
    ratio: str
    clips: list[Clip]
    source: str               # conti | book | list
    unused_images: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        d = asdict(self)
        d["total_seconds"] = sum(c.seconds for c in self.clips)
        return d


def reading_seconds(text: str) -> float:
    """소리 내어 읽는 시간(초). 한국어는 공백 뺀 글자 4자/초, 그 밖은 단어 2.5개/초 (그림책을 천천히 읽는 빠르기)."""
    t = str(text or "").strip()
    if not t:
        return 0.0
    if HANGUL.search(t):
        return len(re.sub(r"\s", "", t)) / 4.0
    return len(t.split()) / 2.5


def auto_seconds(text: str = "", given=None) -> tuple[int, str]:
    """장면 길이: JSON 값 → 글 읽는 시간 + 1.5초 → 기본 6초. 모델 요청은 나누어 이어 붙이고 전체 장면 길이는 보존한다."""
    lo = spec.SCENE_MIN
    if given not in (None, ""):
        try:
            # 반올림은 웹(JS Math.round)과 같게: .5 는 올린다
            value = float(given)
            if not math.isfinite(value) or value <= 0:
                raise ValueError()
            return max(spec.DURATION_MIN, math.floor(value + 0.5)), "JSON"
        except (TypeError, ValueError):
            raise H3Error(f"seconds 는 숫자여야 한다: {given!r}") from None
    r = reading_seconds(text)
    if not r:
        return DEFAULT_SECONDS, "기본"
    n = len(re.sub(r"\s", "", text)) if HANGUL.search(text) else len(text.split())
    unit = "자" if HANGUL.search(text) else "단어"
    return max(lo, math.ceil(r + 1.5)), f"글 {n}{unit}"


# ---------- 영상 프롬프트 ----------
def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().rstrip(". ")


def narration_line(text: str) -> str:
    """쪽 글을 화면 밖 내레이터가 읽게 한다. 대사는 H3 형식 <d>[언어] 글</d> (README '프롬프트 요령')."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().replace("<", "‹").replace(">", "›")
    if not t:
        return ""
    lang = "Korean" if HANGUL.search(t) else "English"
    return f" Voice-over: an off-screen storyteller with a warm, gentle voice reads slowly and clearly <d>[{lang}] {t}</d>"


def video_prompt(scene: str, *, image: bool, style: str = "", characters: str = "", text: str = "", narration: bool = True) -> str:
    """그림책 장면 → 영상 프롬프트. 첫 프레임 그림이 있으면 그 그림을 살아 움직이게, 없으면 그림체·인물을 글로."""
    parts = [f"{_clean(scene)}."]
    if image:
        parts.append("Bring this picture-book illustration to life with gentle, natural motion: the characters move a little and the camera drifts slowly."
                     " Keep the art style and every character exactly as in the first frame.")
    else:
        if characters:
            parts.append(f"Characters — {characters}.")
        parts.append(f"Style: children's picture book illustration{', ' + _clean(style) if style else ''}. Gentle, natural motion and a slow camera drift.")
    parts.append("No on-screen text or captions. Soft, calm background music.")
    return " ".join(parts) + (narration_line(text) if narration else "")


# ---------- JSON 모양 알아보기 ----------
def _is_conti(o) -> bool:
    b = o.get("book", o) if isinstance(o, dict) else None
    return isinstance(b, dict) and isinstance(b.get("pages"), list) and isinstance(b.get("style"), dict) \
        and any(isinstance(p, dict) and isinstance(p.get("scene"), str) for p in b["pages"])


def _is_maker_book(o) -> bool:
    return isinstance(o, dict) and o.get("kind") == "batch" and isinstance(o.get("items"), list)


def _ratio(r, has_images: bool) -> str:
    if r in spec.ASPECT_RATIOS:
        return r
    return "auto" if has_images else "16:9"


def _conti(o, narration: bool) -> tuple[str, str, list[dict]]:
    b = o.get("book", o)
    style = _clean((b.get("style") or {}).get("prompt"))
    chars = {str(c.get("name")): _clean(c.get("prompt")) for c in b.get("characters") or [] if isinstance(c, dict)}
    shot = {"wide": "Wide shot: ", "medium": "Medium shot: ", "close-up": "Close-up: ", "bird-eye": "Bird's-eye view: ",
            "low-angle": "Low-angle shot: ", "over-shoulder": "Over-the-shoulder shot: "}
    raw = []
    cover = b.get("cover") or {}
    if _clean(cover.get("scene")):
        raw.append({"id": "cover", "label": "표지", "scene": f"Book cover: {_clean(cover.get('scene'))}", "text": "",
                    "chars": cover.get("characters") or [], "optional": True, "page": 0})
    for i, p in enumerate(b.get("pages") or [], 1):
        if not isinstance(p, dict) or not _clean(p.get("scene")):
            continue
        n = p.get("page") if isinstance(p.get("page"), int) else i
        raw.append({"id": f"page-{n:02d}", "label": f"{n}쪽", "page": n, "scene": shot.get(p.get("shot"), "") + _clean(p.get("scene")),
                    "text": str(p.get("text") or ""), "chars": p.get("characters") or [], "seconds": p.get("seconds")})
    for r in raw:
        r["style"] = style
        r["characters"] = "; ".join(f"{n}: {chars[n]}" for n in r.pop("chars") if n in chars and chars[n])
    ratio = (o.get("opts") or {}).get("ratio") if isinstance(o.get("opts"), dict) else None
    return str(b.get("title") or "동화책"), ratio, raw


def _maker_book(o, base: Path | None) -> tuple[str, str, list[dict]]:
    raw = []
    style = _clean(o.get("style"))
    for it in o["items"]:
        if not isinstance(it, dict) or it.get("kind") not in ("cover", "page", "image"):
            continue
        img = it.get("image")
        raw.append({"id": str(it.get("id")), "label": str(it.get("label") or it.get("id")), "page": it.get("page"),
                    "scene": _clean(it.get("scene") or it.get("prompt")), "text": str(it.get("text") or ""),
                    "image": str((base / img) if base and img else img) if img else None, "style": style,
                    "characters": "", "optional": it.get("kind") == "cover"})
    w, h = o.get("width"), o.get("height")
    ratio = None
    if w and h:
        best = min(("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"), key=lambda r: abs(math.log((w / h) / (int(r.split(':')[0]) / int(r.split(':')[1])))))
        ratio = best
    return str(o.get("title") or "동화책"), ratio, raw


def _list(o) -> tuple[str, str, list[dict]]:
    items = o if isinstance(o, list) else next((o.get(k) for k in ("clips", "scenes", "pages", "items") if isinstance(o.get(k), list)), None)
    if items is None:
        raise H3Error('장면을 찾지 못했다: 동화책 콘티 JSON, 동화책 만들기 book.json, 또는 {"clips": [{"prompt": ...}]} 이어야 한다')
    raw = []
    for i, x in enumerate(items, 1):
        x = {"prompt": x} if isinstance(x, str) else x
        if not isinstance(x, dict):
            raise H3Error(f"{i}번째 장면이 글이나 객체가 아니다")
        prompt = str(x.get("prompt") or x.get("scene") or "").strip()
        if not prompt:
            raise H3Error(f"{i}번째 장면에 prompt 가 없다")
        raw.append({"id": f"clip-{i:02d}", "label": str(x.get("label") or x.get("name") or x.get("title") or f"{i}번"),
                    "prompt": prompt, "text": str(x.get("text") or x.get("caption") or ""),
                    "image": x.get("image") or x.get("first") or None, "seconds": x.get("seconds", x.get("duration")),
                    "seed": x.get("seed"), "page": i})
    title = str(o.get("title") or "영상 묶음") if isinstance(o, dict) else "영상 묶음"
    ratio = o.get("ratio") if isinstance(o, dict) else None
    return title, ratio, raw


# ---------- 이미지 붙이기 ----------
def _num_in(name: str) -> int | None:
    m = re.search(r"(?:page|p|쪽|scene|clip)?[-_ ]?0*(\d{1,3})(?!\d)", Path(name).stem, re.I)
    return int(m.group(1)) if m else None


def _match_images(raw: list[dict], images: list[str], base: Path | None, local_paths: bool = True) -> list[str]:
    """JSON 경로 → 파일 이름(cover·숫자) → 남은 그림은 순서대로. 쓰지 않은 그림 목록을 돌려준다.
    local_paths=False(웹 요청)면 JSON 에 적힌 경로로 이 컴퓨터의 파일을 읽지 않고, 함께 올린 그림의 이름으로만 맞춘다."""
    pool = [str(p) for p in images]
    by_name = {Path(p).name.lower(): p for p in pool}
    used: set[str] = set()
    for r in raw:
        img = r.get("image")
        if not img:
            continue
        p = Path(str(img)).expanduser()
        cand = p if p.is_absolute() else (base / p if base else p)
        if local_paths and cand.is_file():
            r["image"] = str(cand)
        elif str(img).startswith(("http://", "https://")):
            continue
        elif p.name.lower() in by_name:
            r["image"] = by_name[p.name.lower()]
        else:
            raise H3Error(f"{r['label']}: 그림 {img} 을 찾지 못했다 (JSON 파일 기준 경로이거나, 같은 이름의 그림을 같이 넘겨라)")
        used.add(r["image"])
    rest = [p for p in pool if p not in used]
    for p in list(rest):
        stem = Path(p).stem.lower()
        target = None
        if "cover" in stem or "표지" in stem:
            target = next((r for r in raw if r["id"] == "cover" and not r.get("image")), None)
        else:
            n = _num_in(p)
            if n is not None:
                target = next((r for r in raw if r.get("page") == n and r["id"] != "cover" and not r.get("image")), None)
        if target:
            target["image"] = p
            rest.remove(p)
    for r in raw:   # 이름으로 못 맞춘 그림은 그림 없는 장면에 순서대로 (표지는 이름이 cover 일 때만)
        if not rest:
            break
        if not r.get("image") and not r.get("optional"):
            r["image"] = rest.pop(0)
    return rest


def expand_images(paths: list[str]) -> list[str]:
    """파일과 폴더(안의 그림 전부, 이름순)를 받아 그림 파일 목록으로."""
    out = []
    for p in paths:
        q = Path(p).expanduser()
        if q.is_dir():
            out += sorted((str(x) for x in q.iterdir() if x.suffix.lower() in IMAGE_EXTS), key=_natural)
        elif q.is_file():
            out.append(str(q))
        else:
            raise H3Error(f"없는 파일: {p}")
    return out


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(s).name)]


def load_story(data, images: list[str] | None = None, base: Path | None = None, narration: bool = True,
               ratio: str | None = None, seed: int = 0, local_paths: bool = True) -> Story:
    """data: JSON 글·객체. images: 그림 파일들. base: JSON 파일이 있는 폴더(상대 경로 기준)."""
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data.decode("utf-8-sig") if isinstance(data, bytes) else data.lstrip("﻿"))
        except json.JSONDecodeError as e:
            # 파이썬 영어 메시지만 주지 않고 어디가 틀렸는지 쉬운 말로 (원래 메시지는 괄호에)
            raise H3Error(f"JSON 을 읽을 수 없다: {e.lineno}줄 {e.colno}번째 글자 근처가 JSON 형식이 아니다 "
                          f"(따옴표·쉼표·괄호를 확인. 원래 메시지: {e.msg})") from None
    if isinstance(data,dict) and isinstance(data.get("board"),dict) and isinstance(data["board"].get("scenes"),list):
        data={"title":data["board"].get("title"),"ratio":data.get("brief",{}).get("ratio"),"clips":[{"prompt":s.get("videoPrompt") or s.get("imagePrompt") or s.get("visual"),"title":s.get("title"),"seconds":s.get("duration"),"text":s.get("caption","")} for s in data["board"]["scenes"]]}
    if _is_conti(data):
        source, (title, jratio, raw) = "conti", _conti(data, narration)
    elif _is_maker_book(data):
        source, (title, jratio, raw) = "book", _maker_book(data, base if local_paths else None)
    elif isinstance(data, (list, dict)):
        source, (title, jratio, raw) = "list", _list(data)
    else:
        raise H3Error("JSON 이 객체나 배열이 아니다")
    unused = _match_images(raw, list(images or []), base, local_paths)
    for r in raw:
        img = r.get("image")
        if img and not str(img).startswith(("http://", "https://")) and Path(img).suffix.lower() not in IMAGE_EXTS:
            raise H3Error(f"{r['label']}: {Path(img).name} 은 첫 프레임으로 쓸 수 없는 형식이다 (PNG·JPEG·WebP)")
    raw = [r for r in raw if not (r.get("optional") and not r.get("image"))]   # 그림 없는 표지는 뺀다
    if not raw:
        raise H3Error("만들 장면이 없다")
    if len(raw) > MAX_CLIPS:
        raise H3Error(f"한 번에 최대 {MAX_CLIPS}개 장면 (지금 {len(raw)}개)")
    clips = []
    for i, r in enumerate(raw):
        secs, how = auto_seconds(r.get("text", ""), r.get("seconds"))
        prompt = r.get("prompt") or video_prompt(r["scene"], image=bool(r.get("image")), style=r.get("style", ""),
                                                 characters=r.get("characters", ""), text=r.get("text", ""), narration=narration)
        if r.get("prompt") and narration and r.get("text"):
            prompt += narration_line(r["text"])
        s = r.get("seed")
        clips.append(Clip(id=r["id"], label=r["label"], prompt=prompt, seconds=secs, image=r.get("image"), text=r.get("text", ""),
                          page=r.get("page"), seed=int(s) if isinstance(s, (int, float)) or (isinstance(s, str) and s.isdigit()) else seed + i,
                          auto=how))
    return Story(title=title, ratio=_ratio(ratio or jratio, any(c.image for c in clips)), clips=clips, source=source, unused_images=unused)


MEDIA_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac")


def _zip_name(info: zipfile.ZipInfo) -> str:
    """zip 안의 이름: UTF-8 표시가 없으면 UTF-8 로 읽어 보고, 안 되면 윈도우 한글(CP949) — 웹 zip.js 와 같다."""
    name = info.filename
    if not info.flag_bits & 0x800:
        raw = name.encode("cp437", errors="replace")
        for enc in ("utf-8", "cp949"):
            try:
                name = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    return name.replace("\\", "/")


def unpack_zip(path: str) -> dict:
    """동화책 만들기의 '파일 받기' zip(book.json + images/*, 압축 없이 담김)을 푼다 — 웹(숏폼 src/app/zip.js·영상 만들기 화면)과 같은 규칙:
    폴더 경로는 버리고 이름만, 같은 이름은 처음 것, 숨김·__MACOSX·index.html 처럼 쓰지 않는 것은 뺀다. JSON 이 여럿이면 book.json.
    푼 파일은 캐시 폴더($XDG_CACHE_HOME/h3video/zip/<zip 내용 해시>)에 둔다: 나중에 이어 하기(--resume)에도 그림이 남아 있게.
    반환 {"json": 경로|None, "images": [...], "media": [영상·소리], "skipped": [zip 안 이름]}"""
    p = Path(path).expanduser()
    try:
        zf = zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        raise H3Error(f"zip 파일이 아니거나 끝이 잘렸다: {path}") from None
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    out = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache").expanduser() / "h3video" / "zip" / h.hexdigest()[:16]
    out.mkdir(parents=True, exist_ok=True)
    jsons, images, media, skipped, seen = [], [], [], [], set()
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            full = _zip_name(info)
            name = full.rsplit("/", 1)[-1]
            low = name.lower()
            junk = not name or name.startswith(".") or full.startswith("__MACOSX/")
            usable = low.endswith(".json") or low.endswith(IMAGE_EXTS) or low.endswith(MEDIA_EXTS)
            if junk or not usable or name in seen:
                if not junk:
                    skipped.append(full)
                continue
            if info.flag_bits & 0x1:
                raise H3Error(f"{full}: 암호가 걸린 zip 은 열 수 없다. 풀어서 파일들을 넣어라")
            seen.add(name)
            dest = out / name
            if not (dest.is_file() and dest.stat().st_size == info.file_size):
                try:
                    with zf.open(info) as src, open(dest, "wb") as fh:
                        shutil.copyfileobj(src, fh)
                except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as e:
                    raise H3Error(f"{full}: zip 안의 파일을 풀지 못했다 ({e})") from None
            (jsons if low.endswith(".json") else images if low.endswith(IMAGE_EXTS) else media).append(str(dest))
    book = next((j for j in jsons if Path(j).name.lower() == "book.json"), jsons[0] if jsons else None)
    return {"json": book, "images": sorted(images, key=_natural), "media": media, "skipped": skipped}


def load_story_file(path: str, images: list[str] | None = None, **kw) -> Story:
    p = Path(path).expanduser()
    if not p.is_file():
        raise H3Error(f"JSON 파일이 없다: {path}")
    if p.suffix.lower() == ".zip":   # 동화책 만들기 '파일 받기' zip: 안의 book.json 과 그림을 그대로
        z = unpack_zip(str(p))
        if not z["json"]:
            raise H3Error(f"zip 안에 JSON 이 없다: {path} (동화책 만들기의 '파일 받기' zip 에는 book.json 이 들어 있다)")
        jp = Path(z["json"])
        return load_story(jp.read_bytes(), z["images"] + expand_images(images or []), base=jp.parent, **kw)
    return load_story(p.read_bytes(), expand_images(images or []), base=p.resolve().parent, **kw)


def describe(story: Story) -> str:
    total = sum(c.seconds for c in story.clips)
    lines = [f"{story.title} · 장면 {len(story.clips)}개 · 합계 {total}초 · 화면비 {story.ratio}"]
    for c in story.clips:
        lines.append(f"  [{c.id}] {c.label} {c.seconds}초 ({c.auto}) · {'첫 프레임 ' + Path(c.image).name if c.image else '그림 없음(글만)'}")
    if story.unused_images:
        lines.append("  쓰지 않은 그림: " + ", ".join(Path(p).name for p in story.unused_images))
    return "\n".join(lines)
