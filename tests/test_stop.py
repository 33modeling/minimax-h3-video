import tempfile
import unittest
from pathlib import Path
from h3video.jobs import JobStore, Worker, new_job

class StopTest(unittest.TestCase):
    def test_remote_failure_retries_new_request_after_reload_and_keeps_finished_scene(self):
        from unittest.mock import patch
        from h3video.client import H3Error
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root));job=new_job('two scenes',seconds=20,scene_seconds=10);job.max_scene=10;store.add(job)
            class Client:
                submitted=[]
                waits=[]
                def submit(self,request):
                    self.submitted.append(request);return 'remote-'+str(len(self.submitted))
                def wait(self,video_id,**kwargs):
                    self.waits.append(video_id)
                    if video_id=='remote-2':raise H3Error('CUDA out of memory')
                    return {'status':'completed'}
                def download(self,video_id,out):out.write_bytes(video_id.encode())
            client=Client();worker=Worker(store,client,inbox_dir=None)
            def frame(video,out):out.write_bytes(b'frame');return out
            def join(parts,out):out.write_bytes(b''.join(p.read_bytes() for p in parts));return out
            with patch('h3video.jobs.extract_last_frame',frame),patch('h3video.jobs.concat_videos',join):
                with self.assertRaisesRegex(H3Error,'out of memory'):worker.process(job)
                self.assertEqual(job.scenes[1].status,'failed')
                job.status='failed';store.save(job)
                original=Path(job.scenes[0].output).read_bytes()
                worker.store=JobStore(Path(root));job=worker.store.get(job.id)
                worker.resume(job.id);worker.process(job)
                self.assertEqual(job.status,'completed')
                self.assertEqual(client.waits,['remote-1','remote-2','remote-3'])
                self.assertEqual(Path(job.scenes[0].output).read_bytes(),original)
                self.assertEqual(client.submitted[1].seed,client.submitted[2].seed)

    def test_stop_during_submit_cancels_late_remote_request_and_stays_paused(self):
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root));job=new_job('stop while submitting',seconds=6);job.max_scene=15;store.add(job)
            class Client:
                cancelled=[]
                def submit(self,request):worker.stop(job.id);return 'late-remote'
                def cancel(self,video_id):self.cancelled.append(video_id);return {'status':'cancelled'}
                def wait(self,*args,**kwargs):raise AssertionError('stopped request must not be awaited')
            client=Client();worker=Worker(store,client,inbox_dir=None);worker.process(job)
            self.assertEqual(job.status,'paused');self.assertEqual(client.cancelled,['late-remote'])
            self.assertIsNone(job.scenes[0].video_id)

    def test_remote_cancel_error_during_wait_still_leaves_resumable_job(self):
        from h3video.client import H3Error
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root));job=new_job('cancel race',seconds=6);job.max_scene=15;store.add(job)
            class Client:
                def submit(self,request):return 'remote'
                def cancel(self,video_id):return {'status':'cancelled'}
                def wait(self,*args,**kwargs):worker.stop(job.id);raise H3Error('remote cancelled')
            worker=Worker(store,Client(),inbox_dir=None);worker.process(job)
            self.assertEqual(job.status,'paused');self.assertIsNone(job.error)

    def test_stop_exits_current_wait_and_resume_reuses_submitted_video(self):
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root));job=new_job('A single scene',seconds=6);job.max_scene=15;store.add(job)
            class Client:
                submits=0
                waiting=True
                def submit(self,request):self.submits+=1;return 'already-submitted'
                def wait(self,video_id,**kwargs):
                    if self.waiting:
                        worker.stop(job.id)
                        kwargs['on_progress']({'status':'in_progress','progress':.2})
                    return {'status':'completed'}
                def download(self,video_id,out):out.write_bytes(b'preserved-video')
            client=Client();worker=Worker(store,client,inbox_dir=None)
            worker.process(job)
            self.assertEqual(job.status,'paused');self.assertEqual(client.submits,1)
            self.assertEqual(job.scenes[0].video_id,'already-submitted')
            restored=JobStore(Path(root));job=restored.get(job.id);worker.store=restored;client.waiting=False
            worker.resume(job.id);worker.process(job)
            self.assertEqual(job.status,'completed');self.assertEqual(client.submits,1)
            self.assertEqual(Path(job.output).read_bytes(),b'preserved-video')

    def test_stopping_queued_job_removes_only_that_job_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as root:
            worker=Worker(JobStore(Path(root)),object(),inbox_dir=None)
            one,two=new_job('one'),new_job('two');worker.enqueue(one);worker.enqueue(two)
            worker.stop(one.id);worker.stop(one.id)
            self.assertEqual(one.status,'paused');self.assertEqual(worker.queue,[two.id])
            worker.resume(one.id);self.assertEqual(worker.queue,[two.id,one.id])

    def test_stop_cancels_supported_backend_and_resume_only_resubmits_unfinished_scene(self):
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root));job=new_job('scene',seconds=6);job.max_scene=15;store.add(job)
            class Client:
                submits=0
                cancelled=[]
                def submit(self,request):self.submits+=1;return 'remote-'+str(self.submits)
                def cancel(self,video_id):self.cancelled.append(video_id);return {'status':'cancelling'}
                def wait(self,video_id,**kwargs):
                    if self.submits==1:
                        worker.stop(job.id);kwargs['on_progress']({'status':'in_progress'})
                    return {'status':'completed'}
                def download(self,video_id,out):out.write_bytes(b'new-video')
            client=Client();worker=Worker(store,client,inbox_dir=None);worker.process(job)
            self.assertEqual(job.status,'paused');self.assertEqual(client.cancelled,['remote-1']);self.assertIsNone(job.scenes[0].video_id)
            worker.resume(job.id);worker.process(job);self.assertEqual(job.status,'completed');self.assertEqual(client.submits,2)

    def test_oom_pauses_same_project_queue_but_other_project_runs(self):
        import threading,time
        with tempfile.TemporaryDirectory() as root:
            worker=Worker(JobStore(Path(root)),object(),inbox_dir=None)
            first,second,other=new_job('oom'),new_job('same group'),new_job('other')
            first.group_id=second.group_id='project-a';other.group_id='project-b'
            failed=[False]
            def process(job):
                if job.id==first.id and not failed[0]:
                    failed[0]=True;raise RuntimeError('CUDA out of memory')
                job.status='completed';worker.store.save(job)
            worker.process=process
            for job in (first,second,other):worker.enqueue(job)
            worker.start()
            for _ in range(200):
                if other.status=='completed':break
                time.sleep(.01)
            self.assertEqual(first.status,'failed');self.assertEqual(second.status,'paused');self.assertEqual(other.status,'completed')
            worker.resume(first.id);worker.resume(second.id)
            for _ in range(200):
                if first.status==second.status=='completed':break
                time.sleep(.01)
            self.assertEqual(first.status,'completed');self.assertEqual(second.status,'completed')
