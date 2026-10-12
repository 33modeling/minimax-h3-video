"""작업 명세(JSON) 검증·정규화. src/core/spec.js 와 같은 규칙(테스트가 맞대어 본다)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "job.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

DEFAULTS = {
    "version": 1, "duration": 8, "ratio": "9:16", "seed": 0, "backend": "auto", "poll": 3, "timeout": 1800, "fit": "blur",
    "resolution": "720x1280", "fps": 30, "quality": "medium", "max_duration": 0, "title": "", "bgm_volume": 0.25, "original_volume": 1,
    "output": "short.mp4",
}
REF_LIMITS = {"image": 9, "video": 3, "audio": 3, "total": 12}
RESOLUTION_PRESETS = SCHEMA["properties"]["resolution"]["x-presets"]
SIZE_MIN, SIZE_MAX = 240, 2160  # 짧은 변
LONG_MAX = 2560  # 긴 변 (1440x2560 프리셋)
H3_MAX_SHORT_EDGE = 768
GEN_FPS = 24  # H3 생성은 24fps 고정, 출력 fps 는 합성 단계에서 맞춘다


def parse_size(v):
    """"WxH" → (w, h), 형식이 틀리면 None."""
    m = re.fullmatch(r"([0-9]+)x([0-9]+)", str(v))
    return (int(m.group(1)), int(m.group(2))) if m else None


def check_size(name: str, w: int, h: int | None) -> list[str]:
    errs = []
    shown = f"{w}" if h is None else f"{w}x{h}"
    vals = [w] if h is None else [w, h]
    pre = "" if h is None else "가로·세로는 "
    if any(x % 2 != 0 for x in vals):
        errs.append(f"{name}: {pre}짝수여야 합니다 (지금 {shown})")
    if h is None:
        if w < SIZE_MIN or w > SIZE_MAX:
            errs.append(f"{name}: {SIZE_MIN}~{SIZE_MAX} 사이여야 합니다 (지금 {shown})")
    elif min(w, h) < SIZE_MIN or min(w, h) > SIZE_MAX or max(w, h) > LONG_MAX:
        errs.append(f"{name}: 짧은 변은 {SIZE_MIN}~{SIZE_MAX}, 긴 변은 {LONG_MAX} 이하여야 합니다 (지금 {shown})")
    return errs


def gen_short_edge(g):
    if g is None:
        return None
    if isinstance(g, (int, float)) and not isinstance(g, bool):
        return int(g)
    s = parse_size(g)
    return min(s) if s else None

TYPE_KO = {
    "string": "문자열이어야", "number": "숫자여야", "integer": "정수여야", "boolean": "true 또는 false여야",
    "array": "목록([...])이어야", "object": "객체({...})여야",
}


class SpecError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def _type_of(v) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, list):
        return "array"
    if v is None:
        return "null"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v.is_integer() else "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _type_matches(t: str, v) -> bool:
    k = _type_of(v)
    return t == k or (t == "number" and k == "integer")


def _num(v):
    """JSON.stringify 처럼 1.0 → 1 (목록·객체 안까지)."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, list):
        return [_num(x) for x in v]
    if isinstance(v, dict):
        return {k: _num(x) for k, x in v.items()}
    return v


def fmt_value(v) -> str:
    s = json.dumps(_num(v), ensure_ascii=False, separators=(",", ":"))
    return s[:37] + "..." if len(s) > 40 else s


def _resolve_ref(root: dict, ref: str) -> dict:
    node = root
    for k in ref[2:].split("/"):
        node = node[k]
    return node


def _edit_distance(a: str, b: str) -> int:
    dp = [[i] + [0] * len(b) for i in range(len(a) + 1)]
    for j in range(1, len(b) + 1):
        dp[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (0 if a[i - 1] == b[j - 1] else 1))
    return dp[len(a)][len(b)]


def _label(path: str, title: str | None) -> str:
    p = path or "(전체)"
    return f"{p} [{title}]" if title else p


def validate_schema(value, sch: dict | None = None, path: str = "", root: dict | None = None,
                    errors: list[str] | None = None, parent_title: str | None = None) -> list[str]:
    sch = SCHEMA if sch is None else sch
    root = SCHEMA if root is None else root
    errors = [] if errors is None else errors
    if "$ref" in sch:
        target = _resolve_ref(root, sch["$ref"])
        merged = dict(target)
        merged["title"] = sch.get("title") or parent_title or target.get("title")
        return validate_schema(value, merged, path, root, errors)
    at = _label(path, sch.get("title") or parent_title)
    if "anyOf" in sch:
        ok = any(not validate_schema(value, s, path, root, []) for s in sch["anyOf"])
        if not ok:
            branch = next((s for s in sch["anyOf"] if s.get("type") and _type_matches(s["type"], value)), None)
            if branch:
                return validate_schema(value, branch, path, root, errors, sch.get("title"))
            errors.append(f"{at}: 형식이 맞지 않습니다. {sch.get('x-hint', '')} 형태로 적어 주세요 (지금 {fmt_value(value)})")
        return errors
    t = sch.get("type")
    if t and not _type_matches(t, value):
        errors.append(f"{at}: {TYPE_KO[t]} 합니다 (지금 {fmt_value(value)})")
        return errors
    if "enum" in sch and value not in sch["enum"]:
        opts = ", ".join(json.dumps(x, ensure_ascii=False) for x in sch["enum"])
        errors.append(f"{at}: {opts} 중 하나여야 합니다 (지금 {fmt_value(value)})")
    if isinstance(value, str):
        if sch.get("minLength") and len(value.strip()) < sch["minLength"]:
            errors.append(f"{at}: 비어 있으면 안 됩니다")
        if sch.get("maxLength") and len(value) > sch["maxLength"]:
            errors.append(f"{at}: {sch['maxLength']}자 이하여야 합니다 (지금 {len(value)}자)")
        if sch.get("pattern") and not re.search(sch["pattern"], value):
            errors.append(f"{at}: {sch.get('x-pattern') or '형식이 맞아야'} 합니다 (지금 {fmt_value(value)})")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in sch and value < sch["minimum"]:
            errors.append(f"{at}: {_num(sch['minimum'])} 이상이어야 합니다 (지금 {fmt_value(value)})")
        if "maximum" in sch and value > sch["maximum"]:
            errors.append(f"{at}: {_num(sch['maximum'])} 이하여야 합니다 (지금 {fmt_value(value)})")
    if isinstance(value, list):
        if sch.get("minItems") and len(value) < sch["minItems"]:
            errors.append(f"{at}: 최소 {sch['minItems']}개가 필요합니다")
        if "maxItems" in sch and len(value) > sch["maxItems"]:
            errors.append(f"{at}: 최대 {sch['maxItems']}개까지 넣을 수 있습니다 (지금 {len(value)}개)")
        if "items" in sch:
            for i, v in enumerate(value):
                validate_schema(v, sch["items"], f"{path}[{i}]", root, errors, sch.get("title"))
    if isinstance(value, dict):
        for key in sch.get("required", []):
            if key not in value:
                errors.append(f"{at}: '{key}' 항목이 필요합니다")
        props = sch.get("properties", {})
        for key, v in value.items():
            sub = f"{path}.{key}" if path else key
            if key in props:
                validate_schema(v, props[key], sub, root, errors)
            elif sch.get("additionalProperties") is False:
                names = [n for n in props if n != "$schema"]
                best = sorted(((_edit_distance(key, n), n) for n in names), key=lambda x: (x[0], x[1]))
                hint = f" 혹시 '{best[0][1]}' 인가요?" if best and best[0][0] <= 3 else ""
                errors.append(f"{sub}: 알 수 없는 항목입니다.{hint}")
    return errors


def media_path(m):
    return m if isinstance(m, str) else (m or {}).get("path")


def norm_media(m):
    if m is None:
        return None
    if isinstance(m, str):
        return {"path": m, "start": 0, "end": None}
    return {"path": m["path"], "start": m.get("start", 0) or 0, "end": m.get("end")}


def base_name(p: str) -> str:
    return re.split(r"[\\/]", str(p))[-1]


def referenced_paths(spec: dict) -> list[str]:
    out: list[str] = []

    def add(p):
        if p and p not in out:
            out.append(p)
    add(media_path(spec.get("base")))
    for m in spec.get("sources") or []:
        add(media_path(m))
    for s in spec.get("scenes") or []:
        for m in s.get("sources") or []:
            add(media_path(m))
        add(s.get("image"))
    add(spec.get("image"))
    add(spec.get("bgm"))
    return out


def attach_files(spec: dict, names: list[str]) -> dict:
    """두 번째 파일: 명세가 같은 이름으로 가리키면 그 자리, 아니면 sources 에 붙인다."""
    nxt = copy.deepcopy(spec)
    refs = [base_name(p) for p in referenced_paths(nxt)]
    for name in names:
        if base_name(name) in refs:
            continue
        nxt["sources"] = list(nxt.get("sources") or []) + [name]
    return nxt


def is_image_path(p) -> bool:
    return bool(re.search(r"\.(png|jpe?g|webp|gif|bmp)$", str(p), re.I))


def is_audio_path(p) -> bool:
    return bool(re.search(r"\.(mp3|m4a|aac|wav|ogg|oga|opus|flac)$", str(p), re.I))


def match_files(spec: dict, names: list[str]) -> tuple[dict, list[str]]:
    """두 번째 파일들을 명세에 맞춘다 — 웹 src/app/match.js matchFiles 와 같은 규칙.
    명세가 이름으로 가리키면 그 자리, 남는 영상은 sources 뒤, 남는 음악은 bgm 이 비었을 때 배경음,
    남는 이미지는 AI 명세일 때만 참조(sources). 반환: (새 명세, 쓰지 않는 파일)."""
    refs = [base_name(p) for p in referenced_paths(spec)]
    uses_ai = bool(spec.get("prompt") or spec.get("scenes"))
    extra: list[str] = []
    unused: list[str] = []
    bgm = None
    for name in names:
        if base_name(name) in refs:
            continue
        if is_audio_path(name):
            if not spec.get("bgm") and not bgm:
                bgm = name
            else:
                unused.append(name)
        elif is_image_path(name):
            (extra if uses_ai else unused).append(name)
        else:
            extra.append(name)
    nxt = attach_files(spec, extra)
    if bgm:
        nxt["bgm"] = bgm
    return nxt, unused


def _make_scene(prompt, sources, image, duration, seed):
    refs = [norm_media(m) for m in (sources or [])]
    task = "ref2va" if refs else ("fl2va" if image else "t2va")
    return {"prompt": prompt, "sources": refs, "image": image or None, "duration": duration, "seed": seed, "task": task}


def ai_scenes(spec: dict) -> list[dict]:
    n = normalize_spec(spec)
    if n["scenes"]:
        out = []
        for i, s in enumerate(n["scenes"]):
            src = s["sources"] if "sources" in s else n["sources"]
            img = s.get("image") if s.get("image") is not None else (n["image"] if i == 0 else None)
            dur = s.get("duration") if s.get("duration") is not None else n["duration"]
            seed = s.get("seed") if s.get("seed") is not None else n["seed"] + i
            out.append(_make_scene(s["prompt"], src, img, dur, seed))
        return out
    if n["prompt"]:
        return [_make_scene(n["prompt"], n["sources"], n["image"], n["duration"], n["seed"])]
    return []


def _check_range(m, path, errors):
    if isinstance(m, dict) and m.get("start") is not None and m.get("end") is not None and m["end"] <= m["start"]:
        errors.append(f"{path}: end({_num(m['end'])})는 start({_num(m['start'])})보다 커야 합니다")


def check_spec(spec) -> tuple[list[str], list[str]]:
    errors = validate_schema(spec)
    warnings: list[str] = []
    if errors:
        return errors, warnings
    uses_ai = bool(spec.get("prompt") or spec.get("scenes"))
    if spec.get("prompt") and spec.get("scenes"):
        errors.append("prompt 와 scenes 는 함께 쓸 수 없습니다. 장면이 여러 개면 scenes 만 쓰세요")
    if not uses_ai and not spec.get("base") and not spec.get("sources"):
        errors.append("만들 재료가 없습니다: prompt(AI 생성) 또는 base·sources(소스 영상) 중 하나는 있어야 합니다. "
                      "소스 영상은 두 번째 파일로 넘겨도 됩니다")
    if spec.get("resolution"):
        w, h = parse_size(spec["resolution"])
        errors.extend(check_size("resolution", w, h))
    if spec.get("gen_size") is not None:
        g = spec["gen_size"]
        gs = parse_size(g) if isinstance(g, str) else None
        errors.extend(check_size("gen_size", gs[0], gs[1]) if gs else check_size("gen_size", int(g), None))
    _check_range(spec.get("base"), "base", errors)
    for i, m in enumerate(spec.get("sources") or []):
        _check_range(m, f"sources[{i}]", errors)
    for i, s in enumerate(spec.get("scenes") or []):
        for j, m in enumerate(s.get("sources") or []):
            _check_range(m, f"scenes[{i}].sources[{j}]", errors)
    for i, c in enumerate(spec.get("captions") or []):
        if isinstance(c, dict) and c.get("start") is not None and c.get("end") is not None and c["end"] <= c["start"]:
            errors.append(f"captions[{i}]: end({_num(c['end'])})는 start({_num(c['start'])})보다 커야 합니다")
    if uses_ai and not errors:
        for i, sc in enumerate(ai_scenes(spec)):
            videos = sum(1 for m in sc["sources"] if not is_image_path(m["path"]))
            images = len(sc["sources"]) - videos + (1 if sc["task"] == "ref2va" and sc["image"] else 0)
            where = f"scenes[{i}]" if spec.get("scenes") else "sources"
            if videos > REF_LIMITS["video"]:
                errors.append(f"{where}: 참조 영상은 최대 {REF_LIMITS['video']}개입니다 (지금 {videos}개)")
            if images > REF_LIMITS["image"]:
                errors.append(f"{where}: 참조 이미지는 최대 {REF_LIMITS['image']}개입니다 (지금 {images}개)")
            if videos + images > REF_LIMITS["total"]:
                errors.append(f"{where}: 참조는 합계 {REF_LIMITS['total']}개 이하여야 합니다")
            if spec.get("backend") == "vllm" and videos + images > 1:
                warnings.append(f"{where}: vLLM 서버는 참조를 1개만 받습니다. 첫 번째만 보냅니다")
        if spec.get("sources"):
            warnings.append("prompt 가 있어 sources 는 AI 참조 입력으로 씁니다")
        se = gen_short_edge(spec.get("gen_size"))
        if se is not None and se > H3_MAX_SHORT_EDGE:
            warnings.append(f"gen_size: 짧은 변 {se}px 은 로컬 H3 상한 {H3_MAX_SHORT_EDGE}px 을 넘습니다. "
                            "H3 서버(sglang·h3video)로는 보내기 전에 막습니다")
        gs = parse_size(spec["gen_size"]) if isinstance(spec.get("gen_size"), str) else None
        ratio = spec.get("ratio") or DEFAULTS["ratio"]
        if gs and ratio != "auto":
            a, b = (int(x) for x in ratio.split(":"))
            if abs(gs[0] / gs[1] - a / b) > 0.02 * (a / b):
                warnings.append(f"gen_size {spec['gen_size']} 의 비율이 ratio {ratio} 와 다릅니다. H3 는 ratio 와 짧은 변({se}px)만 씁니다")
    tpl = spec.get("template")
    if tpl and tpl != "montage" and not spec.get("base"):
        warnings.append(f"기본 영상(base)이 없어 '{tpl}' 대신 몽타주로 만듭니다")
    return errors, warnings


def normalize_spec(spec: dict) -> dict:
    s = dict(DEFAULTS)
    s.update(spec)
    s["prompt"] = spec.get("prompt") or None
    s["scenes"] = [dict(x) for x in spec["scenes"]] if spec.get("scenes") else None
    s["sources"] = [norm_media(m) for m in (spec.get("sources") or [])]
    s["base"] = norm_media(spec.get("base"))
    for k in ("image", "bgm", "server", "ref_server", "model"):
        s[k] = spec.get(k) or None
    s["captions"] = [{"text": c} if isinstance(c, str) else dict(c) for c in (spec.get("captions") or [])]
    s["template"] = spec.get("template") or ("cutaway" if s["base"] else "montage")
    s["usesAi"] = bool(s["prompt"] or s["scenes"])
    return s


def compose_inputs(spec: dict, generated: list[str] | None = None) -> dict:
    n = normalize_spec(spec)
    clips = [{"path": p, "start": 0, "end": None} for p in (generated or [])] if n["usesAi"] else n["sources"]
    return {"base": n["base"], "clips": clips, "bgm": n["bgm"]}
