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

- **받아쓰기 자막 불러오기** — 받아쓰기 작업실(asr-studio)에서 내보낸 SRT·VTT·JSON을 '자막 불러오기'로 고르거나 놓으면 구간 시각 그대로 `captions` 에 들어간다(이전 자막은 '수정 전 JSON 복원'으로 되돌림). 받아쓰기 작업실의 **숏폼 자막으로 보내기**는 허브 안에서 `localStorage['shorts-captions-handoff']` 로 넘기고 `/shorts/#from=asr` 를 연다(지금 작업은 작업 목록에 보관하고 새 작업으로 시작). 영상보다 늦게 시작하는 줄은 안내 후 빠진다.
- **영상 만들기에서 받기** — 영상 만들기(video-maker) 작업 카드의 **숏폼으로 보내기**는 다 만든 영상을 같은 출처 IndexedDB(`creative-handoff`, key `shorts-video-input`)에 두고 `/shorts/#from=video` 를 연다. 받은 영상은 '내 영상' 칸에 들어간다(작업 JSON 이 있으면 지금 작업은 작업 목록에 보관하고 새 작업, 파일만 있으면 그 옆에 더함). 30분 넘은 값·영상이 아닌 값은 안내만 한다. 허브 밖(H3 서버가 직접 내준 화면)에서는 영상을 내려받는다.
- **로컬 서버** — `vite dev`·`vite preview` 는 허브가 내주는 `/creative-ai/client.mjs`(사이트 연결 없음 대역)와 `/fonts/…`(옆 `../../33modeling-site` 체크아웃, `SHORTS_HUB_DIR`)를 같은 주소로 내준다. 허브 밖에서 띄워도 404 콘솔 오류가 나지 않는다.
- **표지 만들기** — 미리보기에서 고른 장면에 제목을 얹어 숏폼 1080×1920·유튜브 1280×720 PNG로 저장한다(글자색·테두리·위치·크기는 자막 모양 설정).

## 일시중지 · 저장한 영상 작업

**일시중지 · 저장**은 현재 AI 장면을 완료하고 저장한 뒤 멈춥니다. 원본 파일·완료한 장면·완성 출력은 IndexedDB에 보관하며 새로고침 후에도 복구합니다. JSON·자막·배치를 바꾼 뒤 **저장본 이어 만들기**를 누르면 요청 내용이 같은 장면을 재사용합니다. 수정한 프롬프트의 장면만 다시 생성하고 최종 합성은 변경한 설정으로 다시 실행합니다. 작업 목록·새 작업·수정 전 JSON 복원을 제공합니다. 브라우저 저장 공간을 초과하면 화면에서 안내하며 완료한 영상은 내려받을 수 있습니다.
