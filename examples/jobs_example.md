# 예시 명령

```bash
# 사양·장면 분할 확인
h3video spec
h3video plan 45            # 45초 → [9, 9, 9, 9, 9]

# 8초 텍스트→영상
h3video gen "새벽 안개 낀 해운대, 드론이 바다 위를 낮게 날아 해변으로 접근. 파도와 갈매기 소리, 잔잔한 피아노." --seconds 8 --ratio 16:9

# Context-IR 3단 형식으로 감싸서(권장) 12초
h3video gen "..." --ir --soundscape "파도, 갈매기, 바람" --music "잔잔한 피아노 솔로" --seconds 12

# 첫 프레임 이미지로 40초 (10초 장면 4개 체인, ffmpeg 필요)
h3video gen "..." --first ./keyframe.png --seconds 40 --scene-seconds 10

# 레퍼런스(ref2va 서버 30011 필요)
h3video ref "<Subject 1>이 카메라를 보며 한국어로 인사한다" --image me.png --audio myvoice.mp3 --seconds 6

# 여러 개 차례로 (examples/batch_example.txt 형식)
h3video batch examples/batch_example.txt -o out/

# 지난 작업
h3video jobs
h3video show last

# 웹 UI
h3video web --port 8790
```
