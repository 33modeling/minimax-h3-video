"""Streaming shard geometry, mode dispatch and a tiny real FSDP forward (no sockets)."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import torch
from h3video.parallel import execution_mode,shard_slice,checkpoint_files,load_fsdp_transformer,require_fsdp_runtime
from test_placement import tiny_model

class ParallelPlanTest(unittest.TestCase):
    def test_runtime_preflight_needs_no_cuda_context(self):
        require_fsdp_runtime()

    def test_speed_is_compute_parallel_and_memory_is_layerwise(self):
        devices=['cuda:0','cuda:1','cuda:2','cuda:3']
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(execution_mode(devices),'fsdp_cp')
            self.assertEqual(execution_mode(devices,'memory'),'sharded')
            self.assertEqual(execution_mode(devices,'speed'),'fsdp_cp')
            self.assertEqual(execution_mode(devices,'speed','cp'),'cp')
            self.assertEqual(execution_mode(['cuda:0','cuda:1']),'split')
            with self.assertRaises(ValueError):execution_mode(devices,'invalid')
    def test_uneven_and_empty_shards_reconstruct_without_overlap(self):
        for rows in [1,2,4,7,56]:
            value=torch.arange(rows*3).reshape(rows,3)
            for world in [1,3,7]:
                slices=[value[shard_slice(value.shape,rank,world)] for rank in range(world)]
                torch.testing.assert_close(torch.cat(slices),value)
                self.assertEqual(sum(x.numel() for x in slices),value.numel())
    def test_local_checkpoint_rejects_duplicates_and_external_paths(self):
        from safetensors.torch import save_file
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save_file({'x':torch.ones(2)},root/'one.safetensors')
            self.assertEqual(set(checkpoint_files(root)),{'x'})
            save_file({'x':torch.ones(2)},root/'two.safetensors')
            with self.assertRaises(ValueError):checkpoint_files(root)
            (root/'weights.safetensors.index.json').write_text(json.dumps({'weight_map':{'x':'../outside.safetensors'}}))
            with self.assertRaises(ValueError):checkpoint_files(root)

@unittest.skipUnless(torch.cuda.is_available(),'tiny CUDA FSDP runtime requires actual CUDA')
class FSDPRuntimeTest(unittest.TestCase):
    def test_three_simulated_ranks_load_only_their_own_exact_weight_slices(self):
        import torch.distributed as dist
        import torch.testing._internal.distributed.fake_pg as fake
        from torch.distributed.tensor import DTensor
        if dist.is_initialized():self.skipTest('Existing distributed group')
        free,_=torch.cuda.mem_get_info(0)
        if free<512*2**20:self.skipTest('Leave occupied GPU alone')
        with tempfile.TemporaryDirectory() as tmp:
            original=tiny_model().eval().to(dtype=torch.bfloat16)
            for name,module in original.named_modules():
                if any(part in name.split('.') for part in original._keep_in_fp32_modules):module.float()
            original.save_pretrained(Path(tmp)/'transformer_ref')
            total=0
            for rank in range(3):
                dist.init_process_group('fake',store=fake.FakeStore(),rank=rank,world_size=3)
                try:
                    from diffusers import ContextParallelConfig
                    model,info=load_fsdp_transformer(tmp,'transformer_ref',torch.device('cuda',0),rank,3,torch.bfloat16,ContextParallelConfig(ulysses_degree=3,ulysses_anything=True))
                    for name,value in model.state_dict().items():
                        expected=original.state_dict()[name]
                        if isinstance(value,DTensor):
                            expected=expected[shard_slice(expected.shape,rank,3,value.placements[0].dim)]
                            actual=value.to_local()
                        else:actual=value
                        torch.testing.assert_close(actual.cpu(),expected,rtol=0,atol=0)
                    total+=info['localWeightBytes']
                    del model
                finally:dist.destroy_process_group()
            self.assertEqual(total,sum(p.numel()*p.element_size()for p in original.parameters()))
        # Fake collectives validate local checkpoint slices only, never 3-GPU output or timing.

    def test_streamed_mixed_precision_checkpoint_matches_nonsharded_model(self):
        import torch.distributed as dist
        import torch.testing._internal.distributed.fake_pg as fake
        # A single rank uses an in-memory fake store; no TCP rendezvous or service.
        if dist.is_initialized():self.skipTest('Leave another distributed test group alone')
        free,_=torch.cuda.mem_get_info(0)
        if free<512*2**20:self.skipTest('Leave occupied GPU alone')
        dist.init_process_group('fake',store=fake.FakeStore(),rank=0,world_size=1)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                model=tiny_model().eval().to(dtype=torch.bfloat16)
                for name,module in model.named_modules():
                    if any(part in name.split('.') for part in model._keep_in_fp32_modules):module.float()
                model.save_pretrained(Path(tmp)/'transformer')
                loaded,info=load_fsdp_transformer(tmp,'transformer',torch.device('cuda',0),0,1,torch.bfloat16)
                model=model.to('cuda')
                torch.manual_seed(7)
                args=dict(hidden_states=torch.randn(1,3,16,device='cuda'),audio_hidden_states=torch.randn(1,2,4,device='cuda'),
                    encoder_hidden_states=torch.randn(1,2,8,device='cuda'),timestep=torch.tensor([.5],device='cuda'),
                    timestep_indices=torch.zeros(7,dtype=torch.long,device='cuda'),token_tags=torch.tensor([1,1,0,0,0,2,2],device='cuda'),
                    position_ids=torch.zeros(7,3,device='cuda'),video_indices=torch.tensor([2,3,4],device='cuda'),
                    audio_indices=torch.tensor([5,6],device='cuda'),text_indices=torch.tensor([0,1],device='cuda'))
                with torch.no_grad():expected=model(**args);actual=loaded(**args)
                torch.testing.assert_close(actual.sample,expected.sample,rtol=.01,atol=.01)
                torch.testing.assert_close(actual.audio_sample,expected.audio_sample,rtol=.01,atol=.01)
                self.assertEqual(loaded.proj_in.weight.dtype,torch.float32)
                self.assertEqual(info['weightCopies'],1)
                self.assertFalse(info['cpuWeightReplication'])
        finally:dist.destroy_process_group()

    def test_real_h3_sampling_for_text_keyframe_and_reference(self):
        import torch.distributed as dist
        import torch.testing._internal.distributed.fake_pg as fake
        from types import SimpleNamespace
        from PIL import Image
        from diffusers import MiniMaxH3Scheduler
        from diffusers.modular_pipelines.minimax_h3.modular_blocks_minimax_h3 import MiniMaxH3Blocks
        from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3ImageReference
        from diffusers.modular_pipelines.modular_pipeline import PipelineState
        from h3video.placement import transfer_denoiser_state
        if dist.is_initialized():self.skipTest('Existing distributed group')
        if torch.cuda.mem_get_info(0)[0]<512*2**20:self.skipTest('Leave occupied GPU alone')
        dist.init_process_group('fake',store=fake.FakeStore(),rank=0,world_size=1)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                base=tiny_model().eval();base.save_pretrained(Path(tmp)/'transformer')
                model,_=load_fsdp_transformer(tmp,'transformer',torch.device('cuda',0),0,1,torch.float32)
                den=MiniMaxH3Blocks().sub_blocks['denoise'];pipe=den.init_pipeline()
                pipe.update_components(transformer=model,transformer_ref=model,scheduler=MiniMaxH3Scheduler(),audio_scheduler=MiniMaxH3Scheduler())
                pipe.vae=SimpleNamespace(config=SimpleNamespace(latent_channels=4,clip_length=17),spatial_compression_ratio=16,tokens_chunk_size=5)
                pipe.audio_vae=SimpleNamespace(config=SimpleNamespace(latent_channels=4,sampling_rate=32000))
                keys={item.name for item in den.inputs if item.name}|set(den.block_trigger_inputs)
                image=Image.new('RGB',(32,32))
                for task in ['t2va','fl2va','ref2va']:
                    with self.subTest(task=task):
                        values=dict(prompt_embeds=torch.ones(1,2,8,device='cuda'),text_token_tags=torch.ones(2,dtype=torch.long),height=32,width=32,num_frames=124,num_inference_steps=3)
                        if task!='t2va':values['condition_latents']=[torch.zeros(1,4,1,2,2,device='cuda')]
                        if task=='fl2va':values.update(image=image,keyframe_anchors=('first',))
                        if task=='ref2va':
                            refs=[MiniMaxH3ImageReference(image)];values.update(references=refs,normalized_references=refs,audio_condition_latents=[])
                        state=PipelineState();state.values=values
                        transfer_denoiser_state(state,torch.device('cuda',0),keys)
                        out=pipe(state=state,generator=torch.Generator('cpu').manual_seed(4),output=['latents','audio_latents'])
                        self.assertTrue(torch.isfinite(out['latents']).all());self.assertTrue(torch.isfinite(out['audio_latents']).all())
                        self.assertEqual(state.values['text_token_tags'].device.type,'cpu')
        finally:dist.destroy_process_group()

if __name__=='__main__':unittest.main()
