"""짧은 요청 → MiniMax H3 공식 프롬프트 형식(H3-Context-IR) 다듬기.

H3-Base 는 영어로 샷·카메라·인물·동작·소리를 자세히 풀어 쓴 프롬프트로 학습됐다. 공식은 이 변환을 호스팅 API(H3-Context-IR)로만
제공하고, 대신 작성 가이드(VIDEO_PROMPT_WRITING_GUIDE_base_en.md / _ref_en.md — 공식 스킬 h3-prompt-writing 의
references/base-en.txt·ref-en.txt 와 같은 내용)를 공개했다. 서버에 이미 올라가 있는 텍스트 인코더가 Qwen3-VL-32B-Instruct 원본과
같은 파일이라(HF 해시 14개 샤드 일치), 그 모델로 가이드를 따라 다시 쓴다. 첫 프레임·레퍼런스 그림은 모델이 직접 본다.

이 파일은 모델 없이 도는 부분(지시문·정렬 줄·출력 검사)과 생성 함수(rewrite_with_model)로 나뉜다.
"""
from __future__ import annotations

import re

BASE_FIELDS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
REF_FIELDS = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
              "overall_soundscape", "non_diegetic_music")
# 키프레임 정렬 줄 (가이드 2.1). 클라이언트가 붙여 보낸 옛 형식까지 지운 뒤 서버가 실제 길이로 다시 붙인다
_INSTRUCTION = re.compile(r"^\s*(For the target video, at 0\.00 seconds|How the reference pictures align|At the final frame of the target video)")

RULES = """You are a prompt writer for the MiniMax H3 audio-video generation model.
Rewrite the user's request into the exact final prompt format defined in the guide below, as the official H3-Context-IR step would.

Output rules (from the official h3-prompt-writing skill):
- Write the sections in English; preserve dialogue, lyrics, and visible scene text in their original language (for example Korean).
- Describe each shot by composition, subjects, environment, actions, camera, sound, and the exact point where referenced content appears.
- Avoid plot summaries, unresolved reference labels, and timing that does not match the requested duration.
- Always match the total duration of the description to the requested video length.
- Keep reference labels consistent (e.g. <Picture 1>, <Video 1>, <Audio 1>) across every section.
- Prefer concrete visual and audio details over abstract words like "cinematic" or "beautiful".
- Keep everything the user asked for; add only details that make the request concrete. Do not change the subject, setting, or story.
- Output ONLY the final prompt text. No explanations, no headings, no markdown, no code fences.

=== GUIDE ===
"""


def mode_name(task: str, slots: list[str]) -> str:
    if task == "ref2va":
        return "Ref2VA"
    if not slots:
        return "T2VA"
    if slots == ["image"]:
        return "I2VA"
    if slots == ["last_image"]:
        return "L2VA"
    return "FL2VA"


def strip_instruction(prompt: str) -> str:
    lines = prompt.strip().splitlines()
    while lines and (_INSTRUCTION.match(lines[0]) or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def already_written(prompt: str, task: str) -> bool:
    """사용자가 이미 공식 형식으로 썼으면 다시 쓰지 않는다."""
    first = (REF_FIELDS if task == "ref2va" else BASE_FIELDS)[0]
    return re.search(rf"(^|\n)\s*{first}\s*:", strip_instruction(prompt)) is not None


def max_shot(text: str) -> int:
    return max([int(n) for n in re.findall(r"\[Shot (\d+)\]", text)] or [1])


def instruction(slots: list[str], seconds: float, shots: int) -> str | None:
    """키프레임 정렬 줄 (가이드 2.1 의 문구 그대로). seconds 는 실제로 만들어지는 영상 길이."""
    mode = mode_name("fl2va", slots)
    if mode == "I2VA":
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if mode == "FL2VA":
        return ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second "
                f"mark of the target video; Picture 2 (from Shot {shots}) aligns with the {seconds:.2f}-second mark of the target video.")
    if mode == "L2VA":
        return (f"How the reference pictures align with the target video — <Picture 1> (from [Shot {shots}]) aligns with the "
                f"{seconds:.2f}-second mark of the target video.")
    return None


def extract(text: str, task: str) -> str | None:
    """모델 출력에서 최종 프롬프트만 꺼낸다. 필드가 순서대로 다 있어야 한다 (없으면 None)."""
    fields = REF_FIELDS if task == "ref2va" else BASE_FIELDS
    t = re.sub(r"```[a-zA-Z]*", "", text).replace("**", "").strip()
    pos = []
    for f in fields:
        m = re.search(rf"(^|\n)\s*{f}\s*:", t[pos[-1] if pos else 0:])
        if not m:
            return None
        pos.append((pos[-1] if pos else 0) + m.start() + len(m.group(1)))
    body = t[pos[0]:].strip()
    last = re.search(rf"(^|\n)\s*{fields[-1]}\s*:[^\n]*", body)
    if last is None or len(last.group(0).split(":", 1)[1].strip()) == 0:
        return None
    return body


def user_text(mode: str, seconds: float, prompt: str, labels: list[str]) -> str:
    lines = [f"Mode: {mode}", f"Target duration: {seconds:.2f} seconds (24 fps)."]
    if labels:
        lines.append("Inputs (labels are fixed, use them exactly): " + "; ".join(labels))
    if mode in ("I2VA", "FL2VA", "L2VA"):
        lines.append("Do NOT write the picture alignment instruction line; it is added automatically. "
                     "Start directly with `integrated_multimodal_description:`.")
    elif mode == "Ref2VA":
        lines.append("Start directly with `subject_definitions:` and write all six sections in order.")
    else:
        lines.append("Start directly with `integrated_multimodal_description:`.")
    lines.append("User request:\n" + prompt.strip())
    return "\n".join(lines)


def rewrite_with_model(text_encoder, processor, device, guide: str, mode: str, seconds: float, prompt: str,
                       visuals: list[tuple[str, object]], labels: list[str], seed: int = 0,
                       max_new_tokens: int = 2048) -> str:
    """Qwen3-VL 로 다시 쓴 원문(검사 전)을 돌려준다. visuals = [(설명, PIL 이미지)] — 모델이 직접 본다."""
    import torch
    content = []
    for caption, img in visuals:
        content.append({"type": "text", "text": caption})
        content.append({"type": "image", "image": img})
    content.append({"type": "text", "text": user_text(mode, seconds, prompt, labels)})
    messages = [{"role": "system", "content": [{"type": "text", "text": RULES + guide}]},
                {"role": "user", "content": content}]
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt").to(device)
    torch.manual_seed(seed)
    with torch.no_grad():
        out = text_encoder.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7,
                                    top_p=0.8, top_k=20, repetition_penalty=1.05)
    return processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]


def small(img, longest: int = 1024):
    """다듬기용으로만 줄인다 (그림 토큰 수 제한). 생성에는 원본을 쓴다."""
    img = img.convert("RGB")
    w, h = img.size
    s = longest / max(w, h)
    return img.resize((max(28, int(w * s)), max(28, int(h * s)))) if s < 1 else img
