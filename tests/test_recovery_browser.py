import os,subprocess,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from h3video.web import App,make_handler
from h3video.jobs import Worker,new_job,plan_job

class RecoveryBrowserTest(unittest.TestCase):
 def test_saved_scene_edit_restore_pause_in_browser(self):
  with tempfile.TemporaryDirectory() as temporary,patch.object(Worker,'start'):
   root=Path(temporary);app=App('http://127.0.0.1:9','http://127.0.0.1:9',root,None)
   app.client.healthy=app.ref_client.healthy=lambda:True
   job=new_job('Original browser prompt',seconds=35);job.scenes=plan_job(job);job.status='paused';app.store.add(job)
   first=root/job.id/'scene01.mp4';first.write_bytes(b'preserve-original');job.scenes[0].output=str(first);job.scenes[0].status='completed';app.store.save(job)
   server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app,{'*'}));threading.Thread(target=server.serve_forever,daemon=True).start()
   try:
    script=Path(__file__).parent/'e2e/recovery_ui.cjs';base=f'http://127.0.0.1:{server.server_address[1]}'
    response=subprocess.run(['node',str(script),base,job.id],capture_output=True,text=True,timeout=120,env={**os.environ,'H3_PLAYWRIGHT':'/home/kms/dev/crossword/node_modules/playwright','CHROME':'/usr/bin/google-chrome-stable'})
    self.assertEqual(response.returncode,0,response.stdout+response.stderr);self.assertEqual(first.read_bytes(),b'preserve-original');print(response.stdout)
   finally:server.shutdown();server.server_close()
