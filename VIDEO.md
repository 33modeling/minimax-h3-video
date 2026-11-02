# 사용법

## H100에 설치된 `h3video`는 어디에 있나요?

기본 Diffusers 설치의 실행 파일은 다음 위치입니다.

```text
/group-volume/minsoo3.kim/minimax-h3-video/.venv-diffusers/bin/h3video
```

코드 폴더와 실행 파일 폴더는 다릅니다. 코드 폴더는 `scripts/up.sh`와 `scripts/cluster_env.sh`가 있는 체크아웃입니다. 아래 `/user-volume/minimax-h3-video`는 코드 폴더의 예시이므로, 다른 곳에 복사했다면 그 폴더에서 실행하세요. 모두 **H100에 접속한 터미널**에서 입력합니다.

```bash
cd /user-volume/minimax-h3-video
source scripts/cluster_env.sh
printf '실행 파일: %s\n입력 폴더: %s\n결과 폴더: %s\n' "$VENV/bin/h3video" "$H3_INBOX_DIR" "$H3_OUTPUT_DIR"
"$VENV/bin/h3video" --help
```

`source`가 설치된 가상환경의 `bin`을 PATH에 넣습니다. 이후 같은 터미널에서는 `h3video`라고 짧게 써도 됩니다. 새 터미널에서는 코드 폴더로 이동해 `source scripts/cluster_env.sh`를 다시 실행하세요. `.cluster_env.local.sh`에서 `STORAGE_ROOT`나 `H3_DIFFUSERS_VENV`를 바꿨다면 위에 출력되는 경로가 실제 설정입니다.

| 구분 | 기본 위치 |
|---|---|
| 실행 파일 | `$VENV/bin/h3video` → `/group-volume/minsoo3.kim/minimax-h3-video/.venv-diffusers/bin/h3video` |
| 이미지·영상 입력 | `$H3_INBOX_DIR` → `/group-volume/minsoo3.kim/minimax-h3-video/inbox` |
| 생성 결과·작업 기록 | `$H3_OUTPUT_DIR` → `/group-volume/minsoo3.kim/minimax-h3-video/outputs` |
| 코드·설정 | `scripts/up.sh`가 있는 폴더, 예: `/user-volume/minimax-h3-video` |

입력 파일은 **H100 노드에서 읽을 수 있는 경로**에 있어야 합니다. 다른 컴퓨터의 경로만 적으면 전송되지 않습니다. `inbox`는 권장 보관 장소이며 다른 읽기 가능한 경로도 사용할 수 있습니다. 아래는 `inbox`에 `1.png`와 `sample.mp4`를 이미 복사한 경우입니다.

```bash
# 파일 확인: 생성 요청을 보내지 않음
h3video inspect "$H3_INBOX_DIR/1.png" "$H3_INBOX_DIR/sample.mp4"

# 요청 미리 보기: GPU 작업을 제출하지 않음
h3video gen "1번 영상의 동작을 참고해 1번 사진의 인물이 걷는다" \
  -i "$H3_INBOX_DIR/1.png" -i "$H3_INBOX_DIR/sample.mp4" \
  -s 8 -o "$H3_OUTPUT_DIR/reference.mp4" --dry-run --json
```

실제 생성은 같은 명령에서 `--dry-run --json`을 빼고 실행합니다. 참고 자료를 쓰는 이 예시는 Ref2VA 서버가 준비돼 있어야 합니다. 첫 프레임용 사진은 `-i` 대신 `--first`로 넣습니다. `h3video`를 쓰기 위해 `up.sh`를 다시 실행할 필요는 없습니다.

**`command not found` 또는 파일 없음:** 먼저 위의 `source`를 실행하고 `ls -l "$VENV/bin/h3video"`로 확인하세요. `$VENV/bin/python`은 있는데 CLI 실행 파일만 없다면 코드 폴더에서 `"$VENV/bin/python" -m pip install --no-deps -e .`로 실행 명령만 등록할 수 있습니다. 이 명령은 모델을 받거나 PyTorch·CUDA 패키지를 다시 설치하지 않습니다. `$VENV/bin/python`도 없다면 `.cluster_env.local.sh`의 경로와 기존 `provision.sh` 설치 완료 여부부터 확인하세요.


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


## CLI 파일·옵션별 실행 예시

`--first start.png`는 생성 영상의 **첫 프레임**입니다. 얼굴 참고 사진은 `--image 1.png`, 동작 참고 영상은 `--video sample.mp4`로 지정합니다. 첫·끝 프레임 옵션과 참고 자료 옵션은 혼합하지 않습니다.

### 1.png의 얼굴로 sample.mp4 인물 얼굴 교체 요청

준비: 1.png: 교체할 인물의 얼굴 사진 / sample.mp4: 동작·구도를 참고할 영상

```bash
h3video gen "1번 영상의 인물 얼굴을 1번 사진의 인물 얼굴로 바꿔 줘. 영상의 걷는 동작, 의상, 배경과 카메라 구도는 유지해 줘." \
  --image 1.png --video sample.mp4 \
  -s 8 -r 16:9 --seed 42 -o face-change.mp4
```

--image는 인물 참고 사진, --video는 동작·장면 참고 영상입니다. Ref2VA로 새 영상을 생성하는 요청입니다. 원본 프레임에 얼굴을 직접 합성하는 전용 face-swap 명령이 아니므로 원본과 같은 동작·얼굴·소리가 그대로 유지된다고 보장하지 않습니다.

### 얼굴 교체 요청을 생성 전에 확인하기

준비: 위와 같은 1.png와 sample.mp4

```bash
h3video gen "1번 영상의 인물 얼굴을 1번 사진의 인물 얼굴로 바꿔 줘. 의상과 배경은 유지해 줘." \
  --image 1.png --video sample.mp4 -s 8 --seed 42 \
  -o face-change.mp4 --dry-run
```

--dry-run은 입력·장면 분할·요청을 확인하는 옵션입니다. 이 명령으로 생성 작업을 제출하지 않습니다. 내용을 확인한 뒤 --dry-run만 빼면 실제 생성 요청을 보냅니다.

### --first: 사진 한 장을 영상의 첫 프레임으로

준비: start.png: 영상이 시작할 때 보여줄 전체 이미지

```bash
h3video gen "사진 속 인물이 카메라를 보며 천천히 미소 짓는다. 배경과 의상은 유지한다." \
  --first start.png -s 8 -o first-frame.mp4
```

--first는 first frame, 즉 생성 영상이 시작할 기준 이미지입니다. start.png 전체 화면에서 움직임을 이어 만드는 용도이며, 기존 영상의 얼굴 교체용 사진을 넣는 옵션이 아닙니다. --last를 생략하면 끝 프레임은 프롬프트에 따라 생성합니다.

### --first + --last: 시작 이미지에서 끝 이미지로

준비: start.png: 시작 화면 / end.png: 끝 화면

```bash
h3video gen "첫 사진의 정원에서 카메라가 천천히 전진해 마지막 사진의 문 앞에 도착한다." \
  --first start.png --last end.png \
  -s 8 --seed 42 -o first-to-last.mp4
```

--last는 last frame, 즉 마지막 프레임의 기준 이미지입니다. 예시는 8초짜리 한 장면입니다. 첫·끝 프레임 모드와 참고 자료 모드는 다른 경로이므로 --first/--last에 --image/--video/--audio를 함께 붙이지 마세요.

### 사진 속 인물로 새 동작 만들기

준비: 1.png: 등장시킬 인물 사진

```bash
h3video gen "1번 사진의 인물이 햇빛이 드는 주방에서 컵을 들어 올린다. 얼굴, 머리 모양과 의상을 일관되게 유지한다." \
  --image 1.png -s 8 -o person-action.mp4
```

--image는 얼굴·인물·제품·스타일 등 어떤 특징을 참고할지 정하는 입력입니다. 사진 자체를 첫 프레임으로 고정하려면 위의 --first 예시를 사용하세요.

### 사진 속 인물에게 참고 영상의 동작 적용

준비: 1.png: 인물 / motion.mp4: 따라 할 동작

```bash
h3video gen "1번 사진의 인물이 1번 영상처럼 천천히 걷다가 뒤돌아본다. 인물의 얼굴과 의상은 사진을 따르고 동작과 카메라 이동은 영상을 참고한다." \
  --image 1.png --video motion.mp4 \
  -s 8 --seed 42 -o motion-reference.mp4
```

사진과 영상은 종류별로 따로 번호를 셉니다. 사진 1개와 영상 1개를 넣으면 각각 1번 사진·1번 영상입니다. 영상이 2번 자료가 되는 것이 아닙니다.

### 인물은 유지하고 의상 변경 요청

준비: 1.png: 참고 의상 / sample.mp4: 인물이 등장하는 영상

```bash
h3video gen "1번 영상의 인물 얼굴과 동작은 유지하고 옷을 1번 사진의 파란 재킷으로 바꿔 줘. 배경과 카메라 이동은 영상을 따른다." \
  --image 1.png --video sample.mp4 -s 8 -o outfit-change.mp4
```

사진에서 가져올 부분이 얼굴인지 의상인지 문장에 명시합니다. 원본 프레임을 수정하는 편집기가 아니라 참고 조건을 바탕으로 재생성하므로 다른 부분도 달라질 수 있습니다.

### 인물·동작은 참고하고 배경 변경 요청

준비: room.png: 원하는 배경 / sample.mp4: 인물·동작

```bash
h3video gen "1번 영상의 인물과 걷는 동작을 참고하고, 배경은 1번 사진의 밝은 거실로 바꿔 줘. 인물 크기와 시선 방향은 유지한다." \
  --image room.png --video sample.mp4 -s 8 -o background-change.mp4
```

어느 입력이 인물·동작이고 어느 입력이 배경인지 분리해서 적으세요.

### 참고 영상 속 제품을 내 제품 사진으로 변경 요청

준비: product.png: 내 제품 / sample.mp4: 연출 참고

```bash
h3video gen "1번 영상의 촬영 구도와 손동작을 참고해 제품 소개 영상을 만든다. 제품은 1번 사진의 텀블러를 사용하고 제품 형태와 로고를 유지한다." \
  --image product.png --video sample.mp4 -s 8 -o product-reference.mp4
```

제품의 작은 글자·로고가 정확히 유지되는지는 결과를 직접 확인해야 합니다.

### 영상의 분위기를 다른 사진 스타일로 변경 요청

준비: style.png: 색감·조명·화풍 / sample.mp4: 장면 구성

```bash
h3video gen "1번 영상의 인물 동작과 구도를 참고해 같은 장면을 만든다. 색감과 조명은 1번 사진처럼 따뜻하고 부드럽게 표현한다." \
  --image style.png --video sample.mp4 -s 8 -o style-reference.mp4
```

스타일 참고 이미지와 인물 참고 이미지는 목적이 다릅니다. 프롬프트에서 사진의 어떤 요소를 사용할지 지정하세요.

### 사진 두 장: 인물과 의상을 각각 지정

준비: 1.png: 인물 / 2.png: 의상 / sample.mp4: 동작

```bash
h3video gen "얼굴과 머리 모양은 1번 사진을, 의상은 2번 사진을 따른다. 1번 영상의 걷는 동작과 카메라 이동을 참고한다." \
  --image 1.png --image 2.png --video sample.mp4 \
  -s 8 -o two-image-reference.mp4
```

--image를 두 번 쓰면 입력 순서대로 1번 사진·2번 사진입니다. 마지막의 영상은 여전히 1번 영상입니다.

### 참고 영상 두 개: 동작과 카메라를 분리

준비: motion.mp4: 인물 동작 / camera.mp4: 카메라 이동

```bash
h3video gen "1번 영상의 인물 동작과 2번 영상의 카메라 이동을 조합해 바닷가 산책 장면을 만든다." \
  --video motion.mp4 --video camera.mp4 -s 8 -o two-video-reference.mp4
```

--video를 여러 번 쓰면 영상끼리 입력 순서대로 번호를 셉니다.

### 인물 사진과 소리 참고를 함께 사용

준비: 1.png: 인물 / voice.wav: 음성·소리 참고

```bash
h3video gen "1번 사진의 인물이 카메라를 보며 한국어로 '안녕하세요'라고 말한다. 1번 소리의 말하는 속도와 분위기를 참고한다." \
  --image 1.png --audio voice.wav -s 8 -o audio-reference.mp4
```

--audio는 소리 참고 입력입니다. 원본 음성 파일을 결과 영상에 그대로 붙이는 합성 옵션은 아닙니다. 소리만 단독으로 넣는 예시는 사용하지 않습니다.

### 사진·영상 없이 글만으로 생성

준비: 첨부 파일 없음

```bash
h3video gen "자연광 아래 흰 도자기 컵. 카메라가 천천히 앞으로 이동한다. 조용한 실내 소리와 부드러운 피아노." \
  -s 8 -r 16:9 -o cup.mp4
```

첨부 자료가 없으므로 글·그림용 FL2VA 서버에 요청합니다.

### 긴 프롬프트를 파일에서 읽기

준비: prompt.txt: 영상 설명을 UTF-8로 저장한 텍스트 파일

```bash
h3video gen -f prompt.txt --first start.png \
  -s 8 -o prompt-from-file.mp4
```

-f prompt.txt가 프롬프트 파일을 읽습니다. 기존의 h3video gen prompt.txt 형태도 파일을 인식하지만 -f로 쓰면 문장과 파일 이름을 구분하기 쉽습니다. prompt.txt 안에는 만들 장면·동작·소리를 적습니다.

### 세로 영상·시드·결과 폴더 지정

준비: prompt.txt: 영상 설명

```bash
h3video gen -f prompt.txt \
  -s 8 -r 9:16 --seed 42 -o ./exports/
```

-r 9:16은 세로 화면비, --seed 42는 생성 시드, -o ./exports/는 결과 복사 폴더입니다. 폴더 지정은 마지막 /까지 쓰세요. 파일 이름까지 정하려면 -o ./exports/portrait.mp4로 바꿉니다.

### 작은 크기·적은 스텝으로 초안 생성

준비: 첨부 파일 없음

```bash
h3video gen "바다 위를 낮게 날다가 해변으로 다가가는 드론 촬영" \
  -s 8 --size 576 --steps 20 --seed 42 -o draft.mp4
```

--size는 짧은 변의 픽셀 수, --steps는 생성 반복 횟수입니다. 값을 줄이면 품질이 달라질 수 있으므로 초안 확인용으로 사용하세요.

### 원하지 않는 요소를 별도로 지정

준비: 첨부 파일 없음

```bash
h3video gen "햇빛이 드는 빈 주방을 천천히 둘러보는 카메라" \
  -s 8 -n "화면 자막, 워터마크, 사람, 심한 흔들림" -o kitchen.mp4
```

-n 또는 --negative는 제외하고 싶은 요소를 적는 옵션입니다. 모든 요소가 반드시 제거된다는 보장은 없습니다.

### 30초 요청을 여러 장면으로 나누기

준비: 첨부 파일 없음

```bash
h3video gen "해변에 도착해 산책하고 노을을 바라보는 여행 영상" \
  -s 30 --scene-seconds 10 -o travel-30s.mp4
```

-s는 최종 총 길이입니다. 한 번 생성 한도를 넘으면 이 도구가 장면으로 나누어 이어 붙입니다. --scene-seconds 10은 나눌 때의 장면 길이 기준입니다. --dry-run을 붙이면 분할 계획부터 볼 수 있습니다.

### 같은 요청으로 다른 후보 만들기

준비: 1.png: 인물 / sample.mp4: 동작 참고

```bash
h3video gen "1번 사진의 인물이 1번 영상처럼 걷는다. 배경은 자연광이 들어오는 복도로 한다." \
  --image 1.png --video sample.mp4 -s 8 --seed random -o candidate.mp4
```

--seed random은 실행할 때마다 다른 시드를 사용합니다. 비교하려는 결과는 -o 이름도 candidate-1.mp4, candidate-2.mp4처럼 바꾸어 보관하세요.

| 옵션 | 뜻 | 사용 방법 |
|---|---|---|
| `--first start.png` | 첫 프레임으로 쓸 전체 이미지 | 사진에서 움직임을 이어 만들 때. 얼굴 참고 사진과 구분합니다. |
| `--last end.png` | 마지막 프레임으로 쓸 전체 이미지 | 첫·끝 그림을 연결하는 한 장면 예시에 사용합니다. |
| `--image 1.png` | 인물·얼굴·의상·제품·스타일 참고 사진 | --video와 함께 쓸 수 있습니다. 여러 장은 --image를 반복합니다. |
| `--video sample.mp4` | 동작·구도·장면 참고 영상 | 참고 영상은 2~15초 범위로 준비합니다. 원본을 직접 잘라 편집하는 옵션은 아닙니다. |
| `--audio voice.wav` | 음성·효과음 등 소리 참고 | 2~15초. 사진·영상과 함께 사용합니다. |
| `-f prompt.txt` | 프롬프트를 읽을 텍스트 파일 | UTF-8로 저장한 장면·동작·카메라·소리 설명입니다. |
| `-s 8` | 만들 결과 영상의 총 길이 8초 | 참고 영상에서 잘라 낼 구간이나 시작 시각이 아닙니다. |
| `-r 9:16` | 출력 화면비: 세로 | 가로는 16:9, 정사각은 1:1입니다. |
| `--seed 42` | 생성 시드 | 인물 ID나 프레임 번호가 아닙니다. 다른 후보는 --seed random. |
| `-o result.mp4` | 완성 결과를 복사할 파일 경로 | 폴더로 지정하려면 -o ./exports/처럼 마지막 /를 붙입니다. |
| `--dry-run` | 장면 분할·요청을 출력하고 생성은 제출하지 않음 | 같은 명령에서 이 옵션만 빼면 실제 요청입니다. |
| `--size 576` | 출력의 짧은 변 픽셀 수 | 512·576·640·704·768 중 선택합니다. |
| `--steps 20` | 생성 반복 횟수 | 작은 값은 초안에 사용할 수 있으며 결과 품질도 달라집니다. |
| `--scene-seconds 10` | 긴 요청을 나눌 장면 길이 기준 | -s 30 등 한 번 생성 한도를 넘는 요청에 사용합니다. |
| `-n "…"` | 피하고 싶은 요소 | --negative와 같은 옵션입니다. |

## 입력 검사와 자동 판별

`h3video inspect 파일… [--json]`은 생성 서버 없이 로컬 파일의 종류·크기와 FFprobe 메타데이터를 확인합니다. 원격 URI의 내용은 조회하지 않으며 미확인으로 표시합니다. 파일 실패는 종료 코드 1, 명령 옵션 오류는 2입니다.

`gen/ref`에서 `-i 파일` 또는 `--input 파일`을 반복하면 확장자로 이미지·영상·소리 참고 자료를 구분합니다. 한 장의 이미지도 참고 입력이므로, 그 그림에서 영상을 시작하려면 `--first 이미지`를 사용합니다. 참고 소리에는 이미지 또는 영상도 필요합니다. 각 종류의 번호는 명령에 적은 순서입니다.

```bash
h3video inspect "inputs/원본 영상.mp4" --json
h3video gen "1번 사진의 인물과 1번 영상의 동작" \
  --input inputs/person.png --input "inputs/원본 영상.mp4" \
  --dry-run --json
```

JSON 계획의 스키마는 `h3video.plan.v1`입니다. `requests`는 장면별 요청이며, `inputs`에는 역할·종류·원본 경로와 확인 상태가 들어갑니다. 계획은 복사 전 파일 URI를 보여 주며 `inbox_dir`가 설정돼 있으면 실행 때 공유 폴더의 사본 URI로 바뀝니다. 계획을 보는 명령은 파일 복사·서버 연결·생성을 수행하지 않습니다.
