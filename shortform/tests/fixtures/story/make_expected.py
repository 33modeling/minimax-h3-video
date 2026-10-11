"""cases.json 의 기대 결과(expected.json)를 파이썬 변환기로 다시 만든다. 규칙을 바꿨을 때만 돌리고, 바뀐 결과를 눈으로 확인한 뒤 커밋한다.
  python3 tests/fixtures/story/make_expected.py"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from shorts.story import story_to_spec  # noqa: E402

cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
out = [dict(zip(("spec", "info"), story_to_spec(c["data"], c["images"], narration=c["narration"], local_paths=False))) for c in cases]
(HERE / "expected.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"{len(out)}개 → {HERE / 'expected.json'}")
