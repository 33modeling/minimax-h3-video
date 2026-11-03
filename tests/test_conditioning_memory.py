"""Actual Diffusers offload hooks under a simulated budget; no tensors/GPU/model load."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import torch
from diffusers.modular_pipelines import components_manager as cm
from h3video.placement import ExclusiveStageOffload
GIB=2**30

class Budget:
    def __init__(self):self.resident={};self.history=[]
    def free(self):return 80*GIB-sum(self.resident.values())

class BudgetModel(torch.nn.Module):
    def __init__(self,budget,name,weights,activation):
        super().__init__();self.budget=budget;self.name=name;self.weights=weights*GIB;self.activation=activation*GIB;self.where=torch.device('cpu')
    @property
    def device(self):return self.where
    def get_memory_footprint(self):return self.weights
    def to(self,device):
        self.where=torch.device(device)
        if self.where.type=='cuda':self.budget.resident[self.name]=self.weights
        else:self.budget.resident.pop(self.name,None)
        self.budget.history.append((self.name,str(self.where),tuple(self.budget.resident)))
        return self
    def forward(self):
        if self.budget.free()<self.activation:raise RuntimeError('CUDA out of memory (simulated activation budget)')
        return self.name+':same-output'

class ConditioningMemoryTest(unittest.TestCase):
    def models(self,strategy):
        budget=Budget();text=BudgetModel(budget,'text',60,3);vae=BudgetModel(budget,'vae',2,22)
        a=cm.custom_offload_with_hook('text_encoder',text,torch.device('cuda:0'),strategy)
        b=cm.custom_offload_with_hook('vae',vae,torch.device('cuda:0'),strategy)
        a.add_other_hook(b);b.add_other_hook(a)
        return budget,text,vae
    def test_old_auto_policy_can_keep_text_weights_when_vae_activations_do_not_fit(self):
        budget,text,vae=self.models(cm.AutoOffloadStrategy('12GB'))
        with patch.object(cm,'TorchDeviceBackend',return_value=SimpleNamespace(mem_get_info=lambda:(budget.free(),80*GIB))),patch.object(cm,'clear_device_cache'):
            self.assertEqual(text(),'text:same-output')
            with self.assertRaisesRegex(RuntimeError,'out of memory'):vae()
            self.assertEqual(set(budget.resident),{'text','vae'})
    def test_exclusive_policy_evicts_before_vae_and_reuses_same_component(self):
        transitions=[];budget,text,vae=self.models(ExclusiveStageOffload(lambda *args:transitions.append(args)))
        with patch.object(cm,'clear_device_cache'):
            self.assertEqual(text(),'text:same-output');n=len(budget.history)
            self.assertEqual(text(),'text:same-output');self.assertEqual(len(budget.history),n)
            self.assertEqual(vae(),'vae:same-output');self.assertEqual(set(budget.resident),{'vae'})
            self.assertEqual(text(),'text:same-output');self.assertEqual(set(budget.resident),{'text'})
            self.assertEqual([x[0]for x in transitions],['text_encoder','vae','text_encoder'])
    def test_oom_report_identifies_conditioning_component_without_stale_denoiser_label(self):
        from h3video.dserver import Engine
        from h3video.memory import GenerationMemoryError
        engine=Engine.__new__(Engine);engine._te_pipe=None;engine.devices=[];engine.torch=SimpleNamespace()
        engine.mode='fsdp_cp';engine.stage='조건 인코딩'
        engine._record_component('text_encoder','Qwen3VLForConditionalGeneration','cuda:0')
        def fail(*args):raise RuntimeError('CUDA out of memory (fixture)')
        engine._run=fail
        with self.assertRaises(GenerationMemoryError)as seen:
            engine.run({'short_edge':768,'task':'t2va'},None,None)
        self.assertEqual(seen.exception.report['component']['type'],'Qwen3VLForConditionalGeneration')
        self.assertEqual(seen.exception.report['executionMode'],'fsdp_cp')
        engine.stage='디노이징'
        with self.assertRaises(GenerationMemoryError)as seen:
            engine.run({'short_edge':768,'task':'t2va'},None,None)
        self.assertNotIn('component',seen.exception.report)

@unittest.skipUnless(torch.cuda.is_available(),'Actual CUDA required for tiny offload transition')
class ActualOffloadTransitionTest(unittest.TestCase):
    def test_real_cpu_gpu_eviction_preserves_outputs(self):
        if torch.cuda.mem_get_info(0)[0]<512*2**20:self.skipTest('Leave occupied GPU alone')
        class Model(torch.nn.Module):
            def __init__(self):super().__init__();self.linear=torch.nn.Linear(16,16)
            @property
            def device(self):return self.linear.weight.device
            def get_memory_footprint(self):return sum(p.numel()*p.element_size()for p in self.parameters())
            def forward(self,x):return self.linear(x).tanh()
        torch.manual_seed(12);text=Model().eval();vae=Model().eval();value=torch.randn(2,16)
        with torch.no_grad():expected_text=text(value);expected_vae=vae(value)
        transitions=[];strategy=ExclusiveStageOffload(lambda *args:transitions.append(args))
        a=cm.custom_offload_with_hook('text_encoder',text,torch.device('cuda:0'),strategy)
        b=cm.custom_offload_with_hook('vae',vae,torch.device('cuda:0'),strategy)
        a.add_other_hook(b);b.add_other_hook(a)
        try:
            with torch.no_grad():
                first=text(value);second=vae(value);third=vae(value)
            self.assertEqual(text.device.type,'cpu');self.assertEqual(vae.device.type,'cuda')
            self.assertEqual([x[0]for x in transitions],['text_encoder','vae'])
            torch.testing.assert_close(first.cpu(),expected_text,rtol=1e-5,atol=1e-6)
            torch.testing.assert_close(second.cpu(),expected_vae,rtol=1e-5,atol=1e-6)
            torch.testing.assert_close(third,second)
        finally:a.remove();b.remove();text.to('cpu');vae.to('cpu')

if __name__=='__main__':unittest.main()
