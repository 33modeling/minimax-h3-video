#!/usr/bin/env bash
# 테스트용 짧은 영상: 가로 기본 영상 1개 + 소스 3개(소리 포함) + 배경음 + 첫 프레임 이미지.
# 사용: tests/fixtures/make_media.sh [출력폴더=.tmp/media]
set -euo pipefail
OUT=${1:-.tmp/media}
mkdir -p "$OUT"
ff() { ffmpeg -y -hide_banner -loglevel error "$@"; }
[[ -f "$OUT/base.mp4" ]] || ff -f lavfi -i "testsrc2=s=1280x720:r=30:d=8" -f lavfi -i "sine=f=440:r=48000:d=8" \
  -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$OUT/base.mp4"
[[ -f "$OUT/src1.mp4" ]] || ff -f lavfi -i "color=c=red:s=1280x720:r=30:d=3,drawbox=x=540:y=260:w=200:h=200:color=white:t=fill" \
  -f lavfi -i "sine=f=660:r=48000:d=3" -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$OUT/src1.mp4"
[[ -f "$OUT/src2.mp4" ]] || ff -f lavfi -i "color=c=green:s=720x1280:r=30:d=2.5,drawbox=x=260:y=540:w=200:h=200:color=white:t=fill" \
  -f lavfi -i "sine=f=880:r=48000:d=2.5" -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$OUT/src2.mp4"
[[ -f "$OUT/src3.mp4" ]] || ff -f lavfi -i "color=c=blue:s=640x480:r=30:d=3,drawbox=x=220:y=140:w=200:h=200:color=yellow:t=fill" \
  -f lavfi -i "sine=f=330:r=48000:d=3" -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest "$OUT/src3.mp4"
[[ -f "$OUT/bgm.m4a" ]] || ff -f lavfi -i "sine=f=220:r=48000:d=5" -c:a aac "$OUT/bgm.m4a"
[[ -f "$OUT/first.png" ]] || ff -f lavfi -i "color=c=purple:s=720x1280:d=1" -frames:v 1 "$OUT/first.png"
echo "$OUT"
