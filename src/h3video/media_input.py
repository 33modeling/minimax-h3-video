"""Offline input inspection; never opens a server or fetches remote media."""
from __future__ import annotations

import difflib
import json
import math
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .client import H3Error

EXTENSIONS = {
    'image': ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'),
    'video': ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi'),
    'audio': ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.opus', '.aif', '.aiff'),
}


def normalize_input(value: str) -> str:
    text = str(value)
    cleaned = text.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1]
    if cleaned.startswith(('https://', 'http://', 'file://')):
        if cleaned.startswith('file://') and urlsplit(cleaned).netloc not in ('', 'localhost'):
            raise H3Error('file URI는 file:///경로 형식으로 입력하세요. 다른 컴퓨터 파일은 공유 폴더나 웹 업로드로 전달하세요.')
        return cleaned
    if Path(text).expanduser().is_file():
        return str(Path(text).expanduser().resolve())
    text = cleaned
    path = Path(text).expanduser()
    if not path.is_file():
        try:
            parts = shlex.split(text)
            if len(parts) == 1 and Path(parts[0]).expanduser().is_file():
                path = Path(parts[0]).expanduser()
        except ValueError:
            pass
    return str(path.resolve())


def input_kind(value: str) -> str | None:
    path = unquote(urlsplit(value).path) if value.startswith(('http://', 'https://', 'file://')) else value
    suffix = Path(path).suffix.lower()
    return next((kind for kind, extensions in EXTENSIONS.items() if suffix in extensions), None)


def describe_input(value: str, expected: str | None = None) -> dict:
    source = normalize_input(value)
    kind = input_kind(source)
    if expected and kind and kind != expected:
        raise H3Error(f'{expected} 입력에 {kind} 파일을 넣었습니다: {value}. --first는 그림, --input은 종류 자동 판별입니다.')
    kind = expected or kind
    if not kind:
        raise H3Error(f'파일 종류를 자동 판별할 수 없습니다: {value}. --image / --video / --audio로 종류를 지정하세요.')
    if source.startswith(('http://', 'https://', 'file://')):
        return dict(source=source, type=kind, location='url' if source.startswith('http') else 'server-file-uri',
                    bytes=None, verification='remote-unverified')
    path = Path(source)
    if not path.is_file():
        matches = []
        try:
            names = [p.name for p in path.parent.iterdir() if p.is_file()]
            matches = difflib.get_close_matches(path.name, names, n=3, cutoff=.45)
        except OSError:
            pass
        hint = '\n  비슷한 파일: ' + ', '.join(repr(name) for name in matches) if matches else ''
        raise H3Error(f'입력 파일 없음: {source}{hint}\n  H100에서 실행한다면 그 서버나 공유 폴더의 파일 경로를 사용하세요.')
    size = path.stat().st_size
    if not size:
        raise H3Error(f'입력 파일이 비어 있습니다: {source}')
    return dict(source=source, type=kind, location='local', bytes=size, verification='file-checked')


def inspect_input(value: str) -> dict:
    info = describe_input(value)
    if info['location'] != 'local':
        info['note'] = '주소 형식만 확인했습니다. 원격 파일의 존재·해상도·길이는 확인하지 않았습니다.'
        return info
    binary = shutil.which('ffprobe')
    if not binary:
        info.update(metadata_status='unavailable', note='ffprobe가 없어 해상도·길이를 확인하지 못했습니다.')
        return info
    try:
        result = subprocess.run([binary, '-v', 'error', '-show_entries',
            'format=format_name,duration:stream=codec_type,width,height,duration:stream_disposition=attached_pic',
            '-of', 'json', info['source']], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise H3Error('미디어를 읽을 수 없습니다. 파일 손상이나 실제 형식을 확인하세요: ' + info['source'])
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        videos = [s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
        audio = any(s.get('codec_type') == 'audio' for s in streams)
        formats = data.get('format', {}).get('format_name', '').split(',')
        image = any(f.endswith('_pipe') or f in ('image2', 'gif', 'apng') for f in formats) and not audio
        actual = 'image' if image and videos else 'video' if videos else 'audio' if audio else None
        if actual != info['type']:
            raise H3Error(f'확장자와 실제 미디어 형식이 다릅니다: {info["source"]} (실제: {actual or "미확인"})')
        info.update(metadata_status='verified', verification='media-checked')
        if videos:
            info.update(width=videos[0].get('width'), height=videos[0].get('height'))
        if not image:
            duration = data.get('format', {}).get('duration')
            if duration not in (None, 'N/A'):
                seconds = float(duration)
                if not math.isfinite(seconds) or seconds < 0:
                    raise H3Error('유효한 미디어 길이를 읽지 못했습니다: ' + info['source'])
                info['duration_seconds'] = seconds
        return info
    except (subprocess.TimeoutExpired, ValueError) as error:
        raise H3Error('미디어 정보 확인에 실패했습니다: ' + info['source']) from error
