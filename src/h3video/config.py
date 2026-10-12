"""저장해 두는 설정: 서버 주소·결과 폴더를 매번 환경 변수로 주지 않아도 되게.

  h3video config                                   지금 값과 어디서 왔는지
  h3video config set endpoint http://127.0.0.1:30010
  h3video config unset endpoint

파일: $XDG_CONFIG_HOME/h3video/config.json (없으면 ~/.config/h3video/config.json)
우선순위: 명령 옵션(--endpoint) > 환경 변수(H3_ENDPOINT) > 설정 파일 > 기본값
비밀 값은 저장하지 않는다. 혹시 파일에 token·key 같은 이름이 있어도 화면에는 가려서 보인다.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path

from .client import H3Error

# 설정 이름: (환경 변수, 기본값, 뜻, 명령 옵션)
KEYS: dict[str, tuple[str, str | None, str, str]] = {
    "endpoint": ("H3_ENDPOINT", "http://127.0.0.1:30010", "글·그림(fl2va) 서버 주소", "--endpoint"),
    "ref-endpoint": ("H3_REF_ENDPOINT", "http://127.0.0.1:30011", "참고 자료(ref2va) 서버 주소", "--ref-endpoint"),
    "output-dir": ("H3_OUTPUT_DIR", "outputs", "결과 폴더", "--output-dir"),
    "inbox-dir": ("H3_INBOX_DIR", None, "서버가 읽는 공유 폴더 (클러스터)", "--inbox-dir"),
}
SECRET_WORDS = ("token", "secret", "password", "passwd", "key", "auth")


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "h3video" / "config.json"


def load() -> dict:
    p = path()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}   # 깨진 파일 때문에 명령이 멈추지 않게 (config 로 보면 알려 준다)
    return d if isinstance(d, dict) else {}


def save(d: dict) -> Path:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def norm_key(key: str) -> str:
    k = key.strip().lower().replace("_", "-")
    if k in KEYS:
        return k
    near = difflib.get_close_matches(k, list(KEYS), n=1, cutoff=0.5)
    raise H3Error(f"모르는 설정 이름: {key}" + (f" — 혹시: {near[0]}" if near else "") + f"  (쓸 수 있는 것: {', '.join(KEYS)})")


def resolve(key: str, cfg: dict | None = None) -> tuple[str | None, str]:
    """(값, 어디서) — 환경 변수 > 설정 파일 > 기본값. 명령 옵션은 부르는 쪽이 먼저 본다."""
    env, default, _, _ = KEYS[key]
    if os.environ.get(env):
        return os.environ[env], f"환경 변수 {env}"
    cfg = load() if cfg is None else cfg
    if cfg.get(key):
        return str(cfg[key]), "설정 파일"
    return default, "기본값"


def check_value(key: str, value: str) -> str:
    v = value.strip()
    if key in ("endpoint", "ref-endpoint"):
        if not v.startswith(("http://", "https://")):
            raise H3Error(f"{key} 는 http:// 또는 https:// 로 시작해야 한다: {value}  — 혹시: h3video config set {key} http://{v}")
        return v.rstrip("/")
    if key in ("output-dir", "inbox-dir"):
        return str(Path(v).expanduser().resolve())
    return v


def masked(key: str, value) -> str:
    return "(가림)" if any(w in key.lower() for w in SECRET_WORDS) and key not in KEYS else str(value)
