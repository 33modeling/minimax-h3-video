"""Execute the checked-in CLI without a pip console script or any service."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CLILauncherTest(unittest.TestCase):
    def test_cluster_environment_exposes_repository_launcher_without_pip_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder);repo=tmp/'repo';(repo/'scripts').mkdir(parents=True)
            shutil.copyfile(ROOT/'scripts/cluster_env.sh',repo/'scripts/cluster_env.sh')
            (repo/'h3video').symlink_to(ROOT/'h3video')
            model=tmp/'models/MiniMax-H3';model.mkdir(parents=True)
            (model/'modular_model_index.json').write_text('{}')
            env=self.env(tmp);env['MODELS_DIR']=str(tmp/'models');env['GROUP_VOLUME_ROOT']=str(tmp)
            result=subprocess.run(['bash','-c','source "$1/scripts/cluster_env.sh" >/dev/null && command -v h3video && h3video gen --help','check',str(repo)],
                cwd=tmp,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(str(repo/'h3video'),result.stdout)
            self.assertIn('h3video gen',result.stdout)

    def env(self,tmp):
        return dict(os.environ,HOME=str(tmp),XDG_CONFIG_HOME=str(tmp/'config'),
                    STORAGE_ROOT=str(tmp/'storage'),VENV=str(tmp/'missing'),
                    H3_DIFFUSERS_VENV='',H3_VENV='',H3_CLI_PYTHON='',PYTHONPATH='')

    def test_missing_venv_console_script_still_runs_help_from_another_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder);result=subprocess.run([str(ROOT/'h3video'),'gen','--help'],cwd=tmp,
                env=self.env(tmp),text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('h3video gen',result.stdout)

    def test_symlink_spaces_and_generation_dry_run_preserve_arguments(self):
        with tempfile.TemporaryDirectory(prefix='H3 CLI ') as folder:
            tmp=Path(folder);link=tmp/'h3video';link.symlink_to(ROOT/'h3video')
            result=subprocess.run([str(link),'gen','한글과 공백이 있는 프롬프트','--dry-run','--json'],
                cwd=tmp,env=self.env(tmp),text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(result.stdout)
            self.assertIn('한글과 공백이 있는 프롬프트',json.dumps(data,ensure_ascii=False))

    def test_explicit_python_does_not_silently_use_another_interpreter(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder);env=self.env(tmp);env['H3_CLI_PYTHON']=str(tmp/'not-installed')
            result=subprocess.run([str(ROOT/'h3video'),'--help'],cwd=tmp,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,127)
            self.assertIn('H3_CLI_PYTHON',result.stderr)

    def test_existing_venv_python_is_used_without_console_entry_point(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder);venv=tmp/'venv';(venv/'bin').mkdir(parents=True)
            python=venv/'bin/python';python.write_text('#!/bin/sh\nprintf "selected-venv:%s\\n" "$*"\n');python.chmod(0o755)
            env=self.env(tmp);env['VENV']=str(venv)
            result=subprocess.run([str(ROOT/'h3video'),'gen','hello world','--dry-run'],cwd=tmp,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('selected-venv:-m h3video.cli gen hello world --dry-run',result.stdout)
            self.assertFalse((venv/'bin/h3video').exists())
