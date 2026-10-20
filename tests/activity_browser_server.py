"""Real web/worker/FFmpeg; only GPU inference is a controlled local stub."""
import json
from pathlib import Path
import signal
import sys
import threading
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import mock_server
from h3video.web import App, make_handler
from h3video.jobs import new_job

directory = Path(sys.argv[1]); directory.mkdir(exist_ok=True)
release = threading.Event(); state = mock_server.State()
ModelHandler = mock_server.make_handler(state, steps=2)
class Model(ModelHandler):
    def do_GET(self):
        if '/videos/' in self.path and not self.path.endswith('/content'):
            release.wait(90)
        return super().do_GET()
model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
threading.Thread(target=model.serve_forever, daemon=True).start()
endpoint = f'http://127.0.0.1:{model.server_address[1]}'
app = App(endpoint, endpoint, directory / 'outputs', None, poll=.01)
complete = new_job(prompt='Completed fixture', seconds=4, aspect_ratio='16:9', seed=1)
media = app.store.root / complete.id / 'completed.mp4'; media.parent.mkdir(parents=True, exist_ok=True); media.write_bytes(mock_server.fake_mp4())
complete.status = 'completed'; complete.output = str(media); app.store.add(complete)
paused = new_job(prompt='Paused fixture', seconds=4, aspect_ratio='16:9', seed=2); paused.status = 'paused'; app.store.add(paused)
active = new_job(prompt='Current video', seconds=4, aspect_ratio='16:9', seed=3); app.worker.enqueue(active)
queued = new_job(prompt='Next video', seconds=4, aspect_ratio='16:9', seed=4); app.worker.enqueue(queued)
Handler = make_handler(app, {'*'})
class Web(Handler):
    def do_POST(self):
        if self.path == '/test-release':
            release.set(); return self._json({'ok': True})
        super().do_POST()
server = ThreadingHTTPServer(('127.0.0.1', 0), Web)
print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_address[1]}', complete=complete.id, paused=paused.id, active=active.id, queued=queued.id)), flush=True)
signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    release.set(); app.motion.close(); app.studio.close(); server.server_close(); model.shutdown(); model.server_close()
