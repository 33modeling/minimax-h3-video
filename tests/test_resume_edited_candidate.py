import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from h3video.web import App
from h3video.jobs import Worker, new_job, plan_job

class ResumeEditedCandidateTest(unittest.TestCase):
    def test_resume_updates_only_unfinished_scene_prompts_and_keeps_job_seed_and_completed_files(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(Worker,'start'):
            app=App('http://127.0.0.1:9','http://127.0.0.1:9',Path(temporary),None)
            try:
                project=app.studio.create({'clips':[{'id':'one','prompt':'original landscape','seconds':20}]})
                job=new_job('original landscape',seconds=20,seed=45);job.max_scene=10;job.scenes=plan_job(job);job.status='paused';app.store.add(job)
                output=Path(temporary)/job.id/'scene01.mp4';output.write_bytes(b'preserve completed scene');mtime=output.stat().st_mtime_ns
                job.scenes[0].status='completed';job.scenes[0].output=str(output);app.store.save(job)
                project=app.studio.load(project['id']);project['clips'][0]['pendingCandidates']=[{'job':job.id,'phase':'draft','seed':job.seed}];app.studio.save(project)
                app.studio.update(project['id'],{'clips':[{'id':'one','prompt':'revised forest prompt'}]})
                app.studio.start(project['id'],'resume')
                resumed=app.store.get(job.id)
                self.assertIn('revised forest prompt',resumed.scenes[1].prompt)
                self.assertNotIn('revised forest prompt',resumed.scenes[0].prompt)
                self.assertEqual(resumed.seed,45);self.assertEqual(resumed.status,'pending');self.assertIn(job.id,app.worker.queue)
                self.assertEqual(output.read_bytes(),b'preserve completed scene');self.assertEqual(output.stat().st_mtime_ns,mtime)
                self.assertTrue(list((Path(temporary)/job.id/'history').glob('*/job.json')))
            finally:app.studio.close();app.motion.close()
