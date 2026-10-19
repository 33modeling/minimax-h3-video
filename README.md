# minimax-h3-video

## Hyperframes 모션 영상 편집

기존 영상 maker의 **Hyperframes · 모션·타임라인 영상**에서 HTML·GSAP 모션과
실제 Hyperframes Studio의 타임라인·레이어·미디어 편집을 사용합니다. 기존 영상
편집실의 **Hyperframes로 모션 편집**으로 장면·선택 영상·소리를 복사할 수 있습니다.
MP4/WebM/MOV/GIF, 원본 크기·4K 출력, 저장 목록·HTML/미디어 ZIP·수정 기록 복원과
중지 후 재출력을 제공합니다. MP4는 완료한 프레임 구간을 검증해 재사용합니다.

설치: `npm run install:hyperframes`. 분석한 원본 구조, 저장 경로, 제작 흐름과
검증은 [Hyperframes 통합 문서](docs/HYPERFRAMES_INTEGRATION.md)를 참고하세요.

## 영상 편집실 · 초안에서 최종 출력까지

기존 웹 UI의 **영상 편집실** 또는 결과 카드의 **편집·보정·AI 업스케일**에서 시작합니다. 기존 H3 웹 서버를 그대로 사용하며 GPU 생성 서버를 새로 시작하거나 주소를 바꾸지 않습니다.

**유튜브 참고 분석**에서 YouTube 주소와 분석 시작·끝 시각을 입력하거나 영상 파일을 올립니다. FFmpeg가 실제 화면 전환과 지정한 간격으로 장면을 나누고, Tesseract가 한글·영문 글자 영역을, 로컬 Whisper가 음성을 분석합니다. 각 장면의 참고 프레임, 영상 프롬프트, Qwen Image용 이미지 프롬프트, 자막, 글자 영역의 0~1 좌표·크기·색·출력 글꼴을 JSON으로 저장합니다. 화면에서 문구·글꼴·굵기·위치·프롬프트를 수정하고 JSON 또는 JSON＋이미지 ZIP을 받거나 **새 편집 프로젝트로 가져오기**를 누릅니다. 기존 프로젝트를 덮어쓰지 않습니다. 저장한 분석 목록과 중지·이어 하기를 지원하며 자료는 `outputs/_references/ref-…/`에 보관합니다. 기본 분석 범위는 시작부터 60초이며 끝 시각으로 늘릴 수 있습니다.

OCR로 원본 글꼴 이름이나 굵기를 확정할 수 없어 출력 기본값을 따로 표시합니다. 색·글자 크기는 추정값입니다. `H3_REFERENCE_VISION_BASE_URL`과 `H3_REFERENCE_VISION_MODEL`을 지정하면 로컬 OpenAI 호환 비전 모델이 실제 참고 프레임을 보고 장면 설명을 보강합니다. 미연결 상태에서는 프레임·OCR·자막·색상으로 만든 초안임을 표시하고 사용자가 장면을 보강할 수 있습니다. 비공개 영상·로그인 요구·YouTube 접근 제한은 오류로 표시하며 직접 준비한 영상 업로드로 이어갈 수 있습니다.

**Qwen Image 보정 + AI 확대**는 기존 로컬 이미지 편집 API(`/v1/images/edits`, 기본 `http://127.0.0.1:8091`)에 각 원본 프레임과 보정 지시를 보낸 뒤 Real-ESRGAN으로 2배·4배 확대합니다. `QWEN_IMAGE_BASE_URL`, `QWEN_IMAGE_MODEL`(기본 `Qwen/Qwen-Image-2.1`), `QWEN_IMAGE_API_KEY`, `QWEN_IMAGE_EDIT_FIELD`를 기존 이미지 서버에 맞춰 지정할 수 있습니다. 서버를 자동으로 시작하거나 모델을 바꾸지 않습니다. 완료한 Qwen 보정 프레임과 확대 프레임을 저장하므로 중지 후 이어 할 수 있습니다. 생성 보정은 세부 형태나 프레임 간 일관성을 바꿀 수 있어 원본·후보 비교로 확인하세요. 모델이 요청한 원본 프레임 크기를 유지하지 않으면 실패 처리하고 이전 선택을 보존합니다.

1. **타임라인**: 드래그·이동 버튼으로 장면 순서를 정하고 시작·끝 자르기, 길이, 겹치기·와이프·슬라이드 전환을 편집합니다.
2. **실제 음성 자막**: CPU의 multilingual Whisper small로 현재 타임라인의 음성을 인식합니다. 문구·시간 수정, 한글 자막 합성, SRT·VTT 저장을 지원합니다. 장면이 바뀌면 이전 자막임을 표시하고 확인 전 자막 포함 최종 출력을 막습니다.
3. **소리 편집**: 별도 내레이션·배경음 업로드, 트랙별 크기, 대사 중 음악 낮추기, 자동 음량 보정을 지원합니다. 생성 모델의 원본 소리는 하나의 트랙으로 유지합니다.
4. **그림 콘티 미리보기**: 현재 JSON·이미지를 가져와 카메라 이동과 전환을 넣은 예비 영상을 생성합니다. GPU 생성 서버가 꺼져 있어도 사용할 수 있습니다.
5. **실제 AI 업스케일**: H3 초안은 576px·20단계, 확정 생성은 768px·50단계입니다. 밝기·대비·색감·감마·선명도·노이즈 보정 후 Real-ESRGAN으로 각 프레임을 2배·4배 보강합니다. 원본 프레임 속도와 소리를 유지하고 길이·크기를 검증합니다. 실제 업스케일과 단순 출력 해상도 변경은 별도 기능입니다.
6. **품질 검사**: 검은 화면·비정상 정지·무음·급격한 밝기 변화, 검출된 사람 얼굴의 시각 특징 변화를 검사합니다. 얼굴 검사는 1초 간격 프레임의 DINOv2 특징을 비교하며 동일 인물일 확률이 아닙니다. 얼굴 미검출·의도된 인물 변경은 직접 판단합니다. 업스케일 뒤 자동으로 검사하며 결과 JSON과 구간 이동을 제공합니다.
7. **후보·원본 보관**: 장면별 시드 후보, 두 영상 비교, 선택·복원, 확정한 장면의 재생성 제외를 지원합니다. 기존 출력 파일을 덮어쓰지 않습니다.
8. **동시 출력**: 가로·세로·정사각, 장면별 인물 위치, 자막 안전 영역, 720·1080·2160px 출력, 전체 그림·화면 채우기 배치와 MP4·자막·타임라인 ZIP을 제공합니다.

편집 기록은 기존 결과 경로의 `_studio/edit-<id>/project.json`, 원본·후보는 `media/`, 출력은 `exports/`에 저장합니다. CPU 작업과 업스케일은 중지·재개할 수 있습니다. 완료한 업스케일 프레임은 `.work/<task>/restored/`에 보존하며 그대로 이어서 처리합니다. 중지 후 설정이 바뀌면 새 설정으로 작업을 다시 시작하고 기존 결과는 유지합니다. 후보 생성은 기존 H3 worker의 중지·재개를 사용합니다.

자동 자막 도구 설치: `npm run install:studio`. 별도 `.venv-video-studio`와 사용자 도구 폴더에 설치하며 모델을 CPU int8로 실행합니다. Whisper 모델 리비전은 `scripts/video-tools.json`에 고정합니다. AI 업스케일과 얼굴 비교는 인접 `storybook-maker`의 설치된 Real-ESRGAN·DINOv2 도구를 재사용합니다. 각각 그 저장소의 `npm run install:studio`, `npm run install:consistency`로 설치할 수 있습니다.

설치 스크립트에는 버전을 고정한 yt-dlp와 공식 Tesseract의 리비전을 고정한 한글·영문 언어팩도 포함합니다. 시스템의 FFmpeg·ffprobe·Tesseract 실행 파일이 필요합니다. 참고 분석 검증은 `python3 -m unittest discover -s tests -p test_reference.py -v`, Qwen API·실제 확대 검증은 `python3 -m unittest discover -s tests -p test_qwen_retouch.py -v`입니다. Qwen 테스트는 이미지 편집 API만 모의 서버로 대체하고 프레임 추출·실제 Real-ESRGAN 확대·소리 복원·원본 보존은 실제 도구로 확인합니다.

브라우저 검증: `npm run test:reference`. 실제 OCR로 글자를 분석하고 글꼴·좌표 수정, ZIP 내려받기, 기존 프로젝트 보존, 새 프로젝트 가져오기와 재접속 복원을 320·390·820·1440px에서 검사합니다. 저장할 때 `typography_prompt`를 수정한 영역에서 다시 만들고 가져온 프로젝트의 영상 프롬프트에도 반영합니다.

검증: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_video_studio.py -v`, `npm run test:studio`. 실제 FFmpeg, Whisper와 AI 업스케일을 사용하며 영상 생성 API만 CPU 모의 서버로 검사합니다. 전체 테스트에는 기존 H3 Diffusers 테스트 환경이 필요합니다. 음성 스모크 검사는 [Whisper 공식 테스트 음성](https://github.com/openai/whisper/blob/main/tests/jfk.flac)을 `H3_ASR_FIXTURE` 또는 사용자 도구 폴더의 `jfk.flac`으로 사용합니다.

구현 근거: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Real-ESRGAN NCNN](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan), [FFmpeg 필터](https://ffmpeg.org/ffmpeg-filters.html).

웹과 편집 도구만 사용자 서비스로 배포하려면 `python3 scripts/install-web-service.py`를 실행합니다. 기존 8790 포트와 CLI에 저장한 생성 서버 설정을 사용하며 GPU 생성 서버는 시작하지 않습니다. 중지는 `systemctl --user stop h3video-web.service`입니다.

MiniMax-H3(Hailuo 3.0) 오픈 가중치를 H100 클러스터에서 SGLang 으로 서빙하고, 프롬프트만 넣으면 오디오 포함 영상을 만들어 주는 도구.
로컬호스트 웹 UI 로 진행 상황을 보고 결과를 바로 재생한다. 클라이언트는 표준 라이브러리만 쓴다(의존성 0).

- **영상 만들기: [VIDEO.md](VIDEO.md)** — 명령·프롬프트(아무 형식이나, 서버가 공식 형식으로 바꿈)·옵션·결과 위치
- **서버 준비·운영: [USAGE.md](USAGE.md)** — 처음 설치(provision), 띄우기·확인·끄기(up·status·down), 저장 위치, 문제 해결

- **영상 한 편**: `h3video gen "..." -s 8` (이 레포의 기본 기능)
- **숏폼 제작**: 장면 영상에 자막·제목·배경음악·템플릿을 얹어 9:16 숏폼으로 합성한다. [`shortform/`](shortform/) (예전 shortform-studio 레포를 2026-10-10 이 레포로 합침). `h3video shorts run job.json` 또는 `shorts run job.json`, 웹은 33modeling 허브의 "숏폼 제작". 자세한 것은 [shortform/USAGE.md](shortform/USAGE.md)
- **클러스터에서 한 번에 띄우기**: `bash scripts/up.sh` / 끄기 `bash scripts/down.sh`

## 모델이 만들 수 있는 것 (공식 사양)

| 항목 | 값 |
|---|---|
| 한 번 생성 길이 | **4~15초** (그 이상은 이 도구가 장면 체인으로 자동 연결) |
| 해상도 | 짧은 변 768px (2K 는 MiniMax 공식 API 의 H3-Regenerate-2K 전용) |
| 프레임 | 24 fps |
| 오디오 | 32 kHz 스테레오, 음성·효과음·음악을 영상과 한 번에 생성 |
| 화면비 | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto |
| 모드 | t2va(텍스트), fl2va(첫/끝 프레임 이미지 0~2장), ref2va(이미지≤9·영상≤3·오디오≤3, 합계≤12) |
| 대사 언어 | 한국어 포함 11개 언어 |
| 모델 | 33B dense transformer, BF16, 권장 H100 4장(`--num-gpus 4 --ulysses-degree 4`) |

`h3video spec` 으로도 출력된다. 생성 시간은 H100 4장 기준 장면당 수 분 단위로 잡는다(서버 로그로 확인).

> 라이선스 주의: MiniMax H3 Community License 는 한국·미국·EU·영국에서의 로컬 사용을 제한한다고 명시돼 있다. 연구·내부 검증 범위인지 라이선스 원문을 확인하고 쓸 것.

## 구조

```
scripts/cluster_env.sh   # fdmu 규약: 저장은 /group-volume/minsoo3.kim/minimax-h3-video, 모델은 /group-volume/models/MiniMax-H3
scripts/provision.sh     # venv + sglang[diffusion] + 가중치 확인(받아 둔 곳 자동 검색, 받기는 --download 일 때만)
scripts/serve.sh         # sglang serve (tmux 포그라운드, 로그 tee)   fl2va|ref2va
scripts/up.sh / status.sh / down.sh   # 띄우기 / 떴는지 확인 / 끄기 — 한 번에: 점검 → 서버·웹 UI 를 이 화면에서 포그라운드(원본 로그) → 준비되면 PC 접속 안내, Ctrl+C 로 전부 끄고 GPU 반환 / 다른 창에서 끄기
scripts/stop.sh / health.sh / sync_to_cluster.sh
src/h3video/spec.py      # 사양 상수, 장면 분할
src/h3video/client.py    # /v1/videos 제출·폴링·다운로드
src/h3video/jobs.py      # 작업 큐 + 장면 체인(마지막 프레임 → 다음 장면 첫 프레임, ffmpeg concat)
src/h3video/web.py+ui.html  # 로컬호스트 웹 UI (tests/e2e/web_ui.cjs 로 브라우저 확인)
src/h3video/config.py    # h3video config: 서버 주소·결과 폴더 저장
src/h3video/hints.py     # 서버가 꺼졌을 때 할 일, 쉬운 오류 문구, 작업 → CLI 명령 (웹·CLI 공용)
src/h3video/tui.py       # 터미널 UI (curses) — tmux 안에서 h3video tui
src/h3video/cli.py       # h3video gen|json|batch|ref|ir|plan|jobs|show|fetch|status|health|doctor|config|spec|web|tui
tests/                   # 모의 SGLang 서버로 CPU 에서 전 구간 검증
shortform/               # 숏폼 제작: shorts CLI(파이썬) + 웹(Vite, 허브 '숏폼 제작') — h3video shorts ...
```

`pip install -e .` 한 번이면 `h3video` 와 `shorts` 명령이 같이 설치된다.

## 클러스터에서 (서버)

명령 하나로 띄우고 끈다. 환경 설정, 모델·sglang·GPU·포트 점검 뒤 서버와 웹 UI 를 **이 화면에서 포그라운드로** 돌린다. 서버 원본 로그와 오류가 그대로 나오고, 준비되면 PC 접속 명령을 출력한다. Ctrl+C 로 서버·워커·웹 UI 를 전부 끄고 GPU 반환까지 확인한다(오래 띄워 둘 거면 직접 연 tmux 창 안에서 실행).

```bash
cd /user-volume/<you>/minimax-h3-video
bash scripts/up.sh             # fl2va 서버(GPU 0-3).  --ref 로 ref2va(GPU 4-7)도, --web 으로 웹 UI 8790 도, --check 는 점검만
bash scripts/status.sh         # 떴는지 확인: 준비됨 / 로딩 중 / 꺼짐
bash scripts/down.sh           # 전부 끄기
```

아래는 같은 일을 단계별로 하는 방법이다.

```bash
# 코드는 rsync 로 user-volume 에 (GitHub egress 없음)
CLUSTER_SSH=user@host CLUSTER_CODE_DIR=/user-volume/<you>/minimax-h3-video bash scripts/sync_to_cluster.sh

# 클러스터 셸
cd /user-volume/<you>/minimax-h3-video
source scripts/cluster_env.sh                 # 가중치를 다른 곳에 올렸으면 H3_MODEL_DIR=<경로> 를 먼저 export
bash scripts/provision.sh                     # 가중치는 받아 둔 곳을 찾아 확인만 (새로 받기는 --download)
tmux new -s h3                                # nohup 금지, 포그라운드
bash scripts/serve.sh fl2va --gpus 0,1,2,3    # 포트 30010. ref2va 는 --gpus 4,5,6,7 로 30011
bash scripts/health.sh                        # 다른 창에서
```

pip 로 sglang 설치가 막히면 공식 도커 `lmsysorg/sglang:dev` 로 같은 `sglang serve` 명령을 실행한다(모델·inbox 경로를 마운트).

## 로컬에서 (클라이언트·웹 UI)

서버 포트를 SSH 로 당겨온 뒤 웹 UI 를 띄운다.

```bash
ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@cluster-node &
pip install -e .            # 또는 PYTHONPATH=src
h3video web --port 8790     # http://127.0.0.1:8790
```

웹 UI: 위쪽에서 만드는 방법(글 · 그림으로 시작 · 참고 자료 · JSON 한번에)을 고르면 그 칸만 나오고, 오른쪽 카드에서 진행·재생·받기·같은 설정으로 다시·명령어로 보기를 한다. 자세한 것은 [VIDEO.md](VIDEO.md#웹-ui).

주의: `fl2va` 의 첫/끝 프레임과 `ref2va` 레퍼런스는 `file://` 경로를 **서버 프로세스**가 읽는다. 로컬에서 UI 를 띄우면 업로드 파일이
서버에 보이지 않으므로, 이미지·레퍼런스를 쓸 때는 웹 UI 를 클러스터 노드에서 띄우고(`h3video web` 후 8790 포트도 포워딩)
`H3_INBOX_DIR` 이 group-volume 안이면 자동으로 그리로 복사된다. 텍스트만 쓰는 t2va 는 어디서 띄워도 된다.

```bash
# 클러스터 노드에서 UI 까지 띄우는 경우
source scripts/cluster_env.sh && h3video web --host 127.0.0.1 --port 8790
# 로컬: ssh -N -L 8790:127.0.0.1:8790 user@cluster-node
```

## 터미널 UI (웹이 안 되는 환경)

```bash
source scripts/cluster_env.sh && h3video tui     # 클러스터 노드 tmux 안에서. 로컬이면 포트 포워딩 후 실행
```

| 키 | 동작 |
|---|---|
| n | 새 작업. 프롬프트는 `$EDITOR`(nano/vi)가 열려 한글도 안전하게 입력, 저장 후 길이·화면비·시드·첫/끝 프레임 경로 순서로 묻는다 |
| p | 한 줄 프롬프트(영문·짧은 것) |
| f | 파일에서 프롬프트 읽기 |
| ↑↓ / Enter | 작업 선택 / 장면별 상세·오류·출력 경로 |
| r / q | 서버 상태 새로고침 / 종료(진행 중이면 확인) |

한 화면에 서버 연결 상태, 대기 수, 작업별 진행률 바(장면 단위)와 경과 시간이 보인다. 결과 mp4 는 작업 폴더에 남는다.

## CLI

```bash
h3video                                       # 자주 쓰는 명령 몇 개 (전부는 h3video --help)
h3video "프롬프트" -s 8                        # 명령 없이도: 글 → gen, 그림 → gen --first, .json → json
h3video doctor                                # 서버·폴더·ffmpeg 점검, 안 되면 할 일
h3video config set endpoint http://127.0.0.1:30010   # 서버 주소 한 번 저장 (환경 변수 없이)
h3video health                                # 서버 확인
h3video plan 45                               # 45초 → [9, 9, 9, 9, 9]
h3video gen "프롬프트" -s 8 -r 16:9 -o out/     # 8초, out/ 에도 저장
h3video gen "프롬프트" --ir --soundscape "파도, 갈매기" --music "피아노"   # Context-IR 3단 형식(권장)
h3video gen "프롬프트" --first key.png -s 40 --scene-seconds 10         # 장면 체인
cat prompt.txt | h3video gen -s 10              # 표준입력 (또는 -f prompt.txt)
h3video gen "프롬프트" -s 40 --dry-run           # 보내지 않고 장면 분할·요청만 확인
h3video ref "프롬프트" --image me.png --audio voice.mp3 -s 6           # ref2va
h3video batch examples/batch_example.txt -o out/                        # 여러 개 차례로 (--- 구분)
h3video json 토토.json pages/ -o 토토.mp4       # JSON + 그림들 → 장면마다 영상 → 이어 붙이기 (장면 수·길이는 JSON 에서)
h3video jobs / h3video show last              # 지난 작업, 마지막 작업 상세
h3video fetch <video_id> [--ref] -o x.mp4     # 서버에서 받기 (ref2va 는 --ref)
```

결과 mp4 경로만 표준 출력으로 나오고(`--open` 이면 바로 재생), 종료 코드는 0 성공·1 실패·2 옵션 오류·130 Ctrl+C. 터미널에서는 진행이 한 줄로 고쳐 써지고, Ctrl+C 로 멈추면 이어 하는 명령(`h3video fetch …`, `h3video json --resume …`)을 알려 준다. 자세한 것은 [VIDEO.md](VIDEO.md).

## 프롬프트 요령

공식 파이프라인은 짧은 프롬프트를 H3-Context-IR(API 전용)로 확장해서 넣는다. 로컬만 쓸 때는 같은 3단 구조로 직접 쓰면 품질이 오른다.

```
integrated_multimodal_description: [Shot 1] 카메라, 피사체, 동작, 조명을 시간 순서로 구체적으로.
overall_soundscape: 환경음·효과음.
non_diegetic_music: 배경음악 스타일·템포.
```

대사는 `<d>[Korean] 안녕하세요.</d>` 형식으로 넣는다. `--ir` 옵션이 이 형식으로 감싸 준다.

## 주요 인물 설정

웹의 `주요 인물 설정`에 인물마다 이름·역할·나이·성별·외모·헤어·의상·소품·성격·태도·말투·목소리·영상용 영어 고정 문구를 적는다. 칸과 예시 인물 6종은 영상 콘티와 같고, `기본값으로 저장`한 인물은 영상 콘티와 같은 칸(`frame-storyboard:cast-default`)에 남아 처음 열 때와 `기본값 불러오기`에 쓰인다. 고친 값은 이 브라우저(`h3video.cast`)에 바로 저장된다.

- **글로 만들기·그림으로 시작·참고 자료로**: 글에 이름이 나오는 인물만 보낼 글 끝에 `Character (이름): 외모.`·`Personality of 이름: …`·`Speech style of 이름: …`·`Voice of 이름: …`를 붙인다. 외모는 영어 고정 문구가 있으면 그 문구, 없으면 나이·외모·의상이다. 글 칸 아래에 어떤 인물이 들어가는지 보인다. 서버의 프롬프트 다듬기(H3 형식)는 이 줄까지 받아서 다듬는다.
- **JSON 한번에**: 화면의 인물을 `cast`(JSON 배열)로 보내고, 서버(`story.py cast_lines`)가 이름이 나오는 장면 프롬프트마다 내레이션(`<d>…</d>`) 앞에 붙인다. 이름은 프롬프트·장면 설명·쪽 글·등장인물 목록에서 찾는다. 그림 없는 장면의 등장인물 묘사도 영어 고정 문구로 바뀐다. 이미 들어 있는 문구(영상 콘티가 붙인 외모 등)는 다시 붙이지 않는다. 장면 표의 `영상 프롬프트`에서 확인할 수 있다.
- 넣은 JSON에 인물 설정(동화책 콘티 `opts.cast`, 영상 콘티 `brief.cast`, 동화책 만들기 `book.json`의 `cast`·영상 보내기 JSON의 `cast`)이 있으면 그 인물로 바뀐다. 동화책 인물의 `kind`·`want`는 나이·성별과 성격에 옮긴다.
- API·CLI: `POST /api/story/plan`·`POST /api/story`의 `cast` 칸(보내지 않으면 JSON 안의 인물), `h3video json 이야기.json --cast cast.json`. 만든 작업의 기록(state)에도 `cast`가 남는다.

## 검증

```bash
python3 -m unittest discover -s tests -v      # 모의 서버로 제출→폴링→다운로드→장면 체인→웹 API 전 구간
python3 tests/mock_server.py 30010            # 실제 서버 없이 UI 만 확인할 때
```

## 저장 · 중간 수정 · 긴 프로젝트 (2026-10-12)

작품의 쪽 수·장면 수·전체 영상 길이에 앱 상한을 두지 않습니다. 생성 서비스의 요청당 길이·해상도는 해당 모델 범위 안에서 사용합니다. Qwen3.8-27B는 LLM/코딩 용도이며 영상·이미지 모델과 별도로 연결합니다.

**일시중지 → 저장본에서 일부 수정 → 이어 만들기** 순서로 사용합니다. 현재 생성 중인 쪽/장면을 마치고 저장한 뒤 멈춥니다. 완료한 출력은 유지하고 미완성·수정한 항목만 다시 생성합니다. 영상 체인에서 앞 장면을 고치면 마지막 프레임을 사용하는 뒤쪽 연결 장면도 다시 생성합니다. 저장 폴더에서 같은 작업 ID로 재개하며 전체 JSON을 다시 넣을 필요가 없습니다. 개별 재생성 전 원본을 보관하므로 이전 그림/영상으로 복원할 수 있습니다.
## Image Maker에서 영상으로 보내기

Image Maker는 선택한 장면 이미지 파일과 스토리라인·재생 시간·카메라 지시를 `creative-image-handoff` 메시지로 보낸다. 기존 `video-maker-ready` 준비 완료 핸드셰이크를 사용하며, 허용한 출처의 opener만 받고 전송 ID로 중복 수신을 방지한다. 수신 후 영상 장면 표에 이미지와 글을 보여 주며 실제 생성은 사용자가 시작한다. 기존 FRAME 콘티 연결은 함께 유지한다.

팝업 대신 Image Maker의 **영상용 이미지 + JSON ZIP**을 기존 JSON 가져오기에서 열 수 있다. `clips[].image`는 함께 첨부한 파일명과 대응하고 SVG 이미지는 보내는 화면에서 PNG로 변환한다. 통합 브라우저 검사는 인접 `image-maker/test/browser.mjs`에서 실제 H3 웹·장면 파서와 CPU 모의 모델로 실행한다.

동화책 Maker의 고급 작업실도 같은 전송 규약을 사용한다. 표지를 선택적으로 포함하고 캐릭터 시트는 제외한다. `sourceKind: "books"`를 받아 동화책에서 넘어온 작업임을 표시하며, 이미지와 쪽 글·재생 시간·카메라·장면 JSON을 함께 가져온다. 두 Maker의 공통 전송 검사는 `storybook-maker/test/browser-creative.mjs`에서 실행한다.

영상 생성 화면의 상단 도구와 하단 고정 바에 **즉시 중지 / 이어 만들기 / 설정 바꿔 재개**를 표시합니다. 완료한 장면·원본·같은 프로젝트 ID를 유지하며, OOM 후보는 실패·중지한 후보만 재개합니다. 자체 Diffusers 영상 서버는 `POST /v1/videos/:id/cancel`로 대기 요청을 취소하고 진행 중인 denoising을 다음 스텝 경계에서 중지합니다. 연결한 다른 영상 서버가 취소 API를 제공하지 않으면 중단한 장면 ID를 보존하고 재개 시 같은 요청을 확인합니다. 고정 바의 해상도 설정은 아직 생성하지 않은 장면에만 적용합니다.


웹 상단에서 영상 웹 서버와 vLLM 이미지 서버를 다시 켤 수 있습니다. 복구 도우미는 storybook-maker 저장소의 `npm run install:control`로 해당 서버 PC에 설치합니다. 영상 모델 엔진과 vLLM 이미지 서버는 별도 서비스이며, 이 버튼은 표시한 서비스만 제어합니다. 입력한 프롬프트와 저장한 작업을 유지하며 새 프로세스가 준비되면 재연결합니다.

### 중지·실패 후 이어 만들기

상단 **저장한 영상 이어 만들기**에서 현재 작업과 남은 영상의 해상도를 선택합니다. 진행 중인 작업을 중지·저장한 뒤 영상 엔진 연결을 확인하고 미완성 장면만 재개합니다. 엔진이 응답하지 않으면 저장본을 유지하고 재개를 보류합니다. **웹 서버만 다시 켜기**는 영상 엔진을 끄지 않습니다. 모델 로딩 대기는 **복구 대기 취소**로 빠져나올 수 있습니다. 이미 접수한 요청의 진행 여부는 하단 작업에서 확인하세요.

OOM으로 끝난 원격 장면은 실패로 저장하고 재개할 때 새 요청을 보냅니다. 완료한 장면의 파일·시드는 보존합니다. 일시적인 연결 오류에는 기존 원격 요청 ID를 유지해 중복 생성을 피합니다. 접수 도중 중지한 경우 늦게 반환된 요청도 취소하고, 취소 중 발생한 원격 오류는 중지 상태로 기록합니다. Diffusers 서버와 분산 워커는 실패한 요청의 예외 프레임·텐서 참조를 해제합니다. 이러한 경로의 CPU 검증은 실제 GPU OOM 해소를 보장하지 않습니다.

회귀 검사는 `PYTHONPATH=src python -m unittest discover -s tests -p 'test_stop.py'`, `test_request_memory.py`, `test_recovery_browser.py`로 실행합니다. 전체 검사에는 프로젝트의 Diffusers 및 dev 의존성이 필요합니다.
