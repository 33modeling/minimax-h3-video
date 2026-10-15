import tempfile
import unittest
from pathlib import Path
from h3video.jobs import JobStore, Worker, new_job

class StopTest(unittest.TestCase):
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
