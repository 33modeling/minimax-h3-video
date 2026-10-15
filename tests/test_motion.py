"""Real pinned Studio, CPU Chromium/FFmpeg and persistent maker integration."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

from h3video.client import H3Error
from h3video.motion import TOOLS, MotionStudio
from h3video.studio import probe
from h3video.web import App, make_handler


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TOOLS / 'node_modules/hyperframes/bin/hyperframes.mjs').exists():
            raise unittest.SkipTest('npm run install:hyperframes is required')
        cls.temp = tempfile.TemporaryDirectory(prefix='h3-motion-test-')
        cls.directory = Path(cls.temp.name)
        cls.app = App('http://127.0.0.1:9', 'http://127.0.0.1:9', cls.directory / 'outputs', None)
        cls.motion = cls.app.motion
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(cls.app, ['https://33modeling.pages.dev']))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.video = cls.directory / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=12', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.motion.close()
        cls.app.studio.close()
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, path, method='GET', data=None, headers=None):
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def create(self, **kw):
        return self.motion.create({'title': '검증 프로젝트', 'scenes': [{'title': '한글 자막', 'text': '원본과 수정 내용을 보관합니다', 'seconds': 1}], **kw})

    def wait(self, name, timeout=180):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            p = self.motion.get(name)
            if name not in self.motion.active:
                return p
            time.sleep(.1)
        self.fail('render did not finish within the timeout')

    def test_save_restore_export_and_restart_preserve_media_and_completed_outputs(self):
        p = self.create()
        original = p['html']
        changed = original.replace('한글 자막', '수정한 자막')
        p = self.motion.edit(p['id'], {'html': changed})
        self.assertIn('수정한 자막', p['html'])
        p = self.motion.restore(p['id'], p['history'][0]['id'])
        self.assertEqual(p['html'], original)
        p = self.motion.upload(p['id'], '원본.mp4', self.video.read_bytes())
        self.assertEqual(p['assets'][0]['name'], '원본.mp4')
        url = self.motion.export(p['id'])['url']
        status, content, _ = self.request(url)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIn('index.html', archive.namelist())
            self.assertIn('HYPERFRAMES-LICENSE', archive.namelist())
            self.assertIn(p['assets'][0]['file'], archive.namelist())
        reopened = MotionStudio(self.app)
        self.assertEqual(reopened.get(p['id'])['html'], original)
        reopened.close()

    def test_validation_origin_paths_and_conflicting_render(self):
        p = self.create()
        for options in ({'fps': float('nan')}, {'scenes': []}, {'ratio': '../../etc'}, {'html': 'invalid'}):
            with self.assertRaises(H3Error):
                self.motion.edit(p['id'], options)
        with self.assertRaises(H3Error):
            self.motion.file(p['id'], '../../../../etc/passwd')
        with self.assertRaises(H3Error):
            self.motion.render(p['id'], {}, resume=True)
        status, _, _ = self.request('/api/motion/projects', 'POST', b'{}', {'Origin': 'https://untrusted.example', 'Content-Type': 'application/json'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('/api/motion/projects', 'POST', b'[]', {'Content-Type': 'application/json'})
        self.assertEqual(status, 400)
        self.motion.active.add(p['id'])
        try:
            with self.assertRaises(H3Error): self.motion.render(p['id'], {})
            with self.assertRaises(H3Error): self.motion.edit(p['id'], {'title': 'busy'})
            status, _, _ = self.request(p['proxy'] + '/api/projects/h3-motion/files/index.html', 'PUT', b'x')
            self.assertEqual(status, 409)
        finally:
            self.motion.active.discard(p['id'])

    def test_real_studio_two_project_isolation_conditional_writes_and_range(self):
        first = self.create()
        second = self.create(title='둘째 프로젝트')
        for p in (first, second):
            status, body, _ = self.request(p['studioUrl'])
            self.assertEqual(status, 200)
            self.assertIn(p['proxy'].encode(), body)
            status, body, _ = self.request(p['proxy'] + '/api/projects')
            self.assertEqual(status, 200)
            self.assertIn(b'h3-motion', body)
        path = first['proxy'] + '/api/projects/h3-motion/files/index.html'
        status, body, _ = self.request(path, 'PUT', b'ignored')
        self.assertEqual(status, 428)
        version = json.loads(body)['currentVersion']
        changed = first['html'].replace('한글 자막', 'Studio에서 저장')
        status, body, _ = self.request(path, 'PUT', changed.encode(), {'If-Match': version, 'Content-Type': 'text/html'})
        self.assertEqual(status, 200, body)
        self.assertIn('Studio에서 저장', self.motion.get(first['id'])['html'])
        self.assertNotIn('Studio에서 저장', self.motion.get(second['id'])['html'])
        status, _, _ = self.request(path, 'PUT', b'stale', {'If-Match': version})
        self.assertEqual(status, 409)
        p = self.motion.upload(first['id'], self.video.name, self.video.read_bytes())
        status, content, headers = self.request(p['assets'][0]['url'], headers={'Range': 'bytes=0-31'})
        self.assertEqual(status, 206)
        self.assertEqual(len(content), 32)
        self.assertIn('bytes 0-31', headers['Content-Range'])
        status, _, _ = self.request(first['proxy'] + '/api/desktop/open', 'POST', b'{}')
        self.assertEqual(status, 403)

    def test_import_real_video_audio_and_render_keeps_original(self):
        p = self.app.studio.create({'title': '원본 편집', 'clips': [{'id': 'one', 'label': '첫 장면', 'text': '나레이션', 'seconds': 1}]})
        p = self.app.studio.upload(p['id'], {'clip': 'one', 'kind': 'video'}, self.video.name, self.video.read_bytes())
        clips = copy.deepcopy(p['clips'])
        clips[0].update(seconds=1, trimIn=.25)
        p = self.app.studio.update(p['id'], {'clips': clips})
        original = self.app.studio.file(p['id'], p['clips'][0]['variants'][0]['file'])
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        imported = self.motion.create({'source': {'kind': 'edit', 'id': p['id']}})
        name = imported['id']
        self.assertEqual(imported['scenes'][0]['kind'], 'video')
        self.assertIn('data-media-start="0.25"', imported['html'])
        self.motion.render(name, {'fps': 12})
        done = self.wait(name)
        self.assertEqual(done['task']['status'], 'done', done['task'])
        output = self.motion.file(name, done['task']['output'])
        info = probe(output)
        self.assertTrue(info['video'])
        self.assertTrue(info['audio'])
        self.assertAlmostEqual(info['duration'], 1, delta=.3)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), digest)
        self.assertEqual(len(done['outputs']), 1)
        self.motion.restore(name, done['history'][0]['id'])
        self.assertTrue(output.is_file())
        self.assertEqual(len(self.motion.get(name)['outputs']), 1)

    def test_pause_edit_resume_and_unfinished_output_hidden(self):
        p = self.create()
        self.motion.render(p['id'], {'fps': 12})
        self.motion.pause(p['id'])
        paused = self.wait(p['id'])
        self.assertEqual(paused['task']['status'], 'paused')
        self.assertEqual(paused['outputs'], [])
        p = self.motion.edit(p['id'], {'title': '중지 후 수정', 'html': p['html'].replace('한글 자막', '이어 만든 영상')})
        self.motion.render(p['id'], {}, resume=True)
        done = self.wait(p['id'])
        self.assertEqual(done['task']['status'], 'done', done['task'])
        self.assertEqual(len(done['outputs']), 1)
        self.assertIn('이어 만든 영상', done['html'])

    def test_generated_templates_pass_upstream_lint(self):
        node, cli = self.motion.runtime()
        for template in self.motion.capabilities()['templates']:
            p = self.create(template=template['id'])
            result = subprocess.run([str(node), str(cli), 'lint', str(self.motion.directory(p['id']) / 'composition'), '--json'], env=self.motion.env(), capture_output=True, text=True)
            report = json.loads(result.stdout)
            self.assertEqual(report['errorCount'], 0, report)
            self.assertTrue(report['ok'], report)

    def test_completed_segments_are_actually_reused_after_pause(self):
        p = self.create(scenes=[{'title': '구간 보관 검증', 'seconds': 30}])
        name = p['id']
        self.motion.render(name, {'fps': 24})
        cache = self.motion.directory(name) / 'composition/renders/.hf-segments'
        segment = None
        until = time.monotonic() + 60
        while time.monotonic() < until and name in self.motion.active:
            for manifest in cache.glob('*/segments.json'):
                completed = json.loads(manifest.read_text())['completed']
                if completed:
                    segment = Path(completed[0]['path'])
                    break
            if segment:
                break
            time.sleep(.02)
        self.assertIsNotNone(segment, 'the actual renderer must produce a reusable checkpoint')
        modified = segment.stat().st_mtime_ns
        self.motion.pause(name)
        self.assertEqual(self.wait(name)['task']['status'], 'paused')
        self.motion.render(name, {}, resume=True)
        done = self.wait(name)
        self.assertEqual(done['task']['status'], 'done', done['task'])
        self.assertEqual(segment.stat().st_mtime_ns, modified, 'a completed segment must not be rendered again')

    def test_webm_mov_gif_outputs_are_real_files(self):
        for format_ in ('webm', 'mov', 'gif'):
            p = self.create()
            self.motion.render(p['id'], {'format': format_, 'fps': 6})
            done = self.wait(p['id'])
            self.assertEqual(done['task']['status'], 'done', done['task'])
            output = self.motion.file(p['id'], done['task']['output'])
            self.assertGreater(output.stat().st_size, 1000)
            info = probe(output)
            self.assertTrue(info['video'])
            self.assertGreater(info['duration'], 0)

    def test_native_studio_export_and_4k_render(self):
        p = self.create(scenes=[{'title': '선명한 글자', 'seconds': .5}])
        status, body, _ = self.request(p['proxy'] + '/api/projects/h3-motion/render', 'POST',
                                       json.dumps({'fps': 2, 'quality': 'draft', 'format': 'mp4'}).encode(),
                                       {'Content-Type': 'application/json'})
        self.assertEqual(status, 200, body)
        job = json.loads(body)['jobId']
        file = self.motion.directory(p['id']) / 'composition/renders' / (job + '.mp4')
        until = time.monotonic() + 120
        while not self.motion.native_complete(file) and time.monotonic() < until:
            sidecar = file.with_suffix('.meta.json')
            if sidecar.exists():
                self.assertNotEqual(json.loads(sidecar.read_text()).get('status'), 'failed')
            time.sleep(.1)
        self.assertTrue(self.motion.native_complete(file), 'native Studio Export must complete')
        self.assertTrue(probe(file)['video'])
        self.assertTrue(self.motion.get(p['id'])['outputs'])
        self.motion.render(p['id'], {'fps': 2, 'resolution': '4k'})
        done = self.wait(p['id'])
        self.assertEqual(done['task']['status'], 'done', done['task'])
        info = probe(self.motion.file(p['id'], done['task']['output']))
        self.assertEqual((info['width'], info['height']), (3840, 2160))


if __name__ == '__main__':
    unittest.main()
