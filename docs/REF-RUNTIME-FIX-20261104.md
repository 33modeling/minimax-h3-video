# Ref2VA 추가 개선 반영 · 2026-11-04

앞선 [감사](ADDITIONAL-REF-AUDIT-20261104.md)의 여섯 항목을 실행 코드에 반영했다. 실제 H100 노드의 전체 모델 OOM 해소·속도는 측정하지 못했다. 이번 검사는 CPU, RTX 3050의 작은 모델, 모의 오류·프로세스·전송을 구분한다.

| 항목 | 반영 내용 | 확인한 범위 |
|---|---|---|
| 참고 프레임 중복 전송 | 인코딩을 끝낸 상태에서 원본 reference/keyframe은 분기 플래그, normalized reference는 kind/has_audio로 변환 | 같은 CPU 합성 입력에서 2,367,201 → 7,585바이트. 실제 작은 H3 denoiser의 t2va/양끝 키프레임/이미지·무음 영상·유음 영상·오디오 혼합 참고 출력이 압축 전후 정확히 같음 |
| worker 오류 보존 | 요청 ID·rank·단계·프로세스별 할당/예약 최고치를 원자 JSON에 기록하고 부모가 수집 | 실제 예외 처리 문장을 실행한 모의 OOM과 연결 없는 실패 회수. 이전 요청·미완성 파일 무시. 실제 rank의 강제 SIGKILL 기록까지 보장하지 않음 |
| 단계별 복구 | 텍스트 OOM은 블록 오프로딩, GPU 입력/생성 OOM은 더 작은 geometry, 일반 worker 종료는 같은 크기로 한 번, host OOM·timeout은 반복 금지 | 복구 이력·실패 이력 보존, 최소 크기에서 무효 재시도 차단. 실패 worker만 재적재하며 조건 모델은 유지 |
| 준비 재사용 | 요청 안에서 원본 입력과 확정 프롬프트 재사용. 캐시 메모리 예산 초과 영상은 요청 임시 매핑 파일 사용 | 실제 wrapper의 decode/rewrite 각 1회, 크기 재시도 간 픽셀 동일, 종료 시 캐시 정리. 최초 영상 읽기 자체를 streaming decode로 바꾼 것은 아님 |
| 조건 GPU 메모리 | Qwen 언어/시각 블록을 하나씩 올리는 group offload. memory 모드에서 즉시 적용, speed의 텍스트 OOM에서 자동 적용 | 작은 실제 Qwen의 텍스트·이미지 입력·generate, CUDA 출력 일치. 블록 내부 모의 OOM 후 실제 GPU 가중치를 내려 다음 요청 출력 보존. 32B/H100 전체 활성값은 미측정 |
| 무진척 제한 | worker 준비, 실제 step 무진척, denoising 전체 제한. PROG 0 반복으로 제한 연장 불가 | 살아 있으나 응답 없는 모의 worker와 준비 대기 종료. 해당 엔진이 만든 worker 묶음만 정리하고 API는 유지 |

`/health`에 조건 오프로딩 방식과 진단 디렉터리를 표시한다. 작업 JSON에는 `memoryHistory`, `failureHistory`, `recoveryHistory`가 남는다. 조건 GPU를 보유한 부모와 생성 GPU를 보유한 worker의 allocator 측정은 서로 바꾸어 보고하지 않는다. 이미 상주한 컴포넌트 호출도 기록해 이전 단계의 모델 이름을 현재 OOM에 붙이지 않도록 했다.

`diagnose.sh`는 fl2va/ref2va 각각의 모델 파일·serve 로그·최신 작업을 읽는다. 시작 명령은 그대로이며 [README](../README.md)의 Ref2VA 재시도·메모리 진단 절에 복구 규칙과 제한 시간 설정을 적었다. 블록 오프로딩에서 Transformers가 model.device=CPU와 CUDA 입력의 generate 경고를 표시할 수 있다. 작은 실제 CUDA 검사에서는 이 상태의 forward/generate 출력과 장치 이동을 대조했으며 경고를 숨기지 않았다.

검사 중 복구 단계 문구가 기존 진척 API 검사와 충돌한 회귀를 발견해 이전 축소 문구를 유지했다. 격리 작업트리의 ASR 가상환경 연결 누락, Server.__new__ 기반 fixture의 ready 상태 누락, 초기 가짜 시계의 값 부족도 따로 보존한다. ASR 연결은 검사 환경에만 만들고 커밋 전에 제거했다. 실제 기능 실패와 검사 환경/fixture 문제를 구분한다.

실행 서비스나 포트를 새로 열지 않고 in-memory HTTP transport와 fake process group으로 검사했다. 사용자 노드 적용에는 새 코드로 기존 `up.sh` 프로세스를 다시 실행해야 한다. 이 작업에서 그 노드의 설치·실행 상태를 바꿨다고 보고하지 않는다.

[검증 원본·실패 기록·소스 해시](bug-ledger/evidence/ref-runtime-validation-20261104.json).
