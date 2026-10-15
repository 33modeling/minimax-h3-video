"""HyperFrames integration: persistent compositions + the real Studio/renderer.

The upstream package is pinned in tools/hyperframes. No generation model or
GPU server is started here. Source and media stay in the existing output root.
"""
from __future__ import annotations

import copy
import html
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

from .client import H3Error
from .studio import atomic, probe, timeline

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'tools/hyperframes'
VERSION = '0.8.158'
ID = re.compile(r'hf-[a-f0-9]{32}')
RATIOS = {'16:9': (1280, 720), '9:16': (720, 1280), '1:1': (1080, 1080)}
TEMPLATES = {'story': '스토리·영상', 'launch': '제품 소개', 'captions': '키네틱 자막', 'stats': '숫자·정보', 'blank': '빈 화면'}
MEDIA = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.mp4', '.webm', '.mov', '.mp3', '.wav', '.m4a', '.ogg', '.flac'}


def finite(value, low, high, label):
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise H3Error(f'{label}: 숫자를 입력하세요.') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise H3Error(f'{label}: {low}~{high} 범위로 입력하세요.')
    return result


def scene(value):
    if not isinstance(value, dict):
        raise H3Error('장면은 JSON 객체여야 합니다.')
    result = dict(id=str(value.get('id') or uuid.uuid4().hex), title=str(value.get('title', value.get('label', '새 장면')))[:300],
                  text=str(value.get('text', ''))[:10000], seconds=finite(value.get('seconds', 4), .1, 86400, '장면 길이'),
                  background=str(value.get('background', '#101927')), color=str(value.get('color', '#ffffff')),
                  motion=str(value.get('motion', 'rise')), asset=str(value.get('asset', '')), kind=str(value.get('kind', 'image')),
                  fontSize=finite(value.get('fontSize', 64), 10, 400, '글자 크기'),
                  x=finite(value.get('x', 8), 0, 90, '글자 가로 위치'), y=finite(value.get('y', 58), 0, 90, '글자 세로 위치'),
                  trim=finite(value.get('trim', 0), 0, 86400, '원본 시작 시각'),
                  volume=finite(value.get('volume', 1), 0, 4, '원본 소리'))
    if not re.fullmatch(r'[\w-]{1,100}', result['id']):
        raise H3Error('장면 ID를 확인하세요.')
    for key in ('background', 'color'):
        if not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', result[key]):
            raise H3Error('색상은 #RRGGBB 형식으로 입력하세요.')
    if result['motion'] not in ('rise', 'fade', 'slide', 'zoom', 'none'):
        raise H3Error('지원하는 모션을 선택하세요.')
    if result['asset'] and not re.fullmatch(r'assets/[a-f0-9]{32}\.[a-z0-9]+', result['asset']):
        raise H3Error('프로젝트에 업로드한 미디어를 선택하세요.')
    if result['kind'] not in ('image', 'video'):
        raise H3Error('미디어 종류를 확인하세요.')
    return result


def composition(project):
    """A native HyperFrames composition, not a video-shaped canvas mockup."""
    width, height = RATIOS[project['ratio']]
    width, height = int(project.get('width', width)), int(project.get('height', height))
    duration = sum(s['seconds'] for s in project['scenes'])
    blocks, motions = [], []
    start = 0
    for index, s in enumerate(project['scenes']):
        sid = 'scene-' + s['id']
        media = ''
        if s['asset']:
            attr = f'class="clip media" data-start="{start:g}" data-duration="{s["seconds"]:g}" data-track-index="{index * 3}"'
            src = html.escape(s['asset'], quote=True)
            media = (f'<video {attr} src="{src}" data-media-start="{s["trim"]:g}" data-volume="{s["volume"]:g}" playsinline></video>'
                     if s['kind'] == 'video' else f'<img {attr} src="{src}" alt="">')
        title = html.escape(s['title'])
        text = html.escape(s['text']).replace('\n', '<br>')
        blocks.append(media + f'''<section id="{sid}" class="clip scene" data-start="{start:g}" data-duration="{s['seconds']:g}" data-track-index="{index * 3 + 1}" style="background:{'transparent' if media else s['background']};color:{s['color']}">
<div class="copy" style="left:{s['x']}%;top:{s['y']}%;font-size:{s['fontSize']}px"><h1>{title}</h1><p>{text}</p></div></section>''')
        target = json.dumps('#' + sid + ' .copy')
        before = {'rise': {'y': 45, 'opacity': 0}, 'fade': {'opacity': 0}, 'slide': {'x': -70, 'opacity': 0}, 'zoom': {'scale': .88, 'opacity': 0}, 'none': {'opacity': 1}}[s['motion']]
        motions.append(f'tl.fromTo({target},{json.dumps(before)},{{x:0,y:0,scale:1,opacity:1,duration:{min(.65,s["seconds"] / 3):g},ease:"power2.out"}},{start:g});')
        if s['seconds'] > .5:
            motions.append(f'tl.to({json.dumps("#" + sid)},{{opacity:0,duration:.2}},{start + s["seconds"] - .2:g});')
        start += s['seconds']
    audio = ''
    if project.get('music'):
        audio = f'<audio src="{html.escape(project["music"], quote=True)}" data-start="0" data-duration="{duration:g}" data-track-index="9999" data-volume="{project.get("musicVolume", .2)}"></audio>'
    if project.get('narration'):
        audio += f'<audio src="{html.escape(project["narration"], quote=True)}" data-start="0" data-duration="{duration:g}" data-track-index="10000" data-volume="{project.get("narrationVolume", 1)}"></audio>'
    captions = []
    for index, caption in enumerate(project.get('captions', [])):
        at, end = max(0, float(caption['start'])), min(duration, float(caption['end']))
        if end > at:
            captions.append(f'<div class="clip subtitle" data-start="{at:g}" data-duration="{end-at:g}" data-track-index="{10001+index}">{html.escape(caption["text"]).replace(chr(10), "<br>")}</div>')
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(project['title'])}</title>
<script src="assets/gsap.min.js"></script><style>
@font-face{{font-family:'Noto Sans CJK KR';src:local('Noto Sans CJK KR');font-weight:100 900}}
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#101927}}body{{font-family:'Noto Sans CJK KR',sans-serif}}
.scene{{position:absolute;inset:0;overflow:hidden}}.media{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}.copy{{position:absolute;width:84%;z-index:2;text-shadow:0 2px 20px #0008}}h1{{margin:0 0 .3em;font-size:1em;line-height:1.2;font-weight:800;white-space:pre-wrap;overflow-wrap:anywhere}}p{{font-size:.43em;line-height:1.6;margin:0;overflow-wrap:anywhere}}.subtitle{{position:absolute;left:7%;right:7%;bottom:7%;text-align:center;font-size:{round(min(width,height)*.042)}px;color:white;text-shadow:0 2px 5px black;z-index:10001;overflow-wrap:anywhere}}#stage{{position:relative;overflow:hidden;width:{width}px;height:{height}px}}
</style></head><body><main id="stage" data-composition-id="h3-motion" data-start="0" data-duration="{duration:g}" data-width="{width}" data-height="{height}" data-fps="{project['fps']}">
{''.join(blocks)}{audio}{''.join(captions)}</main><script>
const tl=gsap.timeline({{paused:true}});{''.join(motions)}
tl.to({{}},{{duration:.001}},{max(0,duration-.001):g});window.__timelines=window.__timelines||{{}};window.__timelines['h3-motion']=tl;
</script></body></html>'''


class MotionStudio:
    def __init__(self, app):
        self.app = app
        self.root = app.store.root / '_hyperframes'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='hyperframes-render')
        self.children, self.processes, self.pauses, self.active = {}, {}, {}, set()
        self.closed = False

    def directory(self, name):
        if not ID.fullmatch(str(name)):
            raise H3Error('잘못된 모션 프로젝트 ID입니다.')
        return self.root / name

    def load(self, name):
        file = self.directory(name) / 'project.json'
        if not file.exists():
            raise KeyError(name)
        p = json.loads(file.read_text())
        if name not in self.active and p.get('task', {}).get('status') in ('running', 'queued', 'pausing'):
            p['task'].update(status='paused', message='저장한 프로젝트에서 렌더링을 이어갈 수 있습니다.')
            self.save(p)
        return p

    def save(self, p):
        p['updated'] = time.time()
        atomic(self.directory(p['id']) / 'project.json', p)

    def file(self, name, relative):
        root = self.directory(name).resolve()
        file = (root / relative).resolve()
        if root not in file.parents or not file.is_file() or file.is_symlink():
            raise H3Error('프로젝트 안의 파일만 사용할 수 있습니다.')
        return file

    def env(self):
        env = {**os.environ, 'DO_NOT_TRACK': '1', 'HYPERFRAMES_NO_TELEMETRY': '1', 'CI': '1',
               'HF_SEGMENTED_CAPTURE': 'true', 'HF_SEGMENT_FRAMES': '120', 'PRODUCER_BROWSER_GPU_MODE': 'software', 'PRODUCER_LOW_MEMORY_MODE': 'true'}
        if not env.get('HYPERFRAMES_BROWSER_PATH'):
            candidates = sorted((Path.home() / '.cache/ms-playwright').glob('chromium_headless_shell-*/chrome-linux/headless_shell'))
            candidates += sorted((Path.home() / '.cache/ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
            candidates += sorted((Path.home() / '.cache/ms-playwright').glob('chromium-*/chrome-linux64/chrome'))
            for binary in reversed(candidates):
                if binary.is_file():
                    env['HYPERFRAMES_BROWSER_PATH'] = str(binary)
                    break
        return env

    def runtime(self):
        node = TOOLS / 'node_modules/node/bin/node'
        cli = TOOLS / 'node_modules/hyperframes/bin/hyperframes.mjs'
        if not node.is_file() or not cli.is_file():
            raise H3Error('HyperFrames를 설치하세요: npm run install:hyperframes')
        return node, cli

    def capabilities(self):
        try:
            self.runtime()
            ready = True
        except H3Error:
            ready = False
        return dict(installed=ready, version=VERSION, ffmpeg=bool(shutil.which('ffmpeg')),
                    templates=[dict(id=k, label=v) for k, v in TEMPLATES.items()],
                    upstream='https://github.com/heygen-com/hyperframes', browser=bool(self.env().get('HYPERFRAMES_BROWSER_PATH')))

    def snapshot(self, p, label):
        version = uuid.uuid4().hex
        directory = self.directory(p['id'])
        atomic(directory / 'history' / (version + '.json'), dict(id=version, label=label, created=time.time(), project=copy.deepcopy(p),
                                                               html=(directory / 'composition/index.html').read_text()))
        return version

    def copy_asset(self, p, source):
        source = source.resolve()
        if self.app.store.root.resolve() not in source.parents or not source.is_file():
            raise H3Error('영상 maker에 저장된 미디어만 가져올 수 있습니다.')
        suffix = source.suffix.lower()
        if suffix not in MEDIA:
            raise H3Error('지원하지 않는 미디어 형식입니다.')
        relative = 'assets/' + uuid.uuid4().hex + suffix
        shutil.copyfile(source, self.directory(p['id']) / 'composition' / relative)
        return relative

    def create(self, body):
        self.runtime()
        if body.get('source') and not isinstance(body['source'], dict):
            raise H3Error('가져올 원본 프로젝트를 선택하세요.')
        ratio = body.get('ratio', '16:9')
        if ratio not in RATIOS:
            raise H3Error('화면비는 16:9, 9:16, 1:1 중에서 선택하세요.')
        template = body.get('template', 'story')
        if template not in TEMPLATES:
            raise H3Error('템플릿을 선택하세요.')
        p = dict(id='hf-' + uuid.uuid4().hex, title=str(body.get('title') or TEMPLATES[template])[:160], ratio=ratio,
                 fps=24, template=template, scenes=[], created=time.time(), updated=time.time(), task={}, outputs=[], source=body.get('source'))
        directory = self.directory(p['id'])
        (directory / 'composition/assets').mkdir(parents=True)
        shutil.copyfile(TOOLS / 'node_modules/gsap/dist/gsap.min.js', directory / 'composition/assets/gsap.min.js')
        try:
            if body.get('source'):
                source = body['source']
                if source.get('kind') == 'edit':
                    original = self.app.studio.get(source['id'])
                else:
                    original = self.app.studio.create({'source': source})
                if original.get('busy'):
                    raise H3Error('원본 영상 편집 작업을 중지·저장한 뒤 가져오세요.')
                p['title'] = str(body.get('title') or original['title'])[:160]
                p['sourceSnapshot'] = original
                p['ratio'] = original['delivery']['ratios'][0]
                for entry in timeline(original)[0]:
                    c = next(c for c in original['clips'] if c['id'] == entry['id'])
                    selected = next((v for v in c['variants'] if v['id'] == c.get('selected')), None)
                    rel = selected['file'] if selected else c.get('image')
                    item = scene(dict(id=c['id'], title=c['label'], text=c['text'], seconds=entry['duration'], trim=c.get('trimIn', 0),
                                      kind='video' if selected else 'image', volume=original['audio'].get('originalGain', 1)))
                    if rel:
                        item['asset'] = self.copy_asset(p, self.app.studio.file(original['id'], rel))
                    p['scenes'].append(item)
                music = original['audio'].get('music')
                if music:
                    p['music'] = self.copy_asset(p, self.app.studio.file(original['id'], music))
                    p['musicVolume'] = original['audio']['musicGain']
                narration = original['audio'].get('narration')
                if narration:
                    p['narration'] = self.copy_asset(p, self.app.studio.file(original['id'], narration))
                    p['narrationVolume'] = original['audio']['narrationGain']
                if original['delivery'].get('subtitles'):
                    p['captions'] = copy.deepcopy(original.get('captions', []))
            else:
                p['scenes'] = [scene(s) for s in body.get('scenes', [])] or [scene(dict(title='이야기가 움직이는 순간', text='글 · 이미지 · 영상으로 만드는 모션 스튜디오', seconds=4)),
                    scene(dict(title='직접 고치고, 바로 확인하세요', text='타임라인에서 장면과 소리를 다듬어 보세요.', background='#184a53', seconds=4))]
                if template == 'stats':
                    p['scenes'][0].update(title='98%', text='전하고 싶은 숫자와 근거를 입력하세요.')
                elif template == 'captions':
                    p['scenes'][0].update(title='한 문장에 움직임을 더하세요', motion='slide')
                elif template == 'launch':
                    p['scenes'][0].update(title='새로운 시작', text='제품과 서비스의 핵심을 소개하세요.', background='#243b74')
                elif template == 'blank':
                    p['scenes'] = [scene(dict(title='', text='', seconds=4))]
            if len({s['id'] for s in p['scenes']}) != len(p['scenes']):
                raise H3Error('장면 ID가 중복되었습니다.')
            (directory / 'composition/index.html').write_text(composition(p))
            self.save(p)
            return self.get(p['id'])
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def get(self, name):
        with self.lock:
            p = copy.deepcopy(self.load(name))
            directory = self.directory(name)
            p['html'] = (directory / 'composition/index.html').read_text()
            p['updated'] = max(p['updated'], (directory / 'composition/index.html').stat().st_mtime)
            p['studioUrl'] = '/?hyperframes=' + name
            p['proxy'] = '/hyperframes/' + name + '/proxy'
            p['previewUrl'] = p['proxy'] + '/api/projects/h3-motion/preview'
            p['assets'] = [dict(file='assets/' + f.name, name=p.get('assetNames', {}).get('assets/' + f.name, f.name), url=self.app.file_url(str(f)))
                           for f in sorted((directory / 'composition/assets').iterdir()) if f.suffix.lower() in MEDIA and f.is_file()]
            p['outputs'] = [dict(file=str(f.relative_to(directory)), name=f.name, url=self.app.file_url(str(f)), size=f.stat().st_size)
                            for folder in [directory / 'exports', directory / 'composition/renders'] if folder.exists()
                            for f in sorted(folder.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
                            if f.is_file() and f.suffix in ('.mp4', '.webm', '.mov', '.gif') and f.stat().st_size > 0
                            and (self.native_complete(f) if folder.name == 'renders' else str(f.relative_to(directory)) in p.get('completedOutputs', []))]
            p['history'] = sorted([dict(id=f.stem, label=(r := json.loads(f.read_text()))['label'], created=r['created'])
                            for f in (directory / 'history').glob('*.json')], key=lambda r: r['created'], reverse=True)
            return p

    @staticmethod
    def native_complete(file):
        try:
            return json.loads(file.with_suffix('.meta.json').read_text()).get('status') == 'complete'
        except (OSError, ValueError):
            return False

    def list(self):
        result = []
        for directory in self.root.glob('hf-*'):
            try:
                p = self.load(directory.name)
                p['updated'] = max(p['updated'], (directory / 'composition/index.html').stat().st_mtime)
                result.append({k: p[k] for k in ('id', 'title', 'ratio', 'updated', 'task')})
            except (H3Error, KeyError, ValueError, OSError):
                continue
        return sorted(result, key=lambda p: p['updated'], reverse=True)

    def edit(self, name, body):
        with self.lock:
            p = self.load(name)
            if name in self.active:
                raise H3Error('렌더링을 중지한 뒤 수정하세요. 기존 출력은 보관됩니다.')
            next_p = copy.deepcopy(p)
            if 'title' in body:
                if not isinstance(body['title'], str) or not body['title'].strip():
                    raise H3Error('프로젝트 이름을 입력하세요.')
                next_p['title'] = body['title'].strip()[:160]
            if 'ratio' in body:
                if body['ratio'] not in RATIOS:
                    raise H3Error('화면비를 선택하세요.')
                next_p['ratio'] = body['ratio']
            if 'fps' in body:
                next_p['fps'] = int(finite(body['fps'], 1, 120, '프레임 속도'))
            if 'music' in body:
                music = str(body['music'])
                if music:
                    if not re.fullmatch(r'assets/[a-f0-9]{32}\.(mp3|wav|m4a|ogg|flac)', music):
                        raise H3Error('업로드한 음악을 선택하세요.')
                    self.file(name, 'composition/' + music)
                next_p['music'] = music
            if 'musicVolume' in body:
                next_p['musicVolume'] = finite(body['musicVolume'], 0, 4, '음악 볼륨')
            if 'scenes' in body:
                if not isinstance(body['scenes'], list) or not body['scenes']:
                    raise H3Error('장면은 하나 이상 필요합니다.')
                next_p['scenes'] = [scene(s) for s in body['scenes']]
                if len({s['id'] for s in next_p['scenes']}) != len(next_p['scenes']):
                    raise H3Error('장면 ID가 중복되었습니다.')
                for s in next_p['scenes']:
                    if s['asset']:
                        self.file(name, 'composition/' + s['asset'])
            raw = body.get('html')
            if raw is not None and (not isinstance(raw, str) or len(raw.encode()) > 5 * 1024 * 1024 or 'data-composition-id' not in raw):
                raise H3Error('5MB 이하의 HyperFrames HTML 문서를 입력하세요.')
            self.snapshot(p, '수정 전 자동 저장')
            if raw is not None or body.get('applyVisual'):
                target = self.directory(name) / 'composition/index.html'
                text = raw if raw is not None else composition(next_p)
                temporary = target.with_suffix('.tmp')
                temporary.write_text(text)
                temporary.replace(target)
            self.save(next_p)
            return self.get(name)

    def restore(self, name, version):
        if not re.fullmatch(r'[a-f0-9]{32}', str(version)):
            raise H3Error('저장 지점을 선택하세요.')
        with self.lock:
            p = self.load(name)
            if name in self.active:
                raise H3Error('렌더링을 중지한 뒤 복원하세요.')
            record = json.loads(self.file(name, 'history/' + version + '.json').read_text())
            self.snapshot(p, '복원 전 자동 저장')
            current_task = p.get('task', {})
            completed = p.get('completedOutputs', [])
            p = record['project']
            p['task'] = current_task
            p['completedOutputs'] = completed
            (self.directory(name) / 'composition/index.html').write_text(record['html'])
            self.save(p)
            return self.get(name)

    def upload(self, name, filename, data):
        with self.lock:
            p = self.load(name)
            if name in self.active:
                raise H3Error('렌더링을 중지한 뒤 미디어를 추가하세요.')
            suffix = Path(filename).suffix.lower()
            if suffix not in MEDIA or not data:
                raise H3Error('그림·영상·소리 파일을 선택하세요.')
            relative = 'assets/' + uuid.uuid4().hex + suffix
            (self.directory(name) / 'composition' / relative).write_bytes(data)
            p.setdefault('assetNames', {})[relative] = Path(filename).name
            self.save(p)
            return self.get(name)

    def export(self, name):
        with self.lock:
            p = self.load(name)
            if name in self.active:
                raise H3Error('렌더링을 중지한 뒤 프로젝트를 묶으세요.')
            directory = self.directory(name)
            target = directory / 'exports' / ('project-' + uuid.uuid4().hex + '.zip')
            target.parent.mkdir(exist_ok=True)
            with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(directory / 'project.json', 'h3-project.json')
                for file in (directory / 'composition').rglob('*'):
                    if file.is_file() and not file.is_symlink() and not any(part in ('.hf-segments', 'renders', '.hyperframes') for part in file.parts):
                        archive.write(file, str(file.relative_to(directory / 'composition')))
                archive.write(TOOLS / 'HYPERFRAMES-LICENSE', 'HYPERFRAMES-LICENSE')
            return dict(url=self.app.file_url(str(target)))

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass

    def stop_preview(self, name):
        item = self.children.pop(name, None)
        if item:
            self.terminate(item['process'])
            item['process'].stdout.close()
            item['log'].close()

    def ensure_preview(self, name):
        with self.lock:
            self.load(name)
            item = self.children.get(name)
            if item and item['process'].poll() is None:
                return item['port']
            self.stop_preview(name)
            node, _ = self.runtime()
            directory = self.directory(name)
            log = (directory / 'studio.log').open('ab')
            preview_env = {**self.env(), 'HF_SEGMENTED_CAPTURE': 'false'}
            process = subprocess.Popen([str(node), str(TOOLS / 'studio-server.mjs'), str((directory / 'composition').resolve()), str((directory / 'studio-history').resolve())],
                                       stdout=subprocess.PIPE, stderr=log, env=preview_env, start_new_session=True)
            lines = queue.Queue()
            def read():
                for line in iter(process.stdout.readline, b''):
                    try:
                        value = json.loads(line)
                        if 'port' in value:
                            lines.put(value['port'])
                    except ValueError:
                        continue
            threading.Thread(target=read, daemon=True).start()
            try:
                port = lines.get(timeout=35)
            except queue.Empty:
                self.terminate(process)
                log.close()
                raise H3Error('HyperFrames 편집기를 시작하지 못했습니다. studio.log를 확인하세요.') from None
            self.children[name] = dict(port=port, process=process, log=log)
            return port

    def render(self, name, body, resume=False):
        with self.lock:
            p = self.load(name)
            if name in self.active:
                raise H3Error('이미 렌더링 중입니다.')
            node, cli = self.runtime()
            if resume and p.get('task', {}).get('status') not in ('paused', 'error'):
                raise H3Error('중지되었거나 실패한 렌더링만 이어 실행할 수 있습니다.')
            options = p.get('task', {}).get('options', {}) if resume else body
            format_ = options.get('format', 'mp4')
            quality = options.get('quality', 'draft')
            if format_ not in ('mp4', 'webm', 'mov', 'gif') or quality not in ('draft', 'standard', 'high'):
                raise H3Error('출력 형식과 품질을 선택하세요.')
            fps = int(finite(options.get('fps', p['fps']), 1, 120, '출력 프레임 속도'))
            resolution = options.get('resolution', 'native')
            if resolution not in ('native', '4k'):
                raise H3Error('원본 크기 또는 4K 출력을 선택하세요.')
            options = dict(format=format_, quality=quality, fps=fps, resolution=resolution)
            self.snapshot(p, '렌더링 전 자동 저장')
            task_id = uuid.uuid4().hex
            p['task'] = dict(id=task_id, status='queued', progress=0, message='렌더링 대기 중', options=options, started=time.time())
            self.save(p)
            self.active.add(name)
            self.pauses[name] = threading.Event()
            self.executor.submit(self._render, name, task_id, node, cli)
            return self.get(name)

    def _render(self, name, task_id, node, cli):
        try:
            with self.lock:
                p = self.load(name)
                options = p['task']['options']
                directory = self.directory(name).resolve()
                destination = directory / 'exports' / (task_id + '.' + options['format'])
                destination.parent.mkdir(exist_ok=True)
                p['task'].update(status='running', message='HyperFrames로 프레임을 조판하고 있습니다.')
                self.save(p)
                args = [str(node), str(cli), 'render', str(directory / 'composition'), '--output', str(destination),
                        '--format', options['format'], '--quality', options['quality'], '--fps', str(options['fps']),
                        '--workers', '1', '--no-browser-gpu', '--low-memory-mode', '--no-best-effort', '--resume', '--keep-segments']
                if options.get('resolution') == '4k':
                    args += ['--resolution', '4k']
                log_file = directory / ('render-' + task_id + '.log')
                if self.pauses[name].is_set():
                    p['task'].update(status='paused', message='렌더링을 시작하기 전에 중지했습니다.')
                    self.save(p)
                    return
                render_env = self.env()
                # Upstream 0.8.158 uses MP4 segment containers, incompatible with
                # alpha-preserving ProRes MOV. Keep that renderer's normal path.
                if options['format'] != 'mp4':
                    render_env['HF_SEGMENTED_CAPTURE'] = 'false'
                process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=render_env, start_new_session=True)
                self.processes[name] = process
            with log_file.open('wb') as log:
                for line in iter(process.stdout.readline, b''):
                    log.write(line)
                    log.flush()
                    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line.decode(errors='replace')).strip()
                    if text:
                        with self.lock:
                            p = self.load(name)
                            p['task']['message'] = text[-350:]
                            m = re.search(r'(\d+(?:\.\d+)?)%', text)
                            if m:
                                p['task']['progress'] = min(99, float(m[1]))
                            if text.startswith('@hf-progress '):
                                try:
                                    progress = json.loads(text[len('@hf-progress '):])
                                    p['task']['progress'] = min(99, float(progress['pct']))
                                    p['task']['message'] = str(progress.get('stage', '렌더링 중'))
                                except (ValueError, KeyError, TypeError):
                                    pass
                            self.save(p)
            code = process.wait()
            with self.lock:
                p = self.load(name)
                if self.pauses[name].is_set():
                    p['task'].update(status='paused', message='중지했습니다. 저장된 구간은 이어 렌더링할 때 엔진이 검증해 재사용합니다.')
                elif code != 0 or not destination.is_file():
                    p['task'].update(status='error', message='렌더링 실패 · 로그를 확인하고 수정 후 이어 실행하세요.', error=log_file.read_text(errors='replace')[-8000:])
                else:
                    if options['format'] in ('mp4', 'webm', 'mov'):
                        info = probe(destination)
                        if not info['video'] or info['duration'] <= 0:
                            raise H3Error('재생 가능한 출력 영상을 확인하지 못했습니다.')
                    p['task'].update(status='done', progress=100, message='영상 출력이 완료되었습니다.', output=str(destination.relative_to(directory)))
                    p.setdefault('completedOutputs', []).append(str(destination.relative_to(directory)))
                self.save(p)
        except Exception as error:
            with self.lock:
                p = self.load(name)
                p['task'].update(status='error', message=str(error), error=str(error))
                self.save(p)
        finally:
            with self.lock:
                process = self.processes.pop(name, None)
                if process:
                    process.stdout.close()
                self.active.discard(name)

    def pause(self, name):
        with self.lock:
            p = self.load(name)
            if name not in self.active:
                return self.get(name)
            self.pauses[name].set()
            p['task'].update(status='pausing', message='진행 중인 렌더링을 멈추고 있습니다.')
            self.save(p)
            process = self.processes.get(name)
        if process:
            self.terminate(process)
        return self.get(name)

    def close(self):
        self.closed = True
        for name in list(self.active):
            self.pause(name)
        self.executor.shutdown(wait=True, cancel_futures=False)
        for name in list(self.children):
            self.stop_preview(name)
