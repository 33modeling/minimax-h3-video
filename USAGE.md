# 서버 준비·운영

영상 만드는 법은 **[VIDEO.md](VIDEO.md)**. 여기는 클러스터에서 서버를 준비하고 띄우고 끄는 법만 적는다.

| 언제 | 명령 (클러스터, `/user-volume/minimax-h3-video` 에서) |
|---|---|
| 코드를 고쳤을 때 (내 PC) | `CLUSTER_SSH=<계정>@<호스트> CLUSTER_CODE_DIR=/user-volume/minimax-h3-video bash scripts/sync_to_cluster.sh` |
| 처음 한 번 | `bash scripts/provision.sh` (참고 자료도 쓰면 `--ref`) |
| H3 서버 띄우기 | `bash scripts/up.sh` (참고 자료도 쓰면 `--ref`) — 끄기: 그 화면에서 Ctrl+C, 다른 창에서는 `bash scripts/down.sh` |
| 웹 UI 띄우기 (필요할 때만) | 다른 창에서 `bash scripts/web.sh` — 끄기: 그 화면에서 Ctrl+C, 다른 창에서는 `bash scripts/web.sh --stop` |
| 떴는지 확인 | `bash scripts/status.sh` |

H3 서버와 웹 UI 는 따로 띄우고 끈다. 하나를 다시 띄우거나 꺼도 다른 하나는 그대로다. CLI(`h3video gen`)만 쓰면 웹 UI 는 필요 없다. `serve.sh` 는 `up.sh` 가 안에서 쓰는 것이라 직접 쓰지 않는다.

## 1. 처음 한 번: provision.sh

```bash
bash scripts/provision.sh            # fl2va(글·첫/끝 프레임)용
bash scripts/provision.sh --ref      # ref2va(참고 자료)용까지
bash scripts/provision.sh --skip-model   # 패키지·가이드만 다시
```

- 노드 드라이버를 보고 엔진을 고른다. 지금 노드(드라이버 CUDA 12.2)는 **Diffusers 엔진**이다. (CUDA 13 이상 노드면 sglang)
- 파이썬 환경 `.venv-diffusers` 를 만든다: torch 2.7.1(CUDA 12.6)·diffusers 0.41 등 버전 고정(`constraints/h100-cu126-diffusers.txt`).
- 모델: 공유 폴더 `/group-volume/models/MiniMax-H3` 의 FL2VA 를 쓴다. 텍스트 인코더(62GB)는 링크로 재사용하고, Diffusers 형식에서 없는 것만 받는다(약 72GB, `--ref` 면 +62GB). 이미 받은 것은 건너뛰고, 받다 끊기면 다시 실행하면 이어 받는다.
- 프롬프트를 공식 형식으로 바꿀 때 쓰는 MiniMax 공식 작성 가이드 2개(40KB)도 받는다.
- 화면 전체가 `logs/provision-<시각>.log` 에 남는다.

## 2. 띄우기·확인·끄기

```bash
bash scripts/up.sh                   # fl2va 서버 (포트 30010)
bash scripts/up.sh --ref             # ref2va 서버도 (포트 30011)
bash scripts/up.sh --check           # 점검만 하고 띄우지 않는다
bash scripts/status.sh               # 다른 창에서: 서버마다 준비됨 ✓ / 로딩 중 / 꺼짐, GPU 메모리
bash scripts/down.sh                 # 다른 창에서 H3 서버 끄기 (웹 UI 는 그대로)
```

`up.sh` 가 하는 일:

1. **전에 띄운 H3 서버 묶음을 전부 내린다**: 서버·워커·torchrun·serve.sh(GPU 를 잡았든 아니든). 포트가 풀릴 때까지 기다린 뒤 시작한다. 웹 UI·같은 셸에서 띄운 다른 GPU 작업·`h3video gen` 은 건드리지 않는다.
2. **비어 있는 GPU 만 쓴다**. 다른 작업이 쓰는 GPU 는 피한다.
   - `--ref` 없이: 빈 GPU 전부를 fl2va 에 (4장이면 텍스트 인코더·VAE 1장 + 영상 모델 3장에 나눠 영상 하나를 함께 만든다)
   - `--ref`: 빈 GPU 를 fl2va·ref2va 가 반씩 (4장이면 2장씩)
   - 직접 고르려면 `--gpus 0,1,2,3 --ref-gpus 4,5,6,7`
   - 이 계정의 다른 작업(다른 실험 등)이 GPU 를 쓰고 있어 모자라거나 서버당 1장이 되면: 그 프로세스(pid·명령)를 보여 주고 **끄고 진행할지 묻는다(y/N)**. 묻지 않고 끄려면 `bash scripts/up.sh --force`
3. 모델·패키지·가이드·메모리·GPU 를 점검하고, 문제가 있으면 이유와 할 일을 출력하고 멈춘다.
4. 서버를 **이 화면에서** 띄운다. 서버 원본 로그가 그대로 나오고 `logs/up-<시각>.log` 에도 남는다. 로딩 시간 제한은 없다.
5. 준비되면 `✓ fl2va 준비됨` 이 나온다. 그다음 다른 창에서 영상을 만든다([VIDEO.md](VIDEO.md)).

끄기: **Ctrl+C**(또는 창을 닫아도) 서버와 하위 프로세스를 모두 끄고 GPU 를 반환한다. 다른 창에서는 `bash scripts/down.sh`.
서버 하나가 죽으면(OOM 등) 바로 알리고 나머지도 정리한다. 오래 띄워 둘 거면 직접 연 tmux 창 안에서 `up.sh` 를 실행한다.

## 3. 저장 위치

```
/group-volume/minsoo3.kim/minimax-h3-video/
  outputs/<작업id>/        결과 mp4 (VIDEO.md 7절)
  inbox/                   입력 그림·영상 사본 (서버가 읽는 곳)
  logs/                    up·provision·서버 로그
  dserver/                 서버가 만든 원본 mp4
  models/MiniMax-H3-diffusers/   Diffusers 형식 가중치
  h3-guides/               공식 프롬프트 작성 가이드
  .venv-diffusers/         파이썬 환경
/group-volume/models/MiniMax-H3   공유 모델 (FL2VA, Ref2VA)
/user-volume/minimax-h3-video     코드
```

## 4. 웹 UI·숏폼

- 웹 UI: 다른 창에서 `bash scripts/web.sh` (허브 숏폼 제작에서 부르면 `--cors https://33modeling.pages.dev`). 화면에 나오는 `ssh -N -L …` 를 PC 에서 실행 → 브라우저 `http://127.0.0.1:8790`. 영상은 H3 서버(`up.sh`)가 떠 있어야 만들어진다
- 웹 UI 를 허브(https://33modeling.pages.dev)처럼 다른 주소에서 열면 위쪽 **서버 주소** 칸에 `http://localhost:8790` 처럼 적는다(브라우저에 기억됨). 이때 웹 UI 는 `bash scripts/web.sh --cors https://33modeling.pages.dev` 로 띄운다
- 서버가 꺼져 있으면 웹 UI 위쪽에 무엇을 켜야 하는지 한 줄로 나온다. CLI 는 `h3video doctor`
- JSON 한번에: 웹 UI 위쪽 "JSON 한번에"를 고르고 동화책 콘티 JSON 과 쪽 그림을 넣으면 장면 표가 나오고, 만들기를 누르면 장면마다 영상을 만들어 이어 붙인다(CLI 는 `h3video json`, [VIDEO.md](VIDEO.md#json-하나로-한-번에-그림책장면-목록))
- 터미널 UI: `source scripts/cluster_env.sh && h3video tui`
- 숏폼(자막·음악·템플릿 합성): [shortform/USAGE.md](shortform/USAGE.md)

## 5. 문제가 생기면

오류는 `up.sh` 화면(= `logs/up-<시각>.log`)의 원본 로그에 그대로 나온다. 안 되면 **`bash scripts/diagnose.sh`** 의 출력을 통째로 붙여 주면 된다(코드 버전·서버 상태·GPU·로그 오류·마지막 작업).

| 보이는 것 | 할 일 |
|---|---|
| `모델 없음` / `Diffusers 형식 가중치가 아직 없다` | `bash scripts/provision.sh` (`--ref` 면 ref2va 것도). 없는 것만 받는다 |
| `Diffusers venv 없음` | `bash scripts/provision.sh --skip-model` |
| 다른 실험이 GPU 를 쓰고 있다 | `up.sh` 가 목록을 보여 주고 끌지 묻는다(y). 바로 끄려면 `bash scripts/up.sh --force` |
| `비어 있는 GPU 가 N장뿐이다` | H3 서버는 이미 다 내린 뒤다. 바로 아래에 이 계정에서 GPU 를 잡은 프로세스(pid·명령)가 나온다. 그것을 끄거나 끝나길 기다리거나 `--ref` 를 뺀다. 목록이 비어 있으면 다른 계정·파드가 쓰는 것 |
| `--gpus 와 --ref-gpus 가 GPU N 에서 겹친다` | 서로 다른 GPU 를 준다 |
| `포트 30010 을 다른 프로그램이 쓰고 있다` | `bash scripts/down.sh` 후 다시 |
| `메모리 여유 …GB < 필요 약 140GB` / 로딩 중 `Killed` | 적재할 때 가중치를 CPU 메모리에 먼저 올린다(서버 하나에 약 140GB). 파드 메모리를 늘리거나 `--ref` 를 뺀다 |
| `영상 모델 워커가 끝났다` | 4장 방식에서 워커가 죽었다. 바로 위 `[dworker]`·`[rank…]` 줄이 원인. 2장 방식으로 띄우려면 `H3_DSERVER_CP=0 bash scripts/up.sh` |
| `서버가 끝났다` | 바로 위 원본 로그가 원인. 남은 프로세스는 이미 끄고 GPU 를 반환했다 |
| `The NVIDIA driver on your system is too old` | sglang 을 CUDA 12 노드에서 띄웠다. `bash scripts/provision.sh` → `bash scripts/up.sh` 하면 Diffusers 엔진으로 바뀐다 |
| 남은 서버만 끄고 싶다 | `python3 scripts/h3_leftovers.py --kill` |
| 느리다 | 요청마다 서버 로그에 `걸린 시간: 다듬기 … 조건 … 디노이징 …(스텝당 …초) · 디코딩 …` 이 찍힌다. 어느 단계인지 보고 줄인다 |

## 6. 바꿀 수 있는 것 (환경 변수)

리포 루트의 `.cluster_env.local.sh`(git 에 안 올라감)에 적으면 매번 적용된다.
CLI 의 서버 주소·결과 폴더는 환경 변수 없이 한 번 저장해 둘 수도 있다: `h3video config set endpoint http://127.0.0.1:30010` (`ref-endpoint`, `output-dir`, `inbox-dir` 도). 파일은 `~/.config/h3video/config.json`, 순서는 명령 옵션 > 환경 변수 > 저장한 값 > 기본값. 지금 값은 `h3video config`.

| 변수 | 기본 | 뜻 |
|---|---|---|
| `STORAGE_ROOT` | `/group-volume/minsoo3.kim/minimax-h3-video` | 저장 위치 |
| `H3_MODEL_DIR` | `/group-volume/models/MiniMax-H3` | 공유 모델 (없으면 찾아보고, 그래도 없으면 물어본다) |
| `H3_ENGINE` | 자동 | `diffusers` / `sglang` 고정 |
| `H3_DSERVER_CP` | 1 | 0 이면 GPU 3장 이상 방식을 끄고 서버당 2장 |
| `H3_PORT_FL2VA` / `H3_PORT_REF2VA` | 30010 / 30011 | 포트 |
| `H3_WAIT_TIMEOUT` | 21600 | CLI 가 영상 하나를 기다리는 최대 초 |

## 7. 테스트 (PC)

```bash
python3 -m unittest discover -s tests       # 모의 서버로 CLI·서버 요청 처리 전 구간
```

웹 UI 브라우저 확인(`tests/test_web_browser.py`)은 node 와 Playwright 가 있을 때만 돈다(`H3_PLAYWRIGHT=<playwright 모듈 경로>`, 없으면 `shortform/node_modules/playwright-core` + google-chrome). 스크린샷을 남기려면 `H3_E2E_OUT=폴더`.
