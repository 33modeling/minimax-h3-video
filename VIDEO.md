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

h3video gen "<Subject 1>이 손을 흔든다" --image me.png -s 6               # 사진 참고
h3video gen "프롬프트" --image a.png --video move.mp4 --audio voice.wav   # 사진·영상·소리 참고
```

- `--first`/`--last`: 준 그림이 영상의 첫·끝 장면이 된다.
- `--image`/`--video`/`--audio`: 사진(최대 9)·영상(3)·소리(3)를 참고해 얼굴·옷·움직임·목소리를 따라 한다. 레퍼런스 서버(`bash scripts/up.sh --ref`)로 알아서 보낸다. 둘은 다른 모델이라 같이 쓸 수 없다. (`h3video ref …` 도 그대로 된다)

## 2. 프롬프트 확인·수정

어떤 프롬프트든 그냥 넣으면 된다(한국어, 인터넷에서 받은 다른 양식, 파일 `-f`). 서버가 H3 공식 형식(영어)으로 바꿔서 만든다(요청마다 1분 정도 추가).
이미 공식 형식의 영어로 완성된 것만 그대로 쓴다.

```bash
h3video ir "프롬프트" -s 8 > p.txt     # 다듬은 프롬프트만 저장 (생성 안 함)
vi p.txt                               # 고치기
h3video gen -f p.txt --raw -s 8        # 고친 그대로 생성
```

- `--raw`: 바꾸지 않고 쓴 그대로 보낸다.
- 그림을 쓰는 요청이면 `ir` 과 `gen` 에 같은 `--first`/`--last`/`--image` 를 준다.
- 16초 이상이면 장면(5~15초)으로 나눠 이어 붙인다. 장면마다 어느 부분인지 알려 주고 바꾼다. 보내기 전 확인: `--dry-run`

## 3. 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-s` | 8 | 길이(초). 5~15초(4초는 5초로), 16초 이상은 장면을 이어 붙인다 |
| `-r` | 16:9 | 화면비: 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto |
| `--seed` | 0 | 같은 값이면 같은 결과, `random` 은 매번 다르게 |
| `--steps` | 50 | 줄이면 빠르고 거칠다 |
| `--size` | 768 | 짧은 변: 768(1344×768), 576(1024×576) 등. 줄이면 메모리·시간이 준다 |
| `-t` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o` | - | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--raw` | - | 프롬프트를 다듬지 않는다 |
| `--dry-run` | - | 보내지 않고 요청만 확인 |

## 4. GPU 메모리(OOM)

| 방식 | 한 장면 최대 (1344×768) |
|---|---|
| GPU 4장, `--ref` 없이 (영상 모델 3장 분할) | 15초 |
| GPU 2장씩 (`--ref` 를 같이 띄울 때) | 12초 |

- 서버가 요청마다 메모리를 미리 계산한다. 모자라면 생성하지 않고 바로 `GPU 메모리가 모자라 …` 와 함께 줄일 길이를 알려 준다.
- 더 긴 영상은 장면을 이어 붙인다: `-s 30 --scene-seconds 10`
- 해상도를 낮춰도 된다: `--size 576` (15초도 2장 방식에 들어간다).
- 길이와 상관없이 OOM 이 나면 다른 작업이 GPU 를 쓰는 것이다: `bash scripts/up.sh` 를 다시 띄우면 빈 GPU 만 쓴다.

## 5. 여러 개 (batch)

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

- 영상마다 `---` 로 나눈다. 블록 위쪽 `key: value` 가 그 영상의 옵션(`seconds` `ratio` `size` `seed` `title` `first` `last` `image` `video` `audio` `raw` …).

## 6. 결과

```
/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/
  <제목>.mp4            완성본 (영상 + 소리)
  scene01.prompt.txt    실제로 쓴 프롬프트
```

```bash
h3video jobs              # 지난 작업
h3video show last         # 마지막 작업 상세
```

## 7. 막히면

| 보이는 것 | 할 일 |
|---|---|
| 서버가 응답하지 않는다 | `bash scripts/status.sh` → 꺼져 있으면 `bash scripts/up.sh` |
| 프롬프트를 안 따른다 | `h3video ir` 로 확인 → 고쳐서 `--raw -f` |
| `GPU 메모리가 모자라 시작하지 않았다` | 메시지에 나온 대로 `-s` 줄이기 또는 `--size 576` (4절) |
| `out of memory` | 다른 작업이 GPU 를 쓰는 중 → `bash scripts/up.sh` 다시 (빈 GPU 만 쓴다) |
| `fl2va 는 … 만 받는다` / ref 서버 응답 없음 | 참고 자료(`--image` 등)는 `bash scripts/up.sh --ref` 필요 |
