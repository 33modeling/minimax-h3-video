"""Diffusers 형식 H3 폴더가 다 받아졌는지 확인한다 (설정 파일·샤드 전부). 빠진 것을 출력하고 0/1 로 끝난다.

  python scripts/check_diffusers_model.py DIR [--variant fl2va|ref2va]
"""
import argparse
import json
import sys
from pathlib import Path

NEED = {"fl2va": ["text_encoder", "tokenizer", "processor", "vae", "audio_vae", "scheduler", "audio_scheduler", "transformer"],
        "ref2va": ["text_encoder", "tokenizer", "processor", "vae", "audio_vae", "scheduler", "audio_scheduler", "transformer_ref"]}


def missing(root: Path, variant: str) -> list[str]:
    out = []
    if not (root / "modular_model_index.json").is_file():
        out.append("modular_model_index.json")
    for comp in NEED[variant]:
        d = root / comp
        if not d.is_dir():
            out.append(f"{comp}/")
            continue
        for idx in d.glob("*.safetensors.index.json"):   # 샤드 목록에 있는 파일이 전부 있어야 한다 (받다 끊긴 경우)
            shards = set(json.loads(idx.read_text()).get("weight_map", {}).values())
            out += [f"{comp}/{s}" for s in sorted(shards) if not (d / s).is_file()]
        if comp in ("transformer", "transformer_ref", "vae", "audio_vae", "text_encoder") and not any(d.glob("*.safetensors")):
            out.append(f"{comp}/*.safetensors")
        if not any(d.glob("*.json")):
            out.append(f"{comp}/*.json")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--variant", choices=sorted(NEED), default="fl2va")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    miss = missing(Path(a.dir), a.variant)
    if miss and not a.quiet:
        print(f"[model] Diffusers 형식 H3({a.variant}) 에 빠진 것 {len(miss)}개: {a.dir}")
        for m in miss[:12]:
            print(f"   - {m}")
        if len(miss) > 12:
            print(f"   … 외 {len(miss) - 12}개")
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
