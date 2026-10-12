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

끝나면 `결과 파일:` 아래에 mp4 경로가 나온다(`--open` 이면 바로 재생). 기다리는 동안 한 줄에 경과 시간·장면 i/n·단계가 나오고, Ctrl+C 로 멈추면 이어 하는 명령을 알려 준다.

**창 3 — 웹 UI** (필요할 때만)

```bash
bash scripts/web.sh
```

**끄기**: 창 1·창 3 에서 Ctrl+C. 다른 창에서는 `bash scripts/down.sh`(H3 서버), `bash scripts/web.sh --stop`(웹 UI).
H3 서버와 웹 UI 는 서로 안 건드린다. 만드는 중에는 창 1 의 `up.sh` 를 다시 실행하지 않는다(서버를 새로 띄워 작업이 끊긴다).

## 처음이면

```bash
h3video                                             # 자주 쓰는 명령 몇 개
h3video doctor                                      # 서버가 켜졌는지, 안 되면 할 일
h3video config set endpoint http://127.0.0.1:30010  # 서버 주소를 한 번 저장 (H3_ENDPOINT 없이)
```

명령을 빼도 알아서 고른다(무엇으로 골랐는지 한 줄 나온다):

| 이렇게 쓰면 | 이렇게 실행 |
|---|---|
| `h3video "비 오는 밤거리" -s 8` | `h3video gen "비 오는 밤거리" -s 8` |
| `h3video 사진.png "웃는다" -s 6` | `h3video gen "웃는다" --first 사진.png -s 6` (그림 두 장이면 둘째는 `--last`) |
| `h3video 토토.json pages/` | `h3video json 토토.json pages/` |

`t2v`·`i2v`→`gen`, `ref2va`→`ref`, `story`→`json`, `list`→`jobs` 도 알아듣고, 명령 이름이 틀리면 비슷한 명령을 알려 준다. 명령마다 예시: `h3video gen --help`.

## 만들기

```bash
h3video gen prompt.txt -s 10                                       # 프롬프트 파일
h3video gen "비 오는 서울 밤거리, 네온이 젖은 길에 번진다" -s 8      # 글
h3video gen prompt.txt --first a.png -s 8                          # 이 그림에서 시작
h3video gen prompt.txt --last b.png -s 8                           # 이 그림으로 끝
h3video gen prompt.txt --first a.png --last b.png -s 8             # 처음·끝 둘 다
h3video gen "1번 사진 사람이 손을 흔든다" --image me.png -s 6        # 사진 참고
h3video gen prompt.txt --image a.png --video m.mp4 --audio v.wav   # 사진·영상·소리 참고
```

- `--first`/`--last`: 그 그림이 영상의 실제 첫·끝 장면이 된다.
- `--image`/`--video`/`--audio`: 얼굴·옷·화풍·움직임·목소리를 참고한다. 창 1 을 `up.sh --ref` 로 띄웠을 때만. `--first`/`--last` 와 같이 못 쓴다.
- 참고 자료는 사진 9·영상 3·소리 3(합계 12)까지. 소리만 넣을 수는 없다. 넣은 순서대로 1번·2번이고, 프롬프트에 "1번 사진" "1번 영상" 처럼 쓴다(`<Picture 1>` `<Video 1>` 표기도 된다).

## 얼굴·그림체 바꾸기

창 1 을 `bash scripts/up.sh --ref` 로 띄운다(GPU 를 2장씩 나눠 써서 더 느리고, 한 장면은 최대 12초).
사진을 `--image` 로 넣고, 무엇을 가져올지(얼굴·옷·그림체·동작)를 사진 번호와 함께 말로 적는다.

```bash
# 이 사람이 나오게 (얼굴 유지)
h3video gen "1번 사진 사람이 바닷가를 걸으며 웃는다" --image face.png -s 8

# 얼굴은 그대로, 그림체는 말로
h3video gen "1번 사진 사람을 지브리풍 애니메이션으로, 비 오는 거리에서 우산을 쓴다" --image face.png -s 8

# 얼굴은 1번 사진, 그림체는 2번 사진
h3video gen "1번 사진 사람 얼굴 그대로, 2번 사진 그림체로 바닷가를 걷는다" --image face.png --image style.png -s 8

# 옷은 2번 사진
h3video gen "1번 사진 사람이 2번 사진 옷을 입고 무대에서 노래한다" --image face.png --image outfit.png -s 8

# 영상 속 동작을 이 사람이
h3video gen "1번 영상 춤 동작 그대로 1번 사진 사람이 춘다" --video dance.mp4 --image face.png -s 8

# 어떻게 지시될지 먼저 보기 (생성 안 함)
h3video ir "1번 사진 사람 얼굴 그대로, 2번 사진 그림체로 바닷가를 걷는다" --image face.png --image style.png -s 8
```

- `<Subject 1>` 같은 표기는 안 써도 된다. 다듬는 모델이 사진을 직접 보고 얼굴·옷 특징을 공식 형식으로 적어 준다.
- 기존 영상의 얼굴만 바꿔 끼우는 편집이 아니다. 참고해서 새로 만든다.
- `--first`/`--last` 와 같이 못 쓴다.
- 결과가 이상하면 결과 폴더의 `scene01.prompt.txt` 에서 실제로 어떻게 지시됐는지 본다.

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
| `--seed 숫자` | 0 | 같으면 같은 결과, `random` 은 매번 다르게 (웹 UI 는 비우면 매번 다르게) |
| `-t 제목` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o 경로` | - | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--open` | - | 끝나면 기본 플레이어로 연다 (화면이 있는 PC 에서) |
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

## JSON 하나로 한 번에 (그림책·장면 목록)

JSON 하나와 그림들을 주면 장면마다 영상을 만들고, 끝나면 쪽 순서대로 이어 붙여 영상 하나로 만든다. **장면 수와 길이는 JSON 에서 정하므로 `-s` 가 필요 없다.**

```bash
h3video json 토토.json --list                        # 만들지 않고 장면·길이·그림·프롬프트만 보기
h3video json 토토.json pages/ -o ~/videos/토토.mp4   # 그림 폴더와 함께 → 이어 붙인 영상
h3video json books/토토-.../book.json                # 동화책 만들기 결과 폴더 (그림 경로가 들어 있어 그림을 따로 안 줘도 됨)
h3video json 토토.zip                                # 동화책 만들기 "파일 받기" zip 그대로 (book.json + 쪽 그림, 명령 없이 h3video 토토.zip 도 됨)
h3video json --resume last                           # 실패한 장면만 다시 하고 이어 붙이기
h3video json 토토.json pages/ --only page-03 --no-narration -r 16:9
```

받는 JSON:

| JSON | 장면 |
|---|---|
| 동화책 콘티(허브 `/storybook-conti/`)의 "JSON" 내보내기 | 쪽마다 하나. 표지는 표지 그림(`cover.png`)을 줄 때만 |
| 동화책 만들기(storybook-maker) "JSON 한번에" 결과의 `book.json` | 표지·쪽마다 하나 (캐릭터 시트는 빼고), 그림은 그 폴더에서 |
| `["프롬프트", ...]` 또는 `{"title", "ratio", "clips": [{"prompt", "image", "text", "seconds", "seed"}]}` | 항목마다 하나 (`clips` 대신 `scenes`·`pages`·`items` 도 됨) |

**길이**: 장면에 `seconds`(또는 `duration`)가 있으면 그 값. 없으면 쪽 글을 소리 내어 읽는 시간(한국어는 공백 뺀 4자/초, 영어는 2.5단어/초)에 1.5초를 더한 값이고, 글이 없으면 6초다. 장면 하나는 5~15초로 맞춘다.

**그림 맞추기**: JSON 에 적힌 경로(JSON 파일 기준) → 파일 이름(`cover`·`표지` → 표지, `page-03`·`03`·`3쪽` → 3쪽) → 남은 그림은 그림 없는 쪽에 순서대로 붙는다. 폴더를 주면 안의 그림을 이름순으로 읽는다. 그림이 있는 장면은 그 그림이 첫 프레임(fl2va), 없으면 글만으로(t2va) 만든다. 쓰지 않은 그림은 `--list` 에 나온다.

**프롬프트**: 콘티 JSON 이면 쪽의 장면 설명(샷 포함)에 "그림을 살아 움직이게, 그림체와 인물은 첫 프레임 그대로"를 붙인다. 그림이 없는 쪽은 그림체와 인물 생김새를 글로 넣는다. 쪽 글은 내레이션 `<d>[Korean] …</d>` 으로 읽게 하고, `--no-narration` 이면 빼지만 길이는 그대로 글 읽는 시간이다. 장면 목록 JSON 의 `prompt` 는 그대로 보낸다(`text` 가 있으면 내레이션만 붙임).

**화면비**: `-r` → 콘티 판형(`opts.ratio`)·book.json 그림 비율 → 그림이 있으면 `auto`, 없으면 16:9.

**기록**: `outputs/story-<시각>-<id>/story.json` 에 장면마다 작업 id·결과·오류가 남고, 다 되면 같은 폴더에 `<제목>.mp4` 가 생긴다. 시드는 `--seed`(기본 0)부터 장면마다 1씩 더한다.

웹 UI(`h3video web`)에도 같은 기능이 있다: 위쪽 **JSON 한번에** 를 고르고 JSON 파일과 쪽 그림(여러 장)을 끌어다 놓으면 장면 표(맞춘 그림·글·길이·합계, 그림 없는 장면 경고)가 바로 나온다. "장면 N개 만들기"를 누르면 오른쪽 카드에 장면별 진행과 이어 붙인 영상이 나오고, 실패한 장면은 "안 된 장면 다시"로 다시 한다. 웹에서는 JSON 에 적힌 이 컴퓨터의 경로를 읽지 않고, 함께 올린 그림을 이름으로만 맞춘다. 동화책 만들기의 "파일 받기" zip 은 그대로 놓으면 안의 book.json 과 그림을 나눠 넣는다(맞는 쪽이 없는 캐릭터 시트 등은 흐리게 '안 씀').

## 웹 UI

`bash scripts/web.sh`(또는 `h3video web`) 후 브라우저 `http://127.0.0.1:8790`.

- 위쪽에서 만드는 방법을 고른다: **글로 만들기 · 그림으로 시작(첫/끝 그림) · 참고 자료로(사진 9·영상 3·소리 3) · JSON 한번에**. 고른 방법에 필요한 칸만 나온다. 파일은 끌어다 놓는다.
- 길이는 한 칸이다. 적으면 "40초 → 장면 4개를 이어 붙여요"처럼 어떻게 나눌지 바로 보인다(서버 GPU 한도 반영). 시드는 비우면 매번 다르게.
- 오른쪽 카드: 진행·경과 시간, 완성되면 바로 재생·받기, **같은 설정으로 다시**(설정과 파일을 왼쪽에 다시 채움), **명령어로 보기**(같은 영상을 만드는 `h3video …` 명령, 복사 버튼). 실패하면 쉬운 말로 이유와 **다시 하기**.
- 서버가 꺼져 있으면 위쪽에 켜는 명령이 한 줄로 나온다. 모델 사양은 왼쪽 아래 **모델 정보**.
- 휴대폰 폭에서도 쓸 수 있다(만들기 버튼이 화면 아래에 붙어 있다). 허브처럼 다른 주소에서 열면 **서버 주소** 칸에 웹 UI 주소를 적는다([USAGE.md](USAGE.md) 4절).

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
| 무엇이 안 되는지 모르겠다 | `h3video doctor` — 서버·결과 폴더·ffmpeg 를 보고 할 일을 알려 준다 |
| 그 밖에 | `bash scripts/diagnose.sh` 출력을 붙여 준다 |

서버 설치·운영(처음 설치, 저장 위치, 환경 변수)은 [USAGE.md](USAGE.md).
