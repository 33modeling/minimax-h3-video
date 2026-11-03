"""Bounded frame lanes: one persistent editor per endpoint, one upscale per GPU."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


def endpoint_lanes(provider):
    prefix = {'qwen-image':'QWEN_IMAGE','qwen-image-turbo':'QWEN_IMAGE_TURBO',
              'qwen-image-quantized':'QWEN_IMAGE_QUANTIZED'}[provider]
    port = {'qwen-image':8091,'qwen-image-turbo':8093,'qwen-image-quantized':8094}[provider]
    endpoints = list(dict.fromkeys(x.strip().rstrip('/') for x in
        os.environ.get(prefix+'_BASE_URL',f'http://127.0.0.1:{port}').split(',') if x.strip()))
    if not endpoints:
        endpoints = [f'http://127.0.0.1:{port}']
    from urllib.parse import urlsplit
    if any(urlsplit(url).scheme not in ('http','https') or not urlsplit(url).hostname for url in endpoints):
        raise ValueError('프레임 편집 서버 주소는 http 또는 https여야 합니다.')
    return prefix, endpoints


def upscale_devices():
    values = os.environ.get('STUDIO_UPSCALER_GPUS',os.environ.get('STUDIO_UPSCALER_GPU','0'))
    devices = list(dict.fromkeys(x.strip() for x in values.split(',') if x.strip()))
    if not devices or any(not x.isdecimal() and x!='-1' for x in devices):
        raise ValueError('STUDIO_UPSCALER_GPUS는 GPU 번호 목록(예: 0,1)입니다.')
    return devices


class RetouchWorker:
    """JSON-lines child process; killing a local worker never kills an engine/service."""
    def __init__(self, command, env, log, check):
        self.command, self.env, self.log, self.check = command, env, Path(log), check
        self.child = None

    def _start(self):
        self.stderr = self.log.open('w')
        try:
            self.child = subprocess.Popen([str(x) for x in self.command], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, env=self.env)
        except BaseException:
            self.stderr.close()
            raise
        self.responses = queue.Queue()
        def read():
            try:
                for line in self.child.stdout:
                    self.responses.put(line)
            finally:
                self.responses.put(None)
        self.reader = threading.Thread(target=read,daemon=True,name='frame-worker-output')
        self.reader.start()

    def edit(self, payload):
        self.check()
        if self.child is None:
            self._start()
        try:
            self.child.stdin.write((json.dumps(payload)+'\n').encode());self.child.stdin.flush()
        except (BrokenPipeError,OSError) as error:
            raise RuntimeError('프레임 편집 worker 종료: '+self.log.read_text(errors='replace')[-1500:]) from error
        while True:
            self.check()
            try:line=self.responses.get(timeout=.1)
            except queue.Empty:continue
            if line is None:
                raise RuntimeError('프레임 편집 worker 종료: '+self.log.read_text(errors='replace')[-1500:])
            result=json.loads(line)
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or '프레임 보정 실패')
            return result.get('result')

    def close(self):
        if self.child is None:
            return
        try:
            try:self.child.stdin.close()
            except OSError:pass
            try:self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:self.child.kill();self.child.wait()
        finally:
            self.reader.join(timeout=2)
            self.child.stdout.close();self.stderr.close()
            self.child = None
