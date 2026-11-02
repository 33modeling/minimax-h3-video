"""CLI workflows against the real worker and generated media; no servers or GPU."""
import contextlib
import copy
import http.client
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

from h3video import cli
from h3video.client import H3Client, H3Error
from h3video.jobs import HOST, JobStore, Worker, new_job, plan_job


class InlineWorker(Worker):
    """Exercise the actual process() path deterministically, without a daemon loop."""
    def start(self):
        while self.queue:
            job = self.store.get(self.queue.pop(0))
            try:
                self.process(job)
            except Exception as error:
                job.status, job.error, job.finished = 'failed', str(error), time.time()
                self.store.save(job)


class CliWorkflowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The fixture is a real tiny MP4. These tests do not measure H3 inference.
        sys.path.insert(0, str(Path(__file__).parent))
        from mock_server import fake_mp4
        cls.video = fake_mp4()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.outputs = self.root/'outputs'
        environment = {k:v for k,v in os.environ.items() if not k.startswith('H3_')}
        environment['XDG_CONFIG_HOME'] = str(self.root/'config')
        for item in [patch.dict(os.environ, environment, clear=True),
                     patch('socket.socket.listen', side_effect=AssertionError('No listeners permitted')),
                     patch('socket.create_connection', side_effect=AssertionError('No network permitted')),
                     patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected HTTP'))]:
            item.start(); self.addCleanup(item.stop)
        self.store = JobStore(self.outputs)

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO(); code = 0
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try: cli.main([*args, '--output-dir', str(self.outputs)])
            except SystemExit as error:
                code = error.code if isinstance(error.code,int) else 1
                if not isinstance(error.code,int): errors.write(str(error.code))
        return code, output.getvalue(), errors.getvalue()

    def saved(self, *, status='failed', seconds=20, completed_first=True, remote=True):
        job = new_job('a boat sails', seconds=seconds, seed=123, title='saved boat')
        job.scenes = plan_job(job); job.status = status; self.store.add(job)
        for index, scene in enumerate(job.scenes):
            if index == 0 and completed_first:
                output = self.outputs/job.id/'scene01.mp4'; output.write_bytes(self.video)
                scene.status, scene.output, scene.progress = 'completed', str(output), 1
            else:
                scene.status = 'in_progress' if remote else 'failed'
                scene.video_id = 'remote-existing' if remote else 'remote-failed'
        self.store.save(job)
        return job

    def client(self):
        client = Mock(spec=H3Client)
        client.healthy.return_value = True
        client.max_seconds.return_value = None
        client.submit.return_value = 'remote-new'
        client.status.return_value = {'status':'in_progress'}
        client.cancel.return_value = {'status':'cancelled'}
        def wait(video_id, **options):
            result = {'id':video_id,'status':'completed','progress':1}
            if options.get('on_progress'): options['on_progress'](result)
            return result
        client.wait.side_effect = wait
        def download(video_id, path):
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.video);return path
        client.download.side_effect = download
        return client

    def resume_with(self, client, *args):
        with patch.object(cli, 'H3Client', return_value=client), patch.object(cli, 'Worker', InlineWorker):
            return self.run_cli('resume', *args)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'real chain fixture needs ffmpeg')
    def test_resume_preserves_completed_bytes_seed_partition_and_live_remote_id(self):
        job=self.saved();first=Path(job.scenes[0].output);before=(first.read_bytes(),first.stat().st_mtime_ns)
        client=self.client();code,out,err=self.resume_with(client,'last')
        self.assertEqual(code,0,err);client.submit.assert_not_called();client.max_seconds.assert_not_called()
        self.assertEqual(client.wait.call_args.args[0],'remote-existing')
        current=JobStore(self.outputs).get(job.id)
        self.assertEqual((current.seed,[s.duration for s in current.scenes]),(123,[10,10]))
        self.assertEqual((first.read_bytes(),first.stat().st_mtime_ns),before)
        self.assertEqual(json.loads((self.outputs/job.id/'scene02.request.json').read_text())['seed'],124)
        self.assertTrue(Path(out.strip()).is_file());self.assertEqual(current.status,'completed')
        self.assertEqual(len(list((self.outputs/job.id/'history').glob('*/job.json'))),1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'real chain fixture needs ffmpeg')
    def test_resume_only_resubmits_failed_scene(self):
        job=self.saved(remote=False);client=self.client();code,out,err=self.resume_with(client,job.id)
        self.assertEqual(code,0,err);self.assertEqual(client.submit.call_count,1)
        self.assertEqual(client.submit.call_args.args[0].seed,124)
        self.assertEqual(JobStore(self.outputs).get(job.id).scenes[0].status,'completed')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'real chain fixture needs ffmpeg')
    def test_resume_size_cancels_active_request_and_only_changes_unfinished_submission(self):
        job=self.saved();before=Path(job.scenes[0].output).read_bytes();client=self.client()
        code,out,err=self.resume_with(client,job.id,'--size','512')
        self.assertEqual(code,0,err);client.cancel.assert_called_once_with('remote-existing')
        self.assertEqual(client.submit.call_args.args[0].short_edge,512)
        current=JobStore(self.outputs).get(job.id);self.assertEqual(current.short_edge,512)
        self.assertEqual(Path(current.scenes[0].output).read_bytes(),before)
        previous=json.loads(next((self.outputs/job.id/'history').glob('*/job.json')).read_text());self.assertEqual(previous['short_edge'],768)

    def test_resume_size_requires_supported_remote_cancellation(self):
        job=self.saved(seconds=8,completed_first=False);client=self.client();client.cancel.return_value={'status':'unsupported'}
        code,out,err=self.resume_with(client,job.id,'--size','512')
        self.assertEqual(code,1);self.assertIn('취소를 지원하지',err);client.submit.assert_not_called()
        self.assertEqual(JobStore(self.outputs).get(job.id).short_edge,768)

    def test_same_size_reattaches_without_cancellation(self):
        job=self.saved(seconds=8,completed_first=False);client=self.client()
        code,out,err=self.resume_with(client,'last','--size','768');self.assertEqual(code,0,err)
        client.cancel.assert_not_called();client.submit.assert_not_called()

    def test_larger_resume_size_is_rejected_without_network(self):
        job=self.saved();job.short_edge=512;self.store.save(job)
        code,out,err=self.run_cli('resume','last','--size','768')
        self.assertEqual(code,1);self.assertIn('크게 설정할 수 없습니다',err)

    def test_resume_dry_run_keeps_job_metadata_and_remote_requests_untouched(self):
        job=self.saved();path=self.outputs/job.id/'job.json';before=path.read_bytes()
        code,out,err=self.run_cli('resume','last','--size','512','--dry-run','--json')
        self.assertEqual(code,0,err);data=json.loads(out)
        self.assertEqual(data['completed_scenes'],1);self.assertEqual(data['short_edge'],512)
        self.assertEqual(data['scenes'][1]['action'],'check-remote-before-resize')
        self.assertEqual(path.read_bytes(),before);self.assertFalse((path.parent/'history').exists());self.assertFalse((path.parent/'.cli-resume.lock').exists())

    def test_resume_dry_run_does_not_persist_orphan_detection(self):
        job=self.saved(status='running');job.host=HOST;job.pid=os.getpid()+99999;self.store.save(job)
        path=self.outputs/job.id/'job.json';before=path.read_bytes()
        with patch('h3video.jobs.pid_alive',return_value=False):code,out,err=self.run_cli('resume','last','--dry-run','--json')
        self.assertEqual(code,0,err);self.assertEqual(path.read_bytes(),before)

    def test_live_job_and_duplicate_resume_are_refused_before_requests(self):
        job=self.saved(status='running');job.host=HOST;job.pid=os.getpid();self.store.save(job)
        code,out,err=self.run_cli('resume','last');self.assertEqual(code,1);self.assertIn('처리 중',err)
        job.status='failed';self.store.save(job)
        with self.store.claim(job.id):
            code,out,err=self.run_cli('resume',job.id);self.assertEqual(code,1);self.assertIn('다른 CLI',err)

    def test_process_lock_is_visible_to_a_second_process(self):
        job=self.saved()
        script="from pathlib import Path;from h3video.jobs import JobStore;from h3video.client import H3Error;import sys\ns=JobStore(Path(sys.argv[1]),read_only=True)\ntry:\n with s.claim(sys.argv[2]):sys.exit(5)\nexcept H3Error:sys.exit(0)"
        with self.store.claim(job.id):
            result=subprocess.run([sys.executable,'-c',script,str(self.outputs),job.id],env={**os.environ,'PYTHONPATH':str(Path(__file__).parents[1]/'src')},capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_completed_job_returns_existing_result_without_server(self):
        job=self.saved(status='completed',seconds=8);job.output=job.scenes[0].output;self.store.save(job)
        code,out,err=self.run_cli('resume','last');self.assertEqual(code,0,err);self.assertEqual(out.strip(),job.output)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'real chain fixture needs ffmpeg')
    def test_completed_scenes_can_be_joined_again_offline(self):
        job=self.saved(remote=False)
        second=self.outputs/job.id/'scene02.mp4';second.write_bytes(self.video);job.scenes[1].status='completed';job.scenes[1].output=str(second);self.store.save(job)
        client=self.client();code,out,err=self.resume_with(client,'last')
        self.assertEqual(code,0,err);client.healthy.assert_not_called();client.submit.assert_not_called();client.wait.assert_not_called()
        self.assertTrue(Path(out.strip()).is_file())

    def test_network_download_failure_can_reattach_on_next_resume(self):
        job=self.saved(seconds=8,completed_first=False);client=self.client();client.download.side_effect=H3Error('download connection lost')
        code,out,err=self.resume_with(client,'last');self.assertEqual(code,1);self.assertIn('h3video resume',err)
        self.assertEqual(JobStore(self.outputs).get(job.id).scenes[0].video_id,'remote-existing')
        client=self.client();code,out,err=self.resume_with(client,'last');self.assertEqual(code,0,err);client.submit.assert_not_called()

    def test_wait_ref_downloads_existing_video_without_submission(self):
        client=self.client();destination=self.root/'received.mp4'
        with patch.object(cli,'H3Client',return_value=client) as factory:
            code,out,err=self.run_cli('wait','existing','--ref','--timeout','30','-o',str(destination))
        self.assertEqual(code,0,err);self.assertTrue(destination.is_file());client.submit.assert_not_called()
        self.assertEqual(factory.call_args.args[0],'http://127.0.0.1:30011');self.assertEqual(client.wait.call_args.kwargs['timeout'],30)

    def test_wait_timeout_does_not_cancel_or_submit(self):
        client=self.client();client.wait.side_effect=H3Error('대기 시간 초과 existing')
        with patch.object(cli,'H3Client',return_value=client):code,out,err=self.run_cli('wait','existing','--timeout','1')
        self.assertEqual(code,1);client.cancel.assert_not_called();client.submit.assert_not_called()

    def test_cancel_reports_supported_and_unsupported_responses(self):
        for status,code in [('cancelled',0),('cancelling',0),('completed',0),('unsupported',1)]:
            with self.subTest(status=status):
                client=self.client();client.cancel.return_value={'id':'existing','status':status}
                with patch.object(cli,'H3Client',return_value=client):actual,out,err=self.run_cli('cancel','existing','--ref')
                self.assertEqual(actual,code,err);self.assertEqual(json.loads(out)['status'],status);client.submit.assert_not_called()

    def test_cancel_checks_existing_id_and_leaves_completed_video_untouched(self):
        client=self.client();client.status.side_effect=H3Error('GET /v1/videos/absent -> HTTP 404: missing')
        with patch.object(cli,'H3Client',return_value=client):code,out,err=self.run_cli('cancel','absent')
        self.assertEqual(code,1);self.assertIn('그런 영상이 없다',err);client.cancel.assert_not_called()
        client=self.client();client.status.return_value={'id':'done','status':'completed'}
        with patch.object(cli,'H3Client',return_value=client):code,out,err=self.run_cli('cancel','done')
        self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['status'],'completed');client.cancel.assert_not_called()

    def test_machine_plan_flags_cannot_accidentally_execute(self):
        batch=self.root/'batch.txt';batch.write_text('example')
        story=self.root/'story.json';story.write_text(json.dumps({'clips':[{'prompt':'example','seconds':8}]}))
        for args in [('batch',str(batch),'--json'),('json',str(story),'--list','--json'),('ir','example','--json')]:
            with self.subTest(args=args):
                code,out,err=self.run_cli(*args);self.assertEqual(code,1);self.assertIn('--dry-run',err)

    def test_jobs_filters_before_limit_and_empty_json_stays_machine_readable(self):
        self.saved(status='failed');self.saved(status='paused');self.saved(status='completed')
        code,out,err=self.run_cli('jobs','--status','failed','--status','paused','--limit','1','--json')
        self.assertEqual(code,0,err);self.assertEqual(len(json.loads(out)),1);self.assertEqual(json.loads(out)[0]['status'],'paused')
        code,out,err=self.run_cli('jobs','--task','ref2va','--json');self.assertEqual(json.loads(out),[])
        shutil.rmtree(self.outputs)
        code,out,err=self.run_cli('jobs','--json');self.assertEqual(code,0,err);self.assertEqual(json.loads(out),[]);self.assertFalse(self.outputs.exists())

    def test_batch_rejects_size_audio_only_and_mixed_modes_without_partial_stdout(self):
        cases=['size: 123\ninvalid','audio: https://fixture.test/voice.wav\naudio only',
               'first: https://fixture.test/start.png\nimage: https://fixture.test/ref.png\nmixed', 'steps: 0\nzero steps']
        for text in cases:
            with self.subTest(text=text):
                path=self.root/'batch.txt';path.write_text('first valid prompt\n---\n'+text)
                code,out,err=self.run_cli('batch',str(path),'--dry-run','--json')
                self.assertEqual(code,1,err);self.assertEqual(out,'');self.assertIn('2번째 블록',err)

    def test_batch_and_story_previews_are_single_json_documents(self):
        path=self.root/'batch.txt';path.write_text('first prompt\n---\nseconds: 20\nsecond prompt')
        code,out,err=self.run_cli('batch',str(path),'--dry-run','--json')
        self.assertEqual(code,0,err);data=json.loads(out);self.assertEqual(data['job_count'],2);self.assertEqual(len(data['jobs'][1]['requests']),2)
        path=self.root/'story.json';path.write_text(json.dumps({'title':'story','clips':[{'prompt':'a boat','seconds':8},{'prompt':'a tree','seconds':8}]}))
        before=set(self.outputs.rglob('*'));code,out,err=self.run_cli('json',str(path),'--dry-run','--json')
        self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['job_count'],2);self.assertEqual(set(self.outputs.rglob('*')),before)

    def test_actual_module_entry_accepts_stdin_and_saved_resume_preview(self):
        env={**os.environ,'PYTHONPATH':str(Path(__file__).parents[1]/'src')}
        command=[sys.executable,'-m','h3video.cli']
        result=subprocess.run([*command,'gen','-s','8','--dry-run','--json'],input='a boat from stdin',env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['requests'][0]['prompt'],'a boat from stdin')
        job=self.saved();result=subprocess.run([*command,'resume',job.id,'--output-dir',str(self.outputs),'--dry-run','--json'],env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['job_id'],job.id)

    def test_ir_dry_run_never_rewrites_or_submits(self):
        code,out,err=self.run_cli('ir','a boat','--dry-run','--json')
        self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['requests'][0]['prompt'],'a boat')

    def test_poll_timeout_steps_and_limits_reject_invalid_values(self):
        for args in [('gen','boat','--steps','0','--dry-run'),('jobs','--limit','-1'),('wait','remote','--timeout','0'),('wait','remote','--timeout','inf'),('gen','boat','--poll','nan','--dry-run'),('gen','boat','--poll','-1','--dry-run')]:
            with self.subTest(args=args):self.assertEqual(self.run_cli(*args)[0],2)

    def test_reference_health_and_doctor_require_the_selected_server(self):
        for command in ['health','doctor']:
            for main,reference,flag,expected in [(True,False,False,0),(True,False,True,1),(False,True,True,0)]:
                with self.subTest(command=command,main=main,reference=reference,flag=flag):
                    with patch.object(cli,'server_report',side_effect=[main,reference]),patch.object(cli.H3Client,'max_seconds',return_value=None):
                        code,out,err=self.run_cli(command,*(['--ref']if flag else []))
                    self.assertEqual(code,expected,err)

    def test_bom_batch_and_prompt_files_are_read_without_hidden_prefixes(self):
        path=self.root/'batch.txt';path.write_text('\ufeffseconds: 6\nfirst prompt')
        code,out,err=self.run_cli('batch',str(path),'--dry-run','--json')
        self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['jobs'][0]['total_seconds'],6)
        path=self.root/'prompt.txt';path.write_text('\ufeffa boat')
        code,out,err=self.run_cli('gen','-f',str(path),'--dry-run','--json')
        self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['requests'][0]['prompt'],'a boat')

    def test_paused_worker_is_terminal_for_the_cli_monitor(self):
        self.saved(seconds=8,completed_first=False);client=self.client()
        class PausedWorker(InlineWorker):
            def start(self):
                job=self.store.get(self.queue.pop(0));job.status='paused';self.store.save(job)
        with patch.object(cli,'H3Client',return_value=client),patch.object(cli,'Worker',PausedWorker):
            code,out,err=self.run_cli('resume','last')
        self.assertEqual(code,1);self.assertIn('h3video resume',err);self.assertEqual(out,'')

    def test_copy_out_never_overwrites_previous_directory_exports(self):
        source=self.root/'original.mp4';source.write_bytes(self.video);folder=self.root/'exports'
        paths=[cli.copy_out(str(source),str(folder)+'/',job_id='same-job')for _ in range(4)]
        self.assertEqual(len(set(paths)),4);self.assertTrue(all(Path(p).read_bytes()==self.video for p in paths))
        self.assertEqual(cli.copy_out(str(source),str(source)),str(source))

    def test_resume_hint_quotes_paths_with_spaces(self):
        path=str(self.root/'my videos');parts=shlex.split(cli.resume_command('id',path));self.assertEqual(parts,['h3video','resume','id','--output-dir',path])


class StreamDownloadTest(unittest.TestCase):
    class Response(io.BytesIO):
        def __init__(self,data,expected=None,fail=False):
            super().__init__(data);self.headers={'Content-Length':str(len(data) if expected is None else expected)};self.fail=fail;self.calls=[]
        def read(self,size=-1):
            if size<0:raise AssertionError('unbounded read')
            self.calls.append(size)
            if self.fail and len(self.calls)>1:raise http.client.IncompleteRead(b'partial')
            return super().read(size)

    def test_success_reads_bounded_chunks_then_replaces_file(self):
        with tempfile.TemporaryDirectory()as directory:
            dest=Path(directory)/'movie.mp4';dest.write_bytes(b'old');data=b'video-data'*300000;response=self.Response(data)
            with patch('urllib.request.urlopen',return_value=response):result=H3Client().download('remote',dest)
            self.assertEqual(result,dest);self.assertEqual(dest.read_bytes(),data);self.assertTrue(all(n==1024*1024 for n in response.calls));self.assertEqual(list(dest.parent.glob('.h3-download-*')),[])

    def test_disconnect_truncation_and_small_body_preserve_existing_output(self):
        for response in [self.Response(b'x'*1500,fail=True),self.Response(b'x'*1500,expected=2500),self.Response(b'bad')]:
            with self.subTest(response=response), tempfile.TemporaryDirectory()as directory:
                dest=Path(directory)/'movie.mp4';dest.write_bytes(b'preserve old result')
                with patch('urllib.request.urlopen',return_value=response), self.assertRaises(H3Error):H3Client().download('remote',dest)
                self.assertEqual(dest.read_bytes(),b'preserve old result');self.assertEqual(list(dest.parent.glob('.h3-download-*')),[])

    def test_download_http_error_preserves_status_and_existing_file(self):
        with tempfile.TemporaryDirectory()as directory:
            dest=Path(directory)/'movie.mp4';dest.write_bytes(b'old')
            error=urllib.error.HTTPError('http://fixture.test',404,'missing',{},io.BytesIO(b'missing'))
            with patch('urllib.request.urlopen',side_effect=error),self.assertRaises(H3Error)as caught:H3Client().download('missing',dest)
            self.assertEqual(caught.exception.http_status,404);self.assertEqual(dest.read_bytes(),b'old')


if __name__=='__main__':unittest.main()
