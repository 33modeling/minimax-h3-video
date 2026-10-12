import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from h3video.jobs import JobStore, Worker, new_job
from h3video.recovery import edit_job, edit_story, restore_story, restore_job
from h3video import storyrun as SR, story as ST

class RecoveryTest(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=JobStore(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_pause_restart_edit_and_resume_preserve_native_scene_outputs(self):
  job=new_job('Original prompt',seconds=35);job.max_scene=15
  worker=Worker(self.store,SimpleNamespace(),inbox_dir=None)
  submitted=[]
  class Client:
   def submit(_self,request):submitted.append(request.prompt);return str(len(submitted))
   def wait(_self,*args,**kwargs):return {}
   def download(_self,video_id,output):output.write_bytes(('video-'+video_id).encode());worker.pause(job.id) if len(submitted)==1 else None
  worker.client=worker.ref_client=Client();self.store.add(job)
  def frame(video,out):out.write_bytes(b'frame');return out
  def join(parts,out):out.write_bytes(b''.join(p.read_bytes() for p in parts));return out
  with patch('h3video.jobs.extract_last_frame',frame),patch('h3video.jobs.concat_videos',join):
   worker.process(job);self.assertEqual(job.status,'paused');self.assertEqual(len(submitted),1)
   original=Path(job.scenes[0].output).read_bytes();restored=JobStore(self.root);job=restored.get(job.id)
   worker.store=restored;worker.resume(job.id);worker.process(job)
   self.assertEqual(job.status,'completed');self.assertEqual(Path(job.scenes[0].output).read_bytes(),original);self.assertEqual(len(submitted),len(job.scenes))
   old=Path(job.output).read_bytes();edit_job(restored,job.id,{'scene':1,'prompt':'Changed second scene'})
   self.assertEqual(job.scenes[0].status,'completed');self.assertIsNone(job.scenes[1].output)
   worker.resume(job.id);worker.process(job);self.assertIn('Changed second scene',submitted[-len(job.scenes)+1]);self.assertEqual(Path(job.scenes[0].output).read_bytes(),original)
   restore_job(restored,job.id);self.assertEqual(Path(job.output).read_bytes(),old)
 def test_story_partial_edit_and_restore_keeps_other_clips_and_old_job_files(self):
  story=ST.load_story({'clips':[{'prompt':'A','seconds':40},{'prompt':'B','seconds':20}]});directory=SR.new_story_dir(self.root);state=SR.initial_state(story,{});state['paused']=True
  state['clips'][0]['output']=str(self.root/'first.mp4');Path(state['clips'][0]['output']).write_bytes(b'old-video');SR.save_state(directory,state)
  edit_story(directory,self.store,{'clip':'clip-02','prompt':'Edited B','seconds':60,'text':'새 글'})
  saved=SR.load_state(directory);self.assertEqual(saved['clips'][0]['output'],state['clips'][0]['output']);self.assertEqual(saved['clips'][1]['seconds'],60);self.assertEqual(saved['clips'][1]['prompt'],'Edited B')
  restore_story(directory,self.store);old=SR.load_state(directory);self.assertEqual(old['clips'][1]['prompt'],'B');self.assertEqual(Path(old['clips'][0]['output']).read_bytes(),b'old-video')
 def test_frame_100_scenes_keep_full_duration_and_model_requests_remain_supported(self):
  frame={'brief':{'ratio':'9:16'},'board':{'title':'One hour','scenes':[{'title':str(i),'videoPrompt':'Scene '+str(i),'duration':36,'caption':'Caption'} for i in range(100)]}}
  story=ST.load_story(frame);self.assertEqual(len(story.clips),100);self.assertEqual(sum(c.seconds for c in story.clips),3600)
  from h3video.spec import plan_scenes
  for clip in story.clips:self.assertEqual(sum(plan_scenes(clip.seconds)),36);self.assertTrue(all(4<=n<=15 for n in plan_scenes(clip.seconds)))

 def test_http_pause_edit_continue_restore_and_restart(self):
  import json, threading, urllib.request
  from http.server import ThreadingHTTPServer
  from h3video.web import App, make_handler
  from h3video.jobs import plan_job
  with patch.object(Worker,'start'):
   app=App('http://127.0.0.1:9','http://127.0.0.1:9',self.root,None)
  job=new_job('Original prompt',seconds=35);job.scenes=plan_job(job);job.status='pending';original_prompt=job.scenes[1].prompt;app.store.add(job)
  server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));threading.Thread(target=server.serve_forever,daemon=True).start()
  base=f'http://127.0.0.1:{server.server_address[1]}'
  def post(action,body={}):
   request=urllib.request.Request(base+f'/api/jobs/{job.id}/{action}',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
   with urllib.request.urlopen(request) as response:return json.loads(response.read())
  try:
   post('pause');self.assertEqual(job.status,'paused')
   first=app.store.root/job.id/'scene-01.mp4';first.write_bytes(b'completed-first-scene');job.scenes[0].output=str(first);job.scenes[0].status='completed';app.store.save(job)
   post('edit',{'scene':1,'prompt':'Changed through HTTP'});self.assertEqual(job.scenes[1].prompt,'Changed through HTTP');self.assertEqual(first.read_bytes(),b'completed-first-scene')
   post('continue');self.assertEqual(job.status,'pending');self.assertIn(job.id,app.worker.queue)
   post('pause');post('restore');self.assertEqual(job.scenes[1].prompt,original_prompt);self.assertEqual(first.read_bytes(),b'completed-first-scene')
   restored=JobStore(self.root).get(job.id);self.assertEqual(restored.status,'paused');self.assertEqual(restored.scenes[0].status,'completed')
  finally:server.shutdown();server.server_close()
