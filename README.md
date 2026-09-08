# minimax-h3-video

MiniMax-H3(Hailuo 3.0) 오픈 가중치를 H100 클러스터에서 SGLang 으로 서빙하고, 프롬프트만 넣으면 오디오 포함 영상을 만들어 주는 도구.
로컬호스트 웹 UI 로 진행 상황을 보고 결과를 바로 재생한다. 클라이언트는 표준 라이브러리만 쓴다(의존성 0).

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
scripts/provision.sh     # venv + sglang[diffusion] + 가중치 검증(없으면 Hub→hf-mirror 다운로드)
scripts/serve.sh         # sglang serve (tmux 포그라운드, 로그 tee)   fl2va|ref2va
scripts/stop.sh / health.sh / sync_to_cluster.sh
src/h3video/spec.py      # 사양 상수, 장면 분할
src/h3video/client.py    # /v1/videos 제출·폴링·다운로드
src/h3video/jobs.py      # 작업 큐 + 장면 체인(마지막 프레임 → 다음 장면 첫 프레임, ffmpeg concat)
src/h3video/web.py+ui.html  # 로컬호스트 웹 UI
src/h3video/cli.py       # h3video spec|health|plan|gen|ref|status|fetch|web
tests/                   # 모의 SGLang 서버로 CPU 에서 전 구간 검증
```

## 클러스터에서 (서버)

```bash
# 코드는 rsync 로 user-volume 에 (GitHub egress 없음)
CLUSTER_SSH=user@host CLUSTER_CODE_DIR=/user-volume/<you>/minimax-h3-video bash scripts/sync_to_cluster.sh

# 클러스터 셸
cd /user-volume/<you>/minimax-h3-video
source scripts/cluster_env.sh                 # 가중치를 다른 곳에 올렸으면 H3_MODEL_DIR=<경로> 를 먼저 export
bash scripts/provision.sh                     # 가중치가 이미 있으면 검증만 하고 지나감
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

## CLI

```bash
h3video spec                                  # 사양
h3video plan 45                               # 45초 → [9, 9, 9, 9, 9]
h3video gen "프롬프트" --seconds 8 --ratio 16:9
h3video gen "프롬프트" --ir --soundscape "파도, 갈매기" --music "피아노"   # Context-IR 3단 형식(권장)
h3video gen "프롬프트" --first key.png --seconds 40 --scene-seconds 10   # 장면 체인
h3video ref "프롬프트" --image me.png --audio voice.mp3 --seconds 6      # ref2va
h3video status <video_id> / h3video fetch <video_id> --out x.mp4
```

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
