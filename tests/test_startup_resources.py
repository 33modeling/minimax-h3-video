"""Resource policy checks with supplied inventory; no GPU, model, socket or service."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

p = Path(__file__).resolve().parents[1] / 'scripts/check_startup_resources.py'
spec = importlib.util.spec_from_file_location('startup_resources', p)
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)

class ResourcesTest(unittest.TestCase):
    def check(self, count=8, total=81920, **kwargs):
        rows='\n'.join(f'{i}, 0, {total}' for i in range(count))
        return resources.validate(rows, available_ram=kwargs.pop('ram',512), minimum_ram=kwargs.pop('required_ram',280), **kwargs)

    def test_eight_h100_cards_accept_four_plus_four(self):
        self.assertEqual(self.check(gpus='0,1,2,3',ref_gpus='4,5,6,7'), [])

    def test_explicit_two_plus_two_is_rejected(self):
        self.assertTrue(self.check(gpus='0,1',ref_gpus='2,3'))

    def test_four_cards_do_not_start_two_variants(self):
        self.assertTrue(self.check(count=4))

    def test_one_node_can_run_reference_only(self):
        self.assertEqual(self.check(count=4,fl2va=False,ref_gpus='0,1,2,3',required_ram=140), [])

    def test_duplicate_or_overlapping_or_unknown_ids_are_rejected(self):
        for options in [dict(gpus='0,0,1,2'),dict(gpus='0,1,2,3',ref_gpus='3,4,5,6'),dict(ref_gpus='4,5,6,8')]:
            with self.subTest(options=options):self.assertTrue(self.check(**options))

    def test_low_vram_auto_assignment_is_rejected(self):
        self.assertTrue(self.check(total=40960))

    def test_explicit_group_cannot_reserve_every_gpu_from_other_variant(self):
        self.assertTrue(self.check(gpus='0,1,2,3,4,5,6,7'))

    def test_insufficient_cpu_ram_is_rejected(self):
        self.assertTrue(self.check(ram=200))

    def test_stale_two_device_or_disabled_cp_is_rejected(self):
        self.assertTrue(self.check(cp=False))
        self.assertTrue(self.check(device_override='cuda:0,cuda:1'))

    def test_direct_reference_engine_rejects_two_devices_before_importing_torch(self):
        from h3video.dserver import Engine
        with tempfile.TemporaryDirectory() as model:
            with self.assertRaisesRegex(ValueError, '최소 GPU 4장'):
                Engine(model,'ref2va',['cuda:0','cuda:1'])

if __name__ == '__main__':unittest.main()
