"""Actual tiny Diffusers/Qwen execution and isolated recovery, without listeners."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import torch
from PIL import Image
from diffusers import MiniMaxH3Scheduler
from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3ImageReference, MiniMaxH3VideoReference, MiniMaxH3AudioReference
from diffusers.modular_pipelines.minimax_h3.modular_blocks_minimax_h3 import MiniMaxH3Blocks
from diffusers.modular_pipelines.modular_pipeline import PipelineState
from h3video.dserver import Engine, Server, WorkerDied, WorkerTimeout
from h3video.dworker import record_failure
from h3video.memory import GenerationMemoryError
from h3video.preparation import RequestPreparation
from h3video.worker_state import denoiser_state, read_failures, write_failure
from h3video.placement import offload_conditioning_text
from test_placement import tiny_model


class DenoiserTransportTest(unittest.TestCase):
    def test_actual_rpc_has_no_pixels_and_keeps_source_state(self):
        den = MiniMaxH3Blocks().sub_blocks['denoise']
        e = Engine.__new__(Engine)
        e._den_keys = {i.name for i in den.inputs if i.name} | set(den.block_trigger_inputs)
        sent = []
        e._conn = SimpleNamespace(send_bytes=sent.append)
        response = io.BytesIO(); torch.save({'ok': True}, response)
        e._recv = lambda deadline=None: b'DONE' + response.getvalue()
        frames = np.zeros((24,128,128,3), dtype=np.uint8)
        ref = MiniMaxH3VideoReference(frames, fps=24)
        state = PipelineState(); state.values = dict(references=[ref], normalized_references=[ref],
                                                      latents=torch.zeros(1,4,2,2,2))
        e._denoise_remote(state, torch.Generator('cpu'), {})
        packet = torch.load(io.BytesIO(sent[0]), weights_only=False)
        self.assertLess(len(sent[0]), 16000)
        self.assertIs(packet['state'].values['references'], True)
        self.assertFalse(hasattr(packet['state'].values['normalized_references'][0], 'frames'))
        self.assertIs(state.values['references'][0].frames, frames)
        self.assertIn('request_id', packet)

    def test_real_sampling_preserves_text_keyframe_and_mixed_reference_outputs(self):
        # Full denoiser workflow, real scheduler and six-block tiny H3 model.
        torch.manual_seed(19)
        model = tiny_model().eval()
        den = MiniMaxH3Blocks().sub_blocks['denoise']
        keys = {i.name for i in den.inputs if i.name} | set(den.block_trigger_inputs)
        pipe = den.init_pipeline()
        pipe.update_components(transformer=model, transformer_ref=model,
                               scheduler=MiniMaxH3Scheduler(), audio_scheduler=MiniMaxH3Scheduler())
        pipe.vae = SimpleNamespace(config=SimpleNamespace(latent_channels=4,clip_length=17), spatial_compression_ratio=16,tokens_chunk_size=5)
        pipe.audio_vae = SimpleNamespace(config=SimpleNamespace(latent_channels=4,sampling_rate=32000))
        image = Image.new('RGB',(32,32))
        frames = np.zeros((24,32,32,3), dtype=np.uint8)
        audio = torch.zeros(2,4000)
        for task in ['t2va','fl2va','ref2va']:
            with self.subTest(task=task):
                values = dict(prompt_embeds=torch.ones(1,2,8),text_token_tags=torch.ones(2,dtype=torch.long),
                              height=32,width=32,num_frames=124,num_inference_steps=3)
                if task=='fl2va':
                    values.update(image=image,last_image=image,keyframe_anchors=('first','last'),
                                  condition_latents=[torch.zeros(1,4,1,2,2),torch.zeros(1,4,1,2,2)])
                if task=='ref2va':
                    refs = [MiniMaxH3ImageReference(image), MiniMaxH3VideoReference(frames,24),
                            MiniMaxH3VideoReference(frames,24,audio,32000), MiniMaxH3AudioReference(audio,32000)]
                    values.update(references=refs,normalized_references=refs,
                                  condition_latents=[torch.zeros(1,4,1,2,2),torch.zeros(1,4,2,2,2),torch.zeros(1,4,2,2,2)],
                                  audio_condition_latents=[torch.zeros(4,4),torch.zeros(4,4)])
                results = []
                for compact in [False, True]:
                    state = PipelineState(); state.values = dict(values)
                    if compact:
                        state = denoiser_state(state, keys)
                        buf = io.BytesIO(); torch.save(state,buf)
                        state = torch.load(io.BytesIO(buf.getvalue()),weights_only=False)
                    with torch.no_grad():
                        out = pipe(state=state,generator=torch.Generator('cpu').manual_seed(7),output=['latents','audio_latents'])
                    results.append(out)
                for name in ['latents','audio_latents']:
                    torch.testing.assert_close(results[0][name],results[1][name],rtol=0,atol=0)


class DurableWorkerFailureTest(unittest.TestCase):
    def test_actual_request_exception_path_persists_oom_before_rank_exits(self):
        import ast
        from h3video import dworker
        tree=ast.parse(Path(dworker.__file__).read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_main')
        loop=next(n for n in main.body if isinstance(n,ast.While))
        start=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Try) and
                   any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='pipe' for x in ast.walk(n)))
        fragment=ast.fix_missing_locations(ast.Module(body=loop.body[start:],type_ignores=[]))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'H3_WORKER_DIAGNOSTICS':tmp}):
            def fail(**kwargs):raise RuntimeError('CUDA out of memory (test)')
            env=dict(__name__='h3video.dworker',__package__='h3video',pipe=fail,state=object(),gen=None,
                     job=dict(kwargs={},request_id='test'),out=None,rank=2,device='cpu',torch=torch,
                     stop=SimpleNamespace(set=lambda:None),th=None,record_failure=dworker.record_failure,
                     traceback=SimpleNamespace(print_exc=lambda:None))
            with self.assertRaisesRegex(RuntimeError,'out of memory'):
                exec(compile(fragment,dworker.__file__,'exec'),env)
            self.assertEqual(read_failures(tmp,'test')[0]['rank'],2)

    def test_rank_failure_survives_dead_connection_and_is_request_scoped(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'H3_WORKER_DIAGNOSTICS':tmp}):
            report = record_failure(RuntimeError('CUDA out of memory'), torch, 'cpu', 2, 'request1', '디노이징')
            self.assertEqual(report['kind'],'cuda')
            self.assertEqual(read_failures(tmp,'other'),[])
            e = Engine.__new__(Engine)
            e.mode='fsdp_cp';e._worker_diagnostics=Path(tmp);e._worker_request_id='request1'
            with self.assertRaises(GenerationMemoryError) as caught:
                e._check_worker_failure()
            self.assertEqual(caught.exception.report['workerReports'][0]['rank'],2)
            self.assertTrue(caught.exception.report['workerFailed'])
            self.assertEqual(caught.exception.report['allocatorScope'],'this_process')

    def test_torn_diagnostic_and_previous_request_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'request-rank0.tmp').write_text('{')
            (Path(tmp)/'request-rank1.json').write_text('{')
            write_failure(tmp,'older',0,dict(kind='cuda',error='old',stage='디노이징'))
            self.assertEqual(read_failures(tmp,'request'),[])
            with self.assertRaises(ValueError):write_failure(tmp,'../outside',0,{})

    def test_startup_failure_is_saved_without_starting_workers(self):
        from h3video import dworker
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'H3_WORKER_DIAGNOSTICS':tmp,'RANK':'0','LOCAL_RANK':'0'},clear=True), \
             patch.object(dworker,'_main',side_effect=RuntimeError('bad checkpoint')):
            with self.assertRaisesRegex(RuntimeError,'bad checkpoint'):dworker.main([])
            self.assertEqual(read_failures(tmp,'startup')[0]['kind'],'error')


class PreparationTest(unittest.TestCase):
    def test_actual_wrappers_reuse_decode_and_prompt_with_disk_backed_frames(self):
        e = Engine.__new__(Engine)
        prepared = RequestPreparation(memory_bytes=0);e._request_preparation=prepared
        original = np.arange(24*16*16*3,dtype=np.uint8).reshape(24,16,16,3)
        ref = MiniMaxH3VideoReference(original,24)
        inputs = dict(references=[ref],prompt='raw')
        e._load_inputs_uncached=Mock(return_value=(inputs,None))
        e._prepare_prompt_uncached=Mock(return_value='fixed prompt')
        try:
            for edge in [768,576]:
                decoded,_=e._load_inputs(dict(short_edge=edge))
                self.assertEqual(e._prepare_prompt({},decoded),'fixed prompt')
            self.assertEqual(e._load_inputs_uncached.call_count,1)
            self.assertEqual(e._prepare_prompt_uncached.call_count,1)
            self.assertIsInstance(ref.frames,np.memmap)
            np.testing.assert_array_equal(ref.frames,original)
            directory=prepared._temporary.name
        finally:prepared.close()
        self.assertFalse(Path(directory).exists())
        self.assertIsNone(prepared.inputs)


class RecoveryPolicyTest(unittest.TestCase):
    def test_failed_group_cleanup_keeps_original_oom_diagnostics(self):
        engine=Engine.__new__(Engine)
        engine.torch=SimpleNamespace();engine.devices=[];engine.mode='sharded'
        engine.stage='조건 인코딩';engine._te_pipe=None;engine.conditioning_offload='block'
        engine._run=Mock(side_effect=RuntimeError('CUDA out of memory (original)'))
        with patch('h3video.placement.release_conditioning_groups',side_effect=RuntimeError('cleanup failed')):
            with self.assertRaises(GenerationMemoryError) as caught:
                engine.run(dict(task='t2va',short_edge=768),None,None)
        self.assertIn('original',caught.exception.report['error'])
        self.assertEqual(caught.exception.report['cleanupError'],'cleanup failed')

    def test_unavailable_engine_does_not_accept_an_already_queued_request(self):
        engine=SimpleNamespace(run=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            server=Server(engine,Path(tmp),'ref2va')
            server.engine_status='unavailable';server.engine_error='worker restart failed'
            with self.assertRaisesRegex(RuntimeError,'worker restart failed'):
                server.run_with_recovery(dict(id='queued',plan={}),Path(tmp)/'out.mp4')
            engine.run.assert_not_called()

    def exercise(self, errors, edge=768):
        calls=[]
        e=SimpleNamespace(mode='fsdp_cp',conditioning_offload='component',_steps_done=0)
        def offload():e.conditioning_offload='block'
        e.enable_conditioning_offload=Mock(side_effect=offload)
        e.restart_denoiser_workers=Mock()
        def run(plan,out,progress):
            calls.append(dict(plan))
            if errors:raise errors.pop(0)
            out.write_bytes(b'video');return 'used'
        e.run=run
        with tempfile.TemporaryDirectory() as tmp:
            srv=Server(e,Path(tmp),'ref2va')
            job=dict(id='video_test',plan=dict(short_edge=edge,task='ref2va'),status='in_progress')
            error=None
            try:srv.run_with_recovery(job,Path(tmp)/'out.mp4')
            except Exception as caught:error=caught
        self.assertIsNone(e._request_preparation)
        return e,calls,job,error

    def memory_error(self,**extra):
        return GenerationMemoryError(RuntimeError('CUDA out of memory'),dict(kind='cuda',stage='디노이징',**extra))

    def test_text_oom_offloads_without_resizing_or_restarting_healthy_workers(self):
        error=GenerationMemoryError(RuntimeError('CUDA out of memory'),dict(kind='cuda',stage='조건 인코딩',component=dict(id='text_encoder',type='Qwen3VL')))
        e,calls,job,failure=self.exercise([error])
        self.assertIsNone(failure);self.assertEqual([p['short_edge'] for p in calls],[768,768])
        e.enable_conditioning_offload.assert_called_once();e.restart_denoiser_workers.assert_not_called()

    def test_worker_oom_resizes_and_only_restarts_workers(self):
        e,calls,job,failure=self.exercise([self.memory_error(workerFailed=True)])
        self.assertIsNone(failure);self.assertEqual([p['short_edge'] for p in calls],[768,576])
        e.restart_denoiser_workers.assert_called_once()

    def test_unknown_worker_death_retries_once_at_same_geometry(self):
        e,calls,job,failure=self.exercise([WorkerDied('worker gone'),WorkerDied('worker gone again')])
        self.assertIsInstance(failure,WorkerDied);self.assertEqual([p['short_edge'] for p in calls],[768,768])

    def test_host_oom_timeout_and_minimum_geometry_do_not_repeat(self):
        cases=[GenerationMemoryError(MemoryError('host OOM'),dict(kind='host',stage='입력 읽기')),
               WorkerTimeout('stalled'),self.memory_error()]
        for error in cases:
            with self.subTest(error=str(error)):
                e,calls,job,failure=self.exercise([error],edge=256)
                self.assertEqual(len(calls),1);self.assertIs(failure,error)


class DeadlineTest(unittest.TestCase):
    def test_worker_startup_wait_is_bounded_and_closes_owned_listener(self):
        import threading
        event=threading.Event()
        e=Engine.__new__(Engine)
        e._listener=SimpleNamespace(accept=lambda:event.wait(1))
        e._proc=SimpleNamespace(poll=lambda:None)
        e._stop_workers=Mock(side_effect=event.set)
        with patch.dict(os.environ,{'H3_WORKER_START_TIMEOUT':'.01'}):
            with self.assertRaises(WorkerTimeout):e._wait_workers()
        e._stop_workers.assert_called_once()

    def test_live_silent_worker_is_stopped_at_deadline(self):
        e=Engine.__new__(Engine);e._conn=SimpleNamespace(poll=lambda seconds:False)
        e._proc=SimpleNamespace(poll=lambda:None);e._stop_workers=Mock()
        with patch('h3video.dserver.time.monotonic',side_effect=[0,0,2]):
            with self.assertRaises(WorkerTimeout):e._recv(deadline=1)
        e._stop_workers.assert_called_once()

    def test_heartbeat_with_unchanged_step_does_not_extend_deadline(self):
        e=Engine.__new__(Engine);e._den_keys=set();e._conn=SimpleNamespace(send_bytes=lambda _:None)
        deadlines=[]
        def recv(deadline):
            deadlines.append(deadline)
            if len(deadlines)>3:raise WorkerTimeout('stalled')
            return b'PROG 0'
        e._recv=recv
        state=PipelineState()
        with patch.dict(os.environ,{'H3_DENOISE_STALL_TIMEOUT':'10','H3_DENOISE_TIMEOUT':'100'}), \
             patch('h3video.dserver.time.monotonic',side_effect=[0,1,4,7]):
            with self.assertRaises(WorkerTimeout):e._denoise_remote(state,torch.Generator('cpu'),{})
        self.assertEqual(deadlines,[10,10,10,10])


def tiny_qwen():
    from transformers import Qwen3VLConfig,Qwen3VLForConditionalGeneration
    config=Qwen3VLConfig(
        text_config=dict(vocab_size=64,hidden_size=32,intermediate_size=64,num_hidden_layers=2,
                         num_attention_heads=4,num_key_value_heads=2,head_dim=8,
                         rope_parameters=dict(rope_type='default',rope_theta=10000,mrope_section=[1,1,2])),
        vision_config=dict(depth=2,hidden_size=32,intermediate_size=64,num_heads=4,patch_size=2,
                           temporal_patch_size=2,spatial_merge_size=2,out_hidden_size=32,
                           num_position_embeddings=16,deepstack_visual_indexes=[0,1]),
        image_token_id=60,video_token_id=61,vision_start_token_id=62,vision_end_token_id=63)
    return Qwen3VLForConditionalGeneration(config).eval()


class ConditioningBlockTest(unittest.TestCase):
    def test_resident_component_calls_remain_visible_in_diagnostics(self):
        from diffusers.modular_pipelines.components_manager import custom_offload_with_hook
        from h3video.placement import record_component_calls
        model=tiny_qwen();events=[]
        hook=custom_offload_with_hook('text_encoder',model,torch.device('cpu'))
        try:
            record_component_calls(SimpleNamespace(model_hooks=[hook]),lambda *args:events.append(args))
            for _ in range(2):
                with torch.no_grad():model(input_ids=torch.tensor([[1,2]]),use_cache=False)
            self.assertEqual([event[0] for event in events],['text_encoder','text_encoder'])
        finally:hook.remove()

    def compare(self,device):
        from diffusers.hooks.group_offloading import _is_group_offload_enabled
        model=tiny_qwen();ids=torch.tensor([[1,2,3,4]],device=device)
        model.to(device)
        pixels=torch.randn(16,24,device=device)
        multimodal=dict(input_ids=torch.tensor([[1,62,60,60,60,60,63,2]],device=device),
                        pixel_values=pixels,image_grid_thw=torch.tensor([[1,4,4]],device=device),
                        mm_token_type_ids=torch.tensor([[0,0,1,1,1,1,0,0]],device=device),use_cache=False)
        with torch.no_grad():
            expected=model(input_ids=ids,use_cache=False).logits.cpu()
            visual_expected=model(**multimodal).logits.cpu()
            generated_expected=model.generate(input_ids=ids,max_new_tokens=2,do_sample=False).cpu()
        pipeline=SimpleNamespace(text_encoder=model)
        self.assertTrue(offload_conditioning_text(pipeline,device))
        self.assertTrue(_is_group_offload_enabled(model))
        self.assertFalse(offload_conditioning_text(pipeline,device))
        with torch.no_grad():
            actual=model(input_ids=ids,use_cache=False).logits.cpu()
            visual_actual=model(**multimodal).logits.cpu()
            generated_actual=model.generate(input_ids=ids,max_new_tokens=2,do_sample=False).cpu()
        torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
        torch.testing.assert_close(visual_actual,visual_expected,rtol=1e-5,atol=1e-6)
        torch.testing.assert_close(generated_actual,generated_expected,rtol=0,atol=0)
        # The real H3 conditioner calls .model with the outer custom pre-hook.
        with torch.no_grad():
            hidden=model.model(input_ids=ids,use_cache=False,output_hidden_states=True).hidden_states
        self.assertTrue(torch.isfinite(hidden[-1]).all())
        # Nested language blocks each have their own hooks, not one 32B group.
        for layer in model.model.language_model.layers:
            self.assertIsNotNone(getattr(layer,'_diffusers_hook',None))
        if str(device).startswith('cuda'):
            self.assertTrue(all(p.device.type=='cpu' for p in model.parameters()))
        return model

    def test_actual_small_qwen_forward_cpu(self):self.compare('cpu')

    @unittest.skipUnless(torch.cuda.is_available(),'Actual tiny CUDA offload test')
    def test_actual_small_qwen_forward_cuda(self):
        if torch.cuda.mem_get_info(0)[0]<512*2**20:self.skipTest('Leave occupied GPU alone')
        self.compare('cuda:0')

    @unittest.skipUnless(torch.cuda.is_available(),'Actual tiny CUDA cleanup test')
    def test_oom_inside_block_releases_weights_and_next_request_matches(self):
        from h3video.placement import release_conditioning_groups,ExclusiveStageOffload
        from diffusers.modular_pipelines.components_manager import custom_offload_with_hook
        if torch.cuda.mem_get_info(0)[0]<512*2**20:self.skipTest('Leave occupied GPU alone')
        model=tiny_qwen();pipeline=SimpleNamespace(text_encoder=model)
        hook=custom_offload_with_hook('text_encoder',model,torch.device('cuda:0'),ExclusiveStageOffload())
        try:
            offload_conditioning_text(pipeline,'cuda:0')
            ids=torch.tensor([[1,2,3]],device='cuda:0')
            with torch.no_grad():expected=model(input_ids=ids,use_cache=False).logits.cpu()
            handle=model.model.language_model.layers[0].register_forward_pre_hook(
                lambda *args: (_ for _ in ()).throw(RuntimeError('CUDA out of memory (synthetic block failure)')))
            try:
                with self.assertRaisesRegex(RuntimeError,'out of memory'):
                    with torch.no_grad():model(input_ids=ids,use_cache=False)
                self.assertTrue(any(p.device.type=='cuda' for p in model.parameters()))
                release_conditioning_groups(pipeline)
                self.assertTrue(all(p.device.type=='cpu' for p in model.parameters()))
            finally:handle.remove()
            with torch.no_grad():actual=model(input_ids=ids,use_cache=False).logits.cpu()
            torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
        finally:
            release_conditioning_groups(pipeline)
            hook.remove()


if __name__=='__main__':
    torch.set_num_threads(2)
    unittest.main()
