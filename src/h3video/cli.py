"""CLI: h3video spec | health | plan | gen | ref | status | fetch | web | tui"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import prompt as P
from . import spec
from .client import DEFAULT_ENDPOINT, DEFAULT_REF_ENDPOINT, Condition, H3Client, H3Error, VideoRequest, stage_input
from .jobs import INBOX_DIR, OUTPUT_DIR, JobStore, Worker, new_job, slugify


def _progress(st):
    print(f"  [{time.strftime('%H:%M:%S')}] {st.get('status')} {round(float(st.get('progress') or 0) * 100)}%", flush=True)


def cmd_spec(a):
    print(spec.summary())


def cmd_plan(a):
    scenes = spec.plan_scenes(a.seconds, a.scene_seconds)
    print(f"{a.seconds}초 → 장면 {len(scenes)}개: {scenes} (첫 장면 {'fl2va' if a.first else 't2va'}, 이후 fl2va 체인)")


def cmd_health(a):
    for name, ep in (("fl2va", a.endpoint), ("ref2va", a.ref_endpoint)):
        print(f"{name} {ep}: {'OK' if H3Client(ep).healthy() else '응답 없음'}")


def _run_job(a, job):
    store = JobStore(Path(a.output_dir))
    w = Worker(store, H3Client(a.endpoint), H3Client(a.ref_endpoint), inbox_dir=a.inbox_dir, poll=a.poll)
    w.enqueue(job)
    w.start()
    print(f"job {job.id} 시작 (총 {job.total_seconds}초)")
    last = None
    while True:
        time.sleep(1)
        jb = store.get(job.id)
        line = f"{jb.status} " + " ".join(f"s{s.index + 1}:{s.status}/{round(s.progress * 100)}%" for s in jb.scenes)
        if line != last:
            print(f"  [{time.strftime('%H:%M:%S')}] {line}", flush=True)
            last = line
        if jb.status in ("completed", "failed"):
            break
    if jb.status == "failed":
        print(f"실패: {jb.error}", file=sys.stderr)
        sys.exit(1)
    print(f"완료: {jb.output}")


def cmd_gen(a):
    prompt = Path(a.prompt_file).read_text() if a.prompt_file else a.prompt
    if not prompt:
        sys.exit("프롬프트가 필요하다 (인자 또는 --prompt-file)")
    if a.ir:
        prompt = P.build_context_ir(prompt, a.soundscape, a.music)
    job = new_job(prompt, seconds=a.seconds, aspect_ratio=a.ratio, seed=a.seed, first_image=a.first,
                  last_image=a.last, scene_seconds=a.scene_seconds, steps=a.steps, title=a.title or "")
    _run_job(a, job)


def cmd_ref(a):
    refs = [{"type": "image", "path": p} for p in a.image] + [{"type": "video", "path": p} for p in a.video] \
        + [{"type": "audio", "path": p} for p in a.audio]
    if not refs:
        sys.exit("--image/--video/--audio 중 하나 이상 필요")
    job = new_job(a.prompt, seconds=a.seconds, aspect_ratio=a.ratio, seed=a.seed, task="ref2va", refs=refs,
                  scene_seconds=a.scene_seconds, steps=a.steps, title=a.title or "")
    _run_job(a, job)


def cmd_status(a):
    print(json.dumps(H3Client(a.endpoint).status(a.video_id), ensure_ascii=False, indent=2))


def cmd_fetch(a):
    out = H3Client(a.endpoint).download(a.video_id, a.out or f"{a.video_id}.mp4")
    print(out)


def cmd_web(a):
    from .web import serve
    serve(host=a.host, port=a.port, endpoint=a.endpoint, ref_endpoint=a.ref_endpoint,
          output_dir=Path(a.output_dir), inbox_dir=a.inbox_dir, poll=a.poll, cors_origin=a.cors_origin)


def cmd_tui(a):
    from .tui import run
    run(a.endpoint, a.ref_endpoint, Path(a.output_dir), a.inbox_dir, a.poll)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="h3video", description="MiniMax-H3 영상 생성 클라이언트")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="fl2va/t2va SGLang 서버")
    ap.add_argument("--ref-endpoint", default=DEFAULT_REF_ENDPOINT, help="ref2va SGLang 서버")
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR))
    ap.add_argument("--inbox-dir", default=INBOX_DIR, help="서버가 file:// 로 읽을 수 있는 공유 폴더")
    ap.add_argument("--poll", type=float, default=3.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spec", help="모델 사양").set_defaults(fn=cmd_spec)
    sub.add_parser("health", help="서버 응답 확인").set_defaults(fn=cmd_health)
    p = sub.add_parser("plan", help="길이 → 장면 분할 미리보기"); p.add_argument("seconds", type=int)
    p.add_argument("--scene-seconds", type=int, default=10); p.add_argument("--first"); p.set_defaults(fn=cmd_plan)

    def common(p):
        p.add_argument("--seconds", type=int, default=8, help="총 길이(초). 15 초과 시 장면 체인")
        p.add_argument("--ratio", default="16:9", choices=spec.ASPECT_RATIOS)
        p.add_argument("--seed", type=int, default=0)
        p.add_argument("--scene-seconds", type=int, default=10)
        p.add_argument("--steps", type=int)
        p.add_argument("--title")

    p = sub.add_parser("gen", help="텍스트(+첫/끝 프레임) → 영상"); p.add_argument("prompt", nargs="?")
    p.add_argument("--prompt-file"); p.add_argument("--first", help="첫 프레임 이미지"); p.add_argument("--last", help="끝 프레임 이미지")
    p.add_argument("--ir", action="store_true", help="Context-IR 3단 형식으로 감싸기"); p.add_argument("--soundscape"); p.add_argument("--music")
    common(p); p.set_defaults(fn=cmd_gen)
    p = sub.add_parser("ref", help="레퍼런스 → 영상 (ref2va)"); p.add_argument("prompt")
    p.add_argument("--image", action="append", default=[]); p.add_argument("--video", action="append", default=[])
    p.add_argument("--audio", action="append", default=[]); common(p); p.set_defaults(fn=cmd_ref)
    p = sub.add_parser("status"); p.add_argument("video_id"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("fetch"); p.add_argument("video_id"); p.add_argument("--out"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("web", help="로컬호스트 웹 UI"); p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("H3_WEB_PORT", 8790)))
    p.add_argument("--cors-origin", default=None,
                   help="이 서버를 부를 수 있는 웹 출처(쉼표 구분, * 는 전부). 기본 끔. 환경변수 H3_CORS_ORIGIN")
    p.set_defaults(fn=cmd_web)
    sub.add_parser("tui", help="터미널 UI (tmux 안에서)").set_defaults(fn=cmd_tui)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except H3Error as e:
        sys.exit(f"오류: {e}")


if __name__ == "__main__":
    main()
