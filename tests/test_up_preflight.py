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
    def fixture(self, *, raw=False, converted=True, incomplete=False, engine='diffusers', reference=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        project = root / 'checkout'
        scripts = project / 'scripts'
        scripts.mkdir(parents=True)
        for name in ['up.sh','cluster_env.sh','check_diffusers_model.py']:
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
        venv = storage / ('.venv-diffusers' if engine=='diffusers' else '.venv')
        (venv / 'bin').mkdir(parents=True)
        fake_python = venv / 'bin/python'
        fake_python.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''\
            import os, subprocess, sys
            from pathlib import Path
            args = sys.argv[1:]
            with Path(os.environ['PREFLIGHT_TRACE']).open('a') as f:
                f.write(repr(args) + '\\n')
            if args and args[0].endswith('check_diffusers_model.py'):
                sys.exit(subprocess.call([os.environ['REAL_PYTHON'], *args]))
            if args and args[0].endswith('h3_leftovers.py'):
                if any(x.startswith('--kill') for x in args):
                    raise AssertionError('Preflight attempted process termination')
                sys.exit(0)
            if args and args[0].endswith('check_torchvision.py'):
                sys.exit(0)
            if args and args[0] == '-c':
                print('[fixture] simulated Python/CUDA import check; no GPU accessed')
                sys.exit(0)
            if args and args[0] == '-':
                code = sys.stdin.read()
                if 'socket.socket' in code:
                    # Report port free without creating or binding a socket.
                    sys.exit(1)
                if 'MemAvailable' in code:
                    print(1024)
                    sys.exit(0)
            raise AssertionError('Unexpected Python operation: ' + repr(args))
        '''))
        fake_python.chmod(0o755)
        (venv / 'bin/python3').symlink_to('python')
        fake_smi = venv / 'bin/nvidia-smi'
        fake_smi.write_text(textwrap.dedent('''\
            #!/bin/sh
            case "$*" in
              *--query-gpu*) printf '0, 0, 81920\\n1, 0, 81920\\n2, 0, 81920\\n3, 0, 81920\\n' ;;
              *) printf 'NVIDIA-SMI fixture; CUDA Version: 12.2\\n' ;;
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
        env.update(REAL_PYTHON=sys.executable,PREFLIGHT_TRACE=str(root/'trace.log'))
        return project, env, root

    def check(self, **kwargs):
        project, env, root = self.fixture(**kwargs)
        result = subprocess.run(['bash',str(project/'scripts/up.sh'),'--check']+(['--ref'] if kwargs.get('reference') else []),cwd=project,env=env,input='',capture_output=True,text=True,timeout=20)
        self.assertNotIn('== fl2va 시작', result.stdout)
        self.assertNotIn('unbound variable', result.stderr)
        return result, root

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

if __name__ == '__main__':
    unittest.main()
