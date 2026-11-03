# H3 버그·회귀 영구 기록

[현황판 영구 기록 #1153](https://77model.pages.dev/bug-board/#item=1153)

현재 H3 작업 담당은 Codex다. CPU 태그를 GPU로 옮긴 회귀, 배포 중 폰트 유실, CSS·JS MIME 오지정 등 확인된 책임을 이 기록에 남긴다.

수정했거나 완료로 표시했던 항목도 지우지 않는다. 원래 기록·실패 배포·부족했던 검증·재발·정정 내용을 함께 보존한다.

- 원인·증상별 기록: **29항목**. 같은 사건의 설치·문서·검증 문제를 나누어 기록한 항목이 있어 독립 장애 횟수와 같지 않다.
- 전체 Git 이력: **181커밋**, [1d5fdf5](https://github.com/33modeling/minimax-h3-video/commit/1d5fdf59de5b37b11af123579bcbff1da94253db)까지. 이 문서 자체를 추가하는 다음 커밋은 스냅샷 범위 밖이다.
- 현황판 원본: **16항목**의 본문·상태·이벤트 스냅샷. 당시 완료 표시는 실제 H100 완주를 뜻하지 않을 수 있다.
- **H100 8장 전체 모델의 OOM 해소·완주는 아직 미확인이다.** 실제 RTX 3050의 작은 모델 검사와 구분한다.
- 과거 최초 유입 커밋·작성 AI를 증명하지 못한 항목은 미확정으로 둔다. Git 작성자명이 같다는 이유로 다른 실행 주체를 단정하지 않는다.

| 기록 | 문제 | 구분 | 현재 근거·상태 |
|---|---|---|---|
| [H3-001](#h3-001) | H3 설명서를 장면 분석실에 잘못 배치하고 H100 설치 메뉴를 숨김 | 설명서·메뉴 | 수정·공개 UI 검증 |
| [H3-002](#h3-002) | Diffusers 변환 모델이 완전해도 별도 원본 모델이 없다는 이유로 시작 차단 | 설치 | 시작 제어 흐름 수정·사용자 H100 성공 미확인 |
| [H3-003](#h3-003) | PyTorch·torchvision의 CUDA 빌드 불일치 | 설치 | 설치 조합 정정·사용자 H100 재확인 필요 |
| [H3-004](#h3-004) | 드라이버 CUDA 버전으로 기본 엔진을 SGLang으로 자동 변경 | 엔진 선택 | 기본 Diffusers·명시 SGLang으로 정정 |
| [H3-005](#h3-005) | 엔진 선택 보강 중 설정된 웹 포트·CORS를 제대로 보존하지 못함 | 설정 | 설정 보존 수정 |
| [H3-006](#h3-006) | 설치 노드에서 h3video 명령 위치·Python 직접 실행 안내가 불명확 | 설명서 | Python 직접 실행·설정 읽기 안내 추가 |
| [H3-007](#h3-007) | 참고 입력을 보내는데 Ref2VA 서버 30011이 시작되지 않음 | 시작 동작 | 실행 규칙 정정·실제 H100 성공 미확인 |
| [H3-008](#h3-008) | 기본 실행을 양 서버 2+2로 바꿔 Ref2VA OOM 위험에 노출 | GPU 배치 | 2+2 차단 수정·H100 OOM 해소 미측정 |
| [H3-009](#h3-009) | 2+2 실행을 차단한 뒤에도 설명서 표에 이전 안내를 남김 | 설명서 | 이전 안내 정정 |
| [H3-010](#h3-010) | GPU 수·번호를 불필요하게 직접 입력하게 한 실행 안내 | 사용성 | 빈 GPU 자동 배정으로 정정 |
| [H3-011](#h3-011) | 8장을 배정해도 CP 워커마다 영상 모델 가중치를 복제 | 메모리 설계 | 가중치 분산 코드 수정·H100 전체 완주 미확인 |
| [H3-012](#h3-012) | 출력 --size를 줄여도 참고 이미지·영상 인코딩 크기를 유지 | 메모리 설계 | 참고 geometry 연동 수정·H100 전체 완주 미확인 |
| [H3-013](#h3-013) | OOM 때 출력 크기만 줄이면서 모델 전체를 매번 재적재 | 재시도 | sharded CUDA OOM의 전체 재적재 제거 |
| [H3-014](#h3-014) | 가중치 분산 패치가 CPU text_token_tags까지 GPU로 전송해 생성 실패 | 코드 회귀 | 실제 작은 CUDA 모델 3종 통과·H100 전체 완주 미확인 |
| [H3-015](#h3-015) | 설명서 CSS·JS를 text/html MIME으로 업로드 | 배포 회귀 | 수정 배포·공개 MIME/해시·4폭 UI 검증 |
| [H3-016](#h3-016) | 배치가 지원하지 않는 해상도를 통과시킴 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-017](#h3-017) | 배치가 오디오만 있는 Ref2VA 요청을 허용 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-018](#h3-018) | 배치에서 첫 프레임과 참고 입력을 섞으면 첫 프레임을 무시 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-019](#h3-019) | 생성 스텝 0을 기본 스텝으로 바꿔 처리 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-020](#h3-020) | IR dry-run이 실제 다듬기 API를 호출 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-021](#h3-021) | jobs --json이 작업이 없으면 JSON 대신 안내문 출력 | CLI 검증 | 전후 재현·CLI 회귀 검증 |
| [H3-022](#h3-022) | 실제 로컬 Arcade 캐시에 필요한 JS 모듈 3개 누락 | 동기화 | 정본 복원·로컬 처리 경로 검증 |
| [H3-023](#h3-023) | 모바일·태블릿 조작과 오류 표시 등 UI 결함 묶음 | UI | 화면·기능 연결 검증 |
| [H3-024](#h3-024) | 배포 보존 검사 실패 뒤에도 업로드가 진행되어 기존 폰트 4개 누락 | 배포 회귀 | 폰트 복원·4개 URL/해시·배포 차단 검사 검증 |
| [H3-025](#h3-025) | CPU·정적 검사 통과를 근거로 H100 메모리 해결을 충분히 검증하지 못함 | 검증 누락 | 검증 한계 기록·사용자 H100 완주 미확인 |
| [H3-026](#h3-026) | 장치 오류 조사 중 root hook 실행 장치 누락을 직접 원인으로 먼저 단정 | 진단 오류 | 설명 정정·잘못된 훅 변경은 커밋하지 않음 |
| [H3-027](#h3-027) | diffusers 없는 환경에서 MaxSecondsTest가 None != 12로 실패 | 기존 테스트 결함 | 기존 수정 이력 보존·이번 기록 작업에서 재시험하지 않음 |
| [H3-028](#h3-028) | OOM 수정의 순차 레이어 분산 이후 낮은 GPU 활용률·90분 초과 생성 보고 | 성능·검증 누락 | 사용자 보고·구조 확인 / 실제 실행 경로와 H100 성능 미검증 |
| [H3-029](#h3-029) | 실제 프레임·단계와 다른 진척률·연결 끊김 표시 | 진척 표시 | 코드·공개/실제 Arcade 4폭·두빌드 검증 |

## 증거 원장

- [구조화한 사건 기록](BUG-LEDGER.json)
- [전체 181개 커밋: 제목·본문·부모·변경 파일·링크](bug-ledger/source-history-20261103.json)
- [현황판 본문·상태·이벤트 원본 스냅샷](bug-ledger/board-snapshot-20261103.json)
- [CLI 6건의 수정 전후 출력](cli-audit-20261103.json)
- [8GPU OOM 설계 수정과 검증 한계](h100-oom-sharding-20261103.json)
- [CPU/GPU 회귀와 실제 CUDA 검사](sharded-device-boundary-20261103.json)

## 사건별 기록

### H3-001

**H3 설명서를 장면 분석실에 잘못 배치하고 H100 설치 메뉴를 숨김**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 수정·공개 UI 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [1a0e7a8](https://github.com/33modeling/minimax-h3-video/commit/1a0e7a8604e1e3279d706e45ae22fb7e97be6816)
- 현황판: [#1024](https://77model.pages.dev/bug-board/#item=1024)
- H3 정본 대신 CUT LAB에 게시
- 발견 가능한 H3 메뉴 누락
- H100 로컬 설치·운영 안내 누락
- 근거 위치: board:1024:reopened; 관련 scene 수정 695bbf9302aba668ffe7269c29a20c017beaf2fb

### H3-002

**Diffusers 변환 모델이 완전해도 별도 원본 모델이 없다는 이유로 시작 차단**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 시작 제어 흐름 수정·사용자 H100 성공 미확인
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [d1f8d4e](https://github.com/33modeling/minimax-h3-video/commit/d1f8d4e386efcce8a8365605697dafb126b438aa)
- 현황판: [#1028](https://77model.pages.dev/bug-board/#item=1028)
- 근거 위치: tests/test_up_preflight.py; board:1028

### H3-003

**PyTorch·torchvision의 CUDA 빌드 불일치**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 설치 조합 정정·사용자 H100 재확인 필요
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [98bfa4c](https://github.com/33modeling/minimax-h3-video/commit/98bfa4cf1d9fd9040551fcb0ca87e65d07b29492)
- 현황판: [#1028](https://77model.pages.dev/bug-board/#item=1028)
- 근거 위치: 사용자 CUDA major mismatch 보고; constraints/h100-cu126-diffusers.txt

### H3-004

**드라이버 CUDA 버전으로 기본 엔진을 SGLang으로 자동 변경**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 기본 Diffusers·명시 SGLang으로 정정
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [98bfa4c](https://github.com/33modeling/minimax-h3-video/commit/98bfa4cf1d9fd9040551fcb0ca87e65d07b29492)
- 현황판: [#1028](https://77model.pages.dev/bug-board/#item=1028)
- 근거 위치: scripts/cluster_env.sh; board:1028

### H3-005

**엔진 선택 보강 중 설정된 웹 포트·CORS를 제대로 보존하지 못함**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 설정 보존 수정
- 유입 확인 커밋: [98bfa4c](https://github.com/33modeling/minimax-h3-video/commit/98bfa4cf1d9fd9040551fcb0ca87e65d07b29492)
- 수정·정정 커밋: [a4725f9](https://github.com/33modeling/minimax-h3-video/commit/a4725f9b6c94a051cbf1100374525cd6fc88279d)
- 현황판: [#1028](https://77model.pages.dev/bug-board/#item=1028)
- 근거 위치: git diff a4725f9 -- scripts/web.sh; tests/test_up_preflight.py

### H3-006

**설치 노드에서 h3video 명령 위치·Python 직접 실행 안내가 불명확**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: Python 직접 실행·설정 읽기 안내 추가
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [cbad709](https://github.com/33modeling/minimax-h3-video/commit/cbad709a0217485305d9819fbb9056cdb1f77e09), [836a9ad](https://github.com/33modeling/minimax-h3-video/commit/836a9ad29e01b62fca0c1254580c719a64b22cc8)
- 현황판: [#1024](https://77model.pages.dev/bug-board/#item=1024)
- 근거 위치: 사용자 h3video 실행 파일이 없다는 보고; 설치 가이드 cli-location

### H3-007

**참고 입력을 보내는데 Ref2VA 서버 30011이 시작되지 않음**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 실행 규칙 정정·실제 H100 성공 미확인
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [7137908](https://github.com/33modeling/minimax-h3-video/commit/7137908995a24469cf55a02579fbe6aff96daa98), [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 현황판: [#1106](https://77model.pages.dev/bug-board/#item=1106)
- 당시 기본 REF=0으로 참고 요청이 연결 실패
- 이후 사용자 요청대로 기본 실행과 --ref 실행을 구분
- 현재 --ref는 양 서버 실행이며 기본 단독 실행은 의도된 규칙
- 근거 위치: board:1106; scripts/up.sh

### H3-008

**기본 실행을 양 서버 2+2로 바꿔 Ref2VA OOM 위험에 노출**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 2+2 차단 수정·H100 OOM 해소 미측정
- 유입 확인 커밋: [7137908](https://github.com/33modeling/minimax-h3-video/commit/7137908995a24469cf55a02579fbe6aff96daa98)
- 수정·정정 커밋: [921af91](https://github.com/33modeling/minimax-h3-video/commit/921af9176d4762483a9fa856aebcebf278e5675b)
- 현황판: [#1107](https://77model.pages.dev/bug-board/#item=1107)
- 2+2 배정 로직은 이전에도 --ref 실행에서 가능했음
- 7137908은 양 서버 시작을 기본으로 바꿔 이 위험을 기본 실행에 노출한 커밋
- 근거 위치: board:1107; tests/test_startup_resources.py

### H3-009

**2+2 실행을 차단한 뒤에도 설명서 표에 이전 안내를 남김**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 이전 안내 정정
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [943eb70](https://github.com/33modeling/minimax-h3-video/commit/943eb709edbcfa38ccc3b4421aac69c300f95364), [35f9e69](https://github.com/33modeling/minimax-h3-video/commit/35f9e69734b54f94c0be2cd983c1105223d6666c)
- 현황판: [#1107](https://77model.pages.dev/bug-board/#item=1107)
- 근거 위치: git diff 943eb70; board:1107

### H3-010

**GPU 수·번호를 불필요하게 직접 입력하게 한 실행 안내**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 빈 GPU 자동 배정으로 정정
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 현황판: [#1107](https://77model.pages.dev/bug-board/#item=1107)
- 근거 위치: 사용자의 --ref 유무만으로 실행하라는 지시; tests/test_up_preflight.py

### H3-011

**8장을 배정해도 CP 워커마다 영상 모델 가중치를 복제**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 가중치 분산 코드 수정·H100 전체 완주 미확인
- 유입 확인 커밋: [4c33028](https://github.com/33modeling/minimax-h3-video/commit/4c33028663244e321a2e333a5252370663437260)
- 수정·정정 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)
- 현황판: [#1149](https://77model.pages.dev/bug-board/#item=1149)
- 약 61.7GiB 가중치가 워커별로 상주
- GPU 8장의 메모리를 하나로 합쳐 쓰는 방식이 아님
- Meta 크기 계산은 실제 VRAM 최대 사용량 측정이 아님
- 근거 위치: src/h3video/dworker.py; docs/h100-oom-sharding-20261103.json

### H3-012

**출력 --size를 줄여도 참고 이미지·영상 인코딩 크기를 유지**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 참고 geometry 연동 수정·H100 전체 완주 미확인
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)
- 현황판: [#1149](https://77model.pages.dev/bug-board/#item=1149)
- 참고 이미지 기본 short edge 2048
- 참고 영상은 출력 height/width와 별도 canvas 설정 사용
- 근거 위치: docs/h100-oom-sharding-20261103.json; tests/test_placement.py

### H3-013

**OOM 때 출력 크기만 줄이면서 모델 전체를 매번 재적재**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: sharded CUDA OOM의 전체 재적재 제거
- 유입 확인 커밋: [6da4947](https://github.com/33modeling/minimax-h3-video/commit/6da494775e6972df58f6753319cc7e99c7d0cc36)
- 수정·정정 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)
- 현황판: [#1149](https://77model.pages.dev/bug-board/#item=1149)
- 재적재 코드 존재는 확인됨
- 사용자 H100에서 재적재가 차지한 실제 최대 메모리는 미측정
- 근거 위치: git history self.reload_engine(error); docs/h100-oom-sharding-20261103.json

### H3-014

**가중치 분산 패치가 CPU text_token_tags까지 GPU로 전송해 생성 실패**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 실제 작은 CUDA 모델 3종 통과·H100 전체 완주 미확인
- 유입 확인 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)
- 수정·정정 커밋: [1d5fdf5](https://github.com/33modeling/minimax-h3-video/commit/1d5fdf59de5b37b11af123579bcbff1da94253db)
- 현황판: [#1151](https://77model.pages.dev/bug-board/#item=1151)
- 사용자 오류: cuda:1 and cpu, 외부 호출 dserver.py:876
- CPU packed-layout 배열의 고급 인덱스 대입과 CUDA 태그 충돌
- 직전 71개 CPU 검사만으로 이 결함을 잡지 못함
- 근거 위치: docs/sharded-device-boundary-20261103.json; bug-ledger/evidence/cuda-device-reproduction.log; tests/test_device_boundary.py

### H3-015

**설명서 CSS·JS를 text/html MIME으로 업로드**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 수정 배포·공개 MIME/해시·4폭 UI 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [1f04b3a](https://github.com/33modeling/minimax-h3-video/commit/1f04b3a7e5862a38bc4a776b5ac8cfd68d6e279b)
- 현황판: [#1145](https://77model.pages.dev/bug-board/#item=1145)
- 실패 배포 550de51d-eab8-41c9-bb36-13cb5a177101
- 동일 자산 키의 메타데이터 재업로드만으로 복구되지 않음
- 새 자산 키·올바른 MIME으로 8a087fda 배포
- 근거 위치: bug-ledger/evidence/mime-failed-publication.json; bug-ledger/evidence/mime-fixed-publication.json

### H3-016

**배치가 지원하지 않는 해상도를 통과시킴**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1118](https://77model.pages.dev/bug-board/#item=1118)
- 근거 위치: docs/cli-audit-20261103.json:invalid-batch-size; tests/test_cli_workflows.py

### H3-017

**배치가 오디오만 있는 Ref2VA 요청을 허용**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1119](https://77model.pages.dev/bug-board/#item=1119)
- 근거 위치: docs/cli-audit-20261103.json:audio-only-batch; tests/test_cli_workflows.py

### H3-018

**배치에서 첫 프레임과 참고 입력을 섞으면 첫 프레임을 무시**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1120](https://77model.pages.dev/bug-board/#item=1120)
- 근거 위치: docs/cli-audit-20261103.json:mixed-batch-modes; tests/test_cli_workflows.py

### H3-019

**생성 스텝 0을 기본 스텝으로 바꿔 처리**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1121](https://77model.pages.dev/bug-board/#item=1121)
- 근거 위치: docs/cli-audit-20261103.json:zero-steps; tests/test_cli_workflows.py

### H3-020

**IR dry-run이 실제 다듬기 API를 호출**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1122](https://77model.pages.dev/bug-board/#item=1122)
- 근거 위치: docs/cli-audit-20261103.json:ir-dry-run; tests/test_cli_workflows.py

### H3-021

**jobs --json이 작업이 없으면 JSON 대신 안내문 출력**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 전후 재현·CLI 회귀 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 확인한 수정 전 스냅샷: [3760b51](https://github.com/33modeling/minimax-h3-video/commit/3760b5191c7baa75ba91751827c440df8d52a956)
- 수정·정정 커밋: [5a7e937](https://github.com/33modeling/minimax-h3-video/commit/5a7e937b7506b0eb693b8d7f8e569e2a98ba3eee)
- 현황판: [#1123](https://77model.pages.dev/bug-board/#item=1123)
- 근거 위치: docs/cli-audit-20261103.json:empty-jobs-json; tests/test_cli_workflows.py

### H3-022

**실제 로컬 Arcade 캐시에 필요한 JS 모듈 3개 누락**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 정본 복원·로컬 처리 경로 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [8b911e6](https://github.com/33modeling/minimax-h3-video/commit/8b911e66e84006e0f28c45cde109e6d04617a14c)
- 현황판: [#1024](https://77model.pages.dev/bug-board/#item=1024)
- storyboard.js
- ai-keys.js
- handoff-store.js
- 근거 위치: board:1024; /home/kms/reports/h3-features-20261102/local-module-restoration.json

### H3-023

**모바일·태블릿 조작과 오류 표시 등 UI 결함 묶음**

- 책임 근거: 본 대화에서 Codex가 수정·검증을 담당. 최초 유입 커밋 또는 작성 AI는 미확정
- 상태: 화면·기능 연결 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [0f733fe](https://github.com/33modeling/minimax-h3-video/commit/0f733feeb43f04ae71906c3c51c56bece0b2a7bd), [92ee107](https://github.com/33modeling/minimax-h3-video/commit/92ee107782025b7365ae520c2784222e32135fb3)
- 현황판: [#1024](https://77model.pages.dev/bug-board/#item=1024)
- 상단 작업 이동·기능 목록 접기·프로젝트 도구 묶음
- 키보드 탭 및 입력 이름 9개
- 분석 오류·파일 선택 접근성
- 템플릿 모바일 버튼·터치 대상
- 모션 화면비·긴 작업명·다크 대비
- 코드 복사 겹침·모바일 한글 코드 글꼴
- 근거 위치: board:1024; /home/kms/reports/h3-ui-audit-20261102/completion.json

### H3-024

**배포 보존 검사 실패 뒤에도 업로드가 진행되어 기존 폰트 4개 누락**

- 책임 근거: Codex가 유입시킨 오류·회귀가 대화 또는 실패 배포 기록으로 확인됨
- 상태: 폰트 복원·4개 URL/해시·배포 차단 검사 검증
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 현황판: [#1094](https://77model.pages.dev/bug-board/#item=1094)
- 검사와 업로더를 별도 셸 명령으로 실행해 실패 후 중단하지 못함
- 실패 배포 321432a8
- 누락 228584바이트
- 정정 배포 4d1c0ab5
- 근거 위치: board:1094; bug-ledger/evidence/restored-font-hashes.json

### H3-025

**CPU·정적 검사 통과를 근거로 H100 메모리 해결을 충분히 검증하지 못함**

- 책임 근거: Codex의 설명·검증 누락 확인
- 상태: 검증 한계 기록·사용자 H100 완주 미확인
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836), [1d5fdf5](https://github.com/33modeling/minimax-h3-video/commit/1d5fdf59de5b37b11af123579bcbff1da94253db)
- 현황판: [#1149](https://77model.pages.dev/bug-board/#item=1149), [#1151](https://77model.pages.dev/bug-board/#item=1151)
- 8GPU 배정과 메모리 해결을 구분하지 않은 안내
- 71개 CPU 검사에 CUDA/CPU indexed assignment 재현이 빠짐
- 실제 RTX 3050 작은 모델 검사와 H100 전체 모델 검증을 구분
- 근거 위치: docs/h100-oom-sharding-20261103.json; docs/sharded-device-boundary-20261103.json; 본 대화에서 8장 배정만으로 해결되는 것처럼 안내한 점 정정

### H3-026

**장치 오류 조사 중 root hook 실행 장치 누락을 직접 원인으로 먼저 단정**

- 책임 근거: Codex의 초기 진단 오류 확인
- 상태: 설명 정정·잘못된 훅 변경은 커밋하지 않음
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [1d5fdf5](https://github.com/33modeling/minimax-h3-video/commit/1d5fdf59de5b37b11af123579bcbff1da94253db)
- 현황판: [#1151](https://77model.pages.dev/bug-board/#item=1151)
- 실제 Accelerate는 main device를 root 실행 장치로 설정함
- 직접 원인은 준비 단계의 CPU 태그/CUDA 태그 충돌
- 정정한 근거와 원인만 최종 코드에 반영
- 근거 위치: 본 대화의 조사 중 설명 및 이후 CUDA 재현으로 정정

### H3-027

**diffusers 없는 환경에서 MaxSecondsTest가 None != 12로 실패**

- 책임 근거: 기존 Git·현황판 이력. 작성 AI는 미확정
- 상태: 기존 수정 이력 보존·이번 기록 작업에서 재시험하지 않음
- 최초 유입 커밋: 미확정. 수정 커밋을 최초 유입으로 대신 적지 않는다.
- 수정·정정 커밋: [018cf45](https://github.com/33modeling/minimax-h3-video/commit/018cf4580edec98859b4555aa4e189449a96bb20)
- 현황판: [#41](https://77model.pages.dev/bug-board/#item=41)
- 근거 위치: board:41; git commit 018cf45

### H3-028

**정정: 사용자가 말한 1080p·16초는 입력 영상이다. 이를 출력 길이로 오인해 8초+8초 분할 설명을 적용한 것은 Codex의 오류다. 실제 출력 길이와 지연 단계는 아직 미확인이다.** [정정 원본](bug-ledger/evidence/input-video-clarification-20261103.json)

**OOM 수정의 순차 레이어 분산 이후 낮은 GPU 활용률·90분 초과 생성 보고**

- 책임 근거: Codex가 82a2bcc에서 순차 레이어 분산을 기본으로 변경했고 H100 속도·사용률을 검증하지 못함
- 상태: 사용자 보고·구조 확인 / 실제 실행 경로와 H100 성능 미검증
- 관련 커밋: [82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)
- 현황판: [#1167](https://77model.pages.dev/bug-board/#item=1167)
- 사용자 보고: 1080p 16초, 90분 초과, GPU 사용률 17%로 할당 종료
- 현재 가중치 분산은 레이어를 순차 실행하며 한 요청에서 모든 GPU를 동시에 계산에 쓰지 않음
- --ref의 다른 변형 서버는 단일 작업에서 대기할 수 있음
- CLI 기본 16초는 8초+8초, 각 49회 모델 평가
- 원본 명령·로그·실행 커밋 미확인. 전체 지연이나 종료 원인을 단정하지 않음
- 1080p는 현재 CLI 직접 생성 선택지와 달라 실제 생성/후처리 경로 확인 필요
- 성능 개선 코드를 반영했다거나 H100에서 개선됐다고 표시하지 않음
- 원본 보고와 미확인 범위: [성능 보고](bug-ledger/evidence/low-utilization-report-20261103.json)

### H3-029

**임의 진척률·출력 구간/원본 프레임 혼동과 연결 끊김 후 이전 진척 유지**

- 현황판: [#1171](https://77model.pages.dev/bug-board/#item=1171)
- 확인한 문제: 프레임 작업에 고정 비율을 배정하고, 생성 구간의 진척을 평균 내 전체 완료율처럼 표시했다. 새 프로젝트·후처리·연결 끊김 상태도 명확히 구분하지 못했다.
- 수정: 검증·저장된 프레임 수/전체 수, 현재 프레임, 실제 생성 계산 수/출력 구간, 단계 경과, 관측 기반 속도·단계 한정 예상 시간을 표시한다. 중지·재시도·연결 끊김·프로세스 중단은 별도 표시한다. 조립·검증 전 전체 완료를 표시하지 않는다.
- 검증: 4프레임 실제 FFmpeg 처리·중지·저장본 재사용·오디오·FPS·원본 보존, CLI 회귀 82건, Chromium 320/390/820/1440폭 상태 전환. 초기 격리 작업트리 ASR 환경 경로 실패와 재검사 결과도 남겼다.
- 제한: H100 전체 실행과 속도 개선은 미측정. GPU 프레임 분산이나 `gen --video`의 처리 방식은 이번 수정으로 바뀌지 않았다.
- [검증 원본과 미확인 범위](bug-ledger/evidence/measured-progress-validation-20261103.json) · [공개·실제 Arcade 검증 및 배포 기록](bug-ledger/evidence/measured-progress-publication-20261103.json)

## 보존 방식

새 사실이 확인되면 사건 번호를 유지하고 날짜·커밋·원본 로그·검증 범위를 덧붙인다. 실패와 미확인 상태를 성공 기록으로 덮어쓰지 않는다. 스냅샷 해시는 구조화한 원장의 snapshotHashes에 남긴다.
