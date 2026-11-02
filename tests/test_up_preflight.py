"""Execute the real up.sh checks with a fake GPU/Python boundary; no sockets or services.

These tests measure only launcher control flow, never model correctness or GPU readiness.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]

class StartupPreflightTest(unittest.TestCase):
    def fixture(self, *, raw=False, converted=True, incomplete=False, engine='diffusers', reference=True, engine_option=True, driver='12.2', gpu_count=8, ram_gib=1024, gpu_rows=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        project = root / 'checkout'
        scripts = project / 'scripts'
        scripts.mkdir(parents=True)
        for name in ['up.sh','provision.sh','cluster_env.sh','check_diffusers_model.py','check_startup_resources.py']:
            shutil.copy2(ROOT / 'scripts' / name, scripts / name)
        group = root / 'group'
        storage = group / 'another-user' / 'h3'
        models = group / 'models'
        model = models / 'MiniMax-H3'
        if raw:
            model.mkdir(parents=True)
            (model / 'model_index.json').write_text('{}')
        converted_dir = root / 'separate-converted-model'
        if converted:
            converted_dir.mkdir()
            (converted_dir / 'modular_model_index.json').write_text('{}')
            for component in ['text_encoder','tokenizer','processor','vae','audio_vae','scheduler','audio_scheduler','transformer'] + (['transformer_ref'] if reference else []):
                part = converted_dir / component
                part.mkdir()
                (part / 'config.json').write_text('{}')
                if component in ['text_encoder','vae','audio_vae','transformer','transformer_ref']:
                    (part / 'fixture.safetensors').write_bytes(b'CONTROL-FLOW-FIXTURE-NOT-WEIGHTS')
            if incomplete:
                (converted_dir / 'transformer/fixture.safetensors').unlink()
        selected=engine if engine_option else 'diffusers'
        venv = storage / ('.venv-diffusers' if selected=='diffusers' else '.venv')
        (venv / 'bin').mkdir(parents=True)
        fake_python = venv / 'bin/python'
        fake_python.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''\
            import os, subprocess, sys
            from pathlib import Path
            args = sys.argv[1:]
            with Path(os.environ['PREFLIGHT_TRACE']).open('a') as f:
                f.write(repr(args) + '\\n')
            if args and args[0].endswith(('check_diffusers_model.py', 'check_startup_resources.py')):
                sys.exit(subprocess.call([os.environ['REAL_PYTHON'], *args]))
            if args and args[0].endswith('h3_leftovers.py'):
                if any(x.startswith('--kill') for x in args):
                    raise AssertionError('Preflight attempted process termination')
                sys.exit(0)
            if args and args[0].endswith('check_torchvision.py'):
                sys.exit(1 if os.environ.get('MOCK_NMS_FAIL') else 0)
            if args and args[0] == '-c':
                print('[fixture] simulated Python/CUDA import check; no GPU accessed')
                sys.exit(0)
            if args and args[0] == '-':
                code = sys.stdin.read()
                if 'socket.socket' in code:
                    # Report port free without creating or binding a socket.
                    sys.exit(1)
                if 'MemAvailable' in code:
                    print(os.environ.get('MOCK_RAM_GIB', '1024'))
                    sys.exit(0)
            raise AssertionError('Unexpected Python operation: ' + repr(args))
        '''))
        fake_python.chmod(0o755)
        (venv / 'bin/python3').symlink_to('python')
        pip=venv/'bin/pip'
        pip.write_text('#!/bin/sh\nprintf "PIP %s\\n" "$*" >> "$PREFLIGHT_TRACE"\n')
        pip.chmod(0o755)
        guides=storage/'h3-guides'
        guides.mkdir()
        for kind in ['base','ref']:(guides/f'VIDEO_PROMPT_WRITING_GUIDE_{kind}_en.md').write_text('fixture')
        fake_smi = venv / 'bin/nvidia-smi'
        fake_smi.write_text(textwrap.dedent('''\
            #!/bin/sh
            case "$*" in
              *--query-gpu*) if [ -n "$MOCK_GPU_ROWS" ]; then printf '%s\\n' "$MOCK_GPU_ROWS"; exit 0; fi; i=0; while [ "$i" -lt "$MOCK_GPU_COUNT" ]; do printf '%s, 0, 81920\\n' "$i"; i=$((i + 1)); done ;;
              *) printf 'NVIDIA-SMI fixture; CUDA Version: %s\\n' "$MOCK_DRIVER" ;;
            esac
        '''))
        fake_smi.chmod(0o755)
        (venv/'bin/sglang').write_text('#!/bin/sh\nexit 0\n')
        (venv/'bin/sglang').chmod(0o755)
        config = {
            'GROUP_VOLUME_ROOT': group, 'STORAGE_ROOT': storage,
            'MODELS_DIR': models, 'H3_MODEL_DIR': model,
            'H3_DIFFUSERS_DIR': converted_dir, 'H3_ENGINE': engine,
        }
        (project / '.cluster_env.local.sh').write_text(''.join(f'export {k}={str(v)!r}\n' for k,v in config.items()))
        env = {k:v for k,v in os.environ.items() if not k.startswith(('H3_','HF_','TRANSFORMERS_','STORAGE_ROOT','WORK_ROOT','MODELS_DIR','GROUP_VOLUME_ROOT','VENV'))}
        env.update(REAL_PYTHON=sys.executable,PREFLIGHT_TRACE=str(root/'trace.log'),MOCK_DRIVER=driver,MOCK_GPU_COUNT=str(gpu_count),MOCK_RAM_GIB=str(ram_gib),MOCK_GPU_ROWS=gpu_rows or '')
        return project, env, root

    def check(self, **kwargs):
        with_ref=kwargs.pop('with_ref', True)
        fl2va_only=kwargs.pop('fl2va_only', False)
        ref_only=kwargs.pop('ref_only', False)
        extra=kwargs.pop('extra', [])
        project, env, root = self.fixture(**kwargs)
        flags=(['--engine',kwargs.get('engine','diffusers')] if kwargs.get('engine_option',True) else [])+(['--ref'] if with_ref else [])+(['--fl2va-only'] if fl2va_only else [])+(['--ref-only'] if ref_only else [])+extra
        result = subprocess.run(['bash',str(project/'scripts/up.sh'),'--check',*flags],cwd=project,env=env,input='',capture_output=True,text=True,timeout=20)
        self.assertNotIn('== fl2va 시작', result.stdout)
        self.assertNotIn('unbound variable', result.stderr)
        return result, root

    def test_ref_startup_checks_both_variants_and_assigns_four_each(self):
        result, root = self.check(engine_option=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Diffusers 형식 가중치(fl2va)', result.stdout)
        self.assertIn('Diffusers 형식 가중치(ref2va)', result.stdout)
        self.assertIn('fl2va GPU 0,1,2,3', result.stdout)
        self.assertIn('ref2va GPU 4,5,6,7', result.stdout)

    def test_plain_startup_uses_all_four_gpus_without_reference_weights(self):
        result, root = self.check(with_ref=False, reference=False, gpu_count=4, ram_gib=200)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fl2va GPU 0,1,2,3', result.stdout)
        self.assertNotIn('ref2va GPU', result.stdout)
        self.assertNotIn('Diffusers 형식 가중치(ref2va)', result.stdout)
        self.assertIn('시작 검사 기준 140GiB', result.stdout)

    def test_plain_startup_automatically_uses_all_eight_gpus(self):
        result, root = self.check(with_ref=False, reference=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fl2va GPU 0,1,2,3,4,5,6,7', result.stdout)
        self.assertNotIn('ref2va GPU', result.stdout)

    def test_ref_automatically_uses_available_nonconsecutive_gpu_ids(self):
        rows = '\n'.join(f'{i}, 0, 81920' for i in [2,4,6,8,10,12,14,16])
        result, root = self.check(gpu_rows=rows)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fl2va GPU 2,4,6,8', result.stdout)
        self.assertIn('ref2va GPU 10,12,14,16', result.stdout)

    def test_plain_startup_skips_gpus_busy_with_other_work(self):
        rows = '\n'.join(f'{i}, {4096 if i < 4 else 0}, 81920' for i in range(8))
        result, root = self.check(with_ref=False, reference=False, gpu_rows=rows)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fl2va GPU 4,5,6,7', result.stdout)

    def test_ref_never_silently_falls_back_to_two_plus_two_when_gpus_are_busy(self):
        rows = '\n'.join(f'{i}, {4096 if i < 4 else 0}, 81920' for i in range(8))
        result, root = self.check(gpu_rows=rows)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('ref2va GPU 6,7', result.stdout)
        self.assertNotIn('== ref2va 시작', result.stdout)

    def test_four_gpu_dual_mode_is_rejected_before_any_cleanup(self):
        result, root = self.check(gpu_count=4)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('2+2 자동 분할은 중단', result.stdout)
        self.assertNotIn('h3_leftovers.py', (root/'trace.log').read_text())

    def test_explicit_two_plus_two_is_rejected_even_on_an_eight_gpu_node(self):
        result, root = self.check(extra=['--gpus','0,1','--ref-gpus','2,3'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('최소 4장', result.stdout)
        self.assertNotIn('h3_leftovers.py', (root/'trace.log').read_text())

    def test_insufficient_cpu_ram_aborts_before_cleanup(self):
        result, root = self.check(ram_gib=200)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CPU RAM 여유 200GiB', result.stdout)
        self.assertNotIn('h3_leftovers.py', (root/'trace.log').read_text())

    def test_reference_only_uses_one_four_gpu_node(self):
        result, root = self.check(gpu_count=4, ref_only=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('ref2va GPU 0,1,2,3',result.stdout)
        self.assertNotIn('Diffusers 형식 가중치(fl2va)',result.stdout)

    def test_ref_startup_blocks_missing_reference_weights(self):
        result, root = self.check(reference=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Diffusers 형식 가중치(ref2va)가 아직 없다', result.stdout)

    def test_explicit_fl2va_only_accepts_base_weights_and_all_four_gpus(self):
        result, root = self.check(reference=False, fl2va_only=True, gpu_count=4)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fl2va GPU 0,1,2,3', result.stdout)
        self.assertNotIn('Diffusers 형식 가중치(ref2va)', result.stdout)

    def test_provision_default_prepares_both_variants(self):
        project, env, root = self.fixture()
        result=subprocess.run(['bash',str(project/'scripts/provision.sh')],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('fl2va ref2va 준비됨',result.stdout)
        self.assertIn('기본 실행: bash scripts/up.sh (GPU 자동 배정)',result.stdout)
        self.assertIn('bash scripts/up.sh --ref (빈 GPU 8장을 4+4로 자동 배정)',result.stdout)
        trace=(root/'trace.log').read_text()
        self.assertIn("'ref2va'",trace)

    def test_provision_explicit_base_only_does_not_require_reference_weights(self):
        project, env, root = self.fixture(reference=False)
        result=subprocess.run(['bash',str(project/'scripts/provision.sh'),'--fl2va-only'],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('fl2va 준비됨',result.stdout)
        self.assertIn('기본 실행: bash scripts/up.sh (GPU 자동 배정)',result.stdout)
        self.assertNotIn('참고 자료도 사용할 때:',result.stdout)
        self.assertNotIn("'ref2va'",(root/'trace.log').read_text())

    def test_complete_converted_model_does_not_require_an_original_checkpoint(self):
        result, root = self.check(raw=False, converted=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('점검 통과', result.stdout)

    def test_incomplete_converted_model_still_blocks_startup(self):
        result, root = self.check(raw=True, converted=True, incomplete=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('transformer/*.safetensors', result.stdout)

    def test_absent_converted_model_still_blocks_startup(self):
        result, root = self.check(raw=True, converted=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Diffusers 형식 가중치(fl2va)가 아직 없다', result.stdout)

    def test_reference_workflow_accepts_both_complete_converted_checkpoints(self):
        result, root = self.check(raw=False, converted=True, reference=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Diffusers 형식 가중치(ref2va)', result.stdout)

    def test_sglang_still_requires_original_checkpoint(self):
        result, root = self.check(raw=False, converted=False, engine='sglang')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('모델 없음', result.stdout)

    def test_cuda_13_does_not_automatically_select_sglang(self):
        result,root=self.check(raw=False,driver='13.0',engine_option=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('engine=diffusers',result.stdout)
        self.assertNotIn('engine=sglang',result.stdout)

    def test_stale_sglang_configuration_does_not_override_default_launcher(self):
        result,root=self.check(raw=False,driver='13.0',engine='sglang',engine_option=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('engine=diffusers',result.stdout)

    def test_provision_defaults_to_diffusers_and_checks_native_operators(self):
        project,env,root=self.fixture(engine='sglang',engine_option=False,driver='13.0')
        result=subprocess.run(['bash',str(project/'scripts/provision.sh'),'--skip-model'],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('선택한 엔진: diffusers',result.stdout)
        trace=(root/'trace.log').read_text()
        self.assertIn('--install-diffusers-stack',trace)
        self.assertGreaterEqual(trace.count('check_torchvision.py'),2)
        self.assertNotIn('.[serve,dev]',trace)

    def test_provision_does_not_report_success_when_native_cuda_check_fails(self):
        project,env,root=self.fixture()
        env['MOCK_NMS_FAIL']='1'
        result=subprocess.run(['bash',str(project/'scripts/provision.sh'),'--skip-model'],env=env,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('검사 실패',result.stdout)
        self.assertNotIn('모델 단계 스킵',result.stdout)

    def test_provision_sglang_requires_explicit_option(self):
        project,env,root=self.fixture(engine='sglang',driver='13.0',raw=True)
        result=subprocess.run(['bash',str(project/'scripts/provision.sh'),'--engine','sglang','--skip-model'],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('선택한 엔진: sglang',result.stdout)
        self.assertIn('.[serve,dev]',(root/'trace.log').read_text())

    def test_web_engine_option_preserves_local_port_and_cors_defaults(self):
        project,env,root=self.fixture()
        config=project/'.cluster_env.local.sh'
        with config.open('a') as out:
            out.write('export H3_WEB_PORT=8888 H3_CORS_ORIGIN=https://example.test\n')
        source=(ROOT/'scripts/web.sh').read_text()
        preamble=source.split('# 전에 띄운 웹 UI',1)[0]
        script=project/'scripts/web-preamble.sh'
        script.write_text(preamble+'\nprintf "RESULT %s %s %s\\n" "$PORT" "$CORS" "$H3_ENGINE"\n')
        result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('RESULT 8888 https://example.test diffusers',result.stdout)
        result=subprocess.run(['bash',str(script),'--port','9999','--cors',''],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('RESULT 9999  diffusers',result.stdout)

if __name__ == '__main__':
    unittest.main()
