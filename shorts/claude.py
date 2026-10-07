"""기획 단계(선택): Claude 가 아이디어(+소스 영상 프레임)를 보고 작업 명세 JSON 을 쓴다.

Messages API 를 표준 라이브러리로 직접 호출한다(CLI 는 의존성 0 이 요구 사항).
- 구조화 출력 output_config.format(json_schema) 으로 JSON 만 받는다. Opus 5.5 는 tool_choice 강제를 받지 않으므로 이 방식.
- 받은 JSON 을 전체 스키마(+의미 검사)로 다시 검증하고, 실패하면 오류를 붙여 한 번만 다시 요청한다.
- 키는 ANTHROPIC_API_KEY 환경변수. 화면·로그에 키를 찍지 않는다.
웹(src/core/claude.js)이 같은 시스템 프롬프트·스키마 변환을 쓴다(테스트가 비교).
"""
from __future__ import annotations

import base64
import copy
import json
import os
import urllib.error
import urllib.request

from . import spec as S

DEFAULT_MODEL = "claude-opus-5-5"
API_VERSION = "2023-06-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
RUNTIME_FIELDS = ("$schema", "server", "ref_server", "backend", "poll", "timeout", "output", "model")
UNSUPPORTED = ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern", "title", "$id", "$schema",
               "x-hint", "description")

SYSTEM_PROMPT = """너는 세로형 숏폼(9:16, 60초 이하) 기획자다. 사용자의 아이디어(와 소스 영상 프레임)를 보고 작업 명세 JSON 하나를 만든다.
명세는 두 단계로 실행된다: (1) 사용자의 영상 생성 서버(MiniMax-H3 같은 모델)가 장면 영상을 만들고, (2) 템플릿으로 9:16 숏폼을 합성한다.

규칙
- scenes: 장면 1~4개. 각 장면 prompt 는 영상 생성용 영어 프롬프트(피사체·동작·카메라·조명·분위기, 1~3문장). 대사가 필요하면 따옴표 안에 한국어로.
- 장면 duration 은 4~15초 정수. 장면 길이 합계는 15~45초가 적당하다.
- ratio 는 "9:16".
- title: 상단 훅 문구, 한국어 18자 이내, 궁금증을 만드는 말.
- captions: 한국어 자막, 한 줄에 한 장면/한 생각, 줄당 22자 이내, 4~10줄. 영상 내용과 맞춘다.
- 소스 영상이 주어졌을 때:
  * 소스를 AI 참조로 써서 새 장면을 만들려면 scenes[].sources 에 파일 이름을 넣는다(장면당 영상 3개 이하).
  * 소스 자체를 주 화면으로 살리려면 base 에 파일 이름을 넣고 template 을 cutaway(소스 위로 AI 장면이 사이사이), split(위 소스·아래 AI), pip(소스 전체·AI 작은 창) 중에서 고른다.
  * 소스를 보지 않고 지어내지 말고, 프레임에서 보이는 내용에 맞춰 자막과 프롬프트를 쓴다.
- 소스가 없으면 template 은 "montage"(AI 장면을 이어 붙임).
- 서버 주소·출력 파일 같은 실행 설정은 넣지 않는다.
- JSON 만 출력한다."""


def _deref(node, root):
    if isinstance(node, dict):
        if "$ref" in node:
            target = node["$ref"][2:].split("/")
            t = root
            for k in target:
                t = t[k]
            return _deref(copy.deepcopy(t), root)
        return {k: _deref(v, root) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_deref(x, root) for x in node]
    return node


def _strip(node):
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in UNSUPPORTED}
    if isinstance(node, list):
        return [_strip(x) for x in node]
    return node


def api_schema() -> dict:
    """구조화 출력에 넘길 스키마: $ref 펼치기 + 지원 안 되는 제약(숫자·길이 범위 등) 제거 + 실행 설정 필드 제거.
    제거한 제약은 받은 뒤 전체 스키마로 다시 검사한다."""
    sch = _deref(copy.deepcopy(S.SCHEMA), S.SCHEMA)
    for k in RUNTIME_FIELDS:
        sch["properties"].pop(k, None)
    return _strip(sch)


def user_content(idea: str, sources: list[dict]) -> list[dict]:
    """sources = [{"name","duration","width","height","frames":[(t, jpeg_bytes)]}]"""
    blocks: list[dict] = []
    lines = [f"아이디어: {idea.strip()}"]
    if sources:
        lines.append("소스 영상:")
        for s in sources:
            lines.append(f"- {s['name']}: {s.get('duration', 0):.1f}초, {s.get('width', 0)}×{s.get('height', 0)}, "
                         f"프레임 {len(s.get('frames', []))}장 (시점: {', '.join(f'{t:.1f}초' for t, _ in s.get('frames', []))})")
            for _t, jpg in s.get("frames", []):
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                          "data": base64.b64encode(jpg).decode()}})
    else:
        lines.append("소스 영상: 없음 (AI 장면만으로 만든다)")
    blocks.append({"type": "text", "text": "\n".join(lines)})
    return blocks


def build_request(idea: str, sources: list[dict], model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_content(idea, sources)}],
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": api_schema()}},
        "fallbacks": "default",
    }


def headers(api_key: str) -> dict:
    return {"content-type": "application/json", "x-api-key": api_key, "anthropic-version": API_VERSION,
            "anthropic-beta": FALLBACK_BETA}


class PlanError(RuntimeError):
    def __init__(self, msg: str, errors: list[str] | None = None):
        super().__init__(msg)
        self.errors = errors or []


def _post(url: str, body: dict, api_key: str, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method="POST", headers=headers(api_key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors="replace")
        e.close()
        if e.code == 401:
            raise PlanError("Anthropic API 키가 맞지 않습니다(401). ANTHROPIC_API_KEY 를 확인하세요") from e
        if e.code == 429:
            raise PlanError("요청 한도에 걸렸습니다(429). 잠시 뒤 다시 하세요") from e
        raise PlanError(f"Anthropic API 오류 HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise PlanError(f"Anthropic API 에 연결하지 못했습니다: {e.reason}") from e


def parse_reply(resp: dict) -> tuple[dict | None, list[str]]:
    stop = resp.get("stop_reason")
    if stop == "refusal":
        return None, ["Claude 가 이 요청을 거절했습니다. 아이디어를 바꿔 보세요"]
    texts = [b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"]
    raw = "".join(texts).strip()
    if stop == "max_tokens":
        return None, ["응답이 max_tokens 에서 잘렸습니다"]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [f"JSON 으로 읽을 수 없습니다: {e}"]
    if not isinstance(obj, dict):
        return None, ["JSON 객체가 아닙니다"]
    errors, _ = S.check_spec(obj)
    return obj, errors


def plan(idea: str, sources: list[dict], api_key: str | None = None, model: str = DEFAULT_MODEL,
         base_url: str | None = None, timeout: float = 600.0, post=None, log=None) -> dict:
    """기획 → 검증 → (실패 시 1회 재요청). 반환: {"spec", "attempts", "usage"}"""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise PlanError("ANTHROPIC_API_KEY 환경변수가 없습니다. export ANTHROPIC_API_KEY=... 후 다시 하세요")
    url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    post = post or _post
    body = build_request(idea, sources, model)
    attempts = 0
    usage = []
    for attempt in range(2):
        attempts += 1
        resp = post(url, body, api_key, timeout)
        usage.append(resp.get("usage"))
        obj, errors = parse_reply(resp)
        if obj is not None and not errors:
            return {"spec": obj, "attempts": attempts, "usage": usage}
        if log:
            log(f"검증 실패 {len(errors)}건 — {'다시 요청합니다' if attempt == 0 else '포기'}: " + "; ".join(errors[:3]))
        if attempt == 0 and resp.get("stop_reason") != "refusal":
            body = copy.deepcopy(body)
            body["messages"].append({"role": "assistant", "content": resp.get("content", [])})
            body["messages"].append({"role": "user", "content": [{"type": "text", "text":
                                     "위 JSON 이 검증에 실패했습니다. 아래 오류를 모두 고친 전체 JSON 을 다시 주세요.\n- " + "\n- ".join(errors)}]})
            continue
        raise PlanError("Claude 가 만든 명세가 검증을 통과하지 못했습니다", errors)
    raise PlanError("기획 실패")


def request_summary(body: dict, url: str) -> dict:
    """--dry-run 용 요약(키 값은 넣지 않는다)."""
    imgs = [b for m in body["messages"] for b in m["content"] if b.get("type") == "image"]
    text = next(b["text"] for b in body["messages"][0]["content"] if b.get("type") == "text")
    return {"url": url, "model": body["model"], "max_tokens": body["max_tokens"],
            "headers": {"x-api-key": "(ANTHROPIC_API_KEY, 출력 안 함)", "anthropic-version": API_VERSION, "anthropic-beta": FALLBACK_BETA},
            "output_config": {"effort": body["output_config"]["effort"], "format": "json_schema (작업 명세 스키마)"},
            "fallbacks": body.get("fallbacks"),
            "images": [f"image/jpeg {len(base64.b64decode(b['source']['data'])) // 1024}KB" for b in imgs],
            "user_text": text, "schema_fields": sorted(body["output_config"]["format"]["schema"]["properties"])}
