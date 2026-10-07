"""tests/parity_cases.json 의 각 경우를 shorts/plan.py 로 계획해 JSON 으로 출력(JS 쪽과 비교용)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shorts import plan as P  # noqa: E402
from shorts import spec as S  # noqa: E402


def inputs_for(spec, media):
    ci = S.compose_inputs(spec, [])
    key = lambda p: p.rsplit(".", 1)[0]  # noqa: E731
    return {"base": {"media": ci["base"], "info": media[key(ci["base"]["path"])]} if ci["base"] else None,
            "clips": [{"media": m, "info": media[key(m["path"])]} for m in ci["clips"]],
            "bgm": {"path": ci["bgm"], "info": media[key(ci["bgm"])]} if ci["bgm"] else None}


def main():
    data = json.loads((ROOT / "tests" / "parity_cases.json").read_text(encoding="utf-8"))
    out = {}
    for c in data["cases"]:
        norm = S.normalize_spec(c["spec"])
        out[c["name"]] = P.plan_timeline(norm, inputs_for(c["spec"], data["media"]))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
