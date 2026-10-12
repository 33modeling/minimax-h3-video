"""Finish browser-playable MP4 files without publishing partial/corrupt results."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fractions import Fraction
from .client import H3Error


def probe(path: Path) -> dict:
    tool = shutil.which('ffprobe')
    if not tool:
        raise H3Error('영상 합치기 검사에 ffprobe가 필요합니다. ffmpeg와 함께 설치해 주세요.')
    try:
        result = subprocess.run([tool, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        duration = float(video.get('duration') or data['format']['duration'])
        if not math.isfinite(duration) or duration <= 0 or video.get('width', 0) <= 0 or video.get('height', 0) <= 0:
            raise ValueError('empty video')
        audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
        return {'video': video, 'audio': audio, 'duration': duration}
    except (subprocess.CalledProcessError, StopIteration, ValueError, KeyError) as e:
        raise H3Error(f'영상 파일을 읽지 못했습니다: {path.name}') from e


def _signature(info: dict) -> tuple:
    v, a = info['video'], info['audio'] or {}
    return tuple(v.get(k) for k in ('codec_name', 'profile', 'width', 'height', 'pix_fmt', 'r_frame_rate', 'time_base', 'sample_aspect_ratio')) + \
           tuple(a.get(k) for k in ('codec_name', 'sample_rate', 'channels', 'channel_layout', 'time_base'))


def _run(args: list[str]):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise H3Error('영상을 합치지 못했습니다: ' + result.stderr.strip()[-1800:])


def join_mp4(parts: list[Path], out: Path, ffmpeg: str) -> Path:
    """Copy compatible H.264/AAC, otherwise fit all scenes to the first scene without cropping.

    Missing audio gets silence. All scenes retain their duration; mixed orientation,
    codecs and audio formats get normalized before concatenation. Final rename is atomic.
    """
    parts, out = [Path(p).resolve() for p in parts], Path(out)
    if not parts:
        raise H3Error('합칠 영상이 없습니다.')
    for p in parts:
        if not p.is_file() or not p.stat().st_size:
            raise H3Error(f'영상 파일이 없거나 비었습니다: {p.name}')
        if '\n' in str(p) or '\r' in str(p):
            raise H3Error('영상 파일 경로에는 줄바꿈을 사용할 수 없습니다.')
    infos = [probe(p) for p in parts]
    first = infos[0]
    compatible = all(_signature(i) == _signature(first) for i in infos) and first['video']['codec_name'] == 'h264' and \
                 (first['audio'] is None or first['audio']['codec_name'] == 'aac')
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + out.stem + '-', suffix='.mp4', dir=out.parent)
    os.close(fd)
    temp = Path(temporary)
    concat_list = temp.with_suffix('.concat.txt')
    try:
        if compatible:
            # ffconcat has its own quoting rules; no shell is used.
            escaped = [str(p).replace("'", "'\\''") for p in parts]
            concat_list.write_text('ffconcat version 1.0\n' + ''.join(f"file '{p}'\n" for p in escaped), encoding='utf-8')
            _run([ffmpeg, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(concat_list),
                  '-map', '0:v:0', '-map', '0:a:0?', '-c', 'copy', '-movflags', '+faststart', str(temp)])
        else:
            width = (int(first['video']['width']) + 1) // 2 * 2
            height = (int(first['video']['height']) + 1) // 2 * 2
            rate = Fraction(first['video'].get('avg_frame_rate') or '24/1')
            if rate <= 0 or rate > 120:
                rate = Fraction(24)
            fps = f'{rate.numerator}/{rate.denominator}'
            args = [ffmpeg, '-y', '-v', 'error', '-filter_complex_threads', '1']
            for p in parts:
                args += ['-i', str(p)]
            audio = any(i['audio'] for i in infos)
            filters, streams = [], []
            for i, info in enumerate(infos):
                duration = info['duration']
                filters.append(f'[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,'
                               f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},'
                               f'format=yuv420p,trim=duration={duration},setpts=PTS-STARTPTS[v{i}]')
                streams.append(f'[v{i}]')
                if audio:
                    if info['audio']:
                        filters.append(f'[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                                       f'apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]')
                    else:
                        filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]')
                    streams.append(f'[a{i}]')
            filters.append(''.join(streams) + f'concat=n={len(parts)}:v=1:a={int(audio)}[v]' + ('[a]' if audio else ''))
            args += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p']
            if audio:
                args += ['-map', '[a]', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
            _run(args + ['-movflags', '+faststart', str(temp)])
        result = probe(temp)
        expected = sum(i['duration'] for i in infos)
        if abs(result['duration'] - expected) > max(.25, len(parts) * .05):
            raise H3Error('합친 영상의 길이가 원본 합계와 다릅니다. 결과를 덮어쓰지 않았습니다.')
        os.replace(temp, out)
        return out
    finally:
        temp.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)
