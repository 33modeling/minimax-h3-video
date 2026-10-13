"""Real frame/OCR analysis, persistence and typography/project round trips."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
import mock_server
from h3video.web import App
from h3video.reference import youtube_url,validate_document
from h3video.client import H3Error


class ReferenceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.model,_,endpoint=mock_server.start(steps=1)
        self.addCleanup(self.model.server_close);self.addCleanup(self.model.shutdown)
        self.app=App(endpoint,endpoint,self.root/'outputs',None,poll=.01);self.addCleanup(self.app.studio.close)
        self.library=self.app.references
        self.video=self.root/'reference.mp4'
        subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=0x203f65:s=640x360:r=4:d=1',
                        '-f','lavfi','-i','color=c=0xeeddb0:s=640x360:r=4:d=1','-filter_complex',
                        "[0:v]drawtext=text='HELLO WORLD':fontsize=44:fontcolor=white:x=80:y=70[a];[1:v]drawtext=text='SECOND SHOT':fontsize=40:fontcolor=black:x=60:y=250[b];[a][b]concat=n=2:v=1:a=0[v]",
                        '-map','[v]','-c:v','libx264','-pix_fmt','yuv420p',str(self.video)],check=True)

    def wait(self,name,status='done',timeout=60):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            job=self.library.get(name)
            if job['status']==status:return job
            if status=='done' and job['status']=='error':self.fail(job['error'])
            time.sleep(.05)
        self.fail('Analysis timeout: '+str(self.library.get(name)))

    def test_url_host_validation_and_canonicalization(self):
        for url in ['https://youtu.be/aqz-KE-bpKQ?t=2','https://m.youtube.com/watch?v=aqz-KE-bpKQ&list=x','https://www.youtube.com/shorts/aqz-KE-bpKQ']:
            self.assertEqual(youtube_url(url),'https://www.youtube.com/watch?v=aqz-KE-bpKQ')
        for url in ['https://youtube.com.evil.org/watch?v=aqz-KE-bpKQ','http://127.0.0.1:8000/x','file:///tmp/x','https://youtube.com/playlist?list=x','https://user@youtube.com/watch?v=aqz-KE-bpKQ']:
            with self.assertRaises(H3Error):youtube_url(url)

    def test_actual_cuts_ocr_boxes_archive_edit_import_and_reopen(self):
        job=self.library.create({'start':0,'end':2,'interval':6,'transcribe':False},('test.mp4',self.video.read_bytes()))
        job=self.wait(job['id']);doc=job['document']
        self.assertEqual(len(doc['clips']),2,'Actual color cut should split the reference')
        self.assertIn('HELLO',doc['clips'][0]['text_overlays'][0]['text'])
        box=doc['clips'][0]['text_overlays'][0]['box'];self.assertAlmostEqual(box['x'],80/640,delta=.03);self.assertAlmostEqual(box['y'],70/360,delta=.06)
        self.assertIsNone(doc['clips'][0]['text_overlays'][0]['source_font_family'])
        self.assertIn('Qwen Image Edit',doc['clips'][0]['image_prompt'])
        before=self.app.studio.create({'title':'기존 작업'})
        doc['clips'][0]['video_prompt']='수정한 제품 소개 장면'
        doc['clips'][0]['text_overlays'][0].update(font_family='Georgia',color='#ff1122')
        saved=self.library.edit(job['id'],{'document':doc})
        with zipfile.ZipFile(self.library.directory(job['id'])/'reference.zip') as archive:
            exported=json.loads(archive.read('prompts.json'))
            self.assertEqual(exported['clips'][0]['text_overlays'][0]['font_family'],'Georgia')
            self.assertEqual(sorted(n for n in archive.namelist() if n.endswith('.png')),['0001.png','0002.png'])
        p=self.library.import_project(job['id']);self.assertNotEqual(p['id'],before['id'])
        self.assertTrue(p['clips'][0]['prompt'].startswith('수정한 제품 소개 장면'))
        self.assertIn('font Georgia',p['clips'][0]['prompt'])
        self.assertIn('color #ff1122',p['clips'][0]['prompt'])
        self.assertEqual(p['clips'][0]['referenceMetadata']['text_overlays'][0]['color'],'#ff1122')
        self.assertTrue(p['clips'][0]['imageUrl']);self.assertEqual(self.app.studio.get(before['id'])['title'],'기존 작업')
        self.assertEqual(self.library.get(job['id'])['document'],saved['document'])

    def test_pause_resume_checkpoints_and_path_invalid_edit_keeps_original(self):
        job=self.library.create({'interval':.5,'transcribe':False},('source.mp4',self.video.read_bytes()))
        self.library.pause(job['id']);job=self.wait(job['id'],'paused')
        self.library.resume(job['id']);job=self.wait(job['id'])
        frames=list((self.library.directory(job['id'])/'frames').glob('*.png'));timestamps={f.name:f.stat().st_mtime_ns for f in frames}
        self.assertGreaterEqual(len(frames),4)
        self.library.resume(job['id'])
        self.assertEqual(timestamps,{f.name:f.stat().st_mtime_ns for f in frames})
        bad=copy.deepcopy(job['document']);bad['clips'][0]['reference_frame']='../../outside.png'
        with self.assertRaises(H3Error):self.library.edit(job['id'],{'document':bad})
        bad=copy.deepcopy(job['document']);bad['clips'][0]['text_overlays'][0]['box']['x']=.99
        with self.assertRaises(H3Error):validate_document(bad)
        self.assertEqual(self.library.get(job['id'])['document'],job['document'])

    def test_youtube_download_range_pipeline_uses_canonical_url_and_actual_analysis(self):
        original=self.library.command;commands=[]
        def command(job,args,*positional,**kwargs):
            commands.append([str(a) for a in args])
            if '--dump-single-json' in args:return json.dumps({'title':'참고 영상','channel':'Official','duration':90})
            if '--download-sections' in args:
                import shutil;shutil.copyfile(self.video,self.library.directory(job['id'])/'download.mp4');return ''
            return original(job,args,*positional,**kwargs)
        with patch.object(self.library,'command',side_effect=command):
            job=self.library.create({'url':'https://youtu.be/aqz-KE-bpKQ?t=40','start':40,'end':42,'transcribe':False})
            job=self.wait(job['id'])
        download=next(c for c in commands if '--download-sections' in c)
        self.assertIn('*40.0-42.0',download);self.assertIn('--force-keyframes-at-cuts',download)
        self.assertEqual(job['document']['clips'][0]['source_start'],40)
        self.assertEqual(job['source']['url'],'https://www.youtube.com/watch?v=aqz-KE-bpKQ')


if __name__=='__main__':unittest.main()
