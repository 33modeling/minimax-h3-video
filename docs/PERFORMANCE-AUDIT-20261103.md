# H3 지연 원인 조사 · 2026-11-03

현재 코드에서 GPU 동시 계산을 제한하는 구조와 실제 결함 두 개를 확인했다. 사용자 H100 노드에는 연결하지 못했고 실행 명령·단계 로그도 없으므로, 90분 중 각 단계가 차지한 시간과 17% 사용률의 분모는 아직 미확인이다. 아래 결과는 코드 감사와 모의 API 재현이며 H100 벤치마크가 아니다.

## 새 영상 생성 경로

[82a2bcc](https://github.com/33modeling/minimax-h3-video/commit/82a2bccec786adedb0da96d49ce830546dba7836)에서 OOM 대응으로 기본 방식을 `sharded`로 변경했다. `dserver.py`는 텍스트 인코더·VAE를 한 GPU에 두고 영상 모델의 **가중치 한 벌**을 나머지 GPU의 **완전한 레이어 단위**로 나눈다. `placement.py`의 `device_map`과 설치된 Diffusers 0.41.0의 `for block in self.transformer_blocks`를 대조했다.

이 방식은 레이어를 차례대로 계산한다. 하나의 레이어 계산을 여러 GPU에 동시에 나누는 tensor/context parallel과 다르다. 가중치가 여러 장에 올라가 있어도 한 요청의 연산이 그 장 수만큼 빨라지지 않는다. 마지막 블록 이후 첫 denoiser GPU의 출력 projection으로 돌아가는 전송도 필요하다. [Accelerate 공식 문서의 제한 사항](https://huggingface.co/docs/accelerate/concept_guides/big_model_inference#limits-and-further-development)과 일치한다.

8장 노드에서 `up.sh --ref`는 두 종류 서버에 4+4를 배정한다. Ref2VA 한 요청은 그중 Ref2VA 묶음만 사용한다. 다른 FL2VA 묶음은 해당 요청의 연산을 돕지 않는다. 이 때문에 **8장 할당을 8장 동시 연산으로 설명할 수 없다.** 사용자 보고의 낮은 평균 사용률과 양립하지만 정확한 17%·90분을 재현한 것은 아니다.

## 원본 영상의 프레임 보정 경로

이 경로는 H3 생성과 별개다. `VideoStudio.upscale()`의 프레임 루프는 Qwen 편집 → 확대 → 검증·저장을 마친 뒤 다음 프레임으로 간다. 프레임마다 Node 프로세스를 새로 만들고, provider의 `turn=0`도 초기화한다. finishing executor도 작업 한 개만 처리하며 확대 GPU 기본값은 0이다.

실제 `retouch-frame.mjs`를 자식 프로세스 네 번으로 실행하되 이미지 API만 모의 응답으로 대체했다. 서버 주소 A/B/C/D를 설정해도 **A/A/A/A**로 요청했다. 동일한 provider 인스턴스를 보존한 대조군은 **A/B/C/D**를 선택했다. 소켓·서버·GPU 추론은 사용하지 않았다. 여러 서버 설정이 있어도 현재 영상 프레임 처리에서 동시 분산을 제공하지 못하는 결함이다. [현황판 #1185](https://77model.pages.dev/bug-board/#item=1185)

일반 Qwen 편집 기본은 프레임당 40스텝이며 Turbo 경로는 8스텝이다. **24fps일 경우에만** 16초 = 384프레임이고 일반 편집은 15,360 이미지 편집 스텝에 해당한다. 이것은 예시 계산이다. 사용자 입력 FPS·선택한 보정 엔진·스텝 설정은 측정하지 못했다.

## 속도 옵션이 작동하지 않음

실제 `serve.sh`를 fake Python·포트 검사와 실행했다. `--mode speed`와 `--mode memory`의 Diffusers 실행 인자와 mode 관련 환경이 동일했다. MODE는 SGLang 실행에만 전달된다. Diffusers에서 이 옵션을 바꿔 속도를 제어한다고 볼 수 없다. [현황판 #1184](https://77model.pages.dev/bug-board/#item=1184)

## 다음 조치와 미확인 범위

- 생성: 현재 레이어 분산을 속도용 병렬화로 취급하지 말고, 메모리 제한을 만족하는 실제 tensor/sequence/context 병렬 방식을 H100에서 검증해야 한다. 이전 CP 기본값을 그대로 복원하면 과거 OOM이 재발할 수 있어 이번 조사에서는 바꾸지 않았다.
- 프레임 보정: endpoint별 지속 worker와 제한된 동시 프레임 처리가 필요하다. 완료 프레임·원본·FPS·오디오·중지/재개를 보존해야 한다. 이번에는 원인 재현만 했고 해당 구조 변경은 하지 않았다.
- 옵션: Diffusers에서 구현한 동작만 명시하거나 지원하지 않는 speed/memory 선택을 분명히 거부해야 한다. 가짜 속도 향상을 표시해서는 안 된다.
- 사용자 노드의 단계 로그로 입력 읽기·프롬프트 다듬기·조건 인코딩·생성 계산·디코딩·저장을 대조해야 실제 지연의 비중을 확정할 수 있다. 프롬프트 재작성·CPU offload·어텐션 백엔드·메모리 압박은 아직 측정된 원인이 아니다.

[재현 결과·소스 해시·측정 한계](bug-ledger/evidence/performance-cause-20261103.json). H100 전체 지연 사건 [#1167](https://77model.pages.dev/bug-board/#item=1167)은 미해결로 유지한다.
