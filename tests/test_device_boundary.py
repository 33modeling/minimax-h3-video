"""Exercise the CPU layout/CUDA denoising boundary, including actual CUDA when available."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import torch
from h3video.placement import transfer_denoiser_state


class StateBoundaryTest(unittest.TestCase):
    def test_fake_cuda_handoff_moves_encoded_data_but_keeps_cpu_tags(self):
        import torch._subclasses.fake_tensor as fake_tensor
        from torch._subclasses.fake_tensor import FakeTensorMode
        # Metadata-only CUDA:0 -> CUDA:1 routing; no GPU allocation or arithmetic.
        with patch.object(fake_tensor,'init_gpu_context',lambda device: None,create=True), FakeTensorMode():
            state=SimpleNamespace(values={"text_token_tags":torch.empty(2,dtype=torch.long),
                                          "prompt_embeds":torch.empty(1,2,8,device='cuda:0'),
                                          "condition_latents":[torch.empty(1,4,1,2,2,device='cuda:0')]},
                                  kwargs_mapping={})
            transfer_denoiser_state(state,'cuda:1',set(state.values))
            self.assertEqual(state.values['text_token_tags'].device.type,'cpu')
            self.assertEqual(str(state.values['prompt_embeds'].device),'cuda:1')
            self.assertEqual(str(state.values['condition_latents'][0].device),'cuda:1')

    def test_cpu_metadata_rng_and_kwargs_mapping_survive_filtered_transfer(self):
        tags = torch.ones(2,dtype=torch.long)
        index = torch.arange(3)
        state = SimpleNamespace(values={"text_token_tags":tags,"prompt_embeds":torch.zeros(1,2,8),
                                       "custom_index":index,"generator":object(),"original_pixels":object()},
                                kwargs_mapping={"denoiser_input_fields":["custom_index"]})
        transfer_denoiser_state(state,"cpu",{"text_token_tags","prompt_embeds","generator"})
        self.assertIs(state.values["text_token_tags"],tags)
        self.assertIs(state.values["custom_index"],index)
        self.assertNotIn("generator",state.values)
        self.assertNotIn("original_pixels",state.values)
        self.assertEqual(state.kwargs_mapping,{"denoiser_input_fields":["custom_index"]})


@unittest.skipUnless(torch.cuda.is_available(),"Requires actual CUDA; run separately from the CPU suite")
class CudaStateBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device = torch.device("cuda:0")
        free,_ = torch.cuda.mem_get_info(cls.device)
        if free < 512*2**20:
            raise unittest.SkipTest("Leave the occupied GPU alone: less than 512 MiB free")

    def test_old_transfer_reproduces_exact_device_mismatch_in_diffusers_layout(self):
        from diffusers.modular_pipelines.minimax_h3.before_denoise import MiniMaxH3PrepareLayoutStep
        from h3video.dworker import to_device
        tags = to_device(torch.ones(2,dtype=torch.long),self.device)
        with self.assertRaisesRegex(RuntimeError,"[Ee]xpected all tensors to be on the same device"):
            MiniMaxH3PrepareLayoutStep.build_packed_sequence(
                text_token_tags=tags,keyframe_anchors=(),num_latent_frames=2,
                latent_height=2,latent_width=2,num_audio_latents=2,patch_size=(1,2,2),
                audio_channels=2,audio_tag=2,video_tag=0)

    def test_gpu_tags_from_an_upstream_caller_are_normalized_to_cpu(self):
        state=SimpleNamespace(values={"text_token_tags":torch.ones(2,device=self.device,dtype=torch.long),
                                      "prompt_embeds":torch.ones(1,2,8,device=self.device)},kwargs_mapping={})
        transfer_denoiser_state(state,self.device,state.values.keys())
        self.assertEqual(state.values["text_token_tags"].device.type,"cpu")
        self.assertEqual(state.values["prompt_embeds"].device,self.device)

    def test_real_denoising_for_text_keyframe_and_reference_with_cpu_tags(self):
        from PIL import Image
        from accelerate import dispatch_model
        from diffusers import MiniMaxH3Scheduler
        from diffusers.modular_pipelines.minimax_h3.modular_blocks_minimax_h3 import MiniMaxH3Blocks
        from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3ImageReference
        from diffusers.modular_pipelines.modular_pipeline import PipelineState
        from test_placement import tiny_model
        model=tiny_model().eval().to(self.device)
        ref_model=tiny_model().eval().to(self.device)
        # Exercise real Accelerate model hooks without moving all weights again.
        mapping={name:str(self.device) for name,_ in model.named_children() if name!='transformer_blocks'}
        mapping.update({f'transformer_blocks.{i}':str(self.device) for i in range(len(model.transformer_blocks))})
        model=dispatch_model(model,device_map=mapping,force_hooks=True)
        ref_model=dispatch_model(ref_model,device_map=mapping,force_hooks=True)
        calls=[]
        model.register_forward_pre_hook(lambda *args: calls.append('base'))
        ref_model.register_forward_pre_hook(lambda *args: calls.append('reference'))
        den=MiniMaxH3Blocks().sub_blocks['denoise']
        pipe=den.init_pipeline()
        pipe.update_components(transformer=model,transformer_ref=ref_model,
                               scheduler=MiniMaxH3Scheduler(),audio_scheduler=MiniMaxH3Scheduler())
        pipe.vae=SimpleNamespace(config=SimpleNamespace(latent_channels=4,clip_length=17),
                                spatial_compression_ratio=16,tokens_chunk_size=5)
        pipe.audio_vae=SimpleNamespace(config=SimpleNamespace(latent_channels=4,sampling_rate=32000))
        keys={item.name for item in den.inputs if item.name}|set(den.block_trigger_inputs)
        image=Image.new('RGB',(32,32))
        for task in ['t2va','fl2va','ref2va']:
            with self.subTest(task=task):
                values=dict(prompt_embeds=torch.ones(1,2,8,device=self.device),
                            text_token_tags=torch.ones(2,dtype=torch.long),height=32,width=32,
                            num_frames=124,num_inference_steps=3)
                if task!='t2va':
                    values['condition_latents']=[torch.zeros(1,4,1,2,2,device=self.device)]
                if task=='fl2va':values.update(image=image,keyframe_anchors=('first',))
                if task=='ref2va':
                    refs=[MiniMaxH3ImageReference(image)]
                    values.update(references=refs,normalized_references=refs,audio_condition_latents=[])
                state=PipelineState()
                state.values=values
                transfer_denoiser_state(state,self.device,keys)
                calls.clear()
                out=pipe(state=state,generator=torch.Generator('cpu').manual_seed(4),
                         output=['latents','audio_latents'])
                self.assertEqual(calls,['reference' if task=='ref2va' else 'base']*2)
                self.assertTrue(torch.isfinite(out['latents']).all())
                self.assertTrue(torch.isfinite(out['audio_latents']).all())
                self.assertEqual(out['latents'].device,self.device)
                self.assertEqual(state.values['text_token_tags'].device.type,'cpu')
