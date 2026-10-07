# shortform-studio 사용법

파일 두 개 — **프롬프트 JSON(작업 명세)** 와 **소스 영상(없어도 됨)** — 로 9:16 숏폼 MP4 를 만든다.
영상 생성은 내가 띄운 서버(MiniMax-H3 같은 모델을 SGLang·vLLM 으로 서빙, 또는 minimax-h3-video 웹 서버)가 하고,
합성(템플릿·자막·제목·배경음)은 CLI 는 ffmpeg, 웹은 브라우저 안에서 한다.

> 아래 명령은 이 저장소에서 가짜 서버(`tests/fake_servers.py`)로 실제로 돌려 본 것이다.
> 단, 2절의 `sglang serve`·`vllm serve` 는 공식 문서의 명령을 옮긴 것이고 여기서는 GPU 가 없어 실행해 보지 못했다.

---

## 1. 설치

| 필요한 것 | 확인 |
|---|---|
| Python 3.10 이상 (표준 라이브러리만 씀) | `python3 --version` |
| ffmpeg·ffprobe (drawtext 포함 빌드) | `ffmpeg -version` |
| 한글 글꼴 (Noto Sans CJK 등) | 자동으로 찾음. 못 찾으면 `export SHORTS_FONT=/경로/글꼴.ttf` |

```bash
git clone https://github.com/33modeling/shortform-studio.git
cd shortform-studio
./bin/shorts --help              # 설치 없이 바로 실행
pip install -e .                 # (선택) 어디서나 `shorts` 로 실행
```

---

## 2. 서버 준비

CLI 는 서버 주소만 있으면 종류(SGLang / vLLM / h3video)를 스스로 알아낸다. 헷갈리면 `--backend` 로 지정한다.

### 2-1. 클러스터에서 H3 띄우고 바로 쓰기 (minimax-h3-video + SGLang, H100 4장)

minimax-h3-video(비공개 33modeling/minimax-h3-video)의 스크립트를 그대로 쓴다. GPU 가 없는 이 환경에서는 실행해 보지 못했다.

```bash
# 0) 내 PC: 코드 올리기 (클러스터는 GitHub egress 없음)
CLUSTER_SSH=user@host CLUSTER_CODE_DIR=/user-volume/<me>/minimax-h3-video bash scripts/sync_to_cluster.sh
# shortform-studio 도 같은 방식(rsync)으로 클러스터에 올린다

# 1) 클러스터: venv + sglang[diffusion] + 가중치 확인
cd /user-volume/<me>/minimax-h3-video && source scripts/cluster_env.sh
bash scripts/provision.sh

# 2) tmux 에서 서버 두 개 (포그라운드)
bash scripts/serve.sh fl2va  --gpus 0,1,2,3      # 텍스트·첫 프레임 → 영상, 포트 30010
bash scripts/serve.sh ref2va --gpus 4,5,6,7      # 소스 영상·이미지 참조 → 영상, 포트 30011
#   serve.sh 가 실행하는 명령: sglang serve --model-path "$H3_MODEL_DIR" --model-variant fl2va \
#     --num-gpus 4 --ulysses-degree 4 --performance-mode speed --host 0.0.0.0 --port 30010

# 3) 다른 창: 상태 확인
bash scripts/health.sh

# 4) 환경변수(H3_ENDPOINT=…:30010, H3_REF_ENDPOINT=…:30011, H3_INBOX_DIR) 잡고 실행
source scripts/cluster_env.sh
/user-volume/<me>/shortform-studio/bin/shorts run prompt.json [source.mp4] --inbox-dir "$H3_INBOX_DIR"
```

- CLI 는 `--server` 가 없으면 `SHORTS_SERVER` → `H3_ENDPOINT` 를, `--ref-server` 가 없으면 `SHORTS_REF_SERVER` → `H3_REF_ENDPOINT` 를 쓴다.
  **소스 영상·참조 이미지가 없는 장면은 fl2va(30010), 있는 장면은 ref2va(30011)** 로 자동으로 보낸다(가짜 서버 두 개로 시험함).
- 같은 venv 에 minimax-h3-video 가 `pip install -e .` 돼 있으면 그 `h3video.client.VideoRequest` 로 요청 본문을 만든다(없으면 같은 형식의 내장 구현).
- 소스 영상은 서버가 `file://` 로 읽으므로 `--inbox-dir "$H3_INBOX_DIR"`(group-volume)로 복사해 넘긴다.

**내 PC 에서 SSH 터널로 붙기** — 텍스트만(t2va) 쓰면 바로 된다. 소스 영상을 보내려면 클러스터의 `h3video web`(2-3, 업로드를 inbox 로 옮겨 줌)에 붙는다.

```bash
ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@cluster-node &
export H3_ENDPOINT=http://127.0.0.1:30010 H3_REF_ENDPOINT=http://127.0.0.1:30011
./bin/shorts server check
./bin/shorts run prompt.json
```

H3 사양(보내기 전에 CLI 가 한국어로 막는다): 장면 4~15초, 24fps, 짧은 변 768px, 화면비 `9:16 16:9 1:1 4:3 3:4 21:9 auto`,
ref2va 참조 합계 12개 이하(영상 3개·이미지 9개·오디오 3개 이하, 참조 영상 각 2~15초·합계 15초).
**생성 영상은 짧은 변 768 기반(9:16 이면 약 768×1366, 24fps)** 이고, 합성 단계에서 720×1280 또는 1080×1920·30fps 로 맞춘다.
H3 는 장면당 수 분 걸리므로 CLI 는 기본으로 장면당 30분까지 기다린다. 참조 영상의 `start`/`end` 는 그 구간만 잘라 보낸다.

- 요청 형식: `POST /v1/videos` (JSON: task·prompt·conditions·target{short_edge 768, aspect_ratio, duration_seconds}·seed) → `GET /v1/videos/{id}` → `GET /v1/videos/{id}/content`.
  minimax-h3-video 의 `client.py` 와 같은 형식이다.

### 2-2. vLLM(vLLM-Omni) (미실행)

[vLLM-Omni Videos API](https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/videos_api/) 의 `/v1/videos`(multipart: prompt·seconds·size·seed·input_reference)에 붙는다.
참조는 1개만 보낸다(첫 프레임 이미지 또는 첫 소스). 서버 실행 명령은 위 문서의 모델별 예시를 따른다.

### 2-3. minimax-h3-video 로 띄운 서버에 연결

`h3video web` 서버는 파일을 업로드로 받아 inbox 로 옮겨 주므로, 원격 서버여도 소스 영상을 그대로 보낼 수 있다.

```bash
# 클러스터 쪽은 minimax-h3-video/USAGE.md 대로 SGLang(30010/30011) + h3video web(8790)
ssh -N -L 8790:127.0.0.1:8790 user@cluster &          # PC 로 당겨오기
./bin/shorts server check --server http://127.0.0.1:8790
./bin/shorts run prompt.json source.mp4 --server http://127.0.0.1:8790
```

### 2-4. 주소·키 환경변수

| 변수 | 뜻 |
|---|---|
| `SHORTS_SERVER` (없으면 `H3_ENDPOINT`) | 서버 주소 (`--server` 와 같음, fl2va 30010) |
| `SHORTS_REF_SERVER` (없으면 `H3_REF_ENDPOINT`) | 참조 모드 서버 (`--ref-server`, ref2va 30011) |
| `SHORTS_API_KEY` | 서버에 `--api-key` 를 걸었으면 `Authorization: Bearer` 로 붙임 |
| `SHORTS_INBOX` / `SHORTS_INBOX_URI` | 2-1 의 공유 폴더 |
| `ANTHROPIC_API_KEY` | Claude 기획(7절)을 쓸 때만 |

SSH 터널 예: `ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@cluster &` 후 `--server http://127.0.0.1:30010`.

연결 확인:

```bash
./bin/shorts server check --server http://127.0.0.1:30010
# 서버: http://127.0.0.1:30010 / 종류: sglang / 모델: MiniMaxAI/MiniMax-H3 / 가능한 모드: t2va, fl2va, ref2va / 사양
```

---

## 3. 프롬프트 JSON 작성법

스키마: [`schema/job.schema.json`](schema/job.schema.json). 경로는 JSON 파일이 있는 폴더 기준이고, 웹에서는 파일 이름으로 맞춘다.

| 필드 | 뜻 | 기본 |
|---|---|---|
| `prompt` | AI 영상 프롬프트(영어 권장). 있으면 AI 로 생성 | — |
| `scenes` | 장면 여러 개 `[{prompt, sources, image, duration, seed}]` (`prompt` 와 같이 못 씀) | — |
| `sources` | 소스 영상 목록. **prompt 가 있으면 AI 참조 입력**, 없으면 합성 재료. `"a.mp4"` 또는 `{"path","start","end"}` | 두 번째 파일 |
| `base` | 기본 영상(템플릿의 주 화면). 생성 영상을 그 위에 얹는다 | — |
| `image` | 첫 프레임 이미지(fl2va) | — |
| `duration` / `ratio` / `seed` | AI 장면 길이 4~15초 / 화면비 / 시드 | 8 / `9:16` / 0 |
| `server` `ref_server` `backend` `model` `poll` `timeout` | 실행 설정(옵션·환경변수로도 줌) | auto, 3초, 장면당 1800초 |
| `template` | `cutaway` `split` `pip` `montage` (base 없으면 montage) | base 있으면 cutaway |
| `fit` | 가로 영상: `crop`(가운데 자르기) / `blur`(흐린 배경 채우기) | blur |
| `resolution` | `720x1280` / `1080x1920` | 720x1280 |
| `max_duration` | 길이 상한(초) | 60 |
| `title` | 상단 훅 문구 | — |
| `captions` | 자막, 한 줄에 한 장면. 시간 자동 배분(글자 수 비례), `{"text","start","end"}` 로 직접 지정 | — |
| `bgm` `bgm_volume` `original_volume` | 배경음과 볼륨(0~1) | —, 0.25, 1 |
| `output` | 출력 파일 | short.mp4 |

**예시 1 — 프롬프트만** (`examples/prompt-only.json`)

```json
{"prompt": "A tabby cat leaps over a wooden fence at golden hour, slow motion", "duration": 8,
 "title": "고양이의 대점프", "captions": ["노을 지는 골목", "담장 앞에 선 고양이", "점프!"], "output": "cat-jump.mp4"}
```

**예시 2 — 소스 영상 있음** (`examples/with-source.json`, 소스는 두 번째 파일로 → AI 참조 ref2va)

```json
{"prompt": "Use <Video 1> as the motion reference: the same person dances on a neon-lit rooftop", "duration": 6,
 "title": "옥상 위 네온 댄스", "captions": ["원본 동작 그대로", "배경만 네온 옥상으로"], "output": "neon-dance.mp4"}
```

**예시 3 — 템플릿 합성만(AI 없음)** (`examples/compose-only.json`)

```json
{"base": "base.mp4", "sources": ["clip1.mp4", {"path": "clip2.mp4", "start": 1, "end": 4}], "template": "cutaway",
 "title": "3초 만에 보는 요약", "captions": ["오늘 할 이야기", {"text": "핵심은 이것", "start": 3, "end": 5.5}],
 "bgm": "music.mp3", "output": "summary.mp4"}
```

여러 장면은 `examples/scenes.json`. 틀리면 한국어로 알려 준다: `duration [AI 장면 길이(초)]: 15 이하여야 합니다 (지금 30)`, `templat: 알 수 없는 항목입니다. 혹시 'template' 인가요?`

**템플릿**: 컷어웨이(기본 영상과 소리가 계속 흐르고 소스가 사이사이 전체 화면, 소스 합은 길이의 60%까지) ·
위아래 분할(위 기본, 아래 소스 반복) · PIP(기본 전체, 소스는 오른쪽 위 작은 창) · 몽타주(소스를 이어 붙이고 기본 영상 소리를 깖, 기본 영상이 없으면 소스 자기 소리).

---

## 4. CLI

```bash
./bin/shorts run prompt.json                      # 프롬프트만: AI 생성 → 9:16 합성
./bin/shorts run prompt.json source.mp4           # 소스 영상 있음 (JSON 의 sources 대신)
./bin/shorts run prompt.json base.mp4 a.mp4 b.mp4 # 이름이 JSON 의 base 와 같으면 그 자리, 나머지는 sources
./bin/shorts run prompt.json --dry-run            # 보낼 요청 본문과 ffmpeg 명령만 보기
./bin/shorts run prompt.json --json               # 진행 상황을 줄마다 JSON 이벤트로
```

진행 표시: `장면 1/1: t2va 요청 보내는 중… → 작업 ID: video_0001 → [####] 66.7% → 받음 → 합성 계획 → 완성: … (720×1280, 8.0초, 오디오 있음)`.

- H3 는 H100 4장에서도 장면당 수 분 걸린다. 기본은 3초마다 확인, 장면당 30분(1800초)까지 기다린다(`--poll 5 --timeout 3600` 으로 조정). 진행률 옆에 경과 시간이 나온다. **Ctrl+C** 를 누르면 작업 ID 를 찍고 끝나며 서버 작업은 계속 돈다.
  `./bin/shorts resume video_0001` 로 이어 받아 합성까지 한다. 대기 시간을 넘겨도 같은 안내가 나온다.
- 같은 JSON 을 다시 돌리면 요청이 같은 장면은 받은 파일을 다시 쓴다(새로 만들려면 `--fresh`).
- 받은 영상 길이가 요청과 다르면 `주의:` 로 알리고 받은 길이로 합성한다.
- 보내기 전 H3 한도 검사: 장면 4~15초, 화면비, 참조 영상 3개·각 2~15초·합계 15초 이하.

하위 명령:

```bash
./bin/shorts gen --server http://127.0.0.1:30010 --prompt "a cat jumps" --duration 4 -o clip.mp4
./bin/shorts compose --base base.mp4 --source a.mp4 b.mp4 --template split --captions captions.txt --title "제목" --bgm m.m4a -o short.mp4
./bin/shorts server check --server http://127.0.0.1:30010 [--json]
./bin/shorts resume <작업ID 또는 state.json>
```

---

## 5. 웹

허브 33 Arcade(https://33modeling.pages.dev, 비밀번호 게이트)의 **숏폼 제작** 카드.

1. 첫 칸에 프롬프트 JSON, 둘째 칸에 소스 영상(없어도 됨)을 올리고 **만들기** → MP4 가 내려받아진다.
2. 고급 영역에서 템플릿·자막·제목·배경음·해상도를 고치면 같은 JSON 으로 내보낼 수 있고, JSON 을 붙여 넣거나 불러오면 화면이 채워진다. 같은 JSON 이면 CLI 와 같은 배치가 나온다(계획 코드를 맞대어 시험).
3. AI 서버 연결: 서버 주소에 `http://localhost:30010`(SSH 터널) 또는 https 터널 주소. 7절의 문제 해결 참고.
4. 업로드한 파일은 브라우저 안에서만 처리한다(내가 지정한 AI 서버로 보내는 경우만 예외).

---

## 6. 결과물

- 위치: JSON 의 `output`(JSON 폴더 기준) 또는 `-o`. AI 장면은 `<출력>.parts/scene01.mp4…` 에 남고 `state.json` 이 이어 받기 정보다.
- 규격: 9:16, 720×1280(기본) 또는 1080×1920, 30fps, H.264 + AAC 48kHz 스테레오, `+faststart`.
- 길이: 템플릿이 몽타주면 소스 길이 합, 그 밖에는 기본 영상 길이. 둘 다 `max_duration`(기본 60초)에서 자른다.

---

## 7. Claude 로 기획하기 (선택)

아이디어 한두 줄(+소스 영상)을 주면 Claude(기본 `claude-opus-5-5`)가 작업 명세 JSON 을 쓴다. 영상은 여전히 내 서버가 만든다.

```bash
export ANTHROPIC_API_KEY=...
./bin/shorts plan "비 오는 밤 네온 거리 감성 숏폼" -o prompt.json
./bin/shorts plan "이 영상 요약 숏폼" --source talk.mp4 -o prompt.json   # 프레임 몇 장(작은 JPEG)을 함께 보냄
./bin/shorts run --idea "비 오는 밤 네온 거리" source.mp4 --plan-output prompt.json   # 기획 → 생성 → 합성 한 번에
./bin/shorts plan "..." --dry-run                                        # 보낼 요청 요약만 (키는 출력 안 함)
```

- Messages API 를 구조화 출력(`output_config.format` json_schema)으로 불러 JSON 만 받고, 받은 JSON 을 전체 스키마로 다시 검사한다.
  실패하면 오류를 붙여 1번만 다시 요청한다. 서버 쪽 거절 대비로 `fallbacks: "default"` 를 켠다.
- 모델 바꾸기: `--claude-model`. 웹은 키를 그 브라우저 localStorage 에만 저장한다(지우기 버튼).

---

## 8. 문제 해결

| 증상 | 해결 |
|---|---|
| `서버에 연결하지 못했습니다` | 주소·포트 확인, SSH 터널이 살아 있는지 `./bin/shorts server check` |
| `인증 실패(HTTP 401)` | 서버에 `--api-key` 를 걸었으면 `export SHORTS_API_KEY=...` |
| 참조 파일을 서버가 못 읽음 | SGLang 은 `file://` 를 서버가 읽는다. 공유 폴더 `--inbox-dir`(+`--inbox-uri`) 또는 h3video 웹 서버(업로드 지원) |
| 웹에서 CORS 오류 | 서버가 허브 출처를 허용해야 한다. h3video: `h3video web --cors-origin https://33modeling.pages.dev` |
| 웹에서 혼합 콘텐츠 차단 | https 페이지는 `http://localhost`·`127.0.0.1` 만 허용된다. SSH 터널로 localhost 에 붙이거나 cloudflared·Tailscale https 터널 주소를 쓴다. 브라우저가 "로컬 네트워크 접근"을 물으면 허용 |
| 웹에서 WebCodecs 없음 | 최신 Chrome·Edge 권장. 없으면 실시간 녹화(WebM)로 대신 내보낸다 |
| `ffmpeg 가 없습니다` | `sudo apt install ffmpeg` (macOS `brew install ffmpeg`, Windows `winget install ffmpeg`) |
| 한글 자막이 네모로 나옴 | `export SHORTS_FONT=/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc` |
| 결과가 요청보다 짧음 | 서버가 돌려준 길이를 따른다(`주의:` 줄 확인). 템플릿이 몽타주가 아니면 기본 영상 길이가 상한 |

## 9. 테스트

```bash
tests/fixtures/make_media.sh .tmp/media                    # 시험용 영상(ffmpeg)
python3 -m unittest discover -s tests -p 'test_*.py'       # CLI: 가짜 서버로 gen·compose·run·resume·plan
node --test tests/unit/                                    # 공용 계획 모듈 + 파이썬과 같은 배치인지
python3 tests/fake_servers.py video 30010 sglang           # 손으로 시험할 가짜 SGLang 서버
```
