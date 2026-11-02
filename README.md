# minimax-h3-video

## H100 설정부터 영상 생성까지

GPU 수와 번호는 자동으로 확인합니다. 실행할 때는 아래 두 명령 중 하나만 고릅니다.

```bash
# 글·첫/끝 프레임 생성 · 빈 GPU 4장 또는 8장을 자동 사용
bash scripts/up.sh

# 참고 이미지·영상까지 사용 · 빈 GPU 8장을 자동으로 4+4 배정
bash scripts/up.sh --ref
```

`--ref` 없이 실행하면 FL2VA만 준비합니다. `--ref`를 붙이면 FL2VA와 Ref2VA를 함께 준비하며, 4장 노드에서 2+2로 줄여 실행하지 않습니다. 다른 작업이 쓰는 GPU는 자동 배정에서 제외합니다. GPU 번호를 직접 지정할 필요는 없습니다.

### 1. H100에서 코드 폴더 열기

이 안내의 명령은 H100에 접속한 터미널에서 실행합니다. 코드 폴더는 scripts/up.sh가 있는 곳입니다. 아래 경로는 예시이므로 다른 위치에 복사했다면 그 폴더로 이동하세요.

```bash
cd /user-volume/minimax-h3-video
source scripts/cluster_env.sh
```

저장 위치를 바꿨다면 코드 폴더의 .cluster_env.local.sh 설정을 사용합니다. source는 그 설정을 읽고 설치된 Python 환경을 PATH에 넣습니다. 새 터미널에서도 다시 실행해야 합니다.

기존 설치본은 먼저 코드를 업데이트해야 새 실행 방식이 적용됩니다. 아래 명령은 모델·입력·결과를 다시 받지 않습니다.

```bash
git status --short
git switch main
git pull --ff-only origin main
```

수정 파일이 있거나 switch·pull이 실패하면 변경을 보관한 뒤 처리하세요. reset --hard로 설치 설정을 지우지 마세요. .cluster_env.local.sh는 기존 값을 유지합니다.

### 2. 최초 설치 · 두 모델 준비

처음 설치할 때 실행합니다. 설치가 정상 완료됐다면 이 단계는 건너뛰세요. 기본 엔진은 Diffusers이며, 최신 provision.sh는 FL2VA와 Ref2VA를 모두 준비합니다. 아래 --ref는 구버전에서도 참고 자료 모델을 포함하도록 명시합니다.

```bash
bash scripts/provision.sh --ref
```

이미 받은 파일은 재사용하고 부족한 파일을 준비합니다. Ref2VA 가중치가 없다고 나올 때도 이 명령을 사용합니다. 글·첫/끝 프레임만 쓸 때는 --fl2va-only를 선택할 수 있습니다. SGLang은 --engine sglang을 명시할 때만 선택합니다.

### 3. 창 1 · 생성 서버 켜기

글·첫/끝 프레임 생성만 필요하면 실행합니다. 비어 있는 GPU가 4장이면 4장, 8장이면 8장을 FL2VA에 자동 배정합니다.

```bash
bash scripts/up.sh
```

참고 이미지·영상 생성도 필요하면 대신 --ref를 붙입니다. H100 80GB 8장 노드에서 비어 있는 GPU를 자동으로 4+4로 나눠 FL2VA와 Ref2VA에 배정합니다.

```bash
bash scripts/up.sh --ref
```

GPU 개수와 번호는 직접 적지 않습니다. 실제 배정 결과는 실행 로그에 표시됩니다. --ref 실행에 필요한 빈 GPU 8장이 부족하면 시작하지 않으며, 4장 노드를 2+2로 나누지 않습니다. CPU RAM 시작 검사 기준은 두 서버 280GiB, 하나 140GiB이며 컨테이너 한도를 반영합니다. 이 수치는 실측 최대 사용량이 아닙니다. 기존 up.sh 창이 실행 중이면 작업 상태를 확인한 뒤 Ctrl+C로 종료하고 다시 실행하세요. 이 터미널은 계속 켜 둡니다.

### 4. 선택한 서버의 준비 완료 확인

기본 실행에서는 아래 한 줄이 나오면 준비된 것입니다. 기본 실행에서 30011이 꺼져 있는 것은 정상입니다.

```text
✓ fl2va 준비됨 (포트 30010)
```

--ref를 붙였다면 아래 줄까지 나와야 참고 자료를 사용할 수 있습니다.

```text
✓ ref2va 준비됨 (포트 30011)
```

--ref로 실행했는데 30010만 준비됐다면 Ref2VA 로그를 확인하세요. 참고 자료 명령은 30011을 사용합니다. 8790은 웹 UI 포트이며 생성 서버 포트와 다릅니다. .cluster_env.local.sh에서 포트를 변경했다면 실제 출력된 포트를 따릅니다.

### 5. 창 2 · CLI 실행

같은 H100 노드에 새 터미널을 열고 같은 코드 폴더로 이동합니다. h3video 명령이 없더라도 아래처럼 설치된 Python으로 직접 실행할 수 있습니다.

```bash
cd /user-volume/minimax-h3-video
source scripts/cluster_env.sh
"$VENV/bin/python" -m h3video.cli --help
```

아래 예시는 실행 파일 등록 여부와 관계없이 같은 Python 직접 실행 형식을 사용합니다. h3video가 정상 등록돼 있다면 그 부분을 h3video로 줄여 써도 됩니다.

### 6. 이미지·영상 원본 위치 확인

파일은 H100 노드에서 읽을 수 있는 경로에 둡니다. 다른 컴퓨터의 파일 경로만 적으면 전송되지 않습니다. H3_INBOX_DIR는 권장 보관 장소이며 다른 읽기 가능한 경로도 가능합니다.

```bash
printf 'Python: %s\nCLI: %s\n입력: %s\n결과: %s\n' "$VENV/bin/python" "$VENV/bin/h3video" "$H3_INBOX_DIR" "$H3_OUTPUT_DIR"
```

아래 입력 예시는 H3_INBOX_DIR에 1.png와 sample.mp4를 이미 복사한 경우입니다. 실제 파일명으로 바꾸세요. 공백·한글이 있는 경로는 따옴표로 묶습니다.

### 7. 글로 영상 생성

FL2VA 서버(기본 30010)로 요청합니다. 글만 사용하는 첫 실행 예시입니다.

```bash
"$VENV/bin/python" -m h3video.cli gen "비 오는 밤거리" \
  -s 8 -o "$H3_OUTPUT_DIR/rain.mp4"
```

완료되면 결과 파일 경로가 출력됩니다. -s는 영상 길이(초), -o는 완성본을 추가로 복사할 경로입니다. 장면·프롬프트·작업 상태도 H3_OUTPUT_DIR 아래에 보관합니다.

### 8. 사진·영상 참고 생성

Ref2VA 서버(기본 30011)를 사용합니다. 먼저 실제 파일을 검사하고 요청 미리 보기를 확인한 다음 생성합니다.

```bash
"$VENV/bin/python" -m h3video.cli inspect \
  "$H3_INBOX_DIR/1.png" "$H3_INBOX_DIR/sample.mp4"

"$VENV/bin/python" -m h3video.cli gen \
  "1번 영상의 동작을 참고해 1번 사진의 인물이 걷는다" \
  --image "$H3_INBOX_DIR/1.png" --video "$H3_INBOX_DIR/sample.mp4" \
  -s 8 -o "$H3_OUTPUT_DIR/reference.mp4" --dry-run --json
```

inspect는 입력 검사이며 --dry-run --json은 작업을 제출하지 않는 요청 미리 보기입니다. 실제 생성은 마지막 명령의 --dry-run --json을 빼고 실행하세요. --image는 참고 사진, --video는 참고 영상입니다. 첫 화면으로 고정할 사진은 --first를 사용하며 참고 자료 옵션과 함께 쓰지 않습니다. 원본 영상의 얼굴을 픽셀 단위로 합성하는 기능은 아닙니다.

### 9. 웹 UI · 선택

CLI 대신 브라우저 화면을 쓸 때만 H100의 별도 터미널에서 실행합니다. 생성 서버가 있는 창 1은 그대로 둡니다.

```bash
cd /user-volume/minimax-h3-video
bash scripts/web.sh
```

기본 웹 UI 포트는 8790입니다. 다른 컴퓨터의 브라우저에서 H100으로 접속한다면 기존에 사용하던 접속 주소나 터널을 사용하세요. 127.0.0.1은 명령·브라우저를 실행한 장치 자신이므로 다른 컴퓨터를 가리키지 않습니다.

### 10. 4장 노드 두 대로 분리 · 메모리 부족 대응

한 노드에서 두 서버를 올리다 CPU RAM이 부족하거나 H100이 4장뿐이라면 노드 A에는 FL2VA, 노드 B에는 Ref2VA를 각각 4장으로 실행합니다. 이 경우도 GPU 수와 번호는 자동으로 확인합니다. NODE_B_IP는 이미 접근 가능한 노드 B의 실제 주소로 바꾸세요. 방화벽 포트를 자동으로 열지 않습니다.

```bash
# 노드 A · 글·첫/끝 프레임 서버
bash scripts/up.sh

# 노드 B · 참고 이미지·영상 서버
bash scripts/up.sh --ref-only

# CLI를 실행하는 노드 A의 새 터미널
source scripts/cluster_env.sh
export H3_REF_ENDPOINT=http://NODE_B_IP:30011
"$VENV/bin/python" -m h3video.cli config
```

두 노드는 동일한 모델 저장소와 입력 inbox 경로를 읽을 수 있어야 합니다. 공유 저장소가 없다면 원본을 노드 B에서도 읽을 수 있도록 먼저 복사하세요. 127.0.0.1은 현재 노드 자신이므로 노드 B 주소로 쓸 수 없습니다. GPU 4+4는 긴 참고 영상이나 다수 입력까지 무제한으로 처리한다는 뜻이 아닙니다. 현재 여러 GPU 경로는 context parallel로 시퀀스를 나누고 영상 워커마다 모델 가중치를 올립니다. 여전히 CUDA OOM이면 -s 5 --size 512로 줄이고 입력 수·참고 영상 길이를 줄여 로그와 함께 확인하세요. CPU RAM 부족이면 해상도 변경만으로 가중치 적재 문제를 해결할 수 없습니다.

### 11. 응답 없음 · 종료·재사용

이미 켠 서버에 연결되지 않을 때는 H3를 띄운 같은 노드에서 상태부터 확인합니다. 서버가 응답하지 않는다는 메시지만으로 재시작하지 마세요.

```bash
bash scripts/status.sh

# 현재 CLI가 쓰는 두 생성 서버 주소 확인
"$VENV/bin/python" -m h3video.cli config
```

기본 실행은 30010만 준비합니다. --ref로 실행했는데 30011이 준비되지 않았다면 Ref2VA 로그를 확인하세요. 두 서버가 준비됐는데도 실패하면 CLI를 실행한 노드와 endpoint/ref-endpoint 값을 비교합니다. 종료는 창 1에서 Ctrl+C, 웹 UI는 해당 창에서 Ctrl+C입니다. 다음 날에는 창 1의 서버 실행과 창 2의 source부터 반복하며 모델 설치를 다시 할 필요는 없습니다.

## CLI 작업 관리 · 재개·대기·취소

기존 설치 폴더에서 git pull --ff-only origin main으로 업데이트한 뒤 사용합니다. 모델을 다시 설치할 필요는 없습니다. h3video 실행 파일이 없다면 같은 환경에서 `"$VENV/bin/python" -m h3video.cli` 뒤에 아래 하위 명령을 붙이면 됩니다.

### 완료한 장면을 보존하고 재개

```bash
h3video jobs --status failed --status paused
h3video show last
h3video resume last --dry-run --json
h3video resume last
```

resume은 로컬 작업 ID·앞부분·last를 받습니다. 기존과 같은 결과 폴더를 사용하세요. 다른 폴더였다면 --output-dir "/내 영상/outputs"를 붙입니다. 완료한 장면 파일·시드·장면 분할은 보존하며, 아직 실행 중인 원격 영상 ID가 있으면 같은 요청에 다시 연결합니다. 실패가 확인된 장면만 새로 제출합니다. 다른 CLI가 같은 작업을 재개 중이거나 기존 처리 프로세스가 살아 있으면 중복 실행을 거절합니다. 재개 전 작업 기록은 작업 폴더의 history에 남깁니다.

```bash
h3video resume last --size 512
```

기존보다 작은 크기로 아직 완료되지 않은 장면만 재개합니다. 서버에서 이미 완료한 영상은 기존 결과를 재사용할 수 있습니다. 진행 중인 요청의 설정을 바꾸려면 서버의 취소 지원이 필요하며, 취소를 지원하지 않으면 재개 설정을 바꾸지 않고 중단합니다. 이미 완료한 장면을 새 크기로 다시 생성하지 않습니다. --dry-run은 파일·기록을 바꾸거나 취소·생성 요청을 보내지 않습니다.

### 기존 원격 영상 기다리기·받기

```bash
h3video wait video_0001 --ref --timeout 600 -o reference.mp4
```

wait·cancel·status·fetch에는 show에서 확인한 장면의 원격 video_id를 넣습니다. 로컬 job ID와 다릅니다. 참고 자료 서버의 영상이면 --ref를 붙이고, 글·첫 프레임 서버라면 생략합니다. wait는 새 영상을 제출하지 않습니다. 대기 한도를 넘겨도 원격 영상을 취소하지 않으며, 같은 ID로 다시 wait하거나 완료 후 fetch할 수 있습니다. -o를 생략하면 완료 상태 JSON을 출력합니다.

```bash
h3video cancel video_0001 --ref
```

원격 영상 하나에 취소를 요청합니다. cancelling은 취소 처리 중, cancelled는 취소 완료입니다. 이미 completed라면 완료 상태를 그대로 보여 줍니다. 취소 API를 지원하지 않는 서버에서는 종료 코드 1과 안내를 내보내며, 원격 작업은 계속될 수 있습니다. 다른 배치 작업까지 모두 취소하는 명령은 아닙니다.

### 배치·JSON 요청을 제출 전에 확인

```bash
h3video batch prompts.txt --dry-run --json
h3video json story.json --dry-run --json
h3video ir prompt.txt --dry-run --json
h3video jobs --task ref2va --status failed --json
h3video doctor --ref
```

batch·json의 --dry-run --json은 모든 작업의 요청을 단일 JSON으로 출력합니다. ir의 --dry-run도 프롬프트 다듬기를 요청하지 않습니다. 잘못된 해상도·스텝·참고 자료 조합은 첫 작업을 제출하기 전에 거절합니다. jobs는 상태·모드로 거른 다음 --limit을 적용하고, 기록이 없으면 --json에서 빈 배열을 출력합니다. doctor·health의 --ref는 참고 자료 서버를 필수로 점검합니다.

영상 다운로드는 메모리에 전체 영상을 올리지 않고 임시 파일로 받습니다. 응답이 끊기거나 크기가 맞지 않으면 기존 결과 파일을 보존합니다. 폴더로 내보낼 때 같은 이름이 여러 번 생겨도 이전 내보내기를 덮어쓰지 않습니다.

### 설치·입력·결과 경로

| 구분 | 기본 위치 |
|---|---|
| 코드·스크립트 | `scripts/up.sh`가 있는 폴더, 예: `/user-volume/minimax-h3-video` |
| 설치된 Python | `$VENV/bin/python` → `/group-volume/minsoo3.kim/minimax-h3-video/.venv-diffusers/bin/python` |
| CLI 실행 파일 | `$VENV/bin/h3video` → `/group-volume/minsoo3.kim/minimax-h3-video/.venv-diffusers/bin/h3video` |
| 원본 입력 권장 위치 | `$H3_INBOX_DIR` → `/group-volume/minsoo3.kim/minimax-h3-video/inbox` |
| 결과·작업 기록 | `$H3_OUTPUT_DIR` → `/group-volume/minsoo3.kim/minimax-h3-video/outputs` |

`.cluster_env.local.sh`에서 저장 위치를 바꿨다면 위 기본값 대신 6단계에 출력되는 경로를 사용합니다.

**Python은 있는데 h3video 실행 파일만 없을 때:** 코드 폴더에서 `"$VENV/bin/python" -m pip install --no-deps -e .`로 실행 명령만 등록할 수 있습니다. 모델이나 PyTorch·CUDA 패키지를 다시 설치하지 않습니다. `$VENV/bin/python`도 없으면 `.cluster_env.local.sh`의 경로와 `provision.sh` 설치 완료 여부를 확인하세요.

CLI 실행 예시는 [VIDEO.md](VIDEO.md#cli-파일옵션별-실행-예시)와 `studio/h3-cli.html` 맨 위에 모았습니다. `--first start.png`는 첫 프레임, `--image 1.png`는 인물 등 참고 사진, `--video sample.mp4`는 동작·장면 참고 영상입니다. 각 옵션의 뜻과 입력·출력 파일을 포함한 명령 예시 20개를 제공합니다.

상단 **영상 교정 · 새 영상 · 영상 편집 · 작업·결과** 메뉴로 이동합니다. **전체 22개 기능 찾기**를 펼치면 검색과 분류를 사용할 수 있고, 편집실의 PDF·검토·일괄 편집·수정본은 **프로젝트 도구**에 모았습니다. 상단 **기능별 사용법**에서 영상 교정·자막·소리·장면 편집·생성·출력 등22개 기능의 입력, 실행 순서와 결과를 확인합니다. 제작실 맨 위의 **영상 넣고 프롬프트로 교정**에서 파일과 수정 요청을 바로 입력할 수 있습니다. 이 경로는 원본을 새 프로젝트에 보관하고 Qwen 프레임 보정과 Real-ESRGAN2배·4배 확대를 실행합니다. 출력 배율은 실행 전에 표시하며 기존 프로젝트와 원본을 덮어쓰지 않습니다. 설치·H100·CLI 안내는 설명서 하단에 모았습니다. 정본은 `src/h3video/studio/h3-cli.html`이며 기존 `/studio/` 정적 경로에서 서버 재시작 없이 파일을 제공할 수 있다. 공개 경로는 `/video-maker/studio/h3-cli.html`이다.


## 엔진·CUDA 패키지

`provision.sh`·`up.sh`·`web.sh`의 기본 엔진은 **Diffusers**다. SGLang은 각 명령에 `--engine sglang`을 명시할 때만 선택한다. 드라이버 버전으로 자동 전환하지 않는다.

Diffusers는 torch 2.7.1+cu126·torchvision 0.22.1+cu126·torchaudio 2.7.1+cu126을 같은 공식 CUDA 12.6 저장소에서 설치하고 CPU NMS까지 확인한다. 기존 설치의 CUDA 주버전 불일치는 `bash scripts/fix_torchvision.sh`, 패키지 전체 정합성은 `bash scripts/provision.sh --skip-model`로 복구한다.

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
9. **스토리보드 PDF**: 장면마다 미리보기(선택 영상의 한 프레임 또는 그림 콘티)·번호·시간·길이·프롬프트·자막을 A4 인쇄 레이아웃으로 모아 브라우저 인쇄에서 PDF로 저장합니다.

편집 기록은 기존 결과 경로의 `_studio/edit-<id>/project.json`, 원본·후보는 `media/`, 출력은 `exports/`에 저장합니다. CPU 작업과 업스케일은 중지·재개할 수 있습니다. 완료한 업스케일 프레임은 `.work/<task>/restored/`에 보존하며 그대로 이어서 처리합니다. 중지 후 설정이 바뀌면 새 설정으로 작업을 다시 시작하고 기존 결과는 유지합니다. 후보 생성은 기존 H3 worker의 중지·재개를 사용합니다.

자동 자막 도구 설치: `npm run install:studio`. 별도 `.venv-video-studio`와 사용자 도구 폴더에 설치하며 모델을 CPU int8로 실행합니다. Whisper 모델 리비전은 `scripts/video-tools.json`에 고정합니다. AI 업스케일과 얼굴 비교는 인접 `storybook-maker`의 설치된 Real-ESRGAN·DINOv2 도구를 재사용합니다. 각각 그 저장소의 `npm run install:studio`, `npm run install:consistency`로 설치할 수 있습니다.

설치 스크립트에는 버전을 고정한 yt-dlp와 공식 Tesseract의 리비전을 고정한 한글·영문 언어팩도 포함합니다. 시스템의 FFmpeg·ffprobe·Tesseract 실행 파일이 필요합니다. 참고 분석 검증은 `python3 -m unittest discover -s tests -p test_reference.py -v`, Qwen API·실제 확대 검증은 `python3 -m unittest discover -s tests -p test_qwen_retouch.py -v`입니다. Qwen 테스트는 이미지 편집 API만 모의 서버로 대체하고 프레임 추출·실제 Real-ESRGAN 확대·소리 복원·원본 보존은 실제 도구로 확인합니다.

브라우저 검증: `npm run test:reference`. 실제 OCR로 글자를 분석하고 글꼴·좌표 수정, ZIP 내려받기, 기존 프로젝트 보존, 새 프로젝트 가져오기와 재접속 복원을 320·390·820·1440px에서 검사합니다. 저장할 때 `typography_prompt`를 수정한 영역에서 다시 만들고 가져온 프로젝트의 영상 프롬프트에도 반영합니다.

검증: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_video_studio.py -v`, `npm run test:studio`. 실제 FFmpeg, Whisper와 AI 업스케일을 사용하며 영상 생성 API만 CPU 모의 서버로 검사합니다. 전체 테스트에는 기존 H3 Diffusers 테스트 환경이 필요합니다. 음성 스모크 검사는 [Whisper 공식 테스트 음성](https://github.com/openai/whisper/blob/main/tests/jfk.flac)을 `H3_ASR_FIXTURE` 또는 사용자 도구 폴더의 `jfk.flac`으로 사용합니다.

구현 근거: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Real-ESRGAN NCNN](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan), [FFmpeg 필터](https://ffmpeg.org/ffmpeg-filters.html).

웹과 편집 도구만 사용자 서비스로 배포하려면 `python3 scripts/install-web-service.py`를 실행합니다. 기존 8790 포트와 CLI에 저장한 생성 서버 설정을 사용하며 GPU 생성 서버는 시작하지 않습니다. 중지는 `systemctl --user stop h3video-web.service`입니다.

MiniMax-H3(Hailuo 3.0) 오픈 가중치를 H100 클러스터에서 기본 Diffusers로 서빙하고, 프롬프트만 넣으면 오디오 포함 영상을 만들어 주는 도구.
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
scripts/cluster_env.sh   # fdmu 규약: 저장은 /group-volume/minsoo3.kim/minimax-h3-video, 모델 기본값은 /rdata/models/MiniMax-H3
scripts/provision.sh     # 기본 Diffusers venv + FL2VA/Ref2VA 가중치 준비(받아 둔 곳 자동 검색, 받기는 --download 일 때만)
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

명령 하나로 띄우고 끈다. 환경 설정, 모델·선택 엔진·GPU·포트 점검 뒤 서버와 웹 UI 를 **이 화면에서 포그라운드로** 돌린다. 서버 원본 로그와 오류가 그대로 나오고, 준비되면 PC 접속 명령을 출력한다. Ctrl+C 로 서버·워커·웹 UI 를 전부 끄고 GPU 반환까지 확인한다(오래 띄워 둘 거면 직접 연 tmux 창 안에서 실행).

```bash
cd /user-volume/<you>/minimax-h3-video
bash scripts/up.sh             # fl2va + ref2va 서버(기본은 빈 GPU를 분할). --fl2va-only로 글·첫/끝 프레임 서버만, --web 으로 웹 UI 8790 도, --check 는 점검만
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

## 원본 이미지·영상 입력

파일 종류를 자동으로 고르는 `--input`(`-i`)을 파일마다 반복합니다. 이 옵션은 **참고 자료**로 사용합니다. 실제 첫 장면을 고정할 때는 `--first`, 마지막 장면은 `--last`를 사용합니다.

```bash
# 로컬 파일 검사: 실제 크기·해상도·길이. GPU 작업을 제출하지 않음
h3video inspect "inputs/인물 사진.png" inputs/motion.mp4
h3video inspect inputs/motion.mp4 --json

# 사진과 영상 참고. Ref2VA 서버가 준비돼 있어야 실제 생성 가능
h3video gen "1번 사진의 인물, 1번 영상의 걷는 동작" \
  -i "inputs/인물 사진.png" -i inputs/motion.mp4 -s 8

# 첫 장면 이미지에서 출발
h3video gen "인물이 천천히 고개를 돌린다" --first "inputs/인물 사진.png" -s 8

# 생성·복사 없이 단일 JSON 계획 확인
h3video gen "1번 영상의 동작" -i inputs/motion.mp4 --dry-run --json
```

- `--input`과 `--image/--video/--audio`를 섞어 써도 입력 순서를 보존합니다. `--first/--last`와 참고 자료를 혼합하면 생성 전에 오류를 표시합니다.
- H100에서 CLI를 실행하면 그 서버나 연결된 공유 폴더의 경로를 줍니다. PC에서 원격 GPU 서버에 접속할 때 PC 경로가 자동 업로드되지는 않습니다. 파일을 공유 폴더로 옮기거나 웹 화면의 파일 업로드를 사용하세요.
- `file:///경로`는 생성 서버가 읽는 경로입니다. HTTP(S)·file URI는 `inspect`에서 내용을 가져오지 않고 **미확인**으로 표시합니다.
- `inspect`는 FFprobe가 있으면 실제 미디어 메타데이터를 읽습니다. FFprobe가 없으면 해상도·길이를 미확인으로 남깁니다. 파일 하나라도 없거나 손상됐으면 JSON 전체 `ok: false`와 종료 코드 1을 반환합니다.
- `--dry-run --json`은 한 개의 JSON만 표준 출력으로 보냅니다. 파일을 복사하거나 GPU 작업을 제출하지 않습니다. 공유 입력 폴더가 설정돼 있으면 실제 실행 때 파일 URI가 입력 사본의 경로로 바뀔 수 있음을 계획에 표시합니다.
- 실행 시 공유 입력 사본은 1MiB씩 읽고 임시 파일에서 완성한 뒤 공개합니다. 복사 도중 실패하거나 원본이 바뀌면 불완전한 파일을 사용하지 않습니다.

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

## 여러 편 한꺼번에 (밤새 돌려 두기)

웹의 `JSON 한번에` 아래 `여러 편 한꺼번에`에 JSON·zip을 여러 개 넣으면 한 파일이 한 편이 된다. 동화책 만들기의 `파일 받기` zip은 안의 그림을 첫 장면으로 쓰고, JSON만 넣은 편은 위 `쪽 그림`을 이름으로 맞춰 쓴다. 화면비·크기·시드·내레이션과 주요 인물 설정(비워 두면 JSON마다 들어 있는 인물 설정)은 모든 편에 같이 쓴다.

- 편마다 `POST /api/story`에 `multi=<묶음 이름>`을 붙여 넣고, 서버 대기열이 차례로 만든다. 넣은 편 목록과 카드에서 진행을 본다.
- `multi`가 붙은 이야기는 서버가 30초마다 살핀다: 장면이 다 되면 화면 없이도 이어 붙이고, 서버를 다시 켜서 대기열에서 빠진 장면은 다시 넣고, 영상 서버가 꺼지거나 끊겨(연결 실패·끊김·대기 시간 초과·HTTP 5xx) 실패한 장면은 1·2·5·10분 기다렸다가 다시 만든다(횟수 제한 없음). 그 밖의 실패는 두 번까지만 다시 하고, 사용자가 멈춘 이야기는 그대로 둔다.

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

## 현재 작업과 완료된 영상

화면 맨 위에서 영상 엔진 연결과 진행·대기 작업을 봅니다. 영상 생성은 현재 장면·단계를, 편집·모션 출력·참고 영상 분석은 해당 작업을 구분해 표시합니다. 작업 목록은 진행·대기, 완료된 결과, 미완성·중지·실패로 나뉘며, 완료 시 해당 영역으로 이동합니다. `npm run test:activity`로 상태 API와 브라우저 전환을 검증합니다.

## 제작 템플릿과 연출 도우미

숏폼과 영상 만들기의 **템플릿으로 기획**에서 제품·사용법·여행·음식·이야기·비교 템플릿을 검색하고 주제·장소·훅·마지막 문장, 비율·길이·카메라·조명을 정한다. 초안을 미리 만든 뒤 자막과 이미지·영상 프롬프트를 직접 고쳐 적용한다. 템플릿은 직접 작성한 구성 초안이며 AI를 호출하거나 영상을 자동 생성하지 않는다.

숏폼에 적용하면 이전 작업을 보관하고 새 저장본을 만든다. FRAME의 **숏폼 제작으로 보내기**는 같은 출처의 준비·수신 확인을 거쳐 장면·자막·피할 요소를 전달한다. 영상 편집실과 재개 편집창의 **연출 도우미**는 기존 피사체 설명을 유지하면서 선택한 카메라·조명 지시를 바꾸며, 저장·생성은 기존 버튼으로 실행한다.

공통 구현은 `src/h3video/studio/prompt-library.js`이다. FRAME은 독립 빌드를 위해 같은 파일을 `lib/prompt-library.js`에 보관한다. 공통 구현을 바꾸면 두 파일을 함께 갱신하고 프로젝트 스키마·JS/Python 변환 및 양쪽 브라우저 검사를 실행한다. 공개 영상 갤러리의 카메라·샷·분위기 탐색 방식은 https://www.bananaprompts.xyz/videos 에서 참고했으며 프롬프트와 디자인 자산은 복제하지 않았다.
