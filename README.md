# shortform-studio

프롬프트 JSON(작업 명세)과 소스 영상(선택) 두 파일로 9:16 숏폼을 만든다.

- **CLI** `shorts` — 파이썬 표준 라이브러리 + ffmpeg. 사용자가 띄운 영상 생성 서버(SGLang `/v1/videos`, vLLM-Omni, minimax-h3-video 웹 서버)에 명령을 보내고, 받은 영상을 템플릿으로 합성한다.
- **웹** — 33modeling 허브의 "숏폼 제작". 브라우저 안에서 합성(WebCodecs)한다.
- 작업 명세 스키마: `schema/job.schema.json` (웹과 CLI 공용)

자세한 사용법은 [USAGE.md](USAGE.md).
