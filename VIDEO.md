# 영상 만들기 사용법

## 1. 서버

```bash
cd /user-volume/minimax-h3-video
bash scripts/up.sh            # 서버 띄우기 (이 화면에 로그, 끄기는 Ctrl+C)
bash scripts/up.sh --ref      # 참고 자료(--image/--video/--audio)도 쓸 때
bash scripts/status.sh        # 다른 창에서 확인: "준비됨 ✓"
bash scripts/down.sh          # 다른 창에서 끄기
```

영상은 다른 창에서 만든다. 새 창마다 먼저:

```bash
cd /user-volume/minimax-h3-video && source scripts/cluster_env.sh
```

## 2. 만들기

```bash
h3video gen "비 오는 서울 밤거리, 네온이 젖은 길에 번진다" -s 8      # 글 → 영상
h3video gen prompt.txt -s 8                                          # 프롬프트 파일 (파일 이름만 주면 된다)
h3video gen "프롬프트" --first a.png -s 8                            # 이 그림에서 시작
h3video gen "프롬프트" --last b.png -s 8                             # 이 그림으로 끝
h3video gen "프롬프트" --first a.png --last b.png -s 8               # 처음·끝 둘 다
h3video gen "<Subject 1>이 손을 흔든다" --image me.png -s 6           # 사진 참고
h3video gen "프롬프트" --image a.png --video m.mp4 --audio v.wav -s 8 # 사진·영상·소리 참고
```

- `--first`/`--last`: 그 그림이 영상의 실제 첫·끝 장면이 된다.
- `--image`/`--video`/`--audio`: 얼굴·옷·화풍·움직임·목소리를 참고한다. `up.sh --ref` 로 띄웠을 때만. `--first`/`--last` 와 같이 쓸 수 없다.
- 참고 자료는 사진 9·영상 3·소리 3(합계 12)까지, 소리만 넣을 수는 없다. 프롬프트에서 넣은 순서대로 `<Subject 1>` `<Picture 1>` `<Video 1>` `<Audio 1>` 로 가리킨다.
- 끝나면 결과 mp4 경로가 나온다.

## 3. 프롬프트

아무 형식이나 그냥 넣으면 된다(한국어, 인터넷에서 받은 JSON·장면 나열·다른 모델용 양식, 글이나 파일). 서버가 형식을 보고 알아서 판단한다:
H3 공식 형식의 영어로 완성된 것만 그대로 쓰고, 나머지는 공식 형식(영어)으로 바꿔서 만든다(바꿀 때 1분 정도 더 걸린다).

```bash
h3video ir prompt.txt -s 8 > p.txt     # 바꾼 결과만 보기 (생성 안 함)
h3video gen p.txt --raw -s 8           # 고친 p.txt 를 그대로 생성
```

- `--raw`: 바꾸지 않고 쓴 그대로 보낸다. 이미 공식 형식의 영어로 완성된 프롬프트는 `--raw` 없이도 그대로 쓴다.
- 그림·참고 자료가 있으면 `ir` 에도 같은 `--first`/`--last`/`--image` 를 준다.
- 실제로 쓴 프롬프트는 결과 폴더의 `scene01.prompt.txt` 에 남는다.
- 대사는 따옴표로 그대로 적으면 그 언어로 말한다(한국어 등 11개 언어).

## 4. 옵션

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-s 초` | 8 | 길이. 한 장면 5~15초. 16초 이상은 장면을 나눠 이어 붙인다 |
| `--scene-seconds 초` | 10 | 이어 붙일 때 장면 하나 길이 (5~15) |
| `-r 비율` | 16:9 | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto(첫 그림 비율) |
| `--size 픽셀` | 768 | 짧은 변: 768·704·640·576·512 (768 = 1344×768). 줄이면 메모리·시간이 준다 |
| `--seed 숫자` | 0 | 같으면 같은 결과, `random` 은 매번 다르게 |
| `--steps 숫자` | 50 | 줄이면 빠르고 거칠다 |
| `-t 제목` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o 경로` | - | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--raw` | - | 프롬프트를 바꾸지 않는다 |
| `--dry-run` | - | 보내지 않고 장면 나누기와 요청만 확인 |

## 5. 여러 개 한 번에

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

## 6. GPU 메모리

| 띄운 방식 | 한 장면 최대 (1344×768) |
|---|---|
| `bash scripts/up.sh` (GPU 4장을 영상 하나에) | 15초 |
| `bash scripts/up.sh --ref` (2장씩 나눔) | 12초, `--size 576` 이면 15초 |

- 서버 로그의 `메모리 예상` 은 참고용이다. 모자랄 것 같으면 `[경고]` 만 남기고 그대로 만든다. 실제로 OOM 이 나면 그 작업만 실패하고 할 일(`-s` 줄이기·`--size 576`)을 알려 준다.
- 길이와 상관없이 OOM 이 나면 다른 작업이 GPU 를 쓰는 것이다. `up.sh` 를 다시 띄우면 빈 GPU 만 쓴다.

## 7. 결과

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

## 8. 막히면

| 보이는 것 | 할 일 |
|---|---|
| `서버가 응답하지 않는다` | `bash scripts/status.sh` → 꺼져 있으면 `bash scripts/up.sh` |
| 참고 자료 요청이 안 된다 | `bash scripts/up.sh --ref` 로 띄운다 |
| 프롬프트를 안 따른다 | `h3video ir` 로 바뀐 결과 확인 → 고쳐서 `--raw` |
| `GPU 메모리 부족(OOM)` | 메시지대로 `-s` 줄이기 또는 `--size 576` (6절) |
| 느리다 | 서버 로그의 `걸린 시간: 다듬기 … 디노이징 …(스텝당 …초)` 를 본다. 빠르게: `--steps 30`, `--size 576`, 다듬기 생략 `--raw` |
| `out of memory` | 다른 작업이 GPU 사용 중 → `bash scripts/up.sh` 다시 |
| 생성 중 서버가 끝났다 | `up.sh` 화면의 바로 위 오류를 확인한다 |
