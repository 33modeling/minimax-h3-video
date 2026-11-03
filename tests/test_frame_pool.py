import copy,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from h3video.web import App
from h3video.frames import endpoint_lanes,upscale_devices,RetouchWorker
from h3video.studio import probe
ROOT=Path(__file__).parents[1]
SHARED=Path('/home/kms/dev/storybook-maker')

class FrameLaneTest(unittest.TestCase):
    def test_unique_endpoints_and_configured_gpus(self):
        with patch.dict(os.environ,{'QWEN_IMAGE_BASE_URL':'http://a:8091/,http://b:8091,http://a:8091','STUDIO_UPSCALER_GPUS':'2,3,2'}):
            self.assertEqual(endpoint_lanes('qwen-image')[1],['http://a:8091','http://b:8091'])
            self.assertEqual(upscale_devices(),['2','3'])
        with patch.dict(os.environ,{'QWEN_IMAGE_BASE_URL':'file:///bad'}):
            with self.assertRaises(ValueError):endpoint_lanes('qwen-image')

class PersistentProtocolTest(unittest.TestCase):
    def test_worker_retains_state_after_error_and_close_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'worker.py'
            script.write_text("import sys,json\nn=0\nfor line in sys.stdin:\n n+=1;d=json.loads(line);print(json.dumps({'ok':False,'error':'fixture failure'} if d.get('fail') else {'ok':True,'result':{'n':n}}),flush=True)\n")
            worker=RetouchWorker([sys.executable,script],dict(os.environ),root/'error.log',lambda:None)
            try:
                self.assertEqual(worker.edit({})['n'],1);pid=worker.child.pid
                with self.assertRaisesRegex(RuntimeError,'fixture failure'):worker.edit({'fail':True})
                self.assertEqual(worker.edit({})['n'],3);self.assertEqual(worker.child.pid,pid)
            finally:worker.close();worker.close()

@unittest.skipUnless((SHARED/'node_modules/sharp').exists(),'Existing shared image provider/sharp required; never install during tests')
class ActualFramePoolTest(unittest.TestCase):
    def test_persistent_two_endpoint_parallel_pause_resume_and_media_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);video=root/'source.mp4';image=root/'source.png';trace=root/'requests.jsonl'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=96x64:r=4','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True)
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-frames:v','1',str(image)],check=True)
            app=App('http://unused.invalid','http://unused.invalid',root/'outputs',None);studio=app.studio
            home=root/'upscale';home.mkdir();(home/'realesrgan-ncnn-vulkan').touch()
            try:
                project=studio.create({'clips':[{'id':'video','seconds':2}]});project=studio.upload(project['id'],{'clip':'video','kind':'video'},video.name,video.read_bytes());original=video.read_bytes()
                command=studio.command;progress=studio.frame_progress;states=[];lock=threading.Lock();active={};max_active={};count=0
                def fake_upscale(p,args,*rest,**kw):
                    nonlocal count
                    if Path(args[0]).name!='realesrgan-ncnn-vulkan':return command(p,args,*rest,**kw)
                    gpu=args[args.index('-g')+1]
                    with lock:active[gpu]=active.get(gpu,0)+1;max_active[gpu]=max(max_active.get(gpu,0),active[gpu]);count+=1
                    try:subprocess.run(['ffmpeg','-v','error','-y','-i',str(args[args.index('-i')+1]),'-vf','scale=iw*2:ih*2',str(args[args.index('-o')+1])],check=True)
                    finally:
                        with lock:active[gpu]-=1
                    return ''
                pause_once=True
                def watch(p,*args,**kw):
                    nonlocal pause_once
                    progress(p,*args,**kw)
                    with studio.lock:
                        state=copy.deepcopy(studio.view(p)['task']['metrics']);states.append(state)
                        if pause_once and state['frames']['completed']>=2:
                            pause_once=False;studio.pause_events[p['id']].set()
                studio.command=fake_upscale;studio.frame_progress=watch
                def wait():
                    end=time.monotonic()+45
                    while time.monotonic()<end:
                        current=studio.get(project['id'])
                        if not current['busy']:return current
                        time.sleep(.02)
                    self.fail('frame pool fixture timeout')
                env={'STORYBOOK_MAKER_ROOT':str(SHARED),'STORYBOOK_LOG_DIR':str(root/'logs'),'QWEN_IMAGE_BASE_URL':'http://gpu-a.invalid:8091,http://gpu-b.invalid:8091','STUDIO_UPSCALER_DIR':str(home),'STUDIO_UPSCALER_GPUS':'0,1','NODE_OPTIONS':'--import='+str(ROOT/'tests/mock_frame_transport.mjs'),'H3_TEST_FRAME_INPUT':str(image),'H3_TEST_FRAME_TRACE':str(trace),'NODE_ENV':'test'}
                with patch.dict(os.environ,env):
                    studio.start(project['id'],'upscale',{'clip':'video','scale':2,'engine':'qwen-realesrgan','retouchPrompt':'preserve all identities'})
                    paused=wait();self.assertEqual(paused['task']['status'],'paused',paused['task'])
                    cached=paused['task']['metrics']['frames']['completed'];self.assertGreaterEqual(cached,2);self.assertLess(cached,8)
                    studio.start(project['id'],'resume');done=wait()
                self.assertEqual(done['task']['status'],'done',done['task']);self.assertEqual(done['task']['metrics']['frames']['completed'],8);self.assertEqual(done['task']['metrics']['frames']['cached'],cached)
                self.assertEqual(count,8,'restored frames must be reused')
                self.assertEqual(max_active,{'0':1,'1':1})
                rows=[json.loads(x)for x in trace.read_text().splitlines()];starts=[x for x in rows if x['event']=='start'];self.assertEqual({x['host']for x in starts},{'gpu-a.invalid','gpu-b.invalid'})
                by_pid={}
                for row in starts:by_pid.setdefault(row['pid'],[]).append(row)
                self.assertTrue(any(len(rows)>=2 for rows in by_pid.values()),'at least one process must persist across multiple frames')
                running=0;peak=0
                for row in sorted(rows,key=lambda x:x['time']):
                    running+=1 if row['event']=='start' else -1;peak=max(peak,running)
                self.assertGreaterEqual(peak,2,'requests to distinct endpoints must overlap')
                self.assertTrue(all(s['frames']['completed']<=8 for s in states))
                last=studio.variant(done['clips'][0]);media=probe(studio.file(done['id'],last['file']));self.assertEqual(media['fps'],4);self.assertTrue(media['audio']);self.assertEqual((media['width'],media['height']),(192,128))
                self.assertEqual(studio.file(done['id'],done['clips'][0]['variants'][0]['file']).read_bytes(),original)
                print('Frame pool: 8 real frames, overlapping endpoint requests, persistent child workers, atomic counts, pause/resume, audio/FPS/original retained. No model or sockets.')
            finally:studio.close()

if __name__=='__main__':unittest.main()
