# 제3자 소프트웨어 고지

숏폼 제작 웹 화면(빌드 결과 `dist/`, 허브 경로 `/shorts/`)에는 아래 오픈소스가 함께 묶여 배포됩니다.
CLI(`shorts/`)는 파이썬 표준 라이브러리만 쓰고, 영상 합성에는 사용자가 설치한 `ffmpeg` 실행 파일을 부릅니다(배포에 포함하지 않음).

| 구성 요소 | 버전 | 라이선스 | 쓰는 곳 | 소스 |
|---|---|---|---|---|
| mediabunny | 1.61.3 | MPL-2.0 | 영상 읽기(디먹싱)·디코딩·MP4/WebM 쓰기(WebCodecs) | https://github.com/Vanilagy/mediabunny |
| @mediabunny/aac-encoder | 1.61.3 | MPL-2.0 (패키지) + 안에 든 FFmpeg libavcodec 은 LGPL-2.1 이상 | 브라우저에 AAC 인코더가 없을 때(리눅스 크롬 등) AAC 소리 인코딩 | https://github.com/Vanilagy/mediabunny/tree/main/packages/aac-encoder |
| FFmpeg (libavcodec AAC 인코더, WASM 빌드) | aac-encoder 에 포함 | LGPL-2.1-or-later | 위 aac-encoder 내부 | https://ffmpeg.org/ · https://github.com/FFmpeg/FFmpeg |

## 고지 사항

- **MPL-2.0 (mediabunny, @mediabunny/aac-encoder)**: 파일 단위 약한 카피레프트입니다. 이 저장소는 두 패키지의 파일을 고치지 않고
  npm 패키지 그대로 번들합니다. 원본 소스와 라이선스 전문은 위 저장소와 `node_modules/mediabunny/LICENSE`,
  `node_modules/@mediabunny/aac-encoder/LICENSE` 에 있습니다(https://mozilla.org/MPL/2.0/).
- **LGPL-2.1+ (FFmpeg libavcodec)**: `@mediabunny/aac-encoder` 는 FFmpeg 의 AAC 인코더를 WebAssembly 로 빌드해 담고 있습니다.
  이 부분은 LGPL 이며, 웹 화면은 그 모듈을 따로 떨어진 파일(`assets/mediabunny-aac-encoder-*.js`)로 두고
  브라우저에 AAC 인코더가 없을 때만 동적으로 불러옵니다. 사용자는 이 파일을 같은 인터페이스의 다른 빌드로 바꿔 끼울 수 있습니다.
  FFmpeg 소스와 빌드 방법은 aac-encoder 의 README("Building") 와 https://ffmpeg.org/download.html 에 있습니다.
- 다른 런타임 의존성은 없습니다. 개발용 도구(vite, playwright-core)는 배포물에 들어가지 않습니다.
