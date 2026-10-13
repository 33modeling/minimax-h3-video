"""Actual FFmpeg, speech and AI restoration; native generation uses a mock H3."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import mock_server
from h3video.web import App
from h3video.studio import probe, timeline, caption_file
from h3video.client import H3Error


class VideoEditingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.model_state, cls.endpoint = mock_server.start(steps=2)

    @classmethod
    def tearDownClass(cls):
        cls.model.shutdown(); cls.model.server_close()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.app = App(self.endpoint, self.endpoint, self.directory / 'outputs', None, poll=.01)
        self.studio = self.app.studio
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.studio.close)
        self.video = self.directory / 'source.mp4'
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=0x406080:s=96x64:r=4',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','libx264',
                        '-pix_fmt','yuv420p','-c:a','aac',str(self.video)],check=True)

    def create(self, count=1):
        p=self.studio.create({'clips':[{'id':f'scene-{i}','prompt':'a moving landscape','seconds':1} for i in range(count)]})
        for c in p['clips']:
            p=self.studio.upload(p['id'],{'clip':c['id'],'kind':'video'},'source.mp4',self.video.read_bytes())
        p=self.studio.update(p['id'],{'delivery':{'shortEdge':64}})
        return p

    def wait(self, project_id, timeout=120):
        deadline=time.time()+timeout
        while time.time()<deadline:
            p=self.studio.get(project_id)
            if not p['busy']:
                self.assertNotEqual(p.get('task',{}).get('status'),'error',p.get('task'))
                return p
            time.sleep(.05)
        self.fail('Task timed out: '+str(self.studio.get(project_id).get('task')))

    def test_trim_transition_color_multiple_deliveries_and_immutable_originals(self):
        p=self.create(2)
        originals=[self.studio.file(p['id'],c['variants'][0]['file']).read_bytes() for c in p['clips']]
        clips=copy.deepcopy(p['clips'])
        clips.reverse();clips[0].update(trimIn=.25,trimOut=.75,seconds=.5,transition='fade',transitionSeconds=.2)
        clips[0]['corrections']['brightness']=.12
        p=self.studio.update(p['id'],{'clips':clips,'delivery':{'ratios':['16:9','9:16','1:1'],'shortEdge':64},
                                      'captions':[{'start':0,'end':.3,'text':'한글 자막 {안녕}'}]})
        self.assertAlmostEqual(timeline(p)[1],1.3)
        self.studio.start(p['id'],'render')
        p=self.wait(p['id'])
        renders=[o for o in p['outputs'] if o['kind']=='render']
        self.assertEqual(len(renders),3)
        for output in renders:
            info=probe(self.studio.file(p['id'],output['file']))
            self.assertAlmostEqual(info['duration'],1.3,delta=.1)
            self.assertTrue(info['audio'])
            self.assertEqual(min(info['width'],info['height']),64)
        bundle=p['outputs'][-1]
        with zipfile.ZipFile(self.studio.file(p['id'],bundle['file'])) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.mp4')]),3)
            self.assertIn('한글 자막',archive.read('captions.srt').decode())
        for original,c in zip(reversed(originals),p['clips']):
            self.assertEqual(original,self.studio.file(p['id'],c['variants'][0]['file']).read_bytes())

    def test_image_animatic_and_saved_reopen(self):
        image=self.directory/'image.png'
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=yellow:s=96x64','-frames:v','1',str(image)],check=True)
        p=self.studio.create({'title':'그림 콘티','clips':[{'id':'image','seconds':.6,'text':'그림 이야기'}]})
        p=self.studio.upload(p['id'],{'clip':'image','kind':'image'},image.name,image.read_bytes())
        self.studio.start(p['id'],'preview',{'animatic':True})
        p=self.wait(p['id'])
        self.assertEqual(p['outputs'][0]['kind'],'preview')
        self.assertAlmostEqual(probe(self.studio.file(p['id'],p['outputs'][0]['file']))['duration'],.6,delta=.08)
        self.assertEqual(self.studio.get(p['id'])['clips'][0]['id'],'image')

    def test_native_low_resolution_candidates_selection_and_lock(self):
        p=self.create()
        clips=copy.deepcopy(p['clips']);clips[0]['text']='새로 고친 이야기'
        p=self.studio.update(p['id'],{'clips':clips})
        selected=p['clips'][0]['selected']
        p=self.studio.candidates(p['id'],{'clips':['scene-0'],'count':2,'phase':'draft','seed':12})
        jobs=[self.app.store.get(v['job']) for v in p['clips'][0]['pendingCandidates']]
        self.assertTrue(all(j.short_edge==576 and j.steps==20 for j in jobs))
        self.assertTrue(all('<d>[Korean] 새로 고친 이야기</d>' in j.prompt for j in jobs))
        p=self.wait(p['id'])
        self.assertEqual(len(p['clips'][0]['variants']),3)
        self.assertEqual(p['clips'][0]['selected'],selected)
        p=self.studio.select(p['id'],{'clip':'scene-0','variant':p['clips'][0]['variants'][1]['id']})
        self.assertNotEqual(p['clips'][0]['selected'],selected)
        clips=copy.deepcopy(p['clips']);clips[0]['locked']=True
        self.studio.update(p['id'],{'clips':clips})
        with self.assertRaises(H3Error):
            self.studio.candidates(p['id'],{'clips':['scene-0']})

    def test_inspection_reports_real_black_freeze_silence_and_stale_captions(self):
        black=self.directory/'black.mp4'
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=black:s=96x64:r=4',
                        '-t','2','-c:v','libx264','-pix_fmt','yuv420p',str(black)],check=True)
        p=self.studio.create({'clips':[{'id':'black','seconds':2}]})
        p=self.studio.upload(p['id'],{'clip':'black','kind':'video'},black.name,black.read_bytes())
        self.studio.start(p['id'],'inspect');p=self.wait(p['id'])
        self.assertTrue({'black','freeze','silence'}.issubset({e['type'] for e in p['inspection']['events']}),p['inspection'])
        self.assertEqual(p['inspection']['faces'][0]['measuredFaces'],0)
        self.assertFalse(p['inspectionStale'])
        p=self.studio.update(p['id'],{'captions':[{'start':0,'end':1,'text':'검사'}]})
        clips=copy.deepcopy(p['clips']);clips[0]['seconds']=1.5
        p=self.studio.update(p['id'],{'clips':clips})
        self.assertTrue(p['captionsStale'])
        self.assertTrue(p['inspectionStale'])
        self.studio.start(p['id'],'render')
        while self.studio.get(p['id'])['busy']:time.sleep(.05)
        self.assertEqual(self.studio.get(p['id'])['task']['status'],'error')

    def test_real_ai_upscale_correction_checkpoint_resume_audio_and_original_restore(self):
        if not self.studio.capabilities()['aiUpscale']:self.skipTest('Install the local AI upscaler')
        p=self.create()
        clips=copy.deepcopy(p['clips']);clips[0]['corrections']['brightness']=.1
        p=self.studio.update(p['id'],{'clips':clips})
        original=p['clips'][0]['selected']
        original_bytes=self.studio.file(p['id'],p['clips'][0]['variants'][0]['file']).read_bytes()
        command=self.studio.command;count=0
        def pause_after_first_frame(project,args,*other,**kwargs):
            nonlocal count
            response=command(project,args,*other,**kwargs)
            if 'realesrgan-ncnn-vulkan' in str(args[0]):
                count+=1
                if count==1:self.studio.pause_events[project['id']].set()
            return response
        self.studio.command=pause_after_first_frame
        self.studio.start(p['id'],'upscale',{'clip':'scene-0','scale':2})
        p=self.wait(p['id'])
        self.assertEqual(p['task']['status'],'paused')
        self.assertEqual(p['clips'][0]['selected'],original)
        task=p['task']['id']
        self.studio.start(p['id'],'resume');p=self.wait(p['id'])
        self.assertEqual(p['task']['id'],task)
        selected=next(v for v in p['clips'][0]['variants'] if v['id']==p['clips'][0]['selected'])
        self.assertEqual((selected['width'],selected['height']),(192,128))
        self.assertEqual(selected['bakedCorrections']['brightness'],.1)
        self.assertEqual(count,4,'The completed frame must be reused')
        self.assertTrue(selected['audio']);self.assertAlmostEqual(selected['fps'],4)
        self.assertIn('inspection',p)
        self.assertEqual(original_bytes,self.studio.file(p['id'],p['clips'][0]['variants'][0]['file']).read_bytes())
        p=self.studio.select(p['id'],{'clip':'scene-0','variant':original})
        self.assertEqual(p['clips'][0]['selected'],original)

    def test_actual_speech_recognition_and_caption_sidecars(self):
        fixture=Path(os.environ.get('H3_ASR_FIXTURE',Path.home()/'.local/share/h3video/studio/jfk.flac'))
        if not self.studio.capabilities()['transcription'] or not fixture.exists():self.skipTest('Install CPU speech tools and the official Whisper speech fixture')
        p=self.create()
        clips=copy.deepcopy(p['clips']);clips[0]['seconds']=11
        p=self.studio.update(p['id'],{'clips':clips,'audio':{'originalGain':0}})
        p=self.studio.upload(p['id'],{'kind':'audio','track':'narration'},fixture.name,fixture.read_bytes())
        self.studio.start(p['id'],'transcribe',{'language':'en'})
        p=self.wait(p['id'],180)
        self.assertTrue(p['captions'])
        recognized=' '.join(c['text'] for c in p['captions']).lower()
        self.assertIn('country',recognized)
        self.assertTrue(all(c['end']>c['start'] for c in p['captions']))
        self.assertTrue(p['captions'][0]['words'])
        self.assertTrue(caption_file(p['captions'],True).startswith('WEBVTT'))
        self.assertTrue(self.studio.file(p['id'],'exports/captions.srt').exists())


if __name__=='__main__':unittest.main()
