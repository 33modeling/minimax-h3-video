# Hyperframes 분석과 Video Maker 통합

2026-10-15. 원본: https://github.com/heygen-com/hyperframes

분석용 소스는 `/home/kms/dev/hyperframes`에 가져왔다. 분석한 커밋은
`8f0bcadcd32893d3ad5231f33b210c410096281f`이다. 서비스는 npm의 **hyperframes
0.8.158**과 전용 **Node 22.22.2**를 잠금 파일로 고정해 사용한다. 운영체제의
Node 버전과 기존 H3 모델 서버를 바꾸지 않는다.

## 원본 구조와 적용 방식

| 원본 구성 | 역할 | Video Maker 적용 |
| --- | --- | --- |
| core | HTML의 `data-*` 타이밍, GSAP·미디어·애니메이션을 같은 시각으로 탐색 | 원본 runtime 사용 |
| studio / studio-server | 타임라인, 레이어, 텍스트·모션 편집, 미디어, 코드, 카탈로그, 수정 기록 | 원본 Studio를 프로젝트별 서버로 실행하고 기존 웹 서버에서 연결 |
| engine | Chromium으로 특정 프레임의 화면 캡처 | 원본 Chromium 엔진 사용 |
| producer | 프레임 인코딩, 오디오 혼합, 출력·구간 보관 | 원본 CLI 렌더러 사용 |
| registry | 설치 가능한 모션 블록과 효과 | Studio의 Catalog 사용; 다운로드에는 네트워크 필요 |
| agent skills / Framey | 외부 코딩 에이전트의 제작 절차, HeyGen 연동 | 제작 엔진과 별도. 외부 계정·에이전트 인증을 대신하거나 내장 LLM으로 가장하지 않음 |

모양만 재현한 편집기가 아니다. 버전을 고정한 원본 Studio와 렌더러를
`tools/hyperframes/studio-server.mjs` 및 Python 어댑터로 연결했다. 원본 패키지는
수정하지 않았다. Apache 2.0 원문과 출처는 같은 폴더에 보관한다. 설치한 블록에
별도 자산 라이선스가 있으면 해당 원본 파일도 프로젝트에 유지된다.

## 사용

기존 영상 maker에서 **Hyperframes · 모션·타임라인 영상**을 연다.

1. 보관함에서 새 프로젝트·템플릿을 만들거나 기존 영상 편집실에서
   **Hyperframes로 모션 편집**을 누른다. 선택한 영상·이미지, 글, 길이·시작 자르기,
   원본 소리·음악·내레이션·자막을 별도 프로젝트로 복사한다.
2. 장면 화면에서 스토리라인·미디어·글자 위치·색·크기·등장 모션을 정한다.
   JSON의 scenes/clips도 가져올 수 있다. **장면 적용·저장**으로 HTML을 구성한다.
3. **타임라인·레이어**에서는 실제 Hyperframes Studio의 재생·탐색, 레이어·모션,
   미디어, 코드, 실행 취소·수정 기록을 사용한다. 별도 창에서도 같은 프로젝트가 열린다.
4. **HTML 편집**에서는 HTML·CSS·GSAP 원본을 직접 수정한다. 고급 편집 후 장면을
   다시 적용하면 장면 양식에서 HTML을 새로 구성하므로 이전 HTML을 자동 보관한다.
5. MP4·WebM·ProRes MOV·GIF, 품질, FPS, 원본 크기 또는 4K를 선택해 출력한다.
   4K는 HTML을 높은 픽셀 밀도로 다시 렌더링한다. 저해상도 원본 영상의 디테일을
   추론하는 AI 업스케일은 기존 영상 편집실의 Real-ESRGAN/Qwen 기능을 사용한다.
6. 프로젝트 HTML·미디어 ZIP, 완성본 내려받기, 이전 수정 상태 복원과 재접속을 지원한다.

기존 편집실의 와이프·슬라이드 전환, 크롭 초점, 영상 색 보정·덕킹·정규화와
이미지 카메라 움직임을 Hyperframes 형식으로 자동 변환하지는 않는다. 원본 설정은
`sourceSnapshot`에 보관하며 원래 프로젝트는 유지한다. 해당 최종 편집이 필요하면
기존 편집실에서 출력한 완성본을 가져오거나 Studio에서 해당 효과를 구성한다.

## 보관과 중지·복원

`--output-dir`의 루트를 그대로 사용한다. 기본 위치:

```
outputs/_hyperframes/hf-<id>/
  project.json                 # 장면·설정·작업 상태·원본 설정 사본
  composition/index.html       # 실제 Hyperframes 문서
  composition/assets/          # 복사한 원본·업로드 미디어·GSAP
  composition/renders/         # Studio 직접 출력과 MP4 구간 캐시
  exports/                     # maker 출력·프로젝트 ZIP
  history/                     # 저장·출력·복원 전 자동 보관
  studio-history/              # 원본 Studio의 수정 기록
  render-<id>.log / studio.log
```

MP4는 `HF_SEGMENTED_CAPTURE=true`, 120프레임 구간, `--resume --keep-segments`로
완료 구간을 보관한다. 중지 후 같은 입력·설정이면 엔진이 검증한 구간을 재사용하고,
입력이나 설정이 달라지면 새 캐시를 만든다. 미완료 maker 출력은 보관함에 노출하지
않는다. 새 출력과 복원은 이전 완성 파일을 지우지 않는다. 서버 재시작 시 남은 작업은
자동 실행하지 않고 중지 상태로 복원한다.

0.8.158의 구간 캡처는 MOV의 ProRes를 MP4 구간 컨테이너에 넣으려 해 실패한다.
어댑터는 **MP4에서만 구간 재사용**을 켠다. WebM·MOV·GIF는 원본 일반 렌더 경로를
사용하며 중지 후에는 전체를 다시 출력한다. Studio 내부 Export도 일반 경로를 쓴다.

## 서버 연결

기존 8790 Python 서버가 API·파일·편집기를 제공한다. Studio 자식 서버는
`127.0.0.1` 임의 포트에만 열고 `/hyperframes/<id>/proxy/`로 연결한다.
전역 선택 쿠키 없이 프로젝트를 URL에 명시해 여러 창의 미디어와 저장을 분리한다.
조건부 쓰기의 If-Match와 Hyperframes 수정 토큰, Range, SSE를 전달한다.
maker 출력 중에는 Studio의 변경 요청을 막아 렌더 대상이 바뀌지 않게 한다.
렌더는 CPU 인코딩, 소프트웨어 Chromium, 1 worker를 사용한다.

설치: `npm run install:hyperframes`. FFmpeg·ffprobe, Chromium, Noto Sans CJK KR가
필요하다. 기존 Chromium을 찾으면 재사용하며 `HYPERFRAMES_BROWSER_PATH`로 지정할
수 있다. CJK 글꼴은 설치된 정확한 이름을 `@font-face src:local(...)`로 선언해 외부
Google Fonts 다운로드 없이 렌더한다. GPU 생성 서버는 시작하지 않는다.

## 검증

- `npm run test:hyperframes`: 실제 Studio의 프로젝트 분리·조건부 저장 충돌·파일 범위,
  원본 영상·오디오 가져오기, 저장·ZIP·복원·재접속, MP4 구간 재사용, MP4/WebM/MOV/GIF 출력.
- `npm run test:motion-ui`: 실제 Studio·미리보기, 기존 장면 가져오기, 장면·HTML 저장,
  업로드·ZIP, 실제 MP4, 중복 클릭, 재접속과 1440/820/390/320px 레이아웃.
- 원본 `hyperframes lint` 및 `hyperframes check`: 생성 문서의 구조·런타임·레이아웃·대비 검사.
  기본 단일 HTML 템플릿은 장면을 sub-composition 파일로 분리하라는 권고 경고가 있으며
  오류는 없어야 한다.

`H3_MOTION_UI`로 공개 또는 로컬 Arcade URL을 지정해 같은 브라우저 검사를 실행한다.
테스트의 생성 서버만 CPU 모의 서버이고 Hyperframes·Chromium·FFmpeg 출력은 실제 도구다.
