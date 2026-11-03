"""Measured counters, clocks, retries and actual FFmpeg frame resume. No servers/models."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from h3video.progress import task_metrics, generation_metrics, generation_snapshot
from h3video.web import App
from h3video.studio import probe
from h3video.dserver import Server

class MeasuredProgressTest(unittest.TestCase):
    def test_current_frame_is_not_completed_and_cached_frames_do_not_inflate_speed(self):
        task=dict(status='running',runStartedAt=100,activeSeconds=8,
                  progressInfo=dict(phase='upscale',startedAt=110),
                  frameProgress=dict(total=10,completed=6,cached=4,current=7,
                      sessionStartedAt=100,lastCompletedAt=120))
        metrics=task_metrics(task,now=125)
        self.assertEqual(metrics['frames']['completed'],6)
        self.assertEqual(metrics['fraction'],.6)
        self.assertEqual(metrics['ratePerSecond'],.1)
        self.assertEqual(metrics['etaSeconds'],40)
        self.assertEqual(metrics['elapsedSeconds'],33)
        self.assertNotIn('fraction',task['progressInfo'],'views must not mutate stored counters')
        stale=task_metrics(task,now=200)
        self.assertTrue(stale['stalled']);self.assertIsNone(stale['etaSeconds'])

    def test_unknown_warmup_assembly_pause_and_done(self):
        task=dict(status='running',progressInfo=dict(phase='extract'))
        self.assertIsNone(task_metrics(task,now=10)['fraction'])
        task.update(runStartedAt=100,activeSeconds=8,frameProgress=dict(total=4,completed=1,cached=0,sessionStartedAt=100,lastCompletedAt=110))
        task['progressInfo']=dict(phase='retouch',startedAt=100)
        self.assertIsNone(task_metrics(task,now=111)['etaSeconds'])
        task['frameProgress']['completed']=4
        for phase in ['upscale','assemble','inspect']:
            task['progressInfo']['phase']=phase
            self.assertIsNone(task_metrics(task,now=120)['fraction'])
        task.update(status='paused',activeSeconds=28,stoppedAt=120)
        paused=task_metrics(task,now=999)
        self.assertEqual(paused['elapsedSeconds'],28)
        self.assertEqual(paused['phaseElapsedSeconds'],20)
        self.assertIsNone(paused['etaSeconds'])
        task['status']='done'
        self.assertEqual(task_metrics(task,now=999)['fraction'],1)

    def test_generation_uses_observed_step_deltas_and_phase_clocks(self):
        engine=SimpleNamespace(_steps_done=4)
        job=dict(plan=dict(steps=50,num_frames=192),status='in_progress',stage='디노이징',stageStartedAt=90,started_at=80)
        job['metrics']=generation_metrics(engine,job,100)
        self.assertIsNone(job['metrics']['etaSeconds'])
        engine._steps_done=6
        job['metrics']=generation_metrics(engine,job,120)
        self.assertEqual(job['metrics']['ratePerSecond'],.1)
        self.assertEqual(job['metrics']['etaSeconds'],430)
        live=generation_snapshot(job,130)
        self.assertEqual(live['phaseElapsedSeconds'],40)
        self.assertEqual(live['elapsedSeconds'],50)
        stale=generation_snapshot(job,190)
        self.assertTrue(stale['stalled']);self.assertIsNone(stale['etaSeconds'])
        job['stage']='영상 저장';engine._steps_done=49
        self.assertIsNone(generation_metrics(engine,job,140)['fraction'])
        job.update(status='completed',finished_at=150)
        self.assertEqual(generation_snapshot(job,999)['fraction'],1)

    def test_retry_clears_previous_step_rate_and_records_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=Server.__new__(Server);server.out_dir=Path(tmp);server.save=lambda job:None
            seen=[]
            class Engine:
                mode='sharded';_steps_done=0
                def run(self,plan,out,callback):
                    self.on_stage('생성 중');self._steps_done=4;callback(.08)
                    seen.append(copy.deepcopy(job['metrics']))
                    if len(seen)==1:raise RuntimeError('CUDA out of memory')
                    return 'ok'
            server.engine=Engine();job=dict(id='fixture',plan=dict(steps=50,short_edge=768))
            with patch('h3video.memory.release_request_memory'),patch('traceback.print_exc'):
                self.assertEqual(server.run_with_recovery(job,Path(tmp)/'out.mp4'),'ok')
            self.assertEqual(seen[1]['retry'],1)
            self.assertIsNone(seen[1]['ratePerSecond'])
            self.assertEqual([p['stage'] for p in job['phaseHistory']],['생성 중','메모리 복구 · 576px로 재시도 1/2','생성 중'])
            self.assertIn('endedAt',job['phaseHistory'][0])

class FramePipelineProgressTest(unittest.TestCase):
    def test_interrupted_saved_job_freezes_at_last_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=App('http://unused.invalid','http://unused.invalid',Path(tmp),None)
            try:
                p=app.studio.create({})
                p['task']=dict(status='running',operation='upscale',runStartedAt=100,activeSeconds=20,
                               progressInfo=dict(phase='upscale',startedAt=110,updatedAt=150))
                app.studio.save(p)
                view=app.studio.get(p['id'])
                self.assertEqual(view['task']['status'],'paused')
                self.assertEqual(view['task']['metrics']['elapsedSeconds'],70)
                self.assertEqual(view['task']['metrics']['phaseElapsedSeconds'],40)
                self.assertTrue(view['task']['metrics']['clockIncomplete'])
            finally:app.studio.close()

    def test_actual_four_frames_pause_resume_atomic_counts_audio_fps_and_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=96x64:r=4',
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True)
            app=App('http://unused.invalid','http://unused.invalid',root/'outputs',None,poll=.01)
            studio=app.studio
            try:
                p=studio.create({'clips':[{'id':'frame-test','seconds':1}]})
                p=studio.upload(p['id'],{'clip':'frame-test','kind':'video'},'source.mp4',video.read_bytes())
                original=video.read_bytes();original_id=p['clips'][0]['selected']
                home=root/'upscaler';home.mkdir();(home/'realesrgan-ncnn-vulkan').touch()
                command=studio.command;updates=[];frame_count=0
                def fake_ai(project,args,*rest,**kwargs):
                    nonlocal frame_count
                    if Path(args[0]).name!='realesrgan-ncnn-vulkan':return command(project,args,*rest,**kwargs)
                    frame_count+=1
                    updates.append(copy.deepcopy(studio.view(project)['task']['metrics']))
                    source=args[args.index('-i')+1];dest=args[args.index('-o')+1]
                    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vf','scale=iw*2:ih*2',str(dest)],check=True)
                    if frame_count==1:studio.pause_events[project['id']].set()
                    return ''
                studio.command=fake_ai
                saved_progress=studio.frame_progress
                def track(project,*args,**kwargs):
                    saved_progress(project,*args,**kwargs)
                    updates.append(copy.deepcopy(studio.view(project)['task']['metrics']))
                studio.frame_progress=track
                def wait():
                    import time
                    deadline=time.monotonic()+30
                    while time.monotonic()<deadline:
                        current=studio.get(p['id'])
                        if not current['busy']:return current
                        time.sleep(.01)
                    self.fail('fixture timed out')
                with patch.dict(os.environ,{'STUDIO_UPSCALER_DIR':str(home)}):
                    studio.start(p['id'],'upscale',{'clip':'frame-test','scale':2})
                    paused=wait()
                    self.assertEqual(paused['task']['status'],'paused',paused['task'])
                    self.assertEqual(paused['task']['metrics']['frames']['completed'],1)
                    disk=json.loads((studio.directory(p['id'])/'project.json').read_text())
                    self.assertEqual(disk['task']['frameProgress']['completed'],1)
                    studio.start(p['id'],'resume');done=wait()
                self.assertEqual(done['task']['status'],'done',done['task'])
                self.assertEqual(frame_count,4,'the saved first frame must be reused')
                self.assertEqual(done['task']['metrics']['frames']['cached'],1)
                self.assertEqual(done['task']['metrics']['frames']['completed'],4)
                self.assertEqual(updates[0]['frames']['completed'],0)
                assembly=next(x for x in updates if x['phase']=='assemble')
                self.assertEqual(assembly['frames']['completed'],4);self.assertIsNone(assembly['fraction'])
                inspection=next(x for x in updates if x['phase']=='inspect');self.assertIsNone(inspection['fraction'])
                current=studio.variant(done['clips'][0]);info=probe(studio.file(p['id'],current['file']))
                self.assertTrue(info['audio']);self.assertEqual(info['fps'],4);self.assertEqual((info['width'],info['height']),(192,128))
                old=next(x for x in done['clips'][0]['variants'] if x['id']==original_id)
                self.assertEqual(original,studio.file(p['id'],old['file']).read_bytes())
            finally:studio.close()

if __name__=='__main__':unittest.main()
