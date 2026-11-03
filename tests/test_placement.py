import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch
from diffusers import MiniMaxH3Transformer3DModel
from h3video.placement import weight_placement, load_sharded_transformer, request_reference_geometry
from h3video.memory import GenerationMemoryError
from h3video.dserver import Server


def tiny_model():
    return MiniMaxH3Transformer3DModel(
        num_attention_heads=2, attention_head_dim=16, hidden_size=32, num_layers=6,
        num_refiner_layers=1, ffn_dim=64, in_channels=4, audio_in_channels=4,
        text_dim=8, freq_dim=8, time_embed_hidden_dim=32, time_embed_dim=16, rope_freq_dim=2)


class PlacementTest(unittest.TestCase):
    def test_one_copy_and_contiguous_blocks_on_selected_gpus_only(self):
        with torch.device("meta"):
            model = tiny_model()
        devices = ["cuda:5", "cuda:6", "cuda:7"]
        mapping, weights = weight_placement(model, devices)
        self.assertEqual(set(mapping.values()), set(devices))
        self.assertNotIn("",mapping,"A root assignment would temporarily load the full model on one GPU")
        self.assertEqual(mapping["proj_in"], "cuda:5")
        self.assertEqual([mapping[f"transformer_blocks.{i}"] for i in range(6)],
                         sorted([mapping[f"transformer_blocks.{i}"] for i in range(6)]))
        # The total must equal one checkpoint, never the number of GPUs times it.
        expected = sum(p.numel() * (4 if any(k in name for k in model._keep_in_fp32_modules) else 2)
                       for name, p in model.named_parameters())
        self.assertEqual(sum(weights.values()), expected)
        self.assertTrue(all(size < expected for size in weights.values()))
        for bad in [[], ["cuda:1", "cuda:1"], [f"cuda:{i}" for i in range(7)]]:
            with self.assertRaises(ValueError): weight_placement(model, bad)

    def test_loader_uses_local_weights_explicit_map_and_no_full_gpu_to(self):
        model = tiny_model()
        recorded = {}
        def load(*args, **kwargs):
            recorded.update(kwargs)
            parameters = []
            for name, parameter in model.named_parameters():
                key = next(key for key in sorted(kwargs["device_map"], key=len, reverse=True)
                           if name.startswith(key + "."))
                parameters.append((name, SimpleNamespace(device=kwargs["device_map"][key],
                                                         numel=parameter.numel, element_size=parameter.element_size)))
            return SimpleNamespace(hf_device_map=kwargs["device_map"],named_parameters=lambda: iter(parameters))
        with tempfile.TemporaryDirectory() as root:
            model.save_config(Path(root)/"transformer_ref")
            with patch.object(MiniMaxH3Transformer3DModel, "from_pretrained", side_effect=load), \
                 patch.object(torch.cuda, "mem_get_info", return_value=(79*2**30, 80*2**30)):
                _, info = load_sharded_transformer(root, "transformer_ref", ["cuda:1", "cuda:2", "cuda:3"], torch.bfloat16, torch)
        self.assertEqual(info["copies"], 1)
        self.assertTrue(recorded["local_files_only"])
        self.assertTrue(recorded["low_cpu_mem_usage"])
        self.assertEqual(set(recorded["device_map"].values()), {"cuda:1", "cuda:2", "cuda:3"})

    def test_real_checkpoint_explicit_dispatch_matches_original_forward(self):
        # Actual Diffusers loader/Accelerate dispatch and real H3 forward; CPU only.
        model = tiny_model().eval()
        torch.manual_seed(4)
        args = dict(hidden_states=torch.randn(1, 3, 16), audio_hidden_states=torch.randn(1, 2, 4),
                    encoder_hidden_states=torch.randn(1, 2, 8), timestep=torch.tensor([.5]),
                    timestep_indices=torch.zeros(7, dtype=torch.long), token_tags=torch.tensor([1,1,0,0,0,2,2]),
                    position_ids=torch.zeros(7,3), video_indices=torch.tensor([2,3,4]),
                    audio_indices=torch.tensor([5,6]), text_indices=torch.tensor([0,1]))
        with torch.no_grad(): expected = model(**args)
        with tempfile.TemporaryDirectory() as root:
            model.save_pretrained(root)
            mapping, _ = weight_placement(model, ["cuda:1", "cuda:2", "cuda:3"], 4)
            mapping = {name: "cpu" for name in mapping}
            loaded = MiniMaxH3Transformer3DModel.from_pretrained(root, device_map=mapping, local_files_only=True)
            from accelerate import dispatch_model
            loaded = dispatch_model(loaded,device_map=mapping,force_hooks=True)
            self.assertFalse(loaded._hf_hook.place_submodules)
            with torch.no_grad(): actual = loaded(**args)
        torch.testing.assert_close(expected.sample, actual.sample, rtol=0, atol=0)
        torch.testing.assert_close(expected.audio_sample, actual.audio_sample, rtol=0, atol=0)


class ReferenceGeometryTest(unittest.TestCase):
    def test_actual_diffusers_reference_resize_follows_request_size(self):
        import numpy as np
        from PIL import Image
        from diffusers.modular_pipelines.minimax_h3.before_encoder import MiniMaxH3Ref2VASetupStep
        from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3ImageReference, MiniMaxH3VideoReference
        pipeline = MiniMaxH3Ref2VASetupStep().init_pipeline()
        image = Image.new("RGB", (640,480))
        frames = np.zeros((2,80,120,3),dtype=np.uint8)
        references = [MiniMaxH3ImageReference(image), MiniMaxH3VideoReference(frames, fps=24)]
        shapes = []
        for edge in (768,576,448):
            with request_reference_geometry(pipeline,edge):
                out = pipeline(references=references,num_frames=124,height=edge,width=edge*2,
                               output=["normalized_references"])["normalized_references"]
                shapes.append((out[0].image.size,out[1].frames.shape))
                self.assertEqual(min(out[0].image.size),edge)
                self.assertEqual(min(out[1].frames.shape[1:3]),edge)
            self.assertEqual(pipeline.config.reference_image_short_edge,2048)
        self.assertEqual(image.size,(640,480))
        self.assertEqual(frames.shape,(2,80,120,3))
        self.assertGreater(shapes[0][0][0],shapes[-1][0][0])

    def test_size_controls_both_references_and_restores_after_failure(self):
        class Pipeline:
            def __init__(self):
                self.config = SimpleNamespace(canvas_short_edge=768, canvas_max_pixels=768*1344, reference_image_short_edge=2048)
            def register_to_config(self, **values):
                for key, value in values.items(): setattr(self.config,key,value)
        pipe = Pipeline()
        for edge in [768, 576, 448, 256]:
            with self.assertRaises(RuntimeError):
                with request_reference_geometry(pipe, edge):
                    self.assertEqual(pipe.config.reference_image_short_edge, edge)
                    self.assertEqual(pipe.config.canvas_short_edge, edge)
                    self.assertLessEqual(pipe.config.canvas_max_pixels, 768*1344)
                    raise RuntimeError("CUDA out of memory")
            self.assertEqual(pipe.config.reference_image_short_edge, 2048)
            self.assertEqual(pipe.config.canvas_short_edge, 768)

    def test_sharded_oom_retries_without_reloading_weights_and_retains_report(self):
        calls = []
        class Engine:
            mode = "sharded"
            def run(self, plan, out, on_progress):
                calls.append(plan["short_edge"])
                if len(calls) == 1:
                    raise GenerationMemoryError(RuntimeError("CUDA out of memory"), {"kind":"cuda","stage":"조건 인코딩"})
                out.write_bytes(b"ok")
                return "prompt"
        with tempfile.TemporaryDirectory() as root:
            server = Server(Engine(), Path(root), "ref2va")
            job = {"id":"video_test","plan":{"short_edge":768},"status":"in_progress"}
            with patch.object(server, "reload_engine", side_effect=AssertionError("must not allocate another model")):
                server.run_with_recovery(job, Path(root)/"out.mp4")
            self.assertEqual(calls, [768,576])
            self.assertEqual(job["memory_failure"]["stage"], "조건 인코딩")
            self.assertEqual(json.loads(server.meta_path(job["id"]).read_text())["recovery"]["short_edge"],576)

    def test_host_oom_does_not_repeat_meaningless_smaller_gpu_requests(self):
        calls = []
        class Engine:
            def run(self, *args):
                calls.append(1)
                raise GenerationMemoryError(MemoryError("malloc failed"), {"kind":"host","stage":"입력 읽기"})
        with tempfile.TemporaryDirectory() as root:
            server = Server(Engine(), Path(root), "ref2va")
            with self.assertRaises(GenerationMemoryError):
                server.run_with_recovery({"id":"test","plan":{"short_edge":448}},Path(root)/"out.mp4")
        self.assertEqual(len(calls),1)
