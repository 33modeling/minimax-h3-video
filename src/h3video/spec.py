"""MiniMax-H3 공식 사양 (github.com/MiniMax-AI/MiniMax-H3 README 기준, 2026-08 공개판)."""

MODEL_ID = "MiniMaxAI/MiniMax-H3"
DURATION_MIN = 4          # 초
DURATION_MAX = 15         # 초 — 단일 생성 상한. 더 길면 장면 체인(chain)으로 이어 붙인다
FPS = 24
SHORT_EDGE_DEFAULT = 768  # 로컬 H3-Base 는 768p. 2K 는 공식 API(H3-Regenerate-2K) 전용
AUDIO = "32 kHz stereo (음성·효과음·음악 동시 생성)"
ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto"]
TASKS = {
    "t2va": "텍스트 → 영상+오디오",
    "fl2va": "첫/끝 프레임 이미지(0~2장) + 텍스트 → 영상+오디오",
    "ref2va": "레퍼런스(이미지≤9, 영상≤3, 오디오≤3, 합계≤12) + 텍스트 → 영상+오디오",
}
REF_LIMITS = {"image": 9, "video": 3, "audio": 3, "total": 12, "clip_seconds": (2, 15), "clip_total_seconds": 15}
LANGUAGES = "한국어 포함 11개 언어 대사 안정 지원"
STEPS_DEFAULT = 50
PARAMS = "33B dense transformer (추론 시 ~20B 로드), BF16, 권장 배치: H100 4장 (--num-gpus 4 --ulysses-degree 4)"


def clamp_duration(seconds) -> int:
    s = int(round(float(seconds)))
    return max(DURATION_MIN, min(DURATION_MAX, s))


def plan_scenes(total_seconds: float, scene_seconds: int = 10) -> list[int]:
    """총 길이를 장면들로 균등 분할. 15초 이하면 한 장면. 모든 장면은 4~15초."""
    import math
    scene_seconds = clamp_duration(scene_seconds)
    total = max(DURATION_MIN, int(round(total_seconds)))
    if total <= DURATION_MAX:
        return [total]
    n = math.ceil(total / scene_seconds)
    base, rem = divmod(total, n)
    return [base + 1] * rem + [base] * (n - rem)


def summary() -> str:
    return (
        f"모델: {MODEL_ID}\n"
        f"한 번에 만들 수 있는 길이: {DURATION_MIN}~{DURATION_MAX}초 (그 이상은 장면 체인으로 연결)\n"
        f"해상도: 짧은 변 {SHORT_EDGE_DEFAULT}px (2K 는 공식 API 재생성 전용), {FPS}fps\n"
        f"오디오: {AUDIO}\n"
        f"화면비: {', '.join(ASPECT_RATIOS)}\n"
        f"모드: " + "; ".join(f"{k}={v}" for k, v in TASKS.items()) + "\n"
        f"하드웨어: {PARAMS}\n"
        f"언어: {LANGUAGES}"
    )
