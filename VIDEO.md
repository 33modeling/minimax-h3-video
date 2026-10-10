# 영상 만들기 사용법

## 0. 시작

```bash
cd /user-volume/minimax-h3-video
source scripts/cluster_env.sh     # 새 창마다
bash scripts/status.sh            # fl2va "준비됨 ✓" 확인 (꺼져 있으면 bash scripts/up.sh)
```

## 1. 만들기

```bash
h3video gen "프롬프트" -s 8                              # 글 → 영상
h3video gen "프롬프트" --first a.png -s 8                # 이 그림에서 시작
h3video gen "프롬프트" --last b.png -s 8                 # 이 그림으로 끝
h3video gen "프롬프트" --first a.png --last b.png -s 8   # 처음·끝 둘 다
h3video gen -f prompt.txt -s 10                          # 프롬프트를 파일로

h3video ref "<Subject 1>이 손을 흔든다" --image me.png -s 6               # 사진 참고
h3video ref "프롬프트" --image a.png --video move.mp4 --audio voice.wav   # 사진·영상·소리 참고
```

- `gen`: 준 그림이 영상의 첫·끝 장면이 된다.
- `ref`: 사진(최대 9)·영상(3)·소리(3)를 참고해 얼굴·옷·움직임·목소리를 따라 한다. `bash scripts/up.sh --ref` 로 띄웠을 때만.

## 2. 프롬프트 확인·수정

서버가 프롬프트를 공식 형식으로 다듬어서 만든다(요청마다 1분 정도 추가).

```bash
h3video ir "프롬프트" -s 8 > p.txt     # 다듬은 프롬프트만 저장 (생성 안 함)
vi p.txt                               # 고치기
h3video gen -f p.txt --raw -s 8        # 고친 그대로 생성
```

- `--raw`: 다듬지 않고 쓴 그대로 보낸다.
- 그림을 쓰는 요청이면 `ir` 과 `gen` 에 같은 `--first`/`--last`/`--image` 를 준다.

## 3. 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-s` | 8 | 길이(초). 5~15초, 16초 이상은 장면을 이어 붙인다 |
| `-r` | 16:9 | 화면비: 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto |
| `--seed` | 0 | 같은 값이면 같은 결과, `random` 은 매번 다르게 |
| `--steps` | 50 | 줄이면 빠르고 거칠다 |
| `-t` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o` | - | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--raw` | - | 프롬프트를 다듬지 않는다 |
| `--dry-run` | - | 보내지 않고 요청만 확인 |

## 4. 여러 개 (batch)

```text
title: seoul-rain
seconds: 8
비 오는 서울 밤거리, 네온이 젖은 길에 번진다.
---
title: fox
first: fox.png
눈 속을 달리는 붉은 여우, 마지막에 카메라를 본다.
```

```bash
h3video batch prompts.txt -o ~/videos/
```

- 영상마다 `---` 로 나눈다. 블록 위쪽 `key: value` 가 그 영상의 옵션(`seconds` `ratio` `seed` `title` `first` `last` `image` `video` `audio` `raw` …).

## 5. 결과

```
/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/
  <제목>.mp4            완성본 (영상 + 소리)
  scene01.prompt.txt    실제로 쓴 프롬프트
```

```bash
h3video jobs              # 지난 작업
h3video show last         # 마지막 작업 상세
```

## 6. 막히면

| 보이는 것 | 할 일 |
|---|---|
| 서버가 응답하지 않는다 | `bash scripts/status.sh` → 꺼져 있으면 `bash scripts/up.sh` |
| 프롬프트를 안 따른다 | `h3video ir` 로 확인 → 고쳐서 `--raw -f` |
| `out of memory` | `bash scripts/up.sh` 다시 (빈 GPU 만 쓴다) |
| `fl2va 는 … 만 받는다` | `ref` 는 `bash scripts/up.sh --ref` 필요 |
