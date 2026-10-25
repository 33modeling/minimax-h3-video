# 공식 도구 조사에 따른 창작 기능 확장 · 2026-10-25

## video-maker

- 기존: 개별 장면 편집만 가능, 선택 장면의 복수 항목 일괄 편집 없음
- 추가: 장면 편집·보정 · 선택 장면 전환·색감 일괄 편집 · 검토표·영상
- 공식 기능 참고: https://www.adobe.com/learn/premiere-pro/web/combine-and-trim-travel-clips
- 검증: 변경 비교 4건·기존 settings API 1회·선택 장면만 변경·원본/버전/프롬프트/타이밍 보존·재접속. API fixture.

## shorts

- 기존: 기본 자막 스타일이 코드에 고정됨
- 추가: 영상·자막 합성 · 자막 크기·색·위치·프리셋 · 프레임 PNG
- 공식 기능 참고: https://www.capcut.com/help/how-to-import-subtitles
- 검증: JS/Python 레이아웃 수치 대조·출력 PNG의 빨간 글자 위치·실제 MP4 합성/ffprobe·JSON 재접속.

통합 브라우저 검사는 `33modeling-site/tests/creation-research/`에 있습니다. 서버 리스너를 금지하고 Playwright 경로 가로채기 및 실제 요청 처리기를 사용합니다. 1440·768·390·320px를 검사합니다. 모델 API 고정 응답 검사는 실제 모델의 생성 품질 측정과 구분합니다. Pages와 로컬 프로필을 각각 빌드·검사합니다.
