"""Persistent video editing, speech captions, real AI restoration and delivery.

Runs on the existing H3 web server. Model generation stays in its existing worker;
FFmpeg/CPU work is serialized separately. Originals and every accepted variant are immutable.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from .client import H3Error
from .jobs import new_job
from .story import narration_line
from . import storyrun as SR

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLOR = dict(brightness=0, contrast=1, saturation=1, gamma=1, sharpen=0, denoise=0)
RATIOS = {'16:9': (16, 9), '9:16': (9, 16), '1:1': (1, 1)}


def number(value, low, high, name):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise H3Error(f'{name}에 숫자를 입력하세요.') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise H3Error(f'{name} 범위는 {low}~{high}입니다.')
    return result


def probe(file):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(file)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise H3Error('미디어 파일을 읽지 못했습니다. MP4·MOV·PNG·JPG·WAV·MP3 등을 사용하세요.')
    info = json.loads(result.stdout)
    video = next((s for s in info.get('streams', []) if s['codec_type'] == 'video'), {})
    audio = next((s for s in info.get('streams', []) if s['codec_type'] == 'audio'), {})
    rate = video.get('avg_frame_rate') or '24/1'
    try:
        fps = float(Fraction(rate)) or 24
    except (ValueError, ZeroDivisionError):
        fps, rate = 24, '24/1'
    return dict(width=video.get('width', 0), height=video.get('height', 0), fps=fps, frameRate=rate,
                duration=float(info.get('format', {}).get('duration') or video.get('duration') or audio.get('duration') or 0),
                audio=bool(audio), video=bool(video), audioDuration=float(audio.get('duration') or 0))


def atomic(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(file)


def timeline(project):
    entries, cursor = [], 0.0
    for index, clip in enumerate(project['clips']):
        duration = float(clip['seconds'])
        transition = clip.get('transition', 'cut') if index + 1 < len(project['clips']) else 'cut'
        overlap = min(float(clip.get('transitionSeconds', .3)), duration / 2,
                      float(project['clips'][index + 1]['seconds']) / 2) if transition != 'cut' else 0
        entries.append(dict(id=clip['id'], start=round(cursor, 4), duration=duration, overlap=overlap, transition=transition))
        cursor += duration - overlap
    return entries, round(cursor, 4)


def timeline_key(project):
    values = [[c['id'], c.get('selected'), c['seconds'], c.get('trimIn'), c.get('trimOut'),
               c.get('transition'), c.get('transitionSeconds')] for c in project['clips']]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def content_key(project):
    return hashlib.sha256(json.dumps([timeline_key(project), [[c['corrections'], c['focus']] for c in project['clips']]]).encode()).hexdigest()


def caption_file(captions, vtt=False):
    def stamp(value):
        ms = round(float(value) * 1000)
        return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}{"." if vtt else ","}{ms % 1000:03}'
    rows = ['WEBVTT\n'] if vtt else []
    for index, caption in enumerate(captions):
        text = str(caption['text']).replace('-->', '→')
        rows.append(f'{index + 1}\n{stamp(caption["start"])} --> {stamp(caption["end"])}\n{text}\n')
    return '\n'.join(rows) + '\n'


class Paused(Exception):
    pass


class VideoStudio:
    def __init__(self, app):
        self.app = app
        self.root = app.store.root / '_studio'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.active, self.pause_events = {}, {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-finishing')

    def directory(self, project_id):
        if not re.fullmatch(r'edit-[a-f0-9]{32}', project_id):
            raise H3Error('잘못된 편집 프로젝트 ID입니다.')
        return self.root / project_id

    def file(self, project_id, relative):
        directory = self.directory(project_id).resolve()
        file = (directory / str(relative)).resolve()
        if directory not in file.parents or not file.is_file():
            raise H3Error('프로젝트 파일이 없거나 허용된 경로가 아닙니다.')
        return file

    def load(self, project_id):
        if project_id in self.active:
            return self.active[project_id]
        file = self.directory(project_id) / 'project.json'
        if not file.exists():
            raise KeyError(project_id)
        project = json.loads(file.read_text())
        if project.get('task', {}).get('status') in ('queued', 'running'):
            project['task']['status'] = 'paused'
            project['task']['message'] = '서버 재시작 후 저장한 지점에서 이어 할 수 있습니다.'
        return project

    def save(self, project):
        atomic(self.directory(project['id']) / 'project.json', project)

    def busy(self, project):
        return project['id'] in self.active or any(
            (job := self.app.store.get(item['job'])) and job.status in ('pending', 'running')
            for c in project['clips'] for item in c.get('pendingCandidates', []))

    def capabilities(self):
        home = Path(os.environ.get('H3_STUDIO_TOOLS', Path.home() / '.local/share/h3video/studio'))
        upscale = Path(os.environ.get('STUDIO_UPSCALER_DIR', Path.home() / '.local/share/storybook-maker/upscaler'))
        shared = Path(os.environ.get('H3_SHARED_STUDIO', ROOT.parent / 'storybook-maker'))
        return dict(ffmpeg=bool(shutil.which('ffmpeg')), transcription=(home / 'whisper-small/model.bin').exists(),
                    aiUpscale=(upscale / 'realesrgan-ncnn-vulkan').exists(),
                    referenceAnalysis=bool(shutil.which('yt-dlp')), referenceOCR=bool(shutil.which('tesseract')),
                    referenceVisionConfigured=bool(os.environ.get('H3_REFERENCE_VISION_BASE_URL') and os.environ.get('H3_REFERENCE_VISION_MODEL')),
                    qwenImage=dict(endpoint=os.environ.get('QWEN_IMAGE_BASE_URL', 'http://127.0.0.1:8091'),
                                   model=os.environ.get('QWEN_IMAGE_MODEL', 'Qwen/Qwen-Image-2.1')),
                    faceInspection=(shared / '.venv-studio/bin/python').exists(), draftSize=576, draftSteps=20,
                    generationServer=self.app.endpoint)

    def view(self, project):
        result = copy.deepcopy(project)
        def url(relative):
            return self.app.file_url(str(self.directory(project['id']) / relative)) if relative else None
        for clip in result['clips']:
            clip['imageUrl'] = url(clip.get('image'))
            for variant in clip['variants']:
                variant['url'] = url(variant['file'])
            clip['videoUrl'] = next((v['url'] for v in clip['variants'] if v['id'] == clip.get('selected')), None)
            for candidate in clip.get('pendingCandidates', []):
                job = self.app.store.get(candidate['job'])
                candidate['status'] = job.status if job else 'missing'
                candidate['error'] = job.error if job else '작업 기록 없음'
        for output in result.get('outputs', []):
            output['url'] = url(output['file'])
        result['captionsStale'] = bool(result.get('captionTimeline') and result['captionTimeline'] != timeline_key(project))
        result['inspectionStale'] = bool(result.get('inspection') and result['inspection'].get('fingerprint') != content_key(project))
        result['busy'] = self.busy(project)
        result['timeline'], result['duration'] = timeline(project)
        if result.get('task'):
            result['task'].pop('snapshot', None)
        return result

    def sync_candidates(self, project):
        changed = False
        for clip in project['clips']:
            for pending in clip.get('pendingCandidates', []):
                job = self.app.store.get(pending['job'])
                if pending.get('imported') or not job or job.status != 'completed' or not job.output:
                    continue
                variant = self.copy_variant(project, clip, Path(job.output), pending['phase'], seed=job.seed, job=job.id)
                pending['imported'] = True
                if not clip.get('selected'):
                    clip['selected'] = variant['id']
                changed = True
        if changed:
            self.save(project)

    def get(self, project_id):
        with self.lock:
            project = self.load(project_id)
            self.sync_candidates(project)
            return self.view(project)

    def list(self):
        result = []
        for directory in self.root.glob('edit-*'):
            try:
                p = self.get(directory.name)
                result.append(dict(id=p['id'], title=p['title'], updated=p['updated'], clips=len(p['clips']), busy=p['busy']))
            except (KeyError, H3Error, ValueError):
                continue
        return sorted(result, key=lambda p: p['updated'], reverse=True)

    def copy_variant(self, project, clip, source, operation, **details):
        root = self.app.store.root.resolve()
        source = source.resolve()
        if root not in source.parents:
            raise H3Error('서버에 저장된 영상만 가져올 수 있습니다.')
        info = probe(source)
        if not info['video'] or info['duration'] <= 0:
            raise H3Error('재생할 수 있는 영상이 아닙니다.')
        variant_id = uuid.uuid4().hex
        relative = 'media/' + variant_id + '.mp4'
        destination = self.directory(project['id']) / relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, destination)
        variant = dict(id=variant_id, file=relative, operation=operation, created=time.time(), **info, **details)
        clip['variants'].append(variant)
        return variant

    def clip(self, value):
        prompt = str(value.get('prompt') or '')
        existing_narration = narration_line(value.get('text'))
        if existing_narration and prompt.endswith(existing_narration):
            prompt = prompt[:-len(existing_narration)]
        return dict(id=str(value.get('id') or uuid.uuid4().hex), label=str(value.get('label') or '새 장면'),
                    prompt=prompt, text=str(value.get('text') or ''),
                    referenceMetadata={k: copy.deepcopy(value[k]) for k in ('source_start', 'source_end', 'text_overlays', 'image_prompt', 'analysis_engine') if k in value},
                    seconds=number(value.get('seconds', 4), .1, 86400, '장면 길이'),
                    image=None, variants=[], selected=None, trimIn=0, trimOut=None, transition='cut',
                    transitionSeconds=.3, motion='push', corrections=copy.deepcopy(DEFAULT_COLOR),
                    focus={ratio: dict(x=.5, y=.5) for ratio in RATIOS}, locked=False)

    def create(self, body):
        with self.lock:
            source = body.get('source')
            if source:
                for item in self.list():
                    previous = self.load(item['id'])
                    if previous.get('source') == source:
                        return self.view(previous)
            project = dict(id='edit-' + uuid.uuid4().hex, title=str(body.get('title') or '나의 영상'),
                           updated=time.time(), revision=0, source=source, clips=[], captions=[], outputs=[],
                           audio=dict(originalGain=1, narrationGain=1, musicGain=.18, duck=True, normalize=True),
                           delivery=dict(ratios=['16:9'], shortEdge=1080, fit='cover', subtitles=True))
            self.directory(project['id']).mkdir()
            native = []
            if source:
                if source.get('kind') == 'story':
                    name = str(source.get('id') or '')
                    if not re.fullmatch(r'story-[\w-]+', name):
                        raise H3Error('저장한 이야기 ID를 선택하세요.')
                    directory = self.app.store.root / name
                    state = SR.refresh_saved(directory, self.app.store)
                    project['title'] = state['title']
                    native = state['clips']
                    project['delivery']['ratios'] = [state['ratio']] if state['ratio'] in RATIOS else ['16:9']
                elif source.get('kind') == 'job':
                    job = self.app.store.get(str(source.get('id')))
                    if not job:
                        raise KeyError(source.get('id'))
                    project['title'] = job.title or '생성한 영상 편집'
                    native = [dict(id=f'scene-{s.index}', label=f'{s.index + 1}번 장면', prompt=s.prompt,
                                   seconds=s.duration, output=s.output, image=job.first_image if s.index == 0 else None)
                              for s in job.scenes]
                    project['delivery']['ratios'] = [job.aspect_ratio] if job.aspect_ratio in RATIOS else ['16:9']
                else:
                    raise H3Error('이야기 또는 영상 작업을 선택하세요.')
            for value in native or body.get('clips') or [{}]:
                c = self.clip(value)
                if any(old['id'] == c['id'] for old in project['clips']):
                    raise H3Error('장면 ID가 중복됩니다.')
                project['clips'].append(c)
                if value.get('output'):
                    v = self.copy_variant(project, c, Path(value['output']), 'original')
                    c['selected'] = v['id']
                if value.get('image') and self.app.file_url(value['image']):
                    file = Path(value['image'])
                    if file.is_file():
                        c['image'] = self.store_media(project, file.name, file.read_bytes(), 'image')
            self.save(project)
            return self.view(project)

    def store_media(self, project, filename, data, kind):
        extension = Path(filename).suffix.lower()
        allowed = {'image': ['.png', '.jpg', '.jpeg', '.webp'], 'video': ['.mp4', '.mov', '.webm', '.mkv'],
                   'audio': ['.wav', '.mp3', '.m4a', '.ogg', '.flac']}
        if extension not in allowed[kind]:
            raise H3Error('지원하는 이미지·영상·소리 파일을 선택하세요.')
        relative = 'media/' + uuid.uuid4().hex + extension
        file = self.directory(project['id']) / relative
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(data)
        try:
            info = probe(file)
            if kind in ('video', 'image') and not info['video'] or kind == 'audio' and not info['audio']:
                raise H3Error('선택한 미디어 종류와 파일 내용이 다릅니다.')
        except Exception:
            file.unlink(missing_ok=True)
            raise
        return relative

    def upload(self, project_id, body, filename, data):
        with self.lock:
            p = self.load(project_id)
            if self.busy(p):
                raise H3Error('현재 작업을 중지한 뒤 파일을 바꿔 주세요.')
            kind = body.get('kind', 'video')
            if kind not in ('image', 'video', 'audio'):
                raise H3Error('미디어 종류를 확인하세요.')
            relative = self.store_media(p, filename, data, kind)
            if kind == 'audio':
                target = body.get('track')
                if target not in ('narration', 'music'):
                    raise H3Error('내레이션 또는 음악 트랙을 선택하세요.')
                p['audio'][target] = relative
            else:
                c = self.find(p, body.get('clip'))
                if kind == 'image':
                    c['image'] = relative
                else:
                    info = probe(self.file(project_id, relative))
                    v = dict(id=uuid.uuid4().hex, file=relative, operation='uploaded', created=time.time(), **info)
                    c['variants'].append(v)
                    if not c.get('selected'):
                        c['selected'], c['seconds'] = v['id'], info['duration']
            p['revision'] += 1
            p['updated'] = time.time()
            self.save(p)
            return self.view(p)

    def find(self, project, clip_id):
        c = next((c for c in project['clips'] if c['id'] == clip_id), None)
        if not c:
            raise H3Error('장면을 찾지 못했습니다.')
        return c

    def update(self, project_id, body):
        with self.lock:
            p = copy.deepcopy(self.load(project_id))
            if self.busy(p):
                raise H3Error('현재 작업을 중지하고 저장한 뒤 편집하세요.')
            p['title'] = str(body.get('title', p['title'])).strip() or p['title']
            if 'clips' in body:
                previous = {c['id']: c for c in p['clips']}
                clips, seen = [], set()
                for edit in body['clips']:
                    cid = str(edit.get('id') or uuid.uuid4().hex)
                    if cid in seen:
                        raise H3Error('장면 ID가 중복됩니다.')
                    seen.add(cid)
                    c = previous.get(cid) or self.clip({'id': cid})
                    for key in ('label', 'prompt', 'text'):
                        if key in edit:
                            c[key] = str(edit[key])
                    c['locked'] = bool(edit.get('locked', c['locked']))
                    c['seconds'] = number(edit.get('seconds', c['seconds']), .1, 86400, '장면 길이')
                    c['trimIn'] = number(edit.get('trimIn', c['trimIn']), 0, 86400, '자르기 시작')
                    c['trimOut'] = number(edit['trimOut'], .01, 86400, '자르기 끝') if edit.get('trimOut') is not None else None
                    if c['trimOut'] is not None and c['trimOut'] <= c['trimIn']:
                        raise H3Error('자르기 끝은 시작보다 뒤여야 합니다.')
                    c['motion'] = edit.get('motion', c['motion'])
                    c['transition'] = edit.get('transition', c['transition'])
                    if c['motion'] not in ('still', 'push', 'pull', 'pan-left', 'pan-right') or c['transition'] not in ('cut', 'fade', 'wipeleft', 'slideright'):
                        raise H3Error('카메라 이동·장면 전환을 확인하세요.')
                    c['transitionSeconds'] = number(edit.get('transitionSeconds', c['transitionSeconds']), .05, 2, '전환 길이')
                    for key, limits in {'brightness': (-.3, .3), 'contrast': (.5, 1.5), 'saturation': (0, 2), 'gamma': (.5, 2), 'sharpen': (0, 1), 'denoise': (0, 3)}.items():
                        c['corrections'][key] = number(edit.get('corrections', {}).get(key, c['corrections'][key]), *limits, key)
                    for ratio in RATIOS:
                        for axis in ('x', 'y'):
                            c['focus'][ratio][axis] = number(edit.get('focus', {}).get(ratio, {}).get(axis, c['focus'][ratio][axis]), 0, 1, '인물 위치')
                    clips.append(c)
                if not clips:
                    raise H3Error('장면을 하나 이상 남겨 주세요.')
                p['clips'] = clips
            for key in ('originalGain', 'narrationGain', 'musicGain'):
                p['audio'][key] = number(body.get('audio', {}).get(key, p['audio'][key]), 0, 2, '소리 크기')
            for key in ('duck', 'normalize'):
                p['audio'][key] = bool(body.get('audio', {}).get(key, p['audio'][key]))
            for key in ('narration', 'music'):
                if body.get('audio', {}).get(key) is None and key in body.get('audio', {}):
                    p['audio'].pop(key, None)
            delivery = {**p['delivery'], **body.get('delivery', {})}
            if not isinstance(delivery['ratios'], list) or not delivery['ratios'] or any(r not in RATIOS for r in delivery['ratios']):
                raise H3Error('가로·세로·정사각 중 출력 화면비를 선택하세요.')
            delivery['shortEdge'] = int(number(delivery['shortEdge'], 64, 2160, '출력 해상도')) // 2 * 2
            if delivery['fit'] not in ('cover', 'contain'):
                raise H3Error('화면 채우기 또는 전체 그림 보기를 선택하세요.')
            p['delivery'] = delivery
            if 'captions' in body:
                captions = []
                duration = timeline(p)[1]
                for item in body['captions']:
                    start = number(item.get('start'), 0, duration, '자막 시작')
                    end = number(item.get('end'), 0, duration, '자막 끝')
                    if end <= start:
                        raise H3Error('자막 끝은 시작보다 뒤여야 합니다.')
                    captions.append(dict(start=start, end=end, text=str(item.get('text', ''))))
                p['captions'] = sorted(captions, key=lambda c: c['start'])
                p['captionTimeline'] = timeline_key(p)
            p['revision'] += 1
            p['updated'] = time.time()
            self.save(p)
            return self.view(p)

    def select(self, project_id, body):
        with self.lock:
            p = self.load(project_id)
            if self.busy(p):
                raise H3Error('현재 작업을 중지한 뒤 후보를 선택하세요.')
            c = self.find(p, body.get('clip'))
            v = next((v for v in c['variants'] if v['id'] == body.get('variant')), None)
            if not v:
                raise H3Error('저장한 영상 후보를 선택하세요.')
            c['selected'] = v['id']
            c['trimIn'], c['trimOut'] = 0, None
            c['seconds'] = min(c['seconds'], v['duration'])
            c['corrections'] = copy.deepcopy(DEFAULT_COLOR)
            p['revision'] += 1
            self.save(p)
            return self.view(p)

    def candidates(self, project_id, body):
        with self.lock:
            p = self.load(project_id)
            if self.busy(p):
                raise H3Error('현재 작업이 끝나거나 중지된 뒤 생성하세요.')
            count = int(number(body.get('count', 1), 1, 4, '후보 수'))
            phase = body.get('phase', 'draft')
            if phase not in ('draft', 'final'):
                raise H3Error('초안 또는 확정 생성을 선택하세요.')
            seed = int(number(body.get('seed', 0), 0, 2147483647, '시드'))
            ids = body.get('clips') or [c['id'] for c in p['clips'] if not c['locked']]
            targets = [self.find(p, cid) for cid in ids]
            if not targets or any(c['locked'] for c in targets):
                raise H3Error('확정을 해제한 장면을 선택하세요.')
            if any(not c['prompt'].strip() for c in targets):
                raise H3Error('생성할 장면의 프롬프트를 입력하세요.')
            for c in targets:
                c.setdefault('pendingCandidates', [])
                for index in range(count):
                    first = str(self.file(project_id, c['image'])) if c.get('image') else None
                    job = new_job(c['prompt'] + narration_line(c['text']), seconds=max(4, round(c['seconds'])), aspect_ratio=p['delivery']['ratios'][0],
                                  seed=seed + index, first_image=first, short_edge=576 if phase == 'draft' else 768,
                                  steps=20 if phase == 'draft' else 50, title=p['title'] + ' · ' + c['label'])
                    self.app.worker.enqueue(job)
                    c['pendingCandidates'].append(dict(job=job.id, phase=phase, seed=job.seed))
            self.save(p)
            return self.view(p)

    def pause(self, project_id):
        with self.lock:
            p = self.load(project_id)
            self.pause_events.get(project_id, threading.Event()).set()
            for c in p['clips']:
                for candidate in c.get('pendingCandidates', []):
                    job = self.app.store.get(candidate['job'])
                    if job and job.status in ('pending', 'running'):
                        self.app.worker.pause(job.id)
            return dict(ok=True, message='중지하고 저장하는 중입니다. 완료한 영상과 업스케일 프레임은 유지됩니다.')

    def start(self, project_id, operation, options=None):
        with self.lock:
            p = self.load(project_id)
            if self.busy(p):
                raise H3Error('현재 작업을 중지한 뒤 다른 작업을 시작하세요.')
            if operation == 'resume':
                task = p.get('task')
                if task and task['status'] in ('paused', 'error'):
                    operation, options = task['operation'], task['options']
                    if task['sourceRevision'] != p['revision']:
                        task = None
                else:
                    resumed = False
                    for c in p['clips']:
                        for candidate in c.get('pendingCandidates', []):
                            job = self.app.store.get(candidate['job'])
                            if job and job.status == 'paused':
                                self.app.worker.resume(job.id)
                                resumed = True
                    if not resumed:
                        raise H3Error('이어 할 중지 작업이 없습니다.')
                    return self.view(p)
            else:
                task = None
            if operation not in ('preview', 'render', 'transcribe', 'inspect', 'upscale'):
                raise H3Error('지원하지 않는 편집 작업입니다.')
            options = options or {}
            if operation == 'upscale':
                options['scale'] = int(number(options.get('scale', 2), 2, 4, '업스케일 배율'))
                if options['scale'] not in (2, 4) or options.get('model', 'illustration') not in ('illustration', 'photo', 'anime'):
                    raise H3Error('업스케일 배율·모델을 확인하세요.')
                if options.get('engine', 'realesrgan') not in ('realesrgan', 'qwen-realesrgan'):
                    raise H3Error('업스케일 방식을 확인하세요.')
                if options.get('engine') == 'qwen-realesrgan':
                    options['retouchPrompt'] = str(options.get('retouchPrompt') or '').strip()
                    if not options['retouchPrompt']:
                        raise H3Error('Qwen Image 보정 지시를 입력하세요.')
                c = self.find(p, options.get('clip'))
                if c['locked'] or not c.get('selected'):
                    raise H3Error('확정을 해제하고 영상이 있는 장면을 선택하세요.')
            if not task:
                snapshot = copy.deepcopy(p)
                snapshot.pop('task', None)
                task = dict(id=uuid.uuid4().hex, operation=operation, options=options, snapshot=snapshot,
                            sourceRevision=p['revision'], created=time.time(), progress=0)
            p['task'] = task
            task.update(status='queued', error=None, message='편집 대기열에 등록했습니다.')
            self.active[project_id] = p
            self.pause_events[project_id] = threading.Event()
            self.save(p)
            self.executor.submit(self.execute, p)
            return self.view(p)

    def check_pause(self, p):
        if self.pause_events[p['id']].is_set():
            raise Paused()

    def progress(self, p, value, message):
        with self.lock:
            p['task'].update(progress=max(0, min(.99, value)), message=message)
            self.save(p)

    def command(self, p, args, stdin=None, duration=None):
        self.check_pause(p)
        work = self.directory(p['id']) / '.work' / p['task']['id']
        work.mkdir(parents=True, exist_ok=True)
        out, err = work / 'process.stdout', work / 'process.stderr'
        with out.open('w') as stdout, err.open('w') as stderr:
            child = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr)
            if stdin is not None:
                child.stdin.write(json.dumps(stdin).encode())
                child.stdin.close()
            while child.poll() is None:
                if self.pause_events[p['id']].wait(.15):
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                    raise Paused()
            if child.returncode:
                raise H3Error((err.read_text(errors='replace') or out.read_text(errors='replace'))[-2500:] or '영상 처리 실패')
        return out.read_text(errors='replace')

    def ffmpeg(self, p, args):
        return self.command(p, ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-threads', '2', '-filter_threads', '1',
                                '-filter_complex_threads', '1', *args])

    def variant(self, clip):
        return next((v for v in clip['variants'] if v['id'] == clip.get('selected')), None)

    def dimensions(self, ratio, short_edge):
        a, b = RATIOS[ratio]
        return ((round(short_edge * a / b / 2) * 2, short_edge) if a >= b else
                (short_edge, round(short_edge * b / a / 2) * 2))

    def color(self, c):
        v = c['corrections']
        filters = [f'eq=brightness={v["brightness"]}:contrast={v["contrast"]}:saturation={v["saturation"]}:gamma={v["gamma"]}']
        if v['denoise']:
            filters.append(f'hqdn3d={v["denoise"]}:{v["denoise"]}:3:3')
        if v['sharpen']:
            filters.append(f'unsharp=5:5:{v["sharpen"]}:5:5:0')
        return ','.join(filters)

    def segment(self, p, snapshot, clip, output, ratio, short_edge, animatic):
        w, h = self.dimensions(ratio, short_edge)
        variant = self.variant(clip)
        image = clip.get('image')
        duration = clip['seconds']
        inputs, filters = [], []
        source_audio = False
        if variant and not animatic:
            source = self.file(p['id'], variant['file'])
            info = probe(source)
            if clip['trimIn'] >= info['duration']:
                raise H3Error(clip['label'] + ': 자르기 시작이 영상 길이를 넘습니다.')
            available = min(info['duration'], clip.get('trimOut') or info['duration']) - clip['trimIn']
            inputs = ['-ss', str(clip['trimIn']), '-t', str(available), '-i', str(source)]
            filters.extend(['setpts=PTS-STARTPTS', 'fps=24', f'tpad=stop_mode=clone:stop_duration={max(0,duration-available)}'])
            source_audio = info['audio']
        elif image:
            inputs = ['-loop', '1', '-i', str(self.file(p['id'], image))]
        else:
            inputs = ['-f', 'lavfi', '-i', f'color=c=0x263f43:s={w}x{h}:r=24']
        focus = clip['focus'][ratio]
        if snapshot['delivery']['fit'] == 'contain':
            filters.append(f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black')
        else:
            filters.append(f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}:(iw-ow)*{focus["x"]}:(ih-oh)*{focus["y"]}')
        if not variant or animatic:
            frames = max(1, round(duration * 24))
            zoom = '1' if clip['motion'] == 'still' else f'1+0.08*on/{frames}' if clip['motion'] == 'push' else f'1.08-0.08*on/{frames}' if clip['motion'] == 'pull' else '1.08'
            x = f'(iw-iw/zoom)*on/{frames}' if clip['motion'] == 'pan-right' else f'(iw-iw/zoom)*(1-on/{frames})' if clip['motion'] == 'pan-left' else '(iw-iw/zoom)/2'
            filters.append(f"zoompan=z='{zoom}':x='{x}':y='(ih-ih/zoom)/2':d=1:s={w}x{h}:fps=24")
        filters.extend([self.color(clip), 'setsar=1', 'format=yuv420p'])
        if not source_audio:
            inputs += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        af = 'aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,apad'
        self.ffmpeg(p, [*inputs, '-map', '0:v:0', '-map', '0:a:0' if source_audio else '1:a:0',
                        '-vf', ','.join(filters), '-af', af, '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '18', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(output)])

    def compose(self, p, snapshot, directory, ratio, short_edge, animatic=False, subtitles=True):
        directory.mkdir(parents=True, exist_ok=True)
        entries, total = timeline(snapshot)
        parts = []
        for index, clip in enumerate(snapshot['clips']):
            part = directory / f'part-{index}.mp4'
            self.progress(p, .05 + .55 * index / len(entries), f'{clip["label"]} · 자르기·보정·화면 배치')
            self.segment(p, snapshot, clip, part, ratio, short_edge, animatic)
            parts.append(part)
        joined = parts[0]
        elapsed = entries[0]['duration']
        for index in range(1, len(parts)):
            result = directory / f'join-{index}.mp4'
            transition = entries[index-1]
            overlap = transition['overlap']
            if overlap:
                vf = f'[0:v][1:v]xfade=transition={transition["transition"]}:duration={overlap}:offset={elapsed-overlap}[v]'
                af = f'[0:a][1:a]acrossfade=d={overlap}:c1=tri:c2=tri[a]'
                graph = vf + ';' + af
            else:
                graph = '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]'
            self.ffmpeg(p, ['-i', joined, '-i', parts[index], '-filter_complex', graph, '-map', '[v]', '-map', '[a]',
                            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-b:a', '192k', '-t', str(elapsed + entries[index]['duration'] - overlap), str(result)])
            joined = result
            elapsed += entries[index]['duration'] - overlap
        output = directory / 'composed.mp4'
        audio = snapshot['audio']
        inputs = ['-i', joined]
        graph = [f'[0:a]volume={audio["originalGain"]},apad,atrim=duration={total}[original]']
        labels = ['original']
        input_index = 1
        narration_label = 'original'
        for name in ('narration', 'music'):
            if not audio.get(name):
                continue
            if name == 'music':
                inputs += ['-stream_loop', '-1']
            inputs += ['-i', self.file(p['id'], audio[name])]
            graph.append(f'[{input_index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={audio[name+"Gain"]},apad,atrim=duration={total}[{name}]')
            labels.append(name)
            if name == 'narration':
                narration_label = name
            input_index += 1
        if 'music' in labels and audio['duck']:
            graph.append(f'[{narration_label}]asplit=2[voice_mix][voice_side]')
            graph.append('[music][voice_side]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[music_duck]')
            labels = ['voice_mix' if label == narration_label else 'music_duck' if label == 'music' else label for label in labels]
        graph.append(''.join(f'[{label}]' for label in labels) + f'amix=inputs={len(labels)}:normalize=0:duration=longest' +
                     (',dynaudnorm=f=250:g=7:p=0.9:m=5,alimiter=limit=0.95' if audio['normalize'] else '') + '[a]')
        w, h = self.dimensions(ratio, short_edge)
        if subtitles and snapshot['delivery'].get('subtitles') and snapshot.get('captions'):
            ass = directory / 'captions.ass'
            ass.write_text(self.ass(snapshot['captions'], w, h))
            escaped = str(ass).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
            graph.append(f"[0:v]subtitles=filename='{escaped}'[v]")
            video = '[v]'
        else:
            video = '0:v:0'
        self.progress(p, .7, '자막·내레이션·배경음 합성')
        self.ffmpeg(p, [*inputs, '-filter_complex', ';'.join(graph), '-map', video, '-map', '[a]', '-t', str(total),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', output])
        return output

    def ass(self, captions, width, height):
        def stamp(value):
            n = round(value * 100)
            return f'{n//360000}:{n//6000%60:02}:{n//100%60:02}.{n%100:02}'
        header = f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Noto Sans CJK KR,{max(16,round(min(width,height)*.042))},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,{round(height*.08)},1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        for c in captions:
            text = c['text'].replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r', '').replace('\n', '\\N')
            header += f'Dialogue: 0,{stamp(c["start"])},{stamp(c["end"])},Default,,0,0,0,,{text}\n'
        return header

    def publish_output(self, p, file, kind, **details):
        relative = 'exports/' + uuid.uuid4().hex + file.suffix
        destination = self.directory(p['id']) / relative
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(file, destination)
        p['outputs'].append(dict(file=relative, kind=kind, created=time.time(), sourceRevision=p['revision'], **details))
        self.save(p)
        return relative

    def upscale(self, p, snapshot, work):
        task, options = p['task'], p['task']['options']
        if task.get('result'):
            current = copy.deepcopy(p)
            current.pop('task', None)
            self.inspect(p, current, work)
            return
        clip = self.find(snapshot, options['clip'])
        variant = self.variant(clip)
        source = self.file(p['id'], variant['file'])
        info = probe(source)
        home = Path(os.environ.get('STUDIO_UPSCALER_DIR', Path.home() / '.local/share/storybook-maker/upscaler'))
        binary = home / 'realesrgan-ncnn-vulkan'
        if not binary.exists():
            raise H3Error('실제 AI 업스케일 도구를 설치하세요: storybook-maker npm run install:studio')
        frames, restored = work / 'frames', work / 'restored'
        frames.mkdir(exist_ok=True); restored.mkdir(exist_ok=True)
        retouched = work / 'qwen-retouched'
        retouched.mkdir(exist_ok=True)
        if not (work / 'extracted.json').exists():
            self.progress(p, .02, '원본 프레임 추출·밝기·색감·노이즈 보정')
            self.ffmpeg(p, ['-i', source, '-vf', self.color(clip), '-fps_mode', 'passthrough', frames / '%08d.png'])
            atomic(work / 'extracted.json', info)
        images = sorted(frames.glob('*.png'))
        if not images:
            raise H3Error('업스케일할 프레임을 추출하지 못했습니다.')
        model = options.get('model', 'illustration')
        model_name = {'illustration': 'realesr-animevideov3', 'photo': 'realesrgan-x4plus', 'anime': 'realesrgan-x4plus-anime'}[model]
        for index, image in enumerate(images):
            self.check_pause(p)
            output = restored / image.name
            if output.exists():
                continue
            temporary = restored / (image.stem + '.working.png')
            source_image = image
            if options.get('engine') == 'qwen-realesrgan':
                source_image = retouched / image.name
                if not source_image.exists():
                    self.progress(p, .05 + .85 * index / len(images), f'Qwen Image 보정 {index+1}/{len(images)} · 원본 구도 유지')
                    python = ROOT / '.venv-video-studio/bin/python'
                    if not python.exists():
                        raise H3Error('이미지 편집 도구를 설치하세요: npm run install:studio')
                    self.command(p, [python, ROOT / 'scripts/qwen-retouch.py'],
                                 dict(input=str(image), output=str(source_image), seed=0,
                                      prompt='Preserve exact composition, identities, geometry and typography across this video frame. ' + options['retouchPrompt']))
            self.progress(p, .05 + .85 * index / len(images), f'AI 업스케일 {index+1}/{len(images)} 프레임 · 완료한 프레임 자동 저장')
            self.command(p, [binary, '-i', source_image, '-o', temporary, '-s', str(options['scale']), '-t', '64',
                             '-m', home / 'models', '-n', model_name, '-g', os.environ.get('STUDIO_UPSCALER_GPU', '0'), '-j', '1:1:1'])
            probe(temporary)
            temporary.replace(output)
        final = work / 'upscaled.mp4'
        self.progress(p, .93, '원본 프레임 속도·소리 유지하여 영상 복원')
        self.ffmpeg(p, ['-framerate', info['frameRate'], '-i', restored / '%08d.png', '-i', source,
                        '-map', '0:v:0', '-map', '1:a?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
                        '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', final])
        measured = probe(final)
        if measured['width'] != info['width'] * options['scale'] or measured['height'] != info['height'] * options['scale']:
            raise H3Error('AI 업스케일 결과 크기가 예상과 다릅니다. 원본은 보존했습니다.')
        if abs(measured['duration'] - info['duration']) > max(.12, 2 / info['fps']):
            raise H3Error('업스케일 결과 길이가 달라 원본을 유지했습니다.')
        current = self.find(p, clip['id'])
        variant = self.copy_variant(p, current, final, 'ai-upscale', scale=options['scale'], model=model,
                                    bakedCorrections=clip['corrections'], engine='Qwen Image Edit + Real-ESRGAN' if options.get('engine') == 'qwen-realesrgan' else 'Real-ESRGAN',
                                    retouchPrompt=options.get('retouchPrompt'), parent=variant['id'])
        current['selected'] = variant['id']
        current['corrections'] = copy.deepcopy(DEFAULT_COLOR)
        task['result'] = variant['id']
        self.save(p)
        current_snapshot = copy.deepcopy(p)
        current_snapshot.pop('task', None)
        self.inspect(p, current_snapshot, work)

    def inspect(self, p, snapshot, work):
        events, face_reports = [], []
        entries, _ = timeline(snapshot)
        for index, c in enumerate(snapshot['clips']):
            v = self.variant(c)
            if not v:
                events.append(dict(type='missing', clip=c['id'], start=entries[index]['start'], end=entries[index]['start'], reason='생성 영상이 없습니다.'))
                continue
            source = work / ('inspection-' + str(index) + '.mp4')
            self.segment(p, snapshot, c, source, snapshot['delivery']['ratios'][0], 320, False)
            duration = probe(source)['duration']
            self.progress(p, index / len(entries) * .85, c['label'] + ' · 검은 화면·정지·소리·얼굴 검사')
            self.ffmpeg(p, ['-i', source, '-vf', 'blackdetect=d=0.15:pix_th=0.1,freezedetect=n=-45dB:d=1',
                            '-af', 'silencedetect=n=-40dB:d=0.5', '-f', 'null', '-'])
            log = (work / 'process.stderr').read_text(errors='replace')
            for kind, prefix in [('black', 'black'), ('freeze', 'lavfi.freezedetect.freeze'), ('silence', 'silence')]:
                starts = re.findall(re.escape(prefix) + r'_start[:=]\s*([\d.]+)', log)
                ends = re.findall(re.escape(prefix) + r'_end[:=]\s*([\d.]+)', log)
                for at, start in enumerate(starts):
                    events.append(dict(type=kind, clip=c['id'], start=round(entries[index]['start']+float(start),3),
                                       end=round(entries[index]['start']+(float(ends[at]) if at<len(ends) else duration),3),
                                       reason={'black':'검은 화면 구간','freeze':'화면 변화가 적은 구간 · 의도된 정지 장면인지 확인','silence':'무음 구간 · 의도된 무음인지 확인'}[kind]))
            if not probe(source)['audio']:
                events.append(dict(type='silence', clip=c['id'], start=entries[index]['start'], end=entries[index]['start']+c['seconds'], reason='오디오 트랙이 없습니다.'))
            self.ffmpeg(p, ['-i', source, '-vf', 'fps=4,signalstats,metadata=print:key=lavfi.signalstats.YAVG', '-an', '-f', 'null', '-'])
            luma_log = (work / 'process.stderr').read_text(errors='replace')
            luminance = [float(value) for value in re.findall(r'lavfi.signalstats.YAVG=([\d.]+)', luma_log)]
            for frame in range(1, len(luminance)):
                delta = abs(luminance[frame] - luminance[frame-1])
                if delta > 40:
                    at = entries[index]['start'] + frame / 4
                    events.append(dict(type='flicker', clip=c['id'], start=at, end=at,
                                       score=round(delta,2), reason='밝기가 급격히 바뀐 구간 · 의도된 효과인지 확인'))
            samples = work / ('samples-' + str(index))
            samples.mkdir(exist_ok=True)
            self.ffmpeg(p, ['-i', source, '-vf', 'fps=1,scale=320:-2', samples / '%06d.png'])
            shared = Path(os.environ.get('H3_SHARED_STUDIO', ROOT.parent / 'storybook-maker'))
            python = shared / '.venv-studio/bin/python'
            if python.exists():
                values = [{'file': str(f), 'time': entries[index]['start'] + n} for n,f in enumerate(sorted(samples.glob('*.png')))]
                report = json.loads(self.command(p, [python, ROOT / 'scripts/video-face-check.py'], {'samples': values}))
                for event in report['events']:
                    events.append(dict(**event, clip=c['id']))
                face_reports.append(dict(clip=c['id'], **report))
        p['inspection'] = dict(created=time.time(), fingerprint=content_key(snapshot), events=sorted(events,key=lambda e:e['start']), faces=face_reports,
                               note='품질 의심 구간을 안내합니다. 의도된 정지·무음·인물 변경은 직접 확인하세요.')

    def execute(self, p):
        task = p['task']
        work = self.directory(p['id']) / '.work' / task['id']
        work.mkdir(parents=True, exist_ok=True)
        try:
            self.check_pause(p)
            task['status'] = 'running'
            snapshot = task['snapshot']
            operation = task['operation']
            if operation == 'upscale':
                self.upscale(p, snapshot, work)
            elif operation == 'inspect':
                self.inspect(p, snapshot, work)
            elif operation == 'transcribe':
                python = ROOT / '.venv-video-studio/bin/python'
                if not python.exists() or not self.capabilities()['transcription']:
                    raise H3Error('자동 자막 도구를 설치하세요: python3 scripts/install-video-tools.py')
                source = self.compose(p, snapshot, work / 'speech', snapshot['delivery']['ratios'][0], 320, subtitles=False)
                self.progress(p, .8, '실제 음성을 인식해 자막 시간 맞추는 중')
                response = json.loads(self.command(p, [python, ROOT / 'scripts/video-transcribe.py'],
                                                 dict(input=str(source), language=task['options'].get('language') or None)))
                p['captions'] = response['captions']
                p['captionTimeline'] = timeline_key(snapshot)
                p['transcription'] = {k:v for k,v in response.items() if k != 'captions'}
                self.write_captions(p)
            else:
                if operation == 'render' and any(not c.get('selected') for c in snapshot['clips']):
                    raise H3Error('최종 출력 전에 모든 장면의 영상을 생성하거나 업로드하세요. 콘티 미리보기는 그림만으로 가능합니다.')
                if operation == 'render' and snapshot.get('captions') and snapshot['delivery'].get('subtitles') and snapshot.get('captionTimeline') != timeline_key(snapshot):
                    raise H3Error('장면이 바뀌어 자막 시간이 맞지 않을 수 있습니다. 자막을 다시 인식하거나 시간 수정 후 저장하세요.')
                ratios = snapshot['delivery']['ratios'] if operation == 'render' else snapshot['delivery']['ratios'][:1]
                for ratio in ratios:
                    source = self.compose(p, snapshot, work / ratio.replace(':','-'), ratio,
                                          snapshot['delivery']['shortEdge'] if operation == 'render' else 320,
                                          animatic=operation == 'preview' and bool(task['options'].get('animatic')))
                    self.publish_output(p, source, operation, ratio=ratio, **probe(source))
                if operation == 'render':
                    self.write_captions(p)
                    bundle = work / 'delivery.zip'
                    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
                        for output in p['outputs'][-len(ratios):]:
                            archive.write(self.file(p['id'], output['file']), output['ratio'].replace(':','-') + '.mp4')
                        archive.writestr('captions.srt', caption_file(p['captions']))
                        archive.writestr('captions.vtt', caption_file(p['captions'], True))
                        archive.writestr('timeline.json', json.dumps({k:v for k,v in snapshot.items() if k!='task'}, ensure_ascii=False, indent=2))
                    self.publish_output(p, bundle, 'bundle')
            task.update(status='done', progress=1, message='완료했습니다. 원본·후보·출력 파일을 모두 보관했습니다.')
        except Paused:
            task.update(status='paused', message='저장하고 중지했습니다. 설정을 수정하거나 저장한 지점에서 이어 할 수 있습니다.')
        except Exception as error:
            task.update(status='error', error=str(error), message='작업을 완료하지 못했습니다. 기존 결과는 유지됩니다.')
        finally:
            with self.lock:
                p['updated'] = time.time()
                self.save(p)
                self.active.pop(p['id'], None)
                self.pause_events.pop(p['id'], None)

    def write_captions(self, p):
        directory = self.directory(p['id']) / 'exports'
        directory.mkdir(exist_ok=True)
        for extension in ('srt', 'vtt'):
            relative = 'exports/captions.' + extension
            (directory / ('captions.' + extension)).write_text(caption_file(p['captions'], extension=='vtt'))
        return {'srt': self.app.file_url(str(directory/'captions.srt')), 'vtt': self.app.file_url(str(directory/'captions.vtt'))}

    def dispatch(self, project_id, action, body):
        if action == 'settings':
            return self.update(project_id, body)
        if action == 'select':
            return self.select(project_id, body)
        if action == 'candidates':
            return self.candidates(project_id, body)
        if action == 'pause':
            return self.pause(project_id)
        if action == 'captions':
            with self.lock:
                return self.write_captions(self.load(project_id))
        return self.start(project_id, action, body)

    def close(self):
        if hasattr(self.app, 'references'):
            self.app.references.close()
        with self.lock:
            for event in self.pause_events.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            for project in self.active.values():
                project['task'].update(status='paused', message='서버 종료 전 저장했습니다.')
                self.save(project)
            self.active.clear()
