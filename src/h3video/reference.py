"""Checkpointed YouTube/upload reference analysis on the existing web server."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

from .client import H3Error
from .studio import ROOT, Paused, atomic, number, probe


def downloader():
    # User services do not necessarily inherit the interactive shell PATH.
    candidates = [ROOT / '.venv-video-studio/bin/yt-dlp', Path.home() / '.local/bin/yt-dlp']
    return next((str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None) or shutil.which('yt-dlp')


def youtube_url(value):
    url = urlparse(str(value).strip())
    if url.scheme not in ('https', 'http') or url.username or url.password or url.port:
        raise H3Error('YouTube 영상 주소를 입력하세요.')
    host = (url.hostname or '').lower()
    if host == 'youtu.be':
        video = url.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        video = parse_qs(url.query).get('v', [''])[0] if url.path == '/watch' else (
            url.path.split('/')[2] if re.fullmatch(r'/(shorts|live|embed)/[^/]+/?', url.path) else '')
    else:
        raise H3Error('youtube.com 또는 youtu.be의 영상 주소만 사용할 수 있습니다.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise H3Error('재생목록 대신 개별 YouTube 영상 주소를 입력하세요.')
    return 'https://www.youtube.com/watch?v=' + video


def validate_document(value):
    if not isinstance(value, dict) or not isinstance(value.get('clips'), list) or not value['clips']:
        raise H3Error('JSON에는 clips 장면 배열이 필요합니다.')
    result = copy.deepcopy(value)
    ids = set()
    for index, c in enumerate(result['clips']):
        if not isinstance(c, dict):
            raise H3Error('각 장면은 JSON 객체여야 합니다.')
        c['id'] = str(c.get('id') or f'reference-{index + 1}')
        if c['id'] in ids:
            raise H3Error('장면 ID가 중복됩니다.')
        ids.add(c['id'])
        c['seconds'] = number(c.get('seconds'), .1, 86400, '장면 길이')
        c['video_prompt'] = str(c.get('video_prompt') or c.get('prompt') or '').split('\nTypography: ', 1)[0]
        c['prompt'] = c['video_prompt']
        if not isinstance(c.get('text_overlays', []), list):
            raise H3Error('text_overlays는 글자 영역 배열이어야 합니다.')
        for item in c.get('text_overlays', []):
            if not isinstance(item, dict) or not isinstance(item.get('box'), dict):
                raise H3Error('글자 위치에는 x·y·width·height box가 필요합니다.')
            b = item['box']
            for key in ('x', 'y', 'width', 'height'):
                b[key] = number(b.get(key), 0, 1, '글자 위치 ' + key)
            if b['x'] + b['width'] > 1.001 or b['y'] + b['height'] > 1.001:
                raise H3Error('글자 영역은 화면 안에 배치하세요.')
            item['font_size_ratio'] = number(item.get('font_size_ratio', b['height']), .001, 1, '글자 크기 비율')
            if not re.fullmatch(r'#[0-9A-Fa-f]{6}', str(item.get('color', '#ffffff'))):
                raise H3Error('글자 색은 #ffffff 형식으로 입력하세요.')
            item['font_weight'] = int(number(item.get('font_weight', 700), 100, 900, '글자 굵기'))
        c['typography_prompt'] = '; '.join(
            f'Text {json.dumps(str(o.get("text", "")), ensure_ascii=False)}: '
            f'font {o.get("font_family", "Noto Sans CJK KR")}, weight {o["font_weight"]}, '
            f'color {o.get("color", "#ffffff")}, size {o["font_size_ratio"]} of frame height, '
            f'box x={o["box"]["x"]}, y={o["box"]["y"]}, width={o["box"]["width"]}, height={o["box"]["height"]}'
            for o in c.get('text_overlays', []))
        if c['typography_prompt']:
            c['prompt'] += '\nTypography: ' + c['typography_prompt']
        c['image_prompt'] = str(c.get('image_prompt') or '').split('\nTypography: ', 1)[0]
        if c['typography_prompt']:
            c['image_prompt'] += '\nTypography: ' + c['typography_prompt']
        if c.get('reference_frame') and not re.fullmatch(r'frames/[0-9]+\.png', str(c['reference_frame'])):
            raise H3Error('분석한 장면의 프레임 파일을 선택하세요.')
    return result


class ReferenceLibrary:
    def __init__(self, app):
        self.app = app
        self.root = app.store.root / '_references'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.active, self.events = {}, {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-reference')

    def directory(self, name):
        if not re.fullmatch(r'ref-[a-f0-9]{32}', str(name)):
            raise H3Error('잘못된 참고 분석 ID입니다.')
        return self.root / name

    def load(self, name):
        if name in self.active:
            return self.active[name]
        file = self.directory(name) / 'analysis.json'
        if not file.exists():
            raise KeyError(name)
        job = json.loads(file.read_text())
        if job['status'] in ('queued', 'running'):
            job.update(status='paused', message='서버 재시작 후 저장한 프레임부터 이어 할 수 있습니다.')
        return job

    def save(self, job):
        job['updated'] = time.time()
        atomic(self.directory(job['id']) / 'analysis.json', job)

    def view(self, job):
        result = copy.deepcopy(job)
        directory = self.directory(job['id'])
        result['frames'] = [dict(file=c['reference_frame'], url=self.app.file_url(str(directory / c['reference_frame'])),
                                 source_time=c['source_start'], overlays=c.get('text_overlays', []))
                            for c in job.get('document', {}).get('clips', []) if c.get('reference_frame')]
        if (directory / 'prompts.json').exists():
            result['jsonUrl'] = self.app.file_url(str(directory / 'prompts.json'))
        if (directory / 'reference.zip').exists():
            result['bundleUrl'] = self.app.file_url(str(directory / 'reference.zip'))
        return result

    def get(self, name):
        with self.lock:
            return self.view(self.load(name))

    def list(self):
        rows = []
        for d in self.root.glob('ref-*'):
            try:
                job = self.load(d.name)
                rows.append({k: job.get(k) for k in ('id', 'title', 'updated', 'status', 'progress', 'message')})
            except (KeyError, ValueError, OSError):
                continue
        return sorted(rows, key=lambda j: j['updated'], reverse=True)

    def create(self, body, upload=None):
        options = dict(start=number(body.get('start', 0), 0, 86400, '분석 시작'),
                       interval=number(body.get('interval', 6), .5, 300, '장면 간격'),
                       end=None if body.get('end') in ('', None) else number(body['end'], .1, 86400, '분석 끝'),
                       transcribe=body.get('transcribe', True) not in (False, 'false', '0'),
                       language=str(body.get('language') or ''), goal=str(body.get('goal') or ''),
                       font=str(body.get('font') or 'Noto Sans CJK KR'))
        if options['end'] is not None and options['end'] <= options['start']:
            raise H3Error('끝 시각을 시작 시각보다 크게 입력하세요.')
        source = dict(kind='upload', name=Path(upload[0]).name) if upload else dict(kind='youtube', url=youtube_url(body.get('url')))
        name = 'ref-' + uuid.uuid4().hex
        d = self.directory(name); d.mkdir()
        if upload:
            (d / 'upload.mp4').write_bytes(upload[1])
            info = probe(d / 'upload.mp4')
            if not info['video'] or info['duration'] <= 0:
                shutil.rmtree(d)
                raise H3Error('분석할 영상 파일을 올려 주세요.')
        job = dict(id=name, title=source.get('name') or 'YouTube 참고 분석', source=source, options=options,
                   status='paused', message='분석 준비', progress=0, created=time.time(), updated=time.time(), warnings=[])
        self.save(job)
        return self.resume(name)

    def restart(self, name):
        with self.lock:
            if name in self.active:raise H3Error('먼저 분석을 중지하세요.')
            job=self.load(name)
            body={**job['options']}
            if job['source']['kind']=='youtube':
                return self.create({**body,'url':job['source']['url']})
            return self.create(body,(job['source']['name'],(self.directory(name)/'upload.mp4').read_bytes()))

    def pause(self, name):
        with self.lock:
            job = self.load(name)
            if name in self.events:
                self.events[name].set()
                job['message'] = '현재 작업을 중지하고 완료한 프레임을 저장하는 중…'
                self.save(job)
            return self.view(job)

    def resume(self, name):
        with self.lock:
            job = self.load(name)
            if name in self.active or job['status'] == 'done':
                return self.view(job)
            self.events[name] = threading.Event()
            self.active[name] = job
            job.update(status='queued', error=None, message='참고 영상 분석 대기')
            self.save(job)
            self.executor.submit(self.execute, job)
            return self.view(job)

    def command(self, job, args, stdin=None, timeout=600):
        event = self.events[job['id']]
        if event.is_set():
            raise Paused()
        d = self.directory(job['id'])
        with (d / 'process.stdout').open('w') as stdout, (d / 'process.stderr').open('w') as stderr:
            child = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, start_new_session=True)
            if stdin is not None:
                child.stdin.write(json.dumps(stdin).encode()); child.stdin.close()
            deadline = time.monotonic() + timeout
            while child.poll() is None:
                if event.wait(.15) or time.monotonic() > deadline:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait()
                    if event.is_set():
                        raise Paused()
                    raise H3Error('분석 응답 시간이 초과됐습니다. 저장한 작업에서 다시 이어 하세요.')
            if child.returncode:
                log = (d / 'process.stderr').read_text(errors='replace')
                if 'Sign in' in log or '403' in log or 'bot' in log:
                    raise H3Error('YouTube에서 서버 접근을 제한했습니다. 직접 준비한 영상 파일을 올려 같은 분석을 실행할 수 있습니다.')
                clean = re.sub(r'https?://\S+', '[URL]', log[-1500:])
                raise H3Error(clean or '참고 영상 처리에 실패했습니다.')
        return (d / 'process.stdout').read_text(errors='replace')

    def progress(self, job, value, text):
        with self.lock:
            job.update(progress=value, message=text)
            self.save(job)

    def execute(self, job):
        d = self.directory(job['id']); options = job['options']
        try:
            job['status'] = 'running'; self.save(job)
            video = d / 'selected.mp4'
            if not video.exists():
                self.progress(job, .02, '참고 영상과 게시 정보 읽기')
                if job['source']['kind'] == 'youtube':
                    binary = downloader()
                    if not binary:
                        raise H3Error('yt-dlp가 없습니다. npm run install:studio로 분석 도구를 설치하세요.')
                    common = [binary, '--ignore-config', '--no-playlist', '--socket-timeout', '20', '--retries', '1', '--fragment-retries', '1']
                    metadata = json.loads(self.command(job, [*common, '--dump-single-json', '--skip-download', job['source']['url']], timeout=120))
                    if metadata.get('is_live') or not metadata.get('duration'):
                        raise H3Error('현재 방송 중인 영상 대신 재생 시간이 정해진 영상을 선택하세요.')
                    job['title'] = metadata.get('title') or job['title']
                    job['source'].update(channel=metadata.get('channel'), duration=metadata['duration'], license=metadata.get('license'))
                    end = min(options['end'] if options['end'] is not None else options['start'] + 60, float(metadata['duration']))
                    if options['start'] >= end:
                        raise H3Error('시작 시각이 원본 영상의 끝보다 뒤에 있습니다.')
                    self.save(job)
                    self.command(job, [*common, '-f', 'bv*[height<=720]+ba/b[height<=720]/b', '--download-sections',
                                       f'*{options["start"]}-{end}', '--force-keyframes-at-cuts', '--merge-output-format', 'mp4',
                                       '--remux-video', 'mp4', '-o', d / 'download.%(ext)s', job['source']['url']], timeout=1800)
                    media = d / 'download.mp4'
                    if not media.exists():
                        raise H3Error('YouTube 영상 다운로드가 완료되지 않았습니다.')
                    media.replace(video)
                else:
                    source_info = probe(d / 'upload.mp4')
                    job['source']['duration'] = source_info['duration']
                    end = min(options['end'] if options['end'] is not None else options['start'] + 60, source_info['duration'])
                    if options['start'] >= end:
                        raise H3Error('시작 시각이 영상 끝보다 뒤에 있습니다.')
                    self.command(job, ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-ss', options['start'], '-i', d / 'upload.mp4',
                                       '-t', end-options['start'], '-threads', '2', '-c:v', 'libx264', '-preset', 'fast',
                                       '-c:a', 'aac', '-movflags', '+faststart', d / 'selected.working.mp4'])
                    (d / 'selected.working.mp4').replace(video)
            info = probe(video)
            self.progress(job, .15, '화면 전환과 장면 구간 찾기')
            cuts_file = d / 'cuts.json'
            if cuts_file.exists():
                cuts = json.loads(cuts_file.read_text())
            else:
                self.command(job, ['ffmpeg', '-hide_banner', '-nostdin', '-i', video, '-vf',
                                   "select='gt(scene,0.32)',showinfo", '-an', '-f', 'null', '-'])
                log = (d / 'process.stderr').read_text()
                candidates = [float(t) for t in re.findall(r'pts_time:([\d.]+)', log)]
                boundaries = sorted(set([0.0, info['duration'], *candidates,
                                         *[round(i*options['interval'], 4) for i in range(1, math.ceil(info['duration']/options['interval']))]]))
                cuts = [boundaries[0]]
                for at in boundaries[1:]:
                    if at-cuts[-1] >= .3 or at == info['duration']:
                        cuts.append(at)
                if len(cuts)>2 and cuts[-1]-cuts[-2]<.1:
                    cuts.pop(-2)
                atomic(cuts_file, cuts)
            captions_file = d / 'transcript.json'
            if not captions_file.exists():
                captions = dict(captions=[], engine='none')
                if options['transcribe'] and info['audio']:
                    python = ROOT / '.venv-video-studio/bin/python'
                    model = Path(os.environ.get('H3_STUDIO_TOOLS', Path.home()/'.local/share/h3video/studio')) / 'whisper-small/model.bin'
                    if python.exists() and model.exists():
                        self.progress(job, .22, '로컬 Whisper로 음성 자막 추출')
                        self.command(job, ['ffmpeg','-hide_banner','-nostdin','-y','-i',video,'-vn','-ac','1','-ar','16000',d/'audio.wav'])
                        captions = json.loads(self.command(job, [python, ROOT/'scripts/video-transcribe.py'],
                                                          dict(input=str(d/'audio.wav'),language=options['language'] or None), timeout=3600))
                    else:
                        job['warnings'].append('음성 인식 모델 미설치: 화면 분석만 포함했습니다.')
                atomic(captions_file, captions)
            captions = json.loads(captions_file.read_text())
            frames = d / 'frames'; frames.mkdir(exist_ok=True)
            clips, warnings = [], list(job['warnings'])
            for index, (start, end) in enumerate(zip(cuts, cuts[1:])):
                if self.events[job['id']].is_set():
                    raise Paused()
                image = frames/f'{index+1:04d}.png'; analysis = frames/f'{index+1:04d}.json'
                self.progress(job, .3+.65*index/max(1,len(cuts)-1), f'{index+1}/{len(cuts)-1} 장면 · 글자 위치·색·프롬프트 분석')
                if not image.exists():
                    self.command(job, ['ffmpeg','-hide_banner','-nostdin','-y','-ss',(start+end)/2,'-i',video,'-frames:v','1',image])
                if not analysis.exists():
                    python = ROOT/'.venv-video-studio/bin/python'
                    if not python.exists():
                        raise H3Error('분석 도구를 설치하세요: npm run install:studio')
                    texts = [c['text'] for c in captions.get('captions',[]) if c['start']<end and c['end']>start]
                    measured = json.loads(self.command(job, [python,ROOT/'scripts/reference-frame.py'],
                                                      dict(image=str(image),font=options['font'],transcript=' '.join(texts),goal=options['goal']),timeout=180))
                    atomic(analysis, measured)
                measured = json.loads(analysis.read_text())
                warnings.extend(measured.get('warnings',[]))
                spoken = ' '.join(c['text'] for c in captions.get('captions',[]) if c['start']<end and c['end']>start)
                clips.append(dict(id=f'reference-{index+1}',label=f'{index+1}번 참고 장면',seconds=round(end-start,4),
                                  source_start=round(options['start']+start,4),source_end=round(options['start']+end,4),
                                  reference_frame='frames/'+image.name,imageName=image.name,text=spoken,
                                  prompt=measured['video_prompt'],video_prompt=measured['video_prompt'],image_prompt=measured['image_prompt'],
                                  visual_description=measured['description'],analysis_engine=measured['engine'],
                                  text_overlays=measured['overlays'],camera=measured.get('camera','검토 필요'),
                                  palette=measured['palette']))
            aspect = min(('16:9','9:16','1:1'),key=lambda r:abs(info['width']/info['height']-int(r.split(':')[0])/int(r.split(':')[1])))
            document = dict(schema_version=1,title=job['title'],aspect_ratio=aspect,source=job['source'],
                            analysis=dict(width=info['width'],height=info['height'],start=options['start'],duration=info['duration'],
                                          font_detection='원본 글꼴 이름은 자동으로 확정할 수 없습니다. font_family는 수정 가능한 출력 글꼴입니다.',
                                          speech_engine=captions['engine'],warnings=sorted(set(warnings))),clips=clips)
            job['document'] = validate_document(document)
            job['warnings'] = document['analysis']['warnings']
            self.export(job)
            job.update(status='done',progress=1,message=f'{len(clips)}개 장면의 프롬프트·글자 위치 JSON을 저장했습니다.')
        except Paused:
            job.update(status='paused',message='완료한 장면을 저장했습니다. 이어 하기를 누르면 복원됩니다.')
        except Exception as error:
            job.update(status='error',error=str(error),message='분석 실패 · 완료한 파일과 기존 프로젝트는 유지됩니다.')
        finally:
            with self.lock:
                self.save(job); self.active.pop(job['id'],None)

    def export(self, job):
        d = self.directory(job['id'])
        atomic(d/'prompts.json',job['document'])
        temporary = d/'reference.working.zip'
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(d/'prompts.json','prompts.json')
            for c in job['document']['clips']:
                if c.get('reference_frame'):
                    path=(d/c['reference_frame']).resolve()
                    if d.resolve() not in path.parents or not path.is_file():
                        raise H3Error('참고 프레임 파일을 찾지 못했습니다.')
                    archive.write(path,Path(c['reference_frame']).name)
        temporary.replace(d/'reference.zip')

    def edit(self, name, body):
        with self.lock:
            job=self.load(name)
            if name in self.active:
                raise H3Error('분석을 중지한 뒤 JSON을 수정하세요.')
            if not job.get('document'):
                raise H3Error('분석을 완료한 뒤 JSON을 수정하세요.')
            document=validate_document(body.get('document'))
            before=copy.deepcopy(job)
            job['document']=document
            try:
                self.export(job)
            except Exception:
                job['document']=before['document'];self.export(job);raise
            self.save(job)
            return self.view(job)

    def import_project(self, name):
        with self.lock:
            job=self.load(name)
            if job['status']!='done':
                raise H3Error('분석을 완료한 뒤 편집 프로젝트로 가져오세요.')
            d=self.directory(name)
            body=copy.deepcopy(job['document'])
            body.pop('source', None)
            for c in body['clips']:
                if c.get('reference_frame'):
                    c['image']=str(d/c['reference_frame'])
            project=self.app.studio.create(body)
            native=self.app.studio.load(project['id'])
            native['reference']=dict(id=name,source=job['source'],analysis=body.get('analysis'))
            native['delivery']['ratios']=[body.get('aspect_ratio','16:9')]
            self.app.studio.save(native)
            return self.app.studio.view(native)

    def close(self):
        for event in self.events.values():
            event.set()
        self.executor.shutdown(wait=True,cancel_futures=True)
        for job in self.active.values():
            job.update(status='paused',message='서버 종료 전 저장했습니다.');self.save(job)
