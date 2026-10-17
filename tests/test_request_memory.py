import tempfile
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from h3video.memory import release_request_memory
from h3video.dserver import Server


class RequestMemoryTest(unittest.TestCase):
    def test_chained_failure_frames_are_released_before_allocator_cleanup(self):
        class Tensor:
            pass
        refs=[]
        def fail():
            tensor=Tensor();refs.append(weakref.ref(tensor))
            raise RuntimeError('CUDA out of memory')
        def chained():
            try:fail()
            except RuntimeError as error:raise RuntimeError('pipeline failed') from error
        def cleanup():
            self.assertIsNone(refs[0]())
            raise RuntimeError('allocator unavailable')
        torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,empty_cache=cleanup))
        try:chained()
        except RuntimeError as error:
            release_request_memory(error,torch)
            self.assertEqual(str(error),'pipeline failed')
        self.assertIsNone(refs[0]())

    def test_failed_video_request_releases_memory_then_next_request_can_run(self):
        refs=[]
        class Tensor:
            pass
        class Engine:
            def plan(self,body):return {'task':'t2va','prompt':body['prompt']}
            def run(self,plan,out,on_progress):
                if plan['prompt']=='oom':
                    tensor=Tensor();refs.append(weakref.ref(tensor));raise RuntimeError('CUDA out of memory')
                self.assert_released();out.write_bytes(b'video');return plan['prompt']
            def assert_released(self):
                if refs[0]() is not None:raise AssertionError('failed request still retained')
        with tempfile.TemporaryDirectory() as root:
            server=Server(Engine(),Path(root),'fl2va')
            failed=server.submit({'prompt':'oom'})['id'];server._one(failed)
            self.assertEqual(server.get(failed)['status'],'failed');self.assertIsNone(refs[0]())
            success=server.submit({'prompt':'next'})['id'];server._one(success)
            self.assertEqual(server.get(success)['status'],'completed')
