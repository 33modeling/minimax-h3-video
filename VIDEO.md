# 사용법

## 순서

**창 1 — H3 서버** (계속 켜 둔다)

```bash
cd /user-volume/minimax-h3-video
bash scripts/up.sh            # 참고 자료(--image/--video/--audio)도 쓰면 --ref
```

`✓ fl2va 준비됨` 이 나오면 된다. 이 계정의 다른 작업이 GPU 를 쓰고 있으면 목록을 보여 주고 끌지 묻는다(y/N). 묻지 않고 끄려면 `--force`.

**창 2 — 영상 만들기**

```bash
cd /user-volume/minimax-h3-video && source scripts/cluster_env.sh
h3video gen prompt.txt -s 10
```

끝나면 결과 mp4 경로가 나온다.

**창 3 — 웹 UI** (필요할 때만)

```bash
bash scripts/web.sh
```

**끄기**: 창 1·창 3 에서 Ctrl+C. 다른 창에서는 `bash scripts/down.sh`(H3 서버), `bash scripts/web.sh --stop`(웹 UI).
H3 서버와 웹 UI 는 서로 안 건드린다. 만드는 중에는 창 1 의 `up.sh` 를 다시 실행하지 않는다(서버를 새로 띄워 작업이 끊긴다).

## 만들기

```bash
h3video gen prompt.txt -s 10                                       # 프롬프트 파일
h3video gen "비 오는 서울 밤거리, 네온이 젖은 길에 번진다" -s 8      # 글
h3video gen prompt.txt --first a.png -s 8                          # 이 그림에서 시작
h3video gen prompt.txt --last b.png -s 8                           # 이 그림으로 끝
h3video gen prompt.txt --first a.png --last b.png -s 8             # 처음·끝 둘 다
h3video gen "<Subject 1>이 손을 흔든다" --image me.png -s 6          # 사진 참고
h3video gen prompt.txt --image a.png --video m.mp4 --audio v.wav   # 사진·영상·소리 참고
```

- `--first`/`--last`: 그 그림이 영상의 실제 첫·끝 장면이 된다.
- `--image`/`--video`/`--audio`: 얼굴·옷·화풍·움직임·목소리를 참고한다. 창 1 을 `up.sh --ref` 로 띄웠을 때만. `--first`/`--last` 와 같이 못 쓴다.
- 참고 자료는 사진 9·영상 3·소리 3(합계 12)까지. 소리만 넣을 수는 없다. 프롬프트에서 넣은 순서대로 `<Subject 1>` `<Picture 1>` `<Video 1>` `<Audio 1>` 로 가리킨다.

## 프롬프트

대강 적어도 되고, 아무 형식이나 그냥 넣는다: 한국어, 인터넷에서 받은 양식(JSON·장면 나열·다른 모델용), 글이나 파일.
서버가 형식을 보고 판단해서, 빠진 것(카메라·조명·소리 등)을 채워 H3 공식 형식(영어)으로 다시 써서 만든다(1분 정도 더 걸린다). 이미 공식 형식의 영어로 완성된 것은 그대로 쓴다.

```bash
h3video ir prompt.txt -s 10 > p.txt    # 바꾼 결과만 보기 (생성 안 함)
h3video gen p.txt --raw -s 10          # 고친 p.txt 를 바꾸지 않고 그대로 생성
```

- 실제로 쓴 프롬프트는 결과 폴더의 `scene01.prompt.txt` 에 남는다.
- 대사는 따옴표로 그대로 적으면 그 언어로 말한다(한국어 등 11개 언어).

## 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-s 초` | 8 | 길이. 길면 알아서 장면으로 나눠 이어 붙인다 (아래 GPU·속도) |
| `--scene-seconds 초` | 10 | 이어 붙일 때 장면 하나 길이 (5~15) |
| `-r 비율` | 16:9 | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto(첫 그림 비율) |
| `--size 픽셀` | 768 | 짧은 변: 768·704·640·576·512 (768 = 1344×768). 줄이면 빨라지고 메모리를 덜 쓴다 |
| `--steps 숫자` | 50 | 줄이면 빠르고 거칠다 (30 이면 약 40% 빠름) |
| `--seed 숫자` | 0 | 같으면 같은 결과, `random` 은 매번 다르게 |
| `-t 제목` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o 경로` | - | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--raw` | - | 프롬프트를 바꾸지 않는다 |
| `--dry-run` | - | 보내지 않고 장면 나누기와 요청만 확인 |

## 여러 개 한 번에

`prompts.txt` — 영상마다 `---` 로 나누고, 블록 위쪽 `key: value` 가 그 영상의 옵션:

```text
title: seoul-rain
seconds: 8
비 오는 서울 밤거리, 네온이 젖은 길에 번진다.
---
title: fox
first: fox.png
size: 576
눈 속을 달리는 붉은 여우, 마지막에 카메라를 본다.
```

```bash
h3video batch prompts.txt -o ~/videos/
```

쓸 수 있는 key: `seconds` `ratio` `size` `seed` `steps` `title` `first` `last` `image` `video` `audio` `raw` `scene-seconds`

## GPU·속도

길이는 얼마든 된다. 서버가 GPU 를 보고 "한 장면 최대 몇 초"를 알려 주고, 그보다 길면 CLI 가 장면으로 나눈다. 다음 장면은 앞 장면의 마지막 프레임에서 시작하고, 끝나면 하나로 이어 붙인다. 그래서 길이 때문에 OOM 이 나지 않는다.

| 창 1 을 띄운 방식 | 한 장면 최대 (1344×768) | 예: `-s 15` | 예: `-s 40` |
|---|---|---|---|
| `bash scripts/up.sh` (빈 GPU 4장을 영상 하나에) | 15초 | 한 장면 | 10초 × 4 |
| `bash scripts/up.sh --ref` (2장씩 나눔) | 12초 (`--size 576` 이면 15초) | 8 + 7초 | 10초 × 4 |

나눌 때는 시작할 때 `이 서버 GPU 에서 한 장면은 최대 12초 → 15초를 장면 2개 [8, 7]로 만들어 이어 붙인다` 처럼 알려 준다. 장면 길이를 직접 정하려면 `--scene-seconds`.

- 진행 줄에 지금 단계가 나온다: `다듬는 중` → `생성 n%` → `디코딩`.
- 창 1 로그에 요청마다 `걸린 시간: 다듬기 … · 디노이징 …(스텝당 …초) · 디코딩 …` 이 찍힌다. 빠르게: `--steps 30`, `--size 576`, 다듬기 생략 `--raw`.
- 참고 자료가 많거나 길면 한 장면 최대 길이가 그만큼 줄어든다(자동 반영). 그래도 OOM 이 나면 그 작업만 실패하고 할 일(`--size 576` 등)을 알려 준다.

## 결과

```
/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/
  <제목>.mp4            완성본 (영상 + 32kHz 스테레오 소리)
  scene01.mp4 …         장면별
  scene01.prompt.txt    실제로 쓴 프롬프트
```

```bash
h3video jobs                          # 지난 작업
h3video show last                     # 마지막 작업 상세
h3video fetch <video_id> -o a.mp4     # 서버에 남은 완성본 받기 (참고 자료 영상은 --ref)
```

## 막히면

| 보이는 것 | 할 일 |
|---|---|
| `서버가 응답하지 않는다` / `Connection refused` | 창 1 이 꺼졌다 → `bash scripts/up.sh` |
| 참고 자료 요청이 안 된다 | 창 1 을 `bash scripts/up.sh --ref` 로 |
| 프롬프트를 안 따른다 | `h3video ir` 로 바뀐 결과를 보고 고쳐서 `--raw` |
| `GPU 메모리 부족(OOM)` | 메시지대로 `-s` 줄이기 또는 `--size 576` |
| GPU 가 다른 작업에 잡혀 있다 | 창 1 의 질문에 y, 또는 `bash scripts/up.sh --force` |
| 그 밖에 | `bash scripts/diagnose.sh` 출력을 붙여 준다 |

서버 설치·운영(처음 설치, 저장 위치, 환경 변수)은 [USAGE.md](USAGE.md).
