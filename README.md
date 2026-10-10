# minimax-h3-video

MiniMax-H3(Hailuo 3.0) 오픈 가중치를 H100 클러스터에서 SGLang 으로 서빙하고, 프롬프트만 넣으면 오디오 포함 영상을 만들어 주는 도구.
로컬호스트 웹 UI 로 진행 상황을 보고 결과를 바로 재생한다. 클라이언트는 표준 라이브러리만 쓴다(의존성 0).

**처음이면 [USAGE.md](USAGE.md)** — 코드 올리기부터 서버 실행, TUI 키, 결과 위치, 문제 해결까지 순서대로 적어 두었다.

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
src/h3video/web.py+ui.html  # 로컬호스트 웹 UI
src/h3video/tui.py       # 터미널 UI (curses) — tmux 안에서 h3video tui
src/h3video/cli.py       # h3video spec|health|plan|gen|ref|status|fetch|web
tests/                   # 모의 SGLang 서버로 CPU 에서 전 구간 검증
shortform/               # 숏폼 제작: shorts CLI(파이썬) + 웹(Vite, 허브 '숏폼 제작') — h3video shorts ...
```

`pip install -e .` 한 번이면 `h3video` 와 `shorts` 명령이 같이 설치된다.

## 클러스터에서 (서버)

명령 하나로 띄우고 끈다. 환경 설정, 모델·sglang·GPU·포트 점검 뒤 서버와 웹 UI 를 **이 화면에서 포그라운드로** 돌린다. 서버 원본 로그와 오류가 그대로 나오고, 준비되면 PC 접속 명령을 출력한다. Ctrl+C 로 서버·워커·웹 UI 를 전부 끄고 GPU 반환까지 확인한다(오래 띄워 둘 거면 직접 연 tmux 창 안에서 실행).

```bash
cd /user-volume/<you>/minimax-h3-video
bash scripts/up.sh             # fl2va(GPU 0-3) + 웹 UI 8790.  --ref 로 ref2va(GPU 4-7)도, --check 는 점검만
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
h3video health                                # 서버 확인
h3video plan 45                               # 45초 → [9, 9, 9, 9, 9]
h3video gen "프롬프트" -s 8 -r 16:9 -o out/     # 8초, out/ 에도 저장
h3video gen "프롬프트" --ir --soundscape "파도, 갈매기" --music "피아노"   # Context-IR 3단 형식(권장)
h3video gen "프롬프트" --first key.png -s 40 --scene-seconds 10         # 장면 체인
cat prompt.txt | h3video gen -s 10              # 표준입력 (또는 -f prompt.txt)
h3video gen "프롬프트" -s 40 --dry-run           # 보내지 않고 장면 분할·요청만 확인
h3video ref "프롬프트" --image me.png --audio voice.mp3 -s 6           # ref2va
h3video batch examples/batch_example.txt -o out/                        # 여러 개 차례로 (--- 구분)
h3video jobs / h3video show last              # 지난 작업, 마지막 작업 상세
h3video fetch <video_id> [--ref] -o x.mp4     # 서버에서 받기 (ref2va 는 --ref)
```

결과 mp4 경로만 표준 출력으로 나오고, 종료 코드는 0 성공·1 실패·2 옵션 오류·130 Ctrl+C. 자세한 것은 [USAGE.md](USAGE.md) 4-2절.

## 프롬프트 요령

공식 파이프라인은 짧은 프롬프트를 H3-Context-IR(API 전용)로 확장해서 넣는다. 로컬만 쓸 때는 같은 3단 구조로 직접 쓰면 품질이 오른다.

```
integrated_multimodal_description: [Shot 1] 카메라, 피사체, 동작, 조명을 시간 순서로 구체적으로.
overall_soundscape: 환경음·효과음.
non_diegetic_music: 배경음악 스타일·템포.
```

대사는 `<d>[Korean] 안녕하세요.</d>` 형식으로 넣는다. `--ir` 옵션이 이 형식으로 감싸 준다.

## 검증

```bash
python3 -m unittest discover -s tests -v      # 모의 서버로 제출→폴링→다운로드→장면 체인→웹 API 전 구간
python3 tests/mock_server.py 30010            # 실제 서버 없이 UI 만 확인할 때
```
