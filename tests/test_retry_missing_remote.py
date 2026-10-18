"""A restarted model server must not trap resume on a deleted remote ID."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from h3video.client import H3Client, H3Error
from h3video.jobs import JobStore, Worker, new_job

class MissingRemoteRetryTest(unittest.TestCase):
    def test_missing_status_or_content_is_resubmitted_but_server_errors_keep_remote_id(self):
        for code, where in [(404, 'status'), (410, 'content'), (503, 'status')]:
            with self.subTest(code=code, where=where), tempfile.TemporaryDirectory() as temporary:
                state = dict(submitted=[], failing=True)
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args): pass
                    def send(self, status, data):
                        payload = data if isinstance(data, bytes) else json.dumps(data).encode()
                        self.send_response(status); self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
                    def do_POST(self):
                        state['submitted'].append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                        self.send(200, {'id':'remote-'+str(len(state['submitted']))})
                    def do_GET(self):
                        video_id = self.path.split('/')[3]
                        content = self.path.endswith('/content')
                        if video_id == 'remote-2' and state['failing'] and content == (where == 'content'):
                            return self.send(code, {'error':'request unavailable'})
                        self.send(200, (video_id.encode()*300) if content else {'status':'completed','progress':1})
                server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    store = JobStore(Path(temporary)); job = new_job('two saved scenes', seconds=20, scene_seconds=10); job.max_scene=10; store.add(job)
                    client = H3Client('http://127.0.0.1:'+str(server.server_address[1])); worker=Worker(store,client,inbox_dir=None,poll=.01)
                    def frame(video, output): output.write_bytes(b'frame'); return output
                    def join(parts, output): output.write_bytes(b''.join(p.read_bytes() for p in parts)); return output
                    with patch('h3video.jobs.extract_last_frame',frame), patch('h3video.jobs.concat_videos',join):
                        with self.assertRaises(H3Error) as failed: worker.process(job)
                        self.assertEqual(failed.exception.http_status, code)
                        self.assertEqual(job.scenes[1].status, 'failed' if code in (404,410) else 'queued')
                        job.status='failed'; store.save(job)
                        original=Path(job.scenes[0].output); data=original.read_bytes(); mtime=original.stat().st_mtime_ns
                        worker.store=JobStore(Path(temporary)); job=worker.store.get(job.id); state['failing']=False
                        worker.resume(job.id); worker.process(job)
                        self.assertEqual(job.status,'completed'); self.assertEqual(original.read_bytes(),data); self.assertEqual(original.stat().st_mtime_ns,mtime)
                        self.assertEqual(len(state['submitted']),3 if code in (404,410) else 2)
                        self.assertIsNone(job.scenes[1].error)
                        if code in (404,410): self.assertEqual(state['submitted'][1]['seed'],state['submitted'][2]['seed'])
                finally:
                    server.shutdown(); server.server_close()
