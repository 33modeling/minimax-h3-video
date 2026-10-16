"""Exercise the local image editing API contract and video variant preservation."""
import base64
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_video_studio as base
from h3video.web import parse_multipart


class QwenRetouchTest(unittest.TestCase):
    setUpClass=classmethod(base.VideoEditingTest.setUpClass.__func__)
    tearDownClass=classmethod(base.VideoEditingTest.tearDownClass.__func__)
    setUp=base.VideoEditingTest.setUp
    create=base.VideoEditingTest.create
    wait=base.VideoEditingTest.wait
    def test_local_edit_api_then_real_upscale_preserves_original_and_audio(self):
        self.run_edit(False)

    def test_turbo_edit_uses_separate_endpoint_eight_steps_cfg_one_and_preserves_video(self):
        self.run_edit(True)

    def run_edit(self, turbo):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                fields=parse_multipart(self.headers['Content-Type'],self.rfile.read(int(self.headers['Content-Length'])))
                calls.append({k:v[0][1].decode() for k,v in fields.items() if k!='image'})
                content=json.dumps({'data':[{'b64_json':base64.b64encode(fields['image'][0][1]).decode()}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        p=self.create();c=p['clips'][0];original=self.studio.file(p['id'],c['variants'][0]['file']).read_bytes()
        prefix='QWEN_IMAGE_TURBO' if turbo else 'QWEN_IMAGE'
        with patch.dict(os.environ,{prefix+'_BASE_URL':f'http://127.0.0.1:{server.server_address[1]}',prefix+'_MODEL':'local-qwen-image-edit'}):
            self.studio.start(p['id'],'upscale',{'clip':c['id'],'scale':2,'engine':'qwen-turbo-realesrgan' if turbo else 'qwen-realesrgan','retouchPrompt':'Reduce noise, keep text unchanged.'})
            result=self.wait(p['id'])
        self.assertEqual(len(calls),4);self.assertIn('Reduce noise',calls[0]['prompt']);self.assertEqual(calls[0]['size'],'96x64')
        self.assertEqual(calls[0]['model'],'local-qwen-image-edit')
        self.assertEqual(calls[0]['num_inference_steps'],'8' if turbo else '40')
        self.assertEqual(calls[0]['true_cfg_scale'],'1' if turbo else '4')
        variant=result['clips'][0]['variants'][-1];self.assertEqual(variant['engine'],'Qwen Image Turbo + Real-ESRGAN' if turbo else 'Qwen Image Edit + Real-ESRGAN')
        self.assertEqual((variant['width'],variant['height']),(192,128));self.assertTrue(variant['audio'])
        self.assertEqual(original,self.studio.file(p['id'],c['variants'][0]['file']).read_bytes())

    def test_edit_server_offline_keeps_previous_selection_and_variants(self):
        p=self.create();c=p['clips'][0]
        with patch.dict(os.environ,{'QWEN_IMAGE_BASE_URL':'http://127.0.0.1:1'}):
            self.studio.start(p['id'],'upscale',{'clip':c['id'],'scale':2,'engine':'qwen-realesrgan','retouchPrompt':'Reduce noise.'})
            import time
            until=time.time()+20
            while time.time()<until:
                result=self.studio.get(p['id'])
                if not result['busy']:break
                time.sleep(.05)
        self.assertEqual(result['task']['status'],'error');self.assertIn('Qwen Image',result['task']['error'])
        self.assertEqual(result['clips'][0]['selected'],c['selected']);self.assertEqual(len(result['clips'][0]['variants']),1)
