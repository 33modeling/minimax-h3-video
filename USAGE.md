# 사용 설명서 (처음부터 끝까지)

## 빠른 시작 (이것만 보면 된다)

> 영상 만드는 법만 보려면 **[VIDEO.md](VIDEO.md)** (서버가 떠 있을 때의 명령·옵션·프롬프트 쓰는 법·결과 위치).

**서버 띄우기·확인·끄기는 이 세 개다** (클러스터의 레포 폴더 `/user-volume/<계정>/minimax-h3-video` 에서):

| 할 일 | 명령 | 보이는 것 |
|---|---|---|
| 띄우기 | `bash scripts/up.sh` (레퍼런스도: `--ref`, 웹 UI 도: `--web`) | 이 화면에 서버 원본 로그. 다 뜨면 `✓ fl2va 준비됨`, `== 준비 완료` |
| 떴는지 확인 (다른 창) | `bash scripts/status.sh` | fl2va·ref2va·웹 UI 마다 `준비됨 ✓` / `로딩 중`(+로그 마지막 줄) / `꺼짐`, GPU 메모리 |
| 끄기 | `up.sh` 화면에서 Ctrl+C, 다른 창에서는 `bash scripts/down.sh` | 서버·워커·웹 UI 종료, GPU 메모리 표시 |

```bash
# ① 내 PC: 코드를 클러스터로 (코드를 고칠 때마다)
CLUSTER_SSH=<계정>@<호스트> CLUSTER_CODE_DIR=/user-volume/<계정>/minimax-h3-video bash scripts/sync_to_cluster.sh

# ② 클러스터: 처음 한 번 — 노드 드라이버를 보고 엔진을 고른다 (2-6절)
#    드라이버 CUDA 12.x 노드(535 계열): Diffusers 엔진. torch 2.7.1(CUDA 12.6)+diffusers venv 를 만들고,
#      Diffusers 형식 가중치 중 없는 것만 받는다(약 72GB, --ref 면 +62GB). 텍스트 인코더 62GB 는 FL2VA 것을 링크로 재사용
#    드라이버 CUDA 13 이상 노드: sglang 엔진. 모델은 /group-volume/models/MiniMax-H3 를 확인만 한다(받지 않음)
cd /user-volume/<계정>/minimax-h3-video
bash scripts/provision.sh       # 레퍼런스(ref2va)도 쓸 거면 --ref

# ③ H3 서버 띄우기 — 이 화면에서 포그라운드, 서버 원본 로그가 그대로 나온다 (웹 UI 는 --web 일 때만)
bash scripts/up.sh              # 레퍼런스(ref2va)도 쓰면 --ref
#    끄기: 이 화면에서 Ctrl+C (서버·워커·웹 UI 전부 끄고 GPU 반환) / 다른 창에서는 bash scripts/down.sh

# ④ 다른 창: 영상 만들기
source scripts/cluster_env.sh
h3video gen "비 오는 서울 밤거리, 네온 반사" -s 8 -o ~/videos/          # 글 → 영상
h3video gen "..." --first first.png -s 8                               # 이 그림에서 시작
h3video ref "<Subject 1>이 손을 흔든다" --image me.png -s 6             # 내 얼굴·동작 참고 (--ref 로 띄웠을 때)
h3video batch prompts.txt -o ~/videos/                                 # 여러 개 차례로 (--- 로 구분)
h3video shorts run job.json --image first.png --ref face.png          # 숏폼: 자막·음악·템플릿 합성
h3video jobs / h3video show last                                       # 지난 작업 / 마지막 작업 상세
```

| 알아 둘 것 | 내용 |
|---|---|
| 결과 | `/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/` (`-o` 를 주면 거기에도 복사) |
| 모델 위치 | `/group-volume/models/MiniMax-H3` (기본, 노드가 바뀌어도 그대로). Diffusers 엔진은 `/group-volume/minsoo3.kim/minimax-h3-video/models/MiniMax-H3-diffusers` (provision.sh 가 만든다) |
| 엔진 | 드라이버 CUDA 12.x 노드 → Diffusers(`h3video.dserver`, 빈 GPU 전부: 4장이면 텍스트 인코더·VAE 1장 + 영상 모델 3장에 나눠 함께), CUDA 13 이상 → sglang(GPU 4장). 자동으로 고르고 `up.sh` 첫 줄에 나온다. 쓰는 법은 같다 |
| fl2va / ref2va | 둘 다 H3 영상 모델, 가중치(62GB)가 달라 서버가 따로다. **fl2va**: 글만, 또는 첫·끝 장면 그림 → 그 그림이 실제 첫·끝 프레임이 된다 (`h3video gen`, `--first/--last`). **ref2va**: 사진·영상·소리를 참고 자료로 → 얼굴·옷·화풍·움직임·목소리를 참고해 새 장면 (`h3video ref --image/--video/--audio`, `up.sh --ref` 로 띄웠을 때) |
| 웹 UI (선택) | CLI 만 쓰면 필요 없다. 쓰려면 `bash scripts/up.sh --web` 후 출력되는 `ssh -N -L ...` 를 PC 에서 실행 → `http://127.0.0.1:8790` |
| 이미 떠 있으면 | `up.sh` 는 떠 있는 서버·웹 UI 를 다시 띄우지 않고 그대로 쓴다 |
| 이미지·영상 입력 | 4-0절 표(H3), 숏폼은 [shortform/USAGE.md](shortform/USAGE.md) 3-1절 |
| 막히면 | 7절 표. 오류는 `up.sh` 화면의 원본 로그에 그대로 나온다 |
| 로그 파일 | `up.sh`·`provision.sh` 화면 전체가 `/group-volume/minsoo3.kim/minimax-h3-video/logs/up-<시각>.log`·`provision-<시각>.log` 에, 서버 로그는 `serve-fl2va-<시각>.log` 에 남는다 (시작할 때 경로 출력) |

아래는 같은 내용을 단계마다 자세히 적은 것이다.

```
[내 PC]  코드 rsync ──▶ [클러스터 노드]  provision(1회) ─▶ up.sh (서버·웹 UI, 이 화면) ─▶ h3video gen / ref / shorts ─▶ mp4
```

- 서버는 클러스터 H100 노드에서만 돈다. 드라이버 CUDA 12.x 노드는 Diffusers 엔진(GPU 2장), CUDA 13 이상은 sglang(GPU 4장).
- 클라이언트(h3video)는 표준 라이브러리만 쓰므로 어디서든 돌지만, 이미지 입력을 쓰려면 서버와 같은 노드에서 띄운다(4절 참고).

---

## 0. 준비물

| 항목 | 내용 |
|---|---|
| 클러스터 계정 | ssh 접속 가능해야 한다. `user@host` 형태로 아래에서 `CLUSTER_SSH` 로 쓴다 |
| 코드 위치 | `/user-volume/<계정>/minimax-h3-video` (user-volume 에는 코드만 둔다) |
| 저장 위치 | `/group-volume/minsoo3.kim/minimax-h3-video` (출력·로그·venv·inbox 전부 여기). 다른 사람이 쓰면 `.cluster_env.local.sh` 로 바꾼다(부록 A) |
| 모델 가중치 | `/group-volume/models/MiniMax-H3` 아래에 `model_index.json`, `FL2VA/`, `Ref2VA/`. 없으면 provision.sh 가 받는다 |
| GPU | H100 4장(fl2va). ref2va 까지 같이 띄우면 8장 |
| python | 클러스터에 python3.12 가 있어야 venv 를 만든다. 다른 버전이면 `PYTHON_BOOTSTRAP=python3.11` 식으로 지정 |
| ffmpeg | 15초 넘는 영상을 장면 체인으로 이어 붙일 때만 필요. 서버 노드에 있어야 한다 |
| tmux | 서버는 항상 tmux 포그라운드에서 띄운다. nohup 은 쓰지 않는다 |

라이선스: MiniMax H3 Community License 는 한국·미국·EU·영국에서의 로컬 사용을 제한한다고 명시돼 있다. 연구·내부 검증 범위인지 원문을 먼저 확인한다.

---

## 1. 코드를 클러스터에 올리기 (내 PC에서)

클러스터에서는 GitHub 에 접속할 수 없다. 그래서 git clone 대신 rsync 로 보낸다.

```bash
cd /home/kms/dev/minimax-h3-video
CLUSTER_SSH=user@host \
CLUSTER_CODE_DIR=/user-volume/<계정>/minimax-h3-video \
bash scripts/sync_to_cluster.sh
```

- `.gitignore` 에 있는 것(venv, outputs, mp4 등)은 보내지 않는다.
- `--delete` 옵션이 있어서 클러스터 쪽에서 직접 고친 파일은 덮어써진다. 코드 수정은 항상 PC 에서 하고 다시 rsync 한다.
- 코드를 고칠 때마다 이 명령만 다시 실행하면 된다.

---

## 2. 서버 준비와 실행 (클러스터 노드에서)

### 2-0. 한 번에 띄우고 끄기 (권장)

```bash
cd /user-volume/<계정>/minimax-h3-video
bash scripts/up.sh --check      # 점검만: 엔진·모델·패키지·메모리·GPU 장수·포트
bash scripts/up.sh              # fl2va 서버(포트 30010). 웹 UI(8790)까지는 --web
bash scripts/up.sh --ref        # ref2va 서버(포트 30011)도
#   GPU: --gpus 를 안 주면 비어 있는 GPU 를 쓴다 (Diffusers 엔진은 빈 GPU 전부, --ref 면 반씩 / sglang 4장씩)
bash scripts/up.sh --cors https://33modeling.pages.dev   # 허브 '숏폼 제작'에서 웹 UI 를 부를 때
bash scripts/down.sh            # 다른 창에서 끄기 (up.sh 화면에서는 Ctrl+C)
```

- `cluster_env.sh` 를 알아서 읽고, 서버와 웹 UI 를 **이 화면에서 포그라운드로** 돌린다. 따로 tmux 를 띄우지 않는다. 오래 띄워 둘 거면 직접 연 tmux 창 안에서 `up.sh` 를 실행한다.
- 서버 **원본 로그**(sglang 출력 그대로)와 오류가 이 화면에 실시간으로 나온다. 모델 로딩은 **시간 제한 없이** 기다린다.
- 서버가 죽으면(OOM 등) 바로 "서버가 끝났다"를 띄우고 남은 프로세스(워커 포함)를 꺼서 GPU 를 반환한 뒤 종료한다. sglang 본체만 죽고 워커가 남은 경우도 잡는다.
- 준비되면 PC 에서 쓸 SSH 터널 명령을 출력하고 계속 돈다. 로딩에 제한을 걸고 싶으면 `H3_UP_TIMEOUT=초`.
- **Ctrl+C** 하면 서버·워커·웹 UI 를 프로세스 묶음째 끄고(30초 안에 안 꺼지면 강제 종료) GPU 별 메모리 사용량을 보여 준다. 이 스크립트가 띄우지 않은 다른 GPU 작업은 건드리지 않는다.
- 시작할 때 **전에 띄운 H3 서버·워커가 GPU 를 잡고 남아 있으면 먼저 내린다**(내 계정이 이 레포로 띄운 것만. 컨테이너에서는 nvidia-smi 가 프로세스를 못 보여 줘서 `/proc` 으로 찾는다, `scripts/h3_leftovers.py`). `--check` 는 보여 주기만 한다.
- GPU 는 비어 있는 것만 쓴다(2GB 넘게 쓰고 있으면 사용 중). `--gpus` 로 준 GPU 를 다른 프로세스가 쓰고 있으면 OOM 이 나기 전에 멈추고 비어 있는 GPU 를 알려 준다.
- 포트를 다른 프로그램이 쓰고 있으면 이유를 출력하고 멈춘다.
- `--gpus`, `--ref-gpus`, `--mode speed|memory`, `--no-web` 으로 바꿀 수 있다. 처음 한 번은 `bash scripts/provision.sh`(아래 2-2)가 먼저 필요하다.

아래 2-1~2-5 는 같은 일을 단계별로 하는 방법이다.

### 2-1. 환경 변수 읽기 (매 셸마다)

```bash
cd /user-volume/<계정>/minimax-h3-video
source scripts/cluster_env.sh
```

마지막 줄에 `[cluster-env] storage=... model=... outputs=... venv=...` 가 찍히면 성공이다.
이 스크립트가 하는 일:

- 저장 경로·모델 경로·포트·엔드포인트 등 `H3_*` 변수를 정한다.
- HOME, TMP, pip·torch·triton 캐시를 전부 group-volume 스크래치로 돌린다(user-volume 용량 보호).
- HF Hub 를 오프라인으로 잠근다(Hub 접속 스톨 방지). provision.sh 만 예외로 푼다.
- venv 가 있으면 PATH 앞에 넣어 `h3video`, `sglang` 명령이 바로 잡히게 한다.

가중치를 다른 경로에 올려 두었으면 source 하기 **전에** 지정한다.

```bash
export H3_MODEL_DIR=/group-volume/<어딘가>/MiniMax-H3
source scripts/cluster_env.sh
```

### 2-2. 프로비저닝 (처음 한 번, 이후에는 검증만)

```bash
bash scripts/provision.sh                 # 엔진 venv + 가중치 확인 (Diffusers 엔진은 Diffusers 형식 중 없는 것만 받는다)
bash scripts/provision.sh --ref           # (Diffusers 엔진) ref2va 용 transformer_ref(62GB)도
bash scripts/provision.sh --skip-model    # 패키지만 설치
bash scripts/provision.sh --download      # (sglang 엔진) 가중치가 정말 없을 때만: 새로 받기 (수백 GB). --fl2va-only 면 Ref2VA 는 안 받음
```

- 엔진은 `cluster_env.sh` 가 드라이버를 보고 고른다(2-6절). 고정하려면 `H3_ENGINE=sglang|diffusers bash scripts/provision.sh`.
- venv 는 sglang 엔진 `$STORAGE_ROOT/.venv`, Diffusers 엔진 `$STORAGE_ROOT/.venv-diffusers` 에 따로 만든다. 이미 있으면 재사용한다.
- 아래 세 줄은 sglang 엔진 이야기다. Diffusers 엔진은 2-6절.
- **모델 위치는 `/group-volume/models/MiniMax-H3` 고정**이고, 가중치는 받지 않는다. 그 폴더에 `model_index.json` 이나 `FL2VA` 가 없으면 "가중치가 없다"고 하고 멈춘다.
- Ref2VA 가 없으면 받지 않고 "ref2va 서버는 못 띄운다"고만 알린다. fl2va 는 그대로 쓴다.
- `--download` 일 때만 HF Hub 에서 받고, 실패하면 hf-mirror.com 으로 다시 시도한다. 둘 다 안 되면 PC 에서 받아 rsync 한다.

  ```bash
  # PC 에서
  hf download MiniMaxAI/MiniMax-H3 --include model_index.json --include 'FL2VA/*' --include 'Ref2VA/*' --local-dir MiniMax-H3   # 패턴마다 --include
  rsync -avz MiniMax-H3/ user@host:/group-volume/models/MiniMax-H3/
  ```
- pip 로 sglang 설치가 막히면(빌드 실패, 인덱스 차단) 3절의 도커 방식으로 간다. 이 경우 `--skip-model` 없이 한 번 더 돌려 가중치만 확인해 둔다.

### 2-3. 서버 띄우기 (tmux 안에서)

```bash
tmux new -s h3                                   # 새 tmux 세션
source scripts/cluster_env.sh
bash scripts/serve.sh fl2va --gpus 0,1,2,3       # 텍스트/프레임 → 영상, 포트 30010
```

- 옵션: `--gpus 0,1,2,3` (GPU 번호), `--mode speed|memory` (기본 speed, OOM 나면 memory), `-- <sglang 추가 옵션>`.
- 로그는 `$H3_LOG_DIR/serve-fl2va-<날짜>.log` 에 tee 된다. 화면에서 로딩 진행이 보인다.
- 33B 가중치를 GPU 4장에 올리므로 처음 뜨는 데 몇 분 걸린다.
- 레퍼런스 입력(내 얼굴, 내 목소리)을 쓰려면 두 번째 서버가 필요하다. 다른 tmux 창에서:

  ```bash
  bash scripts/serve.sh ref2va --gpus 4,5,6,7    # 포트 30011
  ```

tmux 창 다루기: `Ctrl-b c` 새 창, `Ctrl-b n` 다음 창, `Ctrl-b d` 떼어놓기(서버는 계속 돈다), `tmux attach -t h3` 다시 붙기.

### 2-4. 살아 있는지 확인 (다른 창에서)

```bash
bash scripts/status.sh     # fl2va·ref2va·웹 UI: 준비됨 ✓ / 로딩 중(로그 마지막 줄) / 꺼짐, GPU 메모리
```

아래는 더 자세히 볼 때.

```bash
source scripts/cluster_env.sh
bash scripts/health.sh                           # 30010
bash scripts/health.sh http://127.0.0.1:30011    # ref2va
```

`/health -> 200` 이면 준비 완료. 아래에 nvidia-smi 요약이 같이 나온다.
`000` 이면 아직 로딩 중이거나 죽은 것이다. 서버 창의 로그를 본다.

### 2-5. 끄기

```bash
bash scripts/stop.sh            # fl2va, ref2va 모두
bash scripts/stop.sh fl2va      # 하나만
```

포트가 이미 사용 중이라고 serve.sh 가 거부하면 stop.sh 로 정리한 뒤 다시 띄운다.

---

### 2-6. 드라이버 CUDA 12.x 노드 — Diffusers 엔진

H3 를 지원하는 sglang(0.5.17 이상)은 CUDA 13 전용이라(torch 2.11+, flashinfer[cu13] 등) 드라이버가 CUDA 12.2(535 계열)인 노드에서는 못 띄운다.
그런 노드에서는 diffusers 0.41 의 공식 H3 통합(MiniMaxH3ModularPipeline)을 기존 클러스터 레포(failure-atlas 등)와 같은 **torch 2.7.1(CUDA 12.6)** 로 돌린다.

- 고르는 건 자동: `cluster_env.sh` 가 `nvidia-smi` 의 CUDA 버전이 13 미만이면 Diffusers 엔진을 쓴다. `up.sh` 첫 줄에 `[up] 엔진: diffusers` 로 나온다.
- 패키지: `constraints/h100-cu126-diffusers.txt` 로 고정(torch 2.7.1·torchvision 0.22.1·torchaudio 2.7.1·diffusers 0.41.0·transformers 5.14.1 등). venv 는 `.venv-diffusers`, sglang venv 와 따로.
- 가중치: Diffusers 형식(`modular_model_index.json`, `transformer/`, `vae/`, `audio_vae/` …)이 필요하다. 공유 폴더의 `FL2VA/`·`Ref2VA/` 는 sglang 형식이라 영상 모델·VAE 는 파일이 다르다.
  텍스트 인코더·토크나이저·프로세서는 파일이 같아서(HF 해시 일치) 링크로 재사용하고, 나머지만 받는다: fl2va 약 72GB, `--ref` 면 transformer_ref 62GB 더.
- GPU: `up.sh` 가 빈 GPU 를 전부 준다(`--ref` 면 fl2va·ref2va 가 반씩). 장수에 따라:
  - **3장 이상**(H100 4장이면 이것): 첫 장에 텍스트 인코더(Qwen3-VL 32B, 62GB)·VAE, 나머지 장에 영상 모델(62GB)을 한 벌씩 올려 **한 영상을 함께** 디노이징한다(context parallel, diffusers Ulysses). 4장이면 영상 모델 3장이라 1장보다 디노이징이 여러 배 빠르다. 워커는 `h3video.dworker` 를 torchrun 으로 띄우고, 로그는 `[dworker]` 로 같은 화면에 나온다.
  - **2장**: 텍스트 인코더 1장 + 영상 모델·VAE 1장(diffusers 문서의 2장 방식).
  - **1장**: 한 장에서 번갈아 올리고 내린다(느림).
- 같은 API(`/v1/videos`)라 `h3video gen/ref/batch`, 웹 UI, 숏폼이 그대로 쓴다. 다른 점:
  - 길이는 5~15초(4초를 달라고 하면 5초로 만든다). 프레임 수는 VAE 단위(17n+5)로 맞춘다: 5초 124프레임, 8초 192프레임, 15초 345프레임(14.4초).
  - `--negative` 는 쓰지 않는다(H3 는 guidance 가 가중치에 들어 있다). 한 요청에 한 편.
  - 레퍼런스 `video` 는 움직임·카메라만, `video_audio` 는 소리까지.
  - 결과 원본은 `/group-volume/minsoo3.kim/minimax-h3-video/dserver/<fl2va|ref2va>/<id>.mp4`(+ `.json`). CLI 는 평소처럼 `outputs/` 에 받는다.
- 워커 하나가 죽으면(OOM 등) 서버도 같이 끝나고 `up.sh` 가 남은 프로세스를 정리해 GPU 를 반환한다.
- 검증(2026-10-10, 로컬): 이 조합으로 diffusers 공식 H3 테스트 75개 통과·실패 0, 작은 H3 모델로 세 작업 생성, GPU 2장 분할과 1장 결과 프레임 동일, 여러 장 방식(워커 2·3개, 헤드가 안 나누어떨어지는 경우 포함)도 한 프로세스 결과와 같음(프레임 차 최대 1/255, CPU gloo 로 흉내), provision.sh 의 PyPI 설치(torch 2.7.1+cu126)와 가중치 준비, serve.sh → `h3video gen/ref` → status.sh → down.sh 전 구간. 실제 H100·진짜 가중치로는 클러스터에서 처음 돈다.

## 3. pip 설치가 막힐 때: 도커로 서빙

`lmsysorg/sglang:dev` 이미지에 sglang 이 들어 있다. 모델·저장 경로를 마운트하고 serve.sh 와 같은 명령을 친다.

```bash
source scripts/cluster_env.sh
docker run --rm -it --gpus '"device=0,1,2,3"' --ipc=host --network host \
  -v "$H3_MODEL_DIR":/models/MiniMax-H3:ro \
  -v "$STORAGE_ROOT":"$STORAGE_ROOT" \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  lmsysorg/sglang:dev \
  sglang serve --model-path /models/MiniMax-H3 --model-variant fl2va \
    --num-gpus 4 --ulysses-degree 4 --performance-mode speed \
    --host 0.0.0.0 --port 30010
```

- `$STORAGE_ROOT` 를 같은 경로로 마운트해야 `file://` 입력(inbox)이 컨테이너 안에서도 같은 경로로 보인다.
- 이 경우 클라이언트(h3video)는 컨테이너 밖에서 `PYTHONPATH=src python3 -m h3video.cli ...` 로 실행한다(의존성이 없어서 venv 없이 된다).

---

## 4. 영상 만들기

세 가지 방법이 있다. 어느 쪽이든 결과는 같은 폴더에 남는다.

| 방법 | 언제 |
|---|---|
| 터미널 UI (`h3video tui`) | 기본. 여러 개 넣고 진행 상황 보면서 기다릴 때 |
| CLI (`h3video gen`) | 한 개만, 스크립트로 돌릴 때 |
| 웹 UI (`h3video web`) | 브라우저가 되는 환경. 결과를 바로 재생 |

### 어디서 띄우나

- **텍스트만** 쓴다면 어디서든 된다. PC 에서 포트만 당겨오면 된다.

  ```bash
  # PC
  ssh -N -L 30010:127.0.0.1:30010 -L 30011:127.0.0.1:30011 user@host &
  cd /home/kms/dev/minimax-h3-video && pip install -e .     # 또는 PYTHONPATH=src
  h3video health
  ```
- **이미지·영상·오디오를 입력**한다면 클러스터 노드에서 띄운다. 서버가 `file://` 경로를 직접 읽기 때문이다.
  클라이언트는 입력 파일을 `$H3_INBOX_DIR`(group-volume) 로 복사한 뒤 그 경로를 서버에 넘긴다. PC 에서 띄우면 PC 의 파일이 서버에 보이지 않아 실패한다.

### 4-0. 입력 정리 — 이미지·영상·오디오를 어디에 넣나

| 넣는 것 | 뜻 | CLI | 웹 UI (8790) |
|---|---|---|---|
| 첫 프레임 이미지 | 영상이 이 그림에서 시작 (fl2va) | `h3video gen "..." --first a.png` | 첫 프레임 |
| 끝 프레임 이미지 | 영상이 이 그림으로 끝남 (한 장면일 때만) | `--last b.png` | 끝 프레임 |
| 참조 이미지 | 인물·물건 생김새 참고 (ref2va, 최대 9) | `h3video ref "..." --image me.png` (여러 번) | 레퍼런스 → 이미지 |
| 참조 영상 | 동작·카메라 참고 (최대 3, 2~15초) | `--video move.mp4` | 레퍼런스 → 영상 |
| 참조 오디오 | 목소리·소리 참고 (최대 3, 2~15초) | `--audio voice.mp3` | 레퍼런스 → 오디오 |

- 참조(ref2va)는 ref2va 서버(30011, `up.sh --ref`)가 있어야 한다. 프롬프트에서 `<Subject 1>`, `<Video 1>` 처럼 순서로 가리킨다.
- CLI 의 파일 경로는 지금 폴더 기준. 클러스터에서는 파일을 `$H3_INBOX_DIR` 로 자동 복사해 서버에 넘긴다. 웹 UI 는 업로드라 어디에 있어도 된다.
- 숏폼(자막·음악·템플릿 합성)의 입력은 [shortform/USAGE.md](shortform/USAGE.md) 3-1절: `h3video shorts run job.json --image a.png --ref face.png`.

### 4-1. 터미널 UI

```bash
# 클러스터 노드, tmux 새 창
source scripts/cluster_env.sh
h3video tui
```

화면 구성: 맨 위에 서버 연결 상태(fl2va/ref2va 각각), 대기 수. 가운데에 작업 목록(제목, 길이, 장면 진행률 바, 경과 시간). 맨 아래에 키 안내와 메시지.

| 키 | 동작 |
|---|---|
| `n` | 새 작업. `$EDITOR`(없으면 nano)가 열린다. 프롬프트를 여러 줄로 쓰고 저장·종료하면 다음을 차례로 묻는다: 총 길이(초) → 화면비 → 시드 → 첫 프레임 경로 → 끝 프레임 경로 → (15초 초과면) 장면 길이 → 제목. 각 질문은 Enter 로 기본값, 빈 값이면 생략 |
| `p` | 한 줄 프롬프트. 영문이나 짧은 것에 쓴다. 한글은 터미널에 따라 깨질 수 있어 `n` 을 권장 |
| `f` | 파일에서 프롬프트 읽기. 미리 써 둔 `.txt` 경로를 넣는다 |
| `↑` `↓` (`k` `j`) | 작업 선택 |
| `Enter` (`d`) | 선택한 작업의 상세: 장면별 상태·video_id·오류 메시지·출력 파일 경로 |
| `r` | 서버 상태 즉시 새로고침 |
| `q` | 종료. 진행 중인 작업이 있으면 y/N 확인. 종료하면 진행 중이던 장면은 버려진다 |

작업은 큐에 쌓여 **하나씩 순서대로** 처리된다(서버가 한 번에 하나만 돌리기 때문). 여러 개 넣어 두고 tmux 를 떼어 놓았다가(`Ctrl-b d`) 나중에 다시 붙어 확인하면 된다.

### 4-2. CLI

```bash
source scripts/cluster_env.sh      # 클러스터: 서버 주소·저장 경로가 자동으로 잡힌다

h3video                            # 명령 목록과 예시
h3video health                     # 서버 확인 (fl2va 가 안 되면 종료 코드 1)
h3video spec                       # 모델 사양 (길이·해상도·화면비 등)
h3video plan 45                    # 45초를 어떻게 나눌지 → [9, 9, 9, 9, 9]
```

#### 영상 하나 (`gen`)

```bash
# 8초 (기본 16:9)
h3video gen "새벽 안개 낀 해운대, 드론이 바다 위를 낮게 날아 해변으로 접근." -s 8

# 세로 9:16, 파일 이름, 원하는 곳에 저장 (-o 는 파일 경로, 또는 / 로 끝나는 폴더)
h3video gen "..." -s 10 -r 9:16 -t haeundae -o ~/videos/

# Context-IR 3단 형식으로 감싸서 (품질 권장)
h3video gen "..." --ir --soundscape "파도, 갈매기, 바람" --music "잔잔한 피아노 솔로" -s 12

# 긴 프롬프트: 파일, 또는 표준입력
h3video gen -f prompt.txt -s 10
cat prompt.txt | h3video gen -s 10            # 프롬프트 인자를 생략하면 표준입력을 읽는다

# 첫 프레임 이미지에서 시작해 40초 (10초 장면 4개 체인, ffmpeg 필요)
h3video gen "..." --first key.png -s 40 --scene-seconds 10

# 첫·끝 프레임 둘 다 (끝 프레임은 마지막 장면에만 쓰인다)
h3video gen "..." --first a.png --last b.png -s 6

# 넣지 않을 것, 매번 다른 결과(시드 무작위)
h3video gen "..." -n "자막, 워터마크, 흐릿함" --seed random

# 보내기 전에 확인: 장면 분할과 서버에 갈 요청 JSON 만 출력 (서버 필요 없음)
h3video gen "..." --first key.png -s 40 --dry-run
```

#### 레퍼런스로 (`ref`, ref2va 서버 30011 필요)

```bash
h3video ref "<Subject 1>이 카메라를 보며 한국어로 인사한다" --image me.png --audio voice.mp3 -s 6
h3video ref -f ref_prompt.txt --image a.png --image b.png --video move.mp4 -s 8 -o out/
```

이미지 최대 9개, 영상 3개, 오디오 3개, 합계 12개. 넘으면 서버에 보내기 전에 오류로 멈춘다.

#### 여러 개를 차례로 (`batch`)

프롬프트 파일 하나에 영상 여러 개를 적고 한 번에 돌린다. 서버가 한 번에 하나씩 만드니 순서대로 처리하고, 끝나면 결과 경로를 한 줄씩 출력한다. 예시: `examples/batch_example.txt`.

```text
title: haeundae-dawn
seconds: 8
새벽 안개 낀 해운대, 드론이 바다 위를 낮게 날아 해변으로 접근한다.
---
title: seoul-rain
seconds: 12
ratio: 9:16
비 오는 서울 밤거리, 네온사인이 젖은 아스팔트에 번진다.
```

```bash
h3video batch prompts.txt -o out/              # 결과를 out/ 에 모은다
h3video batch prompts.txt -s 10 -r 9:16        # 블록에 없는 옵션의 기본값
h3video batch prompts.txt --dry-run            # 블록마다 요청만 확인
```

- 영상마다 `---` 줄로 나눈다. 블록 맨 위의 `key: value` 줄은 그 영상만의 옵션이고, 나머지 줄(여러 줄 가능)이 프롬프트다. `#` 로 시작하는 줄은 주석.
- 쓸 수 있는 key: `seconds` `ratio` `seed` `title` `first` `last` `negative` `scene-seconds` `steps` `ir` `raw` `soundscape` `music` `image` `video` `audio`. `image` 등은 쉼표로 여러 개.
- 파일 경로(`first`, `image` 등)는 프롬프트 파일이 있는 폴더 기준이다.
- 블록 하나라도 잘못되면(없는 파일, 4초 미만 등) 아무것도 보내기 전에 "N번째 블록" 오류로 멈춘다.

#### 지난 작업과 서버의 영상

```bash
h3video jobs                       # 최근 20개: id, 시각, 상태, 길이, 제목, 결과 경로 (--limit, --json)
h3video show last                  # 마지막 작업 상세: 장면별 상태·video_id·오류·결과 (id 나 id 앞부분도 됨)
h3video status <video_id>          # 서버에 상태 묻기
h3video fetch <video_id> -o a.mp4  # 서버에서 완성본 받기
h3video fetch <video_id> --ref     # ref2va(30011) 영상은 --ref
```

#### 옵션 (`gen` · `ref` · `batch` 공통)

| 옵션 | 기본 | 설명 |
|---|---|---|
| `-s`, `--seconds` | 8 | 총 길이. 4~15 는 한 장면, 16 이상은 장면 체인 |
| `-r`, `--ratio` | 16:9 | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto |
| `--seed` | 0 | 정수 또는 `random`. 같은 프롬프트·시드면 같은 결과. 체인이면 장면마다 1씩 더한다 |
| `--scene-seconds` | 10 | 체인일 때 장면 하나 길이. 실제 분할은 `plan` 이나 `--dry-run` 으로 확인 |
| `--steps` | 서버 기본 | 디노이징 스텝. 줄이면 빠르고 거칠다 |
| `-t`, `--title` | 프롬프트 앞부분 | 결과 mp4 이름 |
| `-n`, `--negative` | 없음 | 넣지 않을 것 |
| `-o`, `--out` | 없음 | 결과를 여기로도 복사. 파일 경로(확장자 없으면 .mp4), 또는 `/` 로 끝나거나 이미 있는 폴더. `batch` 는 폴더 |
| `--dry-run` | 끔 | 서버에 보내지 않고 장면 분할과 요청 JSON 만 출력 |
| `--raw` | 끔 | 서버(Diffusers 엔진)의 프롬프트 다듬기를 끄고 쓴 그대로 보낸다 |
| `--ir` | 끔 | 3단 필드 이름만 붙여 감싸기(다듬기 없이 그대로). `--soundscape`, `--music` 으로 소리 설명 |

`gen` 만: 프롬프트(인자, `-f 파일`, `-f -` 표준입력, 생략 시 파이프 입력), `--first`, `--last`.
`ref` 만: 프롬프트(같은 방식), `--image`, `--video`, `--audio`(여러 번).

공통 옵션 `--endpoint`, `--ref-endpoint`, `--output-dir`, `--inbox-dir`, `--poll` 은 명령 앞뒤 어디에 써도 된다.
`cluster_env.sh` 를 source 했으면 전부 자동으로 채워진다.

#### 실행 중과 끝난 뒤

```text
job 20261010-142233-a1b2c3 등록: 40초, 16:9, 시드 0
  [14:22:40] 진행 장면1 서버 대기열  (경과 6초)
  [14:23:10] 진행 장면1 35%  (경과 36초)
  [14:31:02] 진행 장면1 완료 · 장면2 12%  (경과 8분 28초)
/group-volume/.../outputs/20261010-142233-a1b2c3/barbeach.mp4
끝: 1/1개 완료, 33분 10초
```

- 보내기 전에 확인하는 것: 입력 파일이 있는지, 길이·화면비·레퍼런스 개수가 맞는지, 서버가 응답하는지. 하나라도 걸리면 GPU 를 쓰기 전에 이유와 할 일을 출력하고 멈춘다.
- 진행 상황은 표준 오류로, **결과 mp4 경로만 표준 출력**으로 나온다. 스크립트에서 `out=$(h3video gen "..." -s 8)` 로 경로를 받을 수 있다.
- 종료 코드: `0` 성공, `1` 실패(생성 실패·서버 응답 없음·입력 오류), `2` 옵션 오류, `130` Ctrl+C.
- **Ctrl+C**: 이 터미널의 처리를 멈추고 작업을 "중단됨"으로 기록한다. 서버에서 이미 만들던 장면은 끝까지 갈 수 있으니, 출력되는 `h3video fetch <video_id>` 로 나중에 받으면 된다.
- 창이 닫히거나 프로세스가 강제로 죽어도, 다음에 `jobs`·`show`·TUI·웹을 열면 그 작업은 "처리하던 프로세스가 끝나 중단됨"으로 바뀐다(같은 노드에서 만든 작업만 판단하고, 다른 노드에서 돌고 있는 작업은 건드리지 않는다).
- 장면 하나를 기다리는 최대 시간은 6시간이다(서버 대기열 포함). 바꾸려면 `H3_WAIT_TIMEOUT=초`. 넘기면 그 작업은 실패로 끝나지만 서버에서는 계속될 수 있어 `h3video fetch` 로 받는다.
- `-o` 가 폴더면 같은 이름 파일을 덮어쓰지 않고 `이름-<작업id 끝 6자리>.mp4` 로 저장한다(batch 에서 제목이 같거나 지난 결과가 있을 때). 파일 경로를 직접 주면 그 파일을 덮어쓴다.

### 4-3. 웹 UI

```bash
# 클러스터 노드
source scripts/cluster_env.sh && h3video web --host 127.0.0.1 --port 8790
# PC: 8790 도 같이 당겨온 뒤 브라우저에서 http://127.0.0.1:8790
ssh -N -L 8790:127.0.0.1:8790 -L 30010:127.0.0.1:30010 user@host &
```

텍스트만 쓸 거면 PC 에서 `h3video web` 을 바로 띄워도 된다(30010 포워딩만 있으면 됨).

다른 웹 페이지(33modeling 허브의 "숏폼 제작", 이 레포의 `shortform/`)에서 이 서버로 바로 작업을 보내려면 CORS 를 켠다(기본은 꺼짐).

```bash
h3video web --host 127.0.0.1 --port 8790 --cors-origin https://33modeling.pages.dev   # 여러 개는 쉼표, * 는 전부 허용
```

허브 페이지에서는 서버 주소를 `http://localhost:8790` 으로 넣는다(SSH 터널로 당겨온 주소). 브라우저가 "로컬 네트워크 접근"을 물으면 허용한다.

- 결과 영상은 구간 요청(Range)을 지원해서 재생 중 앞뒤로 넘길 수 있고 Safari·iPhone 에서도 재생된다.
- `/api/jobs` 에 JSON 으로 작업을 보낼 때 입력 파일은 `http(s)://` 주소나 이 서버가 받은 업로드·`$H3_INBOX_DIR` 안의 파일만 받는다. 이 컴퓨터의 다른 경로는 거절한다(웹 요청이 아무 파일이나 공유 inbox 로 복사하지 못하게). 파일은 화면처럼 업로드(multipart)로 보내면 된다.

---

## 5. 결과물은 어디에

저장물은 전부 `/group-volume/minsoo3.kim/minimax-h3-video/`(= `$STORAGE_ROOT`) 아래에 모인다. 코드는 user-volume, 모델 가중치는 공용 `/group-volume/models/MiniMax-H3` 에 있다. 경로는 `scripts/cluster_env.sh` 가 정하고, 바꾸려면 부록 A.

```
/group-volume/minsoo3.kim/minimax-h3-video/
  outputs/<job_id>/        결과 (아래)            $H3_OUTPUT_DIR
  inbox/                   입력 이미지·영상 사본    $H3_INBOX_DIR  (서버가 file:// 로 읽는 곳)
  logs/                    서버 로그·pid          $H3_LOG_DIR
  .venv/                   파이썬 환경            $H3_VENV
  runtime/<user>/<host>/   HOME·임시·캐시          $WORK_ROOT
```

`$H3_OUTPUT_DIR` (기본 `/group-volume/minsoo3.kim/minimax-h3-video/outputs`) 아래에 작업 id 별 폴더가 생긴다.

```
outputs/<job_id>/
  job.json                 # 요청·상태 전체 (TUI·CLI 가 읽는 것)
  scene01.request.json     # 서버에 보낸 실제 요청 (프롬프트·조건 확인용)
  scene01.mp4              # 장면 1
  scene01.last.png         # 장면 1 마지막 프레임 (다음 장면 첫 프레임으로 씀)
  scene02.mp4 ...
  <제목>.mp4               # 최종본. 장면이 하나면 scene01 복사본, 여러 개면 ffmpeg concat
```

PC 로 가져오려면:

```bash
rsync -avz user@host:/group-volume/minsoo3.kim/minimax-h3-video/outputs/<job_id>/ ./out/
```

---

## 6. 프롬프트 쓰는 법

모델은 영상과 오디오(음성·효과음·음악)를 한 번에 만든다. 공식 파이프라인은 짧은 프롬프트를 아래 3단 형식(Context-IR)으로 확장해서 넣는다.
**Diffusers 엔진은 서버가 이 확장을 직접 한다**: GPU 0 의 텍스트 인코더(= Qwen3-VL-32B-Instruct 원본과 같은 파일)로 MiniMax 공식 작성 가이드(`VIDEO_PROMPT_WRITING_GUIDE_base/ref_en.md`, provision.sh 가 `$STORAGE_ROOT/h3-guides` 에 받음)를 따라 다시 쓴다. 미리 보기는 `h3video ir "..."`, 끄기는 `--raw`, 자세한 것은 [VIDEO.md](VIDEO.md) 2절.

```
integrated_multimodal_description: [Shot 1] 카메라·피사체·동작·조명을 시간 순서로. [Shot 2] ...
overall_soundscape: 환경음·효과음.
non_diegetic_music: 배경음악 스타일·템포.
```

- 대사는 `The young woman (S1) says: <d>[Korean] 안녕하세요, 반갑습니다.</d>` 처럼 화자 번호와 언어 태그를 함께 넣는다(공식 가이드 4.4). 한국어 포함 11개 언어.
- 카메라 움직임(드론, 팬, 줌), 시간대·조명, 피사체의 동작을 시간 순서로 구체적으로 쓸수록 안정적이다.
- 장면 체인은 앞 장면의 마지막 프레임을 다음 장면의 첫 프레임으로 넘길 뿐, 프롬프트는 모든 장면에 같은 것이 들어간다. 장면마다 다른 내용을 원하면 작업을 따로 나눠 만들고 ffmpeg 로 잇는다.
- ref2va 에서 레퍼런스 인물은 `<Subject 1>`, `<Subject 2>` 로 가리킨다(이미지 넣은 순서).

---

## 7. 문제가 생기면

| 증상 | 확인할 것 |
|---|---|
| `cluster_env.sh 를 먼저 source 하라` | 매 셸마다 `source scripts/cluster_env.sh` |
| `저장 경로가 group-volume 밖` | STORAGE_ROOT 를 group-volume 아래로. 부록 A |
| `모델 없음: ...` / provision.sh 가 `가중치가 없다` | `ls /group-volume/models/MiniMax-H3` 로 확인. 이미 받아 둔 모델을 다시 받지 않는다(받기는 `--download` 일 때만) |
| `sglang 없음` | provision.sh 가 실패했거나 venv 가 PATH 에 없음. `which sglang` 확인. 안 되면 3절 도커 |
| `포트 30010 이미 사용 중` / `OSError: [Errno 98] Address already in use` | 그 포트에 이미 서버·웹 UI 가 떠 있다. `up.sh` 는 떠 있는 걸 그대로 쓴다. 새로 띄우려면 `bash scripts/down.sh`, 예전 방식(tmux 세션)으로 띄운 게 남았으면 `tmux kill-session -t h3` |
| `The NVIDIA driver on your system is too old (found version 12020)` | sglang(CUDA 13 전용)을 드라이버 CUDA 12.2 노드에서 띄웠다. 코드를 올린 뒤 `bash scripts/provision.sh` → `bash scripts/up.sh` 하면 Diffusers 엔진으로 자동으로 바뀐다(2-6절) |
| `OSError: Could not load this library: .../torchaudio/lib/_torchaudio.abi3.so` | (sglang 엔진) sglang 이 고정한 torchaudio(PyPI 기본판)와 torch(CUDA 13)의 CUDA 가 다르다. provision.sh 가 자동으로 맞춘다. 드라이버 CUDA 12.x 노드라면 위 줄처럼 Diffusers 엔진을 쓴다 |
| `Diffusers 형식 가중치(fl2va)가 아직 없다` | `bash scripts/provision.sh` (`--ref` 면 ref2va 것도). 없는 것만 받고, 받다 끊기면 다시 실행해서 이어 받는다 |
| `CUDA out of memory … GPU 1 has a total capacity of 79.11 GiB of which … is free` | 그 GPU 를 다른 프로세스가 이미 쓰고 있었다(전에 띄운 서버가 남은 경우 등). 지금 `up.sh` 는 시작할 때 남은 H3 서버를 내리고 비어 있는 GPU 만 쓴다. 남은 것만 끄려면 `python3 scripts/h3_leftovers.py --kill` |
| `영상 모델 워커가 끝났다 (종료 코드 …)` | GPU 3장 이상 방식에서 워커(`[dworker]`)가 죽었다. 바로 위 `[dworker]`·`[rank…]` 줄이 원인(OOM 이면 그 GPU 를 다른 프로세스가 쓰는지 `nvidia-smi`). 서버는 같이 끝나고 `up.sh` 가 정리한다. 2장 방식으로 띄우려면 `H3_DSERVER_CP=0 bash scripts/up.sh` |
| `메모리 여유 …GB < 필요 약 140GB` / 서버가 로딩 중 `Killed` | Diffusers 엔진은 적재할 때 가중치를 CPU 메모리에 먼저 올린다(서버 하나에 약 140GB). 파드 메모리 한도를 늘리거나 `--ref` 를 빼고 띄운다 |
| `up.sh` 가 `서버가 끝났다` | 바로 위 원본 로그가 원인(OOM 등). 남은 프로세스는 끄고 GPU 를 반환한 상태 |
| health 가 `000` | 서버 로딩 중(몇 분) 또는 죽음. `up.sh` 화면의 로그 확인 |
| CUDA OOM | `--mode memory` 로 재시작. 그래도 안 되면 `--steps` 줄이거나 길이 단축 |
| 장면 체인에서 `ffmpeg` 오류 | 서버 노드에 ffmpeg 설치. 단일 장면(≤15초)은 ffmpeg 없이 된다 |
| 이미지 넣었는데 `file not found` 류 | PC 에서 띄웠기 때문. 클러스터 노드에서 tui/gen 실행 |
| TUI 한글이 깨짐 | `n` 키(에디터) 로 입력. tmux 안에서 실행 |
| 결과가 안 보임 | `$H3_OUTPUT_DIR` 확인. `h3video show last` 나 TUI `Enter` 로 출력 경로 표시 |
| `대기 시간 초과 ... h3video fetch <id>` | 서버 대기열이 길었거나 생성이 느림. 출력된 `fetch` 로 나중에 받고, 한도는 `H3_WAIT_TIMEOUT`(초, 기본 6시간) |
| 작업이 `처리하던 프로세스가 끝나 중단됨` | 그 작업을 돌리던 CLI·TUI·웹이 꺼졌다. 오류 메시지의 `h3video fetch <video_id>` 로 서버에서 만든 장면을 받거나 다시 실행 |
| CLI 가 `서버가 응답하지 않는다` 로 멈춤 | 출력된 안내대로: 클러스터면 `scripts/health.sh`·`serve.sh`, PC 면 SSH 터널, 주소가 다르면 `--endpoint`. 요청만 보려면 `--dry-run` |
| Ctrl+C 로 끊었는데 서버는 계속 만듦 | 정상. 출력된 `h3video fetch <video_id>` 로 끝난 장면을 받는다 (ref2va 는 `--ref`) |
| `fetch` 가 404 | ref2va 영상이면 `--ref` 를 붙인다 |

서버 로그: `$H3_LOG_DIR/serve-fl2va-*.log`. 요청이 정확히 뭐였는지는 `outputs/<job_id>/scene01.request.json`.

---

## 8. 서버 없이 미리 해보기 (PC)

모의 서버로 전 구간이 돈다. UI 손에 익히거나 코드 고친 뒤 검증할 때.

```bash
cd /home/kms/dev/minimax-h3-video
python3 -m unittest discover -s tests -v          # 자동 검증
PYTHONPATH=src python3 tests/mock_server.py 30010 &   # 모의 서버
PYTHONPATH=src python3 -m h3video.cli tui         # 또는 gen "..." --seconds 8
```

---

## 부록 A. 저장 경로를 내 것으로 바꾸기

리포 루트에 `.cluster_env.local.sh` (git 비추적) 를 만들면 cluster_env.sh 가 먼저 읽는다.

```bash
# .cluster_env.local.sh
export STORAGE_ROOT=/group-volume/<내 이름>/minimax-h3-video
export H3_MODEL_DIR=/group-volume/models/MiniMax-H3
export H3_NUM_GPUS=4
# export H3_PORT_FL2VA=30020   # 포트 충돌 시
```

## 부록 B. 자주 쓰는 한 줄 모음

```bash
# 서버
bash scripts/up.sh                  # H3 서버 (이 화면, Ctrl+C 로 끄기). 웹 UI 도 띄우려면 --web
bash scripts/up.sh --check          # 점검만
bash scripts/status.sh              # 떴는지 확인
bash scripts/down.sh                # 다른 창에서 끄기
source scripts/cluster_env.sh && bash scripts/health.sh
# 생성
source scripts/cluster_env.sh && h3video tui
source scripts/cluster_env.sh && h3video gen "..." -s 8 --ir -o ~/videos/
source scripts/cluster_env.sh && h3video batch prompts.txt -o ~/videos/
h3video jobs && h3video show last
source scripts/cluster_env.sh && h3video shorts run job.json --image first.png --ref face.png
# 코드 갱신 (PC)
CLUSTER_SSH=user@host CLUSTER_CODE_DIR=/user-volume/<계정>/minimax-h3-video bash scripts/sync_to_cluster.sh
```
