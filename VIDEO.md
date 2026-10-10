# 영상 만들기 (사용법만)

서버 띄우기·끄기는 [USAGE.md](USAGE.md) 빠른 시작. 여기는 **서버가 떠 있을 때 영상을 만드는 법**만 적는다.

```bash
cd /user-volume/minimax-h3-video
source scripts/cluster_env.sh       # 새 창마다 한 번
bash scripts/status.sh              # fl2va 가 "준비됨 ✓" 이면 시작
```

## 1. 만들기

| 하고 싶은 것 | 명령 | 필요한 서버 |
|---|---|---|
| 글 → 영상 | `h3video gen "비 오는 서울 밤거리, 네온이 젖은 길에 번진다" -s 8` | fl2va |
| 이 그림에서 시작 | `h3video gen "..." --first a.png -s 8` | fl2va |
| 이 그림으로 끝 | `h3video gen "..." --last b.png -s 8` | fl2va |
| 처음·끝 그림 둘 다 | `h3video gen "..." --first a.png --last b.png -s 8` | fl2va |
| 사진·영상·소리를 참고 | `h3video ref "<Subject 1>이 손을 흔든다" --image me.png -s 6` | ref2va (`up.sh --ref`) |
| 여러 개 차례로 | `h3video batch prompts.txt -o ~/videos/` | 내용에 따라 |
| 프롬프트만 미리 보기 | `h3video ir "..." -s 8` (생성 안 함) | 해당 서버 |

- **fl2va 와 ref2va**: fl2va 는 준 그림이 영상의 실제 첫·끝 프레임이 된다. ref2va 는 사진(최대 9)·영상(3)·소리(3)를 *참고*해서 얼굴·옷·화풍·움직임·목소리를 따라 한다(그림이 그대로 프레임이 되지는 않는다). 프롬프트에서 참고 자료는 넣은 순서대로 `<Subject 1>`·`<Picture 1>`·`<Video 1>`·`<Audio 1>` 로 가리킨다.
- 끝나면 결과 mp4 경로가 나온다. 진행률은 화면에, 서버 원본 로그는 `up.sh` 화면에 나온다.
- 입력 파일 경로는 지금 폴더 기준. 서버가 읽는 곳(inbox)으로 알아서 복사된다.

## 2. 프롬프트는 서버가 다듬는다 (Diffusers 엔진)

H3 는 영어로 샷·카메라·인물·동작·소리를 아주 자세히 풀어 쓴 **공식 형식(Context-IR)** 으로 학습됐다. 짧은 한국어 한 줄을 그대로 넣으면 잘 안 따라간다.
그래서 서버가 생성 전에 **MiniMax 공식 작성 가이드대로 다시 쓴다**(GPU 0 에 이미 있는 Qwen3-VL-32B 로, 첫 프레임·참고 그림도 보고 쓴다). 요청마다 1분 안팎 더 걸린다.

```bash
h3video ir "눈 속을 달리는 붉은 여우, 마지막에 카메라를 본다" -s 8 --first fox.png > fox_ir.txt   # 다듬은 결과만 보기
# fox_ir.txt 를 고친 뒤 그대로 쓰기 (다듬지 않음)
h3video gen -f fox_ir.txt --raw --first fox.png -s 8
```

- 실제로 쓴 프롬프트는 결과 폴더의 `scene01.prompt.txt` 와 서버 로그(`다듬은 프롬프트`)에 남는다.
- 처음부터 공식 형식(`integrated_multimodal_description:` 로 시작)으로 쓰면 다듬지 않고 그대로 쓴다. `--raw` 는 짧은 글이어도 그대로 보낸다.
- 다듬은 결과가 형식에 안 맞으면 한 번 더 시도하고, 그래도 안 되면 원래 글로 만든다(서버 로그에 나온다).
- 첫·끝 그림이 있으면 공식 정렬 문장(`For the target video, at 0.00 seconds …` / `How the reference pictures align …`)을 실제 영상 길이로 서버가 맨 앞에 붙인다.

### 잘 따라오게 쓰는 법

짧게 써도 다듬어 주지만, 원하는 것이 빠지면 모델이 채워 넣는다. 아래를 넣을수록 그대로 나온다.

- **누가·어디서·무엇을**: 인물 생김새(나이·옷·머리), 장소·시간대·조명, 동작 순서.
- **카메라**: 고정, 천천히 다가감(push in), 따라감(tracking), 좌우로 돌림(pan), 흔들림 등.
- **장면 전환**: "4초쯤 얼굴 클로즈업으로 바뀐다"처럼 시점까지.
- **소리**: 환경음·효과음·배경음악(장르·빠르기). 영상과 소리를 함께 만든다.
- **대사**: 말할 문장을 따옴표로 그대로 적는다(한국어 등 11개 언어). 다듬을 때 원어로 둔다. 직접 공식 형식으로 쓸 때는 `The young woman (S1) says: <d>[Korean] 다음 역에서 내려요.</d>` 처럼 쓴다.
- 금지어(`-n`)는 이 모델에 없다. "안 나왔으면 하는 것"은 원하는 모습을 반대로 구체적으로 쓴다.

## 3. 옵션 (gen · ref · batch · ir 공통)

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-s 초` | 8 | 길이. 한 번에 5~15초(4초는 5초로 만든다). 16초 이상은 장면을 이어 붙인다 |
| `-r 화면비` | 16:9 | 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, auto(첫 그림 비율) |
| `--seed 숫자` | 0 | 같은 프롬프트·시드면 같은 결과. `random` 은 매번 다르게 |
| `--steps 숫자` | 50 | 줄이면 빠르고 거칠다 |
| `-t 제목` | 프롬프트 앞부분 | 결과 파일 이름 |
| `-o 경로` | 없음 | 결과를 여기로도 복사 (`/` 로 끝나면 폴더) |
| `--raw` | 끔 | 다듬지 않고 쓴 그대로 보낸다 |
| `--dry-run` | 끔 | 보내지 않고 요청 내용만 출력 |

- 실제 길이는 영상 VAE 단위(17n+5 프레임, 24fps)로 맞춘다: 5초 → 5.17초, 6초 → 6.58초, 8초 → 8.00초, 15초 → 14.38초.
- 해상도는 짧은 변 768(16:9 면 1344×768).

## 4. 결과

```
/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/
  <제목>.mp4              최종본 (영상 + 32kHz 스테레오 소리)
  scene01.mp4             장면별
  scene01.prompt.txt      서버가 실제로 쓴 프롬프트 (다듬은 것)
  scene01.request.json    보낸 요청
```

```bash
h3video jobs                       # 지난 작업
h3video show last                  # 마지막 작업 상세
h3video fetch <video_id> -o a.mp4  # 서버에 남은 완성본 받기 (ref2va 는 --ref)
rsync -avz user@host:/group-volume/minsoo3.kim/minimax-h3-video/outputs/<작업id>/ ./out/   # PC 로
```

## 5. 막히면

| 보이는 것 | 할 일 |
|---|---|
| `서버가 응답하지 않는다` | `bash scripts/status.sh`. 꺼져 있으면 `bash scripts/up.sh` |
| 프롬프트를 안 따른다 | `h3video ir` 로 다듬은 결과를 보고, 빠진 내용을 원래 글에 더 적거나 결과를 고쳐 `--raw -f` 로 |
| `생성 실패 … out of memory` | 그 GPU 를 다른 작업이 쓰는지 `nvidia-smi`. `up.sh` 를 다시 띄우면 빈 GPU 만 쓴다 |
| `이 서버(fl2va)는 … 만 받는다` | 참고 자료(`ref`)는 ref2va 서버가 필요하다: `bash scripts/up.sh --ref` |
| 레퍼런스 개수 오류 | 사진 9·영상 3·소리 3, 합계 12 까지. 소리만 넣을 수는 없다 |
