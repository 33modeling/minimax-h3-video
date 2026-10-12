# 숏폼 제작 (shortform/)

> 2026-10-10: 예전 `shortform-studio` 레포를 **minimax-h3-video 레포의 `shortform/`** 으로 합쳤다. 레포 루트에서 `pip install -e .` 하면 `shorts` 와 `h3video shorts` 가 같이 생기고, 클러스터 서버는 루트의 `bash scripts/up.sh` 로 띄운다.

프롬프트 JSON(작업 명세)과 소스 영상(선택) 두 파일로 9:16 숏폼을 만든다.

- **CLI** `shorts` — 파이썬 표준 라이브러리 + ffmpeg. 사용자가 띄운 영상 생성 서버(SGLang `/v1/videos`, vLLM-Omni, minimax-h3-video 웹 서버)에 명령을 보내고, 받은 영상을 템플릿으로 합성한다.
- **웹** — 33modeling 허브의 "숏폼 제작". 브라우저 안에서 합성(WebCodecs)한다.
- 작업 명세 스키마: `schema/job.schema.json` (웹과 CLI 공용)

```bash
scripts/setup.sh                  # 레포 안 .venv/·.tools/ 에만 설치 (기존 환경은 그대로)
source scripts/env.sh             # 이 셸에서만 켜기 (끄기: shorts-env-off)
shorts doctor && shorts run prompt.json [source.mp4]
```

자세한 사용법은 [USAGE.md](USAGE.md).

## 일시중지 · 저장한 영상 작업

**일시중지 · 저장**은 현재 AI 장면을 완료하고 저장한 뒤 멈춥니다. 원본 파일·완료한 장면·완성 출력은 IndexedDB에 보관하며 새로고침 후에도 복구합니다. JSON·자막·배치를 바꾼 뒤 **저장본 이어 만들기**를 누르면 요청 내용이 같은 장면을 재사용합니다. 수정한 프롬프트의 장면만 다시 생성하고 최종 합성은 변경한 설정으로 다시 실행합니다. 작업 목록·새 작업·수정 전 JSON 복원을 제공합니다. 브라우저 저장 공간을 초과하면 화면에서 안내하며 완료한 영상은 내려받을 수 있습니다.
