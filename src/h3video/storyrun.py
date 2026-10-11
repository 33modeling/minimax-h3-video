"""JSON 한번에 만들기의 기록·작업·이어 붙이기 (CLI `h3video json` 과 웹 UI 가 같이 쓴다).

결과 폴더(H3_OUTPUT_DIR) 아래 story-<시각>-<id>/story.json 에 장면마다 어느 작업(job)인지, 결과·오류를 남긴다.
장면이 전부 끝나면 쪽 순서대로 이어 붙여 story-.../<제목>.mp4 하나를 만든다. 실패한 장면만 다시: h3video json --resume.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from .client import H3Error
from .jobs import Job, JobStore, concat_videos, new_job, slugify
from .story import Story

STATE = "story.json"
_join_lock = threading.Lock()


def new_story_dir(root: Path) -> Path:
    d = Path(root) / f"story-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def find_story_dir(root: Path, name: str) -> Path:
    """폴더 경로, story-... 이름(앞부분), 또는 last."""
    p = Path(name).expanduser()
    if (p / STATE).is_file():
        return p
    dirs = sorted((d for d in Path(root).glob("story-*") if (d / STATE).is_file()), key=lambda d: d.name)
    if name == "last" and dirs:
        return dirs[-1]
    hit = [d for d in dirs if d.name.startswith(name) or d.name.endswith(name)]
    if len(hit) == 1:
        return hit[0]
    raise H3Error(f"JSON 작업 폴더를 찾지 못했다: {name} (예: h3video json --resume last)")


def load_state(d: Path) -> dict:
    return json.loads((Path(d) / STATE).read_text(encoding="utf-8"))


def save_state(d: Path, state: dict) -> None:
    tmp = Path(d) / (STATE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(Path(d) / STATE)


def initial_state(story: Story, params: dict) -> dict:
    return {"title": story.title, "ratio": story.ratio, "source": story.source, "params": params, "created": time.time(),
            "clips": [dict(c, job_id=None, output=None, error=None) for c in story.to_json()["clips"]],
            "unused_images": story.unused_images, "output": None}


def jobs_for(state: dict, only: set[str] | None = None) -> list[Job]:
    """아직 결과가 없는 장면(또는 only 로 고른 장면)마다 작업을 하나씩 만든다. 장면 길이는 JSON 에서 정한 값."""
    p = state["params"]
    out = []
    for c in state["clips"]:
        if (only and c["id"] not in only) or (not only and c.get("output")):
            continue
        job = new_job(c["prompt"], seconds=c["seconds"], aspect_ratio=state["ratio"], seed=int(c.get("seed") or 0),
                      first_image=c.get("image"), steps=p.get("steps"), negative=p.get("negative"), raw=bool(p.get("raw")),
                      short_edge=int(p.get("size") or 768), title=f"{slugify(state['title'], 24)}-{c['id']}")
        c.update(job_id=job.id, output=None, error=None)
        out.append(job)
    return out


def refresh(d: Path, state: dict, store: JobStore) -> dict:
    """작업 기록에서 장면별 상태를 읽어 오고, 전부 끝났으면 이어 붙인다. 바뀌면 저장한다."""
    changed = False
    for c in state["clips"]:
        jb = store.get(c["job_id"]) if c.get("job_id") else None
        if not jb:
            continue
        st = {"status": jb.status, "output": jb.output if jb.status == "completed" else None,
              "error": jb.error if jb.status == "failed" else None,
              "progress": (sum((1 if s.status == "completed" else s.progress) for s in jb.scenes) / len(jb.scenes)) if jb.scenes else 0}
        if any(c.get(k) != v for k, v in st.items()):
            c.update(st)
            changed = True
    if not state.get("output") and state["clips"] and all(c.get("output") for c in state["clips"]):
        with _join_lock:
            parts = [Path(c["output"]) for c in state["clips"]]
            final = Path(d) / f"{slugify(state['title'])}.mp4"
            if len(parts) == 1:
                final.write_bytes(parts[0].read_bytes())
            else:
                concat_videos(parts, final)
            state["output"] = str(final)
            changed = True
    if changed:
        save_state(d, state)
    return state


def summary(state: dict) -> dict:
    done = sum(1 for c in state["clips"] if c.get("output"))
    failed = sum(1 for c in state["clips"] if c.get("error"))
    return {"done": done, "failed": failed, "total": len(state["clips"]),
            "seconds": sum(c["seconds"] for c in state["clips"]), "output": state.get("output")}
